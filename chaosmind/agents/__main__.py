"""Audit → plan → (safely inject → judge → re-plan) loop for the first three agents.

python3 -m chaosmind.agents --dry-run          # audit + plan + safety review, injects nothing
python3 -m chaosmind.agents --budget 4         # live: runs up to 4 experiments through the guard
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from chaosmind.agents import cartographer, facts, safety, strategist


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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--budget', type=int, default=4, help='max experiments (default 4)')
    parser.add_argument('--baseline', default='baseline.json')
    parser.add_argument('--workloads', help='saved deployments JSON instead of the live cluster')
    parser.add_argument('--dry-run', action='store_true', help='no injection')
    args = parser.parse_args()

    out = Path('runs') / f"agents-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    out.mkdir(parents=True)
    save = lambda name, data: (out / name).write_text(json.dumps(data, indent=1))
    print(f'Artifacts: {out}')

    baseline = load_baseline(args.baseline)
    f = facts.collect(json.load(open(args.workloads)) if args.workloads else None)
    save('facts.json', f)
    audit = cartographer.audit(f)
    save('vulnerabilities.json', audit)
    vulns = audit['vulnerabilities']
    print(f"Cartographer: {len(vulns)} vulnerabilities ({len(audit['rejected'])} rejected for unverifiable evidence)")
    for v in vulns:
        print(f"  {v['id']} [{v['severity']}] {v['service']}: {v['weakness']}")

    history = []
    plan = strategist.plan(vulns, baseline, history, args.budget)
    save('plan-1.json', plan)
    while plan['plan'] and len(history) < args.budget:
        item = plan['plan'][0]
        exp = item['experiment']
        print(f"\nStrategist → {exp['id']}: {item.get('reason', '')}")
        if args.dry_run:
            from chaosmind.monitor import snapshot
            health = {'note': 'offline'} if args.workloads else snapshot()
            result = {**safety.review(exp, health, baseline), 'steps': []}
            obs = None
        else:
            from chaosmind.monitor import snapshot
            result = safety.run(exp, snapshot(), baseline)
            obs = next((s['observed'] for s in reversed(result['steps']) if s['observed']), None)
        verdict, met = strategist.evaluate(item['criteria'], obs)
        print(f"Safety Checker: {result['decision']} ({result['reason']}); ramp={result.get('ramp')}; "
              f"breaking point={result.get('breaking_point')} → {verdict}")
        history.append({'vulnerability': item.get('vulnerability'), 'experiment': exp, 'criteria': item['criteria'],
                        'prediction': item.get('prediction'), 'safety': result, 'observed': obs,
                        'verdict': verdict, 'criteria_met': met})
        for v in vulns:
            if v['id'] == item.get('vulnerability') and verdict in ('confirmed', 'refuted'):
                v['status'] = verdict
        save('history.json', history)
        if args.dry_run or len(history) >= args.budget:
            break
        plan = strategist.plan(vulns, baseline, history, args.budget - len(history))
        save(f'plan-{len(history) + 1}.json', plan)
        print(f"Strategist re-plan: {plan['replan_note']}")

    save('vulnerabilities.json', audit)
    print(f"\nDone. {sum(h['verdict'] == 'confirmed' for h in history)} confirmed, "
          f"{sum(h['verdict'] == 'refuted' for h in history)} refuted. See {out}")


if __name__ == '__main__':
    main()
