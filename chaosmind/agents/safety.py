"""④ Safety Checker: approve / shrink / reject, then inject via the guard with a gradual intensity ramp.

The AI may only make an experiment SMALLER (enforced in code). Injection always goes through
guard.run(), so validation and auto-revert stay deterministic and can't be loosened.
"""
import json

from chaosmind import guard, inject
from chaosmind.agents import llm

STEP_DURATION_S = 30
MAX_STEPS = 4
STOP_EVENTS = {'REFUSED', 'ERROR', 'NOT_RECOVERED', 'REVERT_FAILED', 'INTERRUPTED'}

SYSTEM = """You are the Safety Checker for a chaos-engineering system running in a local sandbox.
Given a proposed experiment, the current health snapshot and the baseline, decide:
- "reject" if the system is not healthy now, or the experiment risks more than the one target service;
- "shrink" if it is too long or too intense (you may ONLY lower duration_s or the intensity value);
- "approve" otherwise.
Never change fault or target. Never increase anything.
Note: pod_kill is a one-shot kill (Kubernetes recreates the pod at once). duration_s is only the observation window,
not how long the service is down; judge its risk by what the service does, not by the duration.
Also propose "ramp": ascending intensity steps ending at the (possibly shrunk) intensity, at most 4 steps,
each at most 2x the previous. Use plain numbers (milliseconds for latency, percent for loss/load).
Return JSON: {"decision": "approve|shrink|reject", "reason": "...", "experiment": {...}, "ramp": [numbers]}"""


def intensity(exp):
    if exp['fault'] not in inject.INTENSITY:
        return None
    key, default = inject.INTENSITY[exp['fault']]
    value = exp.get('params', {}).get(key, default)
    return float(value[:-2]) if isinstance(value, str) else float(value)


def with_intensity(exp, value):
    key, _ = inject.INTENSITY[exp['fault']]
    value = f'{int(value)}ms' if exp['fault'] == 'network_delay' else int(value)
    return {**exp, 'params': {**exp.get('params', {}), key: value}}


def only_smaller(original, proposed):
    if (proposed.get('fault'), proposed.get('target')) != (original['fault'], original['target']):
        return False
    if proposed.get('duration_s', 0) > original['duration_s']:
        return False
    try:
        inject.validate({**proposed, 'id': original['id']})
    except ValueError:
        return False
    return intensity(original) is None or intensity(proposed) <= intensity(original)


def default_ramp(top):
    # Start low (1/8): at 20 shoppers even 500 ms on the catalog already crosses the 1,000 ms p95 limit.
    steps = [top / 8, top / 4, top / 2, top]
    return [s for s in steps if s >= 1]


def clean_ramp(ramp, top):
    try:
        ramp = [float(r) for r in ramp]
    except (TypeError, ValueError):
        return default_ramp(top)
    ok = (0 < len(ramp) <= MAX_STEPS and ramp[-1] <= top and all(r > 0 for r in ramp)
          and all(b > a and b <= 2 * a for a, b in zip(ramp, ramp[1:])))
    return ramp if ok else default_ramp(top)


# Counters accumulated since the load generator started: they still carry failures from earlier experiments,
# so they say nothing about health *now*. (Both agents in the bake-off wrongly read 98.9% cumulative checkout
# success as "degraded".) Recent-window metrics (error_rate, p95_ms, rps, unhealthy_services) stay.
CUMULATIVE = ('checkout_success', 'checkout_requests', 'checkout_failures', 'requests', 'failures')


def current_health(snapshot):
    return {k: v for k, v in (snapshot or {}).items() if k not in CUMULATIVE}


def review(exp, snapshot, baseline):
    reply = llm.ask(SYSTEM, {'experiment': exp, 'current_health': current_health(snapshot), 'baseline': baseline})
    decision = reply.get('decision')
    proposed = reply.get('experiment') if isinstance(reply.get('experiment'), dict) else exp
    if decision not in ('approve', 'shrink', 'reject'):
        return {'decision': 'reject', 'reason': f'invalid decision {decision!r}', 'experiment': exp, 'ramp': []}
    if decision != 'reject' and not only_smaller(exp, {**exp, **proposed}):
        return {'decision': 'reject', 'reason': 'agent tried to enlarge or alter the experiment',
                'experiment': exp, 'ramp': []}
    final = {**exp, **proposed, 'id': exp['id']}
    top = intensity(final)
    ramp = [] if decision == 'reject' else ([None] if top is None else clean_ramp(reply.get('ramp'), top))
    return {'decision': decision, 'reason': reply.get('reason', ''), 'experiment': final, 'ramp': ramp}


