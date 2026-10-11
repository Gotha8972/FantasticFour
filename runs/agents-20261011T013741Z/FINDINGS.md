# Findings report

The chaos experiments exposed critical single‑replica weaknesses across the checkout path, causing significant error spikes and service unavailability. All affected services recovered within seconds, but the lack of PDB/HPA left them vulnerable to repeated outages. Implementing replicas for cartservice and productcatalogservice mitigated the most severe failures, while other services still require architectural changes.

**AI hypotheses:** 4 tested, 3 confirmed, 1 refuted; **1 refuted after their fix** (same criteria, re-run after the approved fix). Verdicts are decided by code against criteria written before each run.

| Experiment | Fault | Verdict | Criteria met | Worst error rate | Worst p95 | Recovery | Integrity | Score |
|---|---|---|---|---|---|---|---|---|
| `v1-pod-kill-productcatalogservice` | pod_kill on productcatalogservice | refuted | 0 of 1 | 54.5% | 73.0 ms | 9.98 s | 0 violation(s) | 53 |
| `v2-pod-kill-cartservice` | pod_kill on cartservice | confirmed | 2 of 2 | 100.0% | 2300.0 ms | 56.2 s | 0 violation(s) | 31 |
| `v3-pod-kill-currencyservice` | pod_kill on currencyservice | confirmed | 1 of 2 | 100.0% | 120.0 ms | 24.6 s | 0 violation(s) | 49 |
| `v5-pod-kill-paymentservice` | pod_kill on paymentservice | confirmed | 1 of 2 | 4.8% | 170.0 ms | 1.356 s | 0 violation(s) | 85 |

Scores are as computed when the run happened. `python3 -m chaosmind.agents.scoreboard` recomputes every run with the current formula.

## Productcatalogservice pod kill (high)

**What happened:** Killing the sole productcatalogservice pod caused 54.5% error rate and 73 ms p95 latency during the fault, but the service recovered in 9.98 s.

**Root cause:** The service had no PDB or HPA and a single replica, so the pod kill left no fallback. Evidence: "frontend: {\"error\":\"could not retrieve product: rpc error: code = Unavailable desc = connection error: desc = \"transport: Error while dialing: dial tcp 10.96.223.78:3550: connect: connection refused\"\""

**Fix:** Add a second replica and enable a PDB to prevent single‑point failures. The remediation plan for cartservice demonstrates the expected improvement.

Evidence: `runs/v1-pod-kill-productcatalogservice-s1-20261011T014016.063696Z`

## Cartservice pod kill (high)

**What happened:** Killing the sole cartservice pod raised error rate to 45.2% and p95 latency to 2,300 ms, but the service recovered in 56.2 s.

**Root cause:** Single‑replica without PDB/HPA caused a complete outage. Evidence: "frontend: {\"error\":\"could not retrieve cart: rpc error: code = Unavailable desc = connection error: desc = \"transport: Error while dialing: dial tcp 10.96.109.18:7070: connect: connection refused\"\""

**Fix:** Increase replicas to 2 and add a PDB. The remediation increased the score to 95 and eliminated the error spike.

**Remediation:** `cartservice-replicas` applied after human approval; the same experiment re-run: score 31 → 95 (improved); hypothesis **refuted** after the fix.

Evidence: `runs/v2-pod-kill-cartservice-s1-20261011T014049.991491Z`

## Currencyservice pod kill (high)

**What happened:** Killing the single currencyservice pod caused a 16.3% error rate and 120 ms p95 latency, recovering in 24.6 s.

**Root cause:** No redundancy for currencyservice left the checkout flow unable to convert prices. Evidence: "frontend: {\"error\":\"could not retrieve currencies: rpc error: code = Unavailable desc = connection error: desc = \"transport: Error while dialing: dial tcp 10.96.54.127:7000: connect: connection refused\"\""

**Fix:** No fix was applied; a future patch should add replicas or a PDB.

**Remediation:** no fix applied (no_fix).

Evidence: `runs/v3-pod-kill-currencyservice-s1-20261011T014421.042873Z`

## Paymentservice pod kill (high)

**What happened:** Killing the sole paymentservice pod raised error rate to 4.8% and kept p95 latency at 170 ms, recovering in 1.36 s.

**Root cause:** Single‑replica without PDB/HPA caused payment failures. Evidence: "frontend: {\"error\":\"failed to complete the order: rpc error: code = Internal desc = failed to charge card: could not charge the card: rpc error: code = Unavailable desc = connection error: desc = \"transport: Error while dialing: dial tcp 10.96.220.189:50051: connect: connection refused\"\""

**Fix:** No fix was applied; adding replicas or a PDB would eliminate the outage.

**Remediation:** no fix applied (no_fix).

Evidence: `runs/v5-pod-kill-paymentservice-s1-20261011T014513.958709Z`

## Fact-check

Numbers not found in the measured data (treat with caution): 300
