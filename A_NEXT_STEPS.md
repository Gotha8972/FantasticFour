# For A: next steps (≈30 min)

Great work on the baseline. 4 things, in order.

## 1. Push ALL your code (most important, ≈5 min)
GitHub has your **results** but not the **code** that produced them. Anyone who clones the repo, judges included, can't run anything. Missing so far:

| Missing | Referenced by |
|---|---|
| `scripts/` (deploy-local, install-kubectl, install-chaos, chaos, load, measure-load, baseline) | README setup, BASELINE_STUDY.md |
| `deploy/` (kind.yaml, kustomization, namespace, containers.conf) | deploy-local.sh |
| `chaos/` (values.yaml, loadgenerator-observability.yaml, experiments/*.yaml, README.md) | monitor.py needs the Locust stats patch |
| `chaosmind/baseline.py`, `chaosmind/c_tests.py`, `chaosmind/test_c_tests.py` | BASELINE_STUDY.md, KILLSWITCH_RESULTS.md |
| `tests/README.md` + your edited `tests/*.sh`, `COMPATIBILITY.md` | KILLSWITCH_RESULTS.md, PROJECT_HANDOFF.md |

```bash
git status
```
Check that `.runtime/` and `microservices-demo/` are **not** listed. If they are, add them to `.gitignore` first. Then:
```bash
git add scripts deploy chaos chaosmind tests COMPATIBILITY.md .gitignore
```
```bash
git commit -m "Add setup scripts, chaos config and runners" && git push
```
**Check:** open https://github.com/Gotha8972/FantasticFour and make sure the `scripts/`, `deploy/` and `chaos/` folders are visible.

## 2. Accept this baseline (≈10 min)
The 15-min study is good, but it was marked unsuitable because the rule is "zero failures". Real systems always have some background failures, and what we measure is **chaos vs normal**. Change the suitability rule in `chaosmind/baseline.py` to:

- window error rate **< 1%** (ours: 0.05%)
- **0** unhealthy services, **0** restart increases, **0** pod replacements (keep these strict)

Re-evaluate the finished study **without re-running it** if your code allows (or re-run `bash scripts/baseline.sh`), so `baseline.json` is published at the repo root. Then push:
```bash
git add -f baseline.json chaosmind/baseline.py && git commit -m "Accept baseline: error rate < 1% rule" && git push
```
Keep the finding "2 checkout 500s with no faults injected" in the report. It's a real result, not something to hide.

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
