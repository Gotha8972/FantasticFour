# Findings report

The chaos experiments confirmed that single‑replica services are vulnerable to outages and performance degradation. A pod failure in the frontend caused a critical site outage, while killing the cartservice led to a high‑severity error spike and service disruption. Redis‑cart pod termination produced a high‑latency slowdown but no data loss, highlighting the need for persistence and replication.

**AI hypotheses:** 3 tested, 3 confirmed, 0 refuted; **1 refuted after their fix** (same criteria, re-run after the approved fix). Verdicts are decided by code against criteria written before each run.

| Experiment | Fault | Verdict | Criteria met | Worst error rate | Worst p95 | Recovery | Integrity | Score |
|---|---|---|---|---|---|---|---|---|
| `v1-pod-failure-frontend` | pod_failure on frontend | confirmed | 2 of 2 | 100.0% | 20000.0 ms | 27.397 s | 0 violation(s) | 18 |
| `v2-pod-kill-redis-cart` | pod_kill on redis-cart | confirmed | 1 of 3 | 0.0% | 3200.0 ms | 10.003 s | 0 violation(s) | 69 |
| `v3-pod-kill-cartservice` | pod_kill on cartservice | confirmed | 2 of 2 | 100.0% | 2900.0 ms | 50.583 s | 0 violation(s) | 20 |

Scores are as computed when the run happened. `python3 -m chaosmind.agents.scoreboard` recomputes every run with the current formula.

## Frontend pod failure caused site outage (critical)

**What happened:** The sole frontend pod crashed, making the service unhealthy and blocking all downstream traffic. Error rate spiked to 0.2045 and p95 latency reached 1100 ms during the fault.

**Root cause:** Single‑replica entrypoint with no pod disruption budget caused the entire frontend to become unhealthy.

**Fix:** Add a second replica to the frontend deployment (frontend-replicas) to provide redundancy and prevent single‑point failure.

**Remediation:** `frontend-replicas` applied after human approval; the same experiment re-run: score 18 → 97 (improved); hypothesis **refuted** after the fix.

Evidence: `runs/v1-pod-failure-frontend-s1-20261010T192530.027978Z`

## Cartservice pod kill caused high error rate and outage (high)

**What happened:** Killing the only cartservice pod caused error_rate to breach 0.05 and p95 latency to spike to 2900 ms. The service remained unhealthy for 50.583 seconds before recovering.

**Root cause:** Single‑replica cartservice with no pod disruption budget led to a service outage when the pod was killed.

**Fix:** Increase cartservice replicas to 2 (cartservice-replicas) to eliminate single‑point failure.

**Remediation:** `cartservice-replicas` applied after human approval; the same experiment re-run: score 20 → 65 (improved); hypothesis **confirmed** after the fix.

Evidence: `runs/v3-pod-kill-cartservice-s1-20261010T193216.325334Z`

## Redis-cart pod kill caused high latency but no data loss (medium)

**What happened:** Killing the redis-cart pod caused p95 latency to reach 3200 ms, breaching the 1000 ms threshold. No integrity violations were recorded.

**Root cause:** Redis-cart is a stateful service using an emptyDir volume; pod termination loses in‑memory state and causes latency spikes.

> ⚠ **Contradicted by the collected config:** it says emptyDir, but the service mounts a persistent volume.

**Fix:** Add persistent storage via a PVC (redis-persistence) to preserve cart state across pod restarts and reduce latency.

**Remediation:** no fix applied (not_approved).

Evidence: `runs/v2-pod-kill-redis-cart-s1-20261010T193107.653073Z`

## Fact-check

Every number above appears in the measured data.

1 claim(s) contradicted by the measurements or the collected config are marked above.
