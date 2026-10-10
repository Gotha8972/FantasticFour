# Operator review of model output

The code verdicts and measurements are preserved. The model's prose is not fully reliable:

- The Analyst says currencyservice caused 38% checkout errors. 38.46% was the aggregate error rate at the first guard breach, not the worst aggregate rate (100%) or the checkout failure rate. Over the complete observed window, 113/206 aggregate requests and 3/6 checkouts failed. The report's numeric fact check flags 38.
- The Analyst claims checkoutservice has a PodDisruptionBudget and that it protected the pod kill. The collected fact is `pdb: false`; the live namespace has no PDB objects. This explanation is unsupported. A PDB would not explain survival of a direct pod kill.
- Checkoutservice was ready again about 3.8 seconds after injection. Its checkout counter did not advance in the first two injected snapshots; new checkout completions appeared later. The refuted verdict means the preregistered thresholds were not crossed in this trial. It does not establish general resilience or checkout coverage during the brief actual outage.
- The dry-run audit accepted a Redis data-loss narrative despite a PVC. One explicit Strategist data-loss proposal was rejected, but corrected prose still referred to data loss and incorrectly said persistence preserves availability. Claim validation does not cover every phrasing.

No extra fixes were applied during this run. Existing Redis persistence and two replicas for frontend, cartservice, and productcatalogservice were retained. All new faults were cleaned up.
