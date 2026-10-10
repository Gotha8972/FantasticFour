"""Preserve available checkout/payment/frontend logs around baseline failures."""
import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import re

from chaosmind import capture, inject

ERROR = re.compile(r'\b(error|failed|failure|500)\b', re.IGNORECASE)


def instant(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()


def failure_windows(study):
    if study is None:
        return []
    windows = []
    with (study / 'metrics.csv').open(newline='') as handle:
        previous = None
        for row in csv.DictReader(handle):
            if row.get('phase') != 'baseline':
                continue
            if previous and int(row['checkout_failures']) > int(previous['checkout_failures']):
                windows.append({'start_utc': previous['timestamp_utc'], 'end_utc': row['timestamp_utc'],
                                'checkout_failure_increase': int(row['checkout_failures']) - int(previous['checkout_failures'])})
            previous = row
    return windows


def latest_study():
    studies = sorted((inject.ROOT / 'runs').glob('baseline-study-*'), reverse=True)
    for study in studies:
        summary = study / 'baseline.json'
        if summary.exists() and json.loads(summary.read_text()).get('status') == 'completed':
            return study
    return None


def run(study, since):
    directory = inject.ROOT / 'runs' / ('checkout-investigation-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ'))
    directory.mkdir(parents=True)
    windows = failure_windows(study)
    summary = {'study': str(study) if study else None, 'lookback': since,
               'failure_observation_windows': windows, 'services': [], 'cause_established': False}
    for service in ('checkoutservice', 'paymentservice', 'frontend'):
        raw = directory / f'{service}-logs.csv'
        result = {'service': service, 'collection_error': None, 'log_rows': 0,
                  'error_candidates': 0, 'candidates_in_failure_windows': 0,
                  'earliest_log_utc': None, 'latest_log_utc': None}
        try:
            capture.logs(raw, inject.NS, f'app={service}', since)
        except Exception as error:
            result['collection_error'] = getattr(error, 'stderr', None) or str(error)
        if raw.exists():
            with raw.open(newline='') as handle, (directory / f'{service}-error-candidates.csv').open('x', newline='') as output:
                reader = csv.DictReader(handle)
                writer = csv.DictWriter(output, fieldnames=[*reader.fieldnames, 'in_failure_observation_window'])
                writer.writeheader()
                timestamps = []
                for row in reader:
                    if row.get('collection_error'):
                        continue
                    result['log_rows'] += 1
                    stamp = row.get('timestamp_utc')
                    if stamp:
                        timestamps.append(stamp)
                    if ERROR.search(row['message']):
                        result['error_candidates'] += 1
                        in_window = False
                        try:
                            in_window = any(instant(w['start_utc']) <= instant(stamp) <= instant(w['end_utc']) for w in windows)
                        except (ValueError, TypeError):
                            pass
                        result['candidates_in_failure_windows'] += int(in_window)
                        writer.writerow(row | {'in_failure_observation_window': in_window})
                if timestamps:
                    result['earliest_log_utc'], result['latest_log_utc'] = min(timestamps), max(timestamps)
        summary['services'].append(result)
    (directory / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    lines = ['# Checkout failure log investigation', '',
             f'Baseline study: `{summary["study"]}`. Requested lookback: `{since}`.', '',
             'Root cause is **not automatically established**. Error matches are investigation candidates.', '',
             '| Service | Rows | Error candidates | Candidates in failure windows | Collection error |',
             '| --- | ---: | ---: | ---: | --- |']
    for service in summary['services']:
        error = service['collection_error']
        lines.append(f'| {service["service"]} | {service["log_rows"]} | {service["error_candidates"]} | '
                     f'{service["candidates_in_failure_windows"]} | {"Yes" if error else "None"} |')
    lines += ['', 'See [summary.json](summary.json) for timestamps and full collection errors.', '',
              'A failure window is between two counter observations; it is not an exact request timestamp. '
              'No matching logs does not rule out a failure. Logs may have rotated or belong to deleted pods. '
              'Raw log CSVs and filtered candidate CSVs are preserved when available.', '']
    (directory / 'CHECKOUT_INVESTIGATION.md').write_text('\n'.join(lines))
    print(json.dumps(summary, indent=2))
    print(f'Investigation report: {directory / "CHECKOUT_INVESTIGATION.md"}')
    return int(any(s['collection_error'] for s in summary['services']))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', type=Path, help='baseline-study directory (default latest completed study)')
    parser.add_argument('--since', default='3h', help='kubectl log lookback, e.g. 3h')
    args = parser.parse_args()
    if not re.fullmatch(r'[1-9][0-9]*(?:s|m|h)', args.since):
        parser.error('--since must be a positive integer followed by s, m, or h')
    return run(args.study or latest_study(), args.since)


if __name__ == '__main__':
    raise SystemExit(main())
