# Longer steady-load baseline

Status: **completed**. Baseline suitable: **True**.

Requested study: 300 seconds after 60 seconds of warm-up; 20 users.

Measured study span: 300.065 seconds. Saved study samples: 61.

| Metric | Mean of samples | p95 of samples | Minimum | Maximum |
| --- | ---: | ---: | ---: | ---: |
| users | 20.0000 | 20.0000 | 20.0000 | 20.0000 |
| rps | 4.4295 | 5.2000 | 3.4000 | 5.6000 |
| error_rate | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| p50_ms | 18.5574 | 23.0000 | 17.0000 | 25.0000 |
| p95_ms | 68.4918 | 97.0000 | 37.0000 | 110.0000 |
| checkout_success | 0.9974 | 0.9975 | 0.9973 | 0.9975 |
| unhealthy_count | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| total_restarts | 17.0000 | 17.0000 | 17.0000 | 17.0000 |
| metrics_age_s | 2.5210 | 3.9151 | 0.8209 | 4.9010 |

## Measurements and interpretation

Window counter measurements: `{"requests": 1329, "failures": 0, "completed_rps": 4.429038751426009, "error_rate": 0.0, "checkout_requests": 69, "checkout_failures": 0, "checkout_success": 1.0}`.

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
