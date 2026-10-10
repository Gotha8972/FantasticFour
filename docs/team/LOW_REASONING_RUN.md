# Updated model: low reasoning effort dry run

Upstream commit: `7e185e7`. Synced 26 updated tracked files into the working project, preserving secrets and backing up replaced local files.

Model: `openai/gpt-oss-20b` hosted by NVIDIA. Request: `NIM_EXTRA_BODY={"reasoning_effort":"low"}`. The ping and complete audit/plan request succeeded. This setting is now in local `.env`; the API key remains private.

## Timing

| Stage | Seconds |
| --- | ---: |
| Architecture audit | 25.109 |
| Strategist | 11.136 |
| Complete dry run, including cluster reads | 45.167 |

The earlier default-effort run took several minutes, but its individual calls were not timed. This is not a controlled speed or quality comparison, and API acceptance alone does not prove how the backend interprets the field.

## Results

- Eight audit findings, zero rejected evidence claims. Redis finding describes availability risk, not data loss.
- Strategist returned two experiments for a maximum budget of three, both pod kills. Its Redis prediction still incorrectly asserts data loss despite the PVC. The Cartographer persistence filter does not validate Strategist predictions.
- Safety Checker rejected the experiment because the supplied baseline is explicitly unsuitable. No safety-model call was made, so the total does not measure a healthy-baseline three-agent run.
- No faults or remediation were executed. Results are inconclusive by design.
- Regression checks: 16 guard tests plus 53 agent/day2/capture/graph/portable tests passed (69 total). Installed the repository's pinned portable dependencies after the initial suite could not import FastAPI. These checks use mocks for fault execution.

## Remaining work

A fresh suitable baseline is required for live runs. Strategist needs persistence-aware prediction instructions and enforcement of fault diversity. Retain evidence validation and compare low reasoning against a timed default-effort run before claiming equal audit quality.

Timing evidence is published alongside this report in `LOW_REASONING_TIMING.json`. Detailed audit, plan, and history remain local under `runs/agents-20261010T175342Z/`; runtime checkpoints and secrets are not published.
