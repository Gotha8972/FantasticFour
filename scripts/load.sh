#!/usr/bin/env bash
set -Eeuo pipefail
PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
export KUBECONFIG="$PROJECT_DIR/.runtime/kubeconfig"
k() { kubectl --context kind-online-boutique -n online-boutique "$@"; }

diagnostics() {
  k get pods -l app=loadgenerator -o wide || true
  k describe pods -l app=loadgenerator || true
  k logs deployment/loadgenerator -c frontend-check --tail=100 || true
}

case "${1:-start}" in
  start)
    users="${2:-20}"
    rate="${3:-2}"
    [[ "$users" =~ ^[1-9][0-9]*$ && "$rate" =~ ^[1-9][0-9]*$ ]] || {
      echo 'Users and spawn rate must be positive integers.' >&2; exit 1;
    }
    trap diagnostics ERR
    k patch deployment/loadgenerator --type=strategic \
      --patch-file "$PROJECT_DIR/chaos/loadgenerator-observability.yaml"
    k set env deployment/loadgenerator "USERS=$users" "RATE=$rate"
    k scale deployment/loadgenerator --replicas=1
    echo 'Waiting for image downloads and the frontend-check init container…'
    k rollout status deployment/loadgenerator --timeout=10m
    echo 'Locust is ready. Verify traffic with: bash scripts/load.sh measure'
    echo 'Follow statistics with: bash scripts/load.sh logs'
    ;;
  logs) k logs -f deployment/loadgenerator -c main ;;
  measure)
    interval="${2:-5}"
    duration="${3:-30}"
    [[ "$interval" =~ ^[1-9][0-9]*$ && "$duration" =~ ^[1-9][0-9]*$ ]] || {
      echo 'Interval and duration must be positive integer seconds.' >&2; exit 1;
    }
    mkdir -p "$PROJECT_DIR/.runtime/load-reports"
    report="$PROJECT_DIR/.runtime/load-reports/sample-$(date +%Y%m%d-%H%M%S).txt"
    k exec -i deployment/loadgenerator -c main -- python - "$interval" "$duration" \
      < "$PROJECT_DIR/scripts/measure-load.py" | tee "$report"
    echo "Saved report: $report"
    ;;
  export)
    report_dir="$PROJECT_DIR/.runtime/load-reports/csv-$(date +%Y%m%d-%H%M%S)"
    mkdir -p "$report_dir"
    for suffix in stats stats_history failures; do
      k exec deployment/loadgenerator -c main -- cat "/stats/load_$suffix.csv" > "$report_dir/load_$suffix.csv"
    done
    echo "Saved CSV reports: $report_dir"
    ;;
  status) diagnostics ;;
  stop) k scale deployment/loadgenerator --replicas=0 ;;
  *) echo 'Usage: bash scripts/load.sh {start [USERS RATE]|measure [INTERVAL DURATION]|export|logs|status|stop}' >&2; exit 1 ;;
esac
