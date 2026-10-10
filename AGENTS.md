# The 6 Agents: who builds what

**Demo story these 6 agents produce together:**
> The AI **predicted** the impact → the **Safety Officer** shrank a risky plan → we broke it safely → the **Integrity Oracle** caught a silent failure that monitoring missed → the **Log Detective** explained the root cause → the **Remediation Engineer** fixed it and **proved** the fix with a re-run → the **Critic** fact-checked the final report against the evidence.

## Who actually injects the failure?
**No LLM does, by design.** The AI **decides** and our code **executes**:
```
① Strategist (AI) proposes → ② Safety Officer (AI) approves/shrinks → Operator inject.py (code) creates the
Chaos Mesh fault → Chaos Mesh breaks the pod/network → guard.py (code) watches and auto-reverts
```
The **Operator** (`inject.py` + `guard.py`, already built and tested live) is a deterministic agent with no LLM. It validates every experiment (allowed fault, real target, our namespace only, duration ≤ 120 s) before creating anything. That way a hallucinated or prompt-injected AI output can never reach the cluster unchecked.

## Ground rules (everyone)
1. **Agents only return JSON.** They never run `kubectl` or touch the cluster. Our deterministic code validates the JSON and then acts. The guard stays plain code; no agent can loosen it.
2. **One shared client:** `chaosmind/agents/llm.py` → `ask(system, user, schema_hint, model="large") -> dict` (Mistral, JSON mode, 1 retry on invalid JSON). D builds it first; everyone imports it.
3. **One agent = one file** in `chaosmind/agents/`, with one public function. Inputs and outputs are the contracts below; don't change them without telling the owner of the next agent.
4. **Every claim cites evidence:** run IDs, metric values or log lines. The Critic rejects anything without them.
5. Each agent ships a `__main__` that runs on a **saved file from `runs/`**, so it can be tested without the cluster.
6. **Models:** `mistral-large-latest` for reasoning (Strategist, Safety, Remediation, Analyst/Critic), `mistral-small-latest` for high-volume reading (Log Detective). Check the exact model IDs on the Mistral console.

## Who owns what

| Person | Agents | Why them |
|---|---|---|
| **D: AI lead** | `llm.py` + orchestrator `run.py` + **① Strategist & Predictor** | Owns the pipeline everyone plugs into |
| **C: Injection** | **② Safety Officer** + **⑤ Remediation Engineer & Verifier** | Both sit right next to the guard/injector C knows |
| **B: Simulation** | **③ Integrity Oracle** + resilience score (plain code) | Extends the customer simulator's journeys |
| **A: Platform** | **④ Log Detective** + **⑥ Analyst & Critic** | A already captures pod logs and writes evidence-rigorous reports |

---

## ① Strategist & Predictor (D)
**Job:** choose and rank the next experiments, and **predict the numbers before running them**.
- **In:** dependency map (README table), `baseline.json`, list of allowed faults, past results from `runs/`
- **Out:**
```json
{"experiments": [{"id": "exp-catalog-delay", "fault": "network_delay", "target": "productcatalogservice",
  "params": {"latency": "300ms"}, "duration_s": 60, "rank": 1,
  "reason": "3 callers; widest blast radius",
  "prediction": {"p95_ms": 1500, "error_rate": 0.02, "unhealthy": 0,
                 "affected": ["frontend", "checkoutservice", "recommendationservice"]}}]}
```
- **Code (not AI) afterwards:** compare prediction vs actual and log `prediction_error`. The demo line is "the AI predicted 5 of 6 blast radii correctly".
- **Done when:** it outputs a top-3 for our cluster that a human agrees with, every one passes `inject.validate()`, and predictions are logged next to actuals.

## ② Safety Officer (C)
**Job:** review each proposed experiment **before** the guard sees it: approve, shrink, or reject, with a reason.
- **In:** one experiment + baseline + currently unhealthy services
- **Out:** `{"decision": "approve|shrink|reject", "experiment": {...possibly reduced...}, "reason": "..."}`
- **Hard rule in code:** the Safety Officer may only make an experiment *smaller* (shorter duration, lower latency, fewer targets). Code checks that the output is ≤ the input on every field and rejects anything else.
- **Demo moment:** feed it "500ms delay on checkout + cart down for 120s" → it shrinks or rejects with a reason.
- **Done when:** 5 hand-made risky/safe cases give sensible decisions, and the "only smaller" check is unit-tested.

