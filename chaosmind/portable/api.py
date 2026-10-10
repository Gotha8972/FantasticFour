"""Authenticated HTTP boundary; applications and credentials are operator configured."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
import hmac
import json
import os
from pathlib import Path
import threading

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from .schema import ApplicationProfile, Contract
from .store import Store
from .workflow import RunRequest, create_run, run_assessment, recover_run


class StartRequest(RunRequest):
    application_id: str


def create_app(profiles_dir=None, data_dir=None, token=None):
    profiles_dir = Path(profiles_dir or os.environ.get('CHAOSMIND_PROFILES', 'profiles'))
    data_dir = Path(data_dir or os.environ.get('CHAOSMIND_DATA', '.runtime/portable-runs'))
    token = token or os.environ.get('CHAOSMIND_API_TOKEN')
    if not token or len(token) < 32:
        raise RuntimeError('Set CHAOSMIND_API_TOKEN to a random token of at least 32 characters')
    profiles = {}
    for path in sorted(profiles_dir.glob('*.json')):
        profile = ApplicationProfile.model_validate_json(path.read_text())
        if profile.id in profiles:
            raise RuntimeError('Duplicate application profile')
        profiles[profile.id] = profile
    if not profiles:
        raise RuntimeError('No application profiles configured')
    store = Store(data_dir)
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='assessment')
    active = set()
    mutex = threading.Lock()

    @asynccontextmanager
    async def lifespan(app):
        store.interrupted()
        yield
        with mutex:
            running = list(active)
        for run_id in running:
            store.cancel(run_id)
        executor.shutdown(wait=True)

    app = FastAPI(title='ChaosMind portable LangGraph agent', lifespan=lifespan)
    app.state.store = store
    bearer = HTTPBearer(auto_error=False)

    def authenticate(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
        if credentials is None or credentials.scheme.lower() != 'bearer' or not hmac.compare_digest(credentials.credentials.encode(), token.encode()):
            raise HTTPException(401, 'Invalid bearer token')

    def record(run_id):
        try:
            return store.get(run_id)
        except KeyError:
            raise HTTPException(404, 'Unknown run') from None

    def submit(run_id, resume=False):
        with mutex:
            if run_id in active:
                raise HTTPException(409, 'Run is already active')
            active.add(run_id)
        def work():
            try:
                run_assessment(store, run_id, resume=resume)
            except Exception:
                # run_assessment records errors, including a pre-acquisition conflict below.
                if store.get(run_id)['status'] in ('queued', 'interrupted'):
                    store.status(run_id, 'failed', error='Application is locked by another assessment')
            finally:
                with mutex:
                    active.discard(run_id)
        executor.submit(work)

    @app.get('/health')
    def health():
        return {'status': 'ok'}

    @app.get('/applications', dependencies=[Depends(authenticate)])
    def applications():
        return [{'id': p.id, 'adapter': p.adapter, 'customer_journey': p.customer_journey,
                 'live_execution_enabled': p.adapter == 'kubernetes' and os.environ.get('CHAOSMIND_ALLOW_EXECUTION') == 'true'} for p in profiles.values()]

    @app.post('/runs', status_code=202, dependencies=[Depends(authenticate)])
    def start(request: StartRequest):
        profile = profiles.get(request.application_id)
        if profile is None:
            raise HTTPException(404, 'Application is not registered')
        if request.mode == 'execute' and profile.adapter == 'kubernetes' and os.environ.get('CHAOSMIND_ALLOW_EXECUTION') != 'true':
            raise HTTPException(403, 'Live execution is disabled by the operator')
        run_id = create_run(store, profile, RunRequest(mode=request.mode, trials=request.trials))
        submit(run_id)
        return {'run_id': run_id, 'status_url': '/runs/' + run_id}

    @app.get('/runs/{run_id}', dependencies=[Depends(authenticate)])
    def status(run_id: str):
        value = record(run_id)
        return {k: value[k] for k in ('id', 'application', 'status', 'cancelled', 'result', 'error')}

    @app.get('/runs/{run_id}/events', dependencies=[Depends(authenticate)])
    def events(run_id: str, after: int = Query(default=0, ge=0)):
        record(run_id)
        return store.events(run_id, after)

    @app.post('/runs/{run_id}/cancel', dependencies=[Depends(authenticate)])
    def cancel(run_id: str):
        record(run_id)
        store.cancel(run_id)
        return {'run_id': run_id, 'cancellation_requested': True}

    @app.post('/runs/{run_id}/resume', status_code=202, dependencies=[Depends(authenticate)])
    def resume(run_id: str):
        value = record(run_id)
        if value['status'] not in ('interrupted', 'failed') or value['cancelled']:
            raise HTTPException(409, 'Only interrupted or failed, uncancelled runs can resume')
        if value['request']['mode'] == 'execute' and value['profile']['adapter'] == 'kubernetes' and os.environ.get('CHAOSMIND_ALLOW_EXECUTION') != 'true':
            raise HTTPException(403, 'Live execution is disabled by the operator')
        submit(run_id, resume=True)
        return {'run_id': run_id}

    @app.post('/runs/{run_id}/recover', dependencies=[Depends(authenticate)])
    def recover(run_id: str):
        record(run_id)
        with mutex:
            if run_id in active:
                raise HTTPException(409, 'Cancel the active worker and wait before recovery')
        try:
            return {'run_id': run_id, 'cleanup_confirmed': recover_run(store, run_id)}
        except RuntimeError:
            raise HTTPException(409, 'Run has an active worker or unresolved recovery conflict') from None

    return app
