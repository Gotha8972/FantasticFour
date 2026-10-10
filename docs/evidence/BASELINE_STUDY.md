# Longer steady-load baseline

The study runner implements the steady-load baseline requested in `PLAN.md`
and `DAY1.md`. Its default is **15 minutes of measurement after one minute of
warm-up**, with **20 shoppers**, spawn rate **2 users/second**, and observations
approximately every **5 seconds**. This exceeds the original five-minute plan.

## Completed study: 10 October 2026

The host-terminal run **completed** the requested observation window and
exported its supporting evidence without collection errors.

**Automatic baseline suitability was false for this archived run:** two requests failed during the
study, and the collector's acceptance rule at that time required zero failures.
This is a completed measurement with a finding. It is not a collection failure.
No suitable root-level `baseline.json` was published by this run.

Evidence directory:
[baseline-study-20261010T072314.832283Z](../../runs/baseline-study-20261010T072314.832283Z/BASELINE_RESULTS.md).

### Duration and coverage

| Measurement | Result |
| --- | --- |
| Requested measurement window | 900 seconds, after 60 seconds of warm-up |
| Actual first-to-last observation span | 900.411 seconds |
| First observation | 07:24:18.936242 UTC / 12:54:18.936242 IST |
| Last observation | 07:39:19.347541 UTC / 13:09:19.347541 IST |
| Saved snapshots | 181 |
| Distinct Locust history timestamps | 181 |
| Largest gap between samples | 5.362 seconds |
| Shopper count | 20 in every sample |
| Supporting export errors | None |

### Requests and checkout results within the study window

These measurements use counter differences between the first and final
snapshots, excluding earlier chaos-test traffic and failures.

| Measurement | Result |
| --- | --- |
| Completed requests | 3,933 |
| Failed requests | 2 |
| Overall window error rate | **0.0509%** (2 / 3,933) |
| Window completed throughput | **4.368 requests/second** |
| Checkout requests | 168 |
| Failed checkouts | 2 |
| Successful checkouts | 166 |
| Window checkout success | **98.8095%** (166 / 168) |

The two observed failures were checkout failures. Their increments first
appeared in the samples at **07:27:03.940488 UTC** and
**07:29:59.051397 UTC**. These are observation times, rather than exact request
failure timestamps. No intentional chaos was injected by the study runner.

The raw Locust failure export lists `POST /cart/checkout` HTTP 500 responses,
but its occurrence counts are cumulative across this Locust process. They
include failures before this study and must not be treated as this window's
failure counts. The failure cause has not been established from this review.

### Sampled metrics

| Metric | Mean | p95 of sampled values | Minimum | Maximum |
| --- | ---: | ---: | ---: | ---: |
| Recent RPS | 4.3398 | 5.0 | 3.3 | 5.7 |
| Recent error rate | 0.0507% | 0% | 0% | 2.5% |
| Recent p50 latency | 19.845 ms | 24 ms | 17 ms | 28 ms |
| Recent p95 latency | 77.503 ms | 100 ms | 52 ms | 240 ms |
| Unhealthy deployments | 0 | 0 | 0 | 0 |
| Total recorded restart count | 9 | 9 | 9 | 9 |
| Locust metric age | 2.679 s | 4.345 s | 0.840 s | 5.347 s |

The nine restarts already existed when observation began. **No restart
increases and no service pod identity changes occurred during the study.**
No sample had an unhealthy service. The sampled maximum error rate of 2.5%
and maximum recent p95 of 240 ms stayed below the guard defaults of 20% and
2,000 ms, respectively.

The p95-of-samples column summarizes each metric's time series. For example,
the 100 ms value is the 95th percentile of the recorded recent p95 latency
estimates; it is not the request-level p95 of all 3,933 requests.

### Interpretation

At 20 simulated shoppers, the application sustained about 4.37 completed
requests per second with low sampled latency and healthy deployments.
It still produced two checkout failures without intentional faults. A future
chaos comparison should account for this observed background failure rate.
The collector retained the evidence and rejected this run under its then-current
zero-failure rule. The updated policy below allows a small background error rate.
The archived study's result has not been rewritten or reclassified.

This study provides a measured traffic reference for this local environment.
It does not establish maximum capacity, a production reliability guarantee,
or CPU/memory behavior. Repeating the study and investigating checkout errors
would help establish how repeatable the results are.

### Evidence links

- [Structured baseline and findings](../../runs/baseline-study-20261010T072314.832283Z/baseline.json)
- [Measured snapshots](../../runs/baseline-study-20261010T072314.832283Z/metrics.csv)
- [Study lifecycle](../../runs/baseline-study-20261010T072314.832283Z/events.jsonl)
- [Raw Locust history](../../runs/baseline-study-20261010T072314.832283Z/load_stats_history.csv)
- [Raw cumulative failure export](../../runs/baseline-study-20261010T072314.832283Z/load_failures.csv)
- [Frontend logs](../../runs/baseline-study-20261010T072314.832283Z/frontend-logs.csv)
- [Loadgenerator logs](../../runs/baseline-study-20261010T072314.832283Z/loadgenerator-logs.csv)

The saved frontend log export begins at approximately 07:34:41 UTC, after the
two failure increments. Although exports completed without errors, available
frontend logs do not cover those earlier failures. Log retention/rotation can
limit the history returned by kubectl. A complete failure diagnosis needs
additional evidence.

