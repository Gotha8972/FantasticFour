# Findings report

The Redis‑cart pod kill caused cart data loss and a 12.5% error rate, confirming the critical vulnerability V1. A frontend pod failure brought the entire site down, validating V3’s single‑replica risk. Killing the product catalog pod increased error rate to 16.7% and latency to 80 ms, demonstrating V5’s impact on checkout flow.

**AI hypotheses:** 3 tested, 3 confirmed, 0 refuted; **1 refuted after their fix** (same criteria, re-run after the approved fix). Verdicts are decided by code against criteria written before each run.

| Experiment | Fault | Verdict | Criteria met | Worst error rate | Worst p95 | Recovery | Integrity | Score |
|---|---|---|---|---|---|---|---|---|
| `v3-pod-failure-frontend` | pod_failure on frontend | confirmed | 1 of 1 | 100.0% | 20000.0 ms | 34.699 s | 0 violation(s) | 16 |
| `v1-pod-kill-redis-cart` | pod_kill on redis-cart | confirmed | 2 of 2 | 12.5% | 5800.0 ms | 16.483 s | 1 violation(s) | 0 |
| `v5-pod-kill-productcatalogservice` | pod_kill on productcatalogservice | confirmed | 1 of 2 | 16.7% | 80.0 ms | 9.916 s | 0 violation(s) | 53 |

Scores are as computed when the run happened. `python3 -m chaosmind.agents.scoreboard` recomputes every run with the current formula.

## Redis‑cart pod kill (critical)

**What happened:** Killing the redis‑cart pod removed all cart items, causing a 12.5% error rate and a 5800 ms p95 latency spike.

**Root cause:** The pod was running with an emptyDir volume that does not persist data across restarts.

**Fix:** Apply a persistent volume claim to the redis‑cart deployment (fix_id: redis-persistence) to preserve cart data across pod restarts.

**Remediation:** `redis-persistence` applied after human approval; the same experiment re-run: score 0 → 27 (improved); hypothesis **confirmed** after the fix.

Evidence: `runs/v1-pod-kill-redis-cart-s1-20261010T190025.868949Z`

## Frontend pod failure (critical)

**What happened:** The frontend pod crashed, making the entire site unreachable and raising error_rate to 23.1% during the fault.

**Root cause:** The frontend service runs as a single replica with no PDB/HPA, so a pod failure brings the whole site down.

**Fix:** Introduce a second replica and a PodDisruptionBudget for the frontend service to ensure high availability.

**Remediation:** no fix applied (no_fix).

Evidence: `runs/v3-pod-failure-frontend-s1-20261010T185929.812984Z`

## Product catalog pod kill (medium)

**What happened:** Killing the sole productcatalogservice pod caused a 16.7% error rate and 80 ms p95 latency, breaching the 5% error threshold.

**Root cause:** The service is a single replica with no PDB/HPA, creating a single point of failure for product data.

**Fix:** Add additional replicas to productcatalogservice (fix_id: productcatalog-replicas) and configure a PodDisruptionBudget to eliminate the outage.

**Remediation:** `productcatalog-replicas` applied after human approval; the same experiment re-run: score 53 → 99 (improved); hypothesis **refuted** after the fix.

Evidence: `runs/v5-pod-kill-productcatalogservice-s1-20261010T190304.133613Z`

## Fact-check

Every number above appears in the measured data.
