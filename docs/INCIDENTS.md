# Manual incident menu

Keep Grafana open in another terminal, then run from the project folder:

```bash
python3 scripts/incidents/menu.py
```

Choose a number from 1 to 6. Choice 2 also asks for `delay` or `loss`.
`q` exits the menu. Each selection launches a Bash script with `subprocess`,
without shell evaluation of user input. The menu can be run from another
directory too; all paths resolve against this project.

## Choices and direct commands

| Choice | Incident | Implementation | Direct command |
| --- | --- | --- | --- |
| 1 | Server or container crash | Existing catalog pod kill demonstration: one exact pod is killed and a replacement observed. | `python3 scripts/incidents/menu.py --choice 1` |
| 2 | Slow or lossy network | 500 ms catalog delay with 50 ms jitter, or 10% catalog packet loss; at most 60 seconds through the existing guard. | `python3 scripts/incidents/menu.py --choice 2 --network-mode delay` or `--network-mode loss` |
| 3 | Full Disk | IOChaos returns errno 28 (ENOSPC) on Redis `/data` write/create/fsync operations, for at most 60 seconds. A dedicated write probe checks the observed error. | `python3 scripts/incidents/menu.py --choice 3` |
| 4 | Overloaded Database | A temporary Job runs `redis-benchmark`: 50 connections, pipeline 4, at most 10 million GET requests against a dedicated unused key. Observe for up to 60 seconds after startup. | `python3 scripts/incidents/menu.py --choice 4` |
| 5 | Failed Dependency | Shipping service becomes unavailable via `pod-failure`, for at most 60 seconds through the existing guard. | `python3 scripts/incidents/menu.py --choice 5` |
| 6 | Sudden Traffic Spike | Increase shopper load from 20 to 200 with spawn rate 100/second; observe for up to 60 seconds. | `python3 scripts/incidents/menu.py --choice 6` |

Bash entry points are under `scripts/incidents/`: `server-crash.sh`,
`network.sh`, `full-disk.sh`, `database-overload.sh`, `failed-dependency.sh`,
and `traffic-spike.sh`. You can invoke each with `bash` directly.

## What is being simulated

- The crash choice kills a **pod**, using the existing demonstration. It does
  not power off the kind node or host. It runs with 100 shoppers, records a
  60-second baseline and 120-second post-kill window, then restores 20 shoppers.
  A killed pod cannot be rolled back; its Deployment creates a replacement.
- Full Disk **simulates disk-full write errors**, without filling the laptop
  filesystem. IOChaos requires the installed CRD and working daemon filesystem
  injection support. A failed injection or missing ENOSPC probe is logged as an
  error, not counted as a successful incident. Redis normally handles carts
  in memory, so storage errors may not immediately cause shopping failures.
  The probe establishes disk-error behavior independently of shopper impact.
  [Chaos Mesh IOChaos documentation](https://chaos-mesh.org/docs/next/simulate-io-chaos-on-kubernetes/)
  describes filesystem error injection and errno 28.
- The database choice uses real Redis read pressure. It does not write over
  carts, clear Redis, or claim to simulate SQL locking. CPU growth and shopper
  failures depend on the load and host capacity; saturation is not guaranteed.
  The Job has a 120-second deadline covering startup and runtime, plus cleanup.
  [Redis benchmark documentation](https://redis.io/docs/latest/operate/oss_and_stack/management/optimization/benchmarks/)
  explains concurrency, pipelines and custom commands.
- The spike changes Locust's headless user settings by rolling its deployment.
  Traffic briefly pauses and CSV counters reset. Interpret pre-rollout and
  post-rollout statistics separately. This is a sharp increase after startup,
  rather than a continuous user-count change inside the same Locust process.
- Failed Dependency targets a real downstream service, shipping; browsing may
  work while cart quotes/checkout fail. No request failure spike is guaranteed
  for every short observation window.

## Scope, guard and cleanup

The new runner refuses concurrent unrecovered Chaos Mesh experiments and
existing database-load jobs, sets 20 baseline shoppers, waits for fresh metrics,
and checks baseline health before requesting a fault. It requires the existing
loadgenerator to have explicit positive `USERS` and `RATE` values.

Network and dependency faults use the existing guard: greater than 5% recent
errors, 1,000 ms recent p95, or 2 unhealthy services triggers removal and
recovery checking. Disk, database and spike observations use those same limits
to end pressure early. A breach is recorded in the lifecycle log. Transient
metric windows and sampling overhead mean this is not an instantaneous guard.

Cleanup removes only the uniquely named IOChaos/Job created by the selected
run, removes its probe file, exports available Locust CSVs, restores previous
user/rate/replica settings for choices 2 to 6, and checks recovery when the original
loadgenerator was enabled. Choice 1 retains the existing demonstration's
restore-to-20 behavior. No Git commands or publication are performed.

Ctrl-C requests cleanup; wait for it to finish. If the process is force-killed,
IOChaos's duration and the Job's deadline bound those faults, but load settings
may still need manual restoration. Do not remove Chaos Mesh finalizers to
bypass cleanup. Failed cleanup and recovery are reported as errors.

## Evidence and Grafana

Choices 2 to 6 print an artifact directory under `runs/incident-*` with:

- `events.csv`, `events.jsonl`, `metrics.csv`: phase timestamps, breaches,
  request metrics, health and cleanup/recovery results.
- `load_stats.csv`, `load_stats_history.csv`, `load_failures.csv`: available
  Locust exports before restoration rolls the pod again.
- Disk/database: `manifest.json` and `injection-status.json`.
- Database: `benchmark.log`, when available.
- Network/dependency: the existing guard writes its own run folder, linked by
  a `GUARD_FINISHED` event in the incident log.

Choice 1 writes its existing `runs/grafana-pod-kill-*` evidence.
It supports one or more ready catalog replicas and kills one specific pod.
Recovery requires a new pod UID and healthy service metrics; a surviving
replica alone does not count as a replacement. The result records the initial
number of ready replicas.

Watch availability and errors for crashes/dependencies, p95 and throughput for
network faults, Redis CPU for database pressure, and shopper count/CPU/RPS for
traffic spikes. Brief faults may fall between scrapes. The injected-fault panel
currently tracks PodChaos, NetworkChaos and StressChaos, **not IOChaos or load
Jobs**; use the saved IOChaos/probe evidence for disk and Job evidence for Redis
pressure. The dashboard does not import older CSV runs.

## Implementation status

These menu/scripts are created locally. No incident was launched and no new
tests were added or run for this task. Disk injection and the new database/spike
scenarios still need live validation on the host; the assistant shell cannot
access this kind cluster. Existing catalog pod kill evidence is documented in
`monitoring/README.md`.

## Packet loss at 100 shoppers

After the previous experiment has recovered, run:

```bash
python3 scripts/incidents/menu.py --choice 2 --network-mode loss --users 100 --rate 10
```

This establishes a baseline at 100 shoppers, then requests 10% catalog packet loss for up to 60 seconds through the guard. Baseline health must pass first; overload at 100 shoppers prevents injection. The guard retains its approved limits and restores the previous load settings afterward. Compare against the 100-shopper baseline to distinguish load effects from loss effects. Shopper count can be 1 to 200 and spawn rate 1 to 100 per second. Starting new load settings rolls Locust and resets its live CSV counters. No higher-load result is claimed until run evidence is captured.
