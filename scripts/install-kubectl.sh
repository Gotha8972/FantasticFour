#!/usr/bin/env bash
set -Eeuo pipefail

KUBECTL_VERSION=v1.37.0
DOWNLOAD_DIR="$(mktemp -d)"
trap 'rm -rf -- "$DOWNLOAD_DIR"' EXIT

curl --http1.1 --fail --location --retry 10 --retry-delay 3 --retry-all-errors \
  "https://dl.k8s.io/release/$KUBECTL_VERSION/bin/linux/amd64/kubectl" \
  -o "$DOWNLOAD_DIR/kubectl"
curl --http1.1 --fail --location --retry 10 --retry-delay 3 --retry-all-errors \
  "https://dl.k8s.io/release/$KUBECTL_VERSION/bin/linux/amd64/kubectl.sha256" \
  -o "$DOWNLOAD_DIR/kubectl.sha256"

cd "$DOWNLOAD_DIR"
printf '%s  kubectl\n' "$(cat kubectl.sha256)" | sha256sum --check
chmod 0755 kubectl
./kubectl version --client
# Replace the installed binary only after checking its checksum and execution.
sudo install -m 0755 kubectl /usr/local/bin/kubectl
/usr/local/bin/kubectl version --client
