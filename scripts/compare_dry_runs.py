#!/usr/bin/env python3
"""Score agent dry-run folders the same way, so two implementations can be compared on evidence, not taste.

python3 scripts/compare_dry_runs.py runs/agents-OURS-1 runs/agents-OURS-2 -- runs/agents-A-1 runs/agents-A-2

Each folder must contain the shared output contract: facts.json, vulnerabilities.json, plan-1.json, history.json
(see docs/team/log/AGENT_BAKEOFF.md). Folders before "--" are implementation 1, after it implementation 2.
"""
import json
from pathlib import Path
import statistics
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from chaosmind import inject  # noqa: E402
from chaosmind.agents import cartographer  # noqa: E402

MUST_BE_SERIOUS = {'redis-cart', 'productcatalogservice', 'frontend', 'cartservice', 'checkoutservice'}
MUST_BE_MILD = {'adservice', 'recommendationservice'}
STATEFUL = {'redis-cart'}


def score_run(folder):
    d = Path(folder)
    facts = json.loads((d / 'facts.json').read_text())
    vulns = json.loads((d / 'vulnerabilities.json').read_text())
    plan = json.loads((d / 'plan-1.json').read_text())
    history = json.loads((d / 'history.json').read_text()) if (d / 'history.json').exists() else []
    # Re-verify the audit with OUR fact checker, so both implementations are held to the same grounding standard.
    reverified = cartographer.verify(vulns, facts)
    sev = {v['service']: v.get('severity') for v in vulns.get('vulnerabilities', [])}
    items = plan.get('plan', [])

    def valid(item):
        exp = item.get('experiment') or {k: item.get(k) for k in ('fault', 'target', 'params', 'duration_s')}
        try:
            inject.validate({'id': 'check', 'params': {}, **{k: v for k, v in exp.items() if v is not None}})
            return True
        except (ValueError, KeyError, TypeError):
            return False

    def fault(item):
        return (item.get('experiment') or item).get('fault')

    def target(item):
        return (item.get('experiment') or item).get('target')

    trivial = sum(1 for i in items if fault(i) in ('pod_kill', 'pod_failure')
                  for c in i.get('criteria', []) if c.get('metric') == 'unhealthy_count')
    stateful = [i for i in items if target(i) in STATEFUL]
    times = [p.stat().st_mtime for p in (d / 'facts.json', d / 'history.json') if p.exists()]
    return {
        'vulnerabilities': len(vulns.get('vulnerabilities', [])),
        'grounding: claims failing our fact check (lower better)': len(reverified['rejected'])
            + sum(len(v['unverified_evidence_dropped']) for v in reverified['vulnerabilities']),
        'ranking: serious services rated critical/high (of 5)': sum(sev.get(s) in ('critical', 'high') for s in MUST_BE_SERIOUS),
        'ranking: optional services rated low/medium (of 2)': sum(sev.get(s) in ('low', 'medium') for s in MUST_BE_MILD),
        'severity inflation: share rated critical (lower better)': round(
            sum(s == 'critical' for s in sev.values()) / max(1, len(sev)), 2),
        'plan: experiments': len(items),
        'plan: share passing inject.validate': round(sum(map(valid, items)) / max(1, len(items)), 2),
        'plan: distinct fault types': len({fault(i) for i in items}),
        'plan: trivial criteria (lower better)': trivial,
        'plan: stateful targets with an integrity criterion': f"{sum(any(c.get('metric') == 'integrity_violations' for c in i.get('criteria', [])) for i in stateful)}/{len(stateful)}",
        'safety: first decision': history[0]['safety']['decision'] if history else 'none',
        'wall time, seconds (lower better)': round(max(times) - min(times)) if len(times) == 2 else None,
    }


def summarize(folders):
    rows = [score_run(f) for f in folders]
    out = {}
    for key in rows[0]:
        values = [r[key] for r in rows]
        nums = [v for v in values if isinstance(v, (int, float))]
        out[key] = (round(statistics.mean(nums), 2) if len(nums) == len(values) and nums else ' / '.join(map(str, values)))
    return out


if __name__ == '__main__':
    args = sys.argv[1:]
    groups = [args[:args.index('--')], args[args.index('--') + 1:]] if '--' in args else [args]
    results = [summarize(g) for g in groups if g]
    names = ['implementation 1', 'implementation 2'][:len(results)]
    width = max(len(k) for k in results[0])
    print(f"{'metric':<{width}}  " + '  '.join(f'{n:>18}' for n in names))
    for key in results[0]:
        print(f'{key:<{width}}  ' + '  '.join(f'{str(r[key]):>18}' for r in results))
    print(f"\nRuns per implementation: {', '.join(str(len(g)) for g in groups if g)} (use ≥ 3 each: AI output varies run to run)")
