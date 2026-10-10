"""Audit → plan → (safely inject → integrity check → score → judge → [fix + re-run] → re-plan) → FINDINGS.md

python3 -m chaosmind.agents --dry-run          # audit + plan + safety review, injects nothing
python3 -m chaosmind.agents --budget 4         # live: runs up to 4 experiments through the guard
python3 -m chaosmind.agents --budget 3 --remediate   # also apply a reviewed fix to confirmed weaknesses and re-run
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from chaosmind import inject
from chaosmind.agents import analyst, cartographer, facts, integrity, remediation, safety, score, strategist


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
    parser.add_argument('--remediate', action='store_true', help='apply a catalog fix to confirmed weaknesses and re-run')
    parser.add_argument('--allow-unverified', action='store_true',
                        help='let the AI use fault types that have not run live yet (default: only proven ones)')
    args = parser.parse_args()

    out = Path('runs') / f"agents-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    out.mkdir(parents=True)
    save = lambda name, data: (out / name).write_text(json.dumps(data, indent=1))
    print(f'Artifacts: {out}')

    baseline = load_baseline(args.baseline)
    f = facts.collect(json.loads(Path(args.workloads).read_text()) if args.workloads else None)
    save('facts.json', f)
    audit = cartographer.audit(f)
    save('vulnerabilities.json', audit)
    vulns = audit['vulnerabilities']
    print(f"Cartographer: {len(vulns)} vulnerabilities ({len(audit['rejected'])} rejected for unverifiable evidence)")
    for v in vulns:
        print(f"  {v['id']} [{v['severity']}] {v['service']}: {v['weakness']}")

    history = []
    allowed = set(inject.KINDS) if args.allow_unverified else inject.LIVE_VERIFIED
    plan = strategist.plan(vulns, baseline, history, args.budget, allowed)
    save('plan-1.json', plan)
    while plan['plan'] and len(history) < args.budget:
        item = plan['plan'][0]
        exp = item['experiment']
        print(f"\nStrategist → {exp['id']}: {item.get('reason', '')}")
        if args.dry_run:
            from chaosmind.monitor import snapshot
            health = {'note': 'offline'} if args.workloads else snapshot()
            result = {**safety.review(exp, health, baseline), 'steps': []}
            obs, violations = None, []
        else:
            from chaosmind.monitor import snapshot
            state = integrity.prepare()                       # silent-failure check: set up before the fault
            result = safety.run(exp, snapshot(), baseline)
            violations = integrity.verify(state) if result['steps'] else []
            obs = next((s['observed'] for s in reversed(result['steps']) if s['observed']), None)
            if obs is not None:
                obs = {**obs, 'integrity_violations': len(violations)}
        verdict, met = strategist.evaluate(item['criteria'], obs)
        if verdict == 'needs_integrity_check' and violations:
            verdict = 'confirmed'
        s = score.score(obs, baseline, (obs or {}).get('recovery_s'), violations) if obs else None
        print(f"Safety Checker: {result['decision']} ({result['reason']}); ramp={result.get('ramp')}; "
              f"tolerated up to={result.get('tolerated_up_to')}, guard limit crossed at={result.get('limit_crossed_at')}; "
              f"integrity violations={len(violations)} → {verdict}" + (f", score {s['score']}" if s else ''))
        entry = {'vulnerability': item.get('vulnerability'), 'experiment': exp, 'criteria': item['criteria'],
                 'prediction': item.get('prediction'), 'safety': result, 'observed': obs, 'integrity': violations,
                 'verdict': verdict, 'criteria_met': met, 'score': s}
        if args.remediate and verdict == 'confirmed' and not args.dry_run:
            try:
                entry['remediation'] = remediation.remediate(entry, baseline)
                r = entry['remediation']
                print(f"Remediation: {r.get('fix', 'none')} → score {r.get('before')} → {r.get('after')} ({r['verdict']})")
            except Exception as error:  # a failed fix must not stop the loop; the guard already restored the fault
                entry['remediation'] = {'verdict': 'error', 'reason': str(error)}
        history.append(entry)
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
    if history and not args.dry_run:
        try:
            print(f'Analyst report: {analyst.write(out)}')
        except Exception as error:
            print(f'Analyst failed ({error}); raw results are in {out}/history.json')
    print(f"\nDone. {sum(h['verdict'] == 'confirmed' for h in history)} confirmed, "
          f"{sum(h['verdict'] == 'refuted' for h in history)} refuted. See {out}")


if __name__ == '__main__':
    main()
