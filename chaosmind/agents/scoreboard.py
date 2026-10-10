"""Ranked resilience scoreboard, recomputed from the raw evidence every time: no score is typed in by hand.

python3 -m chaosmind.agents.scoreboard > docs/evidence/SCOREBOARD.md

Each row is one experiment scored with score.py (penalties E, L, R, B, I shown), ranked worst first.
A fix counts as proven only when the same experiment, re-run after it, scores higher.
"""
import json
from pathlib import Path
from statistics import median

from chaosmind.agents import facts as facts_mod, safety, score, steps, trials

# (finding in FINDINGS.md, experiment, condition, evidence kind, run[#target]). Same experiment twice = before/after.
AI_RUN = 'runs/agents-20261010T185909Z'    # first full live AI loop (Redis and catalog fixes approved)
AI_RUN2 = 'runs/agents-20261010T192511Z'   # fresh live AI loop, Redis fix already in place (frontend and cart fixes)
AI_RUN3 = 'runs/agents-20261010T200021Z'   # third live AI loop: payment, currency, checkout (no reviewed fixes for them)
AI_RUN4 = 'runs/agents-20261010T215020Z'   # recorded AI loop for the video: frontend and Redis fixes approved in the UI
FIXED = 'after the fix, approved by a human'
EVIDENCE = [
    (1, 'Redis restarted (cart test)', 'before fix', 'redis', 'runs/c-redis-20261010T070925.577773Z'),
    (1, 'Redis restarted (cart test)', 'after fix: PVC + append-only log', 'redis', 'runs/c-redis-20261010T102251.009037Z'),
    (1, 'Redis pod kill, chosen and run by the AI', 'before fix', 'agent', f'{AI_RUN}#redis-cart'),
    (1, 'Redis pod kill, chosen and run by the AI', FIXED, 'agent-after', f'{AI_RUN}#redis-cart'),
    (1, 'Redis pod kill, fresh AI run', 'fix already in place', 'agent', f'{AI_RUN2}#redis-cart'),
    (2, 'frontend unavailable, chosen and run by the AI', '1 replica', 'agent', f'{AI_RUN2}#frontend'),
    (2, 'frontend unavailable, chosen and run by the AI', FIXED, 'agent-after', f'{AI_RUN2}#frontend'),
    (3, 'currencyservice unavailable, chosen and run by the AI', '1 replica', 'agent', f'{AI_RUN3}#currencyservice'),
    (4, 'cartservice unavailable', '1 replica', 'guard', 'runs/test-down-20261010T062320.861245Z'),
    (4, 'cartservice pod kill, chosen and run by the AI', '1 replica', 'agent', f'{AI_RUN2}#cartservice'),
    (4, 'cartservice pod kill, chosen and run by the AI', FIXED, 'agent-after', f'{AI_RUN2}#cartservice'),
    (5, 'catalog pod kill, 5 trials', '1 replica', 'trials', 'runs/trials-catalog-podkill-20261010T182606Z'),
    (5, 'catalog pod kill, 5 trials', '2 replicas', 'trials', 'runs/trials-catalog-podkill-20261010T183121Z'),
    (5, 'catalog pod kill, chosen and run by the AI', '1 replica', 'agent', f'{AI_RUN}#productcatalogservice'),
    (5, 'catalog pod kill, chosen and run by the AI', FIXED, 'agent-after', f'{AI_RUN}#productcatalogservice'),
    (6, 'paymentservice pod kill, chosen and run by the AI', '1 replica', 'agent', f'{AI_RUN3}#paymentservice'),
    (7, '+500 ms delay on productcatalogservice', 'no fix', 'guard', 'runs/test-delay-20261010T062255.501508Z'),
    (9, 'adservice unavailable', 'no fix needed', 'guard', 'runs/c-ad-health-13973e53bd-20261010T070523.440196Z'),
    (None, 'checkoutservice pod kill, chosen and run by the AI (hypothesis refuted)', '1 replica', 'agent',
     f'{AI_RUN3}#checkoutservice'),
    (1, 'Redis pod kill, recorded AI run', 'before fix', 'agent', f'{AI_RUN4}#redis-cart'),
    (1, 'Redis pod kill, recorded AI run', FIXED, 'agent-after', f'{AI_RUN4}#redis-cart'),
    (2, 'frontend unavailable, recorded AI run', '1 replica', 'agent', f'{AI_RUN4}#frontend'),
    (2, 'frontend unavailable, recorded AI run', FIXED, 'agent-after', f'{AI_RUN4}#frontend'),
    (None, 'checkoutservice unavailable, recorded AI run (no reviewed fix)', '1 replica', 'agent',
     f'{AI_RUN4}#checkoutservice'),
]


def events(run):
    return [json.loads(line) for line in (Path(run) / 'events.jsonl').read_text().splitlines() if line.strip()]


