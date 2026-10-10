#!/usr/bin/env bash
set -Eeuo pipefail
PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"
python3 - <<'PY'
from chaosmind import inject
active = inject.running()
if active:
    raise SystemExit(f'Stop unrecovered experiments first: {active}')
PY
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'bash scripts/load.sh start 20 2' EXIT
bash scripts/load.sh start 100 10
python3 -m chaosmind.podkill_demo
