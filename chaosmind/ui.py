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
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / 'runs'
PAGE = Path(__file__).with_name('ui.html')
NAME = re.compile(r'^[A-Za-z0-9._-]+$')  # a single runs/ entry: no slashes, no '..'
LIVE_S = 120  # a run touched within this many seconds counts as live


def read(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default


def safe_dir(name):
    if not name or not NAME.match(name) or name in ('.', '..'):
        raise ValueError('bad run name')
    path = RUNS / name
    if not path.is_dir():
        raise FileNotFoundError(name)
    return path


def updated(d):
    return max((p.stat().st_mtime for p in d.iterdir()), default=d.stat().st_mtime)


def list_runs():
    out = []
    for d in sorted(RUNS.glob('agents-*'), reverse=True):
        if (d / 'facts.json').exists():
            history = read(d / 'history.json', [])
            out.append({'name': d.name, 'experiments': len(history), 'done': (d / 'FINDINGS.md').exists(),
                        'dry_run': bool(history) and all(h.get('observed') is None for h in history),
                        'live': time.time() - updated(d) < LIVE_S})
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
    live = time.time() - updated(d) < LIVE_S
    current = None
    if plans and plans[-1].get('plan'):
        exp_id = plans[-1]['plan'][0]['experiment']['id']
        since = (d / 'facts.json').stat().st_mtime
        dirs = [p for p in RUNS.glob(f'{exp_id}-*') if p.is_dir() and p.stat().st_mtime >= since]
        if dirs:
            current = {'id': exp_id, 'dir': max(dirs, key=lambda p: p.stat().st_mtime).name}
    return {'name': name, 'live': live, 'stage': stage(d, plans, history, pending, live), 'pending': pending,
            'facts': read(d / 'facts.json', {}), 'audit': read(d / 'vulnerabilities.json', {}), 'plans': plans,
            'history': history, 'current': current, 'findings': (d / 'FINDINGS.md').exists()}


def events(name):
    path = safe_dir(name) / 'events.jsonl'
    lines = path.read_text().splitlines() if path.exists() else []
    return [json.loads(line) for line in lines if line.strip()]


def scoreboard():
    from chaosmind.agents import scoreboard as sb
    try:
        rows = sb.rows(ROOT / 'baseline.json')
    except (OSError, SystemExit, ValueError, KeyError, StopIteration):
        return []
    return sorted(rows, key=lambda r: r['score'])


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
