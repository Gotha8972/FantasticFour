# Agent bakeoff result — 2026-10-10

> **Historical.** The bake-off ran on OpenAI `gpt-5.6-luna`. The team now uses **our implementation only**, on NVIDIA-hosted `openai/gpt-oss-20b`; the alternative's best prompt rules were merged in, and its code was removed (recoverable at commit `709bd13`). See [MODEL_AND_IMPLEMENTATION.md](MODEL_AND_IMPLEMENTATION.md).

## Decision

Keep **`chaosmind.graph` + `chaosmind.agents`** as the team entry point. It won four directional metrics versus one in the first comparison, and two versus one in the repeat comparison. Both implementations passed the deliberately risky safety test. The alternative is archived in `alternatives/chaosmind_lc` (since removed; commit `709bd13`); the existing README, demo workflow and slides entry point remain valid.

We built two implementations and chose by measurement. The alternative covered more serious services; the existing implementation distinguished optional failures better and was faster in both comparisons. Counts of vulnerabilities or experiments are descriptive, not automatic wins; ordinary first safety decisions are also descriptive because the selected experiments differ.

## Shared contract and qualification

- Same frozen facts from `chaosmind.agents.facts.collect()`, same `baseline.json`, same captured health, same `inject.LIVE_VERIFIED` faults.
- Same OpenAI `gpt-5.6-luna`, low reasoning effort, through the existing `llm.py`.
- Three real model dry runs per implementation per comparison: **12 dry runs total**, plus **four risky safety reviews**. No API failures.
- Both output `facts.json`, `vulnerabilities.json`, `plan-1.json` and `history.json`; the unmodified team scoring script rechecked facts and experiment validity.
- The alternative gives models no command tools; it uses the shared fact verifier, experiment validator, `safety.only_smaller`, ramp rules and `strategist.evaluate`. Its entry point supports only dry runs. Live injection remains through the existing guarded team workflow.
- **No faults were injected and no remediation was applied.** Dry-run verdicts are inconclusive, not evidence of application resilience or measured failure probability.

Frozen inputs and their SHA256 fingerprints are recorded in each manifest. Health was deliberately held identical for comparison; its recorded age is not a fresh health check at every later model call. The baseline is an earlier completed measurement at 20 shoppers. Recollect health and establish a suitable current baseline before any future live run.

## Initial comparison

| Metric | Existing | Alternative |
|---|---:|---:|
| vulnerabilities | 8 | 7 |
| grounding: claims failing our fact check (lower better) | 0 | 0 |
| ranking: serious services rated critical/high (of 5) | 3.67 | 4.67 |
| ranking: optional services rated low/medium (of 2) | 1.33 | 0.67 |
| severity inflation: share rated critical (lower better) | 0.21 | 0.47 |
| plan: experiments | 4 | 4 |
| plan: share passing inject.validate | 1.0 | 1.0 |
| plan: distinct fault types | 3 | 2.33 |
| plan: trivial criteria (lower better) | 0 | 0 |
| plan: stateful targets with an integrity criterion | 1/1 / 1/1 / 1/1 | 1/1 / 1/1 / 1/1 |
| safety: first decision | reject / reject / reject | reject / approve / approve |
| wall time, seconds (lower better) | 39.67 | 45 |

Risky case (2,000 ms checkout delay for 120 s): **existing reject; alternative reject**. Both satisfy shrink/reject.

Evidence: [bakeoff-20261010T165006.772371Z manifest](../../runs/bakeoff-20261010T165006.772371Z/manifest.json), [raw score table](../../runs/bakeoff-20261010T165006.772371Z/scores.txt). The manifest lists all six artifact folders.

## Repeat after porting validation checks

| Metric | Existing | Alternative |
|---|---:|---:|
| vulnerabilities | 8 | 8 |
| grounding: claims failing our fact check (lower better) | 0 | 0 |
| ranking: serious services rated critical/high (of 5) | 4 | 4.33 |
| ranking: optional services rated low/medium (of 2) | 1.67 | 1 |
| severity inflation: share rated critical (lower better) | 0.29 | 0.29 |
| plan: experiments | 4 | 4 |
| plan: share passing inject.validate | 1.0 | 1.0 |
| plan: distinct fault types | 3 | 3 |
| plan: trivial criteria (lower better) | 0 | 0 |
| plan: stateful targets with an integrity criterion | 1/1 / 1/1 / 1/1 | 1/1 / 1/1 / 1/1 |
| safety: first decision | approve / reject / approve | reject / approve / approve |
| wall time, seconds (lower better) | 43 | 47.67 |

Risky case (2,000 ms checkout delay for 120 s): **existing reject; alternative shrink**. Both satisfy shrink/reject.

Evidence: [bakeoff-20261010T165551.289790Z manifest](../../runs/bakeoff-20261010T165551.289790Z/manifest.json), [raw score table](../../runs/bakeoff-20261010T165551.289790Z/scores.txt). The manifest lists all six artifact folders.

## Ideas ported into the winner

The planner now rejects an experiment whose target does not match its cited audited vulnerability. Redis trials also require an integrity criterion in code, rather than relying only on the prompt. Neither change permits additional faults or bypasses `guard.run`.

The repeat retained zero grounding failures, 100% experiment validity, zero trivial pod criteria, and integrity criteria for every Redis experiment. Serious-service and optional-service coverage improved in that sample. Critical severity share and wall time rose between samples; these small, stochastic comparisons do not isolate a causal effect of the code changes. We claim preserved validation/safety results, not an improvement on every metric.

## Verification and portable agent

**68 tests pass:** 47 existing regression tests and 21 new portable/bakeoff tests. Added tests cover scope mismatch, missing integrity criteria, model enlargement, risky-case bounds, cancellation, cleanup failure, recovery, replay and API authentication.

The application-configured package is separately documented in [PORTABLE.md](../agent-workflow/PORTABLE.md). Its two offline application demos and read-only Kubernetes discovery succeeded. Its generic live executor is experimental and was not the bakeoff candidate or a substitute for the team's live-verified guard. Native agents.ai deployment remains unverified.

The next live recording is a separate rehearsal requiring fresh telemetry and an appropriate baseline; this bakeoff did not run it.

## Post-bake-off fix: cumulative counters
In the risky-case test, both Safety Checkers justified their decision with "checkout success 98.90% is below the baseline minimum 99.76%". Both numbers come from a **cumulative** counter (since the load generator started, including failures from earlier chaos tests), so this wasn't evidence of current degradation; the baseline's own measured window was 98.55%. The decisions were still correct (shrink/reject a 2,000 ms, 120 s checkout delay), but partly for the wrong reason. Fix: cumulative counters (`checkout_success`, `checkout_requests`, `checkout_failures`, `requests`, `failures`) are no longer shown to the AI, and the baseline's cumulative checkout series is replaced by its window value (`safety.current_health`, `steps.load_baseline`; test `test_safety_never_sees_cumulative_counters`). Re-run the risky-case review once before the live recording.
