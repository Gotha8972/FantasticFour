# The agents: what each one does and how it's kept honest

Back to the [README](../README.md) · one-page view: [ARCHITECTURE.md](ARCHITECTURE.md)

Every agent follows one pattern: **code gathers facts → the AI reasons and returns JSON → code verifies → code acts.**
No agent runs `kubectl` or touches the cluster. All live actions go through `inject.py` / `guard.py` or a reviewed allow-list.
Model: OpenAI `gpt-5.6-luna` via `chaosmind/agents/llm.py` (JSON mode, configurable reasoning effort, invalid-JSON retry, and bounded rate-limit/server-error retries). Override with `OPENAI_MODEL`, `OPENAI_MODEL_LARGE`, or `OPENAI_REASONING_EFFORT`; settings are read from the environment, then the local `.env`. Explicit `AI_PROVIDER=mistral` selects the retained Mistral client. Keys stay local.

| Agent | File | AI decides | Code guarantees |
|---|---|---|---|
| **Cartographer** (vulnerability auditor) | `agents/cartographer.py` (+ `facts.py`) | Which combinations of config facts are dangerous; severity; a testable hypothesis | Facts are read from the live config (call graph, replicas, probes, storage, risk score). **Every cited fact is checked against the real config; claims that don't match are dropped** |
| **Strategist** | `agents/strategist.py` | Which experiment proves each vulnerability; predicted blast radius; pass/fail **criteria written before the run**; re-ranking after results | Experiments pass `inject.validate()`; no repeats; only fault types proven live (unless `--allow-unverified`); **the verdict (confirmed/refuted) is computed by code**, never by the AI |
| **Safety Checker** | `agents/safety.py` | Approve / shrink / reject; the intensity ramp | **Can only make experiments smaller** (same fault and target, ≤ duration, ≤ intensity); ramp ≤ 4 steps, each ≤ 2× the previous; every step runs through `guard.run()`; stops at the first guard trip and reports `tolerated_up_to` / `limit_crossed_at` |
| **Remediation** | `agents/remediation.py` | Which **reviewed fix from `remediation/catalog.json`** addresses the confirmed weakness (or none) | Only catalogued fixes for that exact target; server-side dry run before applying; **re-runs the identical experiment**; automatic rollback if the score gets worse |
| **Analyst** | `agents/analyst.py` | Root cause and explanation per experiment; severity ordering; summary | All numbers computed by code (before/during/after phases, scores, verdicts); log quotes must be real captured lines (others dropped); every number in the report is **fact-checked** against the measured data |

**Plain-code components** (no AI on purpose):

| Component | File | Purpose |
|---|---|---|
| Integrity checks | `agents/integrity.py` | Catch silent failures: the cart keeps its items across the fault, and checkout really produces an order (HTTP 200 alone isn't trusted) |
| Resilience score | `agents/score.py` | `100 − error impact − latency impact − recovery − integrity (40)`, relative to the baseline |
| Loop | `agents/__main__.py` | audit → plan → [integrity prep → Safety Checker → integrity verify → verdict → score → optional remediation → re-plan] → Analyst |
| Injector + kill switch | `inject.py`, `guard.py` | Validation, Chaos Mesh resources, 2-second polling, auto-revert, recovery confirmation |

**Fault types** (`inject.py`): `pod_failure`, `pod_kill`, `network_delay`, `network_loss`, `network_partition`, `cpu_stress`, `disk_full`. Proven live so far: `pod_failure`, `network_delay` (`inject.LIVE_VERIFIED`). Add each one there after its first successful live guarded run.

**Run it:** see [RUNNING.md](RUNNING.md#let-the-agents-choose-and-run-experiments).
**Tests:**
```bash
python3 -m unittest chaosmind.agents.test_agents chaosmind.agents.test_day2
```
14 offline tests: fake AI replies, real saved cluster data and run evidence.
