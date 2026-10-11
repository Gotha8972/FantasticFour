"""Offline tests for the mission-control UI server: python3 -m unittest chaosmind.test_ui"""
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from chaosmind import graph, ui

REAL_RUN = 'agents-20261010T192511Z'  # second live AI run: 3 experiments, 2 fixes approved and re-run


class UITests(unittest.TestCase):
    def test_reads_a_real_run(self):
        d = ui.run(REAL_RUN)
        self.assertEqual((d['stage'], len(d['history'])), ('report', 3))
        self.assertEqual([(h['remediation'] or {}).get('after_verdict') for h in d['history']],
                         ['refuted', None, 'confirmed'])  # frontend fix refuted the hypothesis; cart kept its latency
        step = Path(d['history'][0]['safety']['steps'][-1]['run_dir']).name
        self.assertTrue(any(e['event'] == 'INJECTED' for e in ui.events(step)))

    def test_never_leaves_the_runs_folder(self):
        for bad in ('../etc', 'a/b', '..', '', None):
            with self.assertRaises((ValueError, FileNotFoundError)):
                ui.safe_dir(bad)

    def test_approval_round_trip_between_ui_and_graph(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(ui, 'RUNS', Path(tmp)):
            run = Path(tmp) / 'agents-test'
            run.mkdir()
            with self.assertRaises(FileNotFoundError):  # nothing pending: the UI can't approve anything
                ui.approve('agents-test', 'y')
            (run / 'pending_approval.json').write_text(json.dumps({'question': 'Apply fix?', 'via': 'ui'}))
            ui.approve('agents-test', 'y')
            self.assertEqual(graph.ui_ask(run, poll_s=0)('Approve?'), 'y')  # the graph picks the answer up
            self.assertFalse((run / 'approval.json').exists())  # consumed, never reused

    def test_kpis_exclude_dry_runs_and_fixes_that_were_rolled_back(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(ui, 'RUNS', Path(tmp)):
            d = Path(tmp) / 'agents-test'
            d.mkdir()
            experiment = {'id': 'test', 'target': 'frontend', 'fault': 'pod_kill'}
            history = [
                {'experiment': experiment, 'observed': None, 'verdict': 'confirmed'},
                {'experiment': experiment, 'observed': {}, 'verdict': 'confirmed',
                 'remediation': {'fix': 'replicas', 'after_observed': {'error_rate': 0},
                                'kept': True, 'before': 20, 'after': 90}},
                {'experiment': experiment, 'observed': {}, 'verdict': 'confirmed',
                 'remediation': {'fix': 'replicas', 'after_observed': {'error_rate': 0},
                                'kept': False, 'before': 90, 'after': 95}}]
            (d / 'history.json').write_text(json.dumps(history))
            k = ui.incidents()['kpis']
            self.assertEqual((k['experiments'], k['confirmed'], k['retested_fixes'],
                              k['improved_fixes'], k['mean_gain']), (2, 2, 2, 1, 70))

    def test_evidence_rejects_secret_files_and_symlink_escapes(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(ui, 'RUNS', Path(tmp) / 'runs'):
            ui.RUNS.mkdir()
            d = ui.RUNS / 'agents-test'
            d.mkdir()
            secret = Path(tmp) / 'private.json'
            secret.write_text('private')
            (d / 'history.json').symlink_to(secret)
            for filename in ('.env', '../private.json'):
                with self.assertRaises(ValueError):
                    ui.evidence_file('agents-test', filename)
            with self.assertRaises(FileNotFoundError):
                ui.evidence_file('agents-test', 'history.json')
            (ui.RUNS / 'agents-outside').symlink_to(Path(tmp), target_is_directory=True)
            with self.assertRaises(ValueError):
                ui.safe_dir('agents-outside')

    def test_failure_case_uses_saved_logs_and_links_before_and_after_evidence(self):
        with patch('chaosmind.agents.analyst.error_lines', side_effect=AssertionError('no live log reads')):
            case = ui.incident(REAL_RUN, 'v1-pod-failure-frontend')
        self.assertEqual(case['history']['remediation']['after'], 97)
        self.assertTrue(any('Fault measurement' in a['label'] for a in case['artifacts']))
        self.assertTrue(any('Fix retest' in a['label'] for a in case['artifacts']))
        self.assertTrue(any(a['url'].startswith('/fix-evidence?') for a in case['artifacts']))
        self.assertTrue(all(line in case['logs'] for line in case['analysis']['evidence']))
        self.assertNotIn('redis-cart:', '\n'.join(case['analysis']['evidence']))

    def test_fix_evidence_only_serves_files_in_the_reviewed_catalog(self):
        self.assertEqual(ui.fix_file('frontend-replicas', 'replicas-2.json').name, 'replicas-2.json')
        with self.assertRaises(ValueError):
            ui.fix_file('frontend-replicas', '.env')
        with self.assertRaises(FileNotFoundError):
            ui.fix_file('invented-fix', 'replicas-2.json')

    def test_live_metrics_cache_does_not_turn_missing_data_into_success(self):
        with patch.object(ui, '_telemetry_cache', {}), patch('chaosmind.monitor.snapshot') as snapshot:
            snapshot.side_effect = RuntimeError('no traffic')
            with self.assertRaises(RuntimeError):
                ui.telemetry()
            snapshot.side_effect = None
            snapshot.return_value = {'error_rate': 0.01}
            self.assertEqual(ui.telemetry(), {'error_rate': 0.01})
            self.assertEqual(ui.telemetry(), {'error_rate': 0.01})
            self.assertEqual(snapshot.call_count, 2)


if __name__ == '__main__':
    unittest.main()
