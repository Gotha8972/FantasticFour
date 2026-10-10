# For A: checklist before we test the AI agents

> **Historical planning note.** The project later switched its AI provider from Mistral to **OpenAI `gpt-5.6-luna`**. See the [README](../../README.md).

The dashboard and the pod-kill run are great. The "pod back in 3 s, customers back in 34 s" result is now in the README as a finding. 5 items, in order.

## ☐ 1. Push everything that's only on your laptop (≈5 min)
GitHub's `monitoring/` has **only the README**, and `scripts/` has **only `baseline.sh`**. Nobody else can install the dashboard or set up the cluster. Missing:

- `scripts/`: install-monitoring, monitoring, grafana-stress, grafana-pod-kill, deploy-local, install-kubectl, install-chaos, chaos, load, measure-load
- `monitoring/`: values.yaml, 99-boutique-inotify.conf, dashboard JSON, Locust exporter, chaos observer
- `deploy/`, `chaos/`, `tests/README.md`, `COMPATIBILITY.md`

```bash
git status
```
Make sure `.runtime/` and `microservices-demo/` are **not** listed (add them to `.gitignore` if they are), then:
```bash
git add scripts monitoring deploy chaos tests COMPATIBILITY.md .gitignore
```
```bash
git commit -m "Add setup, monitoring and chaos files" && git push
```
**Check** on https://github.com/Gotha8972/FantasticFour that `monitoring/values.yaml` and `scripts/install-monitoring.sh` are visible.

## ☐ 2. Which guard limits are real? (≈2 min)
`monitoring/README.md` says the guard trips at **5% errors / 1,000 ms**. But `chaosmind/guard.py` on GitHub still has **20% / 2,000 ms**.
- If you changed it locally: push `chaosmind/guard.py`.
- If not: tell the team, and we'll fix the monitoring README instead.

`README.md` ("Safety controls") currently says 20% / 2,000 ms. Update that line too if 5% / 1,000 ms is the real setting.

## ☐ 3. Fresh baseline with monitoring installed (≈7 min)
Your README says installing monitoring resets Locust counters and adds load, so the old baseline no longer matches. The agents read `baseline.json` to judge impact.
```bash
python3 -m chaosmind.inject abort
```
```bash
bash scripts/baseline.sh --duration 300
```
```bash
git add -f baseline.json runs/baseline-study-* && git commit -m "Baseline with monitoring installed" && git push
```
If it's still marked unsuitable because of a couple of background failures, push the run anyway and say so. We'll use its numbers.

## ☐ 4. Add the Mistral key (1 min)
Get the key from the team. Never commit it.
```bash
echo 'MISTRAL_API_KEY=...' >> .env
```

## ☐ 5. First AI run: dry run, nothing injected (≈3 min)
Keep Grafana open next to it.
```bash
git pull
```
```bash
python3 -m unittest chaosmind.agents.test_agents
```
```bash
python3 -m chaosmind.agents --dry-run
```
It should print the Cartographer's ranked vulnerabilities, the Strategist's first experiment, and the Safety Checker's decision and ramp. Push the output folder:
```bash
git add -f runs/agents-* && git commit -m "First agent dry run" && git push
```
**Don't run the live version (`--budget 3`) yet.** We'll review the dry-run plan together first.
