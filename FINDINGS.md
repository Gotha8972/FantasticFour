# Findings report: resilience of Google Online Boutique

**Team FantasticFour** | Bosch Hackathon 2026 | AI-Driven Chaos Engineering for Cloud-Native Resilience

## Summary

We pointed ChaosMind, our AI chaos engineering system, at Google's Online Boutique: 10 microservices and a Redis cart store, running on Kubernetes. Across 8 live AI runs the AI chose 27 experiments covering 5 fault types. Code judged every one of them against pass/fail criteria the AI wrote before the experiment started: 24 hypotheses were confirmed and 3 were refuted. Together with our own experiments and a set of repeated trials, this produced the 11 findings ranked below.

The most serious finding is silent data loss. Restarting Redis empties every shopper's cart, yet every page keeps answering HTTP 200, so no error-rate dashboard ever notices. The frontend and the currency service each take the whole shop down when they fail. Network partitions are the most deceptive fault: customers waited up to 29 seconds for pages while not a single request failed.

The AI proposed 11 fixes from a catalog of reviewed changes. A person approved each one on screen, it was applied, and the identical experiment was run again. All 11 fixes scored higher, by 56 points on average, and 6 of the original hypotheses no longer held after the fix. Repeated trials show this is not luck: with one catalog replica, a pod kill hurt customers in 5 of 5 trials; with two replicas, in 0 of 5.

## How we tested

| Aspect | Details |
|---|---|
| System under test | Google Online Boutique v0.10.4 (Apache-2.0) on a local kind cluster with rootless Podman, namespace `online-boutique` |
| Load | Locust shoppers: 20 for normal operation, 100 for stress tests |
| Normal behaviour | Final baseline at 20 shoppers: 1,299 requests and 58 checkouts with zero failures, p95 latency 54 ms on average ([baseline](runs/baseline-study-20261010T211603.935532Z/BASELINE_RESULTS.md)). Earlier baselines: 0.05% to 0.07% errors ([baseline study](docs/evidence/BASELINE_STUDY.md)) |
| Faults | Chaos Mesh. Proven live: pod failure, pod kill, network delay, packet loss, network partition, CPU stress. Full disk cannot be injected on this application because its containers are read-only |
| Safety | Every fault ran under our kill switch, which reverts it when errors exceed 5%, p95 latency exceeds 1,000 ms or more than 2 services are unhealthy |
| Verdicts | The AI writes pass/fail criteria before each experiment. Code, not the AI, decides confirmed or refuted, and raises any threshold that normal noise could reach |
| Integrity checks | After each fault, code checks that a test cart still holds its item and that a real order still goes through. An HTTP 200 response alone is not trusted |
| Resilience score | 0 to 100: 100 minus penalties for extra errors (up to 40), extra p95 latency (up to 25), recovery time (up to 15), blast radius (up to 10, only when customers were hurt) and any integrity violation (40). Every score is recomputed from raw evidence by one command; the [scoreboard](docs/evidence/SCOREBOARD.md) lists all 44 scored experiments |

## Ranked findings

Ranked by severity (data loss, then outages, then slowdowns, then contained failures) and then by score. A lower score is worse.

