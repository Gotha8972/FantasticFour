#!/usr/bin/env bash
# Publish only the incident entry points and Bash scripts on remote main.
set -Eeuo pipefail
PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"
git fetch origin main
publish_tmp="$(mktemp -d)"
publish_checkout="$publish_tmp/repo"
git worktree add --detach "$publish_checkout" FETCH_HEAD
echo "Publication checkout: $publish_checkout"

files=(incidents.py INCIDENTS.md chaosmind/incidents.py)
while IFS= read -r -d '' script; do
  files+=("$script")
done < <(rg --files -0 scripts -g '*.sh')

for source_file in "${files[@]}"; do
  mkdir -p "$publish_checkout/$(dirname "$source_file")"
  cp "$source_file" "$publish_checkout/$source_file"
done
git -C "$publish_checkout" add -- "${files[@]}"

# Enforce the exact publication scope before committing.
git -C "$publish_checkout" diff --cached --name-only -z | python3 -c '
import sys
names=[n.decode() for n in sys.stdin.buffer.read().split(b"\0") if n]
allowed={"incidents.py", "INCIDENTS.md", "chaosmind/incidents.py"}
unexpected=[n for n in names if n not in allowed and not (n.startswith("scripts/") and n.endswith(".sh"))]
if unexpected:
    sys.exit(f"Refusing unexpected staged files: {unexpected}")
print("Publication scope checked: incident source/docs and Bash scripts only.")'
git -C "$publish_checkout" diff --cached --stat
if git -C "$publish_checkout" diff --cached --quiet; then
  echo 'No incident or Bash script changes to publish.'
else
  git -C "$publish_checkout" commit -m "Add manual incident menu, scenarios and shell scripts"
  git -C "$publish_checkout" push origin HEAD:main
fi
# Preserve a failed publication worktree for diagnosis; remove only on success.
git worktree remove "$publish_checkout"
rmdir "$publish_tmp"
