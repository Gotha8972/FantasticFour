# Running FantasticFour: setup, experiments, agents, dashboard

Back to the [README](../README.md).

## Setup

**Tested on:** Fedora Linux, rootless Podman, kind v0.33.0, Kubernetes v1.37, Chaos Mesh 2.8.4, Python 3.

### Prerequisites
- Linux with **rootless Podman** and systemd (the scripts run kind with the Podman provider)
- `kind`, `python3`, `curl`, `git`, `rg` (ripgrep)
- ~4 CPU cores and 8 GB RAM free (≈ 12 GB with Prometheus/Grafana)

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

### 6. Measure normal on this machine (≈ 6 min)
```bash
bash scripts/baseline.sh --duration 300
```
Every verdict, threshold and score is relative to this baseline, so take it on the machine that runs the experiments (the `baseline.json` in the repository was measured on ours) and again after changing the configuration. It must end with `baseline suitable: True`; if it doesn't, free memory (stop Docker, pause software updates) and repeat. Live agent runs refuse to start on an unsuitable baseline.

### 7. Check everything without breaking anything
```bash
python3 -m chaosmind.test_guard
```
```bash
python3 -m chaosmind.verify --dry-run
```

---

## Running experiments

### Quick demo (≈5 min, watch it in Grafana)
```bash
bash scripts/grafana-stress.sh
```
20 shoppers, then 100 shoppers, then 500 ms delay on the product catalog through the guard, then the automatic revert and recovery, all visible on the **Online Boutique: Chaos Overview** dashboard.

### An experiment is a JSON file
```json
{"id": "test-delay", "fault": "network_delay", "target": "productcatalogservice",
 "params": {"latency": "500ms"}, "duration_s": 60,
 "hypothesis": "All pages slow down; nothing crashes"}
```
| Field | Allowed |
|---|---|
| `fault` | `pod_failure`, `pod_kill`, `network_delay`, `network_loss`, `network_partition`, `cpu_stress`, `disk_full` (see coverage table below) |
| `target` | Any deployment name, e.g. `cartservice`, `productcatalogservice` |
| `duration_s` | 1 to 120 |
| `params` | `network_delay`: `latency`, `jitter` (ms, at most 2000); `network_loss`: `loss` (at most 50%); `network_partition`: `to` (the dependency to cut off); `cpu_stress`: `load` (1 to 100), `workers` (1 or 2); `disk_full`: `path` (a mounted volume, e.g. `/data`), `percent` (1 to 100) |

**Coverage of the failure types listed in the brief**

| Brief's example | How we inject it | Live status |
|---|---|---|
| Service or container crash | `pod_failure` (down for N s), `pod_kill` (instant kill and recreate) | Proven live, manually and in all 8 AI runs |
| Slow or lossy network | `network_delay`, `network_loss` | Proven live, manually ([delay](../runs/test-delay-20261010T062255.501508Z), [loss](../runs/catalog-loss-20261011T012959.046378Z)) and in AI runs 7 and 8 |
| Full disk | `disk_full`: Chaos Mesh IOChaos returns `ENOSPC` ("no space left on device") on the volume | Not runnable on this application: Chaos Mesh's disk-fault helper cannot start in Online Boutique's read-only containers ([attempt](../runs/redis-disk-full-20261011T013212.812294Z)) |
| Overloaded database | `cpu_stress` on `redis-cart` | Proven live ([run](../runs/redis-cpu-20261011T013116.326478Z)): no customer impact |
| Failed dependency | `network_partition`: e.g. `cartservice` can no longer reach `redis-cart` | Proven live, manually ([run](../runs/cart-redis-partition-20261011T013040.963758Z)) and in AI runs 7 and 8 |
| Sudden traffic spike | 20 to 100 shoppers (`scripts/grafana-stress.sh`) | Proven live, run twice |

Ready-made experiments for each are in [`experiments/`](../experiments).


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

### Let the agents choose and run experiments
One-time setup:
```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```
The workflow pauses for approval before any fix (`--auto-approve` for recorded runs) and can resume an interrupted run with `--resume runs/agents-<time>`. Without LangGraph, `python3 -m chaosmind.agents` runs the same steps (no resume).

Needs `NVIDIA_API_KEY` in the environment or in `.env` (copy `.env.example`; git-ignored). Model: NVIDIA-hosted `openai/gpt-oss-20b`; swap with `NIM_MODEL` (plus `NIM_EXTRA_BODY` for models that need extra request fields). Check the key with `python3 -m chaosmind.agents.llm --ping`.

Audit, plan and safety review only; nothing is injected:
```bash
.venv/bin/python -m chaosmind.graph --dry-run
```
Live: up to 3 experiments. Each one is set up with an integrity check, ramped through the guard, scored and judged, and the AI re-plans after each result. Then the Analyst writes `FINDINGS.md`:
```bash
.venv/bin/python -m chaosmind.graph --budget 3
```
Also let Remediation apply a reviewed fix to each confirmed weakness and re-run the identical experiment (changes the cluster). With `--ui`, approve each fix in **mission control** (`python3 -m chaosmind.ui`, then http://127.0.0.1:8090) instead of the terminal:
```bash
.venv/bin/python -m chaosmind.graph --budget 6 --remediate --ui
```
Approved fixes stay applied. To give the AI the original weaknesses again (for example before a recorded run), then re-take the baseline:
```bash
bash scripts/reset-weaknesses.sh
```
By default the AI may only use fault types already proven live (`inject.LIVE_VERIFIED`: pod failure, pod kill, network delay, packet loss, network partition, CPU stress); `--allow-unverified` adds full disk, which can't inject on Online Boutique's read-only containers.
A live run takes roughly 4 to 6 minutes per experiment (ramp steps and recovery), so pre-record it for the demo.

Offline tests (no cluster, no API key):
```bash
python3 -m chaosmind.test_guard && python3 -m unittest chaosmind.agents.test_agents chaosmind.agents.test_day2 chaosmind.test_c_tests && .venv/bin/python -m unittest chaosmind.test_graph chaosmind.test_ui
```
Everything is saved to `runs/agents-<time>/`: facts, vulnerabilities, every plan, the full history with verdicts and scores, and `FINDINGS.md` (written even if the model fails, then without the AI narrative). To regenerate the report for a run: `python3 -m chaosmind.agents.analyst runs/agents-<time>`.

### Manual incident menu (one scenario per failure type in the brief)
```bash
python3 scripts/incidents/menu.py
```
Details: [INCIDENTS.md](INCIDENTS.md).

### Undo / redo the Redis fix (before-vs-after demo)
```bash
bash scripts/redis-fix.sh apply
```
```bash
bash scripts/redis-fix.sh revert
```

### Watch it live in Grafana
```bash
bash scripts/install-monitoring.sh
```
```bash
bash scripts/monitoring.sh grafana
```
Then open the **Online Boutique: Chaos Overview** dashboard at http://127.0.0.1:3000. Full guide: [monitoring/README.md](../monitoring/README.md).

### Optional: standalone customer simulator
`customer_simulator.py` runs scripted shopper journeys with per-request error tracing and Prometheus metrics. See [`CUSTOMER_SIMULATION.md`](CUSTOMER_SIMULATION.md).
