"""Durable LangGraph assessment with guarded, journaled fault execution."""
from contextlib import contextmanager
import json
import fcntl
import math
from pathlib import Path
import sqlite3
import time
from typing import TypedDict
import uuid

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver

from .adapters import make_adapter
from .planning import audit, plan, recommendations
from .schema import ApplicationProfile, Contract, Experiment, customer_breach, guard_breach, digest
from pydantic import Field
from typing import Literal
from .store import Store


class RunRequest(Contract):
    mode: Literal['dry_run', 'execute'] = 'dry_run'
    trials: int = Field(default=3, ge=1, le=10)


class State(TypedDict, total=False):
    run_id: str
    request: dict
    topology: dict
    baseline: list[dict]
    findings: list[dict]
    experiment: dict
    trials: list[dict]
    report: dict


def wilson(k, n):
    if not n:
        return None
    z = 1.96
    center = (k / n + z*z / (2*n)) / (1 + z*z/n)
    half = z * math.sqrt(k/n*(1-k/n)/n + z*z/(4*n*n)) / (1 + z*z/n)
    return [max(0, center-half), min(1, center+half)]


class Workflow:
    def __init__(self, profile, store, adapter=None):
        self.profile = profile
        self.store = store
        self.adapter = adapter or make_adapter(profile)

    def event(self, state, stage, **details):
        self.store.event(state['run_id'], stage, **details)

    def valid_sample(self):
        sample = self.adapter.sample()
        age = time.time() - sample.timestamp
        if not -1 <= age <= self.profile.limits.max_metrics_age_s:
            raise RuntimeError('Telemetry is stale or has a future timestamp')
        if sample.users != self.profile.expected_users:
            raise RuntimeError('Traffic level does not match expected_users')
        return sample

    def pause(self, run_id):
        if not self.adapter.simulated:
            deadline = time.monotonic() + self.profile.limits.poll_s
            while time.monotonic() < deadline and not self.store.cancelled(run_id):
                time.sleep(min(.2, deadline - time.monotonic()))

    def discover(self, state):
        self.event(state, 'discover')
        topology = self.adapter.discover()
        return {'topology': topology}

    def baseline(self, state):
        self.event(state, 'baseline')
        samples = []
        previous = None
        for _ in range(self.profile.limits.baseline_samples):
            if self.store.cancelled(state['run_id']):
                raise RuntimeError('Assessment cancelled before injection')
            sample = self.valid_sample()
            if sample.unhealthy_services or guard_breach(sample, self.profile.limits):
                raise RuntimeError('Baseline is unhealthy; no fault was injected')
            if previous is not None and sample.timestamp <= previous:
                raise RuntimeError('Baseline telemetry did not advance')
            previous = sample.timestamp
            samples.append(sample.model_dump())
            self.pause(state['run_id'])
        return {'baseline': samples}

    def reason(self, state):
        self.event(state, 'audit_and_plan')
        findings = audit(state['topology'], self.profile)
        experiment = plan(state['topology'], self.profile, findings)
        return {'findings': findings, 'experiment': experiment.model_dump()}

    def execute(self, state):
        results = list(state.get('trials', []))
        for index in range(len(results), state['request']['trials']):
            if self.store.cancelled(state['run_id']):
                break
            result = self.trial(state, index)
            results.append(result)
            if result['status'] not in ('passed', 'breached') or not result['cleanup_confirmed'] or result.get('guard_tripped'):
                break
        return {'trials': results}

    def trial(self, state, index):
        run_id = state['run_id']
        operation = digest([run_id, index])[:32]
        saved = self.store.operation(operation)
        if saved and 'result' in saved:
            return saved['result']  # Node replay does not repeat completed fault trials.
        if saved:
            # An intent may have been committed before creation; never assume absence means safe to retry.
            handle = saved['handle']
            result = {'status': 'invalid', 'reason': 'Interrupted operation reconciled without reinjection',
                      'confirmed': False, 'samples': [], 'breached': False, 'cleanup_confirmed': False}
            result['cleanup_confirmed'] = self.cleanup(run_id, handle)
            self.store.save_operation(operation, run_id, {**saved, 'result': result})
            return result
        topology = self.adapter.discover()
        if topology['revision'] != state['topology']['revision']:
            raise RuntimeError('Application configuration changed; start a new assessment')
        sample = self.valid_sample()
        if sample.unhealthy_services or guard_breach(sample, self.profile.limits):
            raise RuntimeError('Trial preflight is unhealthy; no fault was injected')
        experiment = Experiment.model_validate(state['experiment']).check(self.profile, topology)
        handle = self.adapter.prepare(operation, experiment, topology)
        journal = {'handle': handle, 'phase': 'intent'}
        self.store.save_operation(operation, run_id, journal)  # Write intent before cluster mutation.
        self.event(state, 'trial_started', trial=index+1, operation=operation)
        result = {'status': 'invalid', 'confirmed': False, 'samples': [], 'breached': False,
                  'cleanup_confirmed': False, 'guard_tripped': False}
        try:
            if self.store.cancelled(run_id):
                result['reason'] = 'Cancelled before injection'
            else:
                self.adapter.inject(handle)
                journal['phase'] = 'created'
                self.store.save_operation(operation, run_id, journal)
                duration = experiment.duration_s
                deadline = time.monotonic() + duration
                confirmation_deadline = min(deadline, time.monotonic() + 15)
                while not self.store.cancelled(run_id) and time.monotonic() < confirmation_deadline:
                    if self.adapter.confirmed(handle):
                        result['confirmed'] = True
                        break
                    if self.adapter.simulated:
                        break
                    self.pause(run_id)
                if result['confirmed']:
                    ticks = 0
                    previous = None
                    while not self.store.cancelled(run_id) and time.monotonic() < deadline:
                        sample = self.valid_sample()
                        if previous is not None and sample.timestamp <= previous:
                            raise RuntimeError('Telemetry did not advance during injection')
                        previous = sample.timestamp
                        result['samples'].append(sample.model_dump())
                        result['breached'] |= customer_breach(sample, self.profile.limits)
                        if guard_breach(sample, self.profile.limits):
                            result['guard_tripped'] = True
                            break
                        ticks += 1
                        if self.adapter.simulated and ticks >= 3:
                            break
                        self.pause(run_id)
                    result['status'] = 'breached' if result['breached'] else 'passed'
                    if not result['samples'] or (result['guard_tripped'] and not result['breached']):
                        result['status'] = 'invalid'
                else:
                    result['reason'] = 'Fault injection was not confirmed'
                if self.store.cancelled(run_id):
                    result['status'] = 'cancelled'
        except Exception as exc:
            result['status'] = 'invalid'
            # Store type only: provider/Kubernetes errors can contain sensitive endpoint details.
            result['reason'] = type(exc).__name__
        finally:
            result['cleanup_confirmed'] = self.cleanup(run_id, handle)
            if not result['cleanup_confirmed']:
                result['status'] = 'cleanup_failed'
            self.store.save_operation(operation, run_id, {**journal, 'result': result})
            self.event(state, 'trial_finished', trial=index+1, status=result['status'], cleanup_confirmed=result['cleanup_confirmed'])
        return result

    def cleanup(self, run_id, handle):
        try:
            self.adapter.cleanup(handle)
            deadline = time.monotonic() + self.profile.limits.recovery_timeout_s
            while time.monotonic() < deadline:
                if self.adapter.recovered(handle):
                    sample = self.valid_sample()
                    if not sample.unhealthy_services and not guard_breach(sample, self.profile.limits):
                        return True
                # Cancellation must not skip cleanup/recovery checks.
                if not self.adapter.simulated:
                    time.sleep(self.profile.limits.poll_s)
                else:
                    return False
        except Exception:
            pass
        return False

    def report(self, state):
        trials = state.get('trials', [])
        valid = [t for t in trials if t['status'] in ('passed', 'breached') and t['confirmed'] and t['cleanup_confirmed']]
        breaches = sum(t['breached'] for t in valid)
        simulated = self.adapter.simulated
        condition = {'application_revision': state['topology']['revision'], 'experiment': state['experiment'],
                     'users': self.profile.expected_users, 'thresholds': self.profile.limits.model_dump(),
                     'customer_journey': self.profile.customer_journey}
        report = {'application': self.profile.id, 'mode': state['request']['mode'], 'simulated': simulated,
            'condition': condition, 'findings': state['findings'], 'trials': trials,
            'valid_trials': len(valid), 'breaches': breaches,
            'observed_breach_frequency': breaches/len(valid) if valid else None,
            'measured_probability': breaches/len(valid) if valid and not simulated else None,
            'wilson_95_interval': wilson(breaches, len(valid)) if not simulated else None,
            'evidence': 'simulation_only' if simulated else 'insufficient_trials' if len(valid) < 3 else 'experimental',
            'limitations': ['Trial frequency applies only to the recorded experiment and traffic; it is not a production outage forecast.',
                            'Dependencies inferred from environment references are incomplete; traces or supplied architecture can improve discovery.',
                            'Suggested fixes require human review and are not automatically applied.'],
            'recommendations': recommendations(state['topology'], state['experiment'], bool(breaches))}
        self.event(state, 'report_ready', valid_trials=len(valid), breaches=breaches)
        return {'report': report}

    def graph(self, checkpointer):
        graph = StateGraph(State)
        for name in ('discover', 'baseline', 'reason', 'execute', 'report'):
            graph.add_node(name, getattr(self, name))
        graph.add_edge(START, 'discover')
        graph.add_edge('discover', 'baseline')
        graph.add_edge('baseline', 'reason')
        graph.add_conditional_edges('reason', lambda s: 'report' if s['request']['mode'] == 'dry_run' else 'execute')
        graph.add_edge('execute', 'report')
        graph.add_edge('report', END)
        return graph.compile(checkpointer=checkpointer)


