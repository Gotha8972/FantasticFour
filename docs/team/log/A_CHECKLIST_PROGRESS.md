# A_CHECKLIST.md: implementation and execution status

> **Historical planning note.** The project later switched its AI provider from Mistral to OpenAI `gpt-5.6-luna`, and now to **NVIDIA-hosted `openai/gpt-oss-20b`**. See the [README](../../../README.md).

## Completed in the workspace

- Setup, monitoring, chaos, pod kill, load and measurement source files are present.
  `.runtime/`, `microservices-demo/`, `.env`, Python caches and `runs/` are ignored.
- Updated `scripts/push-next-steps.sh` to publish all platform Python source,
  scripts/configuration, tests, experiment definitions and documentation on top
  of remote `main` in a separate worktree. It explicitly adds saved baseline,
  pod kill, stress, investigation, agent and checklist evidence. It never copies
  `.env`, `.runtime`, downloaded application source or Python caches.
  After pushing it checks that remote `main` contains `monitoring/values.yaml`
  and `scripts/install-monitoring.sh`. No force push or unrelated-history merge.
- Guard defaults remain **5% recent errors / 1,000 ms recent p95 / 2 unhealthy
  services**, as approved by the team. Updated the team's root README Safety
  controls to match; the 2,000 ms maximum injected network delay is a separate
  validation limit. Earlier experiment results retain their original limits.
- Restored the team's seven agent modules and updated injector from the cached
  `origin/main` commit `b547216`. The injector supports the fault/intensity names
  used by the team agent planner. These extra fault types have not all been
  validated live. Previous local README/injector copies are in ignored
  `.runtime/checklist-backups/`.
- Confirmed the Mistral client's `.env` path is the project root and added
  support for whitespace and optional `export` prefixes. The user confirmed
  the key was stored locally and selected **mistral-small-latest**. Both model
  aliases now default to that model; the checklist runner explicitly selects it.
  No key value is included in logs or committed files.
- The agent baseline loader skips failed/incomplete archived runs rather than
  silently using them as measurements, and includes baseline suitability and
  findings in the facts supplied to the planner. An explicitly selected failed
  baseline is refused. A completed but unsuitable baseline remains labeled so
  the team can review it, as the checklist requests.
- The requested command `python3 -m unittest chaosmind.agents.test_agents`
  passed **all seven tests** after importing the team code.
  The existing guard suite also passed **all fourteen tests** with the updated
  injector. Both checklist/publication shell scripts passed syntax checks.

## Host sequence

With Grafana running in another terminal:

```bash
bash scripts/checklist.sh
```

The script checks key presence without printing it, checks Grafana/Prometheus
readiness, publishes setup, aborts only Python-owned faults, collects a fresh
300-second baseline after the baseline runner's warm-up, publishes the measured
run, repeats the requested offline tests, requests the AI **dry run**, and
publishes its saved output. It uses the exact new baseline path, so an older
root `baseline.json` cannot silently substitute for the fresh study.

Unrecovered faults owned by other tools are not deleted by the Python abort;
the baseline preflight will refuse them. A completed study marked unsuitable
is published with its findings; a failed/incomplete study stops before AI calls.
If it stops, inspect the printed logs before restarting the sequence: restarting
collects another baseline. Git push conflicts stop normally and retain the
publication worktree for review, with no force push.

The dry run prints the Cartographer's vulnerabilities, first Strategist
experiment, and Safety Checker's decision/ramp. The wrapper contains no live
agent invocation. Saved plans are for team review before live execution.

## Pending execution evidence

The checklist runner successfully detected the locally stored key without
printing it; it then stopped at Kubernetes preflight with the socket restriction.
That presence check does not establish that Mistral accepts the key.

Assistant attempts to fetch/publish fail because `.git/FETCH_HEAD` is read-only.
Kubernetes access fails with `socket: operation not permitted`; the assistant
cannot obtain the required fresh cluster baseline in this shell. GitHub network
access from the shell is also unavailable. Consequently **publication, remote
file verification, the fresh monitoring baseline, and the API-backed agent dry
run are not claimed complete**. Run the host sequence above to finish them.

Offline test success establishes mocked agent behavior, not actual Mistral API
access, key validity or live cluster recovery. No live AI experiment is authorized
by this checklist; the team must review the dry-run output first.
