#!/usr/bin/env bash
# Redis cart persistence fix (finding #1): PVC + append-only log + Recreate strategy.
# Usage: bash scripts/redis-fix.sh apply | revert | status
# Applying/reverting replaces the redis-cart pod, which empties current carts once (that's the bug being fixed).
set -Eeuo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
K=(kubectl --kubeconfig .runtime/kubeconfig --context kind-online-boutique -n online-boutique)

status() {
  "${K[@]}" get deploy redis-cart -o jsonpath='volume: {.spec.template.spec.volumes[0]}{"\n"}args: {.spec.template.spec.containers[0].args}{"\n"}strategy: {.spec.strategy.type}{"\n"}'
  "${K[@]}" get pvc redis-cart-data --ignore-not-found
}

case "${1:-status}" in
  apply)
    if "${K[@]}" get deploy redis-cart -o jsonpath='{.spec.template.spec.volumes[0].persistentVolumeClaim.claimName}' | grep -q redis-cart-data; then
      echo "Already applied."; status; exit 0
    fi
    "${K[@]}" apply -f remediation/redis-persistence-pvc.yaml
    "${K[@]}" patch deploy redis-cart --type=json --patch-file remediation/redis-persistence-patch.json
    "${K[@]}" rollout status deploy/redis-cart --timeout=180s
    "${K[@]}" wait --for=jsonpath='{.status.phase}'=Bound pvc/redis-cart-data --timeout=60s
    "${K[@]}" exec deploy/redis-cart -- redis-cli CONFIG GET appendonly
    status ;;
  revert)
    "${K[@]}" patch deploy redis-cart --type=json --patch-file remediation/redis-persistence-revert.json
    "${K[@]}" rollout status deploy/redis-cart --timeout=180s
    "${K[@]}" delete -f remediation/redis-persistence-pvc.yaml --ignore-not-found
    status ;;
  status) status ;;
  *) echo "usage: $0 apply|revert|status" >&2; exit 2 ;;
esac
