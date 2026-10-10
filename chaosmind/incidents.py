"""Manual incident implementations with scoped resources and CSV evidence."""
import argparse
import json
import subprocess
import time
import uuid

from chaosmind import guard, inject
from chaosmind.monitor import snapshot
from chaosmind.runlog import RunLog

SCENARIOS = ('network-delay', 'network-loss', 'full-disk',
             'database-overload', 'failed-dependency', 'traffic-spike')


def load(users, rate):
    subprocess.run(['bash', str(inject.ROOT / 'scripts/load.sh'), 'start', str(users), str(rate)], check=True)


def read(resource, name):
    return json.loads(inject.kubectl('get', resource, name, '-n', inject.NS, '-o', 'json'))


def run(scenario, users=20, rate=2):
    if not 1 <= users <= 200 or not 1 <= rate <= 100:
        raise ValueError('Users must be 1–200 and spawn rate must be 1–100')
    active = inject.running()
    jobs = json.loads(inject.kubectl('get', 'jobs', '-n', inject.NS,
                                   '-l', 'boutique.local/incident=database-overload', '-o', 'json'))['items']
    if active or any(not j.get('status', {}).get('completionTime') for j in jobs):
        raise RuntimeError('An unrecovered experiment or database load job exists; stop it first')
    deployment = read('deployment', 'loadgenerator')
    original_replicas = deployment['spec'].get('replicas', 1)
    main = next(c for c in deployment['spec']['template']['spec']['containers'] if c['name'] == 'main')
    env = {e['name']: e.get('value') for e in main.get('env', [])}
    if not all(str(env.get(k, '')).isdigit() and int(env[k]) > 0 for k in ('USERS', 'RATE')):
        raise RuntimeError('Set explicit positive USERS and RATE on loadgenerator before using this runner')
    output = RunLog({'id': f'incident-{scenario}', 'fault': scenario, 'target': 'online-boutique'})
    print(f'Artifacts: {output.directory}', flush=True)
    log = output.log
    resource = None
    name = f'incident-{uuid.uuid4().hex[:10]}'
    changed_load = False
    probe = f'/data/{name}-probe.txt'
    probe_created = False
    result = 0

    def sample(stage):
        snap = snapshot()
        log('SNAPSHOT', stage=stage, **snap)
        return snap

    def observe(stage, seconds, stop_on_breach=True):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            snap = sample(stage)
            if stage == 'baseline' and snap['unhealthy_services']:
                raise RuntimeError('A service became unhealthy during baseline; refusing incident')
            if stop_on_breach and (b := guard.breach(snap, guard.LIMITS)):
                log('BREACH', metric=b[0], value=b[1], limit=b[2])
                if stage == 'baseline':
                    raise RuntimeError('Guard limits were exceeded during baseline; refusing incident')
                return
            if stage == 'injected' and resource == 'job':
                state = read('job', name).get('status', {})
                if state.get('failed'):
                    raise RuntimeError('Redis load job failed while running')
                if state.get('succeeded'):
                    log('LOAD_COMPLETED', reason='Redis benchmark completed its bounded request count')
                    return
            time.sleep(2)

    def probe_write():
        return inject.kubectl('exec', 'deployment/redis-cart', '-n', inject.NS,
                              '-c', 'redis', '--', 'sh', '-c', 'printf incident > "$1"', 'sh', probe)

    try:
        changed_load = True
        log('BASELINE_LOAD_REQUESTED', users=users, spawn_rate=rate)
        load(users, rate)
        # Allow Locust's recent window to populate after its rollout.
        time.sleep(15)
        snap = sample('preflight')
        if snap['unhealthy_services'] or guard.breach(snap, guard.LIMITS):
            raise RuntimeError('Preflight unhealthy or above approved guard limits')
        observe('baseline', 30)
        snap = sample('pre-injection')
        if snap['unhealthy_services'] or guard.breach(snap, guard.LIMITS):
            raise RuntimeError('Baseline became unhealthy; refusing incident')
        if scenario in ('network-delay', 'network-loss', 'failed-dependency'):
            fault, target, params = {
                'network-delay': ('network_delay', 'productcatalogservice', {'latency': '500ms', 'jitter': '50ms'}),
                'network-loss': ('network_loss', 'productcatalogservice', {'loss': 10}),
                'failed-dependency': ('pod_failure', 'shippingservice', {}),
            }[scenario]
            events = guard.run({'id': name, 'fault': fault, 'target': target,
                                'params': params, 'duration_s': 60})
            log('GUARD_FINISHED', guard_artifact=events[0].get('artifact_dir') if events else None)
            if any(e['event'] in ('REFUSED', 'ERROR', 'REVERT_FAILED', 'NOT_RECOVERED', 'INTERRUPTED') for e in events):
                result = 1
        elif scenario == 'traffic-spike':
            log('SPIKE_REQUESTED', users=200, spawn_rate=100,
                reason='Locust rollout resets counters; compare phases separately')
            load(200, 100)
            time.sleep(15)
            observe('spike', 60)
        else:
            if scenario == 'full-disk':
                inject.kubectl('get', 'crd', 'iochaos.chaos-mesh.org')
                redis = read('deployment', 'redis-cart')
                container = next(c for c in redis['spec']['template']['spec']['containers'] if c['name'] == 'redis')
                if not any(v['mountPath'] == '/data' for v in container.get('volumeMounts', [])):
                    raise RuntimeError('Redis has no /data volume mount to target')
                probe_created = True
                probe_write()
                resource = 'iochaos'
                manifest = {'apiVersion': 'chaos-mesh.org/v1alpha1', 'kind': 'IOChaos',
                            'spec': {'action': 'fault', 'mode': 'one',
                                     'selector': {'namespaces': [inject.NS], 'labelSelectors': {'app': 'redis-cart'}},
                                     'containerNames': ['redis'], 'volumePath': '/data', 'path': '/data/**/*',
                                     'methods': ['write', 'create', 'fsync'], 'errno': 28,
                                     'percent': 100, 'duration': '60s'}}
            else:
                resource = 'job'
                redis = read('deployment', 'redis-cart')
                image = next(c['image'] for c in redis['spec']['template']['spec']['containers'] if c['name'] == 'redis')
                manifest = {'apiVersion': 'batch/v1', 'kind': 'Job',
                            'spec': {'activeDeadlineSeconds': 120, 'backoffLimit': 0, 'ttlSecondsAfterFinished': 300,
                                     'template': {'metadata': {'labels': {'app': 'incident-db-load'}},
                                                  'spec': {'restartPolicy': 'Never',
                                                           'containers': [{'name': 'benchmark', 'image': image,
                                                                           'command': ['redis-benchmark', '-h', 'redis-cart', '-p', '6379',
                                                                                       '-c', '50', '-P', '4', '-n', '10000000',
                                                                                       '--csv', 'GET', f'{name}:unused-key'],
                                                                           'resources': {'requests': {'cpu': '100m', 'memory': '32Mi'},
                                                                                         'limits': {'cpu': '500m', 'memory': '128Mi'}}}]}}}}
            manifest['metadata'] = {'name': name, 'namespace': inject.NS,
                                    'labels': {'app.kubernetes.io/part-of': 'manual-incidents',
                                               'boutique.local/incident': scenario}}
            (output.directory / 'manifest.json').write_text(json.dumps(manifest, indent=2))
            created_at = time.monotonic()
            inject.kubectl('create', '-f', '-', stdin=json.dumps(manifest))
            log('CREATED', resource=resource, name=name)
            deadline = time.monotonic() + 60
            while True:
                status = read(resource, name)
                (output.directory / 'injection-status.json').write_text(json.dumps(status, indent=2))
                if resource == 'iochaos':
                    state = inject.injection_state(status)
                    if state['errors']:
                        raise RuntimeError('Disk injection failed: ' + state['errors'][-1])
                    ready = state['injected']
                else:
                    if status.get('status', {}).get('failed'):
                        raise RuntimeError('Redis benchmark job failed; inspect saved pod logs')
                    pods = json.loads(inject.kubectl('get', 'pods', '-n', inject.NS,
                                                   '-l', f'job-name={name}', '-o', 'json'))['items']
                    ready = bool(status.get('status', {}).get('succeeded')) or any(
                        any(c.get('ready') for c in p.get('status', {}).get('containerStatuses', [])) for p in pods)
                if ready:
                    log('INJECTED', resource=resource, name=name)
                    break
                if time.monotonic() >= deadline:
                    raise RuntimeError('Incident startup not confirmed within 60 seconds')
                if guard.breach(sample('injecting'), guard.LIMITS):
                    raise RuntimeError('Guard threshold exceeded during incident startup')
                time.sleep(2)
            if resource == 'iochaos':
                try:
                    probe_write()
                except subprocess.CalledProcessError as error:
                    verified = 'No space left on device' in (error.stderr or '')
                    log('DISK_PROBE', enospc_verified=verified, stderr=error.stderr)
                    if not verified:
                        raise RuntimeError('Write failed but ENOSPC was not confirmed')
                else:
                    raise RuntimeError('IOChaos reported injected, but write probe did not return ENOSPC')
            # Disk duration starts at creation, not at injection confirmation.
            remaining = 60 if resource == 'job' else max(0, 60 - (time.monotonic() - created_at))
            observe('injected', remaining)
    except KeyboardInterrupt:
        log('INTERRUPTED', reason='Ctrl-C; requesting cleanup')
        result = 130
    except Exception as error:
        log('ERROR', reason=getattr(error, 'stderr', None) or str(error))
        result = 1
    finally:
        if resource:
            if resource == 'job':
                try:
                    logs = inject.kubectl('logs', f'job/{name}', '-n', inject.NS, '--all-containers=true', '--tail=200')
                    (output.directory / 'benchmark.log').write_text(logs)
                except Exception as error:
                    log('LOG_EXPORT_FAILED', reason=str(error))
            try:
                inject.kubectl('delete', resource, name, '-n', inject.NS,
                               '--ignore-not-found', '--timeout=60s', timeout=70)
                log('REMOVED', resource=resource, name=name)
            except Exception as error:
                log('CLEANUP_FAILED', resource=resource, name=name, reason=str(error))
                result = 1
        if probe_created:
            try:
                inject.kubectl('exec', 'deployment/redis-cart', '-n', inject.NS,
                               '-c', 'redis', '--', 'rm', '-f', probe)
            except Exception as error:
                log('PROBE_CLEANUP_FAILED', reason=str(error))
                result = 1
        for suffix in ('stats', 'stats_history', 'failures'):
            try:
                data = inject.kubectl('exec', 'deployment/loadgenerator', '-n', inject.NS,
                                     '-c', 'main', '--', 'cat', f'/stats/load_{suffix}.csv')
                (output.directory / f'load_{suffix}.csv').write_text(data)
            except Exception as error:
                log('CSV_EXPORT_FAILED', reason=str(error))
        if changed_load:
            try:
                load(int(env['USERS']), int(env['RATE']))
                if original_replicas != 1:
                    inject.kubectl('scale', 'deployment/loadgenerator', '-n', inject.NS,
                                   f'--replicas={original_replicas}')
                log('LOAD_RESTORED', users=env['USERS'], replicas=original_replicas)
                if original_replicas:
                    time.sleep(15)
                    deadline = time.monotonic() + 120
                    while time.monotonic() < deadline:
                        snap = sample('recovery')
                        if not snap['unhealthy_services'] and not guard.breach(snap, guard.LIMITS):
                            log('HEALTHY')
                            break
                        time.sleep(2)
                    else:
                        log('NOT_RECOVERED', reason='Recovery not confirmed within 120 seconds')
                        result = 1
            except Exception as error:
                log('RECOVERY_ERROR', reason=str(error))
                result = 1
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('scenario', choices=SCENARIOS)
    parser.add_argument('--users', type=int, default=20)
    parser.add_argument('--rate', type=int, default=2)
    args = parser.parse_args()
    if not 1 <= args.users <= 200 or not 1 <= args.rate <= 100:
        parser.error('--users must be 1–200 and --rate must be 1–100')
    return run(args.scenario, args.users, args.rate)


if __name__ == '__main__':
    raise SystemExit(main())
