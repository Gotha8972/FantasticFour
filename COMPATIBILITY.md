# Repository review and local integration

Reviewed `PLAN.md`, `DAY1.md`, `C_INJECTION_KILLSWITCH.md`, the local `README.md` and `chaos/README.md`, both original Python modules, their original tests, experiment JSON files, and `setup/sandbox.sh`.

## Fit with the intended plan

The repository's design matches the goal: Online Boutique on kind, declarative Chaos Mesh failures, a deterministic Python operator/kill switch, and measured customer impact. Its two implemented faults are a useful starting point for the eventual AI agent. It is currently a scaffold rather than the complete planned system: Cartographer, Strategist, Safety Officer, Analyst, shared state, Streamlit, and Prometheus integration are not implemented in this checkout.

| Issue found | Local integration |
| --- | --- |
| Injector and guard used namespace `boutique` | Fixed to `online-boutique` |
| kubectl used the user's default context | Explicit project kubeconfig and `kind-online-boutique` context |
| Original setup creates cluster `chaos`, assumes Docker/Ubuntu, installs a second platform stack | Use the existing `scripts/deploy-local.sh` and `scripts/install-chaos.sh`; do not run `setup/sandbox.sh` on this Fedora setup |
| Error rate and p95 were fabricated zero placeholders | Replaced with real Locust CSV statistics; stale/missing/zero-traffic metrics cause refusal or cleanup |
| Resource creation was logged as successful injection | `CREATED` and `INJECTED` are separate; injection requires Chaos Mesh status evidence |
| Creation happened outside the cleanup block | Creation, observation, and exceptions now enter the cleanup path; cleanup verifies ownership and run identity |
| Original abort deleted every fault in the namespace | Python abort deletes only resources labeled as owned by `chaosmind` |
| Guard allowed thresholds to be loosened | Error, latency, blast radius, duration, polling and injection-wait overrides may only tighten defaults |
| Runs recorded only lifecycle JSONL | Each run now writes lifecycle CSV, metric CSV, and JSONL; a separate collector exports pod logs to CSV |
| No automatic check of injection status or recovery | Added `python3 -m chaosmind.verify`, which checks admission, confirms injection, checks recovery, and tests the pod-health kill switch |

The imported design's `mode: all` has been changed to `one` for a small initial blast radius. With the current single-replica deployments, both select one service pod. Pod Failure is retained for the guarded outage test because it is a continuous fault that can be reverted, unlike a one-time pod deletion.

## Run on the existing cluster

No additional Python packages are required; these modules use the standard library and kubectl.

```bash
cd /home/aashrith/Desktop/boschthon
python3 -m chaosmind.test_guard
bash scripts/load.sh start 20 2
bash scripts/load.sh measure 5 30
```

Let the load reach 20 users and settle before verification. The guard requires fresh, nonzero traffic and healthy deployment readiness. Completed manually-created experiments can be removed with `bash scripts/chaos.sh stop-all`; remove dashboard-created faults separately. The verifier refuses to overlap with any unrecovered PodChaos, NetworkChaos, StressChaos, or IOChaos object in the application namespace.

Check schemas and admission without injecting:

```bash
python3 -m chaosmind.verify --dry-run
```

Run the two experiments sequentially:

```bash
python3 -m chaosmind.verify
```

This tests a 500 ms network delay on `productcatalogservice`, followed by a pod failure on `cartservice`. Each requests a 60-second Chaos Mesh duration. The pod-failure test tightens `max_unhealthy` to zero to demonstrate automatic rollback on a pod-health breach. An experiment only passes verification when injection and recovery are both confirmed; the pod-failure test also requires a detected breach. A preflight refusal, failed injection, monitor error, missing recovery, or cleanup failure is reported rather than counted as a resilience success. Pod log export failures are reported separately.

Each guard run prints its artifact directory. Verification also writes a separate `runs/verification-<UTC timestamp>/summary.json` with actual pass/fail results. It stops after a failed experiment rather than moving on to the next fault.

To run one experiment:

```bash
python3 -m chaosmind.guard experiments/test-delay.json
python3 -m chaosmind.guard experiments/test-down.json '{"max_unhealthy": 0}'
```

Manual emergency cleanup for Python-created experiments:

```bash
python3 -m chaosmind.inject abort
```

This command does not remove independently-created dashboard or shell experiments. Keep the Chaos Mesh controller and daemon running while cleanup occurs. A deleted experiment's finalizers let Chaos Mesh restore its injected state; do not force-remove them to bypass a recovery failure.

## CSV evidence

| File | Contents |
| --- | --- |
| `runs/<experiment>-<timestamp>/events.csv` | UTC time, elapsed seconds, experiment identity, lifecycle state, breach reason/threshold, and structured details |
| `metrics.csv` in the same directory | Real snapshot samples during preflight, injection, and recovery: users, RPS, request/failure counts, error fraction, p95, checkout success, deployment health, and restart counts |
| `events.jsonl` in the same directory | Complete structured records for the later orchestrator |
| `*-logs.csv` exported by verification | Pod/container identity, Kubernetes log timestamp, message, and any collection error |

Export a separate baseline or observation window:

```bash
python3 -m chaosmind.capture metrics --duration 60 --interval 2 --phase baseline --output runs/baseline.csv
```

Export recent console logs:

```bash
python3 -m chaosmind.capture logs --selector app=loadgenerator --since 10m --output runs/loadgenerator-logs.csv
python3 -m chaosmind.capture logs --selector app=frontend --since 10m --output runs/frontend-logs.csv
python3 -m chaosmind.capture logs --namespace chaos-mesh --selector app.kubernetes.io/component=chaos-daemon --output runs/daemon-logs.csv
```

Collector outputs use exclusive file creation: choose a new filename for a new capture. Logs are snapshots of the selected containers' available log history, not a persistent cluster logging service. Older/deleted pods' logs may no longer be available. Metrics CSV records an error row if real collection fails; it never substitutes zero values.

Convert an existing JSONL run to CSV:

```bash
python3 -m chaosmind.capture convert runs/<run>/events.jsonl --output runs/converted-events.csv
```

The error fraction, RPS, and p95 use Locust's recent aggregate history; history is configured with `--csv-full-history` to provide current percentile samples. Checkout success is cumulative for the current Locust process and is blank until a checkout completes. These are request-level application observations, not CPU utilization or per-service Prometheus metrics. Guard reaction time includes Kubernetes API calls, so a two-second polling interval does not guarantee cleanup in two seconds.

## Validation performed in this session

- Original offline checks passed before adaptation, but they only covered manifests and threshold comparisons.
- Expanded offline behavior tests cover cleanup on breach, creation/monitor errors, Ctrl-C, rejection of unrelated resources and unsafe parameters, true metric parsing, and CSV escaping.
- Both adapted guard scripts and the verification dry run were attempted against the real project kubeconfig. This session denied the local API socket (`socket: operation not permitted`), so no faults were created by those attempts. Their CSV/JSON artifacts record the connection error.
- Earlier host-terminal evidence confirmed that the manually-created `shipping-delay` experiment reached `Injected` after loading the missing kernel modules. That does not verify the imported product-catalog or pod-failure experiments; run the verifier from the host terminal to confirm them.
