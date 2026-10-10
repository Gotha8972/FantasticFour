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


if __name__ == '__main__':
    unittest.main()
