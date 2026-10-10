"""Validated contracts shared by the graph, API, and adapters."""
import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class Limits(Contract):
    error_rate: float = Field(default=.05, ge=0, le=1)
    p95_ms: float = Field(default=1000, gt=0)
    max_unhealthy: int = Field(default=2, ge=0, le=10)
    max_duration_s: int = Field(default=60, ge=1, le=120)
    max_delay_ms: int = Field(default=500, ge=1, le=2000)
    max_loss_percent: float = Field(default=10, gt=0, le=50)
    poll_s: float = Field(default=2, ge=.5, le=10)
    baseline_samples: int = Field(default=3, ge=3, le=30)
    recovery_timeout_s: int = Field(default=60, ge=1, le=120)
    max_metrics_age_s: int = Field(default=15, ge=1, le=60)


class ModelSettings(Contract):
    adapter: Literal['rules', 'chat_completions'] = 'rules'
    base_url: str | None = None
    model: str | None = None
    api_key_env: str | None = None

    @model_validator(mode='after')
    def configured(self):
        if self.adapter == 'chat_completions':
            if not (self.base_url and self.model and self.api_key_env):
                raise ValueError('chat_completions requires base_url, model, and api_key_env')
            if not self.base_url.startswith('https://'):
                raise ValueError('Model endpoint must use HTTPS')
        return self


class KubernetesSettings(Contract):
    namespace: str = Field(pattern=r'^[a-z0-9][a-z0-9-]{0,62}$')
    context: str | None = None
    kubeconfig: str | None = None
    prometheus_url: str
    prometheus_token_env: str | None = None
    queries: dict[str, str]

    @model_validator(mode='after')
    def metrics(self):
        if not {'error_rate', 'p95_ms', 'rps', 'users', 'source_age_s'} <= self.queries.keys():
            raise ValueError('Queries must include error_rate, p95_ms, rps, users, and source_age_s')
        if not self.prometheus_url.startswith(('http://', 'https://')):
            raise ValueError('Invalid Prometheus URL')
        return self


class ApplicationProfile(Contract):
    id: str = Field(pattern=r'^[a-z0-9][a-z0-9-]{0,62}$')
    adapter: Literal['offline', 'kubernetes']
    allowed_targets: list[str] = Field(min_length=1)
    allowed_faults: list[Literal['pod_kill', 'network_delay', 'network_loss']] = Field(min_length=1)
    customer_journey: str = Field(min_length=1)
    expected_users: int = Field(ge=1, le=100000)
    limits: Limits = Field(default_factory=Limits)
    model: ModelSettings = Field(default_factory=ModelSettings)
    kubernetes: KubernetesSettings | None = None
    fixture: dict | None = None

    @model_validator(mode='after')
    def adapter_settings(self):
        if self.adapter == 'kubernetes' and self.kubernetes is None:
            raise ValueError('Kubernetes settings required')
        if self.adapter == 'offline' and self.fixture is None:
            raise ValueError('Offline fixture required')
        if len(set(self.allowed_targets)) != len(self.allowed_targets):
            raise ValueError('Duplicate targets')
        return self


class Experiment(Contract):
    target: str
    fault: Literal['pod_kill', 'network_delay', 'network_loss']
    duration_s: int = Field(ge=1, le=120)
    params: dict[str, float] = Field(default_factory=dict)

    def check(self, profile: ApplicationProfile, topology: dict):
        if self.target not in profile.allowed_targets or self.target not in topology['services']:
            raise ValueError('Target is not discovered and authorized')
        if self.fault not in profile.allowed_faults:
            raise ValueError('Fault is not authorized')
        if self.duration_s > profile.limits.max_duration_s:
            raise ValueError('Duration exceeds profile limit')
        permitted = {'pod_kill': set(), 'network_delay': {'latency_ms'}, 'network_loss': {'loss_percent'}}[self.fault]
        if set(self.params) != permitted:
            raise ValueError('Incorrect fault parameters')
        if self.fault == 'network_delay' and not 0 < self.params['latency_ms'] <= profile.limits.max_delay_ms:
            raise ValueError('Delay exceeds profile limit')
        if self.fault == 'network_loss' and not 0 < self.params['loss_percent'] <= profile.limits.max_loss_percent:
            raise ValueError('Packet loss exceeds profile limit')
        return self


class Measurement(Contract):
    timestamp: float
    error_rate: float = Field(ge=0, le=1)
    p95_ms: float = Field(ge=0)
    rps: float = Field(gt=0)
    users: int = Field(ge=1)
    unhealthy_services: list[str] = Field(default_factory=list)
    integrity_violations: int = Field(default=0, ge=0)
    source: str


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def customer_breach(sample: Measurement, limits: Limits):
    return sample.error_rate > limits.error_rate or sample.p95_ms > limits.p95_ms or sample.integrity_violations > 0


def guard_breach(sample: Measurement, limits: Limits):
    return customer_breach(sample, limits) or len(sample.unhealthy_services) > limits.max_unhealthy
