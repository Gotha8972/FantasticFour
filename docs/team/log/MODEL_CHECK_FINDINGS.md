# Model and implementation findings — 10 October 2026

## Summary

**A working intermediate model was found: `openai/gpt-oss-20b`, hosted by NVIDIA.** It passed a JSON probe, the repository's model ping, and a complete LangGraph dry run. It uses `NVIDIA_API_KEY` and NVIDIA's endpoint, not the OpenAI hosted API.

This establishes client and workflow compatibility. It does **not** establish that every prediction is correct or that a live demo is ready. Two reasoning problems appeared in the dry run, and the fresh baseline was unsuitable for live experiments.

No live faults, remediation, or replica changes were performed. The catalog remained at two replicas. Model overrides were scoped to individual commands; the default model was not changed.

## Model availability

These are real inference checks using the locally configured NVIDIA key, including a replacement key. A model appearing in NVIDIA's catalog did not guarantee that its inference endpoint was available to this account.

| Candidate | Result | What was established |
| --- | --- | --- |
| `openai/gpt-oss-20b` | Passed | JSON probe, repository ping, and LangGraph dry run |
| `nvidia/nemotron-3.5-lightning-30b-a3b` | Passed with thinking disabled | JSON probe only; no full agent run |
| `mistralai/mistral-7b-instruct-v0.3` | HTTP 404 | Configured default was unavailable to this account |
| `nvidia/nemotron-mini-4b-instruct` | HTTP 410 | Documented fallback was retired |
| `nvidia/nvidia-nemotron-nano-9b-v2` | HTTP 410 | Additional intermediate candidate was unavailable |
| Gemma 3 12B, Mistral NeMo 12B (both tested IDs), Phi 4 14B, Qwen 2.5 14B, StarCoder2 15B | HTTP 404 | Additional intermediate candidates failed |
| Gemma 3 27B | HTTP 410 | Additional intermediate candidate was unavailable |
| Other tested small candidates | HTTP 404 or 410 | None passed the inference probe |

The small-model sweep covered 30 candidate IDs with nominal sizes from 1B to 9B. It included Gemma, RecurrentGemma, Granite, DeepSeek Coder, SEA-LION, CodeGemma, Mistral, Zamba2, Phi Mini, Qwen, Llama, and Nemotron variants. These results describe the tested NVIDIA endpoints and account access; they do not establish unavailability on other providers.

