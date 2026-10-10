# Findings report: Online Boutique resilience

> **This is the team's consolidated report**, built from the AI's live runs plus our manual experiments and repeated trials. **The AI's own reports**, written by the Analyst agent with code fact-checking every number, are [run 1](runs/agents-20261010T185909Z/FINDINGS.md), [run 2](runs/agents-20261010T192511Z/FINDINGS.md) and [run 3](runs/agents-20261010T200021Z/FINDINGS.md). The AI's prose isn't fully reliable, and its reports flag it: claims that the measurements or the collected config contradict are marked automatically (an invented PodDisruptionBudget, emptyDir on a persistent volume, data loss with the cart kept).

**System under test:** Google Online Boutique v0.10.4 (11 services + Redis) on kind, namespace `online-boutique`.
**Load:** Locust shoppers (20 = normal, 100 = stress). **Faults:** Chaos Mesh, every one run under our kill switch.
**Normal (20 shoppers):** 4.4–4.6 req/s, 0.05–0.07% errors, p95 35–78 ms, checkout success ~98.7% ([baselines](docs/evidence/BASELINE_STUDY.md)).

**Resilience score** (0–100, [formula](chaosmind/agents/score.py)): 100 minus penalties for extra errors (≤ 40, square-root scale: 5% costs 13, 50%+ costs 40), extra p95 latency (≤ 25, square-root scale: +1 s costs 8, +10 s costs 25), recovery time (≤ 15), **blast radius** (≤ 10: the share of services that break with the target, counted only when customers were hurt) and any data-integrity violation (40). Every score below is **recomputed from the raw evidence** by `python3 -m chaosmind.agents.scoreboard`: see the [scoreboard](docs/evidence/SCOREBOARD.md).

## Ranked weaknesses

Ranked by **severity** first (silent data loss above outages, outages above slowdowns, contained failures last), then by **resilience score** (lower = worse). A full score-only ranking of every experiment is in the [scoreboard](docs/evidence/SCOREBOARD.md).

