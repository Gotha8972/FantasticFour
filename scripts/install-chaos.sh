#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_DIR="$PROJECT_DIR/.runtime"
export KUBECONFIG="$STATE_DIR/kubeconfig"
export HELM_CONFIG_HOME="$STATE_DIR/helm/config"
export HELM_CACHE_HOME="$STATE_DIR/helm/cache"
export HELM_DATA_HOME="$STATE_DIR/helm/data"
HELM_VERSION=v3.19.0
CHAOS_VERSION=2.8.4
HELM_BIN="$STATE_DIR/tools/helm"
CLUSTER_CONTEXT=kind-online-boutique

for tool in kubectl curl tar sha256sum; do
  command -v "$tool" >/dev/null || { echo "Missing required command: $tool" >&2; exit 1; }
done
[[ -f "$KUBECONFIG" ]] || { echo 'Deploy Online Boutique first.' >&2; exit 1; }
k() { kubectl --context "$CLUSTER_CONTEXT" "$@"; }
k cluster-info
k get namespace online-boutique >/dev/null

# Install a pinned Helm into the workspace; no sudo or global Helm setup needed.
mkdir -p "$STATE_DIR/tools"
if [[ ! -x "$HELM_BIN" ]]; then
  case "$(uname -m)" in
    x86_64) helm_arch=amd64 ;;
    aarch64) helm_arch=arm64 ;;
    *) echo 'This installer supports Linux amd64 and arm64.' >&2; exit 1 ;;
  esac
  download_dir="$(mktemp -d "$STATE_DIR/helm-download.XXXXXX")"
  trap 'rm -rf -- "$download_dir"' EXIT
  archive="helm-$HELM_VERSION-linux-$helm_arch.tar.gz"
  curl --http1.1 --fail --location --retry 10 --retry-delay 3 --retry-all-errors \
    "https://get.helm.sh/$archive" -o "$download_dir/$archive"
  curl --http1.1 --fail --location --retry 10 --retry-delay 3 --retry-all-errors \
    "https://get.helm.sh/$archive.sha256sum" -o "$download_dir/$archive.sha256sum"
  (cd "$download_dir" && sha256sum --check "$archive.sha256sum")
  tar -xzf "$download_dir/$archive" -C "$download_dir"
  "$download_dir/linux-$helm_arch/helm" version --short
  install -m 0755 "$download_dir/linux-$helm_arch/helm" "$HELM_BIN"
fi
"$HELM_BIN" version --short

diagnostics() {
  echo 'Chaos Mesh installation failed; diagnostics:' >&2
  k -n chaos-mesh get pods -o wide || true
  k -n chaos-mesh get events --sort-by=.metadata.creationTimestamp || true
}
trap diagnostics ERR

"$HELM_BIN" repo add chaos-mesh https://charts.chaos-mesh.org --force-update
"$HELM_BIN" repo update chaos-mesh
"$HELM_BIN" upgrade --install chaos-mesh chaos-mesh/chaos-mesh \
  --version "$CHAOS_VERSION" --namespace chaos-mesh --create-namespace \
  --kube-context "$CLUSTER_CONTEXT" --values "$PROJECT_DIR/chaos/values.yaml" \
  --wait --timeout 15m

k annotate namespace online-boutique chaos-mesh.org/inject=enabled --overwrite
k wait --for=condition=Established --timeout=120s \
  crd/podchaos.chaos-mesh.org crd/networkchaos.chaos-mesh.org crd/stresschaos.chaos-mesh.org
workloads="$(k -n chaos-mesh get deployment,daemonset -l app.kubernetes.io/instance=chaos-mesh -o name)"
while IFS= read -r workload; do
  [[ -n "$workload" ]] || continue
  k -n chaos-mesh rollout status "$workload" --timeout=5m
done <<< "$workloads"

# Validate schemas and admission without injecting a fault.
k apply --dry-run=server -f "$PROJECT_DIR/chaos/experiments/" >/dev/null
k -n chaos-mesh get pods -o wide
echo 'Chaos Mesh installed. No experiments have been started.'
echo 'Dashboard: bash scripts/chaos.sh dashboard'
echo 'First experiment: bash scripts/chaos.sh start shipping-kill'
