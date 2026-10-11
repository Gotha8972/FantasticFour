"""Collect a longer steady-load baseline without injecting faults."""
import argparse
import csv
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import statistics
import subprocess
import time

from chaosmind import app, capture, guard, inject
from chaosmind.monitor import snapshot

FIELDS = ['timestamp_utc', 'phase', 'elapsed_s', 'ts', 'locust_history_ts', 'users', 'rps',
          'requests', 'failures', 'error_rate', 'p50_ms', 'p95_ms', 'checkout_success',
          'checkout_requests', 'checkout_failures', 'unhealthy_services', 'restarts',
          'loadgenerator_pod_uids', 'pod_uids', 'unhealthy_count', 'total_restarts',
          'metrics_age_s', 'source', 'error']
METRICS = ['users', 'rps', 'error_rate', 'p50_ms', 'p95_ms', 'checkout_success',
           'unhealthy_count', 'total_restarts', 'metrics_age_s']


def positive(value):
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise argparse.ArgumentTypeError('must be finite and positive')
    return result


def integer(value):
    result = int(value)
    if result < 1:
        raise argparse.ArgumentTypeError('must be a positive integer')
    return result


def percentile(values, fraction):
    ordered = sorted(values)
    index = (len(ordered) - 1) * fraction
    low = math.floor(index)
    high = math.ceil(index)
    return ordered[low] + (ordered[high] - ordered[low]) * (index - low)


def metric_summary(samples):
    result = {}
    for metric in METRICS:
        values = [s[metric] for s in samples if s.get(metric) is not None]
        result[metric] = {'samples': len(values), 'mean': statistics.fmean(values),
                          'p95': percentile(values, .95), 'min': min(values), 'max': max(values)} if values else None
    return result


def check_sample(snap, users, first=None):
    required = ('users', 'rps', 'error_rate', 'p50_ms', 'p95_ms', 'requests', 'failures',
                'checkout_requests', 'checkout_failures', 'locust_history_ts')
    for name in required:
        if snap.get(name) is None or not math.isfinite(float(snap[name])) or snap[name] < 0:
            raise RuntimeError(f'Missing or invalid baseline metric: {name}')
    if snap['users'] != users:
        raise RuntimeError(f'Shopper count changed: expected {users}, observed {snap["users"]}')
    if len(snap['loadgenerator_pod_uids']) != 1:
        raise RuntimeError('Baseline requires exactly one loadgenerator pod')
    if first:
        if snap['loadgenerator_pod_uids'] != first['loadgenerator_pod_uids']:
            raise RuntimeError('Loadgenerator pod was replaced during the study')
        for name in ('requests', 'failures', 'checkout_requests', 'checkout_failures'):
            if snap[name] < first[name]:
                raise RuntimeError(f'Locust counter reset during the study: {name}')
        if snap['locust_history_ts'] < first['locust_history_ts']:
            raise RuntimeError('Locust history timestamp moved backwards')