| Rank | Weakness | Severity | Evidence | Score | Fix | Status |
|---|---|---|---|---|---|---|
| 1 | **Silent cart data loss** on Redis restart | 🔴 Critical | Cart **1 → 0 items**; afterwards every page answers HTTP 200 with the cart empty, so the loss is never reported. **Found, confirmed and fixed by the AI loop live** (fix approved by a human) | Cart test **40 → 81**; AI loop **13 → 50** | PVC for `/data` + Redis append-only log + `Recreate` strategy | ✅ **Data loss fixed:** cart **1 → 1** both times. **Restart disruption not fixed:** with one replica a restart still causes errors and 2–6 s cart requests |
| 2 | **The frontend is a single point of failure** | 🔴 Critical | **Chosen and confirmed by the AI:** frontend down → **100% errors**, p95 20 s, pod back after 19.7 s, customers after 40.5 s | **18 → 96** (AI loop) | 2 frontend replicas (reviewed [catalog](remediation/catalog.json) fix) | ✅ **Fixed in the AI loop** after human approval: 0% errors on the same experiment; hypothesis **refuted after the fix** |
| 3 | **The currency service is a single point of failure** | 🔴 Critical | **Chosen and confirmed by the AI:** currency down → **100% errors** (every page shows prices), 113 of 206 requests and 3 of 6 checkouts failed; customers back after 43 s | **47** | 2 replicas (not in the reviewed catalog yet, so the AI correctly applied nothing) | Fix recommended |
| 4 | **Cart service is a single point of failure** | 🟠 High | Cart down → errors peak 100%, p95 2,700 ms, customers recovered after ~62 s; the AI's pod kill confirmed it (100% errors) | **31 → 78** (AI loop) | 2 replicas + PodDisruptionBudget (in the [fix catalog](remediation/catalog.json)) | ✅ **Fixed in the AI loop:** errors 100% → 0%; p95 still 2.7 s, so latency stays a weakness |
| 5 | **"Healthy" ≠ recovered** after a catalog pod kill | 🟠 High | At 100 shoppers: replacement pod up in **~3 s**, but **66 HTTP 500s**, checkout 16/179 failed, customers recovered after **~34 s**. Repeated at 20 shoppers: customers hurt in **5 of 5** kills (95% CI 57–100%); the AI's own kill confirmed it (17% errors) | **29 → 100** with 2 replicas (medians of 5); AI loop **70 → 99** | 2 catalog replicas; frontend retries with backoff | ✅ **Fix measured:** 2 replicas → hurt in **0 of 5** (95% CI 0–43%); in the AI loop the hypothesis was **refuted after the fix** |
| 6 | **A payment outage hides inside the overall error rate** | 🟠 High | **Chosen and confirmed by the AI:** payment pod killed → the overall error rate peaked at only **4.5%** (2 of 145 requests failed in the window), below our own kill switch's 5% limit, while **2 of 5 checkouts failed**. Score 87 overstates it: the score, like the kill switch, sees aggregate errors | **87** | 2 payment replicas; a checkout-specific error limit in the kill switch and the score | Recommended (also a limit of our tool) |
| 7 | **Catalog latency spreads to the whole site** | 🟡 Medium | +500 ms on the catalog → site p95 **3,500 ms** at 20 shoppers, **4,300 / 4,400 ms** at 100 (two identical runs) | **77** | Client-side timeouts + caching catalog reads in the frontend | Recommended |
| 8 | **Background checkout failures** | 🟡 Medium | 3 HTTP 500s in 237 checkouts with **no fault injected** (~1.3%); 4 of 56 under host memory pressure with `paymentservice` restarts; **0 of 55** with memory headroom | n/a (no fault injected) | Resource headroom for `paymentservice` (memory limits/requests); card data ruled out | Likely cause found |
| 9 | Ads service outage | 🟢 Low | Ad service down → **0% errors**; the frontend degrades gracefully | **89** | None needed | ✅ Resilient |

## Details

### 1. Silent cart data loss: fixed ✅
- **What we did:** added an item to a cart, then restarted the `redis-cart` pod. Later the **AI loop chose the same experiment itself** (Redis pod kill with an integrity criterion), confirmed it live, proposed the fix, and applied it after a human approved.
- **What happened:** the cart was empty afterwards, and every page kept answering HTTP 200 with the empty cart: nothing ever reports the loss. In the cart test the load generator saw no failed requests at all; in the AI's run the restart itself caused a short error spike (≤ 12.5%), but no error says "your cart is gone". Our **integrity check** (same session: is the item still there?) caught it both times.
- **Root cause:** Redis is a single replica storing data on an `emptyDir` volume, which is deleted with the pod. Redis saves on shutdown, but into that temporary folder.
- **Fix:** `bash scripts/redis-fix.sh apply`: a PersistentVolumeClaim for `/data`, `--appendonly yes` (covers crashes, not only clean shutdowns), and the `Recreate` strategy, so two Redis pods never share the disk.
- **Proof:** same experiment after the fix: cart **1 → 1**, 0 failed requests in the cart test; in the AI's run the integrity violation disappeared. Scores: cart test **40 → 81**, AI loop **13 → 50**. Evidence: [before/after](docs/evidence/REDIS_FIX_RESULTS.md), `runs/c-redis-20261010T070925.577773Z` (before), `runs/c-redis-20261010T102251.009037Z` (after), AI run `runs/agents-20261010T185909Z`.
- **What the fix doesn't solve, said plainly:** it stopped the data loss, but customer disruption during a restart did **not** improve. In the AI loop's re-run, errors were 17.9% (vs 12.5% before) and p95 5.5 s; part of that was the fix's own rollout, because the re-run started too early. The re-run now waits for customers to settle first. In a later AI run with the fix settled, the Redis kill kept the cart and caused 0% errors, but p95 still reached 3.2 s. Redis is still one replica. Next step: cartservice retries, or a replicated Redis.