## Run

From the host terminal in the project folder:

```bash
bash scripts/baseline.sh
```

The wrapper starts/configures the existing Locust deployment, waits for rollout,
warms up, collects the study, and exports evidence. It leaves shoppers running.
Allow roughly 16 minutes plus startup and export time. No faults are injected.
Keep other testers from running experiments or restarting services during the
study. The collector checks for unrecovered chaos at each sample; faults that
start and finish entirely between samples may not be detected.

Adjust the duration if needed:

```bash
# The original five-minute plan:
bash scripts/baseline.sh --duration 300
# A thirty-minute study:
bash scripts/baseline.sh --duration 1800
# Reuse an already running, instrumented load generator:
python3 -m chaosmind.baseline --duration 900 --users 20
```

The Python command without `--start-load` does not configure shoppers.
`--users` is the expected steady user count; actual throughput is measured.

## Artifacts

Each invocation creates `runs/baseline-study-<UTC timestamp>/`:

| File | Contents |
| --- | --- |
| `metrics.csv` | Every measured snapshot and any collection-error row. |
| `events.jsonl` | Warm-up, study start, sample progress, completion or failure. |
| `baseline.json` | Duration, sample count, metric summaries, counter deltas, restarts, pod changes, findings, and suitability. |
| `BASELINE_RESULTS.md` | Generated report of actual results; failures also get a report. |
| `workloads-initial.json`, `workloads-final.json` | Live deployment and pod state around the study. |
| `loadgenerator-logs.csv`, `frontend-logs.csv`, `cartservice-logs.csv` | Available pod logs spanning the run and a small lookback buffer. |
| `load_stats.csv`, `load_stats_history.csv`, `load_failures.csv` | Raw Locust CSV exports after the study. |

A completed suitable study also writes the latest `baseline.json` at the
project root. Failed, interrupted, or unsuitable studies do not overwrite it.
Check the root file's timestamped `artifact_dir` before using it; it can refer
to an older suitable run if a later run failed.

## Measurements

The CSV records UTC time, elapsed study time, user count, recent RPS, recent
error rate, recent p50/p95 latency in milliseconds, cumulative requests and
failures, checkout counters/success fraction, unhealthy services, restarts,
pod identities, Locust history time, and metric age.

`baseline.json` summarizes sampled user count, RPS, error rate, p50, p95,
checkout success, unhealthy count, total restarts, and metric age with their
mean, p95, minimum, maximum, and available sample count.

Interpret these quantities carefully:

- `metrics.p95_ms.p95` is the 95th percentile of the sampled **recent p95
  estimates**. It is not a request-level p95 pooled over the whole study.
- Recent Locust metric windows overlap. Duplicate history timestamps can
  repeat estimates; `unique_history_timestamps` records how many were distinct.
- Sample `checkout_success` is cumulative since Locust started.
- `window.checkout_success`, `window.error_rate`, and `window.completed_rps`
  use **counter differences between the first and final study samples**.
  Earlier chaos failures are excluded from these window calculations.
- No checkout success is inferred when zero checkouts completed; that value
  is `null` and the report records a finding.
- Warm-up and startup are excluded from the baseline summary. The collector
  observes a full requested duration between its first and final samples.
- Restarts already present at the start are reported in samples; increases
  during the study are separately identified.

The collector uses real Locust and Kubernetes data. It does not collect CPU,
memory, Prometheus metrics, or traces. Logs can overlap with other exports,
and deleted pods' older logs may be unavailable.

## Suitability and failure handling

Following `A_NEXT_STEPS.md`, the updated policy accepts a measured background
error rate **strictly below 1%**. An error rate of 1% or more is a finding that
rejects the baseline. Smaller nonzero failure counts appear under `notes`, so
the failed requests remain visible without automatically rejecting the study.
This is based on the full study's counter differences, rather than the peak
error rate of an overlapping recent window.

The team approved guard limits of **5% recent error rate** and **1,000 ms recent
p95**. `max_unhealthy=2` remains unchanged. Baseline collection still requires
zero unhealthy services and applies the guard checks to every sampled window.

The collector stops and saves partial evidence if collection fails, traffic is
stale/absent, user count changes, the loadgenerator is replaced, counters reset,
or an unrecovered chaos resource is detected. An unhealthy initial sample also
rejects the baseline.

A completed study is marked unsuitable if recorded observations include
unhealthy services, guard-limit breaches, restart increases, pod replacements,
large sampling gaps, a window error rate of at least 1%, no completed checkouts, or insufficient
measured duration. These findings are preserved for investigation.

Supporting export failures are listed under `collection_errors`. They return
nonzero even when the collected metric baseline is suitable. A nonzero command
exit is not proof of application failure: inspect the generated report.

The scripts never substitute zero for missing metrics, delete existing
experiments, stop shoppers, or publish evidence automatically.

## Earlier assistant-session attempt

The earlier run in `runs/baseline-study-20261010T072219.153158Z/` failed before
observation because this assistant session could not connect to the local
Kubernetes API (`socket: operation not permitted`). It contains zero study
samples. Its failure evidence is preserved separately from the completed
host-terminal study reported above.
