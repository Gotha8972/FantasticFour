#!/usr/bin/env bash
# Collect local checklist evidence only; agent execution is dry-run only.
set -Eeuo pipefail
PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"
export KUBECONFIG="$PROJECT_DIR/.runtime/kubeconfig"
export MISTRAL_LARGE=mistral-small-2603
export MISTRAL_SMALL=mistral-small-2603

# Validate presence without echoing or sourcing the secret file.
python3 - <<'PY'
from chaosmind.agents.llm import api_key
if not api_key():
    raise SystemExit('MISTRAL_API_KEY is empty; set it locally in .env first.')
print('Mistral key is configured (value withheld). Model: mistral-small-2603.')
PY
monitoring_pods="$(kubectl --context kind-online-boutique -n monitoring get pods -o json)"
python3 -c '
import json, sys
pods=json.load(sys.stdin)["items"]
for prefix in ("boutique-grafana-", "prometheus-boutique-monitoring-prometheus-"):
    ready=[p for p in pods if p["metadata"]["name"].startswith(prefix)
           and not p["metadata"].get("deletionTimestamp")
           and any(c["type"] == "Ready" and c["status"] == "True"
                   for c in p.get("status", {}).get("conditions", []))]
    if not ready:
        sys.exit(f"Monitoring is not ready: {prefix}; fix it before the fresh baseline.")
print("Grafana and Prometheus are ready.")' <<< "$monitoring_pods"

mkdir -p .runtime runs
run_dir="runs/checklist-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$run_dir"
echo 'Collecting local evidence. This script does not commit or publish files.'

echo 'Clearing Python-owned faults before a fresh 300-second baseline.'
python3 -m chaosmind.inject abort | tee "$run_dir/abort.log"
touch .runtime/checklist-baseline-start
baseline_exit=0
bash scripts/baseline.sh --duration 300 | tee "$run_dir/baseline.log" || baseline_exit=$?
echo "Baseline command exit: $baseline_exit" | tee -a "$run_dir/baseline.log"
python3 - <<'PY'
import json
from pathlib import Path
marker=Path('.runtime/checklist-baseline-start').stat().st_mtime_ns
candidates=[p for p in Path('runs').glob('baseline-study-*/baseline.json')
            if p.stat().st_mtime_ns >= marker]
if not candidates:
    raise SystemExit('No fresh baseline artifact; inspect the checklist log.')
p=max(candidates, key=lambda p:p.stat().st_mtime_ns)
b=json.loads(p.read_text())
if b.get('status') != 'completed' or not b.get('metrics') or not b.get('window'):
    raise SystemExit(f'Fresh baseline failed; no agent calls will be made. Evidence: {p}')
Path('.runtime/checklist-baseline-path.txt').write_text(str(p))
print(f'Fresh baseline: {p}; suitable={b.get("baseline_suitable")}; findings={b.get("findings", [])}')
PY
echo 'Running the requested offline agent tests.'
python3 -m unittest chaosmind.agents.test_agents 2>&1 | tee "$run_dir/agent-tests.log"
baseline_path="$(cat .runtime/checklist-baseline-path.txt)"
echo 'Requesting the agent plan and safety review. No faults will be injected.'
touch .runtime/checklist-agents-start
python3 -m chaosmind.agents --dry-run --baseline "$baseline_path" \
  2>&1 | tee "$run_dir/agent-dry-run.log"
python3 - <<'PY'
import json
from pathlib import Path
marker=Path('.runtime/checklist-agents-start').stat().st_mtime_ns
histories=[p for p in Path('runs').glob('agents-*/history.json')
           if p.stat().st_mtime_ns >= marker]
if not histories:
    raise SystemExit('Dry run produced no first experiment/safety review; inspect runs/agents-* before proceeding.')
p=max(histories, key=lambda p:p.stat().st_mtime_ns)
history=json.loads(p.read_text())
if not history or history[0]['safety']['decision'] not in ('approve', 'shrink', 'reject'):
    raise SystemExit(f'Dry-run review is incomplete: {p}')
if any(item['safety'].get('steps') for item in history):
    raise SystemExit('Unexpected injection steps in dry-run evidence; stop for review.')
print(f'Dry-run plan and safety review recorded: {p}; no injection steps.')
PY
echo "Local checklist sequence complete. Review evidence in $run_dir and runs/agents-*."
echo 'Read docs/team/A_FINAL_CHECK.md from the updated team checkout before publishing anything.'