def save_report(directory, result):
    summary = result.get('metrics', {})
    text = ['# Longer steady-load baseline', '',
            f'Status: **{result["status"]}**. Baseline suitable: **{result.get("baseline_suitable", False)}**.', '',
            f'Requested study: {result["requested_duration_s"]:g} seconds after '
            f'{result["warmup_s"]:g} seconds of warm-up; {result["expected_users"]} users.', '',
            f'Measured study span: {result.get("measured_span_s", 0):.3f} seconds. '
            f'Saved study samples: {result.get("sample_count", 0)}.', '',
            '| Metric | Mean of samples | p95 of samples | Minimum | Maximum |',
            '| --- | ---: | ---: | ---: | ---: |']
    for name, metric in summary.items():
        if metric:
            text.append(f'| {name} | {metric["mean"]:.4f} | {metric["p95"]:.4f} | '
                        f'{metric["min"]:.4f} | {metric["max"]:.4f} |')
    text += ['', '## Measurements and interpretation', '',
             f'Window counter measurements: `{json.dumps(result.get("window", {}))}`.', '',
             'The table summarizes sampled metrics. The p95 of the `p95_ms` series is a '
             'percentile of recent latency estimates; it is not a pooled request-latency p95. '
             'Locust recent windows overlap. Repeated history timestamps can repeat estimates. '
             '`checkout_success` in the sample table is cumulative since Locust started. '
             'The window error and checkout-success fractions use counter differences and exclude '
             'failures and checkouts accumulated before this study.', '',
             'No chaos is injected. CPU, memory, and distributed traces are not collected by this runner.', '',
             '## Findings', '']
    text += [f'- {finding}' for finding in result.get('findings', [])] or ['- No recorded findings.']
    text += ['', '## Background observations', '']
    text += [f'- {note}' for note in result.get('notes', [])] or ['- No background observations recorded.']
    if result.get('error'):
        text += ['', '## Collection error', '', '```text', result['error'], '```']
    text += ['', '## Evidence', '', '- [Metrics CSV](metrics.csv)',
             '- [Lifecycle events](events.jsonl)', '- [Structured baseline](baseline.json)',
             '- Initial/final workload JSON and pod-log CSVs, when collection was available.', '']
    (directory / 'BASELINE_RESULTS.md').write_text('\n'.join(text))
    (directory / 'baseline.json').write_text(json.dumps(result, indent=2) + '\n')


