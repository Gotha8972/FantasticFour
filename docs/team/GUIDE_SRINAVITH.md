# Srinavith: injection, kill switch, Safety Checker + Remediation

Read [GUIDE_00_EVERYONE.md](GUIDE_00_EVERYONE.md) first.

**Your role:** you own the "hands" of the system: everything that **changes** the cluster. You built the injector, the guard and the Safety Checker. Today you add **⑤ Remediation**, the agent that *fixes* a weakness and **proves** the fix by re-running the same experiment. That's the strongest moment in the demo: "score 41 → 78".

---

## Part 0: Understand what you already own (≈20 min, read the code)
| File | What it does | Read these functions |
|---|---|---|
| `chaosmind/inject.py` | Experiment JSON → Chaos Mesh resource. 7 fault types, each with limits | `validate`, `manifest`, `apply`, `revert` |
| `chaosmind/guard.py` | Preflight → inject → watch every 2 s → revert on breach → confirm recovery | `run`, `breach` |
| `chaosmind/agents/safety.py` | AI approves/shrinks/rejects, then **ramps intensity** through the guard | `review`, `only_smaller`, `clean_ramp`, `run`, `observed` |
| `scripts/redis-fix.sh` + `remediation/` | The hand-written Redis fix (PVC + append-only log + Recreate) | — |

**Concepts to be able to explain:**
- **Why the AI never injects directly:** a hallucinated or manipulated AI reply could break something outside the sandbox. Code validates everything, and the guard can always overrule.
- **Ramp:** 100 → 200 → 400 ms, each step a full guarded run; stop at the first breach. That step is the **breaking point**.
- **Only smaller:** the Safety Checker may lower duration or intensity, never raise them or change the target, and **code** enforces it (`only_smaller`).

---

## Part 1: Safety Checker live (with Aashrith, ≈20 min)
After Aashrith's dry run works:
```bash
python3 -m chaosmind.agents.safety experiments/test-delay.json --review-only
```
This shows the AI's decision and ramp without injecting. Then one live ramp:
```bash
python3 -m chaosmind.agents.safety experiments/test-delay.json
```
**Expect:** steps like 125 → 250 → 500 ms, a `breaking_point`, and one `runs/` folder per step.

**For the demo:** record one **rejected** request too. Write an experiment with `"duration_s": 120` and `"latency": "2000ms"` on `checkoutservice` and run `--review-only`. If the AI approves it as-is, tighten the SYSTEM prompt in `safety.py` (e.g. "reject anything on the checkout path above 500 ms or longer than 60 s"). **That's prompt engineering, and it's your call.**

---

## Part 2: Build ⑤ Remediation (≈2 h): `chaosmind/agents/remediation.py`
**Concept:** a confirmed weakness → the AI proposes a **Kubernetes patch** → code checks it against an **allow-list** → apply it → **re-run the identical experiment** → compare scores. Fixing without re-testing is just advice; re-testing is proof.

### Interface
```python
def propose(vulnerability: dict, history_item: dict, deployment: dict, root_cause: dict | None) -> dict:
    """AI proposes a fix. Returns {"fix": "...", "patch": [json-patch ops], "extra_resources": [...],
                                   "expected_effect": "...", "rollback": [json-patch ops]}"""

def check(proposal: dict, deployment: dict) -> list[str]:
    """Code: return a list of problems; an empty list means allowed."""

def apply_and_verify(proposal, experiment, baseline) -> dict:
    """Apply → re-run the SAME experiment via guard.run() → score before vs after.
       Returns {"before": {...}, "after": {...}, "score_before": 41, "score_after": 78, "verdict": "improved"}"""
```

### Step by step
1. **Inputs:** the vulnerability (from the Cartographer), the experiment and its observed result (from `history.json`), the target's live Deployment JSON (`inject.kubectl('get','deployment',name,'-n',inject.NS,'-o','json')`), and the Log Detective's `root_cause` if available.

