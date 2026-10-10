# For A: final pre-checkpoint items

## ⚠️ 1. Stop using `scripts/push-next-steps.sh` (do this first)
It copies **your local** `README.md`, `NEXT_STEPS_PROGRESS.md`, `A_CHECKLIST*.md` etc. over GitHub's version. `README.md` was fixed for the checkpoint, and the team notes moved to `docs/team/`, so a push from that script would **undo both**. `checklist.sh` calls it 3 times (lines 34, 58, 83).

- If `checklist.sh` is still running: let the dry run finish, but **Ctrl-C before the "publish" step**. If it already pushed, tell the team so we can restore the README.
- From now on, publish the normal way:
```bash
git stash
```
```bash
git pull
```
```bash
git stash pop
```
```bash
git add <your files> && git commit -m "..." && git push
```
If `git pull` complains about unrelated histories, your local folder isn't a clone. Clone the repo fresh and copy only `.runtime/` and `.env` into it:
```bash
git clone https://github.com/Gotha8972/FantasticFour.git
```
Then delete `scripts/push-next-steps.sh` and remove its 3 calls from `scripts/checklist.sh` (or delete `checklist.sh`; its job is done).

## 2. Finish the AI dry run (≈3 min, injects nothing)
The baseline from `checklist.sh` arrived (suitable ✅), but no agent output has come through yet. Run it directly:
```bash
python3 -m chaosmind.agents --dry-run
```
```bash
git add -f runs/agents-* && git commit -m "First agent dry run" && git push
```
If it fails, push the terminal output anyway; that's what we need to fix it.

## 3. Small fix: don't save your home folder path (≈2 min)
`baseline.json` contains `"artifact_dir": "/home/aashrith/Desktop/boschthon/runs/..."`. In `chaosmind/baseline.py`, store the path relative to the project root (e.g. `str(directory)` instead of the resolved absolute path). This takes effect on the next baseline; no need to re-run now.

## 4. Rehearse the checkpoint demo once (≈5 min)
Grafana open → `bash scripts/grafana-stress.sh` → narrate: shop at 20 shoppers → map / riskiest service → 100 shoppers → 500 ms catalog delay → guard trips at p95 ≈ 4,300 ms (limit 1,000) and reverts in 0.3 s → healthy in 14 s → "we ran it twice, same numbers".

## What changed today (so nothing surprises you after `git pull`)
- Internal notes moved to `docs/team/`: PLAN, DAY1, B/C guides, RUN_*, A_CHECKLIST*, NEXT_STEPS_PROGRESS. All links updated.
- Removed: `setup/sandbox.sh`, `.devcontainer/`, `chaosmind/baseline_summary.py` (superseded by your `baseline.py`).
- `cd /home/aashrith/...` lines in COMPATIBILITY / PROJECT_HANDOFF / chaos/README replaced with `cd FantasticFour`.
- README: Podman (not Docker) is required, plus `rg`; both baselines are shown side by side; it notes which runs used the old 20% / 2,000 ms limits; the 100-shopper delay runs are added; findings re-ranked, with a new one (checkout fails ~1.3% with nothing broken); quick demo section added.
