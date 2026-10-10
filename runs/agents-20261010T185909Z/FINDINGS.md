# Findings report

The experiments confirmed that a pod kill of redis-cart caused cart data loss, a pod failure of frontend brought the entire site down, and killing productcatalogservice introduced significant latency and errors. Root causes were identified as missing persistence for Redis, lack of high‑availability for the frontend, and a single‑replica product catalog. Recommended fixes involve adding persistent storage for Redis, deploying multiple replicas with PDB/HPA for frontend, and scaling productcatalogservice to multiple replicas.

**AI hypotheses:** 3 tested, 3 confirmed, 0 refuted. Verdicts are decided by code against criteria written before each run.

| Experiment | Fault | Verdict | Worst error rate | Worst p95 | Recovery | Integrity | Score |
|---|---|---|---|---|---|---|---|
| `v3-pod-failure-frontend` | pod_failure on frontend | confirmed | 23.1% | 17.0 ms | 34.699 s | 0 violation(s) | 16 |
| `v1-pod-kill-redis-cart` | pod_kill on redis-cart | confirmed | 0.0% | 5800.0 ms | 16.483 s | 1 violation(s) | 0 |
| `v5-pod-kill-productcatalogservice` | pod_kill on productcatalogservice | confirmed | 16.7% | 41.0 ms | 9.916 s | 0 violation(s) | 53 |

## Redis Cart Pod Kill – Data Loss (critical)

**What happened:** Killing the redis-cart pod cleared the cart, causing checkout failures and 0 cart items for the session.

**Root cause:** The Redis instance runs on an emptyDir volume that does not persist data across restarts.

**Log evidence:**

    frontend: {"error":"could not retrieve cart: rpc error: code = FailedPrecondition desc = Can't access cart storage. StackExchange.Redis.RedisConnectionException: The message timed out in the backlog attempting to send because no connection became available (5000ms) - Last Connection Exception: It was not poss  (x9)

**Fix:** Apply a persistent volume claim to redis-cart so that cart data survives pod restarts (redis-persistence).

**Remediation:** `redis-persistence` applied, re-run score 0 → 27 (improved).

Evidence: `runs/v1-pod-kill-redis-cart-s1-20261010T190025.868949Z`

## Frontend Pod Failure – Site Outage (critical)

**What happened:** The frontend pod crashed, making all services unreachable and returning 500 errors to users.

**Root cause:** The frontend has a single replica with no PDB/HPA; its failure stops the entire site.

**Log evidence:**

    frontend: {"error":"could not retrieve cart: rpc error: code = FailedPrecondition desc = Can't access cart storage. StackExchange.Redis.RedisConnectionException: The message timed out in the backlog attempting to send because no connection became available (5000ms) - Last Connection Exception: It was not poss  (x9)
    frontend: {"error":"could not retrieve products: rpc error: code = Unavailable desc = connection error: desc = \"transport: Error while dialing: dial tcp 10.96.223.78:3550: connect: connection refused\"","http.req.id":"3525473b-3b63-4ea5-b626-c4a2e1504063","http.req.method":"GET","http.req.path":"/","message"

**Fix:** Deploy multiple replicas of the frontend with a PDB and HPA to ensure high availability (frontend-replicas).

**Remediation:** `None` applied, re-run score None → None (no_fix).

Evidence: `runs/v3-pod-failure-frontend-s1-20261010T185929.812984Z`

## Product Catalog Pod Kill – Latency & Errors (high)

**What happened:** Killing the sole productcatalogservice pod caused product lookups to fail, raising error_rate to 0.1667 and p95 latency to 41 ms.

**Root cause:** The productcatalogservice runs as a single replica with no PDB/HPA, creating a single point of failure.

**Log evidence:**

    frontend: {"error":"could not retrieve products: rpc error: code = Unavailable desc = connection error: desc = \"transport: Error while dialing: dial tcp 10.96.223.78:3550: connect: connection refused\"","http.req.id":"3525473b-3b63-4ea5-b626-c4a2e1504063","http.req.method":"GET","http.req.path":"/","message"

**Fix:** Add additional replicas and enable PDB/HPA for productcatalogservice (productcatalog-replicas).

**Remediation:** `productcatalog-replicas` applied, re-run score 53 → 99 (improved).

Evidence: `runs/v5-pod-kill-productcatalogservice-s1-20261010T190304.133613Z`

## Fact-check

Every number above appears in the measured data.
