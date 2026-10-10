#!/usr/bin/env bash
set -Eeuo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.."
case "${1:-delay}" in
  delay|loss) exec python3 -m chaosmind.incidents "network-${1:-delay}" ;;
  *) echo 'Usage: bash scripts/incidents/network.sh [delay|loss]' >&2; exit 1 ;;
esac
