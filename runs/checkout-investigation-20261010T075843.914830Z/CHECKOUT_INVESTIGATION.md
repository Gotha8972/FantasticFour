# Checkout failure log investigation

Baseline study: `runs/baseline-study-20261010T072314.832283Z`. Requested lookback: `3h`.

Root cause is **not automatically established**. Error matches are investigation candidates.

| Service | Rows | Error candidates | Candidates in failure windows | Collection error |
| --- | ---: | ---: | ---: | --- |
| checkoutservice | 0 | 0 | 0 | Yes |
| paymentservice | 0 | 0 | 0 | Yes |
| frontend | 0 | 0 | 0 | Yes |

See [summary.json](summary.json) for timestamps and full collection errors.

A failure window is between two counter observations; it is not an exact request timestamp. No matching logs does not rule out a failure. Logs may have rotated or belong to deleted pods. Raw log CSVs and filtered candidate CSVs are preserved when available.
