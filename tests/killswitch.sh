#!/usr/bin/env bash
# Kill-switch tests not yet proven live (breach on error rate/p95 already proven in runs/).
# Run on the cluster machine with load running (bash scripts/load.sh start 20 2). ~3 min.
set -uo pipefail
cd "$(dirname "$0")/.."
K="kubectl --kubeconfig .runtime/kubeconfig --context kind-online-boutique -n online-boutique"
G="python3 -m chaosmind.guard"; I="python3 -m chaosmind.inject"
FAILED=0
ok()  { echo "PASS: $*"; }
bad() { echo "FAIL: $*"; FAILED=1; }
latest() { ls -td runs/"$1"-*/ | head -1; }
none_running() { [ -z "$(python3 -c 'from chaosmind import inject; print(*inject.running())')" ]; }

echo "== 1. Pod-health trigger on its own (ads are optional, so no errors expected, only unhealthy=1)"
$G experiments/test-ads-down.json '{"max_unhealthy": 0}'
d=$(latest test-ads-down)
grep -q 'BREACH.*unhealthy' "$d/events.csv" && grep -q HEALTHY "$d/events.csv" \
  && ok "breach on unhealthy, reverted, healthy ($d)" \
  || bad "health trigger; check $d/events.csv (if error_rate fired first: ads failure is NOT graceful, that's a finding)"

echo "== 2. Guard crashes (kill -9): Chaos Mesh's own duration still ends the fault"
$G experiments/test-down.json & pid=$!
sleep 12; kill -9 $pid; wait $pid 2>/dev/null
echo "   guard dead mid-experiment; waiting out the 60s duration..."
sleep 60
$K wait --for=condition=available deploy/cartservice --timeout=90s \
  && none_running && ok "fault ended and cartservice recovered with no guard alive" || bad "fail-safe"
$I revert experiments/test-down.json   # delete the finished resource object

echo "== 3. Manual abort clears everything"
$I apply experiments/test-down.json
$I abort
none_running && ok "abort cleared all chaosmind faults" || bad "abort"
$K wait --for=condition=available deploy --all --timeout=120s >/dev/null

[ $FAILED = 0 ] && echo "ALL PASSED" || { echo "SOME FAILED"; exit 1; }
