"""Deterministic Chaos Mesh injection into this project's kind cluster."""
import argparse
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
NS = 'online-boutique'
CONTEXT = 'kind-online-boutique'
MAX_DURATION_S = 120
KINDS = {'pod_failure': 'PodChaos', 'network_delay': 'NetworkChaos', 'network_loss': 'NetworkChaos',
         'cpu_stress': 'StressChaos', 'pod_kill': 'PodChaos',
         'network_partition': 'NetworkChaos', 'disk_full': 'IOChaos'}
# Fault -> (param, default) that the Safety Checker ramps. pod_failure/pod_kill/network_partition have none.
INTENSITY = {'network_delay': ('latency', '500ms'), 'network_loss': ('loss', 10), 'cpu_stress': ('load', 50),
             'disk_full': ('percent', 100)}
DNS = r'[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?'
OWNER = 'chaosmind'
# Faults that have actually run live through the guard on our cluster. The AI only plans these unless
# --allow-unverified is passed. Add a fault here once a live guarded run has succeeded.
LIVE_VERIFIED = {'pod_failure', 'network_delay'}


def kubectl(*args, stdin=None, timeout=40):
    return subprocess.run(
        ['kubectl', '--kubeconfig', str(ROOT / '.runtime/kubeconfig'),
         '--context', CONTEXT, '--request-timeout=20s', *args],
        input=stdin, text=True, capture_output=True, check=True, timeout=timeout,
    ).stdout


def validate(exp):
    if exp.get('fault') not in KINDS:
        raise ValueError(f'unknown fault; allowed: {list(KINDS)}')
    for field in ('id', 'target'):
        if not isinstance(exp.get(field), str) or not re.fullmatch(
                r'[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?', exp[field]):
            raise ValueError(f'{field} must be a Kubernetes DNS label')
    duration = exp.get('duration_s')
    if type(duration) is not int or not 0 < duration <= MAX_DURATION_S:
        raise ValueError(f'duration_s must be an integer in 1..{MAX_DURATION_S}')
    if exp.get('namespace', NS) != NS:
        raise ValueError(f'only namespace {NS} is allowed')
    params = exp.get('params', {})
    if not isinstance(params, dict):
        raise ValueError('params must be an object')
    if exp['fault'] == 'network_delay':
        for key, default in (('latency', '500ms'), ('jitter', '50ms')):
            value = params.get(key, default)
            if not isinstance(value, str) or not re.fullmatch(r'\d+(?:\.\d+)?ms', value):
                raise ValueError(f'{key} must be a nonnegative duration in ms')
            if float(value[:-2]) > 2000:
                raise ValueError(f'{key} must be <= 2000ms')
    if exp['fault'] == 'network_loss':
        loss = params.get('loss', 10)
        if type(loss) not in (int, float) or not 0 < loss <= 50:
            raise ValueError('loss must be a percentage in (0, 50]')
    if exp['fault'] == 'cpu_stress':
        load, workers = params.get('load', 50), params.get('workers', 1)
        if type(load) is not int or not 0 < load <= 100:
            raise ValueError('load must be an integer in 1..100')
        if type(workers) is not int or not 1 <= workers <= 2:
            raise ValueError('workers must be 1 or 2')
    if exp['fault'] == 'network_partition':
        to = params.get('to')
        if not isinstance(to, str) or not re.fullmatch(DNS, to) or to == exp['target']:
            raise ValueError('network_partition needs params.to: another service to cut the target off from')
    if exp['fault'] == 'disk_full':
        path, percent = params.get('path', '/data'), params.get('percent', 100)
        if not isinstance(path, str) or not re.fullmatch(r'(/[A-Za-z0-9._-]+)+', path) or '..' in path:
            raise ValueError('disk_full path must be an absolute mount path like /data')
        if type(percent) is not int or not 0 < percent <= 100:
            raise ValueError('percent must be an integer in 1..100')


def manifest(exp):
    validate(exp)
    spec = {'mode': 'one', 'duration': f"{exp['duration_s']}s",
            'selector': {'namespaces': [NS], 'labelSelectors': {'app': exp['target']}}}
    params = exp.get('params', {})
    if exp['fault'] == 'network_delay':
        spec.update(action='delay', delay={'latency': params.get('latency', '500ms'),
                                          'jitter': params.get('jitter', '50ms'), 'correlation': '50'})
    elif exp['fault'] == 'network_loss':
        spec.update(action='loss', loss={'loss': str(params.get('loss', 10)), 'correlation': '25'})
    elif exp['fault'] == 'cpu_stress':
        spec['stressors'] = {'cpu': {'workers': params.get('workers', 1), 'load': params.get('load', 50)}}
    elif exp['fault'] == 'network_partition':
        # Failed dependency: target can no longer reach params.to
        spec.update(action='partition', direction='to',
                    target={'mode': 'all', 'selector': {'namespaces': [NS], 'labelSelectors': {'app': params['to']}}})
    elif exp['fault'] == 'disk_full':
        # Full disk: writes under the mount fail with ENOSPC (errno 28, "No space left on device")
        path = params.get('path', '/data')
        spec.update(action='fault', errno=28, percent=params.get('percent', 100), volumePath=path, path=f'{path}/**')
    elif exp['fault'] == 'pod_kill':
        spec['action'] = 'pod-kill'  # ponytail: not yet verified live; one-shot kill, guard still watches recovery
    else:
        spec['action'] = 'pod-failure'
    metadata = {'name': exp['id'], 'namespace': NS,
                'labels': {'app.kubernetes.io/part-of': OWNER}}
    if exp.get('_run_token'):
        metadata['annotations'] = {'chaosmind/run-token': exp['_run_token']}
    return {'apiVersion': 'chaos-mesh.org/v1alpha1', 'kind': KINDS[exp['fault']],
            'metadata': metadata, 'spec': spec}


