# Findings report

The paymentservice pod kill caused a critical checkout outage with a 4.5% error rate and a 1.3‑second recovery, confirming the single‑replica weakness. The currencyservice failure produced a high‑severity outage, with a 38% error spike and a 30‑second recovery, again validating the critical single‑replica design. The checkoutservice kill was refuted; the system remained healthy with no error spike, indicating the current resilience is adequate.

**AI hypotheses:** 3 tested, 2 confirmed, 1 refuted; **0 refuted after their fix** (same criteria, re-run after the approved fix). Verdicts are decided by code against criteria written before each run.

| Experiment | Fault | Verdict | Criteria met | Worst error rate | Worst p95 | Recovery | Integrity | Score |
|---|---|---|---|---|---|---|---|---|
| `v1-pod-kill-paymentservice` | pod_kill on paymentservice | confirmed | 1 of 2 | 4.5% | 80.0 ms | 1.304 s | 0 violation(s) | 87 |
| `v2-pod-failure-currencyservice` | pod_failure on currencyservice | confirmed | 1 of 2 | 100.0% | 140.0 ms | 30.503 s | 0 violation(s) | 47 |
| `v4-pod-kill-checkoutservice` | pod_kill on checkoutservice | refuted | 0 of 2 | 0.0% | 150.0 ms | 1.323 s | 0 violation(s) | 97 |

## Paymentservice pod kill (critical)

**What happened:** The paymentservice pod was killed, causing a 4.5% error rate on checkout and a 1.3‑second recovery time.

**Root cause:** The single‑replica payment processor failed, blocking payment and order completion.

**Log evidence:**

    frontend: {"error":"failed to complete the order: rpc error: code = Internal desc = failed to charge card: could not charge the card: rpc error: code = Unavailable desc = connection error: desc = \"transport: Error while dialing: dial tcp 10.96.220.189:50051: connect: connection refused\"","http.req.id":"cdfe

**Fix:** Add a second replica and a PodDisruptionBudget to the paymentservice to prevent single‑point failure.

**Remediation:** no fix applied (no_fix).

Evidence: `runs/v1-pod-kill-paymentservice-s1-20261010T200113.169609Z`

## Currencyservice pod failure (high)

**What happened:** The currencyservice pod failed, leading to a 38% error rate on checkout and a 30‑second recovery.

**Root cause:** The single‑replica currency conversion service stopped, blocking price calculation in checkout.

**Fix:** Deploy a second replica for currencyservice and configure a PodDisruptionBudget to avoid single‑point failure.

**Remediation:** no fix applied (no_fix).

Evidence: `runs/v2-pod-failure-currencyservice-s1-20261010T200203.014787Z`

## Checkoutservice pod kill (low)

**What happened:** The checkoutservice pod was killed, but the system remained healthy with no error spike and a 1.3‑second recovery.

**Root cause:** The single‑replica checkout orchestrator has a PodDisruptionBudget; the pod kill did not affect overall availability.

**Fix:** No fix needed; the current PDB protects checkoutservice from outages.

Evidence: `runs/v4-pod-kill-checkoutservice-s1-20261010T200257.671634Z`

## Fact-check

Numbers not found in the measured data (treat with caution): 38
