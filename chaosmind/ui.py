"""ChaosMind mission control: a local web UI over the agent runs, live while a run is in progress.

python3 -m chaosmind.ui                     → http://127.0.0.1:8090 (another port: --port 8091)
.venv/bin/python -m chaosmind.graph --budget 3 --remediate --ui    → approve fixes in the browser

Read-only over runs/, except one action: answering a pending fix approval. Binds to localhost only. Stdlib only.
"""
import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import time
import threading
from urllib.parse import parse_qs, urlparse, urlencode

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / 'runs'
PAGE = Path(__file__).with_name('ui.html')
NAME = re.compile(r'^[A-Za-z0-9._-]+$')  # a single runs/ entry: no slashes, no '..'
LIVE_S = 120  # a run touched within this many seconds counts as live
_telemetry_lock = threading.Lock()
_telemetry_cache = {}


def telemetry():
    """Read-only live measurements, shared across viewers for eight seconds."""
    from chaosmind import monitor
    with _telemetry_lock:
        if time.monotonic() - _telemetry_cache.get('at', float('-inf')) < 8:
            return _telemetry_cache['value']
        value = monitor.snapshot()
        _telemetry_cache.update(at=time.monotonic(), value=value)
        return value


def read(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default


def visible_run(name):
    """A local demo reset hides old evidence without deleting committed artifacts."""
    return name not in read(ROOT / '.runtime/ui-reset.json', {}).get('hidden_runs', [])


def safe_dir(name):
    if not name or not NAME.match(name) or name in ('.', '..'):
        raise ValueError('bad run name')
    path = (RUNS / name).resolve()
    if not path.is_relative_to(RUNS.resolve()):
        raise ValueError('bad run path')
    if not path.is_dir():
        raise FileNotFoundError(name)
    return path


def updated(d):
    return max((p.stat().st_mtime for p in d.iterdir()), default=d.stat().st_mtime)


def is_live(d):
    """Touched recently, or waiting for a fix approval (nothing is written while it waits, so the age alone would drop
    the run, and its approval banner, after LIVE_S)."""
    return (d / 'pending_approval.json').exists() or time.time() - updated(d) < LIVE_S


def list_runs():
    out = []
    for d in sorted(RUNS.glob('agents-*'), reverse=True):
        if visible_run(d.name) and (d / 'facts.json').exists():
            history = read(d / 'history.json', [])
            out.append({'name': d.name, 'experiments': len(history), 'done': (d / 'FINDINGS.md').exists(),
                        'dry_run': bool(history) and all(h.get('observed') is None for h in history),
                        'live': is_live(d)})
    return out


def stage(d, plans, history, pending, live):
    """Where the workflow is, inferred from the files it has written so far."""
    if pending:
        return 'approve'
    if (d / 'FINDINGS.md').exists():
        return 'report'
    if not (d / 'vulnerabilities.json').exists():
        return 'audit'
    if not plans:
        return 'plan'
    if not live:
        return 'report'
    latest = ((plans[-1].get('plan') or [{}])[0].get('experiment') or {}).get('id')
    return 'inject' if latest and latest not in {h['experiment']['id'] for h in history} else 'plan'


def run(name):
    from chaosmind.agents import analyst  # after-fix verdicts for runs recorded before it existed
    d = safe_dir(name)
    plans = [read(p, {}) for p in sorted(d.glob('plan-*.json'), key=lambda p: int(p.stem.split('-')[1]))]
    history = [{**h, 'remediation': analyst.after_verdict(h)} for h in read(d / 'history.json', [])]
    pending = read(d / 'pending_approval.json')
    live = is_live(d)
    current = None
    if plans and plans[-1].get('plan'):
        exp_id = plans[-1]['plan'][0]['experiment']['id']
        since = (d / 'facts.json').stat().st_mtime
        dirs = [p for p in RUNS.glob(f'{exp_id}-*') if p.is_dir() and p.stat().st_mtime >= since]
        if dirs:
            current = {'id': exp_id, 'dir': max(dirs, key=lambda p: p.stat().st_mtime).name}
    return {'name': name, 'live': live, 'stage': stage(d, plans, history, pending, live), 'pending': pending,
            # facts-current.json: the config after an approved fix, so the map shows the fix as it lands
            'facts': read(d / 'facts-current.json') or read(d / 'facts.json', {}),
            'audit': read(d / 'vulnerabilities.json', {}), 'plans': plans,
            'history': history, 'current': current, 'findings': (d / 'FINDINGS.md').exists()}


def events(name):
    path = safe_dir(name) / 'events.jsonl'
    lines = path.read_text().splitlines() if path.exists() else []
    return [json.loads(line) for line in lines if line.strip()]


def scoreboard():
    from chaosmind.agents import scoreboard as sb
    try:
        rows = sb.rows(ROOT / 'baseline.json')
    except (OSError, SystemExit, ValueError, KeyError, StopIteration, IndexError):
        return []
    for row in rows:
        directory, _, target = row['run'].partition('#')
        name = Path(directory).name
        query = {'run': name, 'target': target} if name.startswith('agents-') else {'evidence': name}
        row['detail_url'] = '/?' + urlencode(query)
    return sorted((r for r in rows if visible_run(Path(r['run'].split('#')[0]).name)),
                  key=lambda r: r['score'])


EVIDENCE_FILES = {'history.json', 'facts.json', 'facts_for_report.json', 'analyst_reply.json',
                  'FINDINGS.md', 'OPERATOR_NOTES.md', 'events.jsonl', 'events.csv', 'metrics.csv',
                  'evidence.jsonl', 'summary.json', 'trials.json', 'REPORT.md'}


def evidence_file(name, filename):
    directory = safe_dir(name)
    if filename not in EVIDENCE_FILES:
        raise ValueError('unsupported evidence file')
    path = (directory / filename).resolve()
    if not path.is_relative_to(directory) or not path.is_file():
        raise FileNotFoundError('evidence file unavailable')
    return path


def artifacts(name, label=None):
    directory = safe_dir(name)
    result = []
    for filename in sorted(EVIDENCE_FILES):
        try:
            evidence_file(name, filename)
        except (ValueError, FileNotFoundError):
            continue
        result.append({'label': f'{label + " · " if label else ""}{filename}',
                       'url': '/evidence?' + urlencode({'dir': name, 'file': filename})})
    return result


def fix_file(fix_id, filename):
    catalog = read(ROOT / 'remediation/catalog.json', [])
    fix = next((f for f in catalog if f['id'] == fix_id), None)
    if not fix:
        raise FileNotFoundError('fix not found')
    allowed = (fix.get('apply_files') or []) + [fix.get('patch'), fix.get('revert_patch')]
    match = next((f for f in allowed if f and Path(f).name == filename), None)
    if not match:
        raise ValueError('unsupported fix evidence file')
    path = (ROOT / match).resolve()
    if not path.is_relative_to((ROOT / 'remediation').resolve()) or not path.is_file():
        raise FileNotFoundError('fix evidence unavailable')
    return path


def incidents():
    """Measured agent experiments only; dry runs and plans never inflate the KPIs."""
    records = []
    for directory in sorted(RUNS.glob('agents-*'), reverse=True):
        if not directory.is_dir() or not visible_run(directory.name):
            continue
        for h in read(directory / 'history.json', []):
            if h.get('observed') is None:
                continue
            x, r = h['experiment'], h.get('remediation') or {}
            records.append({'run': directory.name, 'id': x['id'], 'target': x['target'],
                            'fault': x['fault'], 'verdict': h.get('verdict'), 'observed': h['observed'],
                            'score': (h.get('score') or {}).get('score'), 'integrity': len(h.get('integrity') or []),
                            'fix': r.get('fix'), 'kept': r.get('kept'), 'before': r.get('before'),
                            'after': r.get('after'), 'retested': bool(r.get('after_observed')),
                            'fix_status': r.get('verdict'),
                            'url': '/?' + urlencode({'run': directory.name, 'experiment': x['id']})})
    fixes = [r for r in records if r['fix'] and r['retested']]
    improved = [r for r in fixes if r['kept'] is True and r['before'] is not None
                and r['after'] is not None and r['after'] > r['before']]
    gains = [r['after'] - r['before'] for r in improved]
    return {'records': records, 'kpis': {'runs': len({r['run'] for r in records}),
            'experiments': len(records), 'confirmed': sum(r['verdict'] == 'confirmed' for r in records),
            'retested_fixes': len(fixes), 'improved_fixes': len(improved),
            'mean_gain': round(sum(gains) / len(gains), 1) if gains else None}}


def incident(name, experiment=None, target=None):
    """Use captured evidence, never today's cluster logs to explain a historical fault."""
    from chaosmind.agents import analyst
    directory = safe_dir(name)
    history = read(directory / 'history.json', [])
    h = next((h for h in history if (h['experiment']['id'] == experiment if experiment
                                   else h['experiment']['target'] == target)), None)
    if not h:
        if experiment or target:
            raise FileNotFoundError('experiment not found in this run')
        return {'run': name, 'artifacts': artifacts(name), 'history': None}
    h = {**h, 'remediation': analyst.after_verdict(h)}
    x = h['experiment']
    sheet = next((e for e in read(directory / 'facts_for_report.json', {}).get('experiments', [])
                  if e.get('experiment_id') == x['id']), {})
    analysis = next((f for f in read(directory / 'analyst_reply.json', {}).get('findings', [])
                     if f.get('experiment_id') == x['id']), None)
    logs = sheet.get('log_errors', [])
    if analysis:
        analysis = {**analysis, 'evidence': [line for line in analysis.get('evidence', []) if line in logs]}
    warnings = analyst.contradictions(' '.join(str(analysis.get(k, '')) for k in
                ('title', 'what_happened', 'root_cause', 'fix')), sheet) if analysis and sheet else []
    links = artifacts(name, 'Analysis and recorded decisions')
    for step in (h.get('safety') or {}).get('steps', []):
        if step.get('run_dir'):
            try:
                links += artifacts(Path(step['run_dir']).name, 'Fault measurement')
            except (ValueError, FileNotFoundError):
                pass
    after = (h.get('remediation') or {}).get('after_run_dir')
    if after:
        try:
            links += artifacts(Path(after).name, 'Fix retest')
        except (ValueError, FileNotFoundError):
            pass
    fix_id = (h.get('remediation') or {}).get('fix')
    definition = next((f for f in read(ROOT / 'remediation/catalog.json', []) if f['id'] == fix_id), None)
    if definition:
        for filename in (definition.get('apply_files') or []) + [definition.get('patch'), definition.get('revert_patch')]:
            if not filename:
                continue
            try:
                fix_file(fix_id, Path(filename).name)
            except (ValueError, FileNotFoundError):
                continue
            label = 'Rollback patch' if filename == definition.get('revert_patch') else 'Applied fix definition'
            links.append({'label': label + ' · ' + Path(filename).name,
                          'url': '/fix-evidence?' + urlencode({'fix': fix_id, 'file': Path(filename).name})})
    return {'run': name, 'history': h, 'analysis': analysis, 'logs': logs,
            'background_logs': sheet.get('log_background', []), 'warnings': warnings,
            'artifacts': links, 'fix_definition': definition}


def approve(name, answer):
    d = safe_dir(name)
    if not (d / 'pending_approval.json').exists():
        raise FileNotFoundError('nothing is waiting for approval')
    (d / 'approval.json').write_text(json.dumps({'answer': 'y' if answer == 'y' else 'n', 'at': time.time()}))


class Handler(BaseHTTPRequestHandler):
    def send(self, code, body, kind='application/json'):
        data = body if isinstance(body, bytes) else json.dumps(body, default=str).encode()
        self.send_response(code)
        self.send_header('Content-Type', kind)
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        try:
            if url.path == '/':
                return self.send(200, PAGE.read_bytes(), 'text/html; charset=utf-8')
            if url.path == '/api/runs':
                return self.send(200, list_runs())
            if url.path == '/api/run':
                return self.send(200, run(q.get('name')))
            if url.path == '/api/events':
                return self.send(200, events(q.get('dir')))
            if url.path == '/api/scoreboard':
                return self.send(200, scoreboard())
            if url.path == '/api/incidents':
                return self.send(200, incidents())
            if url.path == '/api/telemetry':
                try:
                    return self.send(200, telemetry())
                except Exception:
                    return self.send(503, {'error': 'Live metrics unavailable. Check the cluster and load generator.'})
            if url.path == '/api/incident':
                return self.send(200, incident(q.get('run'), q.get('experiment'), q.get('target')))
            if url.path in ('/evidence', '/fix-evidence'):
                path = (evidence_file(q.get('dir'), q.get('file')) if url.path == '/evidence'
                        else fix_file(q.get('fix'), q.get('file')))
                with path.open('rb') as stream:
                    data = stream.read(2_000_001)
                if len(data) > 2_000_000:
                    data = data[:2_000_000] + b'\n[Preview truncated at 2 MB]\n'
                return self.send(200, data, 'text/plain; charset=utf-8')
            self.send(404, {'error': 'not found'})
        except (ValueError, FileNotFoundError) as error:
            self.send(404, {'error': str(error)})

    def do_POST(self):
        if urlparse(self.path).path != '/api/approve':
            return self.send(404, {'error': 'not found'})
        try:
            body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0)) or 2) or b'{}')
            approve(body.get('run'), body.get('answer'))
            self.send(200, {'ok': True})
        except (ValueError, FileNotFoundError) as error:
            self.send(409, {'error': str(error)})

    def log_message(self, *args):  # keep the terminal clean for the agents' output
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--port', type=int, default=8090)
    args = parser.parse_args()
    os.chdir(ROOT)  # the scoreboard's evidence paths are relative to the repo root
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    print(f'ChaosMind mission control: http://127.0.0.1:{args.port}', flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