| # | Finding | Severity | Key evidence | Score before | Score after fix | Status |
|---|---|---|---|---|---|---|
| 1 | Restarting Redis silently empties every cart | Critical | Test cart went from 1 item to 0 with no failed requests. The AI reproduced it in 4 live runs, once on camera with 0% errors | 13 to 43 | 50 to 81 | Data loss fixed and re-tested 4 times. Restarts still slow the cart |
| 2 | The frontend is a single point of failure | Critical | AI confirmed it in 4 runs: 100% errors, p95 20 s, customers back after 34 to 41 s | 17 to 18 | 96 | Fixed by the AI loop 3 times. A later pod kill on 2 replicas was absorbed |
| 3 | The currency service is a single point of failure | Critical | AI confirmed it twice: 100% errors, because every page shows prices; customers back after 31 to 43 s | 47 to 49 | not yet | Fix recommended |
| 4 | The cart service is a single point of failure | High | Manual test and 3 AI runs: errors up to 100%, customers back after 57 to 63 s | 30 to 31 | 78 to 95 | Fixed by the AI loop 3 times. Errors dropped from 100% to 0% to 2.6% |
| 5 | "Healthy" is not "recovered" | High | Catalog pod kill: pod ready in about 3 s, customers hurt for 32 to 38 s, in 5 of 5 trials (95% interval 57% to 100%) | 27 to 70 | 98 to 99 | Fixed: 0 of 5 trials hurt customers (95% interval 0% to 43%) |
| 6 | Network partitions hang customers without a single error | High | Catalog cut off from the frontend: p95 29 s. Payment cut off from checkout: p95 17 s. 0% errors both times, and the kill switch could not see it | 68 to 70 | not yet | Fix recommended |
| 7 | A payment outage hides inside the overall error rate | High | Overall errors peaked at 4.5% to 4.8%, under the 5% kill-switch limit, while 2 of 5 checkouts failed | 85 to 86 | not yet | Fix recommended |
| 8 | Checkout outages fail orders even after the dashboards recover | High | 30 s checkout outage: a test order failed with HTTP 500 4.3 s after the shop looked healthy. A quick restart was absorbed | 41 | not yet | Fix recommended |
| 9 | Slowness in an every-page service spreads site-wide | Medium | +500 ms on the catalog: site p95 3.5 s (4.3 s at 100 shoppers, reproduced). +500 ms on currency: 3.3 s. 30% packet loss on currency: 2.8 s | 77 to 81 | not yet | Fix recommended |
| 10 | About 1.3% of checkouts fail with nothing broken | Medium | 3 of 237 checkouts in fault-free baselines. Two causes found: rejected card types and payment restarts under memory pressure | n/a | n/a | Causes found |
| 11 | The ads service and Redis under CPU load are contained | Low | Ads down: 0% errors. Redis under CPU stress: 0% errors, p95 100 ms | 89 to 98 | n/a | Resilient |

## Fixes proven by running the same experiment again

Each fix came from the reviewed catalog in [`remediation/catalog.json`](remediation/catalog.json). In the AI runs, Remediation proposed it, a person approved it, and the identical experiment was repeated after customers had settled. Scores are from the [scoreboard](docs/evidence/SCOREBOARD.md).

| Fix | Experiment | Before | After | Gain | Criteria after the fix |
|---|---|---|---|---|---|
| 2 frontend replicas | Frontend down, AI run 3 | 18 | 96 | +78 | Refuted |
| 2 frontend replicas | Frontend down, AI run 5 (recorded) | 17 | 96 | +79 | Refuted |
| 2 frontend replicas | Frontend down, AI run 8 | 17 | 96 | +79 | Refuted |
| 2 catalog replicas | Catalog pod kill, AI run 2 | 70 | 98 | +28 | Refuted |
| 2 catalog replicas | Catalog pod kill, AI run 7 | 27 | 98 | +71 | Refuted |
| 2 catalog replicas | Catalog pod kill, 5 trials each | 29 | 99 | +70 | Customers hurt in 0 of 5 |
| 2 cart replicas | Cart pod kill, AI run 3 | 31 | 78 | +47 | Still met (p95 2.7 s) |
| 2 cart replicas | Cart pod kill, AI run 6 | 31 | 95 | +64 | Refuted |
| 2 cart replicas | Cart down, AI run 8 | 30 | 78 | +48 | Still met (2.6% errors) |
| Redis persistence | Redis pod kill, AI run 2 | 13 | 50 | +37 | Still met (errors during restart) |
| Redis persistence | Redis pod kill, AI run 5 (recorded) | 43 | 80 | +37 | Still met (latency only, cart kept) |
| Redis persistence | Redis pod kill, AI run 8 | 40 | 78 | +38 | Still met (latency only, cart kept) |
| Redis persistence | Redis restart, cart test | 40 | 81 | +41 | Cart kept |

"Refuted" here is the strongest proof a fix can get: the same criteria that confirmed the weakness no longer held.

## Findings in detail

### 1. Restarting Redis silently empties every cart (critical, fixed)
- **What we did:** put an item in a test cart, then restarted the `redis-cart` pod. The AI later chose the same experiment on its own and ran it in 4 live runs.
- **What happened:** the cart was empty afterwards, and every page kept answering HTTP 200 with the empty cart. In our cart test the load generator recorded no failed requests at all. In the recorded AI run (run 5) the AI's Redis kill emptied the cart with 0% errors. Our integrity check caught it every time.
- **Root cause:** Redis is a single replica that keeps its data on an `emptyDir` volume, which is deleted together with the pod.
- **Fix:** `bash scripts/redis-fix.sh apply` adds a PersistentVolumeClaim for `/data`, turns on Redis append-only logging (so data survives crashes, not only clean shutdowns) and switches the rollout to `Recreate`, so two Redis pods never share the disk.
- **Proof:** after the fix the cart kept its item in all 4 re-tests (cart test, runs 2, 5 and 8). Scores rose from 40 to 81 (cart test) and from 43 to 80 (recorded run).
- **What the fix does not solve:** Redis is still one replica, so during a restart cart requests still take 2 to 5.5 seconds (p95). The data is safe; the wait is not gone. Next step: retries in the cart service or a replicated Redis.
- **Evidence:** [before and after](docs/evidence/REDIS_FIX_RESULTS.md), [AI run 5](runs/agents-20261010T215020Z), [AI run 8](runs/agents-20261011T021019Z).

