# Aashrith: platform owner + Observer + Log Detective

Read [GUIDE_00_EVERYONE.md](GUIDE_00_EVERYONE.md) first.

**Your role:** you own the only machine with the cluster, so everything "live" goes through you. You also build two agents that *watch and explain*: the **Observer** (what changed) and the **Log Detective** (why it broke).

**Important:** your AI coding assistant **cannot reach the cluster** ("socket: operation not permitted"). Anything that needs the cluster, **type it yourself in a normal terminal**.

---

## Part 1: Live runs only you can do (≈45 min, do these first)
Setup for all of them:
```bash
git pull
```
```bash
bash scripts/load.sh start 20 2
```
Keep Grafana open: `bash scripts/monitoring.sh grafana`.

### 1.1 First real AI dry run (5 min, injects nothing)
```bash
python3 -m chaosmind.agents --dry-run
```
**What you should see:**
1. **Cartographer:** a ranked list like `V1 [critical] redis-cart: …`, `V2 [high] productcatalogservice: …`.
2. **Strategist → …**: the first experiment and the reason for it.
3. **Safety Checker:** a decision (`approve`/`shrink`/`reject`) and a ramp, e.g. `[100, 200, 400]`.

**If it errors:**
- `Mistral API 401`: wrong key in `.env`.
- `Mistral API 400`: the model name is wrong. Set `MISTRAL_LARGE=mistral-large-latest` or check the console.
- `invalid JSON twice`: send the output to Smrithi (prompt issue).

Publish:
```bash
git add -f runs/agents-* && git commit -m "First agent dry run" && git push
```

### 1.2 One live run of each brief fault type (≈15 min)
Wait for `HEALTHY` between runs. Full list and the Redis before/after steps: [A_REDIS_FIX_AND_FAULTS.md](A_REDIS_FIX_AND_FAULTS.md).
```bash
python3 -m chaosmind.guard experiments/catalog-loss.json
```
```bash
python3 -m chaosmind.guard experiments/redis-cpu.json
```
```bash
python3 -m chaosmind.guard experiments/cart-redis-partition.json
```
```bash
python3 -m chaosmind.guard experiments/redis-disk-full.json
```
An `ERROR` is useful evidence, not a failure. Push it.

### 1.3 Capture logs for the mystery checkout 500s (≈10 min)
Background checkouts fail ~1.3% with nothing broken. Your Log Detective needs real logs, and they rotate away quickly, so capture them *right after* a baseline:
```bash
bash scripts/baseline.sh --duration 300
```
```bash
python3 -m chaosmind.checkout_investigation --since 15m
```
Push the `runs/checkout-investigation-*` folder. That's your Log Detective's first real case.

---

## Part 2: Build the ③ Observer (≈1.5 h)
**Concept:** the guard already records metrics *before*, *during* and *after* every fault (`stage` in each SNAPSHOT). The Observer turns that into a clear **pre / during / post comparison**, works out **which services were affected**, and writes a 1–2 sentence summary. Code does the maths; the AI only writes the summary.

**File:** `chaosmind/agents/observer.py`

**Input:**
- `events`: the list from `guard.run()`, or loaded from `runs/<id>/events.jsonl`
- `baseline`: the dict from `baseline.json`
- `facts`: from `chaosmind.agents.facts.collect()`, so you know who calls whom

**Output (`impact.json` inside the run folder):**
```json
{"experiment": "test-down", "target": "cartservice", "fault": "pod_failure",
 "phases": {
   "pre":    {"error_rate": 0.0,  "p95_ms": 45,   "rps": 4.9, "unhealthy": []},
   "during": {"error_rate": 0.35, "p95_ms": 2700, "rps": 3.4, "unhealthy": ["cartservice"]},
   "post":   {"error_rate": 0.0,  "p95_ms": 60,   "rps": 4.8, "unhealthy": []}},
 "vs_baseline": {"error_rate_x": 700, "p95_x": 77},
 "recovery_s": 55.5,
 "nodes_affected": {"cartservice": "down", "frontend": "degraded", "checkoutservice": "degraded"},
 "summary": "Cart outage caused 35% errors site-wide; recovered in 55 s."}
```

