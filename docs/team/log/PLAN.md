# Bosch Hackathon — AI-Driven Chaos Engineering

> **Historical planning note.** The project later switched its AI provider from Mistral to OpenAI `gpt-5.6-luna`, and now to **NVIDIA-hosted `openai/gpt-oss-20b`**. See the [README](../../../README.md).

**Task:** an AI that picks what to break in a cloud-native app, breaks it safely, watches what happens, and reports weaknesses + fixes + a resilience score.
**Team:** 4 people. Out of scope: anything outside our own sandbox.

## Environment: local laptops
- Each teammate runs their own `kind` cluster (no stepping on each other's experiments). The demo runs on the strongest laptop (Linux), plugged in, with sleep off.
- Setup on Linux: `./setup/sandbox.sh` (installs Docker if missing, kind/kubectl/helm, then deploys everything). UIs on localhost via the printed `port-forward`s.
- Backup only: GitHub Codespaces via `.devcontainer/` (same script).
- Before submitting: a clean run from scratch on a second laptop, following only the README.

## Stack
- **Cluster:** `kind` (Kubernetes in Docker) on one strong laptop. That laptop is the "chaos box"; everyone else works through its kubeconfig or their own kind cluster.
- **App:** Google **Online Boutique** (`GoogleCloudPlatform/microservices-demo`, Apache-2.0). 11 microservices in 5 languages, using gRPC + Redis, with a **built-in load generator**. That gives us a rich dependency graph and realistic failure targets: checkout fans out to 6 services, the cart depends on Redis.
- **Fault injection:** **Chaos Mesh** (PodChaos, NetworkChaos, StressChaos, IOChaos, HTTPChaos). It's declarative, and deleting the CR reverts the fault, so it doubles as the rollback mechanism.
- **Metrics:** Prometheus (kube-prometheus-stack) + the load generator's own stats. Optionally Istio/Linkerd for per-edge latency, but only if setup is quick.
- **AI:** **Mistral** (`mistral-large-latest` for reasoning agents, `mistral-small-latest` for cheap/fast ones) via the `mistralai` Python SDK, with function calling + JSON mode. Multi-agent setup, see below.
- **Our code:** Python CLI `chaosmind/` + Streamlit dashboard.

## App: Online Boutique — https://github.com/GoogleCloudPlatform/microservices-demo
Deploy: `kind create cluster` then `kubectl apply -f release/kubernetes-manifests.yaml` (prebuilt images, no build needed). Open the UI with `kubectl port-forward svc/frontend 8080:80`.

Known dependency graph. It's the ground truth for checking the Cartographer's output:
```
loadgenerator ─► frontend ─┬─► adservice
                           ├─► recommendationservice ─► productcatalogservice
                           ├─► productcatalogservice
                           ├─► currencyservice
                           ├─► shippingservice
                           ├─► cartservice ─► redis-cart
                           └─► checkoutservice ─┬─► productcatalog, cart, currency, shipping
                                                ├─► paymentservice
                                                └─► emailservice
```
Hypotheses worth testing (good Strategist output to aim for):
- `productcatalogservice` has the biggest fan-in, so latency there should hit almost every page.
- `redis-cart` has 1 replica and no persistence, so killing it means the cart breaks and its data is lost.
- `checkoutservice` depends on 6 services, so a single slow dependency makes the whole checkout fail.
- `adservice` and `recommendationservice` aren't critical, so the frontend *should* degrade gracefully. Verify it.

## Multi-agent design
A plain Python orchestrator (no framework) passes one shared `state.json` (graph, baseline, experiments, results) between agents. Each agent = system prompt + its own tools + a JSON output schema.

| Agent | Model | Tools it can call | Output |
|---|---|---|---|
| **Cartographer** | small | `kubectl get svc/deploy`, read env vars, read manifests | dependency graph JSON (services, edges, criticality guess) |
| **Strategist** (planner) | large | read graph + baseline, list fault templates | ranked experiment list: target, fault, params, hypothesis, reason, expected blast radius |
| **Safety Officer** | large | read experiment, read thresholds | approve / reject / shrink params (e.g. 50% pods, 60s max) **before** anything runs |
| **Operator** (executor) | none — deterministic code | apply/delete Chaos Mesh CR | run log |
| **Observer** | small | query Prometheus, load-gen stats, pod events | per-experiment metrics: error %, p95 delta, recovery time, services affected |
| **Analyst** | large | read all results + graph | ranked weaknesses, root cause, fixes (YAML patches), resilience score |

**Hard rule:** the kill switch (`guard.py`) is **plain code, not an agent.** It polls Prometheus every 2s and deletes the CR when a threshold is breached, whatever any LLM says. Agents can only make experiments *safer* (the Safety Officer can veto), never loosen the guard. This is the line to say in the demo.

```
Cartographer ─► Strategist ─► Safety Officer ─(approved)─► Operator ─► Chaos Mesh
                     ▲                                        │
                     │                         guard.py ◄─────┤ (deterministic kill switch)
                     │                                        ▼
                 Analyst ◄──────────────────────────────── Observer ◄── Prometheus
                     │
                     └─► findings + score ─► (stretch) apply fix, re-run loop
```

## Who does what
| Person | Area | Day 1 | Day 2 |
|---|---|---|---|
| **A: Platform** | Cluster, app, Chaos Mesh, Prometheus | kind + Boutique + Chaos Mesh + Prometheus up; 1-command `make up` script | Clean-from-scratch runs; apply fixes (replicas, PDBs, timeouts, probes) for the re-run |
| **B: Mapping + monitoring** | Cartographer tools, `monitor.py` | Tools the Cartographer calls (k8s Services/env vars `*_SERVICE_ADDR`) + overrides file; baseline (error %, p50/p95, pod health, restarts) under steady load | Recovery-time measurement; metrics API for the dashboard |
| **C: Injection + safety** | `inject.py`, `guard.py` | Templates for pod-kill + network delay; guard polls every 2s and **auto-deletes the CR** on breach (error rate, p95, # unhealthy services, max duration) + `chaosmind abort` | Remaining fault types: loss, CPU/mem stress, Redis down, traffic spike (scale load generator), disk fill; combined failures |
| **D: Agents + docs** | `agents/`, orchestrator, dashboard | Mistral client + orchestrator + shared state; Cartographer and Strategist working on the real graph (dry run); start README + architecture slide | Safety Officer, Observer, Analyst; full loop end to end; Streamlit dashboard showing agent decisions live; demo video |

## Day 1: Milestone 1 (today)
| Time | Milestone |
|---|---|
| H0–1 | **A:** cluster + app running end to end (place an order in the UI). Others: repo skeleton, agree on the JSON contracts (graph, metrics snapshot, experiment spec) |
| H1–3 | **B:** dependency map rendered (Mermaid/graphviz). **C:** first pod-kill through Chaos Mesh. **D:** orchestrator + Cartographer producing the map, Strategist dry-run |
| H3–4 | **Baseline:** 5 min of steady load, saved as `baseline.json` |
| H4–5 | **First injection, observed:** kill `cartservice` or add 500 ms delay to `productcatalog`, and watch the error/latency spike |
| H5–6 | **Kill switch tested:** set a low threshold and show the CR being auto-deleted and the app recovering. Log it |
| End | **Checkpoint demo:** running app → map → safe failure → impact → automatic rollback |

**Day-1 done =** running app + dependency map + one safe failure with a working kill switch.

## Day 2: Milestone 2
- The Strategist agent ranks experiments by blast radius × criticality from the graph, with a reason for each. Run **≥3 failure types** and record errors, slowdowns and recovery time.
- The Analyst agent ranks weaknesses by severity, recommends fixes and gives a **resilience score** (0–100; formula: error %, p95 degradation, recovery time, blast radius).
- **Stretch, in priority order:** re-run after a fix to show the score improving (strongest demo moment) → live dashboard → combined failures (traffic spike + service down).
- Feature freeze, then a clean run from scratch, then the demo video (≤3 min), then submit 30 min early.

## Deliverables
- [ ] Repo + README (setup, how to run)
- [ ] Demo video ≤3 min (inject → impact → report)
- [ ] Architecture overview, 1 page (components, how the AI decides, safety controls)
- [ ] Findings report (ranked, with fixes)
- [ ] Team form (members, tools, AI models, libs: Online Boutique, Chaos Mesh, Prometheus, kind, Streamlit, Mistral API + `mistralai` SDK; models used)
