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
# Live AI runs, numbered in time order as in FINDINGS.md (run 1, agents-20261010T182208Z, stopped at its first
# approval and was never resumed, so it has no before/after pair of its own).
R2, R3, R4 = 'runs/agents-20261010T185909Z', 'runs/agents-20261010T192511Z', 'runs/agents-20261010T200021Z'
R5 = 'runs/agents-20261010T215020Z'  # recorded for the demo video, fixes approved in mission control
R6, R7, R8 = 'runs/agents-20261011T013741Z', 'runs/agents-20261011T015326Z', 'runs/agents-20261011T021019Z'
VIDEO_RUN = 'runs/agents-20261011T034630Z'  # latest recorded demo run
FIXED = 'after the fix, approved by a human'


def pair(finding, name, run, target, before='1 replica'):
    return [(finding, name, before, 'agent', f'{run}#{target}'), (finding, name, FIXED, 'agent-after', f'{run}#{target}')]


EVIDENCE = [
    (1, 'Redis restarted (cart test)', 'before fix', 'redis', 'runs/c-redis-20261010T070925.577773Z'),
    (1, 'Redis restarted (cart test)', 'after fix: PVC + append-only log', 'redis', 'runs/c-redis-20261010T102251.009037Z'),
    *pair(1, 'Redis pod kill, AI run 2', R2, 'redis-cart', 'before fix'),
    (1, 'Redis pod kill, AI run 3', 'fix already in place', 'agent', f'{R3}#redis-cart'),
    *pair(1, 'Redis pod kill, AI run 5 (recorded)', R5, 'redis-cart', 'before fix'),
    *pair(1, 'Redis pod kill, AI run 8', R8, 'redis-cart', 'before fix'),
    *pair(2, 'frontend unavailable, AI run 3', R3, 'frontend'),
    *pair(2, 'frontend unavailable, AI run 5 (recorded)', R5, 'frontend'),
    *pair(2, 'frontend unavailable, AI run 8', R8, 'frontend'),
    (2, 'frontend pod kill, AI run 7 (refuted: 2 replicas held)', '2 replicas', 'agent', f'{R7}#frontend'),
    (3, 'currency unavailable, AI run 4', '1 replica', 'agent', f'{R4}#currencyservice'),
    (3, 'currency pod kill, AI run 6', '1 replica', 'agent', f'{R6}#currencyservice'),
    (4, 'cart unavailable (manual)', '1 replica', 'guard', 'runs/test-down-20261010T062320.861245Z'),
    *pair(4, 'cart pod kill, AI run 3', R3, 'cartservice'),
    *pair(4, 'cart pod kill, AI run 6', R6, 'cartservice'),
    *pair(4, 'cart unavailable, AI run 8', R8, 'cartservice'),
    (5, 'catalog pod kill, 5 trials', '1 replica', 'trials', 'runs/trials-catalog-podkill-20261010T182606Z'),
    (5, 'catalog pod kill, 5 trials', '2 replicas', 'trials', 'runs/trials-catalog-podkill-20261010T183121Z'),
    *pair(5, 'catalog pod kill, AI run 2', R2, 'productcatalogservice'),
    (5, 'catalog pod kill, AI run 6 (verdict missed the errors; fixed in code)', '1 replica', 'agent',
     f'{R6}#productcatalogservice'),
    *pair(5, 'catalog pod kill, AI run 7', R7, 'productcatalogservice'),
    (6, 'network partition, catalog cut off from frontend, AI run 8', '1 replica', 'agent', f'{R8}#productcatalogservice'),
    (6, 'network partition, payment cut off from checkout, AI run 7', '1 replica', 'agent', f'{R7}#paymentservice'),
    (7, 'payment pod kill, AI run 4', '1 replica', 'agent', f'{R4}#paymentservice'),
    (7, 'payment pod kill, AI run 6', '1 replica', 'agent', f'{R6}#paymentservice'),
    (7, '20% packet loss on payment, AI run 8', '1 replica', 'agent', f'{R8}#paymentservice'),
    (8, 'checkout unavailable for 30 s, AI run 5 (recorded)', '1 replica', 'agent', f'{R5}#checkoutservice'),
    (8, 'checkout pod kill, AI run 4 (refuted: restart absorbed)', '1 replica', 'agent', f'{R4}#checkoutservice'),
    (9, '+500 ms delay on catalog (manual)', 'no fix', 'guard', 'runs/test-delay-20261010T062255.501508Z'),
    (9, '+500 ms delay on currency, AI run 8', 'no fix', 'agent', f'{R8}#currencyservice'),
    (9, '30% packet loss on currency, AI run 7', 'no fix', 'agent', f'{R7}#currencyservice'),
    (11, 'ads unavailable (manual)', 'no fix needed', 'guard', 'runs/c-ad-health-13973e53bd-20261010T070523.440196Z'),
    (11, 'Redis under CPU stress (manual)', 'no fix needed', 'guard', 'runs/redis-cpu-20261011T013116.326478Z'),
    *pair(1, 'Redis pod kill, latest video run', VIDEO_RUN, 'redis-cart', 'before fix'),
    *pair(2, 'frontend pod kill, latest video run', VIDEO_RUN, 'frontend'),
    *pair(5, 'catalog pod failure, latest video run', VIDEO_RUN, 'productcatalogservice'),
    *pair(7, 'payment pod kill, latest video run', VIDEO_RUN, 'paymentservice'),
    (9, '+delay on currency, latest video run', 'no fix', 'agent', f'{VIDEO_RUN}#currencyservice'),
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
             '| Rank | Score | Experiment | Condition | E | L | R | B | I | Finding # | Evidence |',
             '|---|---|---|---|---|---|---|---|---|---|---|']
    for n, r in enumerate(sorted(table, key=lambda r: r['score']), 1):
        spread = f" ({r['range'][0]}-{r['range'][1]}, n={r['n']})" if r['n'] > 1 else ''
        b = r['breakdown']
        lines.append(f"| {n} | **{r['score']}**{spread} | {r['experiment']} | {r['condition']} | {b['E']} | {b['L']} | "
                     f"{b['R']} | {b['B']} | {b['I']} | {r['finding'] or 'n/a'} | [{Path(r['run'].split('#')[0]).name}](../../{r['run'].split('#')[0]}) |")
    lines += ['', '## Fixes proven by re-running the same experiment', '',
              '| Experiment | Before | After | Change |', '|---|---|---|---|']
    for name in dict.fromkeys(r['experiment'] for r in table):
        pair = [r for r in table if r['experiment'] == name]
        if len(pair) == 2:
            before, after = pair
            lines.append(f"| {name} | {before['score']} ({before['condition']}) | {after['score']} ({after['condition']}) "
                         f"| **{after['score'] - before['score']:+d}** |")
    return '\n'.join(lines) + '\n'