### 2. The frontend is a single point of failure (found by the AI)
- **What happened:** the AI ranked the frontend first (blast radius: all 11 services × critical) and ran `pod_failure` on it, in both live runs. Customers saw **100% errors** and p95 of 20 s; the kill switch removed the fault, and customers were back after 34–41 s. Score **18**.
- **Root cause:** one replica on the only entrypoint; every customer request passes through it.
- **Fix, applied by the AI loop:** Remediation chose `frontend-replicas` from the reviewed catalog, a human approved it, and the identical experiment was re-run after customers settled: **0% errors, p95 97 ms, score 18 → 96**. The same pre-registered criteria were then **refuted**: the code can say no. Evidence: `runs/agents-20261010T192511Z`.

### 3. The currency service is a single point of failure (found by the AI)
- **What happened:** in the third live AI run, `pod_failure` on `currencyservice` sent errors to **100%**: the frontend calls it on every page to show prices. Over the observed window 113 of 206 requests and 3 of 6 checkouts failed; the kill switch reverted the fault early and customers were back after 43 s. Score **47**: errors maxed out, but failures were fast, so latency stayed low.
- **Fix:** 2 replicas. There's no reviewed catalog fix for it yet, so Remediation correctly proposed nothing. Evidence: `runs/agents-20261010T200021Z`.

### 4. Cart service single point of failure
- **What we did:** `pod_failure` on `cartservice` at 20 shoppers.
- **What happened:** the kill switch tripped on error rate (35%) at 8.1 s and removed the fault 0.38 s later. During the restart that followed, errors peaked at 100% and p95 at 2,700 ms. The service had capacity back after ~42 s; customers recovered after ~62 s.
- **Root cause:** one replica; every cart and checkout request depends on it.
- **The AI's run:** pod kill on `cartservice` → 100% errors, customers back after 57 s, score 31. Remediation applied 2 replicas after approval and re-ran it: **errors 100% → 0%**, customers back after 14 s, score **31 → 78**. p95 still reached 2.7 s, so the latency criterion stays confirmed: more replicas fixed availability, not latency.
- **Fix:** 2 replicas (+ PDB). Evidence: `runs/test-down-20261010T062320.861245Z`, `runs/agents-20261010T192511Z`.

