# FantasticFour: AI-Driven Chaos Engineering for Cloud-Native Resilience

> Bosch Hackathon 2026. An AI system that decides **what to break** in a microservices app, breaks it **safely**, watches how the system responds, and reports **ranked weaknesses, fixes and a resilience score**.

---

## Contents
- [The problem](#the-problem)
- [How it works](#how-it-works)
- [Target application and dependency map](#target-application-and-dependency-map)
- [Safety controls](#safety-controls)
- [Setup](#setup)
- [Running experiments](#running-experiments)
- [Results so far](#results-so-far)
- [Repository layout](#repository-layout)
- [Team, tools and models](#team-tools-and-models)

---

## The problem

Modern apps are dozens of small services calling each other. When one fails, nobody knows in advance what else breaks, how users are affected, or how long recovery takes. Teams usually find out during a real outage.

**Chaos engineering** finds out first, by deliberately injecting controlled failures (a crashed service, a slow network, an overloaded CPU) and observing the result. Doing this by hand is slow and unfocused. Our system automates the whole loop: **choose → inject safely → observe → analyse → recommend fixes**.

---

## How it works

```mermaid
flowchart LR
    subgraph AI["AI agents (Mistral)"]
        CA[Cartographer<br/>maps services] --> ST[Strategist<br/>ranks experiments]
        ST --> SO[Safety Officer<br/>approves / shrinks]
        AN[Analyst<br/>findings + score]
    end
    SO -->|experiment JSON| OP[Operator<br/>inject.py]
    OP -->|Chaos Mesh resource| APP[Online Boutique<br/>on kind]
    LG[Locust shoppers] --> APP
    APP --> MON[monitor.py<br/>error rate, p95, health]
    MON --> GU[Guard<br/>guard.py]
    GU -->|breach → delete resource| OP
    MON --> AN
    GU --> EV[(runs/<br/>CSV + JSONL evidence)]
    EV --> AN
```

| Component | Role | Status |
|---|---|---|
| **Online Boutique** on kind | The system under test (11 microservices + Redis) | ✅ Running |
| **Chaos Mesh** | Executes faults declared as Kubernetes resources; deleting the resource reverts the fault | ✅ Installed, injection verified |
| **Locust load generator** | 20 simulated shoppers browsing, adding to cart and checking out | ✅ Running |
| `chaosmind/inject.py` (**Operator**) | Validates experiments, creates/reverts Chaos Mesh resources, confirms injection | ✅ |
| `chaosmind/monitor.py` | Real error rate, p95 latency, checkout success, unhealthy services, restarts | ✅ |
| `chaosmind/guard.py` (**kill switch**) | Preflight → inject → watch every 2 s → auto-revert on breach → confirm recovery | ✅ Verified live |
| AI agents: Cartographer, Strategist, Safety Officer, Observer, Analyst | Plan experiments from the dependency map, explain results, rank weaknesses, score resilience | 🚧 In progress |
| Dashboard | Live view of experiments and metrics | 🚧 Planned |

**Design rule:** the kill switch is **deterministic code, not an LLM**. AI agents may propose experiments and make them *safer*, but they can never loosen or bypass the guard.

---

## Target application and dependency map

[Google Online Boutique](https://github.com/GoogleCloudPlatform/microservices-demo) (Apache-2.0), release `v0.10.4`: an e-commerce demo with 10 business services in 5 languages, communicating over gRPC, plus Redis.

![Online Boutique dependency graph](docs/dependency-graph.webp)

Based on Google's architecture diagram and **checked against the deployment manifest**. Every `*_ADDR` environment variable is a service-to-service call, and all 17 edges match:

| Caller | Calls |
| :--- | :--- |
| loadgenerator | frontend |
| frontend | ad, recommendation, productcatalog, cart, shipping, currency, checkout |
| checkout | productcatalog, cart, shipping, currency, payment, email |
| recommendation | productcatalog |
| cart | redis-cart |

*Manual correction:* upstream `main` also gives `frontend` an optional `SHOPPING_ASSISTANT_SERVICE_ADDR`. It isn't in our deployed release, so it's excluded.

**What the map predicts:**
- `productcatalog` has the most callers, so it has the widest blast radius.
- `checkout` depends on 6 services, so it's the most fragile path.
- `redis-cart` is a single store behind `cart`, so it's a data-loss risk.
- `ad` and `recommendation` are optional, so they should degrade gracefully.

---

## Safety controls

Every experiment passes through layered safeguards. All of them have been **tested live** (evidence in [`KILLSWITCH_RESULTS.md`](KILLSWITCH_RESULTS.md)).

| Layer | What it does |
|---|---|
| **Validation** | Only known fault types; target must be a real deployment in namespace `online-boutique`; duration ≤ 120 s; latency ≤ 2000 ms |
| **Preflight** | Refuses to inject if the app is already unhealthy or another experiment is still active |
| **Confirmed injection** | Distinguishes "resource created" from "Chaos Mesh actually injected" |
| **Guard (kill switch)** | Polls every 2 s; reverts automatically when **error rate > 20%**, **p95 > 2000 ms** or **unhealthy services > 2** |
| **Recovery check** | After revert, waits until health and metrics are back within limits and records the recovery time |
| **Fail-safe duration** | Every fault carries Chaos Mesh's own `duration`, so it ends even if our guard process crashes (`kill -9` tested) |
| **Ctrl-C / errors** | Any interruption or error triggers revert in a `finally` block |
| **Scoped abort** | `python3 -m chaosmind.inject abort` removes all faults we own, and only those |
| **Tighten-only overrides** | Limits passed at runtime may only be made stricter |

---

## Setup

**Tested on:** Fedora Linux, rootless Podman, kind v0.33.0, Kubernetes v1.37, Chaos Mesh 2.8.4, Python 3.

### Prerequisites
- Linux with Podman (rootless) or Docker
- `kind`, `python3`, `curl`, `git`
- ~4 CPU cores and 8 GB RAM free

### 1. Clone
```bash
git clone https://github.com/Gotha8972/FantasticFour.git
cd FantasticFour
```

### 2. Install kubectl (checksum-verified; skip if you already have it)
```bash
bash scripts/install-kubectl.sh
```

### 3. Create the cluster and deploy Online Boutique
```bash
bash scripts/deploy-local.sh
```
Creates the kind cluster `online-boutique`, deploys the app into namespace `online-boutique`, waits for every service, and checks `/` and `/cart`. The project kubeconfig is written to `.runtime/kubeconfig`.
The storefront is at **http://localhost:8080**.

### 4. Install Chaos Mesh
```bash
bash scripts/install-chaos.sh
```
Network faults need these kernel modules on the host:
```bash
sudo modprobe -a ip_tables iptable_filter iptable_mangle ip_set ip_set_hash_ip xt_set sch_netem
```

### 5. Start traffic
```bash
bash scripts/load.sh start 20 2
```
That's 20 simulated shoppers, starting at 2 per second. Check that traffic is flowing:
```bash
bash scripts/load.sh measure 5 30
```

### 6. Check everything without breaking anything
```bash
python3 -m chaosmind.test_guard
```
```bash
python3 -m chaosmind.verify --dry-run
```

---

## Running experiments

### An experiment is a JSON file
```json
{"id": "test-delay", "fault": "network_delay", "target": "productcatalogservice",
 "params": {"latency": "500ms"}, "duration_s": 60,
 "hypothesis": "All pages slow down; nothing crashes"}
```
| Field | Allowed |
|---|---|
| `fault` | `pod_failure` (service unavailable), `network_delay` (added latency + jitter) |
| `target` | Any deployment name, e.g. `cartservice`, `productcatalogservice` |
| `duration_s` | 1–120 |
| `params` | `network_delay`: `latency`, `jitter` (ms, ≤ 2000) |

Samples are in [`experiments/`](experiments/).

### Run one experiment under the kill switch
```bash
python3 -m chaosmind.guard experiments/test-delay.json
```
Optionally tighten the limits for this run:
```bash
python3 -m chaosmind.guard experiments/test-down.json '{"max_unhealthy": 0}'
```
The guard prints each event and writes evidence to `runs/<id>-<timestamp>/`:

| Event | Meaning |
|---|---|
| `CREATED` → `INJECTED` | Resource accepted, then injection confirmed by Chaos Mesh |
| `BREACH` | A limit was crossed (metric, value, limit recorded) |
| `ENDED` | Planned duration finished without a breach |
| `REVERTED` → `HEALTHY` | Fault removed, then the app confirmed back to normal (`recovery_s`) |
| `REFUSED` / `NOT_RECOVERED` / `ERROR` | Preflight blocked it, recovery timed out, or something failed |

### Run the verification suites
Runs both sample experiments end to end:
```bash
python3 -m chaosmind.verify
```
Health trigger, guard-crash fail-safe and manual abort:
```bash
./tests/killswitch.sh
```
Redis cart-persistence check:
```bash
./tests/redis_finding.sh
```

### Stop everything
Remove all chaosmind faults:
```bash
python3 -m chaosmind.inject abort
```
Stop traffic:
```bash
bash scripts/load.sh stop
```
Open the Chaos Mesh dashboard at http://localhost:2333:
```bash
bash scripts/chaos.sh dashboard
```

### Optional: standalone customer simulator
`customer_simulator.py` runs scripted shopper journeys with per-request error tracing and Prometheus metrics. See [`CUSTOMER_SIMULATION.md`](CUSTOMER_SIMULATION.md).

---

## Results so far

**Steady-state baseline** (15 min, 20 shoppers, 181 samples, no faults; [details](BASELINE_STUDY.md)): **4.37 req/s, 0.05% errors (2 / 3,933), p50 ≈ 20 ms, p95 ≈ 78 ms (max 240 ms), checkout success 98.8%**, 0 unhealthy services, 0 restarts during the window.

Even with nothing broken, **2 of 168 checkouts failed with HTTP 500**. That's a background failure rate, so every experiment below is judged against the baseline, not against zero.

| Experiment | What happened | Kill switch | Recovery |
|---|---|---|---|
| 500 ms delay on `productcatalogservice` | p95 rose to 3,500 ms (peak 4,100 ms); no errors | Breach on **p95** at 7.8 s, reverted in 0.33 s | 14.8 s |
| `cartservice` unavailable | Error rate 35% (peak 100% in one window), p95 2,700 ms | Breach on **error rate** at 8.1 s, reverted in 0.38 s | 55.5 s |
| `adservice` unavailable | **0% errors**, the frontend degrades gracefully | Breach on **unhealthy service** at 9.2 s, reverted in 0.38 s | 36.1 s |
| Guard killed with `kill -9` mid-fault | Fault still ended via Chaos Mesh's duration | Fail-safe ✅ | — |
| Manual abort with 2 active faults | Both removed in 0.39 s | ✅ | — |
| `redis-cart` pod restarted | **Cart emptied (1 item → 0) with zero HTTP errors**: silent data loss | — | 4.9 s |

**Findings so far**

1. 🔴 **Silent cart data loss.** `redis-cart` runs as 1 replica on an `emptyDir` volume, so any restart wipes every cart while the site reports success. *Fix:* a PersistentVolumeClaim with Redis persistence (AOF), or replicated Redis.
2. 🟠 **Cart outage takes the shop down hard.** Losing `cartservice` drives error rate to 35–100% and takes ~55 s to recover. *Fix:* more replicas plus a PodDisruptionBudget; degrade the cart page instead of failing.
3. 🟡 **Catalog latency spreads everywhere.** 500 ms on one service pushes site-wide p95 to 3.5–4 s, consistent with it having the most callers. *Fix:* client-side timeouts and caching of catalog reads in the frontend.
4. 🟢 **Ads fail gracefully**, as the map predicted.

Full evidence: [`KILLSWITCH_RESULTS.md`](KILLSWITCH_RESULTS.md), [`PROJECT_HANDOFF.md`](PROJECT_HANDOFF.md) and the `runs/` directory.

---

## Repository layout

```
chaosmind/
  inject.py          Operator: validate, create, confirm, revert, abort Chaos Mesh faults
  guard.py           Kill switch: preflight, watch, auto-revert, recovery check
  monitor.py         Metrics: Locust stats + Kubernetes health → snapshot()
  runlog.py          CSV/JSONL evidence writer
  capture.py         Standalone metric and pod-log capture
  verify.py          End-to-end verification of sample experiments
  baseline_summary.py  Steady-state baseline → baseline.json
  test_guard.py      Offline behaviour tests (no cluster needed)
experiments/         Experiment definitions (JSON)
scripts/             Cluster, Chaos Mesh and load setup
tests/               Live kill-switch and Redis checks
runs/                Evidence from every run
docs/                Diagrams
customer_simulator.py  Optional scripted shopper with Prometheus metrics
```

---

## Team, tools and models

**Team FantasticFour**

| Member | Area |
|---|---|
| aashrith | Platform: cluster, Chaos Mesh, monitoring, verification |
| Gotha8972 | Customer simulation |
| Srinavith Srinath | Fault injection and kill switch |
| *(name)* | AI agents |

**Third-party software:** Online Boutique v0.10.4 (Apache-2.0), kind, Podman, Kubernetes, Chaos Mesh 2.8.4, Helm 3.19, Locust (bundled load generator), Python `requests` and `prometheus_client` (simulator only).

**AI models:** Mistral (agents, in progress).

**Data:** synthetic only. Simulated shoppers and the app's built-in demo products; no real user data.
