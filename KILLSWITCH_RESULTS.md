# Kill-switch results and recent changes

Recorded on **10 October 2026** from the saved live run evidence in this checkout.
This supplements [PROJECT_HANDOFF.md](PROJECT_HANDOFF.md).

## Summary

All three kill-switch checkpoints **passed**. The Redis checkpoint recorded a
**data-loss finding**: replacing the Redis pod emptied the test shopper's cart.

| Checkpoint | Result | Observed evidence |
| --- | --- | --- |
| Ad-service health trigger | PASS | One unhealthy service exceeded the configured limit of zero; the guard reverted the fault and confirmed recovery. |
| Guard killed with SIGKILL | PASS | Chaos Mesh recovered the injected fault automatically with its 60-second duration, while the guard process was dead. |
| Manual abort | PASS | Two confirmed faults were removed; deletion took 0.386 seconds, followed by application recovery. |
| Redis cart persistence | FINDING | The same session had one item before Redis pod replacement and zero afterward. |

Primary evidence:

- [Kill-switch summary](runs/c-killswitch-20261010T070521.008028Z/summary.json)
- [Kill-switch event log](runs/c-killswitch-20261010T070521.008028Z/evidence.jsonl)
- [Kill-switch CSV](runs/c-killswitch-20261010T070521.008028Z/evidence.csv)
- [Redis summary](runs/c-redis-20261010T070925.577773Z/summary.json)
- [Redis event log](runs/c-redis-20261010T070925.577773Z/evidence.jsonl)

PASS describes the tested safety control. It does not establish that the entire
application is resilient to every fault or every traffic level.

## Environment and traffic

The tests targeted `kind-online-boutique`, namespace `online-boutique`, using
the project kubeconfig at `.runtime/kubeconfig`.

Traffic remained active with **20 Locust users** throughout the sampled
kill-switch metrics. Twenty users means concurrent simulated shoppers; it
does not mean 20 requests per second.

Across the checkpoint runner's baseline and recovery samples:

| Measurement | Observed value |
| --- | --- |
| Users | 20 |
| Recent completed throughput | 3.3–5.1 requests/second |
| Recent aggregate p95 latency | 40–580 ms |
| Recent aggregate error rate | 0 in the recorded samples |
| Cumulative completed requests | 11,367 → 12,416; increase of 1,049 |
| Cumulative failures | 207 → 207; no additional failures in this interval |

The 207 failures predated these checkpoints. Recent error rate and cumulative
failure count describe different windows. These are sampled aggregate metrics;
they do not expose every short spike or every individual service's behavior.

## 1. Ad-service health trigger

### What was tested

The runner injected a `PodChaos` **pod-failure** into one `adservice` pod for a
maximum of 60 seconds. The guard used `max_unhealthy=0`, so one unavailable
deployment was sufficient to trigger cleanup.

Other guard thresholds remained active: error rate greater than 20% and p95
latency greater than 2,000 ms. The implementation checks error rate, then
latency, then unhealthy services. In this run, **service health was the actual
trigger**.

### Timeline

Times below are seconds from the start of this guard run, including preflight.

| Event | Time |
| --- | ---: |
| Chaos resource created | 2.792 s |
| Injection confirmed | 2.935 s |
| BREACH: unhealthy = 1, limit = 0 | 9.193 s |
| Revert requested | 9.193 s |
| Chaos resource deletion completed | 9.568 s |
| Application health confirmed | 45.286 s |

The observed breach followed confirmed injection by approximately **6.258
seconds**. Deletion completed approximately **0.375 seconds** after the revert
request. Healthy recovery was recorded **36.093 seconds** after that request.

At the breach sample, `unhealthy_services` contained `adservice`, recent error
rate was zero, and p95 was 88 ms. Ad-service restart count increased from zero
to two by the final healthy sample. The cumulative failure count stayed at 207.

This demonstrates the guard can react to Kubernetes service health even while
the sampled user-facing aggregate metrics remain within their limits.
The record does not establish the precise cause of the additional recovery
delay; diagnosing that would require correlating pod events and service logs.

