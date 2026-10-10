#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
CLUSTER_NAME=online-boutique
APP_VERSION=v0.10.4
STATE_DIR="$PROJECT_DIR/.runtime"
SOURCE_DIR="$PROJECT_DIR/microservices-demo"
export KUBECONFIG="$STATE_DIR/kubeconfig"
export KIND_EXPERIMENTAL_PROVIDER=podman
# Apply these overrides only to this invocation, preserving host Podman settings.
export CONTAINERS_CONF_OVERRIDE="$PROJECT_DIR/deploy/containers.conf"

for tool in kind kubectl podman git curl rg systemd-run; do
  command -v "$tool" >/dev/null || { echo "Missing required command: $tool" >&2; exit 1; }
done

if ! kubectl version --client; then
  echo 'kubectl failed to execute. Run bash scripts/install-kubectl.sh to install a verified binary.' >&2
  exit 1
fi

if ! podman info >/dev/null; then
  echo 'Podman is unavailable. Run this script in your regular host terminal.' >&2
  exit 1
fi

mkdir -p "$STATE_DIR/manifests"
chmod 700 "$STATE_DIR"

if [[ ! -d "$SOURCE_DIR" ]]; then
  git clone --depth 1 --branch "$APP_VERSION" \
    https://github.com/GoogleCloudPlatform/microservices-demo.git "$SOURCE_DIR"
fi
if [[ ! -f "$SOURCE_DIR/release/kubernetes-manifests.yaml" ]]; then
  echo "Missing upstream release manifest in $SOURCE_DIR" >&2
  exit 1
fi
if [[ "$(git -C "$SOURCE_DIR" describe --tags --exact-match HEAD)" != "$APP_VERSION" ]]; then
  echo "Expected $APP_VERSION in $SOURCE_DIR; refusing to change an existing checkout." >&2
  exit 1
fi
cp "$SOURCE_DIR/release/kubernetes-manifests.yaml" "$STATE_DIR/manifests/upstream.yaml"
cp "$PROJECT_DIR/deploy/kustomization.yaml" "$PROJECT_DIR/deploy/namespace.yaml" "$STATE_DIR/manifests/"
# Render before creating the cluster so invalid overlays fail early.
kubectl kustomize "$STATE_DIR/manifests" > "$STATE_DIR/rendered.yaml"

clusters="$(kind get clusters)"
if ! printf '%s\n' "$clusters" | rg -qx "$CLUSTER_NAME"; then
  echo 'Creating kind cluster with rootless Podman…'
  systemd-run --scope --user -p Delegate=yes \
    env KIND_EXPERIMENTAL_PROVIDER=podman \
        CONTAINERS_CONF_OVERRIDE="$CONTAINERS_CONF_OVERRIDE" \
    kind create cluster --name "$CLUSTER_NAME" \
      --config "$PROJECT_DIR/deploy/kind.yaml" \
      --kubeconfig "$KUBECONFIG" --wait 5m
else
  kind export kubeconfig --name "$CLUSTER_NAME" --kubeconfig "$KUBECONFIG"
fi
chmod 600 "$KUBECONFIG"

k() { kubectl --context "kind-$CLUSTER_NAME" "$@"; }
diagnostics() {
  echo 'Deployment failed; cluster diagnostics:' >&2
  k -n online-boutique get pods -o wide || true
  k -n online-boutique get events --sort-by=.metadata.creationTimestamp || true
}
trap diagnostics ERR

k apply -f "$STATE_DIR/rendered.yaml"
echo 'Waiting for application deployments (initial image downloads can take several minutes)…'
deployments="$(k -n online-boutique get deployments -o name)"
while IFS= read -r deployment; do
  [[ -n "$deployment" ]] || continue
  k -n online-boutique rollout status "$deployment" --timeout=10m
done <<< "$deployments"
k -n online-boutique get pods
curl --fail --silent --show-error --retry 12 --retry-delay 5 --retry-all-errors \
  --connect-timeout 5 --max-time 15 http://127.0.0.1:8080/ -o "$STATE_DIR/storefront.html"
curl --fail --silent --show-error --retry 12 --retry-delay 5 --retry-all-errors \
  --connect-timeout 5 --max-time 15 http://127.0.0.1:8080/cart -o "$STATE_DIR/cart.html"
echo 'Online Boutique is ready: http://localhost:8080'
echo "Kubeconfig: $KUBECONFIG"
echo 'The built-in load generator has zero replicas; the stress agent can control traffic.'
