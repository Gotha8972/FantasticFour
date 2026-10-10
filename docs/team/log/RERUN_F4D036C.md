# Rerun on f4d036c — 10 October 2026 UTC

Pulled `f4d036c` and synced 19 changed files. Used NVIDIA-hosted `openai/gpt-oss-20b` with low reasoning effort. Existing approved fixes remained applied: Redis PVC + append-only logging, and two replicas for frontend, cartservice and productcatalogservice.

## Regression checks and previous reports

The first suite had 78 passing tests and one failure. The rollback test's new applied-fix check accessed the real cluster, where cartservice already had two replicas, skipping its mocked rollback. Added a single `applied=False` mock to that test. All **79 tests passed** on rerun (63 suite + 16 guard). Production logic was not changed locally.

Regenerated both prior AI reports as instructed:

- `runs/agents-20261010T185909Z/FINDINGS.md`
- `runs/agents-20261010T192511Z/FINDINGS.md`

Both reports passed the numeric fact check. This checks numbers, not every causal explanation.

## Fresh baseline

`runs/baseline-study-20261010T195340.323671Z`

- `baseline_suitable: true`; 300.071 measured seconds, 61 samples, 20 shoppers.
- 1,329 requests, 51 checkouts, zero failures.
- No restart increases or suitability findings.

## Dry run

`runs/agents-20261010T195951Z`: five accepted audit findings, zero rejected evidence, two fault types. Error thresholds were at least 1%; a Redis integrity criterion was present. One explicit Redis data-loss proposal was rejected due to its PVC. Unsupported Redis data-loss language still appeared in audit and corrected-plan prose; deterministic fact verification does not validate all prose.

## Fresh live run completed

`runs/agents-20261010T200021Z`: seven audit findings accepted, one rejected. Two hypotheses confirmed and one refuted. No remediation was applied: no reviewed fixes existed for the two confirmed targets.

| Experiment | Verdict | Worst sampled aggregate errors | Worst p95 | Score | Whole observed window requests / failures | Whole observed window checkouts / failures |
|---|---|---:|---:|---:|---:|---:|
| Payment pod kill | Confirmed | 4.55% | 80 ms | 87 | 145 / 2 | 5 / 2 |
| Currency pod failure | Confirmed | 100% | 140 ms | 47 | 206 / 113 | 6 / 3 |
| Checkout pod kill | Refuted in this trial | 0% | 150 ms | 97 | 158 / 0 | 6 / 0 |

Worst sampled error rates differ from failure percentages across the whole window. Both confirmed verdicts met the preregistered error criterion (1%) without meeting the latency criterion. Payment did not cross the guard's 5% error stop limit; currency did and was reverted early. Currency customer metrics recovered 43.2 seconds after injection.

Checkout was ready 3.8 seconds after injection; no checkout counter advance appeared in the earliest injected snapshots. The refuted result is limited by brief outage and sparse checkout traffic, and is not evidence of general availability.

Scores use the new square-root formula and should not be compared directly with prior raw scores computed using the old formula.

## Report limitations and final health

The Analyst generated its report successfully, but its fact check flags an unsupported rounded number (38). It also invents a checkout PDB. The live namespace has no PDB objects, and the collected checkout PDB fact is false. Full corrections and caveats are in `runs/agents-20261010T200021Z/OPERATOR_NOTES.md`; raw Analyst prose is retained for evaluation.

No active new faults remain. Final sample: 20 shoppers, zero errors, p95 96 ms, no unavailable services. All deployments were ready. Existing fixes remain in place. This run is complete and has no pending approval.

## Status after review

- Thanks for the test fix (the rollback test reached the real cluster). Kept.
- **The PodDisruptionBudget claim was invented because the Analyst never saw the configuration.** Its fact sheet now includes each target's config (replicas, PDB, HPA, volumes, probes), the prompt says to describe config only from it, and code marks config claims the facts contradict (a PDB that doesn't exist, emptyDir on a persistent volume) next to the data-loss check. The "38" was already caught by the number check.
- **All three AI reports were re-rendered offline** from the saved `analyst_reply.json` (no API call): run 2 now marks "emptyDir", and run 3 marks the invented PDB. Each report notes that its scores are from run time; the [scoreboard](../../evidence/SCOREBOARD.md) recomputes every run with the current formula, run 3 included.
- **Findings:** currency is a new critical single point of failure (#3). Payment is a new honest finding (#6): its outage failed 2 of 5 checkouts while the overall error rate stayed under our kill switch's 5% limit. That's a blind spot in our own tool, documented, not fixed (feature freeze). The checkout refutation is in FINDINGS under "Hypotheses the AI got wrong".
- Dry-run prose still says "data loss" sometimes where facts show a PVC; experiments with that prediction are dropped and corrected by code, but free-text prose in the audit isn't fully checked. That's documented as a limitation.

Day 2 work on the cluster laptop is done. Remaining: the video, and the clean install on a second laptop.
