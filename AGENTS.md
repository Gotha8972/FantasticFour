# The 7 Agents: who builds what

**Pipeline**
```
② Cartographer → ① Strategist → ④ Safety Checker ⇄ inject.py/guard.py → Chaos Mesh
   (map)           (what to break)   (inject + ramp intensity)     (code: validate, auto-revert)
                                              ↓
                         ③ Observer (pre/post stats) + ⑥ Log Detective (why it broke)
                                              ↓
                         ⑤ Remediation (fix + re-run) → ⑦ Documentor (report)
```

**Demo story:**
> The Cartographer mapped the app → the Strategist predicted the weak points by blast radius → the Safety Checker injected safely and ramped intensity until the breaking point → the Observer showed the impact against the baseline → the Log Detective explained why → Remediation fixed it and the re-run proved it → the Documentor wrote it all up.

## Ground rules (everyone)
1. **Agents return JSON; code acts.** Even the Safety Checker never runs `kubectl` itself. It calls `guard.run()`, which calls `inject.py`, which validates everything (allowed fault, real target, `online-boutique` only, duration ≤ 120 s, latency ≤ 2000 ms). **The guard's kill-switch limits can't be changed by any agent.**
2. **One shared client:** `chaosmind/agents/llm.py` → `ask(system, user, model="large") -> dict` (Mistral, JSON mode, 1 retry on bad JSON). D builds it first.
3. **One agent = one file** in `chaosmind/agents/` with one public function and a `__main__` that runs on **saved files in `runs/`**, so it can be tested without the cluster.
4. **Every claim cites evidence:** a run ID, metric value or log line.
5. **Models:** `mistral-large-latest` for reasoning (Strategist, Safety Checker, Remediation, Documentor), `mistral-small-latest` for bulk reading (Cartographer, Log Detective, Observer). Confirm the exact IDs on the Mistral console.

## Who owns what

| Person | Agents | Why them |
|---|---|---|
| **D: AI lead** | `llm.py` + orchestrator + **② Cartographer** + **① Strategist** | The map feeds the Strategist directly, and D owns the pipeline |
| **C: Injection** | **④ Safety Checker** + **⑤ Remediation** | Both drive `inject.py`/`guard.py`, which C built |
| **A: Platform** | **③ Observer** + **⑥ Log Detective** | A built `monitor.py`, the baseline and the log capture |
| **B: Simulation** | **⑦ Documentor** + resilience score (code) + integrity checks for the Observer | Reports + the customer-journey checks from the simulator |

---

## ② Cartographer (D)
**Job:** build the dependency graph by reading the live network structure.
- **Code part:** read deployments, services and every `*_ADDR` env var (each one is a call edge) via `inject.kubectl()` → raw nodes + edges + replica counts + storage type (e.g. `redis-cart` uses `emptyDir`).
- **AI part:** label each service (`critical` / `optional` / `stateful`) and explain why.
- **Out:** `graph.json`
```json
{"nodes": [{"name": "redis-cart", "replicas": 1, "storage": "emptyDir", "role": "stateful", "why": "holds all carts"}],
 "edges": [{"from": "cartservice", "to": "redis-cart"}]}
```
- **Done when:** the edges match the verified README table (17 edges), and it's rendered as a Mermaid diagram.

## ① Strategist (D)
**Job:** find likely points of failure from the graph, and **predict** what happens if each one breaks.
- **Uses:** blast radius (how many services depend on it, directly and indirectly), fan-in/fan-out, single replicas, stateful storage, the critical path (checkout).
- **In:** `graph.json` + `baseline.json` + past results in `runs/`
- **Out:**
```json
{"targets": [{"service": "productcatalogservice", "rank": 1, "blast_radius": 4,
  "reason": "3 direct callers incl. checkout; single replica",
  "experiment": {"fault": "network_delay", "params": {"latency": "300ms"}, "duration_s": 60},
  "prediction": {"p95_ms": 1500, "error_rate": 0.02, "affected": ["frontend", "checkoutservice", "recommendationservice"]}}]}
```
- **Code afterwards:** compare prediction vs actual. The demo line is "the AI predicted 5 of 6 blast radii correctly".
- **Done when:** a top-5 that a human agrees with, and predictions saved next to actuals.

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
Cartographer → Strategist → for each target: Safety Checker (ramp via guard) →
Observer + Log Detective → (if weakness) Remediation + re-run → Documentor → FINDINGS.md
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

**If behind, cut in this order:** Documentor's self-check → Cartographer's AI labels (keep the code part) → intensity ramp (single intensity instead) → Strategist predictions.
**Never cut:** Strategist ranking, Safety Checker injection through the guard, Observer pre/post, Remediation re-run.
