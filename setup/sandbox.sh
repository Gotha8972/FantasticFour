#!/usr/bin/env bash
# One-shot sandbox setup: GitHub Codespace (4-core, via .devcontainer) or any Ubuntu 22.04/24.04 VM (4+ vCPU, 16+ GB).
# Brings up: Docker, kind cluster, Online Boutique, Chaos Mesh, Prometheus+Grafana.
# Re-runnable: each step skips if already done.
set -euo pipefail

CLUSTER=chaos
KIND_VER=v0.24.0

step() { echo -e "\n=== $* ==="; }

step "Docker"
if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker "$USER"
  echo "Docker installed. Log out/in (or run: newgrp docker) and re-run this script."; exit 0
fi

step "kind / kubectl / helm"
command -v kind >/dev/null || { curl -fsSLo kind "https://kind.sigs.k8s.io/dl/${KIND_VER}/kind-linux-amd64"; sudo install kind /usr/local/bin/; rm kind; }
command -v kubectl >/dev/null || { curl -fsSLO "https://dl.k8s.io/release/$(curl -fsSL https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"; sudo install kubectl /usr/local/bin/; rm kubectl; }
command -v helm >/dev/null || curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash

step "Raise inotify limits (kind + many pods hit 'too many open files' otherwise)"
sudo sysctl -w fs.inotify.max_user_watches=524288 fs.inotify.max_user_instances=512 >/dev/null

step "kind cluster"
kind get clusters | grep -qx "$CLUSTER" || kind create cluster --name "$CLUSTER"

step "Online Boutique"
kubectl create ns boutique --dry-run=client -o yaml | kubectl apply -f -
kubectl -n boutique apply -f https://raw.githubusercontent.com/GoogleCloudPlatform/microservices-demo/main/release/kubernetes-manifests.yaml

step "Chaos Mesh (containerd runtime, as kind uses)"
helm repo add chaos-mesh https://charts.chaos-mesh.org >/dev/null
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts >/dev/null
helm repo update >/dev/null
helm upgrade --install chaos-mesh chaos-mesh/chaos-mesh -n chaos-mesh --create-namespace \
  --set chaosDaemon.runtime=containerd \
  --set chaosDaemon.socketPath=/run/containerd/containerd.sock

step "Prometheus + Grafana"
helm upgrade --install monitoring prometheus-community/kube-prometheus-stack -n monitoring --create-namespace \
  --set grafana.adminPassword=admin

step "Waiting for pods"
kubectl -n boutique wait --for=condition=available deploy --all --timeout=600s
kubectl -n chaos-mesh wait --for=condition=available deploy --all --timeout=300s
kubectl -n monitoring wait --for=condition=available deploy --all --timeout=300s

cat <<'EOF'

All up. Expose UIs on the VM (run in a separate tmux pane):
  kubectl -n boutique   port-forward svc/frontend 8080:80
  kubectl -n monitoring port-forward svc/monitoring-grafana 3000:80
  kubectl -n monitoring port-forward svc/monitoring-kube-prometheus-prometheus 9090:9090
  kubectl -n chaos-mesh port-forward svc/chaos-dashboard 2333:2333

Codespaces: ports auto-forward (PORTS tab, private to your GitHub login).
VM: from your laptop (SSH tunnel, nothing public):
  ssh -L 8080:localhost:8080 -L 3000:localhost:3000 -L 9090:localhost:9090 -L 2333:localhost:2333 <user>@<vm-ip>
Then open http://localhost:8080 (shop), :3000 (Grafana admin/admin), :2333 (Chaos Mesh).
EOF
