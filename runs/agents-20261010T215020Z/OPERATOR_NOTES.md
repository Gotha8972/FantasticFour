# Operator notes: recorded AI run

Recorded on camera with the mission-control UI; both fixes were approved by a human in the browser (`--ui`, no `--auto-approve`). An earlier attempt was aborted because of host CPU load, not the shop; see [agents-20261010T214437Z](../agents-20261010T214437Z/OPERATOR_NOTES.md).

**Correction to the Analyst's summary.** [FINDINGS.md](FINDINGS.md) says "All three failures were mitigated by adding replicas or persistent storage, restoring service health and eliminating integrity violations." The raw data ([history.json](history.json)) says otherwise for checkout:

| Experiment | Before | Fix | After | After-fix verdict |
|---|---|---|---|---|
| `v2-pod-failure-frontend` | confirmed, score 17 (errors 100%) | `frontend-replicas`, approved | score 96, 0 integrity violations | **refuted** |
| `v1-pod-kill-redis-cart` | confirmed, score 43 (cart 1 → 0 items) | `redis-persistence`, approved | score 80, cart kept (0 integrity violations) | confirmed (p95 criterion only: one Redis replica still stalls during a restart) |
| `v3-pod-failure-checkoutservice` | confirmed, score 41 (errors 7.1%, checkout HTTP 500) | **none**: no reviewed fix for checkoutservice in the catalog | not re-run | — |

So two of the three weaknesses were fixed and proven; checkout remains open. The report's fact-check passed because it verifies numbers and data-loss claims, not claims about which fixes were applied.

**Checkout integrity violation:** the order check ran after the guard reported the shop healthy (4.3 s after the revert) and still got HTTP 500, i.e. checkout was not yet serving orders when the metrics looked normal. This is one sample; the baseline's background checkout failure rate is ~1.3%, so it is consistent with, but does not on its own prove, the "healthy ≠ recovered" finding.
