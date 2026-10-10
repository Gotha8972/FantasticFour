# Final runbook: Aashrith's laptop (for Claude Code + Aashrith)

Three tasks are left, in this order: **record the AI loop for the video → clean install from scratch → push.** The clean install deletes the cluster, so it must come last.

## Ground rules (read first)
- **Read first:** [README](../../README.md), [FINDINGS](../../FINDINGS.md), [MODEL_AND_IMPLEMENTATION](MODEL_AND_IMPLEMENTATION.md), [PRESENTATION_PLAN](PRESENTATION_PLAN.md).
- **Feature freeze:** don't change agent, guard, injector or scoring logic. Allowed: README/doc fixes that the clean install proves necessary; adding the new run to `chaosmind/agents/scoreboard.py`'s `EVIDENCE` list; regenerating reports.
- **Secrets:** never commit `.env`, `.runtime/` or `checkpoints.sqlite`. The model is NVIDIA-hosted `gpt-oss-20b` via `NVIDIA_API_KEY`; never use an OpenAI key.
- **Commits:** no `Co-Authored-By` or AI-attribution lines (team rule). `git pull` before editing: Srinavith's Claude also edits this repo.
- **Interactive steps belong to Aashrith.** The graph pauses with `Approve? [y/N]`, so **Aashrith runs it in his own terminal while screen recording** and types `y` on camera. Claude prepares the cluster before and verifies the results after. Claude never answers approval prompts and never uses `--auto-approve` for the video.
- **kubectl prefix:** `kubectl --kubeconfig .runtime/kubeconfig --context kind-online-boutique -n online-boutique`.
- **After every experiment:** `bash scripts/chaos.sh status` shows no podchaos/networkchaos/stresschaos, and all deployments are ready.

---

## Task 1: record the AI loop for the video (≈ 40 min)
The video must show the **AI's** moments: plan → safety shrink → integrity violation → approval gate → re-run → refuted after the fix. See [PRESENTATION_PLAN](PRESENTATION_PLAN.md).

1. **Update and test** (no API calls in the tests; expect 79 OK):
   ```bash
   git pull
   ```
   ```bash
   python3 -m chaosmind.test_guard && python3 -m unittest chaosmind.agents.test_agents chaosmind.agents.test_day2 chaosmind.test_c_tests && .venv/bin/python -m unittest chaosmind.test_graph tests.portable.test_workflow
   ```
2. **Health check:** all deployments ready, no active chaos, 20 shoppers running (`bash scripts/load.sh start 20 2` if not).
3. **Put the original weaknesses back**, so the AI has something to find and fix on camera. The fixes from last night are still applied.
   ```bash
   bash scripts/redis-fix.sh revert
   ```
   ```bash
   for d in frontend cartservice productcatalogservice; do kubectl --kubeconfig .runtime/kubeconfig --context kind-online-boutique -n online-boutique patch deployment $d --type=json --patch-file remediation/replicas-1.json; done
   ```
   Wait for the rollouts. `bash scripts/redis-fix.sh status` must show `emptyDir`, and each of the three deployments must show 1 replica.
4. **Fresh baseline** at this configuration. It must end with `baseline suitable: True`; it then becomes the root `baseline.json` automatically. If it doesn't, check memory (`free -h`, at least 4 GiB available) and repeat.
   ```bash
   bash scripts/baseline.sh --duration 300
   ```
5. **Recording (Aashrith).** Start the screen recorder: the terminal at a large font plus the Grafana *Chaos Overview* dashboard side by side. In your own terminal:
   ```bash
   .venv/bin/python -m chaosmind.graph --budget 3 --remediate
   ```
   Type `y` on camera at each approval. Expect about 15–20 minutes. Then, still recording, the safety test (it must print `shrink` with `500ms`/`30`, or `reject`):
   ```bash
   python3 -m chaosmind.agents.safety experiments/risky-checkout.json --review-only
   ```
