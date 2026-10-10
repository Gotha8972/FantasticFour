"""The agent workflow as a LangGraph state machine.

    setup → audit → plan ─┬─► execute → judge ─┬─► plan (re-plan with results)
                          └─► report            ├─► propose_fix → approve_fix ─┬─► apply_fix → plan / report
                                                └─► report                     └─► skip_fix  → plan / report

Same agents and deterministic safety code as `python3 -m chaosmind.agents`; LangGraph adds
  • a human approval gate before any fix touches the cluster (interrupt; --auto-approve to skip),
  • checkpointing: an interrupted run resumes from its last finished step (--resume runs/agents-…),
  • the workflow diagram exported from the real graph (--draw).
Model-agnostic: nodes call chaosmind/agents/llm.py (NVIDIA NIM, gpt-oss-20b by default; NIM_MODEL to swap), no LangChain.

.venv/bin/python -m chaosmind.graph --dry-run
.venv/bin/python -m chaosmind.graph --budget 3 --remediate
.venv/bin/python -m chaosmind.graph --resume runs/agents-20261011T101500Z
.venv/bin/python -m chaosmind.graph --draw
"""
import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from chaosmind.agents import steps


class RunState(TypedDict, total=False):
    out_dir: str
    budget: int
    dry_run: bool
    remediate: bool
    auto_approve: bool
    allow_unverified: bool
    workloads: str | None
    baseline_path: str
    baseline: dict
    facts: dict
    audit: dict
    plan: dict
    plan_round: int
    current: dict
    history: list
    fix_choice: dict | None
    approved: bool
    stop_reason: str | None


def approve_fix(state):
    """Human gate. Nothing before interrupt() in this node, because a resumed node restarts from the top."""
    choice = state['fix_choice']
    if choice.get('fix_id') == 'none':
        return {'approved': False}
    if state.get('auto_approve'):
        return {'approved': True}
    exp = state['history'][-1]['experiment']
    answer = interrupt({'question': f"Apply fix '{choice['fix_id']}' to {exp['target']} and re-run {exp['id']}?",
                        'reason': choice.get('reason', ''), 'expected_effect': choice.get('expected_effect', '')})
    return {'approved': str(answer).strip().lower() in ('y', 'yes')}


def build():
    g = StateGraph(RunState)
    for name in ('setup', 'audit', 'plan', 'execute', 'judge', 'propose_fix', 'apply_fix', 'report'):
        g.add_node(name, getattr(steps, name))
    g.add_node('approve_fix', approve_fix)
    g.add_node('skip_fix', lambda s: steps.skip_fix(s, 'no_fix' if (s.get('fix_choice') or {}).get('fix_id') == 'none'
                                                   else 'not_approved'))
    g.add_edge(START, 'setup')
    g.add_edge('setup', 'audit')
    g.add_edge('audit', 'plan')
    g.add_conditional_edges('plan', steps.after_plan, ['execute', 'report'])
    g.add_edge('execute', 'judge')
    g.add_conditional_edges('judge', steps.after_judge, ['plan', 'propose_fix', 'report'])
    g.add_edge('propose_fix', 'approve_fix')
    g.add_conditional_edges('approve_fix', lambda s: 'apply_fix' if s.get('approved') else 'skip_fix',
                            ['apply_fix', 'skip_fix'])
    g.add_conditional_edges('apply_fix', steps.after_fix, ['plan', 'report'])
    g.add_conditional_edges('skip_fix', steps.after_fix, ['plan', 'report'])
    g.add_edge('report', END)
    return g


def drive(app, config, first_input: Any, ask=input):
    """Run until the graph finishes, answering approval interrupts on the terminal."""
    payload = first_input
    while True:
        result = app.invoke(payload, config)
        pending = result.get('__interrupt__') if isinstance(result, dict) else None
        if not pending:
            return result
        info = pending[0].value
        print(f"\n⏸  {info['question']}\n   Why: {info['reason']}\n   Expected: {info['expected_effect']}")
        payload = Command(resume=ask('   Approve? [y/N] '))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--budget', type=int, default=4)
    parser.add_argument('--baseline', default='baseline.json')
    parser.add_argument('--workloads', help='saved deployments JSON instead of the live cluster')
    parser.add_argument('--dry-run', action='store_true', help='audit + plan + safety review; injects nothing')
    parser.add_argument('--remediate', action='store_true', help='propose a catalog fix for confirmed weaknesses')
    parser.add_argument('--auto-approve', action='store_true', help='apply proposed fixes without asking (recorded runs)')
    parser.add_argument('--allow-unverified', action='store_true', help='let the AI use fault types not yet proven live')
    parser.add_argument('--resume', help='continue an interrupted run from its last finished step')
    parser.add_argument('--draw', action='store_true', help='print the workflow as a Mermaid diagram and exit')
    args = parser.parse_args()

    if args.draw:
        print(build().compile().get_graph().draw_mermaid())
        return
    out = Path(args.resume) if args.resume else Path('runs') / f"agents-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    out.mkdir(parents=True, exist_ok=bool(args.resume))
    config = {'configurable': {'thread_id': str(out)}}
    with SqliteSaver.from_conn_string(str(out / 'checkpoints.sqlite')) as saver:
        app = build().compile(checkpointer=saver)
        if args.resume:
            if not app.get_state(config).next:
                print(f'{out} has nothing left to resume.')
                return
            print(f'Resuming {out} at: {", ".join(app.get_state(config).next)}')
            drive(app, config, None)
        else:
            print(f'Artifacts: {out}')
            drive(app, config, {'out_dir': str(out), 'budget': args.budget, 'dry_run': args.dry_run,
                                'remediate': args.remediate, 'auto_approve': args.auto_approve,
                                'allow_unverified': args.allow_unverified, 'workloads': args.workloads,
                                'baseline_path': args.baseline})


if __name__ == '__main__':
    main()
