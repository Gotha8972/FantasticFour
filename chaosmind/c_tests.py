"""Live C checkpoint tests. No mocked metrics or inferred injection success."""
import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import time
from urllib import parse, request
import uuid

from chaosmind import capture, guard, inject
from chaosmind.monitor import snapshot


def error_text(error):
    return getattr(error, 'stderr', None) or str(error)


class Evidence:
    def __init__(self, command):
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
        self.directory = inject.ROOT / 'runs' / f'c-{command}-{stamp}'
        self.directory.mkdir(parents=True)
        self.start = time.monotonic()
        self.results = []
        with (self.directory / 'evidence.csv').open('x', newline='') as handle:
            csv.writer(handle).writerow(['timestamp_utc', 'elapsed_s', 'test', 'event', 'details_json'])

    def log(self, test, event, **details):
        row = {'timestamp_utc': datetime.now(timezone.utc).isoformat(),
               'elapsed_s': round(time.monotonic() - self.start, 3),
               'test': test, 'event': event, 'details': details}
        with (self.directory / 'evidence.jsonl').open('a') as handle:
            handle.write(json.dumps(row) + '\n')
        with (self.directory / 'evidence.csv').open('a', newline='') as handle:
            csv.writer(handle).writerow([row['timestamp_utc'], row['elapsed_s'], test, event,
                                        json.dumps(details)])
        print(json.dumps(row), flush=True)

    def result(self, test, outcome, **details):
        self.results.append({'test': test, 'outcome': outcome, **details})
        self.log(test, outcome, **details)
        (self.directory / 'summary.json').write_text(json.dumps(self.results, indent=2) + '\n')
        print(f'{outcome}: {test}', flush=True)


def experiment(target, prefix, fault='pod_failure', duration=60):
    return {'id': f'c-{prefix}-{uuid.uuid4().hex[:10]}', 'fault': fault, 'target': target,
            'duration_s': duration, '_run_token': str(uuid.uuid4())}


def preflight(evidence, test):
    active = inject.running()
    if active:
        raise RuntimeError(f'Remove unrecovered experiments first: {active}')
    snap = snapshot()
    evidence.log(test, 'BASELINE', **snap)
    if snap['unhealthy_services'] or guard.breach(snap, guard.LIMITS):
        raise RuntimeError('Baseline is unhealthy; refusing injection')


def wait_for(evidence, test, event, probe, timeout, interval=2):
    deadline = time.monotonic() + timeout
    while True:
        value = probe()
        evidence.log(test, event, value=value)
        if value:
            return value
        if time.monotonic() >= deadline:
            raise RuntimeError(f'Timed out after {timeout}s waiting for {event}')
        time.sleep(min(interval, max(0, deadline - time.monotonic())))


def confirmed(exp):
    state = inject.injection_state(inject.status(exp))
    if state['errors']:
        raise RuntimeError(f'Injection failed: {state["errors"]}')
    return state if state['injected'] else None


def healthy(evidence, test):
    def probe():
        try:
            snap = snapshot()
            evidence.log(test, 'SNAPSHOT', **snap)
            return not snap['unhealthy_services'] and not guard.breach(snap, guard.LIMITS)
        except Exception as error:
            evidence.log(test, 'MONITOR_ERROR', reason=error_text(error))
            return False
    wait_for(evidence, test, 'HEALTHY', probe, 120)


def save_logs(evidence, test, target):
    errors = []
    for label, namespace, selector in (
            ('target', inject.NS, f'app={target}'),
            ('loadgenerator', inject.NS, 'app=loadgenerator'),
            ('chaos-daemon', 'chaos-mesh', 'app.kubernetes.io/component=chaos-daemon')):
        try:
            capture.logs(evidence.directory / f'{test}-{label}-logs.csv', namespace, selector, '10m')
        except Exception as error:
            errors.append(error_text(error))
    evidence.log(test, 'LOG_COLLECTION', errors=errors)


