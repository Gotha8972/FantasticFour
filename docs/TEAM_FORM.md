# Team form

Ready to copy into the submission portal, field by field.

**Team name**
FantasticFour

**Problem statement**
AI-Driven Chaos Engineering for Cloud-Native Resilience

**Project name**
ChaosMind

**One-line description**
An AI that finds weak spots in a Kubernetes application, breaks them safely behind a deterministic kill switch, catches failures that monitoring misses, and proves its fixes by running the same experiment again.

**Repository**
https://github.com/Gotha8972/FantasticFour

**Demo video**
VIDEO LINK HERE

**Team members and roles**

| Name | Role |
|---|---|
| Aashrith | Platform: kind and Podman cluster, Chaos Mesh, Prometheus and Grafana, baselines, live verification runs |
| Srinavith | Fault injection and kill switch, AI agents, integrity checks, resilience score, mission control UI |
| Harshil | Customer simulator, integrity-check validation, demo video |
| Smrithi | Prompt tuning, architecture overview, reproducible setup |

**Sample application**
Google Online Boutique v0.10.4 (https://github.com/GoogleCloudPlatform/microservices-demo, Apache-2.0): 10 services and Redis, run locally on kind.

**AI model**
`openai/gpt-oss-20b`, an open-weight model (21B parameters in total, 3.6B active per token), hosted by NVIDIA and called through NVIDIA's OpenAI-compatible chat completions API. It powers five agents: Cartographer, Strategist, Safety Checker, Remediation and Analyst. Every AI output is checked by deterministic code before anything acts on it.

**Tools and platforms**
Kubernetes on kind v0.33 with rootless Podman (Fedora), Chaos Mesh 2.8.4, Helm 3.19, Locust (Online Boutique's load generator), kube-prometheus-stack 92.3.0 (Prometheus, Grafana, kube-state-metrics), Python 3.

**Libraries**
LangGraph 1.2 and langgraph-checkpoint-sqlite (workflow orchestration, human approval gate, checkpointing). The agents, kill switch, injector and web UI otherwise use only the Python standard library. The customer simulator uses `requests` and `prometheus_client`. Kubernetes is driven through `kubectl`.

**Data used**
Synthetic only: simulated shoppers and the application's built-in demo products. No personal or real customer data.

**Key results**
- 8 live AI runs, 27 experiments across 5 fault types: 24 hypotheses confirmed, 3 refuted, all decided by code against criteria written before each run.
- 11 fixes proposed by the AI, approved by a person and applied; all 11 scored higher when the identical experiment was repeated (56 points on average).
- Found silent data loss: restarting Redis empties every cart while every page still answers HTTP 200. Fixed and proven by repeating the experiment.
- Repeated trials: a catalog pod kill hurt customers in 5 of 5 trials with one replica and 0 of 5 with two.
- Kill switch proven live on all triggers; it reverts a fault 0.3 seconds after a breach and refused to inject when the system already looked unhealthy.
