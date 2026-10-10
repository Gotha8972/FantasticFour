# Longer steady-load baseline

Status: **completed**. Baseline suitable: **True**.

Requested study: 300 seconds after 60 seconds of warm-up; 20 users.

Measured study span: 301.501 seconds. Saved study samples: 62.

| Metric | Mean of samples | p95 of samples | Minimum | Maximum |
| --- | ---: | ---: | ---: | ---: |
| users | 20.0000 | 20.0000 | 20.0000 | 20.0000 |
| rps | 4.5097 | 5.3950 | 3.3000 | 5.7000 |
| error_rate | 0.0006 | 0.0000 | 0.0000 | 0.0185 |
| p50_ms | 10.7742 | 12.0000 | 10.0000 | 13.0000 |
| p95_ms | 34.6935 | 59.9500 | 16.0000 | 94.0000 |
| checkout_success | 0.9991 | 1.0000 | 0.9976 | 1.0000 |
| unhealthy_count | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| total_restarts | 9.0000 | 9.0000 | 9.0000 | 9.0000 |
| metrics_age_s | 1.9045 | 2.4005 | 0.3188 | 3.3926 |

## Measurements and interpretation

Window counter measurements: `{"requests": 1372, "failures": 1, "completed_rps": 4.55056441078316, "error_rate": 0.0007288629737609329, "checkout_requests": 69, "checkout_failures": 1, "checkout_success": 0.9855072463768116}`.

The table summarizes sampled metrics. The p95 of the `p95_ms` series is a percentile of recent latency estimates; it is not a pooled request-latency p95. Locust recent windows overlap. Repeated history timestamps can repeat estimates. `checkout_success` in the sample table is cumulative since Locust started. The window error and checkout-success fractions use counter differences and exclude failures and checkouts accumulated before this study.

No chaos is injected. CPU, memory, and distributed traces are not collected by this runner.

## Findings

- No recorded findings.

## Background observations

- 1 failed requests (0.07%) without faults: background error rate.

## Evidence

- [Metrics CSV](metrics.csv)
- [Lifecycle events](events.jsonl)
- [Structured baseline](baseline.json)
- Initial/final workload JSON and pod-log CSVs, when collection was available.
