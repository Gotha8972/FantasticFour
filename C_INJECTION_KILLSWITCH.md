# Role C: Injection + Kill Switch (Day 1)

**You own:** breaking things on purpose (`inject.py`) and stopping them safely (`guard.py`).
**Day-1 done =** one failure injected through Chaos Mesh, the guard detects a breach and reverts it automatically, a timestamped log, and the Redis cart finding.

```
chaosmind/
  inject.py              # apply / revert / abort_all
  guard.py               # preflight → inject → watch → revert → confirm healthy
  thresholds.yaml        # the limits (contract #4)
  templates/
    pod_failure.yaml
    network_delay.yaml
runs/                    # one log file per experiment (git-ignored)
```

---

## Step 0: Get a cluster (≈20 min, runs in background)
- Linux: `./setup/sandbox.sh`
- Mac: install OrbStack or Docker Desktop, run `brew install kind kubectl helm`, then run the kind/helm parts of `sandbox.sh` by hand (skip the Docker and sysctl steps).
- Check:
  ```bash
  kubectl get pods -n boutique      # all Running
  kubectl get pods -n chaos-mesh    # controller + daemon Running
  kubectl api-resources | grep chaos-mesh   # CRDs installed
  ```

## Step 1: Break things by hand first (≈30 min)
Learn the tool before writing code. Labels in Online Boutique are `app: <service-name>`.

**1a. Pod failure** (a service down for N seconds, then it comes back). Use `pod-failure`, **not** `pod-kill`: `pod-kill` is instant and Kubernetes restarts the pod straight away, so there is nothing to roll back. `pod-failure` keeps the pod broken for `duration`, so the kill switch has something to stop.
```yaml
# templates/pod_failure.yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: PodChaos
metadata: {name: "{id}", namespace: boutique}
spec:
  action: pod-failure
  mode: all                  # all pods of the target (each service has 1 replica)
  duration: "{duration}"     # FAIL-SAFE: Chaos Mesh ends it even if our guard dies
  selector:
    namespaces: [boutique]
    labelSelectors: {app: "{target}"}
```

**1b. Network delay** (a service gets slow):
```yaml
# templates/network_delay.yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: NetworkChaos
metadata: {name: "{id}", namespace: boutique}
spec:
  action: delay
  mode: all
  duration: "{duration}"
  selector:
    namespaces: [boutique]
    labelSelectors: {app: "{target}"}
  delay: {latency: "{latency}", jitter: "50ms", correlation: "50"}
```

Try both by hand with real values:
```bash
kubectl apply -f my-test.yaml            # inject
kubectl get podchaos,networkchaos -n boutique
# watch the shop at :8080 — it should break or slow down
kubectl delete -f my-test.yaml           # revert = delete the object
```
Things to check:
- [ ] The shop breaks or slows down while the fault is on, and recovers after `delete`.
- [ ] Leaving the fault alone makes it end by itself after `duration`. That's the fail-safe.
- [ ] Time how long recovery takes after `delete`. That's your baseline recovery time.

## Step 2: `inject.py` (≈45 min)
Three functions, nothing more. Use `kubectl` via subprocess; there's no need for the Kubernetes Python client.
```python
def apply(exp: dict) -> str:
    """Fill template for exp['fault'] with id/target/duration/params, kubectl apply -f -. Return CR name."""
def revert(exp: dict) -> None:
    """kubectl delete <kind> <id> -n boutique --ignore-not-found"""
def abort_all() -> None:
    """Big red button: kubectl delete podchaos,networkchaos,stresschaos,iochaos --all -n boutique"""
```
- Input is **contract #3** (`experiment.json`): `{id, fault, target, params, duration_s, hypothesis}`.
- Map `fault` → template + kind: `pod_failure → PodChaos`, `network_delay → NetworkChaos`.
- **Validate before applying:** the target must exist in the namespace, the namespace must be `boutique`, and `duration_s` must be ≤ `max_duration_s`. Reject anything else. This is a safety layer too.
- CLI so you can test alone:
  ```bash
  python -m chaosmind.inject apply experiments/exp-001.json
  python -m chaosmind.inject revert exp-001
  python -m chaosmind.inject abort
  ```

## Step 3: `thresholds.yaml` (5 min)
```yaml
error_rate: 0.20       # stop if >20% of requests fail
p95_ms: 2000           # stop if p95 latency > 2s
max_unhealthy: 2       # blast radius: stop if >2 services unhealthy
max_duration_s: 120    # hard cap on any experiment
poll_s: 2
recovery_timeout_s: 120
```

