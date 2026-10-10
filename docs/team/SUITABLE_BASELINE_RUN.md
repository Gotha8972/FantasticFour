# Fresh suitable baseline and implementation run

## Baseline and fixes

Run: `runs/baseline-study-20261010T181454.739973Z`.
`baseline_suitable: true`, completed, 300.069 s measured, 61 samples, 20 shoppers. 1,308 requests and 55 checkouts; zero failures in either. No restarts, configuration changes during collection, or supporting export errors. Root `baseline.json` is this measured result.

An earlier attempt (`181201.538959Z`) failed when Locust's main container was OOMKilled (exit 137, 512 MiB limit). Host available RAM was ~7 GiB. `monitor.READ_STATS` was loading the whole accumulated CSV history inside that container; now it reads a bounded 1 MiB tail and ignores incomplete rows, following the exporter approach. Synthetic 100,001-row verification and guard tests passed; the next full baseline succeeded.

The guide's demo reset reverted Redis to emptyDir and catalog to one replica before measurement. The later probability comparison leaves catalog at two replicas. Redis remains on emptyDir while agent remediation awaits approval.

## Agent runs

Healthy dry run: `runs/agents-20261010T182111Z`.
NVIDIA-hosted `openai/gpt-oss-20b`, low reasoning effort. Total 45.819 s: audit 34.327 s, plan 7.786 s, safety 2.763 s. Eight validated findings, two planned fault types (pod kill / pod failure), Redis integrity criterion present, Redis kill approved. Dry run injected nothing and is inconclusive by design. The separate oversized checkout safety probe was rejected, rather than shrunk; safe, but differs from the guide's literal expected output.

Live run: `runs/agents-20261010T182208Z`, checkpointed at the human `approve_fix` gate. Seven audit claims were rejected for incorrect evidence types or unknown service `all`; one Redis vulnerability survived. This shows output variability remains even though validation works.

Redis pod kill was confirmed. The cart actually went from one item to zero. Service ready at 3.2 s, customer healthy at 14.5 s relative to run start; recovery after cleanup was 8.696 s. Peak sampled p95 was 3,000 ms; sampled error rate was zero. Raw score is 33.

Raw history records a second integrity failure (checkout HTTP 422), which is NOT valid fault evidence: checker supplied a hyphenated card number that fails frontend validation even when healthy. `integrity.CHECKOUT_FORM` now uses the frontend's digits-only sample number; healthy verification returns no violations. Original evidence is preserved; raw score/after-fix comparisons must carry this limitation.

No Redis remediation or comparison rerun has been performed: the guide and LangGraph require human approval at that gate. Resume with `.venv/bin/python -m chaosmind.graph --resume runs/agents-20261010T182208Z` after approval. Checkpoints remain local.

## Catalog probability trials

Five attempted guarded catalog pod kills per replica count, 20 shoppers, 30-second configured duration, same customer thresholds.

| Catalog replicas | Valid | Invalid | Breaches | Observed breach rate | 95% Wilson interval |
| --- | ---: | ---: | ---: | ---: | --- |
| 1 | 3 | 2 | 3 | 100% | 43.8–100% |
| 2 | 5 | 0 | 0 | 0% | 0–43.4% |

The two invalid one-replica trials hit zero completed RPS during the fault and were excluded. This censoring limits confidence; the comparison is conditional on valid trials, not a production outage probability. No claim of perfect reliability follows from 0/5.

One-replica service-ready times: 3.1–3.2 s; customer-recovered timestamps: 37.5–37.8 s. Two-replica service-ready times: 3.2 s; customer-recovered timestamps: 32.1 s. These customer timestamps include the runner's observation duration and are not outage lengths. Both conditions completed cleanup; no chaos resources remain, all deployments are ready.

Trials: `runs/trials-catalog-podkill-20261010T182606Z` and `runs/trials-catalog-podkill-20261010T183121Z`.

## Verification and remaining work

71 regression tests passed (16 guard + 55 agent/day2/capture/graph/portable), including after both fixes. Mock-based regression tests do not substitute for the live evidence above.

Remaining: approve Redis persistence, rerun the reviewed fault with the corrected integrity input, complete any remaining agent plan. Model evidence typing, severity ranking, and zero-RPS handling during real outages still deserve review. This report does not claim the full live remediation loop is complete.

Upstream agent implementation tested: `d1c6cee`; latest memory-guide update `5f825b1` was pulled before publishing. That later Docker shutdown recommendation wasn't needed for this successful baseline (~7 GiB available already); no other applications were shut down.
