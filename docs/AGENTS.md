# The agents: what each one does and how it's kept honest

Back to the [README](../README.md) · one-page view: [ARCHITECTURE.md](ARCHITECTURE.md)

Every agent follows one pattern: **code gathers facts → the AI reasons and returns JSON → code verifies → code acts.**
No agent runs `kubectl` or touches the cluster. All live actions go through `inject.py` / `guard.py` or a reviewed allow-list.
Model: NVIDIA-hosted `openai/gpt-oss-20b` (open weights; 21B total, 3.6B active) via `chaosmind/agents/llm.py` (NVIDIA's OpenAI-compatible API; system prompt folded into the user turn, JSON extracted from the reply, one corrective retry). Swap with `NIM_MODEL`.

| Agent | File | AI decides | Code guarantees |
|---|---|---|---|
| **Cartographer** (vulnerability auditor) | `agents/cartographer.py` (+ `facts.py`) | Which combinations of config facts are dangerous; severity; a testable hypothesis | Facts are read from the live config (call graph, replicas, probes, storage, risk score). **Every cited fact is checked against the real config; claims that don't match are dropped** |
| **Strategist** | `agents/strategist.py` | Which experiment proves each vulnerability; predicted blast radius; pass/fail **criteria written before the run**; re-ranking after results | Experiments pass `inject.validate()`; criteria thresholds raised above baseline noise (error rate ≥ max(5× baseline, 1%), p95 ≥ 5× baseline); no repeats; only fault types proven live (unless `--allow-unverified`); target must match the cited vulnerability; Redis needs an integrity criterion; no data-loss prediction for services with a persistent volume; dropped proposals and one-fault-type plans go back to the model once with code's reasons, and corrected proposals are added; **experiments are ranked by code as blast radius × criticality** (services that break with the target × severity), the model's reason explains each; **the verdict (confirmed/refuted) is computed by code**, never by the AI |
| **Safety Checker** | `agents/safety.py` | Approve / shrink / reject; the intensity ramp | **Can only make experiments smaller** (same fault and target, ≤ duration, ≤ intensity); ramp ≤ 4 steps, each ≤ 2× the previous; every step runs through `guard.run()`; stops at the first guard trip and reports `tolerated_up_to` / `limit_crossed_at` |
| **Remediation** | `agents/remediation.py` | Which **reviewed fix from `remediation/catalog.json`** addresses the confirmed weakness (or none) | Only catalogued fixes for that exact target; server-side dry run before applying; **re-runs the identical experiment**; automatic rollback if the score gets worse |
| **Analyst** | `agents/analyst.py` | Root cause and explanation per experiment; severity ordering; summary | All numbers computed by code (before/during/after phases, scores, verdicts); log quotes must be real captured lines (others dropped); every number in the report is **fact-checked** against the measured data |

**Plain-code components** (no AI on purpose):

| Component | File | Purpose |
|---|---|---|
| Integrity checks | `agents/integrity.py` | Catch silent failures: the cart keeps its items across the fault, and checkout really produces an order (HTTP 200 alone isn't trusted) |
| Resilience score | `agents/score.py` | `100 − errors (≤ 40, square-root scale) − latency (≤ 25, square-root scale) − recovery (≤ 15) − blast radius (≤ 10, only when customers were hurt) − integrity (40)`, relative to the baseline |
| Scoreboard | `agents/scoreboard.py` | Recomputes every published score from the raw evidence, ranks worst first, and lists before/after-fix pairs ([SCOREBOARD.md](evidence/SCOREBOARD.md)) |
| Workflow | `chaosmind/graph.py` (LangGraph) · `agents/steps.py` · fallback `agents/__main__.py` | audit → plan → [execute → judge → optional fix (human-approved) → re-plan] → Analyst. Diagram: [WORKFLOW.md](WORKFLOW.md). The fallback runs the same steps without LangGraph |
| Injector + kill switch | `inject.py`, `guard.py` | Validation, Chaos Mesh resources, 2-second polling, auto-revert, recovery confirmation |

**Fault types** (`inject.py`): `pod_failure`, `pod_kill`, `network_delay`, `network_loss`, `network_partition`, `cpu_stress`, `disk_full`. Proven live so far: `pod_failure`, `network_delay` (`inject.LIVE_VERIFIED`). Add each one there after its first successful live guarded run.

**Run it:** see [RUNNING.md](RUNNING.md#let-the-agents-choose-and-run-experiments).
**Tests:**
```bash
python3 -m unittest chaosmind.agents.test_agents chaosmind.agents.test_day2
```
14 offline tests: fake AI replies, real saved cluster data and run evidence.
