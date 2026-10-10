# Longer steady-load baseline

Status: **completed**. Baseline suitable: **True**.

Requested study: 300 seconds after 60 seconds of warm-up; 20 users.

Measured study span: 300.006 seconds. Saved study samples: 61.

| Metric | Mean of samples | p95 of samples | Minimum | Maximum |
| --- | ---: | ---: | ---: | ---: |
| users | 20.0000 | 20.0000 | 20.0000 | 20.0000 |
| rps | 4.3984 | 5.0000 | 3.4000 | 5.9000 |
| error_rate | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| p50_ms | 10.9672 | 12.0000 | 10.0000 | 12.0000 |
| p95_ms | 24.3115 | 51.0000 | 16.0000 | 82.0000 |
| checkout_success | 0.9979 | 0.9980 | 0.9977 | 0.9980 |
| unhealthy_count | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| total_restarts | 15.0000 | 15.0000 | 15.0000 | 15.0000 |
| metrics_age_s | 3.2567 | 4.1983 | 1.1893 | 4.2045 |

## Measurements and interpretation

Window counter measurements: `{"requests": 1327, "failures": 0, "completed_rps": 4.4232407866635395, "error_rate": 0.0, "checkout_requests": 63, "checkout_failures": 0, "checkout_success": 1.0}`.

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
