# Longer steady-load baseline

Status: **completed**. Baseline suitable: **False**.

Requested study: 900 seconds after 60 seconds of warm-up; 20 users.

Measured study span: 900.411 seconds. Saved study samples: 181.

| Metric | Mean of samples | p95 of samples | Minimum | Maximum |
| --- | ---: | ---: | ---: | ---: |
| users | 20.0000 | 20.0000 | 20.0000 | 20.0000 |
| rps | 4.3398 | 5.0000 | 3.3000 | 5.7000 |
| error_rate | 0.0005 | 0.0000 | 0.0000 | 0.0250 |
| p50_ms | 19.8453 | 24.0000 | 17.0000 | 28.0000 |
| p95_ms | 77.5028 | 100.0000 | 52.0000 | 240.0000 |
| checkout_success | 0.9870 | 0.9878 | 0.9859 | 0.9880 |
| unhealthy_count | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| total_restarts | 9.0000 | 9.0000 | 9.0000 | 9.0000 |
| metrics_age_s | 2.6792 | 4.3455 | 0.8404 | 5.3468 |

## Measurements and interpretation

Window counter measurements: `{"requests": 3933, "failures": 2, "completed_rps": 4.3680054463884534, "error_rate": 0.0005085176709890668, "checkout_requests": 168, "checkout_failures": 2, "checkout_success": 0.9880952380952381}`.

The table summarizes sampled metrics. The p95 of the `p95_ms` series is a percentile of recent latency estimates; it is not a pooled request-latency p95. Locust recent windows overlap. Repeated history timestamps can repeat estimates. `checkout_success` in the sample table is cumulative since Locust started. The window error and checkout-success fractions use counter differences and exclude failures and checkouts accumulated before this study.

No chaos is injected. CPU, memory, and distributed traces are not collected by this runner.

## Findings

- 2 failed requests occurred without intentional faults.

## Evidence

- [Metrics CSV](metrics.csv)
- [Lifecycle events](events.jsonl)
- [Structured baseline](baseline.json)
- Initial/final workload JSON and pod-log CSVs, when collection was available.