def observed(events):
    """Worst metrics seen while the fault was active (None if nothing was measured), plus separate recovery
    timings, all in seconds from confirmed injection:
      service_ready_s     the target stopped appearing as unhealthy (capacity back)
      customer_recovered_s  HEALTHY: health AND customer metrics back within limits
    They differ: a killed catalog pod was Ready in ~3 s while customers were affected for ~30 s more."""
    active = [e for e in events if e['event'] == 'SNAPSHOT' and e.get('stage') in ('injecting', 'injected')]
    if not active:
        return None
    # Impact window = injection until recovery: the worst moments often come right after the revert
    # (e.g. cart service restarting), so recovery snapshots count too.
    snaps = active + [e for e in events if e['event'] == 'SNAPSHOT' and e.get('stage') == 'recovery']
    t0 = next((e.get('t', 0) for e in events if e['event'] == 'INJECTED'), active[0].get('t', 0))
    target = next((e.get('target') for e in events if e.get('target')), None)
    seen_down, service_ready = False, None
    for e in (e for e in events if e['event'] == 'SNAPSHOT' and e.get('t', 0) >= t0):
        if target in e['unhealthy_services']:
            seen_down = True
        elif seen_down:
            service_ready = round(e.get('t', 0) - t0, 1)
            break
    healthy = next((e for e in events if e['event'] == 'HEALTHY'), None)
    return {'error_rate': max(e['error_rate'] for e in snaps),
            'p95_ms': max(e['p95_ms'] for e in snaps),
            'unhealthy_count': max(len(e['unhealthy_services']) for e in snaps),
            'breach': next(({k: e[k] for k in ('metric', 'value', 'limit')} for e in events if e['event'] == 'BREACH'), None),
            'recovery_s': healthy['recovery_s'] if healthy else None,
            'service_ready_s': service_ready,
            'customer_recovered_s': round(healthy['t'] - t0, 1) if healthy and 't' in healthy else None,
            'users': snaps[0].get('users')}


def run(exp, snapshot, baseline, guard_run=guard.run):
    verdict = review(exp, snapshot, baseline)
    # tolerated_up_to: highest step that stayed inside the guard limits.
    # limit_crossed_at: first step where the guard tripped. "Crossed our safety limit", not "the system died".
    result = {**verdict, 'steps': [], 'tolerated_up_to': None, 'limit_crossed_at': None, 'status': verdict['decision']}
    if verdict['decision'] == 'reject':
        return result
    final = verdict['experiment']
    for n, level in enumerate(verdict['ramp'], 1):
        step = final if level is None else with_intensity(final, level)
        step = {**step, 'id': f"{final['id']}-s{n}"[:63], 'duration_s': min(final['duration_s'], STEP_DURATION_S)}
        events = guard_run(step)
        stop = next((e['event'] for e in events if e['event'] in STOP_EVENTS), None)
        result['steps'].append({'intensity': level, 'run_dir': next((e.get('artifact_dir') for e in events), None),
                                'observed': observed(events), 'stopped_by': stop})
        if stop:
            result['status'] = f'aborted: {stop}'
            break
        if result['steps'][-1]['observed'] and result['steps'][-1]['observed']['breach']:
            result['limit_crossed_at'] = level  # guard already reverted; don't go higher
            if n == 1:
                result['status'] = 'crossed limit at the lowest step; no tolerated level found, try a lower start'
            break
        result['tolerated_up_to'] = level
    return result


if __name__ == '__main__':
    import argparse
    from chaosmind.monitor import snapshot
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('experiment', help='experiment JSON file')
    parser.add_argument('--baseline', default='baseline.json')
    parser.add_argument('--review-only', action='store_true', help='decide and plan the ramp, inject nothing')
    args = parser.parse_args()
    exp = json.load(open(args.experiment))
    base = json.load(open(args.baseline))
    print(json.dumps(review(exp, snapshot(), base) if args.review_only else run(exp, snapshot(), base), indent=1))
