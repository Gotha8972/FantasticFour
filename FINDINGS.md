# Findings report: Online Boutique resilience

**System under test:** Google Online Boutique v0.10.4 (11 services + Redis) on kind, namespace `online-boutique`.
**Load:** Locust shoppers (20 = normal, 100 = stress). **Faults:** Chaos Mesh, every one run under our kill switch.
**Normal (20 shoppers):** 4.4–4.6 req/s, 0.05–0.07% errors, p95 35–78 ms, checkout success ~98.7% ([baselines](docs/evidence/BASELINE_STUDY.md)).

**Resilience score** (0–100, [formula](chaosmind/agents/score.py)): 100 minus penalties for extra errors (≤ 40), extra p95 latency (≤ 25), recovery time (≤ 15) and any data-integrity violation (40).

## Ranked weaknesses

| Rank | Weakness | Severity | Evidence | Score | Fix | Status |
|---|---|---|---|---|---|---|
| 1 | **Silent cart data loss** on Redis restart | 🔴 Critical | Cart **1 → 0 items** with **0 HTTP errors** | **58** (integrity violation) | PVC for `/data` + Redis append-only log + `Recreate` strategy | ✅ **Fixed and re-tested:** cart **1 → 1** |
| 2 | **Cart service is a single point of failure** | 🟠 High | Cart down → errors peak 100%, p95 2,700 ms, customers recovered after ~62 s | **21** | 2 replicas + PodDisruptionBudget (in the [fix catalog](remediation/catalog.json)) | Fix ready |
| 3 | **"Healthy" ≠ recovered** after a catalog pod kill | 🟠 High | At 100 shoppers: replacement pod up in **~3 s**, but **66 HTTP 500s**, checkout 16/179 failed, customers recovered after **~34 s** | — | 2 catalog replicas; frontend retries with backoff | Fix ready |
| 4 | **Catalog latency spreads to the whole site** | 🟡 Medium | +500 ms on the catalog → site p95 **3,500 ms** at 20 shoppers, **4,300 / 4,400 ms** at 100 (two identical runs) | **71** | Client-side timeouts + caching catalog reads in the frontend | Recommended |
| 5 | **Background checkout failures** | 🟡 Medium | 3 HTTP 500s in 237 checkouts with **no fault injected** (~1.3%) | — | Root cause under investigation (load-generator card data ruled out) | Investigating |
| 6 | Ads service outage | 🟢 Low | Ad service down → **0% errors**; the frontend degrades gracefully | **90** | None needed | ✅ Resilient |

## Details

### 1. Silent cart data loss: fixed ✅
- **What we did:** added an item to a cart, then restarted the `redis-cart` pod.
- **What happened:** the cart was empty afterwards, yet every request returned HTTP 200. The guard and error-rate monitoring saw nothing; our **integrity check** (same session: is the item still there?) caught it.
- **Root cause:** Redis is a single replica storing data on an `emptyDir` volume, which is deleted with the pod. Redis saves on shutdown, but into that temporary folder.
- **Fix:** `bash scripts/redis-fix.sh apply`: a PersistentVolumeClaim for `/data`, `--appendonly yes` (covers crashes, not only clean shutdowns), and the `Recreate` strategy, so two Redis pods never share the disk.
- **Proof:** same experiment after the fix: cart **1 → 1**, 0 failed requests, back in 3.3 s. Evidence: [before/after](docs/evidence/REDIS_FIX_RESULTS.md), `runs/c-redis-20261010T070925.577773Z` (before), `runs/c-redis-20261010T102251.009037Z` (after).

### 2. Cart service single point of failure
- **What we did:** `pod_failure` on `cartservice` at 20 shoppers.
- **What happened:** the kill switch tripped on error rate (35%) at 8.1 s and removed the fault 0.38 s later. During the restart that followed, errors peaked at 100% and p95 at 2,700 ms. The service had capacity back after ~42 s; customers recovered after ~62 s.
- **Root cause:** one replica; every cart and checkout request depends on it.
- **Fix:** 2 replicas (+ PDB). Our Remediation agent applies this from the reviewed catalog and re-runs the identical experiment. Evidence: `runs/test-down-20261010T062320.861245Z`.

### 3. "Healthy" ≠ recovered
- **What we did:** killed one `productcatalogservice` pod at 100 shoppers.
- **What happened:** Kubernetes had a replacement Ready in ~3 s, but customers saw **66 HTTP 500s**, a checkout failure rate of 8.9% and peak p95 of 10 s, for ~34 s in total.
- **Why it matters:** pod health alone would have reported this as a 3-second blip. Customer metrics show it was a 34-second outage.
- **Fix:** 2 catalog replicas, so a single kill is absorbed; frontend retries with backoff. Evidence: [monitoring results](monitoring/README.md#recorded-pod-kill-results--october-10-2026), `runs/grafana-pod-kill-1a0c612c9e`.

### 4. Catalog latency spreads everywhere
- **What we did:** +500 ms network delay on `productcatalogservice`.
- **What happened:** site-wide p95 went from ~35–78 ms to 3,500 ms (20 shoppers) and 4,300 / 4,400 ms (100 shoppers). The kill switch tripped on p95 at 7.8 s and 9.6 s and removed the fault within 0.33 s; recovery took 14–15 s. **Reproducible:** two runs, near-identical numbers.
- **Root cause:** the catalog has the most callers (frontend, checkout, recommendations), as our automatically generated dependency map predicted.
- **Fix:** client-side timeouts and caching catalog reads. Evidence: `runs/test-delay-20261010T062255.501508Z`, `runs/grafana-stress-*`.

### 5. Background checkout failures (investigating)
3 of 237 checkouts failed with HTTP 500 across two fault-free baselines, always on `POST /cart/checkout`. We checked the load generator's source: card expiry dates are always in the future and card numbers are always valid Visa numbers, so those aren't the cause. Payment and checkout logs are being captured right after a baseline to find it.

### 6. Ads fail gracefully
With `adservice` down, customer error rate stayed at **0%**. The kill switch still tripped on service health (9.2 s) and reverted in 0.38 s. As predicted: optional features don't break the shop.

## Safety record
Every experiment ran under the kill switch. All three triggers (error rate, latency, service health) fired live and removed the fault in **0.30–0.39 s**. The **crash fail-safe** was proven (guard killed with `kill -9`; the fault still ended on Chaos Mesh's timer), **manual abort** cleared 2 faults in 0.39 s, and **pre-flight** refused to start while another fault was active. No experiment affected anything outside the `online-boutique` namespace.

## How these were found
The **Cartographer** audits the live configuration and ranks risks (it flagged Redis, the catalog, cart and checkout path). The **Strategist** turns each into an experiment with pass/fail criteria written in advance. The **Safety Checker** approves and ramps it through the kill switch. **Integrity checks** catch silent failures, **code** decides confirmed/refuted and the score, and **Remediation** applies a reviewed fix and re-runs the same experiment. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
