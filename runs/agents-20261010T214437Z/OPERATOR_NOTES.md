# Operator notes: aborted attempt (not a result)

This run was stopped by the operator after two experiments. It measured nothing and is **not** part of any published result. The recorded AI run is [agents-20261010T215020Z](../agents-20261010T215020Z/).

**What happened:** the host was busy while recording started. A background system software update (`packagekitd`, `gnome-software`, `flatpak`: ~47% CPU) and the browser (~100% CPU) competed with the kind cluster for the same CPUs. The shop's tail latency rose (p95 1,500–1,700 ms) while the median stayed normal (p50 17–23 ms) and errors stayed at 0%. Five minutes earlier the same configuration measured p95 67 ms.

**What the safety layers did (as designed):**
- `v2-pod-failure-frontend`: the Safety Checker **rejected** it because the current health snapshot showed p95 1,700 ms against a ~54 ms baseline. Verdict: inconclusive.
- `v1-pod-kill-redis-cart`: the Safety Checker approved it (its snapshot read p95 100 ms), but the guard's own pre-flight snapshot 2 s later read p95 1,700 ms, so the guard **refused** to inject (`REFUSED: baseline unhealthy`, [events](../v1-pod-kill-redis-cart-s1-20261010T214553.823701Z/events.jsonl)). Verdict: inconclusive.

No fault was injected (`inject.running()` was empty before the operator stopped the run). After the update was paused, p95 held at 27–54 ms for 40 s and the run was restarted as agents-20261010T215020Z.