def health_trigger(evidence):
    test = 'ad-service-health-trigger'
    preflight(evidence, test)
    exp = experiment('adservice', 'ad-health')
    events = guard.run(exp, {'max_unhealthy': 0})
    (evidence.directory / 'ad-guard-events.json').write_text(json.dumps(events, indent=2))
    names = {event['event'] for event in events}
    # An error during injection/recovery must never count as a successful kill switch.
    bad = names & {'ERROR', 'REFUSED', 'REVERT_FAILED', 'NOT_RECOVERED', 'INTERRUPTED'}
    breach = next((event for event in events if event['event'] == 'BREACH'), None)
    if bad or not {'INJECTED', 'REVERTED', 'HEALTHY'} <= names or breach is None:
        raise RuntimeError(f'Guard checkpoint failed: events={sorted(names)}')
    details = {'metric': breach['metric'], 'value': breach['value'], 'limit': breach['limit'],
               'guard_artifact_dir': events[0]['artifact_dir']}
    if breach['metric'] == 'unhealthy':
        evidence.result(test, 'PASS', **details)
    else:
        evidence.result(test, 'FINDING', reason='Another threshold fired before service health', **details)
    save_logs(evidence, test, 'adservice')


def guard_events(path):
    if not path.exists():
        return []
    # The guard may be appending a line while we poll its file.
    lines = path.read_text().splitlines(keepends=True)
    return [json.loads(line) for line in lines if line.endswith('\n') and line.strip()]


def crash_failsafe(evidence):
    test = 'guard-sigkill-failsafe'
    preflight(evidence, test)
    exp = experiment('adservice', 'crash')
    exp_path = evidence.directory / 'crash-experiment.json'
    exp_path.write_text(json.dumps(exp, indent=2))
    process = None
    try:
        with (evidence.directory / 'crash-guard-terminal.txt').open('x') as terminal:
            process = subprocess.Popen(['python3', '-m', 'chaosmind.guard', str(exp_path)],
                                       cwd=inject.ROOT, stdout=terminal, stderr=subprocess.STDOUT)
            def started():
                paths = list((inject.ROOT / 'runs').glob(f'{exp["id"]}-*/events.jsonl'))
                events = guard_events(paths[0]) if paths else []
                if any(event['event'] == 'INJECTED' for event in events):
                    return str(paths[0])
                if process.poll() is not None:
                    raise RuntimeError('Guard exited before injection; see crash-guard-terminal.txt')
                return None
            events_path = wait_for(evidence, test, 'WAIT_GUARD_INJECTED', started, 65, interval=0.05)
            process.kill()  # SIGKILL: finally blocks cannot execute.
            returncode = process.wait(timeout=10)
            evidence.log(test, 'SIGKILL', pid=process.pid, returncode=returncode,
                         guard_events_path=events_path)
            resource = inject.status(exp)
            # The guard creates its own ownership token; retain it for scoped cleanup.
            exp['_run_token'] = resource['metadata']['annotations']['chaosmind/run-token']
            (evidence.directory / 'crash-resource-before.json').write_text(json.dumps(resource, indent=2))
            if returncode != -9 or not inject.injection_state(resource)['injected']:
                raise RuntimeError('Did not kill an actively injecting guard with SIGKILL')
            started_wait = time.monotonic()
            def recovered():
                current = inject.status(exp)
                state = inject.injection_state(current)
                evidence.log(test, 'CHAOS_STATE', **state)
                if state['recovered']:
                    (evidence.directory / 'crash-resource-recovered.json').write_text(json.dumps(current, indent=2))
                    return True
                return False
            # Observe Chaos Mesh recovery BEFORE any manual deletion. Allow reconciliation slack.
            wait_for(evidence, test, 'AUTOMATIC_RECOVERY', recovered, exp['duration_s'] + 45)
            recovery_wait = round(time.monotonic() - started_wait, 3)
            healthy(evidence, test)
            evidence.result(test, 'PASS', duration_s=exp['duration_s'],
                            seconds_after_sigkill_to_recovery=recovery_wait,
                            reason='Chaos Mesh reported AllRecovered without manual deletion')
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait(timeout=10)
        # If startup failed, discover the guard token before cleaning up its resource.
        raw = inject.kubectl('get', 'podchaos', exp['id'], '-n', inject.NS,
                             '--ignore-not-found', '-o', 'json')
        if raw.strip():
            exp['_run_token'] = json.loads(raw)['metadata'].get('annotations', {}).get('chaosmind/run-token')
            inject.revert(exp)
            evidence.log(test, 'FINAL_CLEANUP', experiment=exp['id'])
    save_logs(evidence, test, 'adservice')


