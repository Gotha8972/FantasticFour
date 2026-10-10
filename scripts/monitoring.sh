#!/usr/bin/env bash
set -Eeuo pipefail
PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
export KUBECONFIG="$PROJECT_DIR/.runtime/kubeconfig"
k() { kubectl --context kind-online-boutique "$@"; }
case "${1:-status}" in
  grafana)
    echo 'Open http://127.0.0.1:3000/d/boutique-chaos/online-boutique-chaos-overview'
    trap 'exit 130' INT
    trap 'exit 143' TERM
    for attempt in 1 2 3 4 5; do
      if k -n monitoring port-forward --address 127.0.0.1 service/boutique-grafana 3000:80; then
        exit 0
      fi
      if (( attempt < 5 )); then
        echo "Grafana connection interrupted; reconnecting in 3 seconds (attempt $((attempt + 1))/5)."
        sleep 3
      fi
    done
    echo 'Repeated forwarding failures. Collect diagnostics: bash scripts/monitoring.sh grafana-diagnostics' >&2
    exit 1
    ;;
  grafana-diagnostics)
    k -n monitoring get pods -l app.kubernetes.io/name=grafana -o wide
    k -n monitoring describe pods -l app.kubernetes.io/name=grafana
    k -n monitoring logs deployment/boutique-grafana -c grafana --tail=80 || true
    k -n monitoring logs deployment/boutique-grafana -c grafana --previous --tail=80 || true
    k -n monitoring get events --sort-by=.metadata.creationTimestamp
    ;;
  repair-grafana)
    # Apply the committed memory budget without rolling Locust during a study.
    k -n monitoring patch deployment/boutique-grafana --type=strategic --patch '
{"spec":{"template":{"spec":{"containers":[{"name":"grafana","resources":{"requests":{"memory":"512Mi"},"limits":{"memory":"1Gi"}},"env":[{"name":"GOMEMLIMIT","value":"768MiB"}]}]}}}}'
    k -n monitoring rollout status deployment/boutique-grafana --timeout=5m
    k -n monitoring get pods -l app.kubernetes.io/name=grafana
    echo 'Memory repair applied. Restart access: bash scripts/monitoring.sh grafana'
    ;;
  prometheus)
    echo 'Open http://127.0.0.1:9090/targets for scrape health.'
    k -n monitoring port-forward --address 127.0.0.1 service/boutique-monitoring-prometheus 9090:9090
    ;;
  password)
    k -n monitoring get secret boutique-grafana -o jsonpath='{.data.admin-password}' | base64 --decode
    echo
    ;;
  status)
    k -n monitoring get pods,svc,servicemonitors
    k -n online-boutique get pods -l app=loadgenerator
    ;;
  exporter-logs)
    k -n online-boutique logs deployment/loadgenerator -c metrics-exporter --tail=60
    k -n monitoring logs deployment/boutique-chaos-observer --tail=60
    ;;
  *) echo 'Usage: bash scripts/monitoring.sh {grafana|grafana-diagnostics|repair-grafana|prometheus|password|status|exporter-logs}' >&2; exit 1 ;;
esac
