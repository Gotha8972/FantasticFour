# Longer steady-load baseline

Status: **failed**. Baseline suitable: **False**.

Requested study: 900 seconds after 60 seconds of warm-up; 20 users.

Measured study span: 0.000 seconds. Saved study samples: 0.

| Metric | Mean of samples | p95 of samples | Minimum | Maximum |
| --- | ---: | ---: | ---: | ---: |

## Measurements and interpretation

Window counter measurements: `{}`.

The table summarizes sampled metrics. The p95 of the `p95_ms` series is a percentile of recent latency estimates; it is not a pooled request-latency p95. Locust recent windows overlap. Repeated history timestamps can repeat estimates. `checkout_success` in the sample table is cumulative since Locust started. The window error and checkout-success fractions use counter differences and exclude failures and checkouts accumulated before this study.

No chaos is injected. CPU, memory, and distributed traces are not collected by this runner.

## Findings

- No recorded findings.

## Background observations

- No background observations recorded.

## Collection error

```text
Unable to connect to the server: dial tcp 127.0.0.1:42957: socket: operation not permitted
Unable to connect to the server: dial tcp 127.0.0.1:42957: socket: operation not permitted
Unable to connect to the server: dial tcp 127.0.0.1:42957: socket: operation not permitted
Unable to connect to the server: dial tcp 127.0.0.1:42957: socket: operation not permitted

```

## Evidence

- [Metrics CSV](metrics.csv)
- [Lifecycle events](events.jsonl)
- [Structured baseline](baseline.json)
- Initial/final workload JSON and pod-log CSVs, when collection was available.
