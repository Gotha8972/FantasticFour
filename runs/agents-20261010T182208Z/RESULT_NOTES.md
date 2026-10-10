# Live run notes

Fresh baseline `runs/baseline-study-20261010T181454.739973Z`: suitable=true, 300.069 seconds, 61 samples, 1,308 requests / zero failures, 55 checkouts / zero failures. No restarts or supporting export errors.

A preceding baseline failed when a history read OOM-killed Locust's main container (512 MiB limit). `monitor.READ_STATS` now reads at most the last 1 MiB of history, using the same complete-row approach as the exporter. A synthetic 100,001-row history with an incomplete final row selected the latest complete aggregate correctly. Guard tests passed.

Healthy dry run `runs/agents-20261010T182111Z` took 45.819 seconds, including all three model calls. Audit 34.327 s, plan 7.786 s, safety 2.763 s. It proposed two fault types and approved the Redis kill. Oversized checkout safety probe was rejected rather than shrunk: safe, but differs from the guide's exact expected output.

Live audit kept one vulnerability and rejected seven due to incorrect evidence types or unknown service `all`; this exposes model-output reliability problems despite correct validation.

The Redis kill confirmed empty-cart data loss. Raw history reports two integrity failures; the second (checkout HTTP 422) is a checker defect, not fault evidence: the card number contained hyphens, and the healthy shop rejected it too. Correcting the number to match the frontend form makes healthy integrity verification pass. Original history remains intact. The reported score 33 therefore includes a confounding checkout-input defect; an after-fix comparison uses corrected input and must be interpreted with that limitation.

Run is checkpointed at `approve_fix`; catalogued redis-persistence remediation is pending human approval. No fix has been applied by this live agent run yet.
