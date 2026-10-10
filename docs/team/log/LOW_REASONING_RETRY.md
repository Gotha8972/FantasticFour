# Retry after upstream 493d8cf

Model: NVIDIA-hosted `openai/gpt-oss-20b`, reasoning effort `low`.

- Audit: 30.191 seconds; 8 vulnerabilities, zero rejected evidence claims.
- Strategist: 12.422 seconds.
- Complete dry run: 48.950 seconds (previous: 45.167 seconds). Model outputs differ, so this is not a controlled performance comparison.
- Tests: 55 agent/day2/capture/graph/portable tests plus 16 guard tests passed (71 total). Fault operations in these tests are mocked.
- Strategist again predicted Redis cart data loss despite persistence. The NEW deterministic check dropped this proposal, recording the reason in `plan-1.json`. This verifies the filter in a real model run; it does not show that the model's reasoning was corrected.
- Only one valid experiment remained: 30-second cartservice `pod_failure`. Budget three is a maximum; the model returned two proposals and one was dropped.
- Diversity retry was false: the code skips corrective feedback when fewer than two valid experiments remain. This run therefore does not verify a varied plan or the feedback retry.
- Safety rejected the remaining experiment because the baseline is marked unsuitable. No safety LLM call, fault injection, or remediation occurred. Verdict is inconclusive.

The remaining prerequisite for a live run is a fresh suitable baseline. Planning could also refill rejected proposals and request varied faults after filtering leaves only one experiment.

Published evidence: `LOW_REASONING_RETRY_TIMING.json` and `LOW_REASONING_RETRY_PLAN.json` alongside this report. Full audit and history remain local in `runs/agents-20261010T180459Z/`.

## Status after review

- **Fixed:** a dropped proposal no longer just disappears. `strategist.plan()` sends every proposal code dropped (with code's reason) and any one-fault-type plan back to the model **once**, and adds the corrected proposals. In this run, the Redis kill would have come back with an availability prediction and its integrity criterion, instead of leaving only the cartservice failure. Recorded as `feedback` in `plan-N.json`; tested (71 total).
- After the demo reset (fixes reverted, Redis back on emptyDir), the data-loss prediction is true and is kept, so this filter doesn't affect the recorded run.
- **Still the only blocker:** a suitable baseline. See [MODEL_AND_IMPLEMENTATION.md](../MODEL_AND_IMPLEMENTATION.md), section 3, steps 0, 2 and 4.
