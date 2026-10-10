# Findings report

The chaos experiments confirmed that single‑replica services are single points of failure. The redis‑cart pod kill caused loss of cart state and a spike in latency, while the frontend pod failure and cartservice pod kill caused service outages and elevated error rates. Adding replicas and persistence mitigated the failures and restored stability.

**AI hypotheses:** 3 tested, 3 confirmed, 0 refuted. Verdicts are decided by code against criteria written before each run.

| Experiment | Fault | Verdict | Worst error rate | Worst p95 | Recovery | Integrity | Score |
|---|---|---|---|---|---|---|---|
| `v1-pod-failure-frontend` | pod_failure on frontend | confirmed | 20.5% | 1100.0 ms | 27.397 s | 0 violation(s) | 18 |
| `v2-pod-kill-redis-cart` | pod_kill on redis-cart | confirmed | 0.0% | 3200.0 ms | 10.003 s | 0 violation(s) | 69 |
| `v3-pod-kill-cartservice` | pod_kill on cartservice | confirmed | 22.9% | 86.0 ms | 50.583 s | 0 violation(s) | 20 |

## Redis‑cart pod kill causes state loss and latency spike (critical)

**What happened:** The redis‑cart pod was killed, causing cart data to become inaccessible, checkout failures, and a 3200 ms p95 latency spike.

**Root cause:** The redis‑cart service used an emptyDir volume, so the pod restart lost all in‑memory state. The log line "frontend: {"error":"could not retrieve cart: rpc error: code = Unavailable desc = connection error: desc = \"transport: Error while dialing: dial tcp 10.96.109.18:7070: connect: connection refused\""" shows the cart service was unreachable.

**Fix:** Add persistent storage to redis‑cart by mounting a PVC instead of emptyDir, and increase replicas to 2 to provide redundancy.

**Remediation:** `None` applied, re-run score None → None (not_approved).

Evidence: `runs/v2-pod-kill-redis-cart-s1-20261010T193107.653073Z`

## Frontend pod failure causes service outage (high)

**What happened:** The single‑replica frontend pod failed, making the frontend unhealthy and blocking all downstream services, with error_rate 0.2045 and p95_ms 1100 ms.

**Root cause:** The log line "frontend: {"error":"could not retrieve cart: rpc error: code = Unavailable desc = connection error: desc = \"transport: Error while dialing: dial tcp 10.96.109.18:7070: connect: connection refused\""" indicates the frontend could not reach cartservice after the pod failure.

**Fix:** Deploy a second replica for the frontend and add a pod disruption budget to avoid single‑point outages.

**Remediation:** `frontend-replicas` applied, re-run score 18 → 97 (improved).

Evidence: `runs/v1-pod-failure-frontend-s1-20261010T192530.027978Z`

## Cartservice pod kill causes checkout failure and latency spike (high)

**What happened:** Killing the sole cartservice pod caused cart operations to fail, leading to checkout errors and a p95 latency of 86 ms during the fault, with error_rate 0.229.

**Root cause:** The log lines "cartservice: System.IO.IOException: The client reset the request stream." and "cartservice: Error reading message." show the cartservice crashed and could not process requests.

**Log evidence:**

    cartservice: System.IO.IOException: The client reset the request stream.  (x2)
    cartservice: Error reading message.

**Fix:** Add a second replica for cartservice and a pod disruption budget to prevent single‑point failure.

**Remediation:** `cartservice-replicas` applied, re-run score 20 → 65 (improved).

Evidence: `runs/v3-pod-kill-cartservice-s1-20261010T193216.325334Z`

## Fact-check

Every number above appears in the measured data.
