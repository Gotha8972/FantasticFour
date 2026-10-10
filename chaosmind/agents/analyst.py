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
from chaosmind.agents import llm

ERROR_LINE = re.compile(r'error|fail|unavailable|timeout|refused|panic|exception|deadline|\b5\d\d\b', re.I)

SYSTEM = """You are the Analyst of a chaos-engineering system. You get a fact sheet of experiments that were run
(numbers are already computed) plus error log lines captured during each fault.
For each experiment write: what happened, the most likely root cause, and the recommended fix.
Rules:
- Do NOT invent numbers. Mention a number only if it appears in the fact sheet.
- "evidence" must be log lines copied EXACTLY from the input. If logs don't explain it, say so in "root_cause".
- Order findings by severity: data loss first, then checkout/site outage, then slowdowns, then graceful cases.
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
    """Error-like log lines from the frontend and the target during the fault (live cluster only)."""
    start = next((e['timestamp_utc'] for e in events if e['event'] == 'INJECTED'), None)
    if not start:
        return []
    since = (datetime.fromisoformat(start) - timedelta(seconds=10)).strftime('%Y-%m-%dT%H:%M:%SZ')
    lines = []
    for app in sorted({'frontend', target}):
        try:
            out = inject.kubectl('logs', f'deployment/{app}', '-n', inject.NS, f'--since-time={since}', '--all-containers')
        except (subprocess.SubprocessError, OSError):
            continue
        lines += [f'{app}: {l.strip()[:300]}' for l in out.splitlines() if ERROR_LINE.search(l)]
    counts = Counter(lines)
    return [l if n == 1 else f'{l}  (x{n})' for l, n in counts.most_common(limit)]


def fact_sheet(run_dir):
    run_dir = Path(run_dir)
    history = json.loads((run_dir / 'history.json').read_text())
    vulns = json.loads((run_dir / 'vulnerabilities.json').read_text())
    experiments = []
    for h in history:
        steps = h.get('safety', {}).get('steps', [])
        events = load_events(steps[-1]['run_dir']) if steps else []
        experiments.append({
            'experiment_id': h['experiment']['id'], 'vulnerability': h.get('vulnerability'),
            'fault': h['experiment']['fault'], 'target': h['experiment']['target'],
            'params': h['experiment'].get('params', {}), 'prediction': h.get('prediction'),
            'criteria': h.get('criteria'), 'verdict': h.get('verdict'),
            'safety_decision': h.get('safety', {}).get('decision'),
            'ramp': [s.get('intensity') for s in steps],
            'tolerated_up_to': h.get('safety', {}).get('tolerated_up_to'),
            'limit_crossed_at': h.get('safety', {}).get('limit_crossed_at'),
            'phases': phases(events), 'recovery_s': (h.get('observed') or {}).get('recovery_s'),
            'integrity_violations': h.get('integrity', []), 'score': h.get('score'),
            'remediation': h.get('remediation'), 'run_dir': steps[-1]['run_dir'] if steps else None,
            'log_errors': error_lines(events, h['experiment']['target']) if events else []})
    return {'vulnerabilities': [{k: v.get(k) for k in ('id', 'service', 'severity', 'weakness', 'status')}
                                for v in vulns['vulnerabilities']],
            'experiments': experiments,
            'scorecard': {'hypotheses': len(history),
                          'confirmed': sum(h.get('verdict') == 'confirmed' for h in history),
                          'refuted': sum(h.get('verdict') == 'refuted' for h in history)}}


def numbers(text):
    return {float(n) for n in re.findall(r'(?<![\w.])\d+(?:\.\d+)?', text)}


def fact_check(prose, facts):
    """Numbers the AI wrote that don't exist anywhere in the fact sheet (allowing % and rounding)."""
    known = numbers(json.dumps(facts))
    known |= {round(k * 100, 1) for k in known if k <= 1} | {round(k) for k in known} | {round(k, 1) for k in known}
    return sorted(n for n in numbers(prose) if n not in known and round(n, 1) not in known)


def render(facts, reply):
    lines = ['# Findings report', '', reply.get('summary', ''), '',
             f"**AI hypotheses:** {facts['scorecard']['hypotheses']} tested, {facts['scorecard']['confirmed']} confirmed, "
             f"{facts['scorecard']['refuted']} refuted. Verdicts are decided by code against criteria written before each run.", '',
             '| Experiment | Fault | Verdict | Worst error rate | Worst p95 | Recovery | Integrity | Score |',
             '|---|---|---|---|---|---|---|---|']
    for e in facts['experiments']:
        w = e['phases']['during_worst'] or {}
        lines.append(f"| `{e['experiment_id']}` | {e['fault']} on {e['target']} | {e['verdict']} | "
                     f"{w.get('error_rate', 0):.1%} | {w.get('p95_ms', '–')} ms | {e['recovery_s'] or '–'} s | "
                     f"{len(e['integrity_violations'])} violation(s) | {(e['score'] or {}).get('score', '–')} |")
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
        lines += [f"**Fix:** {f.get('fix', '')}", '']
        if e.get('remediation'):
            r = e['remediation']
            lines += [f"**Remediation:** `{r.get('fix')}` applied, re-run score {r.get('before')} → {r.get('after')} "
                      f"({r.get('verdict')}).", '']
        lines += [f"Evidence: `{e.get('run_dir')}`", '']
    return '\n'.join(lines)


def write(run_dir, out=None):
    facts = fact_sheet(run_dir)
    (Path(run_dir) / 'facts_for_report.json').write_text(json.dumps(facts, indent=1))
    reply = llm.ask(SYSTEM, facts)
    report = render(facts, reply)
    unmatched = fact_check(report, facts)
    report += '\n## Fact-check\n\n' + ('Every number above appears in the measured data.' if not unmatched else
              'Numbers not found in the measured data (treat with caution): ' + ', '.join(f'{n:g}' for n in unmatched))
    path = Path(out or Path(run_dir) / 'FINDINGS.md')
    path.write_text(report + '\n')
    return path


if __name__ == '__main__':
    print(write(sys.argv[1]))
