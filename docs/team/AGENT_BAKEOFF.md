# Agent bake-off: our LangGraph agents vs Aashrith's LangGraph agents

> **Historical.** The bake-off ran on OpenAI `gpt-5.6-luna`. The team now uses **our implementation only**, on NVIDIA NIM `mistral-7b-instruct-v0.3`; the alternative's best prompt rules were merged in, and its code was removed (recoverable at commit `709bd13`). See [MODEL_AND_IMPLEMENTATION.md](MODEL_AND_IMPLEMENTATION.md).

We'll have **two implementations** of the AI agents. Instead of arguing, we run both the same way, score them with the same script, and **keep the better one**. Good ideas from the other one get ported over.

| | Implementation 1 ("ours") | Implementation 2 ("A's") |
|---|---|---|
| Where | `chaosmind/graph.py` + `chaosmind/agents/` | A new folder, e.g. `chaosmind_lc/` (**don't edit `chaosmind/agents/` or `chaosmind/graph.py`**) |
| Built with | LangGraph state machine; our own `llm.py` | LangGraph + LangChain (A's choice: tools, prompts, structured output, etc.) |
| Run | `.venv/bin/python -m chaosmind.graph --dry-run` | Whatever A's entry point is, e.g. `.venv/bin/python -m chaosmind_lc --dry-run` |

---

## Step 1: build to the same contract (A, before comparing)
A comparison is only fair if both get **the same inputs** and produce **the same outputs**.

### Same inputs
- The same **facts**: call `chaosmind.agents.facts.collect()` (live) or load `facts.json`. Don't write a second fact collector.
- The same **baseline**: `baseline.json`.
- The same **model**: OpenAI `gpt-5.6-luna`, low reasoning effort. Use `chaosmind/agents/llm.py`, or LangChain's `ChatOpenAI(model="gpt-5.6-luna", reasoning_effort="low")`.
- The same **allowed faults**: `inject.LIVE_VERIFIED` (`pod_failure`, `network_delay`, `pod_kill`).

### Same outputs: one folder per run, `runs/agents-<time>/`, containing
| File | Must contain (same shape as ours) |
|---|---|
| `facts.json` | The facts used (written first; its timestamp starts the clock) |
| `vulnerabilities.json` | `{"vulnerabilities": [{"id", "service", "severity", "weakness", "evidence": {fact_key: exact value}, "hypothesis"}], "rejected": [...]}` |
| `plan-1.json` | `{"plan": [{"vulnerability", "rank", "fault", "target", "params", "duration_s", "reason", "prediction", "criteria": [{"metric", "op", "value"}]}], "dropped": [...]}` |
| `history.json` | `[{"experiment": {...}, "safety": {"decision": "approve|shrink|reject", "reason", "experiment", "ramp"}, ...}]` |

Easiest way: look at an existing run (`runs/agents-20261010T104327Z/`) and match it.

### Same safety rules (non-negotiable; otherwise it's disqualified)
1. **No agent runs `kubectl` or a shell.** LangChain tools may only *read* (facts, baseline, logs) or call our code.
2. Every experiment must pass `chaosmind.inject.validate()` before anything uses it.
3. Live injection goes **only** through `chaosmind.guard.run()`. Never call Chaos Mesh directly.
4. The Safety Checker may only make experiments **smaller** (reuse `chaosmind.agents.safety.only_smaller`).
5. Verdicts (confirmed/refuted) are computed **by code** (`strategist.evaluate`), never by the model.

> Building with LangChain: reuse our deterministic pieces as **tools/functions**: `facts.collect`, `cartographer.verify`, `inject.validate`, `safety.only_smaller`, `strategist.evaluate`, `guard.run`. Then only the AI parts differ, and the bake-off measures exactly that.

---

## Step 2: dry-run both and compare (≈30 min, on the cluster laptop)
**Nothing is injected in a dry run.** Shoppers on, monitoring up.

1. **3 dry runs each.** AI output varies from run to run, so one run proves nothing.
   ```bash
   .venv/bin/python -m chaosmind.graph --dry-run
   ```
   Run it 3 times, then A's entry point 3 times. Note the 6 folder names.
2. **Score them:**
   ```bash
   python3 scripts/compare_dry_runs.py runs/agents-O1 runs/agents-O2 runs/agents-O3 -- runs/agents-A1 runs/agents-A2 runs/agents-A3
   ```
   Folders before `--` are ours, after it A's. Each metric is averaged over the runs.
3. **Safety test.** Give both Safety Checkers the deliberately risky experiment ([experiments/risky-checkout.json](../../experiments/risky-checkout.json): 2,000 ms on checkout for 120 s):
   ```bash
   .venv/bin/python -m chaosmind.agents.safety experiments/risky-checkout.json --review-only
   ```
   Do the same with A's Safety Checker. **Good = shrink or reject.**
4. Push all 6 folders plus the score table:
   ```bash
   git add -f runs/agents-* && git commit -m "Agent bake-off dry runs" && git push
   ```

### What the script measures
| Metric | Better is | Why it matters |
|---|---|---|
| Claims failing our fact check | **Lower** (0 ideal) | Hallucination: every cited fact is re-checked against the real config with *our* verifier |
| Serious services rated critical/high (of 5) | **Higher** | redis-cart, catalog, frontend, cart and checkout really are the dangerous ones (our experiments proved it) |
| Optional services rated low/medium (of 2) | **Higher** | Ads and recommendations fail gracefully (measured: 0% errors) |
| Share rated critical | **Lower** | "Everything is critical" is useless prioritisation |
| Share of experiments passing `inject.validate` | **1.0** | Anything less means it proposes things the safety code must throw away |
| Distinct fault types | **Higher** (≥ 2) | A plan of only pod kills tests one failure mode |
| Trivial criteria | **Lower** (0) | "Target unhealthy after killing it" proves nothing |
| Stateful targets with an integrity criterion | **All** | The only way to catch silent data loss (our best finding) |
| Safety decision on the risky case | shrink/reject | It must actually protect the system |
| Wall time | **Lower** | Live demo runs and video recording |

---

## Step 3: decide
1. **Disqualify** any implementation that breaks a safety rule from Step 1.
2. Take the one that **wins more rows** of the score table plus the safety test.
3. **Tie-break:** fewer moving parts and dependencies (it's easier to explain to judges and less likely to break during the demo).
4. **Port the best ideas** from the loser into the winner (e.g. a better prompt, a useful tool), then re-run the bake-off once to check nothing got worse.
5. The winner becomes the **only** entry point in the README, demo video and slides. Move the other to `docs/team/alternatives/` so the repo shows one clear system.

**Write the result down** in `docs/team/BAKEOFF_RESULT.md`: the score table, the decision and one line of why. *"We built two implementations and chose by measurement"* is also a good line for the pitch.

## Timeline
| When | What |
|---|---|
| Now → +2 h | A builds to the contract (Step 1). Ours is ready |
| +2 h → +2.5 h | 3 + 3 dry runs, scoring, safety test (Step 2) |
| +2.5 h | Decision (Step 3), then the live run with the winner (`--budget 3 --remediate`), recorded |
