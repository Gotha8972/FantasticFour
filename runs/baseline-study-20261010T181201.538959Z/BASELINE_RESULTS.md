# Longer steady-load baseline

Status: **failed**. Baseline suitable: **False**.

Requested study: 300 seconds after 60 seconds of warm-up; 20 users.

Measured study span: 61.944 seconds. Saved study samples: 11.

| Metric | Mean of samples | p95 of samples | Minimum | Maximum |
| --- | ---: | ---: | ---: | ---: |
| users | 20.0000 | 20.0000 | 20.0000 | 20.0000 |
| rps | 4.1455 | 5.0000 | 3.4000 | 5.0000 |
| error_rate | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| p50_ms | 11.6364 | 12.5000 | 11.0000 | 13.0000 |
| p95_ms | 72.4545 | 160.0000 | 30.0000 | 160.0000 |
| checkout_success | 0.9892 | 0.9892 | 0.9892 | 0.9892 |
| unhealthy_count | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| total_restarts | 13.0000 | 13.0000 | 13.0000 | 13.0000 |
| metrics_age_s | 2.9177 | 4.5792 | 0.9692 | 4.6278 |

## Measurements and interpretation

Window counter measurements: `{"requests": 260, "failures": 0, "completed_rps": 4.197341438419154, "error_rate": 0.0, "checkout_requests": 10, "checkout_failures": 0, "checkout_success": 1.0}`.

The table summarizes sampled metrics. The p95 of the `p95_ms` series is a percentile of recent latency estimates; it is not a pooled request-latency p95. Locust recent windows overlap. Repeated history timestamps can repeat estimates. `checkout_success` in the sample table is cumulative since Locust started. The window error and checkout-success fractions use counter differences and exclude failures and checkouts accumulated before this study.

No chaos is injected. CPU, memory, and distributed traces are not collected by this runner.

## Findings

- No recorded findings.

## Background observations

- No background observations recorded.

## Collection error

```text
command terminated with exit code 137

```

## Evidence

- [Metrics CSV](metrics.csv)
- [Lifecycle events](events.jsonl)
- [Structured baseline](baseline.json)
- Initial/final workload JSON and pod-log CSVs, when collection was available.
