"""The steps of one agent run, shared by the LangGraph workflow (chaosmind/graph.py) and the plain fallback loop
(python3 -m chaosmind.agents). Each step takes the run state (a JSON-friendly dict) and returns only the keys it
changes. Anything that isn't JSON (HTTP sessions, open files) lives and dies inside a single step, so the state can
be checkpointed and resumed.
"""
import json
from pathlib import Path

from chaosmind import inject
from chaosmind.agents import analyst, cartographer, facts as facts_mod, integrity, remediation, safety, score, strategist

STOP_EVENTS = {'NOT_RECOVERED', 'REVERT_FAILED', 'INTERRUPTED'}


def save(state, name, data):
    (Path(state['out_dir']) / name).write_text(json.dumps(data, indent=1))


def load_baseline(path):
    candidates = [Path(path)] + sorted(Path('runs').glob('baseline-study-*/baseline.json'), reverse=True)
    for p in candidates:
        if p.exists():
            b = json.loads(p.read_text())
            # Failed/preflight-only runs must never stand in for measurements.
            if b.get('status') != 'completed' or not b.get('metrics') or not b.get('window'):
                if p == Path(path) and Path(path).exists():
                    raise SystemExit(f'Baseline {p} has no completed measurement window')
                continue
            return {'source': str(p), 'metrics': b['metrics'], 'window': b['window'],
                    'baseline_suitable': b.get('baseline_suitable'),
                    'findings': b.get('findings', []), 'notes': b.get('notes', [])}
    raise SystemExit('No completed baseline found: run bash scripts/baseline.sh first')


def _health():
    from chaosmind.monitor import snapshot  # imported at call time: tests patch it, offline runs never need it
    return snapshot()


# ── steps ────────────────────────────────────────────────────────────────────

def setup(state):
    wl = state.get('workloads')
    f = facts_mod.collect(json.loads(Path(wl).read_text()) if wl else None)
    save(state, 'facts.json', f)
    return {'baseline': load_baseline(state['baseline_path']), 'facts': f, 'history': [], 'plan_round': 0,
            'stop_reason': None}


def audit(state):
    a = cartographer.audit(state['facts'])
    save(state, 'vulnerabilities.json', a)
    print(f"Cartographer: {len(a['vulnerabilities'])} vulnerabilities ({len(a['rejected'])} rejected for unverifiable evidence)")
    for v in a['vulnerabilities']:
        print(f"  {v['id']} [{v['severity']}] {v['service']}: {v['weakness']}")
    return {'audit': a}


def plan(state):
    allowed = set(inject.KINDS) if state.get('allow_unverified') else set(inject.LIVE_VERIFIED)
    remaining = state['budget'] - len(state['history'])
    p = strategist.plan(state['audit']['vulnerabilities'], state['baseline'], state['history'], remaining, allowed)
    n = state['plan_round'] + 1
    save(state, f'plan-{n}.json', p)
    if n > 1:
        print(f"Strategist re-plan: {p.get('replan_note', '')}")
    return {'plan': p, 'plan_round': n}


def execute(state):
    item = state['plan']['plan'][0]
    exp = item['experiment']
    baseline = state['baseline']
    print(f"\nStrategist → {exp['id']}: {item.get('reason', '')}")
    if state.get('dry_run'):
        health = {'note': 'offline'} if state.get('workloads') else _health()
        result = {**safety.review(exp, health, baseline), 'steps': [], 'health_at_review': health}
        return {'current': {'item': item, 'result': result, 'observed': None, 'integrity': []}}
    health = _health()
    base_users = ((baseline.get('metrics') or {}).get('users') or {}).get('mean')
    if base_users and health.get('users') and abs(health['users'] - base_users) > 0.1 * base_users:
        print(f"⚠ Load differs from the baseline ({health['users']} vs {base_users:.0f} shoppers); "
              "results won't be comparable. Re-run the baseline at this load.")
    check = integrity.prepare()  # silent-failure check: set up before the fault
    result = {**safety.run(exp, health, baseline), 'health_at_review': health}
    violations = integrity.verify(check) if result['steps'] else []
    obs = next((s['observed'] for s in reversed(result['steps']) if s['observed']), None)
    if obs is not None:
        obs = {**obs, 'integrity_violations': len(violations)}
    return {'current': {'item': item, 'result': result, 'observed': obs, 'integrity': violations}}


