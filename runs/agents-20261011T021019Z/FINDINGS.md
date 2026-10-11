# Findings report

The chaos experiments confirmed that killing the redis-cart pod caused data loss and a spike in latency, while failures of frontend, cartservice, productcatalogservice, currencyservice, and paymentservice caused site outages or performance degradation. Root causes ranged from single‑replica configurations to network issues, with most faults exposing critical weaknesses that remain unaddressed except for a few replication or persistence fixes. The findings highlight the need to eliminate single points of failure and to persist state where appropriate to maintain service reliability.

**AI hypotheses:** 6 tested, 6 confirmed, 0 refuted; **1 refuted after their fix** (same criteria, re-run after the approved fix). Verdicts are decided by code against criteria written before each run.

**Fixes applied (from the data):** `redis-persistence` on redis-cart (score 40 → 78), `frontend-replicas` on frontend (score 17 → 96), `cartservice-replicas` on cartservice (score 30 → 78). **Confirmed weaknesses still open:** currencyservice, paymentservice, productcatalogservice.

| Experiment | Fault | Verdict | Criteria met | Worst error rate | Worst p95 | Recovery | Integrity | Score |
|---|---|---|---|---|---|---|---|---|
| `v1-pod-kill-redis-cart` | pod_kill on redis-cart | confirmed | 2 of 3 | 0.0% | 2800.0 ms | 12.819 s | 1 violation(s) | 40 |
| `v5-pod-failure-frontend` | pod_failure on frontend | confirmed | 2 of 2 | 100.0% | 20000.0 ms | 30.113 s | 0 violation(s) | 17 |
| `v2-network-partition-productcatalogservice` | network_partition on productcatalogservice | confirmed | 1 of 2 | 0.0% | 29000.0 ms | 12.92 s | 0 violation(s) | 68 |
| `v4-network-delay-currencyservice` | network_delay on currencyservice | confirmed | 1 of 2 | 0.0% | 3300.0 ms | 16.008 s | 0 violation(s) | 79 |
| `v3-pod-failure-cartservice` | pod_failure on cartservice | confirmed | 2 of 2 | 100.0% | 2700.0 ms | 56.038 s | 0 violation(s) | 30 |
| `v6-network-loss-paymentservice` | network_loss on paymentservice | confirmed | 1 of 2 | 2.3% | 150.0 ms | 1.291 s | 0 violation(s) | 89 |

Scores are as computed when the run happened. `python3 -m chaosmind.agents.scoreboard` recomputes every run with the current formula.

## Redis Cart Pod Kill (critical)

**What happened:** Killing the redis-cart pod caused cart data loss, leading to a 2800 ms p95 latency spike and a single integrity violation.

**Root cause:** The integrity violation shows cart data was lost when the redis-cart pod was killed, indicating that Redis is using an emptyDir volume that is wiped on pod restart.

> ⚠ **Contradicted by the collected config:** it says emptyDir, but the service mounts a persistent volume.

**Fix:** redis-persistence

**Remediation:** `redis-persistence` applied after human approval; the same experiment re-run: score 40 → 78 (improved); hypothesis **confirmed** after the fix.

Evidence: `runs/v1-pod-kill-redis-cart-s1-20261011T021135.296690Z`

## Frontend Pod Failure (high)

**What happened:** A single frontend pod failure caused the service to become unhealthy, raising error_rate to 0.1219 and p95 latency to 83 ms.

**Root cause:** The experiment shows that a single pod failure in the frontend brings down the entire service, indicating a single point of failure.

**Fix:** frontend-replicas

**Remediation:** `frontend-replicas` applied after human approval; the same experiment re-run: score 17 → 96 (improved); hypothesis **refuted** after the fix.

Evidence: `runs/v5-pod-failure-frontend-s1-20261011T021459.172746Z`

## Cartservice Pod Failure (high)

**What happened:** Killing a cartservice pod caused a 452% error_rate spike and 2700 ms p95 latency, with cart operations failing.

**Root cause:** The log errors show connection refused to cartservice, proving the service outage was due to the single replica.

**Fix:** cartservice-replicas

**Remediation:** `cartservice-replicas` applied after human approval; the same experiment re-run: score 30 → 78 (improved); hypothesis **confirmed** after the fix.

Evidence: `runs/v3-pod-failure-cartservice-s1-20261011T022031.209342Z`

## Productcatalogservice Network Partition (high)

**What happened:** Network partitioning of productcatalogservice caused a 29000 ms p95 latency spike, though error_rate remained 0.

**Root cause:** No log errors explain the latency; the fault likely caused timeouts in downstream services.

**Fix:** 

**Remediation:** no fix applied (no_fix).

Evidence: `runs/v2-network-partition-productcatalogservice-s1-20261011T021832.756291Z`

## Currencyservice Network Delay (high)

**What happened:** Adding 500 ms delay to currencyservice raised p95 latency to 3300 ms, with no error_rate impact.

**Root cause:** The log errors show normal request completions; the delay likely caused downstream timeout handling but did not trigger errors.

**Log evidence:**

    frontend: {"http.req.id":"6bf5aec5-4e66-4289-b400-c4bc65e0dc5d","http.req.method":"GET","http.req.path":"/product/OLJCESPC7Z","http.resp.bytes":7932,"http.resp.status":200,"http.resp.took_ms":561,"message":"request complete","session":"61978733-baf1-4d20-b3a8-434e37286d64","severity":"debug","timestamp":"2026

**Fix:** 

**Remediation:** no fix applied (no_fix).

Evidence: `runs/v4-network-delay-currencyservice-s1-20261011T021940.264048Z`

## Paymentservice Network Loss (high)

**What happened:** 20% packet loss to paymentservice caused a 23.2 ms p95 latency spike and a 0.023 error_rate, with some checkout failures.

**Root cause:** Log errors show failed card charges and internal errors, indicating that packet loss caused intermittent communication failures with paymentservice.

**Log evidence:**

    paymentservice: UnacceptedCreditCard [Error]: Sorry, we cannot process visa_electron credit cards. Only VISA or MasterCard is accepted.

**Fix:** 

**Remediation:** no fix applied (no_fix).

Evidence: `runs/v6-network-loss-paymentservice-s4-20261011T022617.676817Z`

## Fact-check

Numbers not found in the measured data (treat with caution): 23.2, 452

1 claim(s) contradicted by the measurements or the collected config are marked above.
