# For A: Redis fix + new fault types + AI dry run (≈35 min)

All commands run from the project folder in a **normal terminal**, with shoppers running (`bash scripts/load.sh start 20 2`) and Grafana open.
Publish with plain `git add … && git commit && git push`, **not** `push-next-steps.sh` (it overwrites the README).

```bash
git pull
```
```bash
python3 -m chaosmind.test_guard && python3 -m unittest chaosmind.agents.test_agents
```

## 1. AI dry run (5 min, injects nothing). Still missing, do it first
```bash
python3 -m chaosmind.agents --dry-run
```
```bash
git add -f runs/agents-* && git commit -m "First agent dry run" && git push
```

## 2. Cover every fault type on the Bosch slide (≈15 min)
Each one has never run live. Run each **once** through the guard. Wait for `HEALTHY` before starting the next.

| Slide item | Command |
|---|---|
| Slow/lossy network (loss) | `python3 -m chaosmind.guard experiments/catalog-loss.json` |
| Overloaded database | `python3 -m chaosmind.guard experiments/redis-cpu.json` |
| Failed dependency | `python3 -m chaosmind.guard experiments/cart-redis-partition.json` |
| Full disk | `python3 -m chaosmind.guard experiments/redis-disk-full.json` |
| Service crash (instant kill via guard) | `python3 -m chaosmind.guard experiments/redis-podkill.json` |

(Delay and pod failure are already proven; the traffic spike is `scripts/grafana-stress.sh`.)

If one fails with `ERROR` (e.g. Chaos Mesh can't inject IOChaos), **that's fine. Keep the output**; it tells us what to change. Then:
```bash
git add -f runs && git commit -m "Live runs for all slide fault types" && git push
```

## 3. Redis fix: before vs after (≈15 min)
**Before** is already proven (`runs/c-redis-*`: cart 1 → 0 with zero errors). Now apply the fix:
```bash
bash scripts/redis-fix.sh apply
```
It creates a 1 Gi PVC, switches `/data` from `emptyDir` to that PVC, turns on Redis's append-only log, and uses the `Recreate` strategy. Expect `appendonly yes` and `persistentVolumeClaim` in the printed status. Applying replaces the Redis pod once, so carts that exist at that moment are lost; that's the bug being fixed.

**After, test A (graceful restart):** the same test as before. The cart should now **survive**:
```bash
./tests/redis_finding.sh
```

**After, test B (instant kill, no clean shutdown):** this is the case only the append-only log protects:
```bash
J=$(mktemp); curl -s -c $J -b $J localhost:8080/ >/dev/null
```
```bash
curl -s -c $J -b $J -d "product_id=OLJCESPC7Z&quantity=1" localhost:8080/cart >/dev/null; curl -s -b $J localhost:8080/cart | grep -c OLJCESPC7Z
```
```bash
python3 -m chaosmind.guard experiments/redis-podkill.json
```
```bash
curl -s -b $J localhost:8080/cart | grep -c OLJCESPC7Z
```
Before the kill, the count should be ≥1. **After, it should still be ≥1.** Save both numbers in `runs/redis-fix-after.txt`.

Push:
```bash
git add -f runs && git commit -m "Redis fix: before/after evidence" && git push
```
**Leave the fix applied** for the demo. To show "before" again live: `bash scripts/redis-fix.sh revert`.

## 4. Small fix in `baseline.py` (2 min)
`baseline.json` stores `/home/aashrith/...` in `artifact_dir`. Store the path relative to the project root.
