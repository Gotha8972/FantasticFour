"""Read-only architecture facts + code-computed risk score. No AI here.

python3 -m chaosmind.agents.facts [--workloads runs/.../workloads-initial.json]
"""
import argparse
import json

from chaosmind import inject

IGNORE = {'loadgenerator'}  # our traffic tool, not part of the system under test


def kube_items(kind):
    return json.loads(inject.kubectl('get', kind, '-n', inject.NS, '-o', 'json'))['items']


def reach(start, edges):
    seen, stack = set(), [start]
    while stack:
        for nxt in edges[stack.pop()]:
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return seen


def risk_score(s):
    # ponytail: hand-tuned weights; the auditor (AI) re-ranks with judgement on top of this.
    return (4 * s['stateful_without_pvc'] + 2 * (s['replicas'] < 2) + len(s['dependents'])
            + 2 * s['on_checkout_path'] + 3 * s['entrypoint'] + (not s['readiness_probe'])
            + (not s['liveness_probe']) + (not s['cpu_memory_limits']) + (not s['pdb']) + (not s['hpa']))


def collect(workloads=None, pdbs=None, hpas=None):
    """Live cluster when workloads is None; otherwise a saved `kubectl get deployments -o json`."""
    live = workloads is None
    deployments = kube_items('deployments') if live else [i for i in workloads['items'] if i['kind'] == 'Deployment']
    if pdbs is None:
        pdbs = {p['spec'].get('selector', {}).get('matchLabels', {}).get('app') for p in kube_items('pdb')} if live else set()
    if hpas is None:
        hpas = {h['spec']['scaleTargetRef']['name'] for h in kube_items('hpa')} if live else set()
    services, calls = {}, {}
    for d in deployments:
        name = d['metadata']['name']
        if name in IGNORE:
            continue
        pod = d['spec']['template']['spec']
        containers = pod['containers']
        calls[name] = {e['value'].split(':')[0] for c in containers for e in c.get('env', [])
                       if e['name'].endswith('_ADDR') and e.get('value')}
        volumes = sorted({k for v in pod.get('volumes', []) for k in v if k != 'name'})
        services[name] = {
            'replicas': d['spec'].get('replicas', 1),
            'readiness_probe': all('readinessProbe' in c for c in containers),
            'liveness_probe': all('livenessProbe' in c for c in containers),
            'cpu_memory_limits': all(c.get('resources', {}).get('limits') for c in containers),
            'volumes': volumes,
            'stateful_without_pvc': 'emptyDir' in volumes and 'persistentVolumeClaim' not in volumes,
            'pdb': name in pdbs, 'hpa': name in hpas}
    # Drop edges to services that aren't deployed (e.g. the optional shopping assistant).
    calls = {n: sorted(c & services.keys()) for n, c in calls.items()}
    callers = {n: sorted(m for m in services if n in calls[m]) for n in services}
    checkout_path = reach('checkoutservice', calls) | {'checkoutservice'} if 'checkoutservice' in services else set()
    for name, s in services.items():
        s.update(calls=calls[name], callers=callers[name], dependents=sorted(reach(name, callers)),
                 on_checkout_path=name in checkout_path, entrypoint=not callers[name] and bool(calls[name]))
        s['risk_score'] = risk_score(s)
    return {'source': 'live cluster' if live else 'saved workloads file',
            'pdb_hpa_known': live or bool(pdbs or hpas),
            'services': dict(sorted(services.items(), key=lambda kv: -kv[1]['risk_score']))}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workloads', help='saved deployments JSON (offline); default: live cluster')
    args = parser.parse_args()
    print(json.dumps(collect(json.load(open(args.workloads)) if args.workloads else None), indent=1))