## Step 4: `guard.py`, the kill switch (≈1.5h, the core of your role)
```
run(exp):
  1. PREFLIGHT   snap = snapshot(); if snap already breaches thresholds → REFUSE (log "system unhealthy, not injecting")
  2. INJECT      inject.apply(exp); t0 = now
  3. WATCH       every poll_s: snap = snapshot()
                   if breach(snap) → log BREACH(which metric, value, limit, t) → inject.revert(exp) → go to 4
                   if now - t0 > duration_s → planned end → inject.revert(exp) → go to 4
  4. CONFIRM     poll until snapshot is back within thresholds AND no unhealthy services
                   → log HEALTHY(t)   (timeout → log "DID NOT RECOVER" — this is a finding!)
  5. RESULT      write runs/<id>.jsonl + return summary
```
- **`snapshot()` comes from B** (contract #2). **Don't wait for B.** Write a stub today:
  ```python
  # ponytail: stub until B's monitor.snapshot() lands; swap the import, same shape
  def snapshot(): ...  # unhealthy_services = deployments where readyReplicas < replicas (kubectl get deploy -n boutique -o json)
  ```
  The `unhealthy_services` part is easy to do yourself with `kubectl`. Use `error_rate=0`, `p95_ms=0` until B's version arrives.
- **Always revert, whatever happens:** wrap steps 2–4 in `try/finally: inject.revert(exp)`, and catch Ctrl-C (KeyboardInterrupt) so it reverts too. A crash must never leave a fault running; Chaos Mesh's `duration` is the last line of defence.
- **Log format** (one JSON object per line, with times in seconds from the start of injection):
  ```
  {"t": 0.0,  "event": "INJECTED", "fault": "network_delay", "target": "productcatalogservice"}
  {"t": 4.2,  "event": "BREACH",   "metric": "p95_ms", "value": 2340, "limit": 2000}
  {"t": 5.1,  "event": "REVERTED"}
  {"t": 18.0, "event": "HEALTHY",  "recovery_s": 12.9}
  ```
  Print it in colour to the terminal as well; this is what the judges see.

## Step 5: Test the kill switch (≈30 min) ← the required Day-1 checkpoint
| Test | How | Expected |
|---|---|---|
| Fires on breach | Set `p95_ms: 300`, inject a 500ms delay on `productcatalogservice` | BREACH → REVERTED within ~2s |
| Blast-radius trigger | Set `max_unhealthy: 0`, inject pod_failure on `cartservice` | BREACH on unhealthy_services |
| Preflight refuses | Leave one fault running by hand, then start a guarded run | REFUSED, nothing injected |
| Ctrl-C safety | Start a run, press Ctrl-C mid-way | Fault reverted, `kubectl get networkchaos` is empty |
| Fail-safe | Kill the guard process with `kill -9` mid-run | The fault still ends after `duration` |
| Abort | `make abort` / `inject abort` during a run | Everything is cleaned up instantly |

Save the log from each one in `runs/`. These are your evidence.

## Step 6: The Redis finding (≈20 min)
Hypothesis: *`redis-cart` has 1 replica and stores data in an `emptyDir` volume, so a pod restart wipes every cart.*
1. Add items to the cart in the shop (and note the cart count).
2. Kill it. **Here use `pod-kill`, on purpose**, because we want a real restart:
   ```bash
   kubectl delete pod -n boutique -l app=redis-cart
   ```
3. Refresh the cart. Is it empty? How long was the cart page erroring?
4. Write 3 lines: what happened, why (1 replica + no persistent volume), and the fix (a PersistentVolumeClaim, or Redis with persistence/replicas). Day 2 re-runs this after the fix.
   Check the manifest first (`kubectl get deploy redis-cart -n boutique -o yaml | grep -A3 volumes`) so the "why" is verified, not assumed.

## Step 7: Hand-offs
| To | What | When |
|---|---|---|
| B | Agree on the `snapshot()` shape (contract #2); swap your stub for theirs | H4 |
| D | `guard.run(exp)` is the function `run.py` calls; D's Safety Officer feeds you `experiment.json` | H4–H6 |
| A | `abort` → `make abort`; your test logs → README "Safety controls" section | H6 |

## What to say at the checkpoint (≈45s of the demo)
> "Every experiment passes through 4 safety layers. **Preflight** refuses to inject into an unhealthy system. The **guard** watches error rate, latency and blast radius every 2 seconds. On a breach it **reverts automatically**: here, a breach at 4.2s was reverted at 5.1s, and the app was healthy again at 18s. If our guard crashes, **Chaos Mesh's own timer** still ends the fault. And there's a manual **abort** for humans."

## Day 2 preview (don't build today)
More faults: `network_loss`, `cpu_stress` (StressChaos), `disk_fill` (IOChaos), traffic spike (scale the loadgenerator), combined failures.