## ③ Integrity Oracle (B)
**Job:** catch failures that **look healthy**, where HTTP returns 200 but the data is wrong. This is our differentiator: the Redis test wiped carts with **0 errors**.
- **Deterministic checks (code, run before/during/after each experiment):**
  - cart keeps its items across the experiment (same session before/after)
  - checkout actually creates an order (an order confirmation ID is in the response)
  - currency conversion is consistent (same product, same currency → same price)
  - product page shows the right product
- **AI part:** given the experiment + check results, explain which business promise broke and why it matters: `{"violations": [{"check": "cart_persistence", "evidence": "...", "business_impact": "..."}]}`
- **Also yours: the resilience score**, plain code, 0–100, per experiment and overall. Suggested:
  `100 − (error-rate impact + latency impact + recovery-time impact + 25 per integrity violation)`, all relative to the baseline. Document the formula in the README.
- **Done when:** the Redis restart shows a `cart_persistence` violation while the error rate is 0, and every run gets a score.

## ④ Log Detective (A)
**Job:** explain **why** something broke, from the pod logs we already capture.
- **In:** experiment + its time window + the log CSVs from `runs/<id>/` (frontend, target, loadgenerator, chaos-daemon). Pre-filter in code to error/warn lines inside the window, then trim before sending.
- **Out:** `{"root_cause": "...", "chain": ["cartservice unavailable", "frontend rpc Unavailable", "no retry → HTTP 500"], "evidence": ["<log line>", ...], "confidence": "high|medium|low"}`
- **First real case:** the **2 checkout HTTP 500s in the baseline with no faults injected**.
- **Done when:** for the cart-down run it names the failing call chain, quoting actual log lines.

## ⑤ Remediation Engineer & Verifier (C)
**Job:** turn a weakness into a **Kubernetes fix**, apply it in our sandbox, **re-run the same experiment**, and prove improvement.
- **In:** finding (from the Analyst/Oracle) + the current deployment YAML of the target
- **Out:** `{"fix": "...", "patch": {<kubectl patch JSON>}, "expected_effect": "..."}`
- **Allow-list in code:** only `replicas`, resources, probes, PodDisruptionBudget, and a PVC/persistence for `redis-cart`, only in `online-boutique`. Anything else is rejected.
- **Verifier (code):** re-run the identical experiment → compare score and metrics before vs after → `{"before": 41, "after": 78, "verdict": "improved"}`
- **First target:** Redis cart loss → PVC + `appendonly yes` → re-run the Redis test → cart survives.
- **Done when:** the Redis before/after shows the cart surviving and the score going up.

## ⑥ Analyst & Critic (A)
**Analyst:** combines all results into the findings report: weaknesses **ranked by severity**, each with evidence, root cause (from ④), fix (from ⑤) and score.
**Critic:** a second pass that checks **every claim** against the evidence files and removes or flags anything unsupported. It answers the obvious judge question "LLMs hallucinate, how do you know this is true?"
- **Out:** `FINDINGS.md`. Every finding cites run IDs; the Critic's verdict is listed per finding (`supported` / `flagged`).
- **Done when:** the final report is generated from real runs, and the Critic catches at least one planted false claim in a test.

---

## Orchestrator (D): `python3 -m chaosmind.run`
```
Strategist → for each experiment: Safety Officer → guard.run() [+ Integrity checks] →
Log Detective → (if weakness) Remediation → Verifier → Analyst → Critic → FINDINGS.md
```
Everything is written to `runs/` so every step is replayable offline.

## Order of work (Day 2)
| When | Milestone |
|---|---|
| H0–1 | D: `llm.py` working. **Everyone else:** build your agent against saved `runs/` files, with no cluster needed |
| H1–3 | Each agent works standalone on saved data |
| H3–4 | **Integration:** D's orchestrator calls agents ①②③④ on one live experiment |
| H4–5 | ⑤ Redis fix + re-run; ⑥ report generated |
| H5–6 | Feature freeze → clean run → record the demo |

**If behind, cut in this order:** Critic → Predictor part of ① → AI explanation part of ③ (keep the deterministic checks!) → Safety Officer.
**Never cut:** Strategist, Integrity checks, Remediation re-run. They're the story.
