# Presentation plan

**One-line pitch:** *"Monitoring said everything was fine, while carts were being wiped. Our AI finds weaknesses like that before customers do, breaks things safely to prove them, and proves its own fixes."*

**Story arc:** problem → how our AI thinks → it breaks things *safely* → it catches what monitoring misses → it fixes and proves the fix → why you can trust it.

---

## 1. Demo video (deliverable #2, ≤ 3:00)
**Rules:** never run live while recording. A live experiment takes 4–6 minutes, so **cut from the recorded AI runs** (`runs/agents-20261010T185909Z`, `runs/agents-20261010T192511Z`) and speed up the waiting. **The AI carries the story, shown in the mission-control UI** (`python3 -m chaosmind.ui`); the scripted tests appear only as supporting evidence.

| Time | Shot (screen) | Voice-over | Speaker |
|---|---|---|---|
| 0:00–0:15 | Shop + Grafana steady | "11 microservices, 20 shoppers. When one fails, what else breaks? Nobody knows until it happens." | Srinavith |
| 0:15–0:40 | **AI audit + plan**: vulnerabilities, then experiments ranked by blast radius × criticality, with criteria | "Our AI audits the live architecture, every cited fact checked against the real config. It ranks experiments by blast radius times criticality and writes pass/fail criteria *before* breaking anything." | Smrithi |
| 0:40–0:55 | **Safety Checker** shrinking the risky checkout test to 500 ms / 30 s | "A Safety Checker can only make experiments smaller, and code enforces hard limits whatever the model says." | Smrithi |
| 0:55–1:25 | **AI's Redis kill** → kill switch → `integrity violations=1` → **confirmed** | "The AI kills Redis. Pages still load, but the cart is gone, and nothing reports it. Our integrity check does." | Harshil |
| 1:25–1:55 | **Approval banner in the UI** → click *Approve fix* → re-run → cart 1 → 1 | "The AI proposes a reviewed fix, a human approves it, and the identical experiment re-runs. The cart survives." | Aashrith |
| 1:55–2:20 | **Frontend: 100% errors → 0%**, score 18 → 96, hypothesis **refuted after the fix** | "And it can say no: after the fix, the same criteria are refuted. Four fixes, four better scores." | Aashrith |
| 2:20–2:40 | Scoreboard + trials table (5/5 vs 0/5) | "Measured, not guessed: one replica hurt customers 5 times in 5, two replicas never." | Srinavith |
| 2:40–3:00 | Architecture diagram | "Honest limit: the Redis fix stops data loss, but a restart is still slow with one replica. AI proposes, code verifies, the kill switch always wins." | Srinavith |

### Shot list (owner: Aashrith, editing: Harshil)
1. The terminal recordings of both live AI runs. If they weren't screen-recorded, re-run `.venv/bin/python -m chaosmind.graph --budget 2 --remediate` once with the recorder on, and cut the waiting.
2. The risky safety test: `python3 -m chaosmind.agents.safety experiments/risky-checkout.json --review-only`.
3. Grafana during one AI experiment (error panel + p95).
4. `docs/evidence/SCOREBOARD.md` and the trials table in the README, scrolled slowly.

Use the recorded numbers. If one differs from this script, **say the recorded one**.

---

## 2. Live pitch (if there's a stage slot): 9 slides, ~5 min
| # | Slide headline | Visual | Key talking points |
|---|---|---|---|
| 1 | **"Monitoring said fine. Carts were gone."** | Cart 1 → 0 next to a 0% error graph | Hook with the silent failure |
| 2 | The problem | Dependency map | 11 services; failure spreads unpredictably; manual chaos is slow and unfocused |
| 3 | How our AI thinks | 6-step loop (audit → hypothesise → inject → judge → fix → report) | Hypotheses and criteria are written *before* each run; code decides the verdict |
| 4 | Breaking things safely | Guard timeline: breach detected at 9.6 s → fault removed 0.3 s later → healthy at 14 s | 9 safety layers; fail-safe even if our own guard crashes; AI can't loosen limits |
| 5 | What we found | Findings 1–5 with icons | Silent data loss; frontend single point of failure (found by the AI); cart outage; "healthy ≠ recovered" (3 s vs 34 s); latency spreads everywhere |
| 6 | Fix → proof | 4 AI-loop fixes, each approved and re-run: frontend **18 → 96**, cart **31 → 78**, catalog **70 → 99**, Redis **13 → 50**; trials 29 → 100 | Fixes come from a reviewed catalog; re-run the identical experiment; keep only if the score improves |
| 7 | Why trust it | "AI proposes → code verifies → guard wins" | Cited facts checked against the live config; noise can't confirm a criterion; 2 hypotheses refuted after fixes; report claims the measurements contradict are flagged |
| 8 | Measured, not guessed | "Customers hurt in **5/5** kills with 1 replica vs **0/5** with 2" + 95% intervals (57–100% vs 0–43%, no overlap) | Repeated trials → failure frequency with uncertainty; invalid runs never count as passes |
| 9 | Impact + next | The LangGraph diagram (generated from the code) + resilience scores | Human approval gate before any fix; resumable runs; runs on any Kubernetes app; next: more fixes in the catalog, CI integration |

