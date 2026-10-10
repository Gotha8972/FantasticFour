# Presentation plan

**One-line pitch:** *"Monitoring said everything was fine, while carts were being wiped. Our AI finds weaknesses like that before customers do, breaks things safely to prove them, and proves its own fixes."*

**Story arc:** problem → how our AI thinks → it breaks things *safely* → it catches what monitoring misses → it fixes and proves the fix → why you can trust it.

---

## 1. Demo video (deliverable #2, ≤ 3:00)
**Rule:** never run live while recording. Cut from screen recordings made beforehand.

| Time | Shot (screen) | Voice-over | Speaker |
|---|---|---|---|
| 0:00–0:15 | Shop running + Grafana steady | "11 microservices, 20 shoppers. When one service fails, what else breaks? Nobody knows until it happens." | Srinavith |
| 0:15–0:40 | Terminal: Cartographer output (8 ranked vulnerabilities) | "Our AI audits the live architecture first. Every fact it cites is checked against the real config; across our runs it made **zero** unverifiable claims." | Smrithi |
| 0:40–1:05 | Strategist plan + Safety Checker decision | "It writes a hypothesis and pass/fail criteria *before* breaking anything. A Safety Checker can only make experiments smaller, never bigger." | Smrithi |
| 1:05–1:40 | Grafana: p95 spikes → guard log `BREACH` → `REVERTED` → recovery (from `grafana-stress.sh`) | "Here we slow the product catalog. Latency spikes to 4.3 s; within seconds the kill switch trips, and the fault is gone 0.3 s later. We ran it twice: same numbers." | Aashrith |
| 1:40–2:15 | Redis test: cart 1 → 0, error panel flat at 0% | "Now the scary one: restart Redis, and every cart is wiped. Zero errors, so monitoring sees nothing. Our integrity check caught it." | Harshil |
| 2:15–2:40 | `redis-fix.sh apply` → same test → cart 1 → 1 | "The fix: persistent storage plus Redis append-only logging. Same experiment, cart survives. Fix proven, not just recommended." | Srinavith |
| 2:40–3:00 | ARCHITECTURE.md diagram + safety table | "AI decides, code verifies, the kill switch always wins. FantasticFour." | Srinavith |

### Shot list: record these first (owner: Aashrith, with Harshil editing)
1. `bash scripts/grafana-stress.sh` with Grafana and the terminal side by side.
2. `.venv/bin/python -m chaosmind.graph --dry-run` (or the live `--budget 2` run if time allows). Terminal only, readable font size.
3. Redis before: `bash scripts/redis-fix.sh revert` → `./tests/redis_finding.sh` (cart 1 → 0), with Grafana's error panel visible.
4. Redis after: `bash scripts/redis-fix.sh apply` → `./tests/redis_finding.sh` (cart 1 → 1).
5. A slow scroll of the README highlights and the architecture diagram.

Use real numbers from the recordings. If a number differs from this script, **say the recorded one**.

---

## 2. Live pitch (if there's a stage slot): 9 slides, ~5 min
| # | Slide headline | Visual | Key talking points |
|---|---|---|---|
| 1 | **"Monitoring said fine. Carts were gone."** | Cart 1 → 0 next to a 0% error graph | Hook with the silent failure |
| 2 | The problem | Dependency map | 11 services; failure spreads unpredictably; manual chaos is slow and unfocused |
| 3 | How our AI thinks | 6-step loop (audit → hypothesise → inject → judge → fix → report) | Hypotheses and criteria are written *before* each run; code decides the verdict |
| 4 | Breaking things safely | Guard timeline: breach detected at 9.6 s → fault removed 0.3 s later → healthy at 14 s | 9 safety layers; fail-safe even if our own guard crashes; AI can't loosen limits |
| 5 | What we found | Findings 1–4 with icons | Silent data loss; cart outage; "healthy ≠ recovered" (3 s vs 34 s); latency spreads everywhere |
| 6 | Fix → proof | Before/after table: cart 1 → 0 vs 1 → 1 | Fixes come from a reviewed catalog; re-run the identical experiment; keep only if the score improves |
| 7 | Why trust it | "AI proposes → code verifies → guard wins" | 0 unverifiable claims; tests for every safety rule; every number in reports fact-checked |
| 8 | Measured, not guessed | "Customers hurt in X/5 kills with 1 replica vs Y/5 with 2" + 95% interval | Repeated trials → failure frequency with uncertainty; invalid runs never count as passes |
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
| *Is the resilience score meaningful?* | It's plain, documented code: error, latency, recovery and integrity penalties relative to the baseline. A silent data-loss case can never score well. |
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
