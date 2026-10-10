#!/usr/bin/env bash
set -Eeuo pipefail
PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"
STATE_DIR="$PROJECT_DIR/.runtime"
export KUBECONFIG="$STATE_DIR/kubeconfig"
export HELM_CONFIG_HOME="$STATE_DIR/helm/config"
export HELM_CACHE_HOME="$STATE_DIR/helm/cache"
export HELM_DATA_HOME="$STATE_DIR/helm/data"
HELM_BIN="$STATE_DIR/tools/helm"
CHART_VERSION=92.3.0
k() { kubectl --context kind-online-boutique "$@"; }
[[ -f "$KUBECONFIG" ]] || { echo 'Deploy Online Boutique first.' >&2; exit 1; }
# Fail with an actionable host fix before spending minutes waiting for pods.
if [[ -r /proc/sys/fs/inotify/max_user_instances && -r /proc/sys/fs/inotify/max_user_watches ]]; then
  read -r inotify_instances < /proc/sys/fs/inotify/max_user_instances
  read -r inotify_watches < /proc/sys/fs/inotify/max_user_watches
  if (( inotify_instances < 512 || inotify_watches < 524288 )); then
    cat >&2 <<'EOF'
Host inotify limits are below the recommended kind settings.
Run from the project folder, then rerun this installer:
  sudo install -m 0644 monitoring/99-boutique-inotify.conf /etc/sysctl.d/99-boutique-inotify.conf
  sudo sysctl --load /etc/sysctl.d/99-boutique-inotify.conf
EOF
    exit 1
  fi
fi
k cluster-info
k -n online-boutique get deployment/loadgenerator >/dev/null
k get crd/podchaos.chaos-mesh.org crd/networkchaos.chaos-mesh.org crd/stresschaos.chaos-mesh.org >/dev/null
python3 - <<'PY'
import sys
from chaosmind import inject
active = inject.running()
if active:
    sys.exit(f'Stop active faults before adding monitoring: {active}')
PY
bash "$PROJECT_DIR/scripts/install-helm.sh"
diagnostics() {
  k -n monitoring get pods,pvc -o wide || true
  k -n monitoring get events --sort-by=.metadata.creationTimestamp || true
  k -n online-boutique get pods -l app=loadgenerator -o wide || true
}
trap diagnostics ERR
"$HELM_BIN" repo add prometheus-community https://prometheus-community.github.io/helm-charts --force-update
"$HELM_BIN" repo update prometheus-community
"$HELM_BIN" upgrade --install boutique-monitoring prometheus-community/kube-prometheus-stack \
  --version "$CHART_VERSION" --namespace monitoring --create-namespace \
  --kube-context kind-online-boutique --values "$PROJECT_DIR/monitoring/values.yaml" \
  --wait --timeout 15m
k wait --for=condition=Established crd/servicemonitors.monitoring.coreos.com --timeout=120s
for namespace in online-boutique monitoring; do
  k -n "$namespace" create configmap boutique-metrics-exporter \
    --from-file=exporter.py="$PROJECT_DIR/monitoring/exporter.py" --dry-run=client -o yaml | k apply -f -
done
mkdir -p "$STATE_DIR/monitoring"
exporter_sha="$(sha256sum "$PROJECT_DIR/monitoring/exporter.py")"
exporter_sha="${exporter_sha%% *}"
for manifest in resources.yaml loadgenerator-patch.yaml; do
  sed "s/__EXPORTER_SHA__/$exporter_sha/g" "$PROJECT_DIR/monitoring/$manifest" \
    > "$STATE_DIR/monitoring/$manifest"
done
k apply -f "$STATE_DIR/monitoring/resources.yaml"
k -n monitoring create configmap boutique-chaos-dashboard \
  --from-file=boutique-chaos.json="$PROJECT_DIR/monitoring/dashboards/boutique-chaos.json" \
  --dry-run=client -o yaml | k apply -f -
k -n monitoring label configmap boutique-chaos-dashboard grafana_dashboard=1 --overwrite
echo 'Adding Locust exporter: this rollout resets live CSV counters in the loadgenerator pod.'
k -n online-boutique patch deployment/loadgenerator --type=strategic \
  --patch-file "$STATE_DIR/monitoring/loadgenerator-patch.yaml"
k -n online-boutique rollout status deployment/loadgenerator --timeout=10m
k -n monitoring rollout status deployment/boutique-chaos-observer --timeout=5m
k -n monitoring rollout status deployment/boutique-grafana --timeout=5m
# The operator creates this workload asynchronously after Helm installs its CR.
k -n monitoring wait --for=create statefulset/prometheus-boutique-monitoring-prometheus --timeout=180s
k -n monitoring rollout status statefulset/prometheus-boutique-monitoring-prometheus --timeout=5m
k -n monitoring get pods
echo 'Monitoring installed. Dashboard: bash scripts/monitoring.sh grafana'
echo 'Login username: admin. Get password: bash scripts/monitoring.sh password'
echo 'Prometheus: bash scripts/monitoring.sh prometheus'
echo 'No faults were started and the shopper replica count was preserved.'