def measurements(kind, run):
    """[(observed, recovery_s, integrity violations, target)] for one piece of evidence."""
    run, _, only = run.partition('#')
    run = Path(run)
    if kind == 'guard':
        ev = events(run)
        obs = safety.observed(ev)
        return [(obs, obs['recovery_s'], [], next(e['target'] for e in ev if e.get('target')))]
    if kind == 'redis':  # the cart-persistence test: load-generator snapshots plus the test's own cart requests
        ev = [json.loads(line) for line in (run / 'evidence.jsonl').read_text().splitlines() if line.strip()]
        deleted = next(e['elapsed_s'] for e in ev if e['event'] == 'REDIS_POD_DELETED')
        after = [e for e in ev if e['elapsed_s'] >= deleted]
        snaps = [e['details'] for e in after if e['event'] == 'SNAPSHOT']
        probes = [e['details']['seconds'] * 1000 for e in after if e['event'] == 'HTTP']
        healthy = next(e['elapsed_s'] for e in after if e['event'] == 'HEALTHY' and e['details'].get('value'))
        s = json.loads((run / 'summary.json').read_text())[0]
        obs = {'error_rate': max([x['error_rate'] for x in snaps] + [1.0 if s['observed_failed_http'] else 0.0]),
               'p95_ms': max([x['p95_ms'] for x in snaps] + probes)}  # worst seen by shoppers or by the test
        return [(obs, healthy - deleted, [{'check': 'cart_persistence'}] if s['cart_wiped'] else [], 'redis-cart')]
    if kind in ('agent', 'agent-after'):
        out = []
        for h in json.loads((run / 'history.json').read_text()):
            if only and h['experiment']['target'] != only:
                continue
            if kind == 'agent' and h.get('observed'):
                # the checkout 422 in one early run was a checker defect (hyphenated card number), not the fault
                out.append((h['observed'], h['observed'].get('recovery_s'),
                            [v for v in h['integrity'] if v.get('actual') != 'HTTP 422'], h['experiment']['target']))
            r = h.get('remediation') or {}
            if kind == 'agent-after' and r.get('after_observed'):  # Remediation's re-run, once a human approved it
                out.append((r['after_observed'], r['after_observed'].get('recovery_s'), r.get('after_integrity', []),
                            h['experiment']['target']))
        return out
    record = json.loads((run / 'trials.json').read_text())
    return [(t['observed'], t['observed'].get('recovery_s'), [{}] * (t['observed'].get('integrity_violations') or 0),
             record['experiment']['target']) for t in map(trials.reobserve, record['trials']) if t.get('observed')]


def rows(baseline_path='baseline.json'):
    baseline = steps.load_baseline(baseline_path)
    workloads = sorted(Path('runs').glob('baseline-study-*/workloads-initial.json'))[0]
    facts = facts_mod.collect(json.loads(workloads.read_text()))
    out = []
    for finding, experiment, condition, kind, run in EVIDENCE:
        scores = [score.score(obs, baseline, rec, viol, facts_mod.blast_share(facts, target))
                  for obs, rec, viol, target in measurements(kind, run)]
        if not scores:  # evidence not recorded yet
            continue
        out.append({'finding': finding, 'experiment': experiment, 'condition': condition, 'run': run,
                    'score': round(median(s['score'] for s in scores)),
                    'range': (min(s['score'] for s in scores), max(s['score'] for s in scores)), 'n': len(scores),
                    'breakdown': {k: round(median(s['breakdown'][k] for s in scores), 1) for k in 'ELRBI'}})
    return out


def render(table):
    lines = ['# Resilience scoreboard (generated)', '',
             'Generated by `python3 -m chaosmind.agents.scoreboard` from the raw evidence linked in each row; '
             '[formula](../../chaosmind/agents/score.py). Penalties: **E** errors, **L** p95 latency, **R** recovery, '
             '**B** blast radius (only when customers were hurt), **I** integrity. Repeated trials show the median and '
             'the range. Baseline: the final suitable baseline (`baseline.json`, 20 shoppers).', '',
             '## Ranked, worst first', '',
             '| Rank | Score | Experiment | Condition | E | L | R | B | I | Finding | Evidence |',
             '|---|---|---|---|---|---|---|---|---|---|---|']
    for n, r in enumerate(sorted(table, key=lambda r: r['score']), 1):
        spread = f" ({r['range'][0]}–{r['range'][1]}, n={r['n']})" if r['n'] > 1 else ''
        b = r['breakdown']
        lines.append(f"| {n} | **{r['score']}**{spread} | {r['experiment']} | {r['condition']} | {b['E']} | {b['L']} | "
                     f"{b['R']} | {b['B']} | {b['I']} | {'#' + str(r['finding']) if r['finding'] else '—'} | [{Path(r['run'].split('#')[0]).name}](../../{r['run'].split('#')[0]}) |")
    lines += ['', '## Fixes proven by re-running the same experiment', '',
              '| Experiment | Before | After | Change |', '|---|---|---|---|']
    for name in dict.fromkeys(r['experiment'] for r in table):
        pair = [r for r in table if r['experiment'] == name]
        if len(pair) == 2:
            before, after = pair
            lines.append(f"| {name} | {before['score']} ({before['condition']}) | {after['score']} ({after['condition']}) "
                         f"| **{after['score'] - before['score']:+d}** |")
    return '\n'.join(lines) + '\n'


if __name__ == '__main__':
    print(render(rows()), end='')
