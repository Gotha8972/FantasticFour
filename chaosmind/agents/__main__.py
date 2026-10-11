"""Dependency-free fallback: runs the same steps and routing as the LangGraph workflow (chaosmind/graph.py),
without checkpoint/resume. Prefer `.venv/bin/python -m chaosmind.graph …` when LangGraph is installed.

python3 -m chaosmind.agents --dry-run
python3 -m chaosmind.agents --budget 3 --remediate [--auto-approve]
"""
import argparse
from datetime import datetime, timezone
from pathlib import Path

from chaosmind import app
from chaosmind.agents import integrity, safety, steps  # noqa: F401  (re-exported for tests that patch them)


def run(state, ask=input):
    state.update(steps.setup(state))
    state.update(steps.audit(state))
    node = 'plan'
    while node != 'report':
        if node == 'plan':
            state.update(steps.plan(state))
            node = steps.after_plan(state)
        elif node == 'execute':
            state.update(steps.execute(state))
            state.update(steps.judge(state))
            node = steps.after_judge(state)
        elif node == 'propose_fix':
            state.update(steps.propose_fix(state))
            choice = state['fix_choice']
            if choice.get('fix_id') == 'none':
                state.update(steps.skip_fix(state, 'no_fix'))
            elif state.get('auto_approve') or ask(f"Apply fix '{choice['fix_id']}'? [y/N] ").strip().lower() in ('y', 'yes'):
                state.update(steps.apply_fix(state))
            else:
                state.update(steps.skip_fix(state, 'not_approved'))
            node = steps.after_fix(state)
    steps.report(state)
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--budget', type=int, default=4, help='max experiments (default 4)')
    parser.add_argument('--baseline', default=str(app.BASELINE.relative_to(app.ROOT)))
    parser.add_argument('--workloads', help='saved deployments JSON instead of the live cluster')
    parser.add_argument('--dry-run', action='store_true', help='no injection')
    parser.add_argument('--remediate', action='store_true', help='propose a catalog fix for confirmed weaknesses')
    parser.add_argument('--auto-approve', action='store_true', help='apply proposed fixes without asking')
    parser.add_argument('--allow-unverified', action='store_true',
                        help='let the AI use fault types that have not run live yet (default: only proven ones)')
    args = parser.parse_args()
    out = Path('runs') / f"agents-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    out.mkdir(parents=True)
    print(f'Artifacts: {out}')
    run({'out_dir': str(out), 'budget': args.budget, 'dry_run': args.dry_run, 'remediate': args.remediate,
         'auto_approve': args.auto_approve, 'allow_unverified': args.allow_unverified,
         'workloads': args.workloads, 'baseline_path': args.baseline})


if __name__ == '__main__':
    main()
