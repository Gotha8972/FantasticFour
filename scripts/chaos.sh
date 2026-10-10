#!/usr/bin/env bash
set -Eeuo pipefail
PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
export KUBECONFIG="$PROJECT_DIR/.runtime/kubeconfig"
EXPERIMENT_DIR="$PROJECT_DIR/chaos/experiments"
k() { kubectl --context kind-online-boutique "$@"; }
usage() {
  echo 'Usage: bash scripts/chaos.sh {start|show|stop} EXPERIMENT'
  echo '       bash scripts/chaos.sh {status|stop-all|dashboard}'
  echo 'Experiments: shipping-kill, shipping-delay, currency-cpu, checkout-partition'
}

command="${1:-status}"
case "$command" in
  start|show|stop)
    experiment="${2:-}"
    case "$experiment" in
      shipping-kill|shipping-delay|currency-cpu|checkout-partition) ;;
      *) usage; exit 1 ;;
    esac
    file="$EXPERIMENT_DIR/$experiment.yaml"
    case "$command" in
      start)
        # create makes repeated runs explicit: stop/delete the old object first.
        k create -f "$file"
        echo "Requested $experiment. Check injection status with: bash scripts/chaos.sh show $experiment"
        ;;
      show) k get -f "$file" -o yaml; k describe -f "$file" ;;
      stop) k delete -f "$file" --ignore-not-found --timeout=120s ;;
    esac
    ;;
  status)
    k -n chaos-mesh get pods
    k -n online-boutique get podchaos,networkchaos,stresschaos
    ;;
  stop-all)
    k -n online-boutique delete podchaos,networkchaos,stresschaos \
      -l app.kubernetes.io/part-of=boutique-chaos --ignore-not-found --timeout=120s
    ;;
  dashboard)
    echo 'Open http://localhost:2333; keep this terminal running (Ctrl+C closes access).'
    k -n chaos-mesh port-forward --address 127.0.0.1 svc/chaos-dashboard 2333:2333
    ;;
  *) usage; exit 1 ;;
esac
