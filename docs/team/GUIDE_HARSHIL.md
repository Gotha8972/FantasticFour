# Harshil: integrity checks + resilience score + Documentor

Read [GUIDE_00_EVERYONE.md](GUIDE_00_EVERYONE.md) first.

**Your role:** you own the parts that turn raw measurements into **meaning**:
1. **Integrity checks:** catch **silent failures**, where the site says "OK" but the data is wrong. This is our **biggest differentiator**: our Redis test emptied carts with **0 errors**, and every other team's error-rate monitoring would miss it.
2. **Resilience score:** one number, 0–100, per experiment and overall.
3. **⑦ Documentor:** writes `FINDINGS.md`, the findings report, which is **deliverable #4**, and fact-checks itself.

You already know the shop's HTTP flows from `customer_simulator.py`. That's exactly what the integrity checks need.

---

## Part 1: Integrity checks (≈1.5 h): `chaosmind/agents/integrity.py`
**Concept:** a normal health check asks "did the request succeed?". An **integrity check** asks "is the *result* correct?". Each check is a tiny scripted customer: it sets something up **before** the fault and verifies it **after**.

**Plain code, no AI.** Use only the standard library (`urllib.request` + `http.cookiejar`), like `tests/redis_finding.sh` does with curl. The shop is at `http://localhost:8080` on Aashrith's laptop.

### The checks to write
| Check | Before the fault | After the fault | Violation when |
|---|---|---|---|
| `cart_persistence` | New session; add product `OLJCESPC7Z` to the cart; confirm it's in `GET /cart` | Same session: `GET /cart` | Product no longer in the cart |
| `checkout_completes` | — | Fresh session; add an item; `POST /cart/checkout` with the form fields from `customer_simulator.py` | Not HTTP 200 **or** the page has no order confirmation |
| `price_consistency` | Read the price shown on `/product/OLJCESPC7Z` | Read it again | Price changed (a currency/catalog bug) |

**Important detail for `checkout_completes`:** `customer_simulator.py` treats **any HTTP 200 as success**. That's the exact trap we're trying to catch. First look at what a real success page contains:
```bash
J=$(mktemp); curl -s -c $J -b $J localhost:8080/ >/dev/null; curl -s -c $J -b $J -d "product_id=OLJCESPC7Z&quantity=1" localhost:8080/cart >/dev/null
```
Then post the checkout form (copy the fields from `customer_simulator.py`) and look for the confirmation text or order ID in the HTML. Check for *that*, not just the status code.

### Interface (Smrithi will call these from the loop)
```python
def prepare() -> dict:
    """Run BEFORE the fault. Returns state for verify(): session cookies, cart contents, price."""

def verify(state: dict) -> list[dict]:
    """Run AFTER recovery. Returns violations:
    [{"check": "cart_persistence", "expected": "1 x OLJCESPC7Z", "actual": "cart empty",
      "evidence": "<short snippet of the HTML>"}]"""
```
- Use a **3-second timeout** on every request; a hung request counts as a violation, not a crash.
- Return an empty list when everything is fine.

### Test
- **Offline:** a unit test that feeds saved HTML (`runs/c-redis-20261010T070925.577773Z/cart-before.html` and `cart-after.html`) into your "is the product in the cart" parser. Before → found; after → not found.
- **Live (with Aashrith):** run `prepare()`, restart Redis (`kubectl … delete pod -l app=redis-cart`), wait 10 s, run `verify()`. You should get a `cart_persistence` violation. After `bash scripts/redis-fix.sh apply`, the same test should return **no** violation. That's the before/after proof.

---

## Part 2: Resilience score (≈45 min): `chaosmind/agents/score.py`
**Concept:** judges want one number. It must be **plain code** (never AI) and **documented**, so anyone can recompute it.

Starting formula. You own it, so tune it and write it in the README:
```
score = 100 − E − L − R − I     (clamped to 0..100)
E  error impact   = min(40, 400 × max(0, peak_error_rate − baseline_error_rate))   # +10% errors → −40
L  latency impact = min(25, 25 × max(0, peak_p95 − baseline_p95) / 2000)           # +2 s p95 → −25
R  recovery       = min(15, recovery_s / 4)                                         # 60 s → −15
I  integrity      = 20 if any integrity violation else 0                            # silent failure → −20
```
```python
def score(observed: dict, baseline: dict, recovery_s: float | None, violations: list) -> dict:
    """Return {"score": 62, "breakdown": {"E": 14, "L": 9, "R": 15, "I": 0}}"""
```
- `observed` = worst values during the fault (what `safety.observed(events)` returns: `error_rate`, `p95_ms`, `unhealthy_count`, `recovery_s`).
- `baseline` = the dict in `baseline.json` (use `metrics.error_rate.mean` and `metrics.p95_ms.mean`).
- **Overall system score** = the average of experiment scores, or the minimum, which is "as strong as the weakest link". Pick one and justify it.

**Sanity tests:** nothing broken → ~100; cart down (35% errors, 55 s recovery) → low; ad service down (0% errors) → high; Redis wipe (0 errors but an integrity violation) → **must not be 100**. That's the point of `I`.

---

## Part 3: ⑦ Documentor (≈1.5 h): `chaosmind/agents/documentor.py`
**Concept:** collect everything the other agents produced and write the findings report: weaknesses **ranked by severity**, with numbers, root cause, fix, before/after and score. Then **fact-check it**: every number in the report must exist in the source files.

**Inputs** (all JSON in `runs/`):
- `runs/agents-<time>/vulnerabilities.json`: the Cartographer's suspects, with `status` confirmed/refuted
- `runs/agents-<time>/history.json`: each experiment, its prediction, criteria, observed metrics, verdict
- per-run `impact.json` (Aashrith's Observer) and `root_cause.json` (Log Detective)
- Remediation before/after results (Srinavith)
- your scores

**Output:** `FINDINGS.md` at the repo root.

**Step by step:**
1. **Code** builds one compact JSON "fact sheet" from all the inputs (only the fields that matter).
2. **AI (large model)** writes the report from the fact sheet. Prompt rules:
   - "Use only numbers from the fact sheet."
   - "Rank by severity: user impact first, then data loss, then recovery time."
   - "For each finding: what we did, what happened, why (root cause), the fix, before/after, and the run ID."
3. **Fact-check (code):**
   - extract every number from the report (regex `\d+(\.\d+)?`)
   - check each one appears in the fact sheet, allowing rounding (e.g. 0.3489 ≈ 34.9%)
   - list unmatched numbers in a **"Fact-check"** section at the bottom of the report
   - aim for zero unmatched
4. Include a **prediction scorecard:** how many of the Strategist's hypotheses were confirmed vs refuted. That's the "our AI predicted N of M" line.

**Test:** run it on the existing evidence (`KILLSWITCH_RESULTS.md` data, `runs/test-*`) even before the full loop exists. Plant a fake number in a test and check the fact-checker flags it.

---

## Hand-offs
- **To Smrithi:** `integrity.prepare()` / `integrity.verify(state)`, `score.score(...)`, `documentor.write(agents_run_dir) -> path`.
- **From Aashrith:** `impact.json`, `root_cause.json`. **From Srinavith:** the before/after JSON.

## What to learn while doing this
- **Why HTTP 200 ≠ correct:** silent failures, the most dangerous kind in real systems.
- **Designing a metric:** a score is only credible if it's simple, documented and recomputable.
- **Grounded AI writing:** letting an AI write prose while code guarantees the numbers are true.