def abort_checkpoint(evidence):
    test = 'manual-abort'
    preflight(evidence, test)
    experiments = [experiment('adservice', 'abort-pod'),
                   experiment('shippingservice', 'abort-net', 'network_delay')]
    attempted = []
    try:
        for exp in experiments:
            attempted.append(exp)
            inject.apply(exp)
            wait_for(evidence, test, 'CONFIRMED_INJECTION', lambda exp=exp: confirmed(exp), 45)
        start = time.monotonic()
        inject.abort_all()
        seconds = round(time.monotonic() - start, 3)
        owned = json.loads(inject.kubectl('get', 'podchaos,networkchaos,stresschaos,iochaos',
                                          '-n', inject.NS, '-l',
                                          f'app.kubernetes.io/part-of={inject.OWNER}', '-o', 'json'))['items']
        if owned:
            raise RuntimeError('Owned faults remain after abort')
        evidence.log(test, 'ABORT_CLEARED', deletion_seconds=seconds)
        healthy(evidence, test)
        evidence.result(test, 'PASS', deletion_seconds=seconds,
                        scope='chaosmind-owned faults; other users experiments are preserved')
    finally:
        # Cleanup each attempted resource, even if a different resource's deletion fails.
        errors = []
        for exp in attempted:
            try:
                inject.revert(exp)
            except Exception as error:
                errors.append(error_text(error))
        if errors:
            raise RuntimeError(f'Abort test cleanup failed: {errors}')
    save_logs(evidence, test, 'shippingservice')


def cart_count(html):
    if 'Your shopping cart is empty!' in html:
        return 0
    match = re.search(r'Cart\s*\((\d+)\)', html)
    if not match:
        raise RuntimeError('Cannot parse cart count; refusing to infer data loss from an error page')
    return int(match.group(1))


