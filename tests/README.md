# C checkpoint tests

These implement [RUN_C_TESTS.md](../RUN_C_TESTS.md) for the existing
`kind-online-boutique` cluster and `online-boutique` namespace.
They use `.runtime/kubeconfig`, confirmed Chaos Mesh status, and live Locust
metrics. Run from the host terminal where kubectl can reach the cluster.

```bash
bash scripts/load.sh start 20 2
# Let traffic run for approximately a minute, then check it:
bash scripts/load.sh measure 5 30
./tests/killswitch.sh
./tests/redis_finding.sh
python3 -m chaosmind.inject abort
```

The kill-switch command runs three cases sequentially:

1. **Ad-service health:** inject a 60-second pod failure with `max_unhealthy=0`.
   PASS requires confirmed injection, an unhealthy-service breach, deletion,
   and healthy recovery. An error-rate or latency breach first is a FINDING,
   as specified in the request. Failed injection/recovery is FAIL.
2. **SIGKILL fail-safe:** start a real guard subprocess, wait for its INJECTED
   event, kill that subprocess with SIGKILL, and verify the fault remains
   injected. Observe Chaos Mesh's `AllRecovered` condition before deleting
   anything, then confirm application health. The spec duration is 60 seconds;
   the observer allows 45 seconds of reconciliation slack. Finally remove the
   recovered resource. This tests controller recovery while the guard is dead.
3. **Abort:** confirm two owned faults (ad-service failure and shipping delay),
   call the same `abort_all()` used by the CLI, verify every chaosmind-owned
   resource is gone, and confirm health. Record actual deletion time;
   Kubernetes deletion and application recovery are not instantaneous.

Preflight rejects existing unrecovered faults and unhealthy/absent traffic.
Cleanup deletes owned test resources. The abort command only deletes faults
labelled `app.kubernetes.io/part-of=chaosmind`; it preserves other users' faults.
If a case fails, the next case performs its own preflight before injecting.

The Redis test adds one item using its own session cookie, verifies the cart,
saves the live deployment storage configuration, deletes the observed Redis
pod, waits for a new ready pod, and checks the same cart. It samples HTTP
failures during recovery and distinguishes an empty cart from an error page.
It deliberately replaces the Redis pod, so other active carts may also be lost.
Both cart loss and retention are recorded as findings. It never installs a
persistence fix or scales any service.

```bash
# If your frontend uses a different local URL:
./tests/redis_finding.sh --frontend-url http://127.0.0.1:8080
```

## Evidence

Each invocation preserves a unique `runs/c-killswitch-<timestamp>/` or
`runs/c-redis-<timestamp>/` directory:

- `evidence.csv` / `evidence.jsonl`: timestamp, elapsed seconds, test, event,
  details (including real metrics, injection state, HTTP errors and cleanup).
- `summary.json`: PASS, FINDING, or FAIL with reasons. A FAIL returns nonzero.
- Guard events and CSVs in separate normal guard run directories; paths are
  recorded by the checkpoint.
- Crash terminal output and CR snapshots before and after automatic recovery.
- Target, loadgenerator and daemon log CSVs after successful cases. Collection
  errors are recorded separately; these are recent historical logs, not streams.
- Redis deployment JSON, before/after cart HTML, and `redis-finding.txt`.

`runs/redis-finding.txt` is the latest Redis report; every report, including
failures, is also preserved in its unique run directory. Sampled HTTP failure
times do not establish an exact outage duration.

The tests leave shoppers running. Stop them only when other testers are done:

```bash
bash scripts/load.sh stop
```

`runs/` is ignored locally. When publishing evidence, explicitly stage the
chosen run directories with `git add -f runs/<directory>` and inspect the staged
diff. These scripts do not pull, commit, push, or send team messages.