def create_run(store, profile, request):
    run_id = uuid.uuid4().hex
    store.create(run_id, profile.model_dump(), request.model_dump())
    return run_id


def _run_assessment(store: Store, run_id, adapter=None, resume=False):
    record = store.get(run_id)
    if record['status'] == 'completed':
        return record['result']
    profile = ApplicationProfile.model_validate(record['profile'])
    store.acquire(profile.id, run_id)
    store.status(run_id, 'running')
    directory = store.directory / run_id
    directory.mkdir(exist_ok=True)
    workflow = Workflow(profile, store, adapter)
    try:
        with SqliteSaver.from_conn_string(str(directory / 'checkpoints.sqlite')) as saver:
            graph = workflow.graph(saver)
            config = {'configurable': {'thread_id': run_id}}
            checkpoint = graph.get_state(config)
            initial = None if resume and checkpoint.values else {'run_id': run_id, 'request': record['request'], 'trials': []}
            final = graph.invoke(initial, config)
        report = final['report']
        (directory / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        (directory / 'report.md').write_text(markdown(report))
        unsafe = any(not t['cleanup_confirmed'] for t in report['trials'])
        store.status(run_id, 'cleanup_failed' if unsafe else 'cancelled' if store.cancelled(run_id) else 'completed', report)
        if not unsafe:
            store.release(profile.id, run_id)
        return report
    except BaseException as exc:
        store.status(run_id, 'interrupted' if isinstance(exc, (KeyboardInterrupt, SystemExit)) else 'failed', error=str(exc) if isinstance(exc, (ValueError, RuntimeError)) else type(exc).__name__)
        # Keep lock if an operation is unresolved; releasing could overlap a live fault.
        with store.connection() as db:
            ops = [json.loads(r[0]) for r in db.execute('SELECT data FROM operations WHERE run_id=?', (run_id,))]
        if all(o.get('result', {}).get('cleanup_confirmed') for o in ops):
            store.release(profile.id, run_id)
        raise


def markdown(report):
    label = 'SIMULATION — no cluster faults or measured failure probability' if report['simulated'] else report['mode']
    return '# Resilience assessment: ' + report['application'] + '\n\n' + label + '\n\n' + \
        f"Valid trials: {report['valid_trials']}; breaches: {report['breaches']}.\n\n" + \
        'Measured conditional breach frequency: ' + str(report['measured_probability']) + '\n\n' + \
        'Wilson 95% interval: ' + str(report['wilson_95_interval']) + '\n\n## Proposed experiment\n\n```json\n' + \
        json.dumps(report['condition'], indent=2) + '\n```\n\n## Recommendations\n\n' + \
        '\n'.join('- ' + r for r in report['recommendations']) + '\n\n## Limits\n\n' + \
        '\n'.join('- ' + r for r in report['limitations']) + '\n'


@contextmanager
def run_lock(store, run_id):
    # Local checkpoint/journal storage supports one machine, one service worker.
    directory = store.directory / run_id
    directory.mkdir(exist_ok=True)
    with (directory / 'worker.lock').open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('This assessment already has an active worker') from None
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def run_assessment(store, run_id, adapter=None, resume=False):
    store.get(run_id)
    with run_lock(store, run_id):
        return _run_assessment(store, run_id, adapter, resume)


def recover_run(store, run_id, adapter=None):
    """Reconcile owned pending faults only; this function never injects a fault."""
    record = store.get(run_id)
    profile = ApplicationProfile.model_validate(record['profile'])
    with run_lock(store, run_id):
        workflow = Workflow(profile, store, adapter)
        with store.connection() as db:
            operations = [(r[0], json.loads(r[1])) for r in db.execute('SELECT id,data FROM operations WHERE run_id=?', (run_id,))]
        recovered = True
        for operation, saved in operations:
            if saved.get('result', {}).get('cleanup_confirmed'):
                continue
            clean = workflow.cleanup(run_id, saved['handle'])
            result = {**saved.get('result', {}), 'status': 'invalid' if clean else 'cleanup_failed',
                      'reason': 'Interrupted trial reconciled without reinjection', 'cleanup_confirmed': clean,
                      'confirmed': False, 'breached': False, 'samples': []}
            store.save_operation(operation, run_id, {**saved, 'result': result})
            recovered &= clean
        store.event(run_id, 'recovery_finished', cleanup_confirmed=recovered)
        if recovered:
            store.release(profile.id, run_id)
            store.status(run_id, 'recovered')
        else:
            store.status(run_id, 'cleanup_failed')
        return recovered