def ai_runs(root='runs'):
    """Every completed live AI run (at least one measured experiment and a report), counted from its history: the
    README's run counts come from here, so they can't drift from the evidence."""
    from chaosmind.agents import analyst
    out = []
    for path in sorted(Path(root).glob('agents-*/history.json')):
        ran = [h for h in json.loads(path.read_text()) if h.get('observed') is not None]
        if not ran or not (path.parent / 'FINDINGS.md').exists():  # completed runs only (aborted takes have no report)
            continue
        fixes = [h['remediation'] for h in ran if (h.get('remediation') or {}).get('fix')]
        out.append({'run': path.parent.name, 'experiments': len(ran),
                    'confirmed': sum(h['verdict'] == 'confirmed' for h in ran),
                    'refuted': sum(h['verdict'] == 'refuted' for h in ran),
                    'faults': sorted({h['experiment']['fault'] for h in ran}),
                    'fixes': [(r['fix'], r.get('before'), r.get('after')) for r in fixes],
                    'refuted_after_fix': sum((analyst.after_verdict(h) or {}).get('after_verdict') == 'refuted' for h in ran)})
    return out


def render_runs(runs):
    fixes = [f for r in runs for f in r['fixes'] if f[1] is not None and f[2] is not None]
    gains = [after - before for _, before, after in fixes]
    total = {k: sum(r[k] for r in runs) for k in ('experiments', 'confirmed', 'refuted', 'refuted_after_fix')}
    lines = ['', '## Live AI runs (generated)', '',
             f"**{len(runs)} runs, {total['experiments']} measured experiments: {total['confirmed']} confirmed, "
             f"{total['refuted']} refuted. {len(fixes)} fixes approved and re-run: {sum(g > 0 for g in gains)} scored "
             f"higher (mean {sum(gains) / len(gains):+.0f}, best {max(gains):+d}); {total['refuted_after_fix']} "
             f"hypotheses refuted after their fix. Fault types the AI chose: "
             f"{', '.join(sorted({f for r in runs for f in r['faults']}))}.**" if gains else '', '',
             'Scores here are as each run recorded them; the first runs used an earlier score formula, so the ranked '
             'table above (recomputed from raw evidence with the current formula) is the one to compare across runs.', '',
             '| Run | Folder | Experiments | Confirmed | Refuted | Fault types | Fixes (score before and after, as recorded) |',
             '|---|---|---|---|---|---|---|']
    for n, r in enumerate(runs, 1):
        fx = ', '.join(f'{f} {b} to {a}' for f, b, a in r['fixes']) or 'none'
        lines.append(f"| {n} | [{r['run']}](../../runs/{r['run']}) | {r['experiments']} | {r['confirmed']} | {r['refuted']} | "
                     f"{', '.join(r['faults'])} | {fx} |")
    return '\n'.join(lines) + '\n'


if __name__ == '__main__':
    print(render(rows()) + render_runs(ai_runs()), end='')