Evidence: [guard lifecycle](runs/c-ad-health-13973e53bd-20261010T070523.440196Z/events.jsonl)
and [guard metrics](runs/c-ad-health-13973e53bd-20261010T070523.440196Z/metrics.csv).

## 2. Guard crash and automatic recovery

### What was tested

The runner launched a separate guard process, waited for its `INJECTED` event,
then killed it using **SIGKILL**, equivalent to `kill -9`. The observed process
return code was **-9**.

The runner checked that the chaos resource was still injected after the kill.
It then watched for Chaos Mesh's `AllRecovered=True` condition **before manual
deletion**, followed by application health confirmation.

### Results

| Event | UTC timestamp |
| --- | --- |
| Injection confirmed by guard | 07:06:15.552787 |
| SIGKILL recorded | 07:06:15.587752 |
| Automatic recovery observed | 07:07:15.785193 |
| Application health confirmed | 07:08:13.162420 |
| Recovered resource cleaned up | 07:08:13.695641 |

The summary reports **60.055 seconds** of recovery observation after the
post-kill resource check. The SIGKILL and recovery event timestamps are about
**60.197 seconds** apart. The saved Chaos Mesh record independently shows
successful Apply at `07:06:15Z` and Recover at `07:07:15Z`.

The recovered resource had:

- `spec.duration: 60s`
- `AllRecovered: True`
- `desiredPhase: Stop`
- `injectedCount: 1` and `recoveredCount: 1`

Application health was confirmed approximately **117.575 seconds after
SIGKILL**, including approximately 57.377 seconds after automatic fault
recovery was observed. The 60-second timer limits the injected fault; pod
readiness and application recovery can take longer.

The crashed guard's own log ends at `INJECTED`. It has no `REVERTED` or `HEALTHY`
event because SIGKILL prevents Python cleanup from running. The separate
checkpoint runner supplies the recovery evidence.

Evidence: [recovered Chaos Mesh resource](runs/c-killswitch-20261010T070521.008028Z/crash-resource-recovered.json),
[resource before recovery](runs/c-killswitch-20261010T070521.008028Z/crash-resource-before.json),
and [crashed guard log](runs/c-crash-e086f13971-20261010T070612.461827Z/events.jsonl).

## 3. Manual abort

### What was tested

The runner confirmed injection of two faults:

1. Ad-service pod failure.
2. Shipping-service network delay.

It called `inject.abort_all()`, the same function used by
`python3 -m chaosmind.inject abort`, and checked that no chaosmind-owned
resources remained.

### Results

- Fault deletion took **0.386 seconds**.
- `ABORT_CLEARED` was recorded at `07:08:21.264137Z`.
- Application health was confirmed at `07:09:23.863484Z`, approximately
  **62.599 seconds after the cleared event**.
- The final health sample had no unhealthy services, recent error rate zero,
  and p95 of 63 ms.

Abort is scoped to the `app.kubernetes.io/part-of=chaosmind` label. It does not
delete unrelated experiments, including the separate `boutique-chaos`
experiments. The test verified removal of the owned resources; it did not
create a foreign experiment to test preservation independently.

The result demonstrates manual cleanup of multiple owned faults. The measured
application recovery time should be shown alongside the much shorter deletion
time when presenting this result.

## 4. Redis cart data-loss finding

The runner created a dedicated shopper session and added one item, product
`OLJCESPC7Z`. It verified the populated cart before deleting the observed Redis
pod, then checked the same session after a different Redis pod became ready.

| Measurement | Result |
| --- | --- |
| Items before replacement | 1 |
| Items after replacement | 0 |
| Redis replicas | 1 |
| Storage mounted at `/data` | `redis-data`, backed by `emptyDir` |
| First successful cart response after deletion was requested | 3.707 s |
| Replacement ready and cart response verified | 4.874 s |
| Failed HTTP responses observed by the test shopper | 0 |

The first post-deletion cart GET took **3.412 seconds** and completed
successfully. No sampled HTTP failures were recorded, but the cart contents
were lost. Successful HTTP responses do not imply preserved application data.

