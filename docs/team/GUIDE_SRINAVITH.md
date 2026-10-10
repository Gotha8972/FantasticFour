# Srinavith: Safety Checker, Remediation, demo story

Read [GUIDE_00_EVERYONE.md](GUIDE_00_EVERYONE.md) first.

**Your role:** you own the "hands", everything that **changes** the cluster: injector, guard, Safety Checker, Remediation. Today you prove the fix loop live (the demo's strongest moment) and own the story.

---

## 1. Know your code (≈20 min)
| File | Key ideas to explain |
|---|---|
| `inject.py` | 7 fault types with caps; namespace-only; ownership labels; `LIVE_VERIFIED` gates what the AI may use |
| `guard.py` | Preflight → inject → poll every 2 s → revert on breach → confirm recovery. `watch_breach()`: a moderate error spike must last 2 polls, so background 500s (~1.3% of checkouts) don't cause false trips |
| `agents/safety.py` | **Only-smaller rule** in code; ramp starts at 1/8 intensity; reports `tolerated_up_to` and `limit_crossed_at` ("crossed our safety limit", not "the system died") |
| `agents/remediation.py` | The AI **picks** from `remediation/catalog.json`, never writes patches. Dry run → apply → re-run the identical experiment → keep only if the score improves, else roll back |
| `scripts/redis-fix.sh` | Manual apply/revert of the Redis fix (PVC + append-only log + Recreate) |

## 2. Redis before/after, live (with Aashrith, ≈30 min)
**Graceful restart: done ✅** (Aashrith, [REDIS_FIX_RESULTS.md](../evidence/REDIS_FIX_RESULTS.md): cart 1 → 0 before, 1 → 1 after). **Still to prove: the instant kill**, plus the AI choosing this fix itself:
- **Through the AI:** `.venv/bin/python -m chaosmind.graph --budget 2 --remediate`. If the Strategist picks Redis and the integrity check confirms it, Remediation should choose `redis-persistence` and the re-run should show no `cart_persistence` violation.
- **Manually** (fallback): `bash scripts/redis-fix.sh apply`, then `./tests/redis_finding.sh` → the cart survives. Then the instant-kill test in [A_REDIS_FIX_AND_FAULTS.md](A_REDIS_FIX_AND_FAULTS.md), section 3B.

Second target: **cart service replicas 1 → 2** (`cartservice-replicas` in the catalog), then re-run `experiments/test-down.json`. Expect the error rate and recovery time to drop. Pod failure only takes out one of the two pods (`mode: one`).

## 3. Record a Safety Checker rejection (≈10 min)
Create a risky experiment (e.g. `network_delay` 2000 ms for 120 s on `checkoutservice`) and run:
```bash
python3 -m chaosmind.agents.safety <file> --review-only
```
If the AI approves it, add an explicit rule to `SYSTEM` in `safety.py` (e.g. "shrink anything on the checkout path to ≤ 500 ms and ≤ 60 s"). **A visible rejection is a great 10-second demo clip.**

## 4. Keep the claims honest
As Aashrith verifies fault types live, update the README's coverage table ("Defined, not yet run" → "✅") and `LIVE_VERIFIED`. **Never claim a fault type we haven't run.**

## 5. Demo narration (your 45 s)
> "Our AI never touches the cluster. It proposes; code validates; the kill switch can always pull the plug. The Safety Checker ramped catalog latency step by step; it tolerated X ms and crossed our limit at Y. Our auditor flagged Redis before we broke anything; the experiment proved it: carts wiped with zero errors, caught only by our integrity check. Remediation picked a reviewed fix, re-ran the identical experiment, and the cart survived. Score A → B."

## What to learn
- **JSON Patch** and `kubectl patch --type=json --dry-run=server`
- **Stateful vs stateless:** why replicas fix the cart service but would *break* Redis (each copy holds different carts)
- **Rollback-first design:** know the undo before you do anything
