# Findings report

The product catalog service pod kill exposed a single‑replica failure that caused checkout to fail with a 51.6% error rate and 60 s latency spikes. A network partition of the payment service did not raise error rates but produced a 17 s p95 latency spike, indicating a slowdown rather than a service outage. A 30% packet loss to the currency service pushed p95 latency to 2.8 s, again a slowdown without data loss.

**AI hypotheses:** 4 tested, 3 confirmed, 1 refuted; **1 refuted after their fix** (same criteria, re-run after the approved fix). Verdicts are decided by code against criteria written before each run.

| Experiment | Fault | Verdict | Criteria met | Worst error rate | Worst p95 | Recovery | Integrity | Score |
|---|---|---|---|---|---|---|---|---|
| `v7-pod-kill-frontend` | pod_kill on frontend | refuted | 0 of 1 | 0.0% | 180.0 ms | 1.19 s | 0 violation(s) | 97 |
| `v1-pod-kill-productcatalogservice` | pod_kill on productcatalogservice | confirmed | 2 of 2 | 51.6% | 60000.0 ms | 15.773 s | 0 violation(s) | 27 |
| `v3-network-partition-paymentservice` | network_partition on paymentservice | confirmed | 1 of 2 | 0.0% | 17000.0 ms | 10.136 s | 0 violation(s) | 70 |
| `v2-network-loss-currencyservice` | network_loss on currencyservice | confirmed | 1 of 2 | 0.0% | 2800.0 ms | 12.989 s | 0 violation(s) | 81 |

Scores are as computed when the run happened. `python3 -m chaosmind.agents.scoreboard` recomputes every run with the current formula.

## Product catalog pod kill causes checkout failure (high)

**What happened:** Killing the sole productcatalogservice pod caused checkout and product pages to return 500 errors, raising error_rate to 0.516 and p95 latency to 60 000 ms.

**Root cause:** The service ran with replicas=1 and no PDB, so the pod kill removed the only instance, breaking all downstream calls.

**Fix:** Increase productcatalogservice replicas to 2 (productcatalog-replicas).

**Remediation:** `productcatalog-replicas` applied after human approval; the same experiment re-run: score 27 → 98 (improved); hypothesis **refuted** after the fix.

Evidence: `runs/v1-pod-kill-productcatalogservice-s1-20261011T015453.929802Z`

## Payment service network partition causes latency spike (medium)

**What happened:** A network partition between paymentservice and checkoutservice caused checkout to experience a 17 s p95 latency spike, though error_rate remained 0.0.

**Root cause:** The fault isolated paymentservice from checkoutservice, delaying payment processing but not causing errors.

**Fix:** No fix applied; consider adding a retry or circuit breaker for paymentservice calls.

**Remediation:** no fix applied (no_fix).

Evidence: `runs/v3-network-partition-paymentservice-s1-20261011T015649.667099Z`

## Currency service 30% packet loss causes latency spike (low)

**What happened:** A 30% packet loss to currencyservice increased checkout p95 latency to 2.8 s, exceeding the 1 s baseline, but error_rate stayed at 0.0.

**Root cause:** Network loss degraded communication with currencyservice, slowing price conversion calls.

**Log evidence:**

    frontend: {"http.req.id":"b16b024c-9d12-431d-83ba-d1dd5102289d","http.req.method":"GET","http.req.path":"/cart","http.resp.bytes":19307,"http.resp.status":200,"http.resp.took_ms":504,"message":"request complete","session":"7e313a25-e930-4404-b02b-b2d35acee6e8","severity":"debug","timestamp":"2026-10-11T01:59:

**Fix:** No fix applied; consider improving network reliability or adding retries for currencyservice calls.

**Remediation:** no fix applied (no_fix).

Evidence: `runs/v2-network-loss-currencyservice-s3-20261011T015849.366685Z`

## Fact-check

Numbers not found in the measured data (treat with caution): 17, 60
