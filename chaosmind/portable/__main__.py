"""CLI: python -m chaosmind.portable --profile profiles/demo-store.json."""
import argparse
import os
from pathlib import Path
from .schema import ApplicationProfile
from .store import Store
from .workflow import RunRequest, create_run, run_assessment, recover_run


def main():
    parser = argparse.ArgumentParser(description='Application-configured LangGraph resilience assessment')
    parser.add_argument('--profile', type=Path)
    parser.add_argument('--data', type=Path, default=Path('.runtime/portable-runs'))
    parser.add_argument('--execute', action='store_true', help='Execute the profile allowlist; offline adapters simulate')
    parser.add_argument('--trials', type=int, default=3)
    parser.add_argument('--recover', help='Reconcile owned pending faults without injecting anything')
    parser.add_argument('--resume', help='Resume a run from the same data directory without repeating completed trials')
    args = parser.parse_args()
    store = Store(args.data)
    if args.recover:
        print('Cleanup confirmed:', recover_run(store, args.recover))
        return
    if args.resume:
        record = store.get(args.resume)
        profile = ApplicationProfile.model_validate(record['profile'])
        execute = record['request']['mode'] == 'execute'
        run_id = args.resume
    else:
        if not args.profile:
            parser.error('--profile is required for a new run')
        profile = ApplicationProfile.model_validate_json(args.profile.read_text())
        execute = args.execute
        run_id = create_run(store, profile, RunRequest(mode='execute' if execute else 'dry_run', trials=args.trials))
    if execute and profile.adapter == 'kubernetes' and os.environ.get('CHAOSMIND_ALLOW_EXECUTION') != 'true':
        parser.error('Set CHAOSMIND_ALLOW_EXECUTION=true only after reviewing the application profile')
    print('Run:', run_id, flush=True)
    try:
        report = run_assessment(store, run_id, resume=bool(args.resume))
    except KeyboardInterrupt:
        store.cancel(run_id)
        print('Interrupted. Resume to reconcile any pending operation before another assessment.')
        return
    print('Simulation:' if report['simulated'] else 'Measured assessment:', report['evidence'])
    print('Report:', store.directory / run_id / 'report.md')


if __name__ == '__main__':
    main()
