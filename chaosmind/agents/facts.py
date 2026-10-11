"""Read-only architecture facts + code-computed risk score. No AI here.

python3 -m chaosmind.agents.facts [--workloads runs/.../workloads-initial.json]
"""
import argparse
import json

from chaosmind import app, inject

# What ChaosMind knows about this app comes from its profile (apps/<name>/profile.json, chaosmind/app.py):
# which calls a caller tolerates (reviewed in the app's source; every other call is fatal to the caller), what every
# page needs, and the service that orchestrates the key transaction (checkout in Online Boutique).
IGNORE = app.IGNORE  # our traffic tool, not part of the system under test
SOFT_CALLS = app.SOFT_CALLS
EVERY_PAGE = app.EVERY_PAGE
JOURNEY = app.JOURNEY


def severity(s):
    """The severity rubric, applied by code from facts so it can't drift between runs (the model rated every
    single-replica service critical). Returns (severity, reason)."""
    one = s['replicas'] < 2
    if s['stateful_without_pvc']:
        return 'critical', 'stateful without a persistent volume: a restart loses data'
    if s['site_fails_without_it'] and one:
        return 'critical', 'single replica that every page needs: one pod failure takes the site down'
    if s['checkout_fails_without_it'] and one:
        return 'high', 'single replica that every purchase needs: one pod failure stops checkout'
    if s['site_fails_without_it'] or s['checkout_fails_without_it']:
        needed = 'every page' if s['site_fails_without_it'] else 'every purchase'
        return 'medium', f"{s['replicas']} replicas, so one pod failure is absorbed; {needed} still needs it (no PDB or HPA)"
    if s['on_checkout_path'] or s['hard_callers']:
        return 'medium', 'a purchase or feature step whose failure is tolerated: it fails silently'
    return 'low', 'optional: every caller tolerates its failure, so it should fail gracefully'


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


def blast_share(facts, target):
    """Fraction of the system inside the target's blast radius (0 if unknown)."""
    s = facts['services'].get(target) if facts else None
    return round(len(s['blast_radius']) / len(facts['services']), 3) if s and s.get('blast_radius') else 0.0


def collect(workloads=None, pdbs=None, hpas=None):
    """Live cluster when workloads is None; otherwise a saved `kubectl get deployments -o json`."""
    live = workloads is None
    deployments = kube_items('deployments') if live else [i for i in workloads['items'] if i['kind'] == 'Deployment']
    if pdbs is None:
        pdbs = {p['spec'].get('selector', {}).get('matchLabels', {}).get(app.SERVICE_LABEL) for p in kube_items('pdb')} if live else set()
    if hpas is None:
        hpas = {h['spec']['scaleTargetRef']['name'] for h in kube_items('hpa')} if live else set()
    services, calls, groups = {}, {}, {}
    for d in deployments:  # one service per label value; several deployments (e.g. versions) can share it
        service = d['spec']['template']['metadata'].get('labels', {}).get(app.SERVICE_LABEL) or d['metadata']['name']
        if service not in IGNORE and d['metadata']['name'] not in IGNORE:
            groups.setdefault(service, []).append(d)
    for name, ds in groups.items():
        pods = [d['spec']['template']['spec'] for d in ds]
        containers = [c for pod in pods for c in pod['containers']]
        if 'env_suffix' in app.CALLS:  # e.g. Online Boutique: every *_ADDR variable is a call
            calls[name] = {e['value'].split(':')[0] for c in containers for e in c.get('env', [])
                           if e['name'].endswith(app.CALLS['env_suffix']) and e.get('value')}
        else:  # calls listed in the profile (apps whose services find each other by fixed hostnames)
            calls[name] = {b for a, b in app.CALLS['edges'] if a == name}
        volumes = sorted({k for pod in pods for v in pod.get('volumes', []) for k in v if k != 'name'})
        services[name] = {
            'replicas': sum(d['spec'].get('replicas', 1) for d in ds),
            'readiness_probe': all('readinessProbe' in c for c in containers),
            'liveness_probe': all('livenessProbe' in c for c in containers),
            'cpu_memory_limits': all(c.get('resources', {}).get('limits') for c in containers),
            'volumes': volumes,
            # data that a restart loses: emptyDir scratch space (/tmp, logs) isn't state, so the profile names the services
            # that keep data (Online Boutique: redis-cart); without that list, any emptyDir counts
            'stateful_without_pvc': 'persistentVolumeClaim' not in volumes and (
                name in app.STATEFUL if 'stateful_services' in app.PROFILE else 'emptyDir' in volumes),
            'pdb': name in pdbs, 'hpa': name in hpas or any(d['metadata']['name'] in hpas for d in ds)}
        if len(ds) > 1:
            services[name]['deployments'] = sorted(d['metadata']['name'] for d in ds)
    # Drop edges to services that aren't deployed (e.g. the optional shopping assistant).
    calls = {n: sorted(c & services.keys()) for n, c in calls.items()}
    callers = {n: sorted(m for m in services if n in calls[m]) for n in services}
    checkout_path = reach(JOURNEY, calls) | {JOURNEY} if JOURNEY in services else set()
    hard_calls = {n: [c for c in cs if (n, c) not in SOFT_CALLS] for n, cs in calls.items()}
    checkout_needs = reach(JOURNEY, hard_calls) | {JOURNEY} if JOURNEY in services else set()
    page_calls = {n: [c for c in cs if n not in EVERY_PAGE or c in EVERY_PAGE[n]] for n, cs in hard_calls.items()}
    entrypoints = [n for n in services if not callers[n] and calls[n]]
    site_needs = set(entrypoints).union(*(reach(e, page_calls) for e in entrypoints))
    for name, s in services.items():
        entrypoint = name in entrypoints
        # on_checkout_path: checkout calls it (directly or not). checkout_fails_without_it: a purchase can't complete
        # without it (the entrypoint, or a fatal dependency of checkout). They differ for emailservice.
        s.update(calls=calls[name], callers=callers[name], dependents=sorted(reach(name, callers)),
                 on_checkout_path=name in checkout_path, entrypoint=entrypoint,
                 checkout_fails_without_it=entrypoint or name in checkout_needs,
                 site_fails_without_it=name in site_needs,
                 hard_callers=sorted(m for m in services if name in hard_calls[m]))
        # Blast radius: what breaks with it. Itself plus every service that (transitively) calls it; for the single
        # entrypoint, everything, because customers reach every service through it.
        s['blast_radius'] = sorted(services) if s['entrypoint'] else sorted({name, *s['dependents']})
        s['risk_score'] = risk_score(s)
        s['severity'], s['severity_reason'] = severity(s)
    return {'app': app.PROFILE.get('name', app.NAME), 'source': 'live cluster' if live else 'saved workloads file',
            'pdb_hpa_known': live or bool(pdbs or hpas),
            'services': dict(sorted(services.items(), key=lambda kv: -kv[1]['risk_score']))}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workloads', help='saved deployments JSON (offline); default: live cluster')
    args = parser.parse_args()
    print(json.dumps(collect(json.load(open(args.workloads)) if args.workloads else None), indent=1))
