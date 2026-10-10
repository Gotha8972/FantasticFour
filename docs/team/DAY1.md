# Day 1 — Work Split

> **Historical planning note.** The project later switched its AI provider from Mistral to OpenAI `gpt-5.6-luna`, and now to **NVIDIA-hosted `openai/gpt-oss-20b`**. See the [README](../../README.md).

**Goal by end of day:** app running → AI-built dependency map → baseline → one safe failure with visible customer impact → kill switch fires automatically → one real finding.

## Hour 0: everyone together (30 min)
1. Create the GitHub repo and push this folder. Everyone clones it.
2. Agree on the **4 contracts** below. Once they're fixed, everyone can build in parallel without waiting on each other.
3. Everyone without a cluster starts `./setup/sandbox.sh` (Linux) or the Mac equivalent (OrbStack/Docker Desktop + `brew install kind kubectl helm`). It runs in the background while you code.

## Contracts (agree on these first, don't change without telling the team)
```jsonc
// 1. graph.json            — B produces, D/C consume
{"services": [{"name": "cartservice", "replicas": 1, "port": 7070}],
 "edges":    [{"from": "frontend", "to": "cartservice"}]}

// 2. monitor.snapshot()    — B produces, C (guard) + D consume
{"ts": 1728550000, "error_rate": 0.004, "p95_ms": 120,
 "checkout_success": 0.99, "unhealthy_services": [], "restarts": {"cartservice": 0}}

// 3. experiment.json       — D produces (Strategist), C executes
{"id": "exp-001", "fault": "network_delay", "target": "productcatalogservice",
 "params": {"latency": "500ms"}, "duration_s": 60,
 "hypothesis": "All pages slow down; checkout success stays >95%"}

// 4. thresholds.yaml       — C owns
error_rate: 0.20     # stop if >20% requests fail
p95_ms: 2000         # stop if p95 > 2s
max_unhealthy: 2     # blast radius
max_duration_s: 120
```

## Who does what

### A: Platform (Linux laptop = demo machine)
| # | Task | Done when |
|---|---|---|
| A1 | Run `sandbox.sh`, fix whatever breaks | All pods `Running`; an order goes through at :8080 |
| A2 | `Makefile`: `make up`, `make ui` (all port-forwards), `make down`, `make abort` | One command from zero to running |
| A3 | Help B/C/D get their own clusters up | Everyone has a working cluster |
| A4 | README: setup + how to run | A teammate follows it without asking questions |
| A5 | Own the checkpoint demo run on the demo laptop | Rehearsed once end to end |

### B: Mapping + monitoring
| # | Task | Done when |
|---|---|---|
| B1 | `tools/k8s.py`: list Services/Deployments + read `*_SERVICE_ADDR` env vars → raw edges | Returns the data the Cartographer needs |
| B2 | `monitor.py`: `snapshot()` per contract #2, from Prometheus + load generator stats | Prints a valid snapshot every 2s |
| B3 | `baseline.py`: 5 min steady load → `baseline.json` (mean/p95 of each metric) | Baseline file committed |
| B4 | Grafana panel: error rate, p95, **checkout success %** | The spike is visible on screen during injection |

### C: Injection + safety
| # | Task | Done when |
|---|---|---|
| C1 | `inject.py`: `apply(experiment.json)` / `revert(id)` → Chaos Mesh CR. Faults: **pod_kill**, **network_delay** | Both work from the CLI |
| C2 | Every CR gets Chaos Mesh's own `duration` (fail-safe if our guard crashes) | Fault ends by itself even with the guard killed |
| C3 | `guard.py`: pre-flight check (refuse if baseline is unhealthy) → poll `snapshot()` every 2s → breach → `revert` → wait until healthy | Fires on a deliberately low threshold |
| C4 | Timestamped log: `breach at 4.2s → reverted 5.1s → healthy 18s` | Log printed + saved |
| C5 | **The finding:** kill `redis-cart`, check whether carts are lost | Before/after evidence written down |

### D: Agents (Mistral)
| # | Task | Done when |
|---|---|---|
| D1 | `agents/llm.py`: Mistral client, JSON-mode helper, key from `.env` | One call returns valid JSON |
| D2 | **Cartographer**: B1 output → `graph.json` + Mermaid diagram; diff against the hand-written graph in PLAN.md | Map rendered, mismatches listed |
| D3 | **Strategist** (dry run): graph + baseline → 3 ranked experiments per contract #3, with hypothesis + reason | Sensible top 3 |
| D4 | **Safety Officer**: rejects/shrinks risky experiments | Demo: "kill all checkout pods for 10 min" → shrunk/rejected |
| D5 | `run.py`: Strategist → Safety → `inject` → `guard` → print result | One AI-chosen experiment runs end to end |

## Sync points
| When | What |
|---|---|
| H0 | Contracts agreed, setup running on all laptops |
| H2 | A: app up. B: `snapshot()` works. C: pod_kill works. D: Mistral JSON call works |
| H4 | **Integration 1:** C's guard reads B's snapshot; D's Cartographer uses B's tools |
| H6 | **Integration 2:** `run.py` runs one AI-chosen experiment; the guard fires on a low threshold |
| H7 | Rehearse the checkpoint demo (script in PLAN.md) and fix what breaks |
| End | Checkpoint demo. Push everything. Write tomorrow's top 3 tasks |

## If behind schedule, cut in this order
Grafana polish → Safety Officer → Strategist (pick the experiment by hand) → Mermaid diagram.
**Never cut:** app running, dep map, one injection, guard firing. Those are the required minimum.