def run(args):
    directory = inject.ROOT / 'runs' / ('baseline-study-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ'))
    directory.mkdir(parents=True)
    result = {'schema_version': 1, 'status': 'running', 'baseline_suitable': False,
              'run_started_utc': datetime.now(timezone.utc).isoformat(),
              'requested_duration_s': args.duration, 'warmup_s': args.warmup,
              'interval_s': args.interval, 'expected_users': args.users,
              'context': inject.CONTEXT, 'namespace': inject.NS, 'artifact_dir': str(directory),
              'findings': [], 'notes': [], 'collection_errors': [],
              'acceptance_policy': {'window_error_rate_exclusive_max': 0.01,
                                    'guard_limits': guard.LIMITS.copy()}}
    result['metric_units'] = {'rps': 'requests/second', 'p50_ms': 'milliseconds',
                             'p95_ms': 'milliseconds', 'error_rate': 'fraction 0..1',
                             'checkout_success': 'fraction 0..1', 'metrics_age_s': 'seconds'}
    start = time.monotonic()
    samples = []

    def log(event, **details):
        row = {'timestamp_utc': datetime.now(timezone.utc).isoformat(),
               'elapsed_s': round(time.monotonic() - start, 3), 'event': event, **details}
        with (directory / 'events.jsonl').open('a') as handle:
            handle.write(json.dumps(row) + '\n')
        print(json.dumps(row), flush=True)

    def no_faults():
        active = inject.running()
        if active:
            raise RuntimeError(f'Baseline contaminated by unrecovered chaos: {active}')

    print(f'Baseline artifacts: {directory}', flush=True)
    with (directory / 'metrics.csv').open('x', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, extrasaction='ignore')
        writer.writeheader()
        handle.flush()
        try:
            no_faults()
            if args.start_load and app.NAME != 'online-boutique':
                raise RuntimeError('scripts/load.sh starts Online Boutique\'s load generator; start this app\'s yourself')
            if args.start_load:
                log('START_LOAD', users=args.users, rate=args.rate)
                subprocess.run(['bash', str(inject.ROOT / 'scripts/load.sh'), 'start',
                                str(args.users), str(args.rate)], check=True, timeout=660)
            initial = inject.kubectl('get', 'deployments,pods', '-n', inject.NS, '-o', 'json')
            (directory / 'workloads-initial.json').write_text(initial)
            log('WARMUP_STARTED', seconds=args.warmup)
            warmup_deadline = time.monotonic() + args.warmup
            while time.monotonic() < warmup_deadline:
                no_faults()
                time.sleep(min(args.interval, max(0, warmup_deadline - time.monotonic())))
            log('STUDY_STARTED')
            result['study_started_utc'] = datetime.now(timezone.utc).isoformat()
            study_start = time.monotonic()
            deadline = study_start + args.duration
            previous = None
            while True:
                iteration = time.monotonic()
                no_faults()
                snap = snapshot()
                check_sample(snap, args.users, previous)
                if previous and snap['loadgenerator_pod_uids'] != samples[0]['loadgenerator_pod_uids']:
                    raise RuntimeError('Loadgenerator pod identity changed')
                sample = snap | {'timestamp_utc': datetime.now(timezone.utc).isoformat(),
                                 'phase': 'baseline', 'elapsed_s': round(time.monotonic() - study_start, 3),
                                 'unhealthy_count': len(snap['unhealthy_services']),
                                 'total_restarts': sum(snap['restarts'].values())}
                row = sample.copy()
                for field in ('unhealthy_services', 'restarts', 'loadgenerator_pod_uids', 'pod_uids'):
                    row[field] = json.dumps(row[field])
                writer.writerow(row)
                handle.flush()
                samples.append(sample)
                previous = snap
                if len(samples) == 1:
                    result['first_observation_utc'] = sample['timestamp_utc']
                    # Measure a full duration between the first and final observations.
                    deadline = time.monotonic() + args.duration
                    if snap['unhealthy_services'] or guard.breach(snap, guard.LIMITS):
                        raise RuntimeError('Initial baseline sample is unhealthy')
                log('SAMPLE', users=snap['users'], rps=snap['rps'], error_rate=snap['error_rate'],
                    p50_ms=snap['p50_ms'], p95_ms=snap['p95_ms'], unhealthy_services=snap['unhealthy_services'])
                if time.monotonic() >= deadline:
                    break
                time.sleep(min(max(0, args.interval - (time.monotonic() - iteration)),
                               max(0, deadline - time.monotonic())))
            no_faults()
            result['status'] = 'completed'
            log('STUDY_COMPLETED', samples=len(samples))
            final = inject.kubectl('get', 'deployments,pods', '-n', inject.NS, '-o', 'json')
            (directory / 'workloads-final.json').write_text(final)
        except KeyboardInterrupt:
            result.update(status='interrupted', error='Interrupted; partial observations are preserved')
            log('INTERRUPTED')
        except Exception as error:
            reason = getattr(error, 'stderr', None) or str(error)
            result.update(status='failed', error=reason)
            writer.writerow({'timestamp_utc': datetime.now(timezone.utc).isoformat(),
                             'phase': 'collection_error', 'error': reason})
            handle.flush()
            log('ERROR', reason=reason)
        finally:
            result['sample_count'] = len(samples)
            result['collection_finished_utc'] = datetime.now(timezone.utc).isoformat()
            result['metrics'] = metric_summary(samples)
            if samples:
                first, last = samples[0], samples[-1]
                result['last_observation_utc'] = last['timestamp_utc']
                span = last['ts'] - first['ts']
                result['measured_span_s'] = round(span, 3)
                requests = last['requests'] - first['requests']
                failures = last['failures'] - first['failures']
                checkout_requests = last['checkout_requests'] - first['checkout_requests']
                checkout_failures = last['checkout_failures'] - first['checkout_failures']
                result['window'] = {'requests': requests, 'failures': failures,
                    'completed_rps': requests / span if span > 0 else None,
                    'error_rate': failures / requests if requests > 0 else None,
                    'checkout_requests': checkout_requests, 'checkout_failures': checkout_failures,
                    'checkout_success': 1 - checkout_failures / checkout_requests if checkout_requests > 0 else None}
                result['unique_history_timestamps'] = len({s['locust_history_ts'] for s in samples})
                result['max_sample_gap_s'] = max((b['ts'] - a['ts'] for a, b in zip(samples, samples[1:])), default=0)
                result['restart_increases'] = {service: max(s['restarts'].get(service, 0) for s in samples) - count
                    for service, count in first['restarts'].items()
                    if max(s['restarts'].get(service, 0) for s in samples) > count}
                if any(s['unhealthy_services'] or guard.breach(s, guard.LIMITS) for s in samples):
                    result['findings'].append('At least one sample had unhealthy services or breached guard limits.')
                if result['restart_increases']:
                    result['findings'].append(f'Service restart increases: {result["restart_increases"]}')
                changed = sorted({service for s in samples for service in set(first['pod_uids']) | set(s['pod_uids'])
                                  if s['pod_uids'].get(service) != first['pod_uids'].get(service)})
                result['services_with_pod_changes'] = changed
                if changed:
                    result['findings'].append(f'Service pod identities changed: {changed}')
                if result['max_sample_gap_s'] > max(15, 3 * args.interval):
                    result['findings'].append('Long collection gaps reduce confidence in the study.')
                if checkout_requests == 0:
                    result['findings'].append('No completed checkouts in the study window.')
                if requests <= 0:
                    result['findings'].append('No completed requests in the study window.')
                elif failures and failures / requests >= 0.01:
                    result['findings'].append(f'{failures} failed requests occurred without intentional faults.')
                elif failures:
                    result['notes'].append(f'{failures} failed requests ({failures / requests:.2%}) '
                                           'without faults: background error rate.')
                if result['status'] == 'completed' and span < args.duration:
                    result['findings'].append('Measured observation span was shorter than the requested duration.')
            result['baseline_suitable'] = result['status'] == 'completed' and bool(samples) and not result['findings']
            # Persist metrics and failure evidence before attempting ancillary log exports.
            save_report(directory, result)
    if result['status'] == 'completed':
        lookback = f'{math.ceil(time.monotonic() - start) + 60}s'
        for label, namespace, selector in (
                ('loadgenerator', inject.NS, 'app=loadgenerator'),
                ('frontend', inject.NS, 'app=frontend'),
                ('cartservice', inject.NS, 'app=cartservice')):
            try:
                capture.logs(directory / f'{label}-logs.csv', namespace, selector, lookback)
            except Exception as error:
                result['collection_errors'].append(getattr(error, 'stderr', None) or str(error))
        for suffix in ('stats', 'stats_history', 'failures'):
            try:
                data = inject.kubectl('exec', 'deployment/loadgenerator', '-n', inject.NS, '-c', 'main',
                                     '--', 'cat', f'/stats/load_{suffix}.csv')
                (directory / f'load_{suffix}.csv').write_text(data)
            except Exception as error:
                result['collection_errors'].append(getattr(error, 'stderr', None) or str(error))
        if result['collection_errors']:
            result['findings'].append('Some supporting log or raw CSV exports failed; see collection_errors.')
        save_report(directory, result)
        if result['baseline_suitable']:
            app.BASELINE.write_text(json.dumps(result, indent=2) + '\n')  # this app's baseline (its profile names the file)
    print(f'Results: {directory / "BASELINE_RESULTS.md"}', flush=True)
    print(f'Status: {result["status"]}; baseline suitable: {result["baseline_suitable"]}', flush=True)
    return 0 if result['baseline_suitable'] and not result['collection_errors'] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--duration', type=positive, default=900, help='study seconds, excluding warm-up (default 900)')
    parser.add_argument('--warmup', type=positive, default=60)
    parser.add_argument('--interval', type=positive, default=5)
    parser.add_argument('--users', type=integer, default=20)
    parser.add_argument('--rate', type=integer, default=2)
    parser.add_argument('--start-load', action='store_true', help='start/configure shoppers before warm-up')
    return run(parser.parse_args())


if __name__ == '__main__':
    raise SystemExit(main())
