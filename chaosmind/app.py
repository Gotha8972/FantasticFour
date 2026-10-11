"""The application under test, read from one profile file: everything ChaosMind knows about a specific app.

Pick it with CHAOSMIND_APP (default online-boutique), e.g.
    CHAOSMIND_APP=bookinfo .venv/bin/python -m chaosmind.graph --dry-run
The agents, the guard, the score and the verdicts are the same for every app; only this file differs
(apps/<name>/profile.json). Supporting a new Kubernetes app = writing its profile.
"""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAME = os.environ.get('CHAOSMIND_APP') or 'online-boutique'
PROFILE_PATH = ROOT / 'apps' / NAME / 'profile.json'
if not PROFILE_PATH.exists():
    raise SystemExit(f'Unknown app {NAME!r}: no {PROFILE_PATH.relative_to(ROOT)}')
PROFILE = json.loads(PROFILE_PATH.read_text())

NS = PROFILE['namespace']
CONTEXT = PROFILE['context']
# Kubernetes label whose value names a service (several deployments, e.g. versions, can share one service).
SERVICE_LABEL = PROFILE.get('service_label', 'app')
# How service-to-service calls are found: env vars ending in a suffix (Online Boutique's *_ADDR), or a list of edges.
CALLS = PROFILE['calls']
SOFT_CALLS = {tuple(c) for c in PROFILE.get('soft_calls', [])}
EVERY_PAGE = {k: set(v) for k, v in PROFILE.get('every_page', {}).items()}
JOURNEY = PROFILE.get('journey_service')  # the service orchestrating the key transaction (checkout), if any
IGNORE = set(PROFILE.get('ignore', []))
LOADGENERATOR = PROFILE.get('loadgenerator', 'loadgenerator')
JOURNEY_PATH = PROFILE.get('journey_path')  # Locust request name of the key transaction, e.g. /cart/checkout
ENTRY_LOGS = PROFILE.get('entry_service')  # whose logs the Analyst reads besides the target's
STATEFUL = set(PROFILE.get('stateful_services', []))  # experiments on these need an integrity criterion
INTEGRITY = PROFILE.get('integrity', 'none')
PAGE_CHECKS = PROFILE.get('page_checks', [])
CATALOG = ROOT / PROFILE.get('remediation_catalog', 'remediation/catalog.json')
BASELINE = ROOT / PROFILE.get('baseline', 'baseline.json')