def apply(exp, dry_run=False):
    validate(exp)
    deployment = json.loads(kubectl('get', 'deployment', exp['target'], '-n', NS, '-o', 'json'))
    if deployment['spec']['template']['metadata'].get('labels', {}).get('app') != exp['target']:
        raise ValueError("target deployment's app label does not match the selector")
    if deployment['spec'].get('replicas', 1) < 1:
        raise ValueError('target has no running replicas')
    params = exp.get('params', {})
    if exp['fault'] == 'network_partition':
        kubectl('get', 'deployment', params['to'], '-n', NS)  # raises if the dependency doesn't exist
    if exp['fault'] == 'disk_full':
        mounts = {m['mountPath'] for c in deployment['spec']['template']['spec']['containers']
                  for m in c.get('volumeMounts', [])}
        if params.get('path', '/data') not in mounts:
            raise ValueError(f"target has no volume mounted at {params.get('path', '/data')}")
    args = ['create', '-f', '-']
    if dry_run:
        args.append('--dry-run=server')
    kubectl(*args, stdin=json.dumps(manifest(exp)))
    return exp['id']


def status(exp):
    return json.loads(kubectl('get', KINDS[exp['fault']].lower(), exp['id'], '-n', NS, '-o', 'json'))


def injection_state(resource):
    state = resource.get('status', {})
    conditions = {c['type']: c['status'] == 'True' for c in state.get('conditions', [])}
    records = state.get('experiment', {}).get('containerRecords', [])
    injected = conditions.get('AllInjected', False) or bool(records) and all(
        r.get('injectedCount', 0) > 0 and r.get('phase') == 'Injected' for r in records)
    failures = [e.get('message', 'injection failed') for r in records
                for e in r.get('events', []) if e.get('type') == 'Failed']
    return {'injected': bool(injected), 'recovered': conditions.get('AllRecovered', False),
            'errors': failures, 'records': records}


def revert(exp):
    raw = kubectl('get', KINDS[exp['fault']].lower(), exp['id'], '-n', NS,
                  '--ignore-not-found', '-o', 'json')
    if not raw.strip():
        return
    metadata = json.loads(raw)['metadata']
    if metadata.get('labels', {}).get('app.kubernetes.io/part-of') != OWNER:
        raise ValueError('refusing to delete a resource not owned by chaosmind')
    if exp.get('_run_token') and metadata.get('annotations', {}).get('chaosmind/run-token') != exp['_run_token']:
        raise ValueError('refusing to delete a resource belonging to another run')
    kubectl('delete', KINDS[exp['fault']].lower(), exp['id'], '-n', NS,
            '--ignore-not-found', '--timeout=30s')


def running():
    items = json.loads(kubectl('get', 'podchaos,networkchaos,stresschaos,iochaos',
                               '-n', NS, '-o', 'json'))['items']
    return [f"{r['kind']}/{r['metadata']['name']}" for r in items
            if not injection_state(r)['recovered']]


def abort_all():
    kubectl('delete', 'podchaos,networkchaos,stresschaos,iochaos', '-n', NS,
            '-l', f'app.kubernetes.io/part-of={OWNER}', '--ignore-not-found', '--timeout=30s')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['apply', 'revert', 'abort', 'render', 'verify'])
    parser.add_argument('experiment', nargs='?')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    if args.command == 'abort':
        abort_all()
    else:
        if not args.experiment:
            parser.error('an experiment JSON file is required')
        exp = json.loads(Path(args.experiment).read_text())
        if args.command == 'render':
            print(json.dumps(manifest(exp), indent=2))
        elif args.command == 'apply':
            apply(exp, args.dry_run)
            print('Dry run accepted' if args.dry_run else 'Created; injection is not yet confirmed')
        elif args.command == 'verify':
            state = injection_state(status(exp))
            print(json.dumps(state, indent=2))
            return 0 if state['injected'] else 1
        else:
            revert(exp)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, subprocess.SubprocessError) as error:
        print(getattr(error, 'stderr', None) or str(error))
        raise SystemExit(1)
