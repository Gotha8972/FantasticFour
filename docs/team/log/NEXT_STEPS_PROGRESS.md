# A next steps: implementation and remaining host actions

This records the work requested in [A_NEXT_STEPS.md (since replaced by A_CHECKLIST.md)](A_CHECKLIST.md).

## 1. Publish the missing setup files

The required local files are present:

- `scripts/`: deploy, kubectl/Helm/Chaos Mesh installation, chaos controls,
  load generation, measurement, and baseline commands.
- `deploy/`: kind configuration, namespace, Kustomize overlay, Podman settings.
- `chaos/`: chart values, Locust observability patch, experiment manifests,
  and run guide.
- `tests/README.md`, `COMPATIBILITY.md`, and `.gitignore`.

`.runtime/` and `microservices-demo/` are ignored, along with `runs/`, Python
caches, and `.env`. Runtime credentials and downloaded source are not included
by the publication script.

`scripts/push-next-steps.sh` (since removed) prepares a separate
checkout of GitHub's existing `main`, copies the required files and updated
code, shows a staged summary, commits, and pushes. This avoids merging the
workspace's independently initialized local history.

Publishing from the assistant session failed because `.git/FETCH_HEAD` is
read-only. GitHub contents could not be verified from this session. Run the
publication script in the host terminal.

## 2. Accept small background baseline errors

[chaosmind/baseline.py](../../../chaosmind/baseline.py) now accepts window error rates
**below 1%**. Rates at or above 1% still produce a rejecting finding. Smaller
nonzero failure counts are saved under `notes`, including count and percentage.
The structured result records the acceptance policy and the guard limits used.
The generated Markdown includes a separate background-observations section.

Checks for unhealthy deployments, restarts, pod changes, sampling gaps,
missing checkouts, duration, traffic resets, and collection failures remain.
Zero completed requests also cannot qualify as an accepted baseline.

The earlier 15-minute study remains unchanged: 3,933 requests, two failed
checkouts, 0.0509% window error rate, and its original unsuitable result.
It has not been retroactively accepted. A new suitable run will write the
root `baseline.json` automatically.

The requested new run was attempted from this assistant session but cannot
pass Kubernetes preflight because local socket access is blocked. Failure
evidence is retained in a new `runs/baseline-study-*` directory. A host-terminal
run is still required; no new accepted baseline is claimed here.

## 3. Team-approved guard limits

The user confirmed that the team approved these changes:

| Limit | Previous | Current |
| --- | ---: | ---: |
| `error_rate` | 0.20 (20%) | **0.05 (5%)** |
| `p95_ms` | 2,000 ms | **1,000 ms** |
| `max_unhealthy` | 2 | **2** |

These are implemented in [chaosmind/guard.py](../../../chaosmind/guard.py). A breach
requires the observed value to be greater than the limit. Existing damage
threshold overrides still may only tighten the defaults. Duration, polling,
injection confirmation, cleanup, and recovery behavior remain as before.

Earlier experiments retain their recorded thresholds and results. Newly run
experiments use the tighter thresholds and may end earlier. The two current
checkout failures remain an observation to investigate.

## 4. Investigate available checkout failure logs

[chaosmind/checkout_investigation.py](../../../chaosmind/checkout_investigation.py) exports
available checkoutservice, paymentservice, and frontend logs to CSV, and saves
filtered error candidates, timestamp coverage, collection errors, and a
Markdown report in `runs/checkout-investigation-<timestamp>/`.

It finds the intervals where checkout failure counters increased in the chosen
study. Matching error candidates are flagged if their log timestamp falls in
those observation intervals. These intervals are not exact request times, and
text matches do not establish root cause.

The assistant-session collection attempt cannot reach the cluster. Its access
errors are retained rather than reported as application errors or absent logs.
Repeat in the host terminal to check whether older pod logs remain available.

## Host-terminal sequence

```bash
# Publish the missing setup files and code changes.
bash scripts/push-next-steps.sh

# Run a new study with the revised acceptance policy (approximately 16 minutes).
bash scripts/baseline.sh

# Check available logs for the ORIGINAL two checkout failures.
python3 -m chaosmind.checkout_investigation \
  --study runs/baseline-study-20261010T072314.832283Z --since 3h

# Publish the accepted baseline, new study evidence, and investigation output.
bash scripts/push-next-steps.sh
```

If time is short, `bash scripts/baseline.sh --duration 300` collects a new
five-minute observation window after warm-up. Shoppers remain running.

The publisher includes the setup directories, updated baseline/guard and
investigation code, supporting documentation, any root accepted baseline,
and archived baseline/investigation directories. Existing historical evidence
is preserved. A failed push leaves the temporary checkout path printed for
review and retry; it does not force-push.

Prometheus/Grafana setup was added after these steps. The publisher now also
includes `monitoring/`, its dashboard/exporters, monitoring scripts, and the
updated root README. See [monitoring/README.md](../../../monitoring/README.md). Installing
monitoring rolls the loadgenerator and resets live counters; install before
starting the next baseline run.

No new offline tests were added or executed for this change. Live execution and
publication are blocked by this session's host-access restrictions, as above.