The live deployment confirms the storage explanation: `emptyDir` belongs to a
pod and is lost when that pod is replaced. The single Redis instance could not
retain this cart through replacement. This run establishes loss for the test
session; it did not enumerate every shopper's cart.

Suggested follow-up: persistent Redis storage with persistence enabled, followed
by the same test to verify retention. Replication and recovery behavior also
need evaluation. **No persistence fix was implemented in this work.**

Evidence: [live Redis deployment](runs/c-redis-20261010T070925.577773Z/redis-deployment.json),
[cart before](runs/c-redis-20261010T070925.577773Z/cart-before.html),
[cart after](runs/c-redis-20261010T070925.577773Z/cart-after.html),
and [archived finding](runs/c-redis-20261010T070925.577773Z/redis-finding.txt).

## Recent implementation changes

These changes implement [RUN_C_TESTS.md](RUN_C_TESTS.md):

| File | Purpose |
| --- | --- |
| [chaosmind/c_tests.py](chaosmind/c_tests.py) | Runs the three kill-switch checkpoints and Redis test; confirms injection/recovery and writes evidence. |
| [tests/killswitch.sh](tests/killswitch.sh) | Executable entry point for the three kill-switch checks. |
| [tests/redis_finding.sh](tests/redis_finding.sh) | Executable entry point for the Redis cart check. |
| [chaosmind/test_c_tests.py](chaosmind/test_c_tests.py) | Ten offline tests for the new runner, including recovery-before-cleanup, partial log reads, scoped cleanup, and session continuity. |
| [tests/README.md](tests/README.md) | Run commands, result meanings, cleanup scope, and evidence format. |
| [RUN_C_TESTS.md](RUN_C_TESTS.md) | Local implementation notes and guidance for staging ignored evidence. |

The existing guard, injection API, metric reader, and pod-log capture API are
reused. Guard thresholds and production application code were not changed by
this checkpoint implementation.

### Evidence format and result meanings

- `evidence.csv`: `timestamp_utc`, `elapsed_s`, `test`, `event`, `details_json`.
- `evidence.jsonl`: corresponding structured events, including metrics,
  injection status, HTTP observations, cleanup, and final outcomes.
- `summary.json`: final results and measurements per checkpoint.
- Normal guard directories retain their `events.csv`, `metrics.csv`, and
  `events.jsonl` lifecycle evidence.
- Pod logs are saved as CSV for the target, loadgenerator, and Chaos Mesh daemon.
  The latest successful checkpoints recorded **no log collection errors**.
- PASS means the checkpoint's required behavior was verified. FINDING records
  an observation, such as Redis data loss or a different guard threshold firing
  first. FAIL means the checkpoint could not be verified and returns nonzero.

Every invocation gets a unique directory. `runs/redis-finding.txt` is the latest
report; its archived version remains in the unique Redis run directory.
Collected pod logs cover recent history and can overlap between checkpoints.

### Verification and earlier failed attempts

During implementation, **10 new runner tests plus 14 existing guard tests passed**
offline. Those checks validate behavior using mocks; the live evidence above
separately validates interaction with the cluster.

Earlier assistant-session attempts in
`runs/c-killswitch-20261010T070311.478646Z/` and
`runs/c-redis-20261010T070312.099165Z/` failed at preflight with
`socket: operation not permitted`. The session could not access the local
Kubernetes API. These were access failures before injection, and their evidence
was preserved. The later host-terminal runs reported above completed the checks.

## Repeating the checks

Run in the host terminal with access to the cluster:

```bash
bash scripts/load.sh start 20 2
# Allow traffic to settle, then verify it:
bash scripts/load.sh measure 5 30
./tests/killswitch.sh
./tests/redis_finding.sh
```

Manual cleanup and optional shopper shutdown:

```bash
python3 -m chaosmind.inject abort
# Stop shoppers only when other testers are finished:
bash scripts/load.sh stop
```

The Redis check deliberately replaces the Redis pod and may wipe other active
carts. These scripts leave shoppers running and do not automatically pull,
commit, push, or send messages.

`runs/` is locally ignored. Evidence links in this document will resolve on
GitHub only if the corresponding run directories are also committed.