6. **Claude verifies:**
   - the new `runs/agents-<time>/` contains `history.json` and `FINDINGS.md`
   - no active chaos remains
   - list each experiment's verdict, score, and remediation before → after and after-fix verdict
   - if anything looks wrong, write `runs/agents-<time>/OPERATOR_NOTES.md`: what happened and what the raw data shows
7. **Claude adds the run to the scoreboard.**
   - In `chaosmind/agents/scoreboard.py`, add `AI_RUN4 = 'runs/agents-<time>'` and one `EVIDENCE` row per experiment (`'agent'`), plus an `'agent-after'` row where a fix was applied.
   - Use the FINDINGS number of the matching weakness, or `None` for a refuted hypothesis.
   - Give the experiments **new names** (e.g. "…, recorded AI run"), so the before/after pairs don't collide with the existing ones.
   - Then:
   ```bash
   python3 -m chaosmind.agents.scoreboard > docs/evidence/SCOREBOARD.md && python3 -m unittest chaosmind.agents.test_day2
   ```
   Update the counts in README "Project status" (runs, experiments, confirmed/refuted, fixes proven) **only from the data**. If the AI chose a `network_delay`, add that the AI has now run 3 fault types itself.

## Task 2: clean install from scratch, recorded (≈ 60 min)
The brief asks for it, and it's the only way to prove the README works on a fresh setup. **Follow only the README.** Every step that fails or is missing is a README fix.

1. **Aashrith:** start the screen recorder.
2. **Delete the cluster** (only after Task 1 is pushed or saved):
   ```bash
   KIND_EXPERIMENTAL_PROVIDER=podman kind delete cluster --name online-boutique
   ```
3. **Fresh clone** into a new folder:
   ```bash
   git clone https://github.com/Gotha8972/FantasticFour ~/fresh-check && cd ~/fresh-check
   ```
4. Do the **README Quick start, in order, exactly as written**. Copy only `NVIDIA_API_KEY` from the old `.env` into a new `.env` (copied from `.env.example`). The check list:
   - `deploy-local.sh`, `install-chaos.sh`, `load.sh start 20 2`
   - venv + `pip install -r requirements.txt`
   - `python3 -m chaosmind.agents.llm --ping`
   - the README test command
   - `python3 -m chaosmind.guard experiments/test-delay.json`: one guarded experiment, which must revert on the p95 breach
   - `.venv/bin/python -m chaosmind.graph --dry-run`
   - optional: `bash scripts/install-monitoring.sh` and `bash scripts/monitoring.sh grafana`
5. **Time each step.** Note every failure, missing prerequisite or unclear instruction. Fix the README in the **original** folder, never in `~/fresh-check`; if you had to type something the README didn't say, the README must say it.
6. **Write `docs/evidence/CLEAN_INSTALL.md`:**
   - date, machine (OS, CPU, RAM), Podman and kind versions
   - each command with its duration and outcome
   - issues found and the README fixes made
   In README "Project status", change "Not done yet: the clean install…" to a line linking this report.

## Task 3: push (from the original folder)
```bash
git add README.md FINDINGS.md docs chaosmind/agents/scoreboard.py baseline.json; git add -f runs/agents-* runs/baseline-study-* runs/v*-*; git reset -q -- 'runs/*/checkpoints.sqlite*' 2>/dev/null; git status --short | grep -E '\.env|sqlite' || echo 'OK: no secrets or checkpoints staged'
```
It must print `OK: no secrets or checkpoints staged`. Then:
```bash
git commit -m "Recorded AI loop, clean install from scratch, scoreboard update" && git push
```

## After the push (humans)
- **Harshil** edits the video from the Task 1 recording, following the [storyboard](PRESENTATION_PLAN.md) (≤ 3:00; speed up the waiting; say the recorded numbers).
- Upload it, add the link at the top of the README, and submit the team form ([TEAM_FORM.md](../TEAM_FORM.md)) 30 minutes early.