### 2. The frontend is a single point of failure (critical, fixed by the AI)
- **What happened:** the AI ranked the frontend first, because every service sits inside its blast radius, and took it down in 4 runs. Customers saw 100% errors and p95 of 20 seconds; customers were back 34 to 41 seconds after the fault started.
- **Fix:** Remediation chose `frontend-replicas` (2 replicas). After approval, the same experiment gave 0% errors and p95 under 100 ms, and customers were never affected. Score 17 to 96, three times. The same criteria were then refuted all three times. In run 7, a frontend pod kill with the 2 replicas in place caused no harm and was refuted as well.
- **Evidence:** [AI run 3](runs/agents-20261010T192511Z), [AI run 5](runs/agents-20261010T215020Z), [AI run 8](runs/agents-20261011T021019Z).

### 3. The currency service is a single point of failure (critical)
- **What happened:** the frontend calls the currency service on every page to show prices. Taking it down (run 4) or killing its pod (run 6) sent errors to 100%. Customers were back after 31 to 43 seconds. The score (47 to 49) is higher than the frontend's only because the requests failed fast instead of hanging.
- **Fix:** 2 replicas. The reviewed catalog has no currency fix yet, so Remediation correctly proposed none.
- **Evidence:** [AI run 4](runs/agents-20261010T200021Z), [AI run 6](runs/agents-20261011T013741Z).

### 4. The cart service is a single point of failure (high, fixed by the AI)
- **What happened:** with `cartservice` down, errors peaked at 100% and p95 at 2.7 to 2.9 seconds. Customers were back after 57 to 63 seconds, the slowest recovery we measured.
- **Fix:** 2 cart replicas, applied by the AI loop 3 times. Errors on the repeated experiment dropped to 0% (twice) and 2.6% (once). In run 6 the hypothesis was refuted after the fix; in runs 3 and 8 it still held, once on latency (2.7 s) and once on errors (2.6%). More replicas fix availability; they do not make each request faster.
- **Evidence:** [manual test](runs/test-down-20261010T062320.861245Z), [AI run 3](runs/agents-20261010T192511Z), [AI run 6](runs/agents-20261011T013741Z), [AI run 8](runs/agents-20261011T021019Z).

### 5. "Healthy" is not "recovered" (high, fixed and measured)
- **What happened:** after a catalog pod kill, Kubernetes had a replacement ready in about 3 seconds, but customers kept seeing errors. At 100 shoppers that meant 66 HTTP 500s and 16 of 179 checkouts failing over about 34 seconds. In AI run 7 the same kill reached 52% errors and p95 of 60 seconds. Pod health alone would have reported a 3 second blip.
- **Repeated trials** (20 shoppers, same customer limits, 5 trials each):

| Catalog replicas | Customers hurt | 95% interval | Pod back | Customers back |
|---|---|---|---|---|
| 1 | 5 of 5 | 57% to 100% | about 3 s | after 32 to 38 s (errors up to 96%, p95 up to 20 s) |
| 2 | 0 of 5 | 0% to 43% | about 3 s | never affected (errors at most 2.4%) |

  The two intervals do not overlap. In two of the one-replica trials traffic stalled completely, so the kill switch reverted early; they count as breaches because the errors that followed were measured.
- **Fix:** 2 catalog replicas, proven by the trials and twice inside the AI loop (scores 70 to 98 and 27 to 98, hypothesis refuted both times). Frontend retries with backoff would help further.
- **Evidence:** [1 replica trials](runs/trials-catalog-podkill-20261010T182606Z/trials.json), [2 replica trials](runs/trials-catalog-podkill-20261010T183121Z/trials.json), [AI run 2](runs/agents-20261010T185909Z), [AI run 7](runs/agents-20261011T015326Z).

