# Team guide: read this first (everyone, ≈15 min)

This explains how the whole system works, the vocabulary, and the rules every piece of code follows. Your personal guide builds on it:
[Aashrith](GUIDE_AASHRITH.md) · [Harshil](GUIDE_HARSHIL.md) · [Srinavith](GUIDE_SRINAVITH.md) · [Smrithi](GUIDE_SMRITHI.md)

---

## 1. The problem in one paragraph
Online Boutique is a shop made of **11 microservices** (small programs) that call each other over the network. If one breaks, others can break too, and nobody knows in advance how badly. **Chaos engineering** means breaking things *on purpose, in a controlled way*, to find weaknesses before real outages do. Bosch wants an **AI** that decides **what** to break, breaks it **safely**, watches the effect, and reports **ranked weaknesses, fixes and a resilience score**.

## 2. Vocabulary (use these words in the demo)
| Term | Meaning |
|---|---|
| **Pod** | One running copy of a service. Kubernetes restarts or replaces pods automatically |
| **Deployment** | The Kubernetes object that says "run N pods of this service". `replicas` = N |
| **Namespace** | A folder inside the cluster. Ours is `online-boutique`; we never touch anything outside it |
| **kind** | "Kubernetes in Docker/Podman": a whole cluster on one laptop |
| **Chaos Mesh** | The tool that actually breaks things. We give it a **resource** (YAML/JSON) such as `NetworkChaos`, and it injects the fault. Deleting the resource undoes it |
| **Fault / experiment** | One controlled breakage: what, where, how hard, how long |
| **Locust** | The load generator: 20 (or 100) fake shoppers clicking around the shop |
| **Error rate** | Failed requests ÷ all requests in the last few seconds. Normal ≈ 0.05% |
| **p95 latency** | 95% of requests finish faster than this. Normal ≈ 35–78 ms |
| **Baseline** | Measured "normal" behaviour with nothing broken (`baseline.json`) |
| **Guard / kill switch** | Our code that watches metrics every 2 s and **reverts** the fault when a **threshold** is **breached** |
| **Threshold** | Current limits: error rate > **5%**, p95 > **1,000 ms**, or > **2** unhealthy services |
| **Blast radius** | Which other services get hurt when one service breaks |
| **Recovery time** | Seconds from revert until metrics are normal again |
| **Silent failure** | The site says "OK" (HTTP 200) but something is wrong, e.g. a cart that got emptied |

## 3. How a single experiment flows

```
experiments/x.json ──► guard.run() ──► inject.py ──► Chaos Mesh ──► the shop gets hurt
                           │                                              │
                           │◄────── monitor.snapshot() every 2 s ◄────────┘  (Locust stats + pod health)
                           │
                           └─ breach? → inject.revert() → wait for HEALTHY → save runs/<id>-<time>/
```

Try it (on the cluster laptop):
```bash
python3 -m chaosmind.guard experiments/test-delay.json
```
Each line printed is an **event**: `SNAPSHOT` (a metrics reading), `CREATED`, `INJECTED`, `BREACH`, `REVERTED`, `HEALTHY`. They're saved in `runs/<id>-<time>/events.jsonl`, one JSON object per line. Open one now so you know the format:
```bash
head -3 runs/test-down-20261010T062320.861245Z/events.jsonl
```
A `SNAPSHOT` event has: `stage` (`preflight` = before, `injecting`/`injected` = during, `recovery` = after), `error_rate`, `p95_ms`, `rps`, `requests`, `failures`, `checkout_success`, `unhealthy_services` (a list), `restarts` (per service).

## 4. How the AI agents fit in

```
② Cartographer ─► ① Strategist ─► ④ Safety Checker ─► guard.run() ─► Chaos Mesh
 (find weak spots)  (plan + predict)  (approve + ramp)    (code, safe)
                          ▲                                    │
                          │                                    ▼
                  re-plan ◄── verdict ◄── ③ Observer + Integrity checks + ⑥ Log Detective
                                                               │
                                               ⑤ Remediation (fix + re-run) ─► ⑦ Documentor (FINDINGS.md)
```

