#!/usr/bin/env bash
# Reuse the fresh monitoring baseline; never restart the study or inject faults.
set -Eeuo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
export AI_PROVIDER=openai
export OPENAI_MODEL="${OPENAI_MODEL:-gpt-5.6-luna}"
export KUBECONFIG="$PWD/.runtime/kubeconfig"
python3 - <<'PYKEY'
from chaosmind.agents.llm import api_key, MODELS
api_key()
print(f'Provider: OpenAI; model: {MODELS["large"]}; key configured (value withheld).')
PYKEY
baseline_path="$(cat .runtime/checklist-baseline-path.txt)"
[[ -f "$baseline_path" ]] || { echo "Missing baseline: $baseline_path" >&2; exit 1; }
run_dir="runs/checklist-agent-retry-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$run_dir"
echo "Reusing baseline: $baseline_path"
python3 -u -m chaosmind.agents --dry-run --baseline "$baseline_path" \
  2>&1 | tee "$run_dir/agent-dry-run.log"
echo 'Dry run finished. Review docs/team/A_FINAL_CHECK.md in the updated team checkout before publishing.'
