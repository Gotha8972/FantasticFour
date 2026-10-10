"""LangGraph workflow tests (offline): .venv/bin/python -m unittest chaosmind.test_graph"""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from chaosmind import graph
from chaosmind.agents import integrity, llm, remediation, safety

ROOT = Path(__file__).resolve().parents[1]
WORKLOADS = str(sorted(ROOT.glob('runs/baseline-study-*/workloads-initial.json'))[0])  # earliest: the original config
STEP = {'intensity': None, 'run_dir': 'runs/x', 'stopped_by': None,
        'observed': {'error_rate': 0.0, 'p95_ms': 60, 'unhealthy_count': 1, 'breach': None, 'recovery_s': 5}}


def ai_replies():
    return iter([
        {'vulnerabilities': [{'service': 'redis-cart', 'severity': 'critical', 'weakness': 'single store',
                              'evidence': {'replicas': 1}, 'hypothesis': 'kill wipes carts'}]},
        {'plan': [{'vulnerability': 'V1', 'rank': 1, 'fault': 'pod_failure', 'target': 'redis-cart', 'duration_s': 30,
                   'criteria': [{'metric': 'integrity_violations', 'op': '>', 'value': 0}]}]},
        {'fix_id': 'redis-persistence', 'reason': 'emptyDir', 'expected_effect': 'cart survives'},
        {'plan': [], 'replan_note': 'done'},
        {'summary': 'ok', 'findings': []}])


class GraphTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cwd = os.getcwd()
        os.chdir(self.tmp.name)
        self.addCleanup(lambda: (os.chdir(self.cwd), self.tmp.cleanup()))
        replies = ai_replies()
        for p in (patch.object(llm, 'ask', side_effect=lambda *a, **k: next(replies)),
                  patch('chaosmind.monitor.snapshot', return_value={'users': 20}),
                  patch.object(safety, 'run', return_value={'decision': 'approve', 'reason': '', 'ramp': [None], 'steps': [STEP]}),
                  patch.object(integrity, 'prepare', return_value={}),
                  patch.object(remediation, 'applied', return_value=False),
                  patch.object(integrity, 'verify', return_value=[{'check': 'cart_persistence'}])):
            p.start()
            self.addCleanup(p.stop)
        self.execute = patch.object(remediation, 'execute', return_value={'fix': 'redis-persistence', 'before': 58,
                                                                           'after': 96, 'verdict': 'improved'}).start()
        self.addCleanup(patch.stopall)
        Path('runs/g').mkdir(parents=True)
        self.state = {'out_dir': 'runs/g', 'budget': 2, 'remediate': True, 'workloads': WORKLOADS,
                      'baseline_path': str(ROOT / 'baseline.json')}
        self.config = {'configurable': {'thread_id': 'g'}}

    def run_graph(self, answer, db='runs/g/cp.sqlite'):
        with SqliteSaver.from_conn_string(db) as saver:
            app = graph.build().compile(checkpointer=saver)
            return graph.drive(app, self.config, self.state, ask=lambda _: answer)

    def test_confirmed_weakness_is_fixed_only_after_approval(self):
        final = self.run_graph('y')
        self.execute.assert_called_once()
        self.assertEqual(final['history'][0]['verdict'], 'confirmed')
        self.assertEqual(final['history'][0]['remediation']['verdict'], 'improved')
        self.assertTrue(Path('runs/g/FINDINGS.md').exists())

    def test_rejected_approval_never_touches_the_cluster(self):
        final = self.run_graph('n')
        self.execute.assert_not_called()
        self.assertEqual(final['history'][0]['remediation']['verdict'], 'not_approved')

    def test_resume_from_checkpoint_in_a_new_process(self):
        with SqliteSaver.from_conn_string('runs/g/cp.sqlite') as saver:
            first = graph.build().compile(checkpointer=saver).invoke(self.state, self.config)
        self.assertIn('__interrupt__', first)          # paused at the approval gate; "process exits"
        with SqliteSaver.from_conn_string('runs/g/cp.sqlite') as saver:   # fresh app, same checkpoint file
            app = graph.build().compile(checkpointer=saver)
            self.assertEqual(app.get_state(self.config).next, ('approve_fix',))
            final = graph.drive(app, self.config, Command(resume='y'))
        self.execute.assert_called_once()
        self.assertEqual(json.loads(Path('runs/g/history.json').read_text())[0]['remediation']['verdict'], 'improved')
        self.assertIn('history', final)

    def test_diagram_comes_from_the_real_graph(self):
        mermaid = graph.build().compile().get_graph().draw_mermaid()
        for node in ('audit', 'plan', 'execute', 'judge', 'approve_fix', 'apply_fix', 'report'):
            self.assertIn(node, mermaid)


if __name__ == '__main__':
    unittest.main()
