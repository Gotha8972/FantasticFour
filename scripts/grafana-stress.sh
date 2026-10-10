#!/usr/bin/env bash
set -Eeuo pipefail
PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"
export KUBECONFIG="$PROJECT_DIR/.runtime/kubeconfig"
kubectl --context kind-online-boutique -n monitoring get pods >/dev/null
python3 - <<'PY'
from chaosmind import inject
active = inject.running()
if active:
    raise SystemExit(f'Stop existing unrecovered experiments first: {active}')
PY
run_dir="$PROJECT_DIR/runs/grafana-stress-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$run_dir"
changed_load=false
cleanup() {
  result=$?
  trap - EXIT INT TERM
  if [[ "$changed_load" == true ]]; then
    echo 'Saving current high-load CSVs before returning to 20 shoppers.'
    for suffix in stats stats_history failures; do
      kubectl --context kind-online-boutique -n online-boutique \
        exec deployment/loadgenerator -c main -- cat "/stats/load_$suffix.csv" \
        > "$run_dir/load_$suffix.csv" || true
    done
    bash scripts/load.sh start 20 2 || result=1
  fi
  echo "Study output: $run_dir (guard artifacts are in their separately printed run folder)."
  exit "$result"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
phase() { printf '%s %s\n' "$(date -u +%FT%TZ)" "$*" | tee -a "$run_dir/phases.log"; }
changed_load=true
phase 'BASELINE: 20 shoppers for 60 seconds after rollout.'
bash scripts/load.sh start 20 2
bash scripts/load.sh measure 5 60 | tee "$run_dir/baseline.txt"
phase 'INCREASED LOAD: 100 shoppers, spawn rate 10/second, observe for 90 seconds.'
bash scripts/load.sh start 100 10
bash scripts/load.sh measure 5 90 | tee "$run_dir/high-load.txt"
phase 'FAULT: catalog delay 500ms, at most 120 seconds, with the existing guard.'
python3 -m chaosmind.guard experiments/grafana-delay.json | tee "$run_dir/guard.log"
phase 'RECOVERY: observe for 60 seconds at 100 shoppers before returning to 20.'
bash scripts/load.sh measure 5 60 | tee "$run_dir/recovery.txt"
phase 'FINISHED: returning to 20 shoppers.'
