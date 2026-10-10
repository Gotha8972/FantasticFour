# Role B: Mapping + Monitoring (Day 1)

**You own the "eyes" of the system:** what the app looks like (the map), and how it's doing right now (the numbers).
Everyone depends on you: C's kill switch reads your numbers, and D's Cartographer agent reads your map data.

**Day-1 done =** `tools/k8s.py` gives raw dependency data, `monitor.snapshot()` returns real numbers, `baseline.json` is saved, and the spike is visible on screen during an injection.

```
chaosmind/
  k8s.py         # B1: read the cluster → services + raw edges
  probe.py       # B2: fake customer that measures error rate / latency / checkout success
  monitor.py     # B2: snapshot() = probe stats + pod health   (contract #2)
  baseline.py    # B3: 5 min of snapshots → baseline.json
```

---

## B1: Map data, `k8s.py` (≈45 min)
Every Online Boutique service finds its dependencies through **environment variables ending in `_ADDR`**:
```
checkoutservice:  PRODUCT_CATALOG_SERVICE_ADDR=productcatalogservice:3550
                  CART_SERVICE_ADDR=cartservice:7070  ...
cartservice:      REDIS_ADDR=redis-cart:6379
```
Each such variable is an edge `checkoutservice → productcatalogservice`.

Try it by hand first:
```bash
kubectl get deploy -n boutique -o json | grep -A1 '_ADDR'
```
Write one function:
```python
def graph() -> dict:
    """kubectl get deploy -n boutique -o json → for each deployment: name, replicas, *_ADDR env vars → edges."""
    # returns contract #1: {"services": [{"name", "replicas"}], "edges": [{"from", "to"}]}
```
- Reuse `inject.kubectl()`; don't write a second kubectl wrapper.
- The `loadgenerator → frontend` edge comes from `FRONTEND_ADDR`, so it's caught too.
- **Check:** compare your edges with the hand-drawn graph in PLAN.md. Any mismatch is either your bug or a real discovery. Write it down; the slides allow "manual corrections".

## B2: Live numbers, `probe.py` + `monitor.py` (≈2h, most important)
**Why a probe:** Online Boutique doesn't report its own error rate to Prometheus. So we act as a **fake customer**: hit the shop every second and measure. That's also the most honest metric, because it's exactly what a real customer feels.

`probe.py` runs in the background and, each second, does one customer journey through the frontend (`kubectl -n boutique port-forward svc/frontend 8080:80`):
1. `GET /`, the home page
2. `GET /product/OLJCESPC7Z`, a product page (the catalog)
3. `POST /cart` with `product_id=OLJCESPC7Z&quantity=1`, which adds to the cart
4. Every 5th loop: `POST /cart/checkout` with the shop's own demo form values (they're pre-filled in the checkout form; copy them from the page source)

For each request, record **status OK or not** and **time taken**. Keep the last 30 seconds in memory.
- Use the stdlib only: `urllib.request` plus `http.cookiejar` (the cart lives in a session cookie).
- A timeout counts as an error. Set a 3s timeout, or a hung service will freeze the probe.

`monitor.py` must return **exactly contract #2**, because C's guard already calls this shape:
```python
def snapshot() -> dict:
    return {"ts": ..., 
            "error_rate": ...,          # failed / total requests, last 30s
            "p95_ms": ...,              # 95th percentile latency, last 30s (statistics.quantiles)
            "checkout_success": ...,    # successful checkouts / attempted, last 30s
            "unhealthy_services": [...],# deployments with readyReplicas < replicas (copy from guard.py's stub)
            "restarts": {...}}          # pod restartCount per service (kubectl get pods -o json)
```
**Once it works:** in `guard.py`, replace the stub `snapshot()` with `from chaosmind.monitor import snapshot`, and tell C.

**Check:** run `python3 -m chaosmind.monitor` and print a snapshot every 2s. Then have C run `experiments/test-delay.json`. **Does `p95_ms` jump by ~500ms?** If yes, the delay test can now trigger the kill switch.

## B3: Baseline, `baseline.py` (≈30 min)
"Normal" must be measured, not guessed. Run `snapshot()` every 2s for **5 minutes** with nothing broken, then save:
```json
{"error_rate": {"mean": 0.002, "max": 0.01},
 "p95_ms": {"mean": 140, "max": 210},
 "checkout_success": {"mean": 1.0, "min": 0.98}}
```
Commit `baseline.json`. It's used by:
- **C:** to set sensible thresholds (e.g. p95 limit = 3× baseline, not a random 2000ms)
- **D:** the Strategist reads it to judge impact
- **The demo:** "normal is 0.2% errors at 140ms"

## B4: Make the spike visible (≈30 min)
- **Grafana** (`kubectl -n monitoring port-forward svc/monitoring-grafana 3000:80`, admin/admin) already has built-in dashboards. Open **"Kubernetes / Compute Resources / Namespace (Pods)"** and pick `boutique`. Pod restarts and CPU spikes show up there for free.
- For **error rate / latency / checkout success** (your probe's numbers), a terminal live view is enough for Day 1: `python3 -m chaosmind.monitor` printing one coloured line per snapshot. The proper dashboard is D's Streamlit work on Day 2.

## Hand-offs
| When | To | What |
|---|---|---|
| H2 | C | `snapshot()` working (even if checkout isn't done yet) |
| H4 | C | Swap the stub in `guard.py` for your import |
| H4 | D | `k8s.graph()` for the Cartographer agent |
| H5 | C, D | `baseline.json` committed |

## If short on time
Skip checkout in the probe (home + product + cart is enough), then skip the `restarts` field.
**Never skip:** `error_rate`, `p95_ms`, `unhealthy_services`. The kill switch depends on them.
