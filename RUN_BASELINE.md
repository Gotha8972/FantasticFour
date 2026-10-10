# For A: capture the monitoring baseline (≈7 min)

**Why:** we need "what normal looks like" before breaking anything. It's a required Day-1 milestone ("normal error rate, latency and health captured under steady load"). C uses it to set sensible kill-switch limits, and D's AI uses it to judge how bad each failure was.

Run on your laptop, from the project folder. **Nothing else should be breaking the app during these 5 minutes.**

## 1. Get the latest code and make sure nothing is broken
```bash
git pull
```
```bash
python3 -m chaosmind.inject abort
```

## 2. Start steady traffic (skip if already running) and let it settle ~1 min
```bash
bash scripts/load.sh start 20 2
```
```bash
bash scripts/load.sh measure 5 30
```

## 3. Record 5 minutes of normal behaviour
```bash
python3 -m chaosmind.capture metrics --duration 300 --interval 2 --phase baseline --output runs/baseline-5min.csv
```

## 4. Turn it into a summary
```bash
python3 -m chaosmind.baseline_summary runs/baseline-5min.csv > baseline.json
```
```bash
cat baseline.json
```
It should show `samples` ≈ 150, plus mean/min/max for error rate, p95 latency, requests/sec and checkout success. `unhealthy_samples` should be **0**. If it isn't, something was broken during the baseline: fix it and redo step 3 with a new filename.

## 5. Push it (`-f` because `runs/` is ignored on your machine)
```bash
git add -f runs/baseline-5min.csv baseline.json && git commit -m "Add 5-min steady-load baseline" && git push
```

## Also push your code from the last round
`chaosmind/c_tests.py`, `chaosmind/test_c_tests.py`, `tests/README.md` and your edited `tests/*.sh` aren't on GitHub yet:
```bash
git status
```
```bash
git add chaosmind tests RUN_C_TESTS.md && git commit -m "Add C test runner" && git push
```
