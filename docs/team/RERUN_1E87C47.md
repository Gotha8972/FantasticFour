# Updated implementation rerun — 10 October 2026 UTC

Pulled upstream `1e87c47`. Used the NVIDIA-hosted `openai/gpt-oss-20b` model with low reasoning effort. No agent code was changed for this run.

## Baseline and checks

- 75 regression tests passed.
- Fresh baseline: `runs/baseline-study-20261010T185159.779897Z`.
- `baseline_suitable: true`; 300.006 measured seconds, 61 samples, 20 shoppers.
- 1,327 requests and 63 checkouts in the measurement window; zero failures in either.
- No collection errors, restart increases, or pod changes during baseline.
- Dry run: `runs/agents-20261010T185840Z`; 23.737 seconds total (audit 8.983, plan 5.717, safety 8.135).
- 8 findings accepted, zero evidence rejected; plan includes frontend pod failure and Redis pod kill, with a Redis integrity criterion.
- Oversized checkout probe was shrunk by deterministic bounds to 500 ms / 30 seconds.

## Live run

Artifacts: `runs/agents-20261010T185909Z`.

| Fault | Result | Worst observed errors | Worst p95 | Service ready after injection | Customer metrics recovered after injection | Score |
|---|---|---:|---:|---:|---:|---:|
| Frontend pod failure | Confirmed | 100% | 20,000 ms | 19.7 s | 40.5 s | 16 |
| Redis pod kill | Confirmed; cart lost | 12.5% | 5,800 ms | 3.2 s | 24.9 s | 0 |

Redis integrity evidence: the same session had one cart item before the fault and zero afterwards. The corrected checkout input produced no additional checkout integrity violation.

The guard removed each fault when customer limits were crossed. Recovery timestamps are sampled observations, not exact request-level failover timings. Scores use the latest blast radius penalty and should not be compared directly with older scores calculated under a different formula.

## Redis remediation approved and executed

The user approved Redis remediation. The workflow applied `redis-persistence`: a bound 1 GiB PVC and `--appendonly yes`. It reran the reviewed Redis pod kill and kept the fix.

| Redis metric | Before | After |
|---|---:|---:|
| Cart integrity violations | 1 (cart emptied) | 0 |
| Score | 0 | 27 |
| Worst observed error rate | 12.5% | 17.86% |
| Worst observed p95 | 5,800 ms | 5,500 ms |
| Service ready after injection | 3.2 s | 4.1 s |
| Customer metrics recovered after injection | 24.9 s | 17.1 s |

After-fix artifacts: `runs/v1-pod-kill-redis-cart-after-20261010T190234.446628Z`. The score improved because the integrity penalty disappeared. Availability remains vulnerable: Redis still has one replica and errors persisted during restart. This single rerun does not establish a reliable latency improvement. Both runs requested the same reviewed fault and duration, but the guard stopped them at different times (before: 8.38 seconds after injection; after: 0.64 seconds), so actual exposure differs. The after-fix preflight was healthy (zero errors, p95 23 ms).

The catalog contains no reviewed frontend fix. The third experiment was a product catalog pod kill; its outcome is recorded below.

Resume from the original local checkout (checkpoint databases are excluded from Git):

```bash
.venv/bin/python -m chaosmind.graph --resume runs/agents-20261010T185909Z
```

## Assessment

Audit evidence verification, fault diversity, safety bounds, guard cleanup, integrity detection and checkpointing worked in this run. Severity labels still vary between dry and live audits, so they remain hypotheses; the code verifies evidence, not every interpretation. This run does not estimate failure probabilities: repeated comparable trials are required for that.

## Final catalog experiment

The product catalog pod kill confirmed customer impact (score 53). Raw measurements: `{"error_rate": 0.16666666666666666, "p95_ms": 80.0, "unhealthy_count": 1, "breach": {"metric": "error_rate", "value": 0.16666666666666666, "limit": 0.05}, "recovery_s": 9.916, "service_ready_s": 3.2, "customer_recovered_s": 18.9, "users": 20, "integrity_violations": 0}`. No integrity violations occurred. Its fault was removed and health recovered. The workflow is checkpointed at a separate human gate for `productcatalog-replicas`; Redis approval does not approve this fix. Catalog remains at one replica pending that decision.

## Status after review

- **The after-fix Redis re-run measured part of the fix's own rollout.** Its latency hit 5,500 ms 0.6 s after the kill, too early for the kill to cause it (in the before run the same kill took 8.4 s to show). Remediation had applied the fix (which restarts Redis) and re-run immediately. **Fixed:** `remediation.settle()` now waits until customers have been within the limits for 30 s before re-running. The score change (0 → 27) holds anyway: both runs hit the error and latency caps, so the difference is exactly the removed integrity penalty.
- **Frontend fix added** to the reviewed catalog (`frontend-replicas`, 2 replicas), so the AI can now fix what it found.
- **Scores corrected** in README/FINDINGS from the [scoreboard](../evidence/SCOREBOARD.md), now computed for the manual Redis test from its own load-generator snapshots: Redis cart test **30 → 67** (was shown as 55 → 99, which ignored the restart latency). The frontend is a new ranked finding (#2, score 16).
- **Next (optional, strong for the video):** `git pull`, then resume this run and approve the **catalog** fix. The re-run now waits for the rollout to settle, so it gives a clean before/after (53 → expected ~99, matching the 5-trial result):
  ```bash
  .venv/bin/python -m chaosmind.graph --resume runs/agents-20261010T185909Z
  ```
  Then push `runs/agents-20261010T185909Z/history.json`, and regenerate the scoreboard with `python3 -m chaosmind.agents.scoreboard > docs/evidence/SCOREBOARD.md`. The catalog's after-fix row fills in automatically.