2. **The AI prompt** (large model). Give it the facts and ask for an RFC 6902 **JSON patch** like `remediation/redis-persistence-patch.json`. Tell it which fixes it may use:
   - `replicas` ≥ 2 (most services are stateless, so this is safe for them; **not** for `redis-cart`)
   - resources (requests/limits), readiness/liveness probes
   - a `PodDisruptionBudget` (as an `extra_resources` item)
   - for `redis-cart` only: the persistence fix (PVC + `--appendonly yes` + `Recreate`)

3. **The allow-list (code). This is the safety part, so make it strict:**
   - The target must be a Deployment in `online-boutique`.
   - Every patch `path` must start with one of: `/spec/replicas`, `/spec/strategy`, `/spec/template/spec/containers/0/resources`, `/spec/template/spec/containers/0/readinessProbe`, `/spec/template/spec/containers/0/livenessProbe`, `/spec/template/spec/containers/0/args` (redis-cart only), `/spec/template/spec/volumes` (redis-cart only, PVC named `redis-cart-data` only).
   - `replicas` must be between 1 and 3, and never > 1 for `redis-cart`. (Explain why in the demo: each Redis copy would have different carts.)
   - `extra_resources`: only `PodDisruptionBudget` or `PersistentVolumeClaim`, in our namespace, labelled `app.kubernetes.io/part-of: chaosmind-remediation`.
   - **Dry-run first:** `kubectl patch … --dry-run=server`. If the API server rejects it, so do you.

4. **Apply:** `kubectl patch deployment <t> --type=json -p '<ops>'`, then `kubectl rollout status`. Save the patch and the rollback ops in the run folder **before** applying.

5. **Verify:** run the *same* experiment JSON through `guard.run()` (new id suffix `-after`). Compute before/after with Harshil's `score.score(...)` and, for Redis, his integrity checks.

6. **Verdict (code):** `improved` if the score went up and nothing new broke, `no_change`, or `worse`. If worse, apply the rollback automatically.

### Test offline
- Patch-check unit tests:
  - the Redis fix passes
  - `replicas: 3` on `redis-cart` is rejected
  - a patch to `/spec/template/spec/containers/0/image` is rejected
  - a patch in another namespace is rejected
- Use `patch.object(llm, 'ask', return_value=...)` to fake the AI's proposal.

### First live target: the Redis cart (the demo moment)
1. **Before:** the already-recorded evidence: cart 1 → 0 with zero errors (`runs/c-redis-*`).
2. Remediation proposes the fix. Check that it matches `remediation/redis-persistence-patch.json` in spirit.
3. Apply → re-run: Harshil's `cart_persistence` check passes, and the score goes up.
4. Second target: `cartservice` replicas 1 → 2, then re-run the cart-down experiment. Error rate and recovery time should drop.

---

## Part 3: The demo narration (your part, ≈45 s)
> "Our AI never touches the cluster directly. It proposes; code validates; the guard can always pull the plug. Here the Safety Checker ramped catalog latency 125 → 250 → 500 ms and found the breaking point at 500. Our auditor flagged Redis before we broke anything; the experiment proved it: carts silently wiped, zero errors. Remediation patched it with persistent storage, re-ran the identical experiment, and the cart survived. Score 41 → 78."
(Use the real numbers once you have them.)

## Hand-offs
- **To Smrithi:** `remediation.propose / check / apply_and_verify`. She calls them when a verdict is `confirmed`.
- **From Harshil:** `score.score(...)`, `integrity.prepare()/verify()`. **From Aashrith:** `root_cause.json`.

## What to learn while doing this
- **JSON Patch (RFC 6902)** and `kubectl patch --type=json`
- **Server-side dry run:** how to test a change against the real API without applying it
- **Rollback design:** always save the undo before doing anything
- **Stateful vs stateless services:** why replicas fix the cart service but would *break* Redis
