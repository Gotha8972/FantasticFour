"""Analyst (Observer + Log Detective + Documentor in one): turns an agent run into FINDINGS.md.

Code computes every number (pre/during/post phases, scores, verdicts) and pulls error log lines;
the AI only writes explanations and must quote log lines exactly. Code then fact-checks the report.

python3 -m chaosmind.agents.analyst runs/agents-<time>
"""
from collections import Counter
from datetime import datetime, timedelta
import json
from pathlib import Path
import re
import subprocess
import sys

from chaosmind import inject
from chaosmind.agents import llm, strategist
from chaosmind.agents.cartographer import NEGATED, claims_data_loss

ERROR_LINE = re.compile(r'error|fail|unavailable|timeout|refused|panic|exception|deadline|\b5\d\d\b', re.I)

SYSTEM = """You are the Analyst of a chaos-engineering system. You get a fact sheet of experiments that were run
(numbers are already computed) plus error log lines captured during each fault.
For each experiment write: what happened, the most likely root cause, and the recommended fix.
Rules:
- Do NOT invent numbers. Mention a number only if it appears in the fact sheet.
- "evidence" must be log lines copied EXACTLY from the input. If logs don't explain it, say so in "root_cause".
- Order findings by severity: data loss first, then checkout/site outage, then slowdowns, then graceful cases.
- Claim data loss ONLY for an experiment whose integrity_violations list is non-empty; otherwise data was kept.
- Use "observed" for an experiment's worst numbers: it covers the fault and the recovery after it.
- Say a fix was applied ONLY for an experiment whose "remediation" has a "fix"; every other weakness is still open.
- Describe a service's configuration (replicas, PodDisruptionBudget, volumes) ONLY from its "config".
Return JSON: {"summary": "3 sentences for a judge", "findings": [{"experiment_id": "...", "title": "...",
 "severity": "critical|high|medium|low", "what_happened": "...", "root_cause": "...", "evidence": ["exact line"],
 "fix": "..."}]}"""


def load_events(run_dir):
    path = Path(run_dir or '') / 'events.jsonl'
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []


def phases(events):
    snaps = [e for e in events if e['event'] == 'SNAPSHOT']
    pick = lambda stages: [s for s in snaps if s.get('stage') in stages]
    pre, during, post = pick({'preflight'}), pick({'injecting', 'injected'}), pick({'recovery'})
    row = lambda s: {'error_rate': s['error_rate'], 'p95_ms': s['p95_ms'], 'unhealthy': s['unhealthy_services']}
    worst = None
    if during:
        worst = {'error_rate': max(s['error_rate'] for s in during), 'p95_ms': max(s['p95_ms'] for s in during),
                 'unhealthy': sorted({u for s in during for u in s['unhealthy_services']})}
    return {'pre': row(pre[-1]) if pre else None, 'during_worst': worst, 'post': row(post[-1]) if post else None}


def error_lines(events, target, limit=60):
    """Error-like log lines from the frontend and the target during THIS experiment only (live cluster only).
    Bounded at both ends: without an end, an experiment would collect errors caused by the ones after it."""
    start = next((e['timestamp_utc'] for e in events if e['event'] == 'INJECTED'), None)
    if not start:
        return []
    since = (datetime.fromisoformat(start) - timedelta(seconds=10)).strftime('%Y-%m-%dT%H:%M:%SZ')
    end = next((e['timestamp_utc'] for e in reversed(events) if e.get('timestamp_utc')), start)
    until = datetime.fromisoformat(end) + timedelta(seconds=5)
    lines = []
    for app in sorted({'frontend', target}):
        try:
            out = inject.kubectl('logs', f'deployment/{app}', '-n', inject.NS, f'--since-time={since}',
                                 '--all-containers', '--timestamps')
        except (subprocess.SubprocessError, OSError):
            continue
        for line in out.splitlines():
            stamp, _, text = line.partition(' ')
            try:
                if datetime.fromisoformat(stamp.replace('Z', '+00:00')) > until:
                    continue
            except ValueError:
                pass
            if ERROR_LINE.search(text):
                lines.append(f'{app}: {text.strip()[:300]}')
    counts = Counter(lines)
    return [l if n == 1 else f'{l}  (x{n})' for l, n in counts.most_common(limit)]


