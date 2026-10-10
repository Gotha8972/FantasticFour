#!/usr/bin/env bash
# Finding #1: does a redis-cart restart wipe every customer's cart?
# Why we expect it (verified in release/kubernetes-manifests.yaml): redis-cart is 1 replica,
# data volume is `emptyDir: {}`, which is deleted with the pod.
# Needs: kubectl -n boutique port-forward svc/frontend 8080:80   Usage: ./tests/redis_finding.sh
set -euo pipefail
cd "$(dirname "$0")/.."
URL=${URL:-http://localhost:8080}; P=OLJCESPC7Z; J=$(mktemp); mkdir -p runs
c() { curl -s --max-time 3 -c "$J" -b "$J" "$@"; }

{
c "$URL/" >/dev/null
c -d "product_id=$P&quantity=1" "$URL/cart" >/dev/null
before=$(c "$URL/cart" | grep -c "$P" || true)
echo "cart before: product appears $before time(s)"
[ "$before" -gt 0 ] || { echo "item not in cart before the test, check port-forward"; exit 1; }

t0=$(date +%s)
kubectl delete pod -n boutique -l app=redis-cart          # waits until the old pod is gone
errors=0
until [ "$(c -o /dev/null -w '%{http_code}' "$URL/cart")" = 200 ]; do errors=$((errors+1)); sleep 1; done
echo "cart page back after $(( $(date +%s) - t0 ))s ($errors failed attempts)"

after=$(c "$URL/cart" | grep -c "$P" || true)
echo "cart after: product appears $after time(s)"
if [ "$after" = 0 ]; then
  echo "FINDING: a single redis-cart restart wiped the cart (1 replica + emptyDir, no persistence)."
  echo "FIX: PersistentVolumeClaim for /data (+ appendonly yes), or a replicated Redis."
else
  echo "Cart survived the restart, hypothesis rejected."
fi
} | tee runs/redis-finding.txt