def redis_finding(evidence, base_url):
    test = 'redis-cart-persistence'
    preflight(evidence, test)
    deployment = json.loads(inject.kubectl('get', 'deployment', 'redis-cart', '-n', inject.NS, '-o', 'json'))
    (evidence.directory / 'redis-deployment.json').write_text(json.dumps(deployment, indent=2))
    spec = deployment['spec']
    storage = spec['template']['spec'].get('volumes', [])
    mounts = [mount for container in spec['template']['spec']['containers']
              for mount in container.get('volumeMounts', []) if mount['mountPath'] == '/data']
    empty_dir = any('emptyDir' in volume and any(m['name'] == volume['name'] for m in mounts)
                    for volume in storage)
    evidence.log(test, 'STORAGE', replicas=spec.get('replicas', 1), data_empty_dir=empty_dir,
                 volumes=storage, data_mounts=mounts)
    pods = json.loads(inject.kubectl('get', 'pods', '-n', inject.NS, '-l', 'app=redis-cart', '-o', 'json'))['items']
    if spec.get('replicas', 1) != 1 or len(pods) != 1:
        raise RuntimeError('Redis checkpoint requires exactly one Redis replica/pod')
    old = pods[0]['metadata']
    session = 'c-redis-' + uuid.uuid4().hex
    headers = {'Cookie': 'shop_session-id=' + session}
    product = 'OLJCESPC7Z'

    def fetch(path, data=None):
        started = time.monotonic()
        req = request.Request(base_url.rstrip('/') + path, data=data, headers=headers)
        with request.urlopen(req, timeout=10) as response:
            html = response.read().decode()
        evidence.log(test, 'HTTP', path=path, method='POST' if data else 'GET',
                     seconds=round(time.monotonic() - started, 3))
        return html

    before = fetch('/cart', parse.urlencode({'product_id': product, 'quantity': 1}).encode())
    (evidence.directory / 'cart-before.html').write_text(before)
    before_count = cart_count(before)
    if before_count != 1 or f'SKU #{product}' not in before:
        raise RuntimeError('Could not verify an item in the isolated test session; Redis will not be restarted')
    evidence.log(test, 'CART_BEFORE', count=before_count, session=session, product=product)
    start = time.monotonic()
    # Delete the specific observed pod, rather than every pod matching the label.
    delete_manifest = {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {
        'name': old['name'], 'namespace': inject.NS}}
    inject.kubectl('delete', '-f', '-', '--wait=false', stdin=json.dumps(delete_manifest))
    evidence.log(test, 'REDIS_POD_DELETED', name=old['name'], uid=old['uid'])

    def replacement():
        current = json.loads(inject.kubectl('get', 'pods', '-n', inject.NS,
                                          '-l', 'app=redis-cart', '-o', 'json'))['items']
        ready = [pod['metadata'] for pod in current if pod['metadata']['uid'] != old['uid']
                 and not pod['metadata'].get('deletionTimestamp')
                 and any(c['type'] == 'Ready' and c['status'] == 'True'
                         for c in pod.get('status', {}).get('conditions', []))]
        return ready or None

    # Poll both the replacement and HTTP during recovery to measure observed failed requests.
    failed_http = []
    first_http_success = None
    deadline = time.monotonic() + 120
    after = None
    while time.monotonic() < deadline:
        ready = replacement()
        try:
            candidate = fetch('/cart')
            cart_count(candidate)
            if first_http_success is None:
                first_http_success = round(time.monotonic() - start, 3)
            if ready:
                after = candidate
                evidence.log(test, 'REDIS_REPLACEMENT_READY', pods=ready)
                break
        except Exception as error:
            failed_http.append({'seconds': round(time.monotonic() - start, 3), 'error': error_text(error)})
            evidence.log(test, 'HTTP_UNAVAILABLE', **failed_http[-1])
        time.sleep(1)
    if after is None:
        raise RuntimeError('Redis/cart did not recover within 120s of pod deletion')
    after_count = cart_count(after)
    ready_seconds = round(time.monotonic() - start, 3)
    (evidence.directory / 'cart-after.html').write_text(after)
    healthy(evidence, test)
    lost = after_count == 0
    details = {'before_count': before_count, 'after_count': after_count, 'cart_wiped': lost,
               'same_session': session, 'data_empty_dir': empty_dir,
               'replacement_and_cart_ready_s': ready_seconds,
               'first_successful_http_s': first_http_success, 'observed_failed_http': failed_http}
    if lost:
        why = ('Redis has one replica and /data uses emptyDir, which is lost on pod replacement.'
               if empty_dir else 'Cart loss was observed; inspect the saved deployment and Redis configuration for its cause.')
        fix = 'Use persistent Redis storage with persistence enabled; evaluate replication and recovery behavior.'
    else:
        why = 'The isolated cart survived pod replacement; the empty-cart hypothesis was not reproduced.'
        fix = 'Review saved storage configuration and repeat after any persistence changes.'
    report = (f'Before: {before_count} item(s). After: {after_count}. Cart wiped: {lost}.\n'
              f'{why}\n{fix}\nEvidence: {evidence.directory}\n'
              f'Observed failed HTTP samples: {len(failed_http)}; this is sampled downtime, not an exact outage duration.\n')
    (evidence.directory / 'redis-finding.txt').write_text(report)
    (inject.ROOT / 'runs' / 'redis-finding.txt').write_text(report)
    evidence.result(test, 'FINDING', **details)
    save_logs(evidence, test, 'redis-cart')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['killswitch', 'redis'])
    parser.add_argument('--frontend-url', default='http://127.0.0.1:8080')
    args = parser.parse_args()
    evidence = Evidence(args.command)
    print(f'Evidence directory: {evidence.directory}', flush=True)
    cases = [('ad-service-health-trigger', lambda: health_trigger(evidence)),
             ('guard-sigkill-failsafe', lambda: crash_failsafe(evidence)),
             ('manual-abort', lambda: abort_checkpoint(evidence))] if args.command == 'killswitch' else [
                 ('redis-cart-persistence', lambda: redis_finding(evidence, args.frontend_url))]
    for name, case in cases:
        try:
            case()
        except KeyboardInterrupt:
            evidence.result(name, 'FAIL', reason='Interrupted; check cleanup events before rerunning')
            return 130
        except Exception as error:
            evidence.result(name, 'FAIL', reason=error_text(error))
            if args.command == 'redis':
                report = f'Redis checkpoint failed: {error_text(error)}\nEvidence: {evidence.directory}\nNo persistence conclusion can be drawn from this failed test.\n'
                (evidence.directory / 'redis-finding.txt').write_text(report)
                (inject.ROOT / 'runs' / 'redis-finding.txt').write_text(report)
    print(f'Summary: {evidence.directory / "summary.json"}', flush=True)
    return int(any(result['outcome'] == 'FAIL' for result in evidence.results))


if __name__ == '__main__':
    raise SystemExit(main())
