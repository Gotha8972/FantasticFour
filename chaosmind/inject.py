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
KINDS = {'pod_failure': 'PodChaos', 'network_delay': 'NetworkChaos'}
OWNER = 'chaosmind'


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


def manifest(exp):
    validate(exp)
    spec = {'mode': 'one', 'duration': f"{exp['duration_s']}s",
            'selector': {'namespaces': [NS], 'labelSelectors': {'app': exp['target']}}}
    if exp['fault'] == 'network_delay':
        params = exp.get('params', {})
        spec.update(action='delay', delay={'latency': params.get('latency', '500ms'),
                                          'jitter': params.get('jitter', '50ms'), 'correlation': '50'})
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
