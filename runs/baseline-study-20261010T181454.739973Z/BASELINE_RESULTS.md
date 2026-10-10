# Longer steady-load baseline

Status: **completed**. Baseline suitable: **True**.

Requested study: 300 seconds after 60 seconds of warm-up; 20 users.

Measured study span: 300.069 seconds. Saved study samples: 61.

| Metric | Mean of samples | p95 of samples | Minimum | Maximum |
| --- | ---: | ---: | ---: | ---: |
| users | 20.0000 | 20.0000 | 20.0000 | 20.0000 |
| rps | 4.4246 | 5.5000 | 3.2000 | 5.7000 |
| error_rate | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| p50_ms | 11.0820 | 12.0000 | 10.0000 | 12.0000 |
| p95_ms | 27.4590 | 85.0000 | 17.0000 | 86.0000 |
| checkout_success | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| unhealthy_count | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| total_restarts | 14.0000 | 14.0000 | 14.0000 | 14.0000 |
| metrics_age_s | 3.4845 | 4.1950 | 1.1849 | 4.2021 |

## Measurements and interpretation

Window counter measurements: `{"requests": 1308, "failures": 0, "completed_rps": 4.358998199387956, "error_rate": 0.0, "checkout_requests": 55, "checkout_failures": 0, "checkout_success": 1.0}`.

The table summarizes sampled metrics. The p95 of the `p95_ms` series is a percentile of recent latency estimates; it is not a pooled request-latency p95. Locust recent windows overlap. Repeated history timestamps can repeat estimates. `checkout_success` in the sample table is cumulative since Locust started. The window error and checkout-success fractions use counter differences and exclude failures and checkouts accumulated before this study.

No chaos is injected. CPU, memory, and distributed traces are not collected by this runner.

## Findings

- No recorded findings.

## Background observations

- No background observations recorded.

## Evidence

- [Metrics CSV](metrics.csv)
- [Lifecycle events](events.jsonl)
- [Structured baseline](baseline.json)
- Initial/final workload JSON and pod-log CSVs, when collection was available.