def judge(state):
    cur = state['current']
    item, result, obs, violations = cur['item'], cur['result'], cur['observed'], cur['integrity']
    verdict, met = strategist.evaluate(item['criteria'], obs)
    if verdict == 'needs_integrity_check' and violations:
        verdict = 'confirmed'
    s = score.score(obs, state['baseline'], (obs or {}).get('recovery_s'), violations) if obs else None
    print(f"Safety Checker: {result['decision']} ({result['reason']}); ramp={result.get('ramp')}; "
          f"tolerated up to={result.get('tolerated_up_to')}, guard limit crossed at={result.get('limit_crossed_at')}; "
          f"integrity violations={len(violations)} → {verdict}" + (f", score {s['score']}" if s else ''))
    entry = {'vulnerability': item.get('vulnerability'), 'experiment': item['experiment'], 'criteria': item['criteria'],
             'prediction': item.get('prediction'), 'safety': result, 'observed': obs, 'integrity': violations,
             'verdict': verdict, 'criteria_met': met, 'score': s}
    audit = {**state['audit'], 'vulnerabilities': [
        {**v, 'status': verdict} if v['id'] == item.get('vulnerability') and verdict in ('confirmed', 'refuted') else v
        for v in state['audit']['vulnerabilities']]}
    history = state['history'] + [entry]
    stopped = [st.get('stopped_by') for st in result.get('steps', []) if st.get('stopped_by') in STOP_EVENTS]
    save(state, 'history.json', history)
    save(state, 'vulnerabilities.json', audit)
    if stopped:
        print(f'Stopping: {stopped[-1]}. Cleanup or recovery needs a human before any further experiment.')
    return {'history': history, 'audit': audit, 'stop_reason': stopped[-1] if stopped else None}


def propose_fix(state):
    choice = remediation.choose(state['history'][-1])
    print(f"Remediation proposes: {choice.get('fix_id')} ({choice.get('reason', '')})")
    return {'fix_choice': choice}


def apply_fix(state):
    """Runs only after approval. Applies the catalog fix and re-runs the identical experiment."""
    history = list(state['history'])
    entry = history[-1]
    try:
        r = remediation.execute(entry, state['fix_choice'], state['baseline'])
        print(f"Remediation: {r['fix']} → score {r.get('before')} → {r.get('after')} ({r['verdict']})")
    except Exception as error:  # a failed fix must not stop the run; the guard already restored the fault
        r = {'verdict': 'error', 'reason': str(error), 'choice': state['fix_choice']}
    history[-1] = {**entry, 'remediation': r}
    save(state, 'history.json', history)
    return {'history': history, 'fix_choice': None}


def skip_fix(state, reason):
    history = list(state['history'])
    history[-1] = {**history[-1], 'remediation': {'verdict': reason, 'choice': state.get('fix_choice')}}
    save(state, 'history.json', history)
    return {'history': history, 'fix_choice': None}


def report(state):
    h = state.get('history', [])
    if h and not state.get('dry_run'):
        try:
            print(f"Analyst report: {analyst.write(state['out_dir'])}")
        except Exception as error:
            print(f"Analyst failed ({error}); raw results are in {state['out_dir']}/history.json")
    print(f"\nDone. {sum(x['verdict'] == 'confirmed' for x in h)} confirmed, "
          f"{sum(x['verdict'] == 'refuted' for x in h)} refuted. See {state['out_dir']}")
    return {}


# ── routing (shared by the graph and the loop) ──────────────────────────────

def after_plan(state):
    return 'execute' if state['plan']['plan'] and len(state['history']) < state['budget'] else 'report'


def after_judge(state):
    last = state['history'][-1]
    if state.get('stop_reason') or state.get('dry_run'):
        return 'report'
    if state.get('remediate') and last['verdict'] == 'confirmed':
        return 'propose_fix'
    return 'plan' if len(state['history']) < state['budget'] else 'report'


def after_fix(state):
    return 'plan' if len(state['history']) < state['budget'] and not state.get('stop_reason') else 'report'