### 6. Network partitions hang customers without a single error (high)
- **What happened:** the AI cut the catalog off from the frontend (run 8) and payment off from checkout (run 7). Requests did not fail; they hung. Page p95 reached 29 seconds and 17 seconds, with 0% errors, and customers were back 39 to 42 seconds after the cut began.
- **Why it matters:** error-rate monitoring sees nothing. Our own kill switch did not trip either, because the load generator only reports requests that have finished, so hung requests become visible only after the fault ends. The scores (68 and 70) understate the harm for the same reason. Our verdicts still caught it, because the recovery period is part of the measurement.
- **Fix:** client-side deadlines on every gRPC call, so a missing dependency fails fast, plus retries with backoff and a circuit breaker. Replicas do not help against a network fault, and Remediation correctly proposed none.
- **Evidence:** [AI run 7](runs/agents-20261011T015326Z), [AI run 8](runs/agents-20261011T021019Z).

### 7. A payment outage hides inside the overall error rate (high)
- **What happened:** the AI killed the single payment pod twice. The overall error rate peaked at only 4.5% and 4.8%, below the 5% kill-switch limit, because payment is used only by checkout and its failures are diluted by browsing traffic. In run 4, 2 of the 5 checkouts in that window failed.
- **Why it matters:** an aggregate error rate under-weights the revenue path. Our kill switch and our score use the aggregate too, so these outages scored 85 and 86 and never tripped the guard. One trial with 5 checkouts, so the exact checkout failure rate is uncertain.
- **Fix:** 2 payment replicas, and a checkout-specific error limit in monitoring and in our kill switch.
- **Evidence:** [AI run 4](runs/agents-20261010T200021Z), [AI run 6](runs/agents-20261011T013741Z).

### 8. Checkout outages fail orders even after the dashboards recover (high)
- **What happened:** in the recorded run the AI took `checkoutservice` down for 30 seconds. The overall error rate peaked at 7.1%. The kill switch reverted the fault, and our order check ran 4.3 seconds after the shop looked healthy again: it still received HTTP 500, so checkout was not yet taking orders. By contrast, a quick checkout pod kill in run 4 (replacement ready in 3.8 seconds) caused no measurable harm and was refuted.
- **Caveat:** one order check is one sample, and the fault-free baseline loses about 1.3% of checkouts. This supports finding 5 but does not prove it alone.
- **Fix:** 2 checkout replicas. The reviewed catalog has no checkout fix yet.
- **Evidence:** [AI run 5](runs/agents-20261010T215020Z), [AI run 4](runs/agents-20261010T200021Z).

### 9. Slowness in an every-page service spreads site-wide (medium)
- **What happened:** 500 ms of delay on the catalog pushed site-wide p95 from under 100 ms to 3.5 seconds at 20 shoppers, and to 4.3 and 4.4 seconds in two identical runs at 100 shoppers. The AI found the same pattern on the currency service: 500 ms of delay gave p95 of 3.3 seconds and 30% packet loss gave 2.8 seconds, with no errors. The kill switch tripped on latency in every one of these experiments; in the catalog tests it removed the fault within 0.33 seconds of tripping.
- **Root cause:** both services are called on every page (the catalog also by checkout and recommendations), as our generated dependency map predicted.
- **Fix:** client-side timeouts and caching of catalog and currency reads in the frontend.
- **Evidence:** [manual test](runs/test-delay-20261010T062255.501508Z), [AI run 7](runs/agents-20261011T015326Z), [AI run 8](runs/agents-20261011T021019Z).

### 10. About 1.3% of checkouts fail with nothing broken (medium)
3 of 237 checkouts failed with HTTP 500 across two fault-free baselines, always on `POST /cart/checkout`. We found two causes:
- **Rejected card types.** The load generator creates random Visa numbers, and the payment service rejects the ones its validator classifies as Visa Electron (`Sorry, we cannot process visa_electron credit cards`, [log](runs/baseline-study-20261010T093022.185681Z/frontend-logs.csv)). This is the only failure in the baseline whose logs cover it.
- **Memory pressure.** In a baseline taken while the host was short of memory, `paymentservice` failed its liveness probe and restarted, and 4 of 56 checkouts failed. With enough memory, 0 of 55 failed.

Fix: let the load generator send only card types the shop accepts, and give `paymentservice` memory headroom.

### 11. The ads service and Redis under CPU load are contained (low)
With `adservice` down, the customer error rate stayed at 0%: the frontend simply leaves the ad out, as the dependency map predicted. Redis under CPU stress kept serving with 0% errors and p95 of 100 ms. The kill switch still tripped on the ads outage through its service-health limit and reverted it in 0.38 seconds.

## Where the AI was wrong, and how code caught it

The AI is useful because code checks it. These are the cases where the check mattered.