| # | Agent | File | Owner | Status |
|---|---|---|---|---|
| ② | Cartographer (vulnerability auditor) | `chaosmind/agents/cartographer.py` | Smrithi | ✅ built, offline-tested |
| ① | Strategist | `chaosmind/agents/strategist.py` | Smrithi | ✅ built, offline-tested |
| ④ | Safety Checker | `chaosmind/agents/safety.py` | Srinavith | ✅ built, offline-tested |
| ③ | Observer | `chaosmind/agents/observer.py` | Aashrith | 🚧 to build |
| ⑥ | Log Detective | `chaosmind/agents/log_detective.py` | Aashrith | 🚧 to build |
| ⑤ | Remediation | `chaosmind/agents/remediation.py` | Srinavith | 🚧 to build |
| ⑦ | Documentor + score + integrity checks | `chaosmind/agents/{documentor,score,integrity}.py` | Harshil | 🚧 to build |
| — | Orchestrator (the loop) | `chaosmind/agents/__main__.py` | Smrithi | ✅ first 3 agents wired; add the rest |

## 5. The ONE pattern every agent follows
**Code gathers facts → the AI reasons and returns JSON → code checks the JSON → code acts.**
Look at `chaosmind/agents/cartographer.py`. It's the template:
1. `facts.collect()` reads the real config (plain code, no AI).
2. `llm.ask(SYSTEM, facts)` sends a prompt and gets back a **dict** (Mistral in JSON mode).
3. `verify(reply, facts)` throws away anything the AI claimed that doesn't match the real facts.

**Why:** AI models sometimes invent things ("hallucinate"). An agent's output is never trusted directly. **No agent ever runs `kubectl` or touches the cluster.** Only `inject.py`, `guard.py` and small allow-listed code paths do.

The shared AI client:
```python
from chaosmind.agents import llm
reply = llm.ask(system_prompt, user_data_dict_or_text, model='large')   # returns a dict
```
- Key: `MISTRAL_API_KEY` in your environment or in `.env` (git-ignored, never commit it).
- Models default to `mistral-small-latest`. Use `MISTRAL_LARGE=mistral-large-latest` for better reasoning.

**Writing a good prompt (the SYSTEM text):**
1. Say the role ("You are a senior SRE…").
2. Give exact rules ("Use ONLY the facts given", "at most 8 items").
3. Show the exact JSON shape you want back, with an example.
4. Tell it what to do when unsure (e.g. return an empty list, don't guess).

## 6. Testing without the cluster or an API key
Every agent must be testable **offline**, using saved files in `runs/` and a **fake AI reply**:
```python
from unittest.mock import patch
from chaosmind.agents import llm
with patch.object(llm, 'ask', return_value={'whatever': 'the AI would say'}):
    result = my_agent.run(...)
assert result[...] == ...
```
See `chaosmind/agents/test_agents.py` for 7 real examples. Run all tests:
```bash
python3 -m chaosmind.test_guard && python3 -m unittest chaosmind.agents.test_agents chaosmind.test_c_tests
```

## 7. Git rules (important, we've lost work before)
```bash
git pull
```
- **Pull before you start and before you push.** Commit small and often, with a clear message.
- Add your own files by name (`git add chaosmind/agents/observer.py`). Avoid `git add -A` unless you've checked `git status`.
- **Never** commit `.env`, `.runtime/` or `microservices-demo/`.
- **Never** use `scripts/push-next-steps.sh`: it overwrites other people's README changes.
- `runs/` is ignored on some machines, so use `git add -f runs/<folder>` to publish evidence.
- Only Aashrith's laptop has the cluster. Everyone else builds and tests offline, then Aashrith runs it live.

## 8. Day 2 timeline (everyone)
| Time | Milestone |
|---|---|
| H0–1 | Aashrith: AI dry run works with the real key. Everyone: read your guide, start building offline |
| H1–3 | Each new agent works offline on saved `runs/` data, with tests |
| H3–4 | **Integration:** Smrithi wires every agent into the loop. One full live run on Aashrith's laptop |
| H4–5 | Redis fix before/after; FINDINGS.md generated; resilience scores |
| H5–6 | **Feature freeze** → clean run → record the ≤3-min demo → submit 30 min early |

**Day 2 deliverables (from the brief):**
1. Repo + README
2. Demo video ≤ 3 min
3. One-page architecture overview
4. Findings report
5. Team form (names, tools, AI models, libraries)
