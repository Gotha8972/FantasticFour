"""Infrastructure adapters. Models never receive command execution capabilities."""
import copy
import json
import os
import subprocess
import time
from typing import Protocol

import httpx

from .schema import ApplicationProfile, Experiment, Measurement, digest


class Adapter(Protocol):
    simulated: bool
    def discover(self) -> dict: ...
    def sample(self) -> Measurement: ...
    def prepare(self, operation: str, experiment: Experiment, topology: dict) -> dict: ...
    def inject(self, handle: dict) -> None: ...
    def confirmed(self, handle: dict) -> bool: ...
    def cleanup(self, handle: dict) -> None: ...
    def recovered(self, handle: dict) -> bool: ...


class OfflineAdapter:
    simulated = True

    def __init__(self, profile):
        self.profile = profile
        self.fixture = copy.deepcopy(profile.fixture)
        self.active = None
        self.index = 0

    def discover(self):
        services = self.fixture['services']
        return {'services': services, 'dependencies': self.fixture.get('dependencies', []),
                'source': 'offline_fixture', 'revision': digest(services)}

    def sample(self):
        samples = self.fixture.get('during', []) if self.active else []
        data = samples[min(self.index, len(samples) - 1)] if samples else self.fixture['baseline']
        self.index += 1
        return Measurement(timestamp=time.time(), source='offline_simulation', **data)

    def prepare(self, operation, experiment, topology):
        return {'id': operation, 'experiment': experiment.model_dump(), 'simulated': True}

    def inject(self, handle):
        self.active = handle
        self.index = 0

    def confirmed(self, handle):
        return self.active is not None

    def cleanup(self, handle):
        self.active = None

    def recovered(self, handle):
        return self.active is None