**Hypotheses the evidence refuted**
- **Checkout pod kill (run 4):** the AI predicted customer harm; there was none (0% errors, p95 150 ms). Refuted. A 30 second outage later did cause harm (finding 8), so the result is about restarts, not outages.
- **Frontend pod kill with 2 replicas in place (run 7):** refuted, which confirms the fix.
- **Catalog pod kill (run 6):** the AI's only criterion was latency, but customers saw 54.5% errors, so code refuted a real outage. That was a gap in our verdict logic, not in the data. Since then code adds the kill switch's customer limits to every experiment, so an outage can no longer be refuted on a technicality.
- **After fixes:** 6 hypotheses were refuted when the identical experiment was repeated after the fix (frontend 3 times, catalog twice, cart once).

**Model output that code rejected or corrected**
- A Redis "data loss" claim on a service that already had a persistent volume was rejected as contradicting the facts.
- Pass/fail thresholds like "error rate > 0", which a single failed request would meet, were raised above normal noise (at least 1% errors).
- A deliberately risky experiment, 2,000 ms of delay on checkout for 120 seconds, was shrunk to 500 ms for 30 seconds by a code limit.
- A fix that was already applied was never offered again.
- In the AI's written reports, code marked claims the data contradicts: a PodDisruptionBudget that does not exist, "emptyDir" on a persistent volume, and a summary saying all failures were fixed when one was not. Numbers the model garbled were flagged by the numeric fact check.

## Safety record
- Every fault ran under the kill switch. All three triggers (error rate, latency, service health) fired live and removed the fault 0.30 to 0.39 seconds after the trip.
- Killing the kill switch itself with `kill -9` mid-fault did not leave the fault running: Chaos Mesh's own timer ended it. Manual abort cleared 2 active faults in 0.39 seconds.
- **An unsafe moment was blocked twice.** While recording, a system software update loaded the laptop and pushed the shop's p95 to 1.7 seconds before any fault. The Safety Checker rejected one experiment, and the kill switch refused to inject the next one. Nothing was injected ([operator notes](runs/agents-20261010T214437Z/OPERATOR_NOTES.md)).
- No experiment touched anything outside the `online-boutique` namespace. Evidence: [kill switch results](docs/evidence/KILLSWITCH_RESULTS.md).

## Limits of these results
- **Two blind spots in our kill switch,** both found with our own tool: it watches the aggregate error rate, so a revenue-only failure can stay under the limit (finding 7), and it sees only finished requests, so hung requests appear only after the fault ends (finding 6). It also needs 6 to 10 seconds to detect a breach, because the load generator reports a rolling window of about 10 seconds.
- **Most AI experiments ran once.** Only the catalog pod kill has repeated trials with confidence intervals; single runs show that a weakness exists, not how often it bites.
- **The AI's prose is not fully reliable.** Every number, verdict and score comes from code; the explanations are the model's and are marked where they contradict the data.
- **One cluster on one laptop.** Every result is relative to the baseline measured on that machine. Full disk could not be injected on this application.

## Evidence index

| AI run | Folder | Experiments | Notable |
|---|---|---|---|
| 1 | [agents-20261010T182208Z](runs/agents-20261010T182208Z) | 1 | First live run: Redis cart loss confirmed |
| 2 | [agents-20261010T185909Z](runs/agents-20261010T185909Z) | 3 | Redis and catalog fixes approved |
| 3 | [agents-20261010T192511Z](runs/agents-20261010T192511Z) | 3 | Frontend and cart fixes approved |
| 4 | [agents-20261010T200021Z](runs/agents-20261010T200021Z) | 3 | Currency and payment outages; checkout kill refuted |
| 5 | [agents-20261010T215020Z](runs/agents-20261010T215020Z) | 3 | Recorded for the demo video; fixes approved in mission control |
| 6 | [agents-20261011T013741Z](runs/agents-20261011T013741Z) | 4 | Cart fix 31 to 95 |
| 7 | [agents-20261011T015326Z](runs/agents-20261011T015326Z) | 4 | First network faults: partition and packet loss |
| 8 | [agents-20261011T021019Z](runs/agents-20261011T021019Z) | 6 | 5 fault types, 3 fixes approved |

Each run folder holds the AI's audit, every plan, the full history with verdicts and scores, and the AI's own report (`FINDINGS.md`, written by the Analyst agent and checked by code). Other evidence: [scoreboard](docs/evidence/SCOREBOARD.md) (every score, recomputed from raw events), [Redis fix](docs/evidence/REDIS_FIX_RESULTS.md), [kill switch](docs/evidence/KILLSWITCH_RESULTS.md), [baselines](docs/evidence/BASELINE_STUDY.md), and the `runs/` folder (CSV and JSON for every run).
