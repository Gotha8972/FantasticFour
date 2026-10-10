#!/usr/bin/env bash
set -Eeuo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.."
mode="${1:-delay}"
if (( $# > 0 )); then shift; fi
case "$mode" in
  delay|loss) exec python3 -m chaosmind.incidents "network-$mode" "$@" ;;
  *) echo 'Usage: bash scripts/incidents/network.sh [delay|loss]' >&2; exit 1 ;;
esac