**Step by step:**
1. **Group SNAPSHOT events by stage:** `preflight` → pre, `injecting` + `injected` → during, `recovery` → post.
2. **Phase summaries (code):** pre = the last preflight snapshot; during = **worst** values (max error_rate, max p95, union of unhealthy); post = the **last** recovery snapshot.
3. **Compare with the baseline:** divide by `baseline['metrics']['error_rate']['mean']` and `['p95_ms']['mean']`, guarding against division by zero.
4. **`nodes_affected` (code):**
   - target = `down` if it appeared in `unhealthy_services`, else `degraded`
   - every service in `facts['services'][target]['dependents']` = `degraded` **if** `during` is clearly worse than the baseline (e.g. p95 > 3× or error rate > 1%), else `ok`

   These colours later light up the dependency graph in the demo.
5. **AI part (small model):** send the phases + `nodes_affected` and ask for one or two sentences. **Rule in the prompt:** only use numbers present in the input.
6. **Save** `impact.json` into the run's `artifact_dir` (every event has `artifact_dir`).

**Test offline** on the real saved runs: `runs/test-down-20261010T062320.861245Z/events.jsonl` (cart down) and `runs/test-delay-20261010T062255.501508Z/events.jsonl` (catalog delay). Assert that `during.error_rate` > `pre.error_rate` for cart down, and that `cartservice` is `down`.

**Done when:**
- `python3 -m chaosmind.agents.observer runs/test-down-…/events.jsonl` prints a sensible `impact.json`.
- 2+ unit tests pass in `chaosmind/agents/test_observer.py`.

---

## Part 3: Build the ⑥ Log Detective (≈1.5 h)
**Concept:** metrics say *that* something broke; logs say *why*. The Log Detective reads the pod logs from the experiment window, keeps only error-like lines, and asks the AI to reconstruct the **failure chain** ("cartservice unavailable → frontend got `rpc error: Unavailable` → user saw HTTP 500"), **quoting real log lines as evidence**.

**File:** `chaosmind/agents/log_detective.py`

**Input:**
- the experiment's time window (from the events: `INJECTED` time → `HEALTHY` time, plus 10 s margin)
- the log CSVs in the run folder (`*-logs.csv`, columns `timestamp_utc, pod, container, message`)
- if they're missing, collect them live with your existing `capture.logs(output, namespace, selector, since)`

**Output:**
```json
{"root_cause": "cartservice was unavailable; frontend has no retry for cart calls",
 "chain": ["cartservice pod-failure", "frontend: rpc error code = Unavailable", "HTTP 500 on POST /cart"],
 "evidence": [{"pod": "frontend-…", "time": "…", "line": "…exact log line…"}],
 "confidence": "high|medium|low",
 "unexplained": ["what the logs don't show"]}
```

**Step by step:**
1. **Load the logs (code)** and keep rows inside the time window.
2. **Filter (code)** to lines matching `error|fail|unavailable|timeout|refused|panic|exception|5\d\d` (case-insensitive).
3. **Trim (code):** de-duplicate repeated messages (keep a count) and cap at ~150 lines, because models have input limits.
4. **AI (small model):** "Here is the experiment and the error lines. Reconstruct the failure chain. Quote evidence lines EXACTLY. If the logs don't explain it, say so in `unexplained`; don't guess."
5. **Verify (code):** every `evidence.line` must appear in the logs you sent. Drop the ones that don't (same idea as the Cartographer's `verify`).
6. **Save** `root_cause.json` into the run folder.

**First real cases:**
- The cart-down run (`runs/test-down-…`): expect frontend `Unavailable` errors.
- The checkout 500s from Part 1.3. **If you crack this one, it's a headline finding for the demo.**

**Done when:** the cart-down run produces a chain with at least 2 verified evidence lines, and 2+ unit tests pass (including "an invented evidence line gets dropped").

---

## Part 4: Hand-offs
- **To Smrithi** (orchestrator): `observer.observe(events, baseline, facts) -> dict` and `log_detective.explain(exp, events) -> dict`.
- **To Harshil** (score + Documentor): `impact.json` and `root_cause.json` in every run folder.
- **To Srinavith** (Remediation): `root_cause.json` tells Remediation *what* to fix.

## What to learn while doing this
- **Time-windowing evidence:** aligning metrics and logs by timestamp (watch out: UTC vs IST).
- **Grounding:** making an AI cite real evidence and checking it in code.
- **Why "HEALTHY" in Kubernetes ≠ customers recovered:** you measured it yourself (3 s vs 34 s).
