# Aashrith: cluster owner, live verification, Analyst logs

Read [GUIDE_00_EVERYONE.md](GUIDE_00_EVERYONE.md) first.

**Your role:** everything is built. **Only your laptop can make it real.** Today you turn "offline-tested" into "proven live", one item at a time, and push the evidence after each. **Type cluster commands yourself in a normal terminal**; your AI assistant can't reach the cluster.

Start every session with:
```bash
git pull
```
```bash
bash scripts/load.sh start 20 2
```
And keep Grafana open: `bash scripts/monitoring.sh grafana`.

---

## 1. AI dry run (5 min, injects nothing)
```bash
.venv/bin/python -m chaosmind.graph --dry-run
```
**Expect:** Cartographer vulnerabilities (Redis should be #1), the Strategist's first experiment, and the Safety Checker's decision and ramp.

| Error | Cause |
|---|---|
| `NVIDIA NIM API 401` | Bad `NVIDIA_API_KEY` in `.env` |
| `NVIDIA NIM API 404/400` | Wrong `NIM_MODEL` name |
| `invalid JSON twice` | Send the output to Smrithi |

```bash
git add -f runs/agents-* && git commit -m "First agent dry run" && git push
```

## 2. Prove the unverified fault types (≈20 min)
One guarded run each. Wait for `HEALTHY` between them. **After each one succeeds**, add its name to `LIVE_VERIFIED` in `chaosmind/inject.py`. That's what lets the AI use it.

| Order | Command | Brief item |
|---|---|---|
| 1 | `python3 -m chaosmind.guard experiments/catalog-loss.json` | lossy network |
| 2 | `python3 -m chaosmind.guard experiments/cart-redis-partition.json` | failed dependency |
| 3 | `python3 -m chaosmind.guard experiments/redis-cpu.json` | overloaded database |
| 4 | `python3 -m chaosmind.guard experiments/redis-podkill.json` | crash (instant kill) |
| 5 | `python3 -m chaosmind.guard experiments/redis-disk-full.json` | full disk. **Last**, because IOChaos is the flakiest part of Chaos Mesh. If it errors, push the error; we'll drop it from the claims |

```bash
git add -f runs chaosmind/inject.py && git commit -m "Live-verify fault types" && git push
```
Tell Srinavith which passed. He updates the README coverage table.

## 3. Integrity checks, live smoke test (5 min, with Harshil)
With nothing broken, this should print `cart before: 1` and then `[]` (no violations):
```bash
python3 -m chaosmind.agents.integrity
```
If it reports `checkout_completes`, the order-confirmation text differs from what the code expects. Send Harshil the output.

## 4. Logs for the mystery checkout 500s (≈10 min)
The logs rotate quickly, so capture them right after a baseline:
```bash
bash scripts/baseline.sh --duration 300
```
```bash
python3 -m chaosmind.checkout_investigation --since 15m
```
Push the `runs/checkout-investigation-*` folder. Look for `paymentservice` or `checkoutservice` errors near the failure times. **If you find the cause, that's a headline finding.** We've already ruled out expired cards and invalid card numbers from the load generator's source.

## 5. The full live AI run, screen-recorded (with Smrithi + Srinavith, ≈25 min)
```bash
.venv/bin/python -m chaosmind.graph --budget 3 --remediate
```
Record the terminal **and** Grafana side by side; the demo video is cut from this. Afterwards:
```bash
git add -f runs/agents-* && git commit -m "Full live agent run" && git push
```

## 6. Redis instant-kill check
The graceful restart is proven ✅. The instant kill (append-only log) is still open. See [A_REDIS_FIX_AND_FAULTS.md](log/A_REDIS_FIX_AND_FAULTS.md), section 3B. Your `python3 scripts/incidents/menu.py` menu can also generate the live runs for section 2. Push its `runs/` output.

## 7. One small code fix
`baseline.json` stores `/home/aashrith/...` in `artifact_dir`. Make `chaosmind/baseline.py` store the path relative to the project root.

## What to learn
- **The Analyst** (`chaosmind/agents/analyst.py`) pulls `kubectl logs --since-time` for the frontend and target during each fault, keeps error-like lines, and only allows the AI to quote lines that really exist. Read `error_lines()` and `fact_check()`. Those are the anti-hallucination parts judges will ask about.
- **Why we gate the AI to `LIVE_VERIFIED` faults:** the AI shouldn't plan experiments we've never seen work.
