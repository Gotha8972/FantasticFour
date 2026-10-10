# Day 2 plan: what's left, who does it

## Orchestration decision: LangGraph
We compared the plain loop, LangGraph and Google ADK, and chose **LangGraph**:
- **Most agnostic:** nodes are plain Python calling our own `llm.py` (NVIDIA NIM, gpt-oss-20b), with no LangChain.
- **It matches our design:** a code-routed state machine with loops and branches. ADK is built around model-driven tool calling and Gemini, the opposite of "AI proposes, code acts".
- **Two real features we'd otherwise hand-build:** a **human approval gate** before any fix touches the cluster, and **checkpoint/resume** for 15–25 min live runs.
- **The diagram is the code** (`--draw`), which looks better in front of judges than a hand-drawn picture.

All of Aashrith's ADK workflow ideas are kept: thresholds up front, matching baselines, split recovery timings, repeated trials with a confidence interval, and stopping on failed cleanup. The design doc stays in [docs/adk/](../adk/README.md).

**Setup on the cluster laptop (once):**
```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```
```bash
.venv/bin/python -m unittest chaosmind.test_graph
```

## ▶ Current: [MODEL_AND_IMPLEMENTATION.md](MODEL_AND_IMPLEMENTATION.md): our implementation only, NVIDIA-hosted gpt-oss-20b, final run steps

## Two agent implementations → bake-off (done)
Aashrith is building his own LangGraph/LangChain agents. Both get dry-run 3× and scored with the same script; the better one becomes the official system. See **[AGENT_BAKEOFF.md](AGENT_BAKEOFF.md)**.

## Day-2 milestones (from the brief) → status
| Milestone | Status | Remaining action |
|---|---|---|
| AI experiment planner | ✅ Built, dry-run twice live | — |
| ≥ 3 failure types run, errors/slowdowns/recovery recorded | ✅ Delay, pod failure, pod kill run live; the AI's two live runs used pod failure and pod kill | — |
| Analysis and scoring | ✅ AI reports for both live runs, [scoreboard](../evidence/SCOREBOARD.md) regenerated from raw evidence, consolidated [FINDINGS.md](../../FINDINGS.md) | Regenerate the two AI reports with the improved Analyst (see [RERUN_020B817.md](RERUN_020B817.md)) |
| Feature freeze + clean run | ✅ **Frozen** (one entry point: `chaosmind.graph`) | Clean install from scratch on a second laptop, recorded (Smrithi) |
| Demo video + docs | Plan ready ([PRESENTATION_PLAN.md](PRESENTATION_PLAN.md)); [architecture](../ARCHITECTURE.md) ✅ | Record + edit |
| Submission | [Team form](../TEAM_FORM.md) ✅ | Submit 30 min early |

## Runs to do on Aashrith's laptop (in this order)
`git pull` first. Shoppers on (`bash scripts/load.sh start 20 2`), Grafana open, **screen recording on**.

1. **Push your local evidence:** the 2-replica catalog kill (`runs/manual-pod-kill-cb0c01b36a-*`: 146 requests, 0 failures). It's our strongest "fix works" result after Redis.
   ```bash
   git add -f runs/manual-pod-kill-* && git commit -m "2-replica catalog pod kill" && git push
   ```
2. **The probability experiment (your proposal's milestone):** catalog pod kill, 1 replica vs 2 replicas, 5 trials each:
   ```bash
   python3 -m chaosmind.agents.trials run experiments/catalog-podkill.json --repeat 5
   ```
   Then apply 2 replicas:
   ```bash
   kubectl --kubeconfig .runtime/kubeconfig --context kind-online-boutique -n online-boutique patch deployment productcatalogservice --type=json --patch-file remediation/replicas-2.json
   ```
   Repeat the same trials, then compare:
   ```bash
   python3 -m chaosmind.agents.trials summary
   ```
   **Pitch line (measured):** "With 1 replica, customers were hurt in **5 of 5** kills; with 2 replicas, in **0 of 5**. The 95% intervals don't overlap."
3. **The AI-driven live run (≥ 3 fault types, chosen by the AI):** this is the core Day-2 milestone.
   ```bash
   .venv/bin/python -m chaosmind.graph --budget 3 --remediate
   ```
   ~15–25 min. It produces `runs/agents-*/FINDINGS.md`. Push the folder.
4. **Verify the remaining fault types once each** and add the passing ones to `LIVE_VERIFIED` in `chaosmind/inject.py`: `catalog-loss`, `cart-redis-partition`, `redis-cpu`, `redis-disk-full` ([A_REDIS_FIX_AND_FAULTS.md](A_REDIS_FIX_AND_FAULTS.md)).
5. **Video shots:** see the shot list in [PRESENTATION_PLAN.md](PRESENTATION_PLAN.md).

## Who does what (Day 2)
| Person | Tasks |
|---|---|
| **Aashrith** | Runs 1–5 above; push after each |
| **Srinavith** | Review each pushed run; update README/FINDINGS numbers; Remediation story; narration |
| **Harshil** | Validate integrity checks live ([GUIDE_HARSHIL](GUIDE_HARSHIL.md)); edit the demo video from the recordings |
| **Smrithi** | Review the AI output from run 3 and tune prompts; architecture slide; 8-slide pitch deck |

## Timeline
| Time | Milestone |
|---|---|
| H0–1 | Runs 1–2 (evidence + probability trials) |
| H1–2 | Run 3: AI live loop, recorded |
| H2–3 | Run 4 (faults); README/FINDINGS updated with the real numbers |
| H3–4 | Video recorded and edited; slides |
| H4–5 | **Feature freeze**, clean test run, final README check |
| H5 | Submit (30 min early) |
