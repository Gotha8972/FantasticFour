# Redis persistence fix: cart survives pod replacement

Date: October 10, 2026. Application: Online Boutique on local kind,
namespace `online-boutique`.

**Finding:** before the persistence fix, replacing Redis silently emptied the
test cart. After the fix, the same-session cart retained its item when the Redis
pod was replaced.

## Before and after

| Measurement | Before fix | After fix |
| --- | --- | --- |
| Test cart before replacement | 1 item | 1 item |
| Test cart after replacement | **0 items** | **1 item** |
| Cart wiped | **True** | **False** |
| `/data` storage | `emptyDir` | PVC `redis-cart-data` |
| Replacement ready and cart accessible | 4.874 seconds | **3.342 seconds** |
| Failed HTTP samples observed | 0 | 0 |

The timing difference comes from one run per configuration and is not proof
of a performance improvement. Zero failed samples does not prove zero downtime.

Before evidence:
[`runs/c-redis-20261010T070925.577773Z/summary.json`](runs/c-redis-20261010T070925.577773Z/summary.json).
After evidence:
[`runs/c-redis-20261010T102251.009037Z/summary.json`](runs/c-redis-20261010T102251.009037Z/summary.json).

## Applied change

`bash scripts/redis-fix.sh apply` created a **1 GiB** PVC, mounted it at `/data`,
enabled Redis with `--appendonly yes`, and changed the Deployment strategy to
`Recreate`. The host output confirmed the PVC was **Bound**, the rollout
completed, and runtime `CONFIG GET appendonly` returned **yes**.

The test's saved deployment independently records the PVC mount,
`--appendonly yes` arguments, and `Recreate` strategy.
The initial switch replaced the old Redis pod; it did not migrate its previous
ephemeral cart data.

## Test method and results

Command: `bash tests/redis_finding.sh`.

The test created an isolated shopping session, added one item
(`OLJCESPC7Z`), saved the cart HTML, deleted the specifically observed Redis pod,
and waited for a different pod UID to become Ready. It then fetched the cart
using the same session and checked application health.

- Before replacement: **1 item**.
- After replacement: **1 item**, `cart_wiped: false`.
- First successful HTTP sample after the deletion request: **2.233 seconds**.
- Replacement ready and cart accessible: **3.342 seconds**.
- Recorded failed HTTP samples: **0**.

The test labels this result `FINDING` for both preserved and lost carts;
that label is not a failure status. The recorded counts and `cart_wiped` value
are the evidence that the graceful replacement check succeeded.

## Limits

This verifies one **graceful Kubernetes pod deletion/replacement**, not an
instantaneous process kill, host failure, or cluster deletion. The separate
instant-kill persistence check in `docs/team/A_REDIS_FIX_AND_FAULTS.md` is still
needed. This result does not establish that every acknowledged write survives
every kind of failure.

## After-fix evidence files

- [Structured result](runs/c-redis-20261010T102251.009037Z/summary.json)
- [Finding text](runs/c-redis-20261010T102251.009037Z/redis-finding.txt)
- [Saved Redis deployment](runs/c-redis-20261010T102251.009037Z/redis-deployment.json)
- [Cart before](runs/c-redis-20261010T102251.009037Z/cart-before.html)
- [Cart after](runs/c-redis-20261010T102251.009037Z/cart-after.html)
- [Lifecycle CSV](runs/c-redis-20261010T102251.009037Z/evidence.csv)
- [Lifecycle JSONL](runs/c-redis-20261010T102251.009037Z/evidence.jsonl)
- Redis, loadgenerator and Chaos Mesh daemon log CSVs in the same run directory.