The nominal GPT-OSS 20B model has approximately **21B total parameters and 3.6B active parameters**. Nemotron Lightning has **30B total parameters**, with 3B active per token. Active parameter counts must not be presented as total model sizes. Sources: [OpenAI model documentation](https://developers.openai.com/api/docs/models/gpt-oss-20b), [NVIDIA Nemotron model page](https://build.nvidia.com/nvidia/nemotron-3.5-lightning-30b-a3b/build).

### Probe results and request settings

- GPT-OSS returned `{"ok":true}` in the diagnostic JSON probe in **3.91 seconds**. The repository's `--ping` also returned `{'ok': True}`.
- Nemotron returned `{"ok":true}` in **2.96 seconds** when the request included `chat_template_kwargs: {"enable_thinking": false}`.
- The earlier Nemotron probe with a 128-token output limit exhausted the short output during reasoning. Receiving text established endpoint availability, but did not pass the JSON check.
- The repository client has **not** been changed to add Nemotron's thinking option. The successful diagnostic request should not be confused with a full workflow test.
- These are single-request timings, not representative latency benchmarks. The full GPT-OSS architecture audit took several minutes.

## GPT-OSS LangGraph dry run

Executed with a command-scoped model override:

```bash
NIM_MODEL=openai/gpt-oss-20b .venv/bin/python -m chaosmind.graph \
  --dry-run --budget 3 \
  --baseline runs/baseline-study-20261010T172032.762159Z/baseline.json
```

The explicitly supplied baseline was completed but **unsuitable**. This dry run evaluated model compatibility and reasoning only; it was not evidence that live injection should proceed.

| Output | Observation |
| --- | --- |
| Cartographer | 8 vulnerabilities; 0 rejected for unverifiable cited facts |
| Strategist | 3 proposals; 0 dropped |
| Fault coverage planned | `pod_kill`, `pod_failure`, `network_delay` |
| Redis proposal | 30-second pod kill with an `integrity_violations > 0` criterion |
| Other proposals | 30-second frontend pod failure; 500 ms cartservice delay for 30 seconds |
| Safety Checker | Reviewed and approved the first proposal only |
| Verdict | Inconclusive, as expected without fault injection or measured experiment results |

The two-replica catalog was ranked medium risk; the single-replica frontend and checkout service were ranked critical. This is a useful response to the collected replica configuration, but the following problems need attention.

### Reasoning and safety findings

1. **Unsupported Redis data-loss prediction.** The audit and plan predicted cart data loss, while collected Redis facts showed `volumes: ["persistentVolumeClaim"]` and `stateful_without_pvc: false`. A single replica can cause temporary unavailability; it does not by itself establish data loss. Zero rejected citations does not mean every causal claim was verified.
2. **Unsuitable baseline did not prevent model approval.** Safety explicitly acknowledged that the baseline was unsuitable, then approved based on current health. The dry run injected nothing. A deterministic baseline-suitability check is needed before treating this workflow as ready for live execution.
3. **Advertised preflight bounds are prompt instructions.** The reviewed code asks the model to shrink excessive checkout-path experiments to at most 500 ms and 30 seconds, but does not independently enforce those specific bounds. Existing validation and runtime guard limits remain in place; they are different controls.

## Fresh baseline and offline tests

**49 offline tests passed:** 16 guard tests, 29 agent/Day 2/capture tests, and 4 LangGraph tests. Fault and remediation output printed by those tests used mocks; it is not live experiment evidence.

The fresh baseline collected **41 samples over 306.088 seconds**, after warm-up, at 20 shoppers. Collection completed and supporting exports succeeded, but `baseline_suitable` was **false**.

| Window measurement | Result |
| --- | ---: |
| Completed requests | 1,307 |
| Failed requests | 4 |
| Window request error rate | 0.306% |
| Completed requests/second | 4.27 |
| Checkout requests | 56 |
| Checkout failures | 4 |
| Window checkout success | 92.86% |
| Maximum sampled recent p95 | 12,000 ms |
| Maximum sampled recent error rate | 8.33% |

Window measurements use counter differences. Recent p95 and error-rate samples are overlapping Locust estimates, not pooled statistics for the entire baseline.

Kubernetes events showed **paymentservice failing its liveness probe and restarting**. Its last termination had exit code 137 and reason `Error`, not `OOMKilled`. It subsequently became Ready. Host memory pressure and substantial swap usage were observed, but were not proven to be the cause of this restart.

The unsuitable baseline did not replace the existing root `baseline.json`. No live agent experiment or one-versus-two-replica trial was started.

## Ollama and local Llama

Ollama is installed, and `llama3:latest` is already cached. Local metadata identifies it as **Llama 3 8.0B, Q4_0**, with a download size of **4.34 GiB**.

A temporary server was started on `127.0.0.1:11434` to inspect metadata, then stopped. No model inference was performed. At the time of inspection, the host had about **2.7 GiB available RAM**, heavy swap usage, and no compatible GPU detected. Loading this model alongside the active cluster would need more memory headroom.

Ollama provides a local OpenAI-compatible endpoint and does not require a real API key for local inference. A NVIDIA key should not be used as the local Ollama credential. [Ollama documentation](https://docs.ollama.com/api/openai-compatibility).

## API key configuration check

The repository follows NVIDIA's hosted API authentication pattern:

- It explicitly reads `NVIDIA_API_KEY` from the project `.env`; an environment variable takes precedence.
- It sends the value in an `Authorization: Bearer …` header.
- It uses `https://integrate.api.nvidia.com/v1/chat/completions`.
- The replacement key reached working inference endpoints, so failures of the other models were not simply failure to load the key.
- `.env` is ignored by Git and untracked. Its permissions were tightened from `0644` to owner-only read/write, `0600`.
- Key values are omitted from this report and were not changed by the checks.

`.env` loading is implemented by the repository; it is not automatic expansion of NVIDIA's example placeholder. [NVIDIA API example](https://build.nvidia.com/nvidia/nemotron-3.5-lightning-30b-a3b/build).

## Recommended next steps

1. Use NVIDIA-hosted GPT-OSS 20B for the next dry-run iteration; it is the smallest candidate tested here that completed the existing agent workflow.
2. Correct the unsupported Redis data-loss reasoning and add deterministic checks for baseline suitability and the advertised preflight limits before a live demo.
3. Collect a suitable fresh baseline with adequate host resource headroom.
4. Repeat the risky-plan safety review, then perform the guarded live run and replica comparison.
5. Treat Nemotron 30B as another candidate after adding its documented request settings and completing the same workflow checks.

## Local evidence locations

The raw evidence is saved on the cluster laptop. This documentation commit does not publish those run directories or credentials.

- Model probes and key/Ollama checks: `runs/demo-implementation-20261010T172032Z/`
- GPT-OSS dry-run facts, audit, plan, history, and checkpoints: `runs/agents-20261010T173330Z/`
- Fresh baseline, metrics CSV, lifecycle events, workload snapshots, and supporting exports: `runs/baseline-study-20261010T172032.762159Z/`

Model availability and conclusions are specific to these checks on 10 October 2026.

## Status after review (same day)

- `openai/gpt-oss-20b` is now the **default** in `chaosmind/agents/llm.py`; no `NIM_MODEL` override is needed. Nemotron's thinking option can be passed with `NIM_EXTRA_BODY` without code changes.
- All three reasoning and safety findings are now **enforced in code with tests**: data-loss claims against persisted services are rejected, an unsuitable baseline rejects every experiment and blocks live runs, and the 500 ms / 60 s revenue-path bounds no longer depend on the prompt. Details and the next run steps: [MODEL_AND_IMPLEMENTATION.md](../MODEL_AND_IMPLEMENTATION.md).
