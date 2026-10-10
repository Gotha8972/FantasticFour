# Day 2 plan: what's left, who does it

## Decision on Aashrith's ADK proposal ([docs/adk/README.md](../adk/README.md))
**We adopt its ideas now and keep our plain-Python loop. No framework migration today.** Why:
- Our loop already does what ADK's workflow agents would orchestrate (sequential stages + a bounded re-plan loop).
- Migrating mid-final means a new dependency, re-plumbing 5 agents and re-testing. ADK is built around Gemini, and we've standardised on OpenAI.
- Every idea in the proposal that earns points is now implemented without it:

| ADK proposal idea | Status |
|---|---|
| Customer thresholds defined before testing | ✅ `trials.CUSTOMER_CRITERIA` + Strategist criteria written before each run |
| Baseline at the same traffic level | ✅ The loop warns when current shoppers ≠ baseline shoppers; 100-shopper reference added |
| Separate recovery timings (service ready vs customers recovered) | ✅ `safety.observed()` now returns `service_ready_s` and `customer_recovered_s` |
| Repeated trials → failure frequency with uncertainty | ✅ **New `chaosmind/agents/trials.py`**: X of N breaches + 95% Wilson interval; invalid runs kept, never counted as passes |
| Stop when cleanup/recovery fails | ✅ The loop stops on `NOT_RECOVERED` / `REVERT_FAILED` / `INTERRUPTED` |
| Narrow tools, no shell for agents | ✅ Already the design: agents return JSON only |

ADK stays in [docs/adk/](../adk/README.md) as our **"next step / productionisation"** story for the pitch.

## Day-2 milestones (from the brief) → status
| Milestone | Status | Remaining action |
|---|---|---|
| AI experiment planner | ✅ Built, dry-run twice live | — |
| ≥ 3 failure types run, errors/slowdowns/recovery recorded | ✅ Delay, pod failure, pod kill run live | **AI-driven live run** (below) so the AI itself runs ≥ 3 types |
| Analysis and scoring | ✅ Analyst, score, [FINDINGS.md](../../FINDINGS.md) | Regenerate after the live run |
| Feature freeze + clean run | — | H5 |
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
   **Target line for the pitch:** "With 1 replica, customers were hurt in X of 5 kills; with 2 replicas, in Y of 5."
3. **The AI-driven live run (≥ 3 fault types, chosen by the AI):** this is the core Day-2 milestone.
   ```bash
   python3 -m chaosmind.agents --budget 3 --remediate
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
