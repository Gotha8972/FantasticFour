"""One catalog pod kill with recorded traffic and replacement evidence."""
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import time
import uuid

from chaosmind import inject
from chaosmind.guard import LIMITS, breach
from chaosmind.monitor import snapshot


def main():
    active = inject.running()
    if active:
        raise RuntimeError(f'Unrecovered experiments exist: {active}')
    initial = snapshot()
    if initial['unhealthy_services'] or breach(initial, LIMITS):
        raise RuntimeError('Preflight health/traffic exceeds approved guard limits')
    pods = json.loads(inject.kubectl('get', 'pods', '-n', inject.NS,
                                  '-l', 'app=productcatalogservice', '-o', 'json'))['items']
    ready = [p for p in pods if not p['metadata'].get('deletionTimestamp') and
             any(c['type'] == 'Ready' and c['status'] == 'True'
                 for c in p.get('status', {}).get('conditions', []))]
    if not ready:
        raise RuntimeError('This demonstration requires at least one ready catalog pod')
    initial_uids = {p['metadata']['uid'] for p in pods}
    victim = sorted(ready, key=lambda p: p['metadata']['name'])[0]['metadata']
    print(f'Catalog has {len(ready)} ready replicas; selecting one pod: {victim["name"]}', flush=True)
    token = uuid.uuid4().hex[:10]
    name = f'grafana-pod-kill-{token}'
    directory = inject.ROOT / 'runs' / name
    directory.mkdir(parents=True)
    print(f'Artifacts: {directory}', flush=True)
    manifest = {'apiVersion': 'chaos-mesh.org/v1alpha1', 'kind': 'PodChaos',
                'metadata': {'name': name, 'namespace': inject.NS,
                             'labels': {'app.kubernetes.io/part-of': inject.OWNER}},
                'spec': {'action': 'pod-kill', 'mode': 'one',
                         'selector': {'namespaces': [inject.NS],
                                      'pods': {inject.NS: [victim['name']]}}}}
    (directory / 'experiment.json').write_text(json.dumps(manifest, indent=2))
    (directory / 'victim.json').write_text(json.dumps(victim, indent=2))
    attempted = False
    replaced = False
    healthy = False
    try:
        with (directory / 'metrics.csv').open('w', newline='') as handle:
            fields = ['utc', 'phase', 'users', 'rps', 'error_rate', 'p95_ms',
                      'requests', 'failures', 'unhealthy_services', 'catalog_pod_uids', 'error']
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for phase, duration in [('baseline', 60), ('after-kill', 120)]:
                if phase == 'after-kill':
                    # Exact pod-name selection prevents selecting its replacement.
                    attempted = True
                    inject.kubectl('create', '-f', '-', stdin=json.dumps(manifest))
                    print(f'KILL REQUESTED: {victim["name"]}; observe availability and errors.', flush=True)
                deadline = time.monotonic() + duration
                while time.monotonic() < deadline:
                    row = {'utc': datetime.now(timezone.utc).isoformat(), 'phase': phase}
                    try:
                        snap = snapshot()
                        row.update({key: snap[key] for key in fields if key in snap})
                        uids = snap['pod_uids'].get('productcatalogservice', [])
                        row['catalog_pod_uids'] = json.dumps(uids)
                        row['unhealthy_services'] = json.dumps(snap['unhealthy_services'])
                        if phase == 'baseline' and (snap['unhealthy_services'] or breach(snap, LIMITS)):
                            raise RuntimeError('Baseline became unhealthy; refusing the kill')
                        if phase == 'after-kill':
                            replaced = victim['uid'] not in uids and bool(set(uids) - initial_uids)
                            healthy = replaced and not snap['unhealthy_services'] and not breach(snap, LIMITS)
                        print(f'{phase}: users={snap["users"]} rps={snap["rps"]} '
                              f'errors={snap["error_rate"]:.1%} p95={snap["p95_ms"]}ms '
                              f'unhealthy={snap["unhealthy_services"]}', flush=True)
                    except Exception as error:
                        row['error'] = str(error)
                        if phase == 'after-kill':
                            healthy = False
                        if phase == 'baseline':
                            writer.writerow(row)
                            handle.flush()
                            raise
                    writer.writerow(row)
                    handle.flush()
                    time.sleep(2)
        report = {'replacement_observed': replaced, 'healthy_at_end': healthy,
                  'original_pod_uid': victim['uid'],
                  'initial_ready_replicas': len(ready)}
        (directory / 'result.json').write_text(json.dumps(report, indent=2))
        if not healthy:
            raise RuntimeError('Replacement and healthy recovery not confirmed within 120 seconds')
    finally:
        if attempted:
            try:
                state = inject.kubectl('get', 'podchaos', name, '-n', inject.NS, '-o', 'json')
                (directory / 'chaos-status.json').write_text(state)
            finally:
                inject.kubectl('delete', 'podchaos', name, '-n', inject.NS,
                               '--ignore-not-found', '--wait=false')
        for suffix in ('stats', 'stats_history', 'failures'):
            try:
                raw = inject.kubectl('exec', 'deployment/loadgenerator', '-n', inject.NS,
                                     '-c', 'main', '--', 'cat', f'/stats/load_{suffix}.csv')
                (directory / f'load_{suffix}.csv').write_text(raw)
            except Exception as error:
                print(f'CSV export failed: {error}', flush=True)
    print('Recovered with a different catalog pod UID. No further kills requested.', flush=True)


if __name__ == '__main__':
    main()
