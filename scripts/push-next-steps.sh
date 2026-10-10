#!/usr/bin/env bash
# Publish the required setup files and updated study code on existing remote history.
set -Eeuo pipefail
echo 'Disabled: this legacy publisher overwrites team checkpoint files with local copies.' >&2
echo 'Pull the updated repository and follow docs/team/A_FINAL_CHECK.md for publication.' >&2
exit 1
PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"
git fetch origin main
publish_tmp="$(mktemp -d)"
publish_checkout="$publish_tmp/repo"
git worktree add --detach "$publish_checkout" FETCH_HEAD
echo "Publication checkout: $publish_checkout"

for directory in scripts deploy chaos monitoring; do
  cp -a "$directory" "$publish_checkout/"
done
mkdir -p "$publish_checkout/tests" "$publish_checkout/chaosmind" "$publish_checkout/experiments"
cp -a tests/. "$publish_checkout/tests/"
cp -a experiments/. "$publish_checkout/experiments/"
cp COMPATIBILITY.md .gitignore README.md BASELINE_STUDY.md NEXT_STEPS_PROGRESS.md \
  PROJECT_HANDOFF.md A_CHECKLIST.md A_CHECKLIST_PROGRESS.md "$publish_checkout/"
# Copy Python source only; omit bytecode caches and local environment files.
while IFS= read -r -d '' source_file; do
  mkdir -p "$publish_checkout/$(dirname "$source_file")"
  cp "$source_file" "$publish_checkout/$source_file"
done < <(rg --files -0 chaosmind -g '*.py')
git -C "$publish_checkout" add scripts deploy chaos monitoring tests experiments COMPATIBILITY.md README.md \
  .gitignore BASELINE_STUDY.md NEXT_STEPS_PROGRESS.md PROJECT_HANDOFF.md A_CHECKLIST.md \
  A_CHECKLIST_PROGRESS.md chaosmind

# Only accepted root baselines are published; preserve every archived study separately.
if [[ -f baseline.json ]]; then
  cp baseline.json "$publish_checkout/"
  git -C "$publish_checkout" add -f baseline.json
fi
mkdir -p "$publish_checkout/runs"
shopt -s nullglob
for evidence in runs/baseline-study-* runs/checkout-investigation-* runs/grafana-pod-kill-* runs/grafana-stress-* runs/agents-* runs/checklist-*; do
  cp -a "$evidence" "$publish_checkout/runs/"
  git -C "$publish_checkout" add -f "runs/$(basename "$evidence")"
done
git -C "$publish_checkout" diff --cached --stat
if git -C "$publish_checkout" diff --cached --quiet; then
  echo 'No changes to publish.'
else
  git -C "$publish_checkout" commit -m "Complete platform checklist: setup, guard limits, monitoring and agent evidence"
  git -C "$publish_checkout" push origin HEAD:main
fi
# Verify required files exist in the newly fetched remote history.
git -C "$publish_checkout" fetch origin main
git -C "$publish_checkout" cat-file -e origin/main:monitoring/values.yaml
git -C "$publish_checkout" cat-file -e origin/main:scripts/install-monitoring.sh
# Keep a failed publication checkout for review/retry; remove successful checkouts.
git worktree remove "$publish_checkout"
rmdir "$publish_tmp"
