# Harshil: integrity checks, resilience score, demo video

Read [GUIDE_00_EVERYONE.md](GUIDE_00_EVERYONE.md) first.

**Your role:** you own the two things that make our results *mean* something, the **integrity checks** and the **score**, plus the **demo video** (deliverable #2). Your shop knowledge from `customer_simulator.py` is exactly what's needed.

---

## 1. Understand the integrity checks (≈20 min): `chaosmind/agents/integrity.py`
**Concept:** a health check asks "did the request succeed?" An **integrity check** asks "is the result *correct*?" Our Redis test wiped carts with **0 HTTP errors**. Error-rate monitoring, which is what most teams have, misses that completely.

What the code does:
- `prepare()`, **before** a fault: new session, adds product `OLJCESPC7Z`, reads the cart count (using `cart_count()` from `c_tests.py`, which reads the "Cart (N)" badge).
- `verify(state)`, **after** recovery:
  - **`cart_persistence`:** same session, is the item still there?
  - **`checkout_completes`:** a fresh buyer adds an item and checks out. It needs HTTP 200 **and** an order confirmation in the page (regex `ORDER_PLACED`).
- Violations feed the verdict (`integrity_violations > 0` → confirmed) and cost 40 points in the score.

Run the offline tests:
```bash
python3 -m unittest chaosmind.agents.test_day2
```

## 2. Validate them live (with Aashrith, ≈30 min)
**2a. The checkout confirmation text (most important).** `customer_simulator.py` counts *any* HTTP 200 as a successful checkout, which is exactly the trap we want to avoid. Check what a real success page says:
```bash
J=$(mktemp); curl -s -c $J -b $J localhost:8080/ >/dev/null; curl -s -c $J -b $J -d "product_id=OLJCESPC7Z&quantity=1" localhost:8080/cart >/dev/null
```
```bash
curl -s -c $J -b $J -d "email=someone@example.com&street_address=1600+Amphitheatre+Parkway&zip_code=94043&city=Mountain+View&state=CA&country=United+States&credit_card_number=4432-8015-6152-0454&credit_card_expiration_month=1&credit_card_expiration_year=2030&credit_card_cvv=672" localhost:8080/cart/checkout | grep -i -o "order[^<]\{0,40\}" | head
```
If the wording isn't matched by `ORDER_PLACED` in `integrity.py`, fix the regex, re-run the tests and push.

**2b. Before/after on Redis:**
1. `python3 -m chaosmind.agents.integrity` → expect `[]`.
2. Then `prepare()` → restart Redis (`kubectl --kubeconfig .runtime/kubeconfig --context kind-online-boutique -n online-boutique delete pod -l app=redis-cart`) → `verify()` → expect a `cart_persistence` violation.
3. After `bash scripts/redis-fix.sh apply`, repeat → expect `[]`.

## 3. Own the score (≈20 min): `chaosmind/agents/score.py`
```
score = 100 − E − L − R − B − I
E = min(40, 400 × extra error rate)   L = min(25, 25 × extra p95 / 2000 ms)
R = min(15, recovery_s / 4)           I = 40 if any integrity violation
B = 10 × share of services in the target's blast radius, only when customers were hurt
```
On our real results it gives (regenerate with `python3 -m chaosmind.agents.scoreboard`):

| Scenario | Score |
|---|---|
| Nothing broken | 100 |
| Ad service down | 90 |
| Catalog delay | 68 |
| Redis silent wipe | 30 (67 after the fix) |
| Catalog pod kill, 1 replica | 29 (99 with 2 replicas) |
| Frontend down (AI-chosen) | 16 |
| Cart down | 18 |

Decide with the team whether those rankings feel right. If you change weights, update the docstring and the sanity test in `test_day2.py`. **Be ready to explain the formula in one sentence on camera.**

## 4. The demo video (deliverable #2, ≤ 3 min), from H4
Suggested storyboard. Use footage from the recorded live run; don't run live while recording.

| Time | Shot | Line |
|---|---|---|
| 0:00–0:20 | README + map | "11 microservices. Our AI audits the architecture before breaking anything." |
| 0:20–0:45 | Cartographer output | "It flagged Redis as critical: one replica, data on a temporary disk." |
| 0:45–1:20 | Strategist + Safety Checker ramp, Grafana spiking | "It predicts, writes pass/fail criteria first, then ramps intensity safely. The kill switch reverts in 0.3 s." |
| 1:20–1:50 | Integrity violation | "Zero HTTP errors, yet carts were wiped. Our integrity check caught it. Error monitoring alone wouldn't." |
| 1:50–2:30 | Remediation | "The AI picked a reviewed fix, re-ran the identical experiment: cart survives, score up." |
| 2:30–3:00 | FINDINGS.md + safety table | "Every number fact-checked. The AI never touches the cluster directly." |

Use the real numbers from the live run. Keep it under 3:00 (judges check).

## 5. Team form (deliverable #5)
Fill it from the README's last section: names, tools, AI models, third-party libraries, data.