CONFIG = ('replicas', 'pdb', 'hpa', 'volumes', 'readiness_probe', 'liveness_probe')
# Config claims a report must not make when the collected facts say otherwise (affirmative mentions only).
CONFIG_CLAIMS = [(re.compile(r'\b(?:PDB|PodDisruptionBudget)s?\b'), lambda c: c.get('pdb') is False,
                  'it mentions a PodDisruptionBudget, but the service has none'),
                 (re.compile(r'\bemptyDir\b', re.I), lambda c: 'persistentVolumeClaim' in (c.get('volumes') or []),
                  'it says emptyDir, but the service mounts a persistent volume')]


# "All three failures were mitigated", "every weakness was fixed": a claim about the whole run.
ALL_FIXED = re.compile(r'\b(?:all|every|each|both)\b[^.]{0,80}?\b(?:fixed|mitigated|resolved|eliminated|remediated)\b', re.I)


def unfixed(facts):
    """Confirmed weaknesses no fix was applied to (and re-run) in this run."""
    return [e['experiment_id'] for e in facts['experiments']
            if e.get('verdict') == 'confirmed' and (e.get('remediation') or {}).get('after') is None]


def contradictions(text, e):
    """Claims in the AI's explanation that the measurements or the collected config contradict."""
    out = [('measurements', 'it claims data loss, but the integrity checks passed (the cart was kept)')
           ] if claims_data_loss(text) and not e.get('integrity_violations') else []
    for pattern, wrong, why in CONFIG_CLAIMS:
        if wrong(e.get('config') or {}) and any(not NEGATED.search(text[max(0, m.start() - 40):m.end()])
                                                for m in pattern.finditer(text)):
            out.append(('collected config', why))
    return out


def after_verdict(h):
    """The same pre-registered criteria applied to the after-fix re-run: a fix that works refutes the hypothesis."""
    r = h.get('remediation')
    if not r or not r.get('after_observed') or 'after_verdict' in r:
        return r
    observed = {**r['after_observed'], 'integrity_violations': len(r.get('after_integrity', []))}
    return {**r, 'after_verdict': strategist.evaluate(h.get('criteria', []), observed)[0]}


def fact_sheet(run_dir):
    run_dir = Path(run_dir)
    history = json.loads((run_dir / 'history.json').read_text())
    vulns = json.loads((run_dir / 'vulnerabilities.json').read_text())
    services = json.loads((run_dir / 'facts.json').read_text())['services'] if (run_dir / 'facts.json').exists() else {}
    experiments = []
    for h in history:
        steps = h.get('safety', {}).get('steps', [])
        events = load_events(steps[-1]['run_dir']) if steps else []
        experiments.append({
            'experiment_id': h['experiment']['id'], 'vulnerability': h.get('vulnerability'),
            'fault': h['experiment']['fault'], 'target': h['experiment']['target'],
            'params': h['experiment'].get('params', {}), 'prediction': h.get('prediction'),
            # the config at the time of the experiment: a fix applied later in the run changes the live config
            'config': h.get('config') or {k: services.get(h['experiment']['target'], {}).get(k) for k in CONFIG},
            'criteria': h.get('criteria'), 'verdict': h.get('verdict'),
            'safety_decision': h.get('safety', {}).get('decision'),
            'ramp': [s.get('intensity') for s in steps],
            'tolerated_up_to': h.get('safety', {}).get('tolerated_up_to'),
            'limit_crossed_at': h.get('safety', {}).get('limit_crossed_at'),
            'phases': phases(events), 'observed': h.get('observed'), 'criteria_met': h.get('criteria_met', []),
            'recovery_s': (h.get('observed') or {}).get('recovery_s'),
            'integrity_violations': h.get('integrity', []), 'score': h.get('score'),
            'remediation': after_verdict(h), 'run_dir': steps[-1]['run_dir'] if steps else None,
            'log_errors': error_lines(events, h['experiment']['target']) if events else []})
    return {'vulnerabilities': [{k: v.get(k) for k in ('id', 'service', 'severity', 'weakness', 'status')}
                                for v in vulns['vulnerabilities']],
            'experiments': experiments,
            'scorecard': {'hypotheses': len(history),
                          'confirmed': sum(h.get('verdict') == 'confirmed' for h in history),
                          'refuted': sum(h.get('verdict') == 'refuted' for h in history),
                          'refuted_after_fix': sum((after_verdict(h) or {}).get('after_verdict') == 'refuted'
                                                   for h in history)}}


