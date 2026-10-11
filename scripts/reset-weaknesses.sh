#!/usr/bin/env bash
# Put Online Boutique back to its original weaknesses before a recorded AI run, so the AI has something to find and
# fix: Redis on emptyDir (no persistence) and one replica for every service a reviewed fix scales.
# Safe to run twice: it only reverts what is actually applied.
# Usage: bash scripts/reset-weaknesses.sh
set -Eeuo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
K=(kubectl --kubeconfig .runtime/kubeconfig --context kind-online-boutique -n online-boutique)

if "${K[@]}" get deploy redis-cart -o jsonpath='{.spec.template.spec.volumes[0].persistentVolumeClaim.claimName}' | grep -q .; then
  echo 'Redis persistence fix is applied: reverting it (empties current carts once).'
  bash scripts/redis-fix.sh revert >/dev/null
  # cartservice can keep a dead connection to the replaced Redis pod (~400 ms on every page) until it restarts.
  "${K[@]}" rollout restart deploy/cartservice >/dev/null
else
  echo 'Redis already on emptyDir.'
fi

# Every deployment a reviewed fix scales (remediation/catalog.json entries that use the replicas patch).
targets=$(python3 -c "import json; print(' '.join(sorted({f.get('deployment', f['target']) for f in json.load(open('remediation/catalog.json')) if f['patch'].endswith('replicas-2.json')})))")
for d in $targets; do
  if [[ "$("${K[@]}" get deploy "$d" -o jsonpath='{.spec.replicas}')" != 1 ]]; then
    "${K[@]}" patch deployment "$d" --type=json --patch-file remediation/replicas-1.json >/dev/null
    echo "$d: back to 1 replica."
  fi
done
for d in $targets redis-cart; do "${K[@]}" rollout status "deploy/$d" --timeout=180s >/dev/null; done

echo 'Original weaknesses restored:'
"${K[@]}" get deploy -o custom-columns=SERVICE:.metadata.name,REPLICAS:.spec.replicas --no-headers | awk '{print "  " $1 ": " $2 " replica(s)"}'
echo "  redis-cart volume: $("${K[@]}" get deploy redis-cart -o jsonpath='{.spec.template.spec.volumes[0].emptyDir}' | grep -q . && echo emptyDir || echo persistentVolumeClaim)"
echo 'Take a fresh baseline at this configuration before the recorded run: bash scripts/baseline.sh --duration 300'
