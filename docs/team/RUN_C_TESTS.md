# For A: run C's remaining tests (≈10 min)

Run everything on your laptop, from the project folder.

## 1. Get the latest code
```bash
git pull
```

## 2. Start the fake shoppers (the guard needs live traffic)
```bash
bash scripts/load.sh start 20 2
```
Wait ~1 minute so the numbers settle.

## 3. Kill-switch tests (≈3 min)
```bash
./tests/killswitch.sh
```
It runs 3 tests and prints PASS/FAIL for each:
1. **Ad service down** → the kill switch should fire because a service is broken (not because of errors).
2. **Guard crashes (`kill -9`)** → the fault should still end by itself after 60s.
3. **Abort** → all faults are cleared instantly.

If test 1 says FAIL because `error_rate` fired first, that's not a bug. It means the shop breaks when ads are down, which is a finding. Just note it.

## 4. Redis cart test (≈1 min)
```bash
./tests/redis_finding.sh
```
It adds an item to a cart, restarts Redis, and checks whether the cart got wiped. The result is saved to `runs/redis-finding.txt`.

## 5. Clean up and push the evidence
```bash
python3 -m chaosmind.inject abort
```
```bash
git add runs && git commit -m "C: health trigger, fail-safe, abort, redis evidence" && git push
```
Leave the shoppers running if others are testing. Otherwise stop them:
```bash
bash scripts/load.sh stop
```

## If something breaks
Send the terminal output to the team chat. Don't delete anything in `runs/`; failed runs are evidence too.