def numbers(text):
    return {float(n) for n in re.findall(r'(?<![\w.])\d+(?:\.\d+)?', text)}


def fact_check(prose, facts):
    """Numbers the AI wrote that don't exist anywhere in the fact sheet (allowing % and rounding)."""
    known = numbers(json.dumps(facts))
    known |= {round(k * 100, 1) for k in known if k <= 1} | {round(k) for k in known} | {round(k, 1) for k in known}
    known |= {v for k in known if k >= 1000 for v in (round(k / 1000), round(k / 1000, 1))}  # 17000 ms written as 17 s
    return sorted(n for n in numbers(prose) if n not in known and round(n, 1) not in known)


def fixes_line(facts):
    """Which fixes were really applied, written by code next to the AI's summary (the model has claimed fixes that
    were never applied)."""
    done = [f"`{e['remediation']['fix']}` on {e['target']} (score {e['remediation'].get('before')} → "
            f"{e['remediation'].get('after')})" for e in facts['experiments'] if (e.get('remediation') or {}).get('fix')]
    still = sorted({e['target'] for e in facts['experiments'] if e['verdict'] == 'confirmed'
                    and not (e.get('remediation') or {}).get('fix')})
    return (f"**Fixes applied (from the data):** {', '.join(done) or 'none'}. "
            f"**Confirmed weaknesses still open:** {', '.join(still) or 'none'}.")


def render(facts, reply):
    summary = reply.get('summary', '')
    open_ = unfixed(facts) if ALL_FIXED.search(summary) else []
    lines = ['# Findings report', '', summary, '']
    if open_:
        lines += [f"> ⚠ **Contradicted by the run:** not every weakness was fixed; no fix was applied to "
                  f"{', '.join(f'`{x}`' for x in open_)}.", '']
    lines += [
             f"**AI hypotheses:** {facts['scorecard']['hypotheses']} tested, {facts['scorecard']['confirmed']} confirmed, "
             f"{facts['scorecard']['refuted']} refuted; **{facts['scorecard']['refuted_after_fix']} refuted after their fix** "
             "(same criteria, re-run after the approved fix). Verdicts are decided by code against criteria written before "
             "each run.", '', fixes_line(facts), '',
             '| Experiment | Fault | Verdict | Criteria met | Worst error rate | Worst p95 | Recovery | Integrity | Score |',
             '|---|---|---|---|---|---|---|---|---|']
    for e in facts['experiments']:
        w = e.get('observed') or e['phases']['during_worst'] or {}  # fault + recovery: the numbers the verdict used
        lines.append(f"| `{e['experiment_id']}` | {e['fault']} on {e['target']} | {e['verdict']} | "
                     f"{len(e.get('criteria_met') or [])} of {len(e.get('criteria') or [])} | "
                     f"{w.get('error_rate', 0):.1%} | {w.get('p95_ms', '–')} ms | {e['recovery_s'] or '–'} s | "
                     f"{len(e['integrity_violations'])} violation(s) | {(e['score'] or {}).get('score', '–')} |")
    lines += ['', 'Scores are as computed when the run happened. `python3 -m chaosmind.agents.scoreboard` recomputes every '
              'run with the current formula.']
    lines.append('')
    by_id = {e['experiment_id']: e for e in facts['experiments']}
    for f in reply.get('findings', []):
        e = by_id.get(f.get('experiment_id'), {})
        logs = set(e.get('log_errors', []))
        evidence = [x for x in f.get('evidence', []) if x in logs]
        lines += [f"## {f.get('title', f.get('experiment_id'))} ({f.get('severity', '?')})", '',
                  f"**What happened:** {f.get('what_happened', '')}", '',
                  f"**Root cause:** {f.get('root_cause', '')}", '']
        lines += ['**Log evidence:**', ''] + [f'    {x}' for x in evidence] + [''] if evidence else []
        for source, why in contradictions(f"{f.get('title', '')} {f.get('what_happened', '')} {f.get('root_cause', '')}",
                                          e) if e else []:
            lines += [f'> ⚠ **Contradicted by the {source}:** {why}.', '']
        lines += [f"**Fix:** {f.get('fix', '')}", '']
        r = e.get('remediation')
        if r and r.get('fix') and r.get('after') is not None:
            lines += [f"**Remediation:** `{r['fix']}` applied after human approval; the same experiment re-run: score "
                      f"{r.get('before')} → {r['after']} ({r.get('verdict')}); hypothesis **{r.get('after_verdict', '?')}** "
                      "after the fix.", '']
        elif r:
            lines += [f"**Remediation:** no fix applied ({r.get('verdict')}).", '']
        lines += [f"Evidence: `{e.get('run_dir')}`", '']
    return '\n'.join(lines)


