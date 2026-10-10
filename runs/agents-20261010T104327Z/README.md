# First successful OpenAI agent dry run

## Result

**The three agents completed the planning pipeline successfully.** This run demonstrates architecture auditing, experiment planning and safety review. It does not demonstrate live injection, rollback, recovery or hypothesis confirmation.

- Run: `agents-20261010T104327Z` (2026-10-10 10:43:27 UTC / 16:13:27 IST).
- Command: `bash scripts/retry-agent-dry-run.sh`.
- Configured provider/model: OpenAI / `gpt-5.6-luna`, low reasoning effort.
- Baseline: [`baseline-study-20261010T093022.185681Z`](../baseline-study-20261010T093022.185681Z/baseline.json).
- No faults were injected. Nothing was published automatically.

## What the agents did

| Agent | Saved result | Assessment |
|---|---|---|
| Cartographer | Eight ranked vulnerabilities; zero rejected; no evidence fields dropped | Configuration evidence matched the collected service facts. Rankings and predicted failure behavior remain hypotheses. |
| Strategist | Four validated, ranked pod-kill proposals; zero dropped | Produced executable experiment descriptions, predictions and measurable criteria. |
| Safety Checker | Approved the first proposal; unchanged target, fault and duration | Completed the review and passed the code check preventing enlargement or alteration. No execution occurred. |

### Cartographer: architecture audit

| Rank | Service | Severity | Suspected weakness |
|---|---|---|---|
| V1 | productcatalogservice | Critical | One replica, required by checkout, frontend and recommendations |
| V2 | redis-cart | Critical | One persistent datastore replica; restart can interrupt cart operations |
| V3 | cartservice | Critical | One service replica and a Redis dependency |
| V4 | paymentservice | Critical | One payment replica on the checkout path |
| V5 | checkoutservice | High | One orchestrator replica with six dependencies |
| V6 | frontend | High | One entrypoint replica for all shoppers |
| V7 | adservice | Low | Advertising is expected to degrade gracefully |
| V8 | recommendationservice | Low | Recommendations are expected to degrade gracefully |

The Redis audit correctly recognizes the new PVC. It identifies remaining availability risk, rather than repeating the previous temporary-storage finding. Persistence does not provide a second serving replica.

Zero rejected findings means their cited configuration fields matched saved facts; it does not prove their severity, blast radius or application behavior. The verifier does not independently validate every narrative statement, systemic observation or blind spot.

### Strategist: proposed experiments

The plan contains these four experiments, all with `pod_kill`, empty parameters and `duration_s: 30`:

1. `productcatalogservice`
2. `redis-cart`
3. `cartservice`
4. `paymentservice`

Only the first proposal received safety review in this dry run. Each proposal uses these confirmation criteria; **any one** observed criterion would confirm its hypothesis under the current evaluator:

| Metric | Criterion |
|---|---|
| Error rate | Greater than 0.05 (5%) |
| Unhealthy services | Greater than 0 |
| Request p95 latency | Greater than 300 ms |

These are hypothesis criteria, separate from the guard's stop limits: error rate 5%, p95 latency 1,000 ms and unhealthy count 2. The AI cannot change the guard limits.

The saved baseline has mean RPS 4.51, mean sampled error rate approximately 0.058%, and mean sampled request p95 34.69 ms. The plan's approximately 60 ms baseline reference matches the **95th percentile across sampled p95 measurements** (59.95 ms), not the mean request p95 or a percentile computed over all requests.

### Safety Checker: review

The checker approved `v1-pod-kill-productcatalogservice`. Its reason states that current health showed no unavailable services, zero current errors and latency within baseline ranges. Historical baseline errors and zero current errors can coexist.

The current health snapshot supplied to this review is not saved separately in this run, so those health assertions cannot be independently reconstructed from the artifacts alone.

- `ramp: [null]` / terminal `[None]`: pod kill has no adjustable intensity; this is the code's one-step marker.
- `steps: []`: no guarded execution took place.
- `observed: null`: no experiment measurements exist.
- `breaking point: None`: no breaking point was measured; this does not establish that none exists.
- `verdict: inconclusive`: expected for a dry run.
- `0 confirmed, 0 refuted`: no hypotheses were tested.

A pod kill is a one-time action. The 30-second duration does not mean the pod will remain down for 30 seconds; Kubernetes can recreate it sooner. The checker calling this a moderate duration is therefore an imprecise explanation of pod-kill severity.

## How the output looks

This is a successful integration result: all three model calls returned usable JSON, configuration verification accepted the audit, experiment validation accepted the plan, and safety review completed without an exception.

Before treating this as a complete resilience study, keep these limitations clear:

- The orchestrator started with empty history. Its statement that there was no prior experiment refers to this agent session; it did not import earlier catalog-kill or Redis studies.
- All four proposals use pod kill. Network, CPU and disk-failure reasoning have not been demonstrated by this run.
- Redis cart survival needs an explicit same-session integrity check; HTTP error rate, latency and pod health cannot establish that carts survived.
- Frontend is ranked below several dependencies despite being the sole entrypoint. This is a debatable AI prioritization, not a measured severity result.
- Graceful degradation for ads and recommendations is a prediction requiring an experiment.
- Approval does not prove the guard's live refusal, rollback or recovery behavior. Those require separate execution evidence.
- With `unhealthy_count > 0` as a confirmation criterion, ordinary replacement downtime alone can confirm a hypothesis even without customer-facing errors; interpret that verdict with the actual customer metrics.

## Artifacts

- [facts.json](facts.json): collected architecture and deployment facts.
- [vulnerabilities.json](vulnerabilities.json): verified evidence, rankings, hypotheses and blind spots.
- [plan-1.json](plan-1.json): four proposals, predictions and criteria.
- [history.json](history.json): first proposal's safety decision and inconclusive dry-run result.

No live experiment was started while documenting this run.
