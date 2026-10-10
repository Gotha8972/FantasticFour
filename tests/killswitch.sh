#!/usr/bin/env bash
# Kill-switch evidence against the live cluster. Logs land in runs/ (commit them).
# Takes ~4 min (the fail-safe test waits out a 60s fault).  Usage: ./tests/killswitch.sh
set -uo pipefail
cd "$(dirname "$0")/.."
G="python3 -m chaosmind.guard"; I="python3 -m chaosmind.inject"
FAILED=0
ok()   { echo "PASS: $*"; }
bad()  { echo "FAIL: $*"; FAILED=1; }
none_running() { [ -z "$(kubectl get podchaos,networkchaos -n boutique -o name)" ]; }
save() { mv runs/test-down.jsonl "runs/$1.jsonl" 2>/dev/null; }
mkdir -p runs; rm -f runs/test-*.jsonl

echo "== 1. Breach → automatic revert → recovery"
$G experiments/test-down.json '{"max_unhealthy": 0}'
grep -q BREACH runs/test-down.jsonl && grep -q HEALTHY runs/test-down.jsonl && none_running \
  && ok "breach detected, reverted, healthy" || bad "breach test"
save 1-breach

echo "== 2. Preflight refuses while another fault is running"
$I apply experiments/test-delay.json
$G experiments/test-down.json
grep -q REFUSED runs/test-down.jsonl && ok "refused" || bad "preflight"
$I revert experiments/test-delay.json
save 2-preflight

echo "== 3. Guard killed politely (Ctrl-C / kill) still reverts"
$G experiments/test-down.json & pid=$!
sleep 8; kill -TERM $pid; wait $pid
grep -q REVERTED runs/test-down.jsonl && none_running && ok "reverted on kill" || bad "kill revert"
save 3-interrupt

echo "== 4. Guard crashes (kill -9): Chaos Mesh's own timer ends the fault"
$G experiments/test-down.json & pid=$!
sleep 8; kill -9 $pid; wait $pid 2>/dev/null
echo "   guard dead, fault left behind; waiting out its 60s duration..."
sleep 60
kubectl wait --for=condition=available deploy/cartservice -n boutique --timeout=90s \
  && ok "cartservice recovered with no guard alive" || bad "fail-safe"
$I revert experiments/test-down.json   # tidy the finished CR object
save 4-failsafe

echo "== 5. Manual abort clears everything"
$I apply experiments/test-down.json
$I abort
none_running && ok "abort cleared all faults" || bad "abort"
kubectl wait --for=condition=available deploy --all -n boutique --timeout=120s >/dev/null

[ $FAILED = 0 ] && echo "ALL KILL-SWITCH TESTS PASSED" || { echo "SOME TESTS FAILED"; exit 1; }
