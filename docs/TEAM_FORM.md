# Team form (deliverable #5): copy into the submission portal

**Team name:** FantasticFour
**Repository:** https://github.com/Gotha8972/FantasticFour

**Members**

| Name | Role |
|---|---|
| Aashrith | Platform: kind/Podman cluster, Chaos Mesh, Prometheus/Grafana, baselines, live verification |
| Srinavith | Fault injection and kill switch; AI agents; integrity checks and resilience score |
| Harshil | Customer simulator, integrity validation, demo video |
| Smrithi | Prompt tuning, architecture overview, reproducible setup |

**Sample application:** Google Online Boutique v0.10.4, https://github.com/GoogleCloudPlatform/microservices-demo (Apache-2.0), run locally on kind.

**AI models:** OpenAI `gpt-5.6-luna` (chat completions API, JSON mode, low reasoning effort), used by the Cartographer, Strategist, Safety Checker, Remediation and Analyst agents. All AI output is validated by deterministic code before any action.

**Tools and platforms:** Kubernetes (kind v0.33, rootless Podman, Fedora), Chaos Mesh 2.8.4, Helm 3.19, Locust (Online Boutique's bundled load generator), kube-prometheus-stack 92.3.0 (Prometheus, Grafana, kube-state-metrics), Python 3.

**Third-party libraries:** the agents, guard and injector use only the Python standard library. The customer simulator uses `requests` and `prometheus_client`. Kubernetes is driven via `kubectl`.

**Data used:** synthetic only: Locust's simulated shoppers and the application's built-in demo products. No personal or real customer data.
