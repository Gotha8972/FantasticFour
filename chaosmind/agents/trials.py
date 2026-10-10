"""Repeat one experiment N times under the same conditions and measure how often customers are hurt.

python3 -m chaosmind.agents.trials run experiments/catalog-podkill.json --repeat 5
python3 -m chaosmind.agents.trials summary        # every trial so far, grouped by comparable conditions

Result: "customer threshold breached in X of N comparable trials", with a 95% Wilson interval.
This is a measured likelihood under one fault, load and configuration; it is not a production outage probability.
Trials with failed injection, missing telemetry or no recovery are kept but marked invalid, never counted as passes.
"""
import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import time

from chaosmind import guard, inject
from chaosmind.agents import integrity, safety, strategist

# Customer thresholds, defined before testing (the same limits the guard protects).
CUSTOMER_CRITERIA = [{'metric': 'error_rate', 'op': '>', 'value': 0.05},
                     {'metric': 'p95_ms', 'op': '>', 'value': 1000},
                     {'metric': 'integrity_violations', 'op': '>', 'value': 0}]
INVALID = {'REFUSED', 'ERROR', 'NOT_RECOVERED', 'REVERT_FAILED', 'INTERRUPTED'}


def wilson(k, n, z=1.96):
    """95% Wilson score interval for k successes in n trials (sound for small n, unlike p ± 1.96·se)."""
    if n == 0:
        return None
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return round(max(0.0, centre - half), 3), round(min(1.0, centre + half), 3)


def conditions(exp, users):
    """What must match for trials to be comparable."""
    replicas = json.loads(inject.kubectl('get', 'deployment', exp['target'], '-n', inject.NS, '-o', 'json'))['spec'].get('replicas', 1)
    return {'fault': exp['fault'], 'target': exp['target'], 'params': exp.get('params', {}),
            'duration_s': exp['duration_s'], 'users': users, 'target_replicas': replicas}


def one_trial(exp, n, guard_run=guard.run):
    state = integrity.prepare()
    events = guard_run({**exp, 'id': f"{exp['id']}-t{n}"[:63]})
    problem = next((e['event'] for e in events if e['event'] in INVALID), None)
    obs = safety.observed(events)
    violations = integrity.verify(state) if obs else []
    if problem or obs is None:
        return {'trial': n, 'outcome': 'invalid', 'reason': problem or 'no measurements', 'observed': obs,
                'run_dir': next((e.get('artifact_dir') for e in events), None)}, problem
    obs = {**obs, 'integrity_violations': len(violations)}
    verdict, met = strategist.evaluate(CUSTOMER_CRITERIA, obs)
    return {'trial': n, 'outcome': 'breach' if verdict == 'confirmed' else 'held', 'criteria_met': met,
            'observed': obs, 'integrity': violations,
            'run_dir': next((e.get('artifact_dir') for e in events), None)}, None


def summarize(trials):
    valid = [t for t in trials if t['outcome'] != 'invalid']
    k = sum(t['outcome'] == 'breach' for t in valid)
    timing = lambda key: sorted(t['observed'][key] for t in valid if t['observed'].get(key) is not None)
    return {'valid_trials': len(valid), 'invalid_trials': len(trials) - len(valid), 'breaches': k,
            'breach_rate': round(k / len(valid), 3) if valid else None, 'wilson_95': wilson(k, len(valid)),
            'evidence': 'insufficient (<3 valid trials)' if len(valid) < 3 else 'ok',
            'service_ready_s': timing('service_ready_s'), 'customer_recovered_s': timing('customer_recovered_s')}


def run(exp, repeat, cooldown_s=30, guard_run=guard.run, snapshot=None, cond=None):
    if snapshot is None:
        from chaosmind.monitor import snapshot
    out = Path('runs') / f"trials-{exp['id']}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    out.mkdir(parents=True)
    record = {'experiment': exp, 'criteria': CUSTOMER_CRITERIA,
              'conditions': cond or conditions(exp, snapshot().get('users')), 'trials': []}
    for n in range(1, repeat + 1):
        trial, stop = one_trial(exp, n, guard_run)
        record['trials'].append(trial)
        record['summary'] = summarize(record['trials'])
        (out / 'trials.json').write_text(json.dumps(record, indent=1))
        print(f"trial {n}/{repeat}: {trial['outcome']}" + (f" ({trial.get('reason')})" if stop else ''), flush=True)
        if stop in ('NOT_RECOVERED', 'REVERT_FAILED', 'INTERRUPTED'):
            print('Stopping: cleanup or recovery needs a human before more trials.')
            break
        if n < repeat:
            time.sleep(cooldown_s)
    print(json.dumps(record['summary'], indent=1))
    return out


def summary_all(root='runs'):
    """Group every saved trial by comparable conditions."""
    groups = {}
    for path in sorted(Path(root).glob('trials-*/trials.json')):
        rec = json.loads(path.read_text())
        key = json.dumps(rec['conditions'], sort_keys=True)
        groups.setdefault(key, []).extend(rec['trials'])
    return [{'conditions': json.loads(k), **summarize(v)} for k, v in groups.items()]


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='cmd', required=True)
    r = sub.add_parser('run')
    r.add_argument('experiment')
    r.add_argument('--repeat', type=int, default=5)
    r.add_argument('--cooldown', type=int, default=30, help='seconds between trials (default 30)')
    sub.add_parser('summary')
    args = parser.parse_args()
    if args.cmd == 'run':
        run(json.loads(Path(args.experiment).read_text()), args.repeat, args.cooldown)
    else:
        print(json.dumps(summary_all(), indent=1))
