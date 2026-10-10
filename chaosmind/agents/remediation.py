"""⑤ Remediation: the AI picks a fix from our reviewed catalog, code applies it and PROVES it by re-running
the identical experiment. The AI never writes patches; it can only choose a vetted one (remediation/catalog.json).
"""
import json
from pathlib import Path

from chaosmind import guard, inject
from chaosmind.agents import integrity, llm, safety, score

ROOT = Path(__file__).resolve().parents[2]
CATALOG = json.loads((ROOT / 'remediation/catalog.json').read_text())

SYSTEM = """You are the Remediation engineer for a chaos-engineering system.
Given a CONFIRMED weakness (the experiment, what was observed, integrity violations) and a catalog of reviewed fixes,
choose the ONE fix that addresses the root cause, or "none" if no fix in the catalog fits.
Only choose a fix whose "target" equals the experiment's target.
Return JSON: {"fix_id": "<catalog id or none>", "reason": "...", "expected_effect": "what should improve on re-run"}"""


def choose(item):
    exp = item['experiment']
    candidates = [f for f in CATALOG if f['target'] == exp['target']]
    if not candidates:
        return {'fix_id': 'none', 'reason': f"no reviewed fix for {exp['target']}"}
    reply = llm.ask(SYSTEM, {'weakness': {k: item.get(k) for k in ('vulnerability', 'experiment', 'observed',
                                                                    'integrity', 'verdict', 'score')},
                             'catalog': candidates})
    if reply.get('fix_id') not in {f['id'] for f in candidates}:
        return {'fix_id': 'none', 'reason': f"AI chose {reply.get('fix_id')!r}, not in the catalog for this target"}
    return reply


def _kubectl_files(verb, files):
    for f in files:
        inject.kubectl(verb, '-f', str(ROOT / f), '-n', inject.NS, *(['--ignore-not-found'] if verb == 'delete' else []))


def _patch(target, patch_file):
    patch = (ROOT / patch_file).read_text()
    inject.kubectl('patch', 'deployment', target, '-n', inject.NS, '--type=json', '-p', patch, '--dry-run=server')
    inject.kubectl('patch', 'deployment', target, '-n', inject.NS, '--type=json', '-p', patch)
    inject.kubectl('rollout', 'status', f'deployment/{target}', '-n', inject.NS, '--timeout=180s', timeout=200)


def apply(fix):
    _kubectl_files('apply', fix.get('apply_files', []))
    _patch(fix['target'], fix['patch'])


def revert(fix):
    _patch(fix['target'], fix['revert_patch'])
    _kubectl_files('delete', fix.get('delete_on_revert', []))


def remediate(item, baseline, guard_run=guard.run):
    """Choose → apply → re-run the identical experiment → compare scores → keep or roll back."""
    choice = choose(item)
    if choice['fix_id'] == 'none':
        return {'choice': choice, 'verdict': 'no_fix'}
    fix = next(f for f in CATALOG if f['id'] == choice['fix_id'])
    apply(fix)
    state = integrity.prepare()
    exp = {**item['experiment'], 'id': f"{item['experiment']['id']}-after"[:63]}
    events = guard_run(exp)
    observed = safety.observed(events) or {}
    violations = integrity.verify(state)
    after = score.score(observed, baseline, observed.get('recovery_s'), violations)
    before = item.get('score', {}).get('score')
    verdict = ('improved' if before is not None and after['score'] > before else
               'no_change' if before is not None and after['score'] == before else 'worse')
    if verdict == 'worse':
        revert(fix)
    return {'choice': choice, 'fix': fix['id'], 'before': before, 'after': after['score'],
            'after_breakdown': after['breakdown'], 'after_observed': observed, 'after_integrity': violations,
            'after_run_dir': next((e.get('artifact_dir') for e in events), None), 'verdict': verdict,
            'kept': verdict != 'worse'}