def write(run_dir, out=None, offline=False):
    """offline: re-render from the saved fact sheet and AI reply (no API call, no cluster), e.g. after the checks improve."""
    run_dir = Path(run_dir)
    if offline:
        facts = json.loads((run_dir / 'facts_for_report.json').read_text())
        reply = json.loads((run_dir / 'analyst_reply.json').read_text())
        services = json.loads((run_dir / 'facts.json').read_text())['services']
        history = {h['experiment']['id']: h for h in json.loads((run_dir / 'history.json').read_text())}
        for e in facts['experiments']:  # fields added since the report was first written
            h = history.get(e['experiment_id'], {})
            e.setdefault('config', {k: services.get(e['target'], {}).get(k) for k in CONFIG})
            e.setdefault('observed', h.get('observed'))
            e.setdefault('criteria_met', h.get('criteria_met', []))
            e['remediation'] = after_verdict(h) if h else e.get('remediation')
        facts['scorecard'].setdefault('refuted_after_fix', sum(
            (after_verdict(h) or {}).get('after_verdict') == 'refuted' for h in history.values()))
    else:
        facts = fact_sheet(run_dir)
        (run_dir / 'facts_for_report.json').write_text(json.dumps(facts, indent=1))
        try:
            reply = llm.ask(SYSTEM, facts)
        except RuntimeError as error:  # the measured results don't depend on the AI: always write the report
            reply = {'summary': f'AI narrative unavailable ({error}). Every measured result below is complete.',
                     'findings': []}
        (run_dir / 'analyst_reply.json').write_text(json.dumps(reply, indent=1))  # re-render without the API
    report = render(facts, reply)
    unmatched = fact_check(report, facts)
    contradicted = report.count('**Contradicted by the')
    report += '\n## Fact-check\n\n' + ('Every number above appears in the measured data.' if not unmatched else
              'Numbers not found in the measured data (treat with caution): ' + ', '.join(f'{n:g}' for n in unmatched))
    if contradicted:
        report += f'\n\n{contradicted} claim(s) contradicted by the measurements or the collected config are marked above.'
    path = Path(out or Path(run_dir) / 'FINDINGS.md')
    path.write_text(report + '\n')
    return path


if __name__ == '__main__':
    print(write(sys.argv[1], offline='--offline' in sys.argv))
