# The 7 Agents: who builds what

**Pipeline**
```
② Cartographer → ① Strategist → ④ Safety Checker ⇄ inject.py/guard.py → Chaos Mesh
 (find weak spots) (prove them)   (inject + ramp intensity)     (code: validate, auto-revert)
                                              ↓
                         ③ Observer (pre/post stats) + ⑥ Log Detective (why it broke)
                                              ↓
                         ⑤ Remediation (fix + re-run) → ⑦ Documentor (report)
```

**Demo story:**
> The Cartographer audited the architecture and flagged its weakest spots → the Strategist turned each suspicion into an experiment with a prediction → the Safety Checker injected safely and ramped intensity until the breaking point → the Observer showed the impact against the baseline → the Log Detective explained why → Remediation fixed it and the re-run proved it → the Documentor wrote it all up.

## Ground rules (everyone)
1. **Agents return JSON; code acts.** Even the Safety Checker never runs `kubectl` itself. It calls `guard.run()`, which calls `inject.py`, which validates everything (allowed fault, real target, `online-boutique` only, duration ≤ 120 s, latency ≤ 2000 ms). **The guard's kill-switch limits can't be changed by any agent.**
2. **One shared client:** `chaosmind/agents/llm.py` → `ask(system, user, model="large") -> dict` (Mistral, JSON mode, 1 retry on bad JSON). D builds it first.
3. **One agent = one file** in `chaosmind/agents/` with one public function and a `__main__` that runs on **saved files in `runs/`**, so it can be tested without the cluster.
4. **Every claim cites evidence:** a run ID, metric value or log line.
5. **Models:** `mistral-large-latest` for reasoning (Cartographer, Strategist, Safety Checker, Remediation, Documentor), `mistral-small-latest` for bulk reading (Log Detective, Observer). Confirm the exact IDs on the Mistral console.

## Who owns what

| Person | Agents | Why them |
|---|---|---|
| **D: AI lead** | `llm.py` + orchestrator + **② Cartographer** + **① Strategist** | The Cartographer's findings feed the Strategist directly, and D owns the pipeline |
| **C: Injection** | **④ Safety Checker** + **⑤ Remediation** | Both drive `inject.py`/`guard.py`, which C built |
| **A: Platform** | **③ Observer** + **⑥ Log Detective** | A built `monitor.py`, the baseline and the log capture |
| **B: Simulation** | **⑦ Documentor** + resilience score (code) + integrity checks for the Observer | Reports + the customer-journey checks from the simulator |

---

## ② Cartographer (D): architecture vulnerability auditor
**Job:** it doesn't draw the graph (code does that, and Google's map is already verified). It **reads the architecture and finds its most vulnerable points *before* anything is broken**, like a reviewer doing a static audit.

**Code gathers the facts** (via `inject.kubectl()`, read-only):
- Call graph from every `*_ADDR` env var → fan-in (who depends on it), fan-out, longest synchronous chain, reachability from `frontend`/`checkout`
- Per deployment: replicas, readiness/liveness probes, resource requests/limits, volumes (`emptyDir` vs PVC), PodDisruptionBudget, HPA

**AI reasons over the facts** and returns ranked vulnerabilities, each with a hypothesis to test:
```json
{"vulnerabilities": [
  {"id": "V1", "service": "redis-cart", "severity": "critical",
   "weakness": "Single replica, data on emptyDir: every cart lives in one pod's temporary disk",
   "evidence": {"replicas": 1, "volume": "emptyDir", "pdb": false, "callers": ["cartservice"]},
   "hypothesis": "Restarting redis-cart silently wipes all carts while HTTP stays 200",
   "blast_radius": ["cartservice", "frontend", "checkoutservice"]},
  {"id": "V2", "service": "productcatalogservice", "severity": "high",
   "weakness": "Highest fan-in (frontend, checkout, recommendation), single replica, on the checkout path",
   "hypothesis": "Latency here propagates to every page and to checkout"}]}
```
Things it should look for: single points of failure, stateful services without persistence, high fan-in hotspots, long synchronous chains on the revenue path (checkout), missing probes, missing PDBs, everything at 1 replica, and optional dependencies (ads, recommendations) that *should* fail gracefully.

- **Why it's a real agent:** facts → judgement. Code can count callers; deciding *which* combination of facts is dangerous, and why, is reasoning.
- **Scored later:** each vulnerability is either **confirmed** or **refuted** by experiments. The demo line is "the static audit flagged 6 risks; experiments confirmed 4 and refuted 2". Redis (V1) and ads-fail-gracefully are already known, so they're free first checks.
- **Done when:** it returns a ranked list where every item cites real config facts, and the top items include redis-cart and productcatalog.

## ① Strategist (D)
**Job:** turn the Cartographer's vulnerabilities into **experiments that prove or refute them**, predict the outcome, and **re-plan after every result**.
- **In:** `vulnerabilities.json` + `baseline.json` + allowed faults + results so far
- **Out:**
```json
{"plan": [{"vulnerability": "V2", "rank": 1,
  "experiment": {"fault": "network_delay", "target": "productcatalogservice", "params": {"latency": "200ms"}, "duration_s": 30},
  "prediction": {"p95_ms": 1200, "error_rate": 0.02, "affected": ["frontend", "checkoutservice", "recommendationservice"]},
  "reason": "Highest fan-in on the checkout path; test latency propagation"}]}
```
- **Loop:** after each experiment, it's called again with the result: mark the vulnerability `confirmed` / `refuted`, re-rank what's left ("catalog was worse than predicted → test checkout's other dependencies next; ads degraded gracefully → skip recommendation").
- **Code afterwards:** prediction vs actual → "the AI predicted 5 of 6 blast radii correctly".
- **Done when:** every plan item maps to a vulnerability, passes `inject.validate()`, and the plan visibly changes after a result.

