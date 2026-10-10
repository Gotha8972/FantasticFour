#!/usr/bin/env bash
set -Eeuo pipefail
PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
HELM_BIN="$PROJECT_DIR/.runtime/tools/helm"
if [[ -x "$HELM_BIN" ]]; then
  "$HELM_BIN" version --short
  exit 0
fi
case "$(uname -m)" in
  x86_64) helm_arch=amd64 ;;
  aarch64) helm_arch=arm64 ;;
  *) echo 'Supported platforms: Linux amd64/arm64.' >&2; exit 1 ;;
esac
mkdir -p "$PROJECT_DIR/.runtime/tools"
download_dir="$(mktemp -d "$PROJECT_DIR/.runtime/helm-download.XXXXXX")"
trap 'rm -rf -- "$download_dir"' EXIT
archive="helm-v3.19.0-linux-$helm_arch.tar.gz"
for suffix in '' .sha256sum; do
  curl --http1.1 --fail --location --retry 10 --retry-all-errors \
    "https://get.helm.sh/$archive$suffix" -o "$download_dir/$archive$suffix"
done
(cd "$download_dir" && sha256sum --check "$archive.sha256sum")
tar -xzf "$download_dir/$archive" -C "$download_dir"
install -m 0755 "$download_dir/linux-$helm_arch/helm" "$HELM_BIN"
"$HELM_BIN" version --short
