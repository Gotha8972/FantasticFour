"""Guarded injection with real metrics, confirmed injection, recovery, CSV logs."""
import argparse
import json
import math
from pathlib import Path
import time
import uuid

from chaosmind import inject
from chaosmind.monitor import snapshot
from chaosmind.runlog import RunLog

LIMITS = {'error_rate': 0.05, 'p95_ms': 1000, 'max_unhealthy': 2,
          'max_duration_s': 120, 'poll_s': 2, 'recovery_timeout_s': 120,
          'injection_timeout_s': 60}


def breach(snap, lim):
    for metric, value, limit in [('error_rate', snap['error_rate'], lim['error_rate']),
                                 ('p95_ms', snap['p95_ms'], lim['p95_ms']),
                                 ('unhealthy', len(snap['unhealthy_services']), lim['max_unhealthy'])]:
        if value > limit:
            return metric, value, limit
    return None


def watch_breach(snap, previous, lim):
    """Breach check while a fault is active. A moderate error-rate spike (<= 2x the limit) must persist for two
    consecutive polls: ~45 requests per Locust window means 2-3 random background 500s can touch 5% on their own.
    Latency, health and severe error spikes still trip on a single poll."""
    b = breach(snap, lim)
    if b and b[0] == 'error_rate' and b[1] <= 2 * b[2] and (previous is None or previous['error_rate'] <= lim['error_rate']):
        rest = breach({**snap, 'error_rate': 0}, lim)
        return rest
    return b


def run(exp, limits=None):
    inject.validate(exp)
    lim = LIMITS.copy()
    for key, value in (limits or {}).items():
        if key not in LIMITS or isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError(f'invalid guard limit: {key}')
        if key in ('error_rate', 'p95_ms', 'max_unhealthy', 'max_duration_s', 'poll_s', 'injection_timeout_s') and value > LIMITS[key]:
            raise ValueError(f'guard overrides may only tighten {key}')
        if key.endswith('_s') and value <= 0:
            raise ValueError(f'{key} must be positive')
        lim[key] = value
    if exp['duration_s'] > lim['max_duration_s']:
        raise ValueError('experiment exceeds guard duration limit')
    exp = exp | {'_run_token': str(uuid.uuid4())}
    output = RunLog(exp)
    log = output.log
    print(f'Run artifacts: {output.directory}', flush=True)
    attempted = False
    clean = False
    try:
        active = inject.running()
        if active:
            log('REFUSED', reason='another unrecovered experiment exists', experiments=active)
            return output.events
        snap = snapshot()
        log('SNAPSHOT', stage='preflight', **snap)
        if snap['unhealthy_services'] or breach(snap, lim):
            log('REFUSED', reason='baseline unhealthy', unhealthy_services=snap['unhealthy_services'])
            return output.events
        attempted = True
        inject.apply(exp)
        created_at = time.monotonic()
        log('CREATED')
        confirmed = False
        while True:
            state = inject.injection_state(inject.status(exp))
            if state['injected']:
                log('INJECTED', records=state['records'])
                confirmed = True
                break
            if state['errors']:
                raise RuntimeError('Chaos Mesh injection failed: ' + state['errors'][-1])
            if time.monotonic() - created_at >= min(lim['injection_timeout_s'], exp['duration_s']):
                raise RuntimeError('Timed out waiting for confirmed injection')
            snap, previous = snapshot(), snap
            log('SNAPSHOT', stage='injecting', **snap)
            if b := watch_breach(snap, previous, lim):
                log('BREACH', metric=b[0], value=b[1], limit=b[2])
                break
            time.sleep(lim['poll_s'])
        if confirmed:
            while time.monotonic() - created_at < exp['duration_s']:
                snap, previous = snapshot(), snap
                log('SNAPSHOT', stage='injected', **snap)
                if b := watch_breach(snap, previous, lim):
                    log('BREACH', metric=b[0], value=b[1], limit=b[2])
                    break
                time.sleep(lim['poll_s'])
            else:
                log('ENDED', reason='planned duration reached')
    except KeyboardInterrupt:
        log('INTERRUPTED', reason='Ctrl-C')
    except Exception as error:
        log('ERROR', reason=getattr(error, 'stderr', None) or str(error))
    finally:
        if attempted:
            reverted_at = time.monotonic()
            try:
                log('REVERT_REQUESTED')
            except OSError:
                pass  # A full/unwritable log directory must not prevent cleanup.
            try:
                inject.revert(exp)
                clean = True
                log('REVERTED')
            except Exception as error:
                log('REVERT_FAILED', reason=getattr(error, 'stderr', None) or str(error))
    if attempted and clean:
        while time.monotonic() - reverted_at < lim['recovery_timeout_s']:
            try:
                snap = snapshot()
                log('SNAPSHOT', stage='recovery', **snap)
                if not snap['unhealthy_services'] and not breach(snap, lim):
                    log('HEALTHY', recovery_s=round(time.monotonic() - reverted_at, 3))
                    return output.events
            except KeyboardInterrupt:
                log('INTERRUPTED', reason='Ctrl-C during recovery; experiment already deleted')
                return output.events
            except Exception as error:
                log('MONITOR_ERROR', reason=getattr(error, 'stderr', None) or str(error))
            time.sleep(lim['poll_s'])
        log('NOT_RECOVERED', reason='health could not be confirmed before recovery timeout')
    return output.events


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('experiment')
    parser.add_argument('limits', nargs='?', default='{}', help='JSON overrides that tighten thresholds')
    args = parser.parse_args()
    events = run(json.loads(Path(args.experiment).read_text()), json.loads(args.limits))
    bad = {'REFUSED', 'ERROR', 'REVERT_FAILED', 'NOT_RECOVERED', 'INTERRUPTED'}
    return 1 if any(event['event'] in bad for event in events) else 0


if __name__ == '__main__':
    raise SystemExit(main())
