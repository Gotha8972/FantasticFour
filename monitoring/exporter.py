"""Dependency-free Prometheus exposition of Locust CSV or Chaos Mesh status."""
import csv
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import ssl
import time
from urllib.request import Request, urlopen


def number(value):
    value = float(value)
    if not math.isfinite(value) or value < 0:
        raise ValueError('Metric is nonfinite or negative')
    return value


def metric(name, value, labels=None):
    def escaped(text):
        return str(text).replace('\\', '\\\\').replace('\n', '\\n').replace('"', '\\"')
    suffix = '{' + ','.join(f'{k}="{escaped(v)}"' for k, v in labels.items()) + '}' if labels else ''
    return f'{name}{suffix} {number(value):.17g}\n'


def family(name, kind, help_text, value):
    return f'# HELP {name} {help_text}\n# TYPE {name} {kind}\n' + metric(name, value)


def locust_metrics():
    directory = Path(os.environ.get('LOCUST_STATS_DIR', '/stats'))
    with (directory / 'load_stats.csv').open(newline='') as handle:
        rows = list(csv.DictReader(handle))
    aggregate = next(r for r in rows if r.get('Name') == 'Aggregated')
    recent = None
    with (directory / 'load_stats_history.csv').open(newline='') as handle:
        for row in csv.DictReader(handle):
            if row.get('Name') == 'Aggregated':
                recent = row
    if recent is None:
        raise ValueError('No aggregate Locust history yet')
    age = time.time() - number(recent['Timestamp'])
    if not -5 <= age <= 15:
        raise ValueError(f'Locust statistics are stale (age={age:.1f}s)')
    rps = number(recent['Requests/s'])
    checkout = [r for r in rows if r.get('Name') == '/cart/checkout']
    values = [
        ('boutique_locust_stats_available', 'gauge', 'Fresh CSV statistics are available.', 1),
        ('boutique_locust_stats_age_seconds', 'gauge', 'Age of Locust aggregate history.', max(0, age)),
        ('boutique_locust_users', 'gauge', 'Current simulated shoppers.', recent['User Count']),
        ('boutique_locust_recent_rps', 'gauge', 'Recent completed requests per second.', rps),
        ('boutique_locust_recent_p50_ms', 'gauge', 'Recent aggregate latency p50 in milliseconds.', recent['50%']),
        ('boutique_locust_recent_p95_ms', 'gauge', 'Recent aggregate latency p95 in milliseconds.', recent['95%']),
        ('boutique_locust_requests_total', 'counter', 'Completed requests since this Locust process started.', aggregate['Request Count']),
        ('boutique_locust_failures_total', 'counter', 'Failed requests since this Locust process started.', aggregate['Failure Count']),
        ('boutique_locust_checkout_requests_total', 'counter', 'Completed checkout requests.', sum(number(r['Request Count']) for r in checkout)),
        ('boutique_locust_checkout_failures_total', 'counter', 'Failed checkout requests.', sum(number(r['Failure Count']) for r in checkout))]
    if rps > 0:
        values.append(('boutique_locust_recent_error_ratio', 'gauge', 'Recent failed requests divided by completed requests.',
                       min(1, number(recent['Failures/s']) / rps)))
    # Calculate all values first: a partial CSV must not emit a partial healthy snapshot.
    output = ''.join(family(*value) for value in values)
    for name, column in (('boutique_locust_endpoint_requests_total', 'Request Count'),
                         ('boutique_locust_endpoint_failures_total', 'Failure Count')):
        output += f'# HELP {name} Per-route count since Locust started.\n# TYPE {name} counter\n'
        for row in rows:
            if row.get('Name') != 'Aggregated':
                output += metric(name, row[column], {'method': row['Type'], 'path': row['Name']})
    return output


def chaos_metrics():
    directory = Path('/var/run/secrets/kubernetes.io/serviceaccount')
    token = (directory / 'token').read_text().strip()
    context = ssl.create_default_context(cafile=str(directory / 'ca.crt'))
    resources = []
    for kind in ('podchaos', 'networkchaos', 'stresschaos'):
        req = Request(f'https://kubernetes.default.svc/apis/chaos-mesh.org/v1alpha1/namespaces/online-boutique/{kind}',
                      headers={'Authorization': f'Bearer {token}'})
        with urlopen(req, context=context, timeout=2) as response:
            resources.extend(json.load(response)['items'])
    output = family('boutique_chaos_stats_available', 'gauge', 'Chaos Mesh status API was read successfully.', 1)
    output += family('boutique_chaos_resource_count', 'gauge', 'Observed experiment resource count including recovered objects.', len(resources))
    for name in ('boutique_chaos_selected', 'boutique_chaos_injected', 'boutique_chaos_recovered'):
        output += f'# HELP {name} Experiment status: 1 means true, 0 means false.\n# TYPE {name} gauge\n'
    injected_count = 0
    for resource in resources:
        state = resource.get('status', {})
        conditions = {c['type']: c['status'] == 'True' for c in state.get('conditions', [])}
        records = state.get('experiment', {}).get('containerRecords', [])
        recovered = conditions.get('AllRecovered', False)
        injected = not recovered and (conditions.get('AllInjected', False) or bool(records) and all(
            r.get('injectedCount', 0) > 0 and r.get('phase') == 'Injected' for r in records))
        labels = {'experiment': resource['metadata']['name'], 'kind': resource['kind'],
                  'target': resource.get('spec', {}).get('selector', {}).get('labelSelectors', {}).get('app', 'other')}
        output += metric('boutique_chaos_selected', int(conditions.get('Selected', False)), labels)
        output += metric('boutique_chaos_injected', int(injected), labels)
        output += metric('boutique_chaos_recovered', int(recovered), labels)
        injected_count += int(injected)
    output += family('boutique_chaos_injected_count', 'gauge', 'Currently confirmed injected experiments.', injected_count)
    return output


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/-/healthy':
            self.reply(200, 'ok\n')
        elif self.path == '/metrics':
            mode = os.environ.get('EXPORTER_MODE', 'locust')
            try:
                content = chaos_metrics() if mode == 'chaos' else locust_metrics()
            except Exception as error:
                print(json.dumps({'mode': mode, 'collection_error': str(error)}), flush=True)
                name = 'boutique_chaos_stats_available' if mode == 'chaos' else 'boutique_locust_stats_available'
                content = family(name, 'gauge', 'Fresh measurements are available.', 0)
            self.reply(200, content)
        else:
            self.reply(404, 'not found\n')

    def reply(self, code, body):
        content = body.encode()
        self.send_response(code)
        self.send_header('Content-Type', 'text/plain; version=0.0.4; charset=utf-8')
        self.send_header('Content-Length', str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, *args):
        pass


if __name__ == '__main__':
    mode = os.environ.get('EXPORTER_MODE', 'locust')
    if mode not in ('locust', 'chaos'):
        raise SystemExit('EXPORTER_MODE must be locust or chaos')
    print(f'Exporting {mode} metrics on port 9464', flush=True)
    ThreadingHTTPServer(('0.0.0.0', 9464), Handler).serve_forever()