## ④ Safety Checker (C): the agent that injects
**Job:** take the Strategist's experiment, decide if it's safe right now, **inject it through `guard.run()`**, and **ramp intensity** step by step to find the breaking point.
- **Before:** check current health vs baseline; approve, shrink or reject. It may only make experiments **smaller** (checked in code).
- **Ramp (intensity up/down):**
```
step 1: 100ms → guard.run() → metrics OK? → step 2: 200ms → OK? → step 3: 400ms → BREACH → auto-revert
→ result: "productcatalog tolerates ≤ 200ms; breaks at 400ms"
```
  If a step breaches, stop ramping and step back down. Never jump more than 2× per step. Each step is a full guarded run.
- **Out:** `{"decision": "approve|shrink|reject", "reason": "...", "steps": [{"latency": "100ms", "run": "<run id>", "breach": false}, ...], "breaking_point": "400ms"}`
- **New fault types to add in `inject.py`** (needed: ≥3 types): `network_loss` (packet loss %) and `cpu_stress` (StressChaos). Both with validation caps.
- **Done when:** a ramp on productcatalog produces a breaking point, and a deliberately risky request gets shrunk or rejected.

## ③ Observer (A)
**Job:** measure how each failure affects the graph, **pre vs during vs post**.
- **In:** run directory (`metrics.csv`, `events.jsonl`) + `baseline.json` + `graph.json`
- **Code part:** per experiment, compute a pre / during / post table: error rate, p50/p95, RPS, checkout success, unhealthy services, restarts, recovery time. Mark which graph nodes degraded.
- **Integrity checks (from B):** did the cart survive? did checkout really create an order? These catch **silent failures** like the Redis cart wipe with 0 errors.
- **AI part:** a short description of the impact ("latency spread from catalog to checkout and frontend; no errors; recovered in 14.8 s").
- **Out:** `impact.json` per run, with a `nodes_affected` list (used to colour the graph red/amber/green in the demo).
- **Done when:** it works on the existing delay/cart-down/ad-health runs in `runs/`.

## ⑥ Log Detective (A)
**Job:** say **what actually broke and why**, using logs.
- **In:** experiment time window + the log CSVs in `runs/<id>/` (frontend, target, loadgenerator, chaos-daemon). Pre-filter in code to error/warn lines inside the window.
- **Out:** `{"root_cause": "...", "chain": ["cartservice unavailable", "frontend: rpc Unavailable", "HTTP 500 to user"], "evidence": ["<log line>"], "confidence": "high|medium|low"}`
- **First real case:** the **2 checkout HTTP 500s in the baseline with no faults injected**.
- **Done when:** on the cart-down run it names the failing call chain with real log lines.

## ⑤ Remediation (C)
**Job:** produce the actual fix for a weakness, apply it in our sandbox, and **prove it** with a re-run.
- **In:** finding (from the Observer + Log Detective) + current deployment YAML of the target
- **Out:** `{"fix": "...", "patch": {<kubectl patch JSON>}, "expected_effect": "..."}`
- **Allow-list in code:** only replicas, resources, probes, PodDisruptionBudget, and persistence/PVC for `redis-cart`, only in `online-boutique`.
- **Verify:** re-run the identical experiment → before vs after score and metrics.
- **First target:** Redis cart loss → PVC + `appendonly yes` → re-run the Redis test → the cart survives.
- **Done when:** the Redis before/after shows the cart surviving and the score going up.

## ⑦ Documentor (B)
**Job:** document all the stats into the final findings report.
- **In:** everything above (`graph.json`, Strategist predictions, Safety Checker ramps, Observer impact, Log Detective causes, Remediation before/after)
- **Out:** `FINDINGS.md`: weaknesses **ranked by severity**, each with numbers, root cause, fix, before/after, resilience score, and the run IDs it's based on. Plus prediction accuracy and breaking points.
- **Self-check:** a final pass where it verifies every number in the report against the source files and flags anything it can't find. This answers "LLMs hallucinate, how do you know?"
- **Also B: resilience score**, plain code, 0–100, relative to the baseline:
  `100 − error-rate impact − latency impact − recovery-time impact − 25 per integrity violation`. Formula documented in the README.

---

## Orchestrator (D): `python3 -m chaosmind.run`
```
Cartographer (audit) → Strategist → for each experiment: Safety Checker (ramp via guard) →
Observer + Log Detective → Strategist re-plans (confirmed/refuted) → (if confirmed) Remediation + re-run → Documentor → FINDINGS.md
```
Every step writes to `runs/`, so everything is replayable offline.

## Order of work (Day 2)
| When | Milestone |
|---|---|
| H0–1 | D: `llm.py`. Everyone else: build your agent against saved `runs/` files |
| H1–3 | Each agent works standalone on saved data. C adds `network_loss` + `cpu_stress` |
| H3–4 | **Integration:** orchestrator runs ② → ① → ④ → ③ → ⑥ on one live target |
| H4–5 | ⑤ Redis fix + re-run; ⑦ report generated |
| H5–6 | Feature freeze → clean run → record the demo |

**If behind, cut in this order:** Documentor's self-check → Strategist re-planning loop (run the plan once) → intensity ramp (single intensity instead) → Strategist predictions.
**Never cut:** Strategist ranking, Safety Checker injection through the guard, Observer pre/post, Remediation re-run.
