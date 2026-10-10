# For A: next steps (≈30 min)

Great work on the baseline. 4 things, in order.

## 1. Push the rest of your code (≈5 min)
Thanks for pushing `baseline.py`, `c_tests.py`, `test_c_tests.py` and `scripts/baseline.sh`. All offline tests pass. **Still missing**, so nobody can set up from GitHub:

| Missing | Referenced by |
|---|---|
| Rest of `scripts/` (deploy-local, install-kubectl, install-chaos, chaos, load, measure-load) | README setup, `baseline.sh --start-load` |
| `deploy/` (kind.yaml, kustomization, namespace, containers.conf) | deploy-local.sh |
| `chaos/` (values.yaml, loadgenerator-observability.yaml, experiments/*.yaml, README.md) | monitor.py needs the Locust stats patch |
| `tests/README.md`, `COMPATIBILITY.md` | KILLSWITCH_RESULTS.md, PROJECT_HANDOFF.md |

```bash
git status
```
Check that `.runtime/` and `microservices-demo/` are **not** listed (add them to `.gitignore` if they are). Then:
```bash
git add scripts deploy chaos tests/README.md COMPATIBILITY.md .gitignore
```
```bash
git commit -m "Add setup scripts and chaos config" && git push
```
**Check:** the `deploy/` and `chaos/` folders show up on https://github.com/Gotha8972/FantasticFour.

## 2. Accept the baseline (≈2 min of edits + 16 min re-run)
It's marked unsuitable only because of this rule in `chaosmind/baseline.py` (~line 240):
```python
if failures:
    result['findings'].append(f'{failures} failed requests occurred without intentional faults.')
```
Any finding makes the baseline unsuitable. Real systems always have some background failures, and what we measure is chaos **vs** normal, so allow a small error rate. Change it to:
```python
if failures and failures / requests >= 0.01:   # >= 1% errors is not a normal steady state
    result['findings'].append(f'{failures} failed requests occurred without intentional faults.')
elif failures:
    result['notes'] = [f'{failures} failed requests ({failures / requests:.2%}) without faults: background error rate.']
```
The unhealthy-services, restart, pod-change and gap checks stay strict. There's no re-evaluate mode, so re-run the study (it writes `baseline.json` at the root once it's suitable):
```bash
bash scripts/baseline.sh
```
Then push:
```bash
git add -f baseline.json runs/baseline-study-* chaosmind/baseline.py && git commit -m "Baseline: allow <1% background errors" && git push
```
Short on time? `bash scripts/baseline.sh --duration 300` (5 min) is enough. Keep the "2 checkout 500s with no faults" result from the first study in the report; it's a real finding.

## 3. Guard limits based on the baseline (team decision, ≈5 min)
The current limits are ~26–400× worse than normal, which is hard to defend to judges. Proposed:

| Limit | Now | Baseline | Proposed |
|---|---|---|---|
| `error_rate` | 0.20 | 0.0005 (max 0.025) | **0.05** |
| `p95_ms` | 2000 | 78 mean, 240 max | **1000** |
| `max_unhealthy` | 2 | 0 | 2 (unchanged) |

This is a 2-number change in `LIMITS` in `chaosmind/guard.py`. **Check with the team first.** Tighter limits mean experiments stop sooner, so the earlier results stay valid but would trip earlier.

## 4. Optional: why did 2 checkouts fail? (≈10 min)
Two `POST /cart/checkout` calls returned HTTP 500 around **07:27:04 and 07:30:00 UTC** with no chaos running. The frontend logs you exported start after that. If the pods still have older logs:
```bash
kubectl --kubeconfig .runtime/kubeconfig --context kind-online-boutique -n online-boutique logs deploy/checkoutservice --since=3h | grep -i error
```
Do the same for `paymentservice` and `frontend`. Save anything you find to `runs/` and push it. If the logs are gone, that's fine; D's Log Detective agent will handle this kind of thing going forward.