class KubernetesAdapter:
    """Namespace-scoped kubectl and Prometheus, with exact-pod Chaos Mesh selectors."""
    simulated = False

    def __init__(self, profile: ApplicationProfile):
        self.profile = profile
        self.settings = profile.kubernetes

    def kubectl(self, *args, payload=None, missing=False):
        command = ['kubectl']
        if self.settings.kubeconfig:
            command += ['--kubeconfig', self.settings.kubeconfig]
        if self.settings.context:
            command += ['--context', self.settings.context]
        command += ['-n', self.settings.namespace, *args]
        proc = subprocess.run(command, input=json.dumps(payload) if payload else None,
                              text=True, capture_output=True, timeout=25)
        if proc.returncode:
            if missing and 'NotFound' in proc.stderr:
                return None
            # Do not return credential-bearing CLI output to the API/model.
            raise RuntimeError('Kubernetes operation failed; inspect cluster access and namespace')
        return json.loads(proc.stdout) if proc.stdout.strip() else None

    def discover(self):
        resources = self.kubectl('get', 'deployments,statefulsets,services,pods,poddisruptionbudgets,horizontalpodautoscalers', '-o', 'json')['items']
        pods = [r for r in resources if r['kind'] == 'Pod']
        services = {}
        routes = {}
        for resource in resources:
            kind = resource['kind']
            name = resource['metadata']['name']
            spec = resource.get('spec', {})
            if kind not in ('Deployment', 'StatefulSet'):
                continue
            labels = spec['selector'].get('matchLabels', {})
            if spec['selector'].get('matchExpressions'):
                continue  # Unsupported selectors must not accidentally broaden scope.
            selected = [p for p in pods if labels and all(p['metadata'].get('labels', {}).get(k) == v for k, v in labels.items())]
            containers = spec['template']['spec']['containers']
            services[name] = {'kind': kind, 'replicas': spec.get('replicas', 1),
                'ready': sum(self.pod_ready(p) for p in selected),
                'images': [c['image'] for c in containers], 'selector': labels,
                'configuration_digest': digest(spec),
                'pods': [{'name': p['metadata']['name'], 'uid': p['metadata']['uid'], 'ready': self.pod_ready(p)} for p in selected],
                'persistent_storage': any('persistentVolumeClaim' in v for v in spec['template']['spec'].get('volumes', [])) or bool(spec.get('volumeClaimTemplates')),
                'readiness_probes': all('readinessProbe' in c for c in containers),
                'pdb': any(r['kind'] == 'PodDisruptionBudget' and r.get('spec', {}).get('selector', {}).get('matchLabels') and all(spec['template']['metadata'].get('labels', {}).get(k) == v for k, v in r['spec']['selector']['matchLabels'].items()) for r in resources),
                'autoscaling': any(r['kind'] == 'HorizontalPodAutoscaler' and r.get('spec', {}).get('scaleTargetRef', {}).get('name') == name for r in resources)}
            for route in resources:
                selector = route.get('spec', {}).get('selector', {})
                if route['kind'] == 'Service' and selector and all(spec['template']['metadata'].get('labels', {}).get(k) == v for k, v in selector.items()):
                    routes[route['metadata']['name']] = name
        dependencies = []
        for resource in resources:
            caller = resource['metadata']['name']
            if resource['kind'] not in ('Deployment', 'StatefulSet') or caller not in services:
                continue
            for container in resource['spec']['template']['spec']['containers']:
                for env in container.get('env', []):
                    # Only retain references to discovered service DNS names, never env values.
                    value = env.get('value', '').split('://')[-1].split(':')[0].split('/')[0].split('.')[0]
                    if value in routes and routes[value] != caller:
                        dependencies.append({'from': caller, 'to': routes[value], 'evidence': 'environment reference: ' + env['name'], 'confidence': 'inferred'})
        signature = {name: {k: v for k, v in data.items() if k not in ('pods', 'ready')} for name, data in services.items()}
        return {'services': services, 'dependencies': dependencies, 'source': 'kubernetes_api', 'revision': digest(signature)}

    @staticmethod
    def pod_ready(pod):
        return not pod['metadata'].get('deletionTimestamp') and any(c['type'] == 'Ready' and c['status'] == 'True' for c in pod.get('status', {}).get('conditions', []))

    def sample(self):
        headers = {}
        if self.settings.prometheus_token_env:
            token = os.environ.get(self.settings.prometheus_token_env)
            if not token:
                raise RuntimeError('Prometheus credential environment variable is missing')
            headers['Authorization'] = 'Bearer ' + token
        values, timestamps = {}, []
        with httpx.Client(timeout=10, headers=headers) as client:
            for key, query in self.settings.queries.items():
                response = client.get(self.settings.prometheus_url.rstrip('/') + '/api/v1/query', params={'query': query})
                response.raise_for_status()
                result = response.json()
                rows = result.get('data', {}).get('result', [])
                if result.get('status') != 'success' or len(rows) != 1 or 'value' not in rows[0]:
                    raise RuntimeError('Each telemetry query must return exactly one fresh numeric series')
                timestamp, value = rows[0]['value']
                timestamps.append(float(timestamp))
                values[key] = float(value)
        topology = self.discover()
        unhealthy = [name for name, service in topology['services'].items() if service['ready'] < service['replicas']]
        # Instant query timestamps alone cannot establish exporter freshness. Profiles can provide
        # a source_age_s query (e.g. time() minus the exporter data timestamp).
        age = values.pop('source_age_s', None)
        if age is None or not 0 <= age <= self.profile.limits.max_metrics_age_s:
            raise RuntimeError('Missing or stale source_age_s telemetry')
        return Measurement(timestamp=min(timestamps), source='prometheus', unhealthy_services=unhealthy, **values)

    def prepare(self, operation, experiment, topology):
        service = topology['services'][experiment.target]
        ready = sorted(p['name'] for p in service['pods'] if p['ready'])
        if not ready:
            raise RuntimeError('Target has no Ready pod')
        name = 'cm-' + operation[:24]
        spec = {'action': {'pod_kill': 'pod-kill', 'network_delay': 'delay', 'network_loss': 'loss'}[experiment.fault],
                'mode': 'one', 'selector': {'pods': {self.settings.namespace: [ready[0]]}},
                'duration': str(experiment.duration_s) + 's'}
        kind = 'PodChaos' if experiment.fault == 'pod_kill' else 'NetworkChaos'
        if kind == 'NetworkChaos':
            spec['direction'] = 'to'
            if experiment.fault == 'network_delay':
                spec['delay'] = {'latency': str(experiment.params['latency_ms']) + 'ms', 'correlation': '0', 'jitter': '0ms'}
            else:
                spec['loss'] = {'loss': str(experiment.params['loss_percent']), 'correlation': '0'}
        manifest = {'apiVersion': 'chaos-mesh.org/v1alpha1', 'kind': kind,
                    'metadata': {'name': name, 'namespace': self.settings.namespace,
                                 'labels': {'app.kubernetes.io/managed-by': 'chaosmind-portable'},
                                 'annotations': {'chaosmind/operation': operation}}, 'spec': spec}
        return {'id': operation, 'kind': kind, 'name': name, 'manifest': manifest,
                'target': experiment.target, 'old_uids': [p['uid'] for p in service['pods']]}

    def resource(self, handle):
        return self.kubectl('get', handle['kind'], handle['name'], '-o', 'json', missing=True)

    def owned(self, resource, handle):
        if resource['metadata'].get('annotations', {}).get('chaosmind/operation') != handle['id']:
            raise RuntimeError('Chaos resource ownership mismatch')

    def inject(self, handle):
        existing = self.resource(handle)
        if existing:
            self.owned(existing, handle)
            return
        # create, not apply: an existing resource must never be overwritten.
        self.kubectl('create', '-f', '-', '-o', 'json', payload=handle['manifest'])

    def confirmed(self, handle):
        resource = self.resource(handle)
        if not resource:
            return False
        self.owned(resource, handle)
        records = resource.get('status', {}).get('experiment', {}).get('containerRecords', [])
        return bool(records) and all(r.get('phase') == 'Injected' and r.get('injectedCount', 0) > 0 for r in records)

    def cleanup(self, handle):
        resource = self.resource(handle)
        if resource:
            self.owned(resource, handle)
            self.kubectl('delete', handle['kind'], handle['name'], '--wait=false', '-o', 'json')

    def recovered(self, handle):
        if self.resource(handle):
            return False  # Finalizer removal confirms Chaos Mesh finished cleanup.
        service = self.discover()['services'].get(handle['target'])
        return service is not None and service['ready'] >= service['replicas']


def make_adapter(profile):
    return OfflineAdapter(profile) if profile.adapter == 'offline' else KubernetesAdapter(profile)