Speaking order: Srinavith (1–3) → Aashrith (4) → Harshil (5) → Srinavith (6) → Aashrith (8) → Smrithi (7, 9).

---

## 3. Q&A prep: likely judge questions
| Question | Answer |
|---|---|
| *What stops the AI from breaking production?* | Agents only return JSON; they never touch the cluster. Code validates every experiment (fault type, target, namespace, caps), the Safety Checker can only shrink experiments, and the guard reverts automatically. Even if the guard crashes, Chaos Mesh ends the fault on its own timer. |
| *How do you know the AI isn't hallucinating?* | Every fact the Cartographer cites is compared with the live config; mismatches are dropped (0 across our runs). Verdicts are computed by code against criteria written before the run. The Analyst can only quote real log lines, and every number in the report is fact-checked. |
| *Why not let the AI write fixes?* | Arbitrary patches to a cluster are risky. It chooses from a reviewed fix catalog, the change is dry-run on the API server first, and we keep it only if the re-run scores better; otherwise it's rolled back. |
| *How fast does the kill switch react?* | It polls every 2 s. A breach is detected ~8–10 s after injection, because it reads the load generator's rolling ~10 s window, and the fault is removed ~0.3 s later. Polling Prometheus directly would cut detection to a few seconds; that's our next step. |
| *Did the Redis fix actually help customers?* | It stopped the data loss, the critical part. It did **not** make a restart less disruptive: with one Redis replica, carts still error and slow down for seconds. That's the next fix (cartservice retries or a replicated Redis). |
| *Can your system ever refute a hypothesis?* | Yes, and it has. In the third live run the AI predicted a checkout pod kill would hurt customers; it didn't, so code **refuted** it. After the frontend and catalog fixes the same criteria were refuted too, and with the Redis fix in place the data-loss criterion failed. Thresholds are raised above baseline noise in code, so noise can't confirm anything. |
| *Is your kill switch perfect?* | No, and we found its blind spot with our own tool: a payment outage failed 2 of 5 checkouts while the overall error rate stayed under the 5% limit. The next step is a checkout-specific limit. |
| *Is the resilience score meaningful?* | It's plain, documented code: error, latency, recovery, blast-radius and integrity penalties relative to the baseline, exactly the factors in the brief. A silent data-loss case can never score well. Every score is regenerated from the raw evidence by one command, so nobody typed a number in. |
| *How are experiments ranked?* | By code, as the brief asks: blast radius (services that break with the target, from the generated dependency map) × criticality (severity). The AI writes the reason for each. |
| *Why Online Boutique? Everyone used it.* | Because it's realistic: 11 services, 5 languages, gRPC, a stateful store. What's different is what we found in it: silent data loss, and "healthy ≠ recovered". |
| *What was the hardest part?* | Proving things are *actually* safe and *actually* fixed, rather than looking fine on a dashboard. |
| *How did you choose your agent design?* | We built two independent implementations and ran 12 real dry runs on frozen, fingerprinted inputs, scored by one script: hallucinated facts, ranking quality, valid experiments, fault variety, safety. The current one won, and we ported the other's best ideas into it. |
| *Why LangGraph?* | Our workflow is a state machine where code decides every transition. LangGraph models exactly that, adds a human approval gate before fixes and checkpoint/resume, and stays model-agnostic: our nodes call any LLM through one small client. |
| *Does it work on other apps?* | Yes. The Cartographer reads any deployment's config and call graph from standard Kubernetes objects; faults are standard Chaos Mesh resources. |

---

## 4. Before presenting
- [ ] All 5 recordings captured, with real numbers noted
- [ ] Video ≤ 3:00, captions legible, audio clear
- [ ] README highlights match the numbers in the video
- [ ] One full rehearsal with a timer; each speaker knows their slide
- [ ] Laptop charged, Grafana logged in, the cluster up in case of a live question
- [ ] Team form submitted (names, tools, AI model, libraries, data)