### 5. "Healthy" ≠ recovered
- **What we did:** killed one `productcatalogservice` pod at 100 shoppers.
- **What happened:** Kubernetes had a replacement Ready in ~3 s, but customers saw **66 HTTP 500s**, a checkout failure rate of 8.9% and peak p95 of 10 s, for ~34 s in total.
- **Why it matters:** pod health alone would have reported this as a 3-second blip. Customer metrics show it was a 34-second outage.
- **Repeated and measured:** 5 kills with 1 replica and 5 with 2 (20 shoppers, same customer limits). With **1 replica, customers were hurt every time (5/5, 95% CI 57–100%)**: errors up to 96%, p95 up to 20 s, customers recovered after 32–38 s while the pod was back in ~3 s. With **2 replicas, never (0/5, 95% CI 0–43%)**: errors stayed ≤ 2.4%. The intervals don't overlap. The AI's own catalog kill (1 replica) also confirmed customer impact (17% errors, score 70); after the approved fix, the same experiment had 0% errors (score 99) and the hypothesis was **refuted**. Evidence: `runs/trials-catalog-podkill-20261010T182606Z` (1 replica) and `runs/trials-catalog-podkill-20261010T183121Z` (2 replicas).
- **Fix:** 2 catalog replicas, so a single kill is absorbed (**measured above**); frontend retries with backoff. Evidence: [monitoring results](monitoring/README.md#recorded-pod-kill-results--october-10-2026), `runs/grafana-pod-kill-1a0c612c9e`.

### 6. A payment outage hides inside the overall error rate (found by the AI)
- **What happened:** the AI killed the single `paymentservice` pod. The overall error rate peaked at 4.5% and only 2 of 145 requests failed, below the kill switch's 5% aggregate limit, but **2 of the 5 checkouts in that window failed**. Payment is only on the checkout path, so its failures are diluted by all the browsing traffic.
- **Why it matters, including for our tool:** aggregate error rate under-weights the revenue path. Our kill switch and our score both use it, so this outage scored **87** and never tripped the guard. Next step: a checkout-specific error limit in both. One trial with 5 checkouts, so the rate itself is uncertain. Evidence: `runs/agents-20261010T200021Z`.

### 7. Catalog latency spreads everywhere
- **What we did:** +500 ms network delay on `productcatalogservice`.
- **What happened:** site-wide p95 went from ~35–78 ms to 3,500 ms (20 shoppers) and 4,300 / 4,400 ms (100 shoppers). The kill switch tripped on p95 at 7.8 s and 9.6 s and removed the fault within 0.33 s; recovery took 14–15 s. **Reproducible:** two runs, near-identical numbers.
- **Root cause:** the catalog has the most callers (frontend, checkout, recommendations), as our automatically generated dependency map predicted.
- **Fix:** client-side timeouts and caching catalog reads. Evidence: `runs/test-delay-20261010T062255.501508Z`, `runs/grafana-stress-*`.

### 8. Background checkout failures (likely cause found)
3 of 237 checkouts failed with HTTP 500 across two fault-free baselines, always on `POST /cart/checkout`. We checked the load generator's source: card expiry dates are always in the future and card numbers are always valid Visa numbers, so those aren't the cause. **Likely cause:** in a baseline taken under host memory pressure, `paymentservice` failed its liveness probe and restarted while 4 of 56 checkouts failed; with memory headroom, 0 of 55 failed (and 0 of 63 in the next baseline).

### 9. Ads fail gracefully
With `adservice` down, customer error rate stayed at **0%**. The kill switch still tripped on service health (9.2 s) and reverted in 0.38 s. As predicted: optional features don't break the shop.

## Hypotheses the AI got wrong (refuted by code)
Code decides every verdict against criteria written before the run, with thresholds raised above baseline noise, so the AI can be wrong:
- **Checkout pod kill** (third run): predicted customer impact; observed 0% errors and p95 150 ms → **refuted** (score 97). The pod was back in 3.8 s and checkout traffic was sparse in that window, so this is one trial, not proof that checkout is resilient.
- **Frontend and catalog, after their fixes:** the same pre-registered criteria were re-applied to the after-fix re-runs → **refuted** both times. The fix removed the weakness.
- **Redis data loss with the fix in place** (second run): the integrity criterion failed (cart kept); only the latency criterion held.
- The Analyst's prose is checked too: in the AI reports, code flags claims the measurements or the collected config contradict (e.g. an invented PodDisruptionBudget, "emptyDir" on a persistent volume, data loss with the cart kept).

## Safety record
Every experiment ran under the kill switch. All three triggers (error rate, latency, service health) fired live and removed the fault in **0.30–0.39 s**. The **crash fail-safe** was proven (guard killed with `kill -9`; the fault still ended on Chaos Mesh's timer), **manual abort** cleared 2 faults in 0.39 s, and **pre-flight** refused to start while another fault was active. No experiment affected anything outside the `online-boutique` namespace.

## How these were found
The **Cartographer** audits the live configuration and ranks risks (it flagged Redis, the frontend, the catalog, cart, currency, payment and the checkout path). The **Strategist** turns each into an experiment with pass/fail criteria written in advance. The **Safety Checker** approves and ramps it through the kill switch. **Integrity checks** catch silent failures, **code** decides confirmed/refuted and the score, and **Remediation** applies a reviewed fix and re-runs the same experiment. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
