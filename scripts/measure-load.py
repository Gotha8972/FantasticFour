"""Executed inside the Locust container; reads its live CSV statistics."""
import csv
import os
import sys
import time


def aggregate(path):
    try:
        with open(path, newline="") as handle:
            rows = csv.DictReader(handle)
            result = None
            for row in rows:
                if row.get("Name") == "Aggregated":
                    result = row
            return result
    except FileNotFoundError:
        return None


def number(row, key):
    return float(row[key])


interval = int(sys.argv[1])
duration = int(sys.argv[2])
stats_dir = os.environ.get("LOCUST_STATS_DIR", "/stats")
deadline = time.monotonic() + duration
previous = None
observed_requests = 0
observed_failures = 0
observed_seconds = 0.0
print("Sampling Locust's counters. Interval RPS measures completed requests.", flush=True)
print("TIME       USERS  TOTAL_REQ  TOTAL_FAIL  INTERVAL_RPS  FAIL/S  P95_MS", flush=True)
while True:
    row = aggregate(os.path.join(stats_dir, "load_stats.csv"))
    history = aggregate(os.path.join(stats_dir, "load_stats_history.csv"))
    now = time.monotonic()
    try:
        if not row:
            raise ValueError("Statistics have not been written yet")
        requests = number(row, "Request Count")
        failures = number(row, "Failure Count")
        p95 = row.get("95%", "n/a")
        users = history.get("User Count", "n/a") if history else "n/a"
        rps = failure_rate = "—"
        if previous:
            old_time, old_requests, old_failures = previous
            elapsed = now - old_time
            request_delta = requests - old_requests
            failure_delta = failures - old_failures
            if request_delta < 0 or failure_delta < 0:
                raise ValueError("Counters reset; restart the sample after the rollout")
            observed_requests += request_delta
            observed_failures += failure_delta
            observed_seconds += elapsed
            rps = f"{request_delta / elapsed:.2f}"
            failure_rate = f"{failure_delta / elapsed:.2f}"
        previous = now, requests, failures
        print(
            f"{time.strftime('%H:%M:%S')} {users:>7} {int(requests):>10} "
            f"{int(failures):>11} {rps:>13} {failure_rate:>7} {p95:>7}",
            flush=True,
        )
    except (KeyError, TypeError, ValueError) as error:
        print(f"Waiting for valid CSV statistics: {error}", flush=True)
    if now >= deadline:
        break
    time.sleep(min(interval, max(0, deadline - now)))

if not previous:
    print("No usable stats. Run bash scripts/load.sh start 20 2, then retry.", file=sys.stderr)
    sys.exit(1)
if observed_seconds:
    print(
        f"Observed {observed_requests:.0f} requests and {observed_failures:.0f} failures "
        f"in {observed_seconds:.1f}s: {observed_requests / observed_seconds:.2f} RPS.",
        flush=True,
    )
    if observed_requests == 0:
        print("No requests completed during this window; inspect main-container logs.", file=sys.stderr)
        sys.exit(2)
print("P95 is cumulative for this Locust run; CSV updates can lag by a few seconds.", flush=True)
