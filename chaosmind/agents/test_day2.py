"""Offline tests for integrity, score, remediation, analyst and the full loop: python3 -m unittest chaosmind.agents.test_day2"""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from chaosmind.agents import __main__ as loop, analyst, integrity, llm, remediation, score

BASE = {'metrics': {'error_rate': {'mean': 0.0007}, 'p95_ms': {'mean': 35}}}
CART_DOWN_RUN = 'runs/test-down-20261010T062320.861245Z'
REDIS_DIR = Path('runs/c-redis-20261010T070925.577773Z')


class Day2Tests(unittest.TestCase):
    def test_score_ranks_real_results_sensibly(self):
        s = lambda obs, rec=0, v=(): score.score(obs, BASE, rec, v)['score']
        self.assertEqual(s({'error_rate': 0.0007, 'p95_ms': 35}), 100)
        cart_down = s({'error_rate': 0.35, 'p95_ms': 2700}, 55.5)
        ads_down = s({'error_rate': 0.0, 'p95_ms': 88}, 36.1)
        redis_wipe = s({'error_rate': 0.0, 'p95_ms': 60}, 4.9, [{'check': 'cart_persistence'}])
        self.assertLess(cart_down, redis_wipe)
        self.assertLess(redis_wipe, ads_down)
        self.assertLessEqual(redis_wipe, 60)  # silent data loss can never look healthy

    def test_integrity_catches_silent_cart_loss(self):
        before, after = (REDIS_DIR / 'cart-before.html').read_text(), (REDIS_DIR / 'cart-after.html').read_text()
        pages = {'/cart': [(200, before), (200, after)], '/cart/checkout': [(200, 'Your order is complete! Order Confirmation ID')]}
        fake = lambda session, path, form=None: pages[path].pop(0) if path in pages and pages[path] and not (path == '/cart' and form) else (200, '')
        with patch.object(integrity, 'fetch', side_effect=fake):
            state = integrity.prepare()
            violations = integrity.verify(state)
        self.assertEqual([v['check'] for v in violations], ['cart_persistence'])

    def test_integrity_flags_checkout_without_order(self):
        fake = lambda session, path, form=None: (200, 'Your shopping cart is empty!') if path == '/cart' else (200, '<html>oops</html>')
        with patch.object(integrity, 'fetch', side_effect=fake):
            violations = integrity.verify({'cart_before': 0})
        self.assertEqual([v['check'] for v in violations], ['checkout_completes'])

    def test_remediation_only_picks_reviewed_fixes(self):
        item = {'experiment': {'id': 'redis-podkill', 'fault': 'pod_kill', 'target': 'redis-cart', 'duration_s': 30}}
        with patch.object(llm, 'ask', return_value={'fix_id': 'rm -rf /'}):
            self.assertEqual(remediation.choose(item)['fix_id'], 'none')
        with patch.object(llm, 'ask', return_value={'fix_id': 'cartservice-replicas'}):  # wrong target
            self.assertEqual(remediation.choose(item)['fix_id'], 'none')
        with patch.object(llm, 'ask', return_value={'fix_id': 'redis-persistence', 'reason': 'emptyDir'}):
            self.assertEqual(remediation.choose(item)['fix_id'], 'redis-persistence')

    def test_remediation_rolls_back_when_worse(self):
        item = {'experiment': {'id': 'cart', 'fault': 'pod_failure', 'target': 'cartservice', 'duration_s': 30},
                'score': {'score': 50}}
        bad_events = [{'event': 'SNAPSHOT', 'stage': 'injected', 'error_rate': 0.9, 'p95_ms': 9000,
                       'unhealthy_services': ['cartservice']}]
        with patch.object(llm, 'ask', return_value={'fix_id': 'cartservice-replicas'}), \
             patch.object(remediation, 'apply') as apply, patch.object(remediation, 'revert') as revert, \
             patch.object(remediation.integrity, 'prepare', return_value={}), \
             patch.object(remediation.integrity, 'verify', return_value=[]):
            out = remediation.remediate(item, BASE, guard_run=lambda exp: bad_events)
        apply.assert_called_once()
        revert.assert_called_once()
        self.assertEqual((out['verdict'], out['kept']), ('worse', False))

    def test_analyst_keeps_only_real_evidence_and_flags_invented_numbers(self):
        with tempfile.TemporaryDirectory() as d:
            history = [{'vulnerability': 'V2', 'experiment': {'id': 'cart-down', 'fault': 'pod_failure', 'target': 'cartservice'},
                        'safety': {'decision': 'approve', 'steps': [{'run_dir': CART_DOWN_RUN, 'intensity': None}]},
                        'observed': {'recovery_s': 55.463}, 'verdict': 'confirmed', 'integrity': [], 'score': {'score': 21}}]
            Path(d, 'history.json').write_text(json.dumps(history))
            Path(d, 'vulnerabilities.json').write_text(json.dumps({'vulnerabilities': []}))
            reply = {'summary': 'Cart outage hurt checkout for 999 minutes.',
                     'findings': [{'experiment_id': 'cart-down', 'title': 'Cart outage', 'severity': 'high',
                                   'evidence': ['frontend: invented line'], 'fix': 'replicas'}]}
            with patch.object(analyst, 'error_lines', return_value=['frontend: rpc error: code = Unavailable']), \
                 patch.object(llm, 'ask', return_value=reply):
                text = analyst.write(d).read_text()
        self.assertIn('| `cart-down` | pod_failure on cartservice | confirmed |', text)
        self.assertNotIn('invented line', text)
        self.assertIn('999', text.split('## Fact-check')[1])

    def test_recovery_timings_from_real_cart_down_run(self):
        events = [json.loads(l) for l in Path(CART_DOWN_RUN, 'events.jsonl').read_text().splitlines()]
        obs = loop.safety.observed(events)
        self.assertEqual((obs['error_rate'], obs['p95_ms']), (1.0, 2700.0))  # worst moment is after the revert
        self.assertLess(obs['service_ready_s'], obs['customer_recovered_s'])  # capacity back before customers

    def test_trials_wilson_and_invalid_runs(self):
        from chaosmind.agents import trials
        self.assertEqual(trials.wilson(0, 5), (0.0, 0.434))  # 0 of 5 still allows up to ~43%
        self.assertEqual(trials.wilson(5, 5)[1], 1.0)
        ok = [{'event': 'INJECTED', 't': 1, 'target': 'x'},
              {'event': 'SNAPSHOT', 'stage': 'injected', 't': 2, 'error_rate': 0.0, 'p95_ms': 80, 'unhealthy_services': []},
              {'event': 'HEALTHY', 't': 9, 'recovery_s': 5}]
        bad = [{'event': 'INJECTED', 't': 1, 'target': 'x'}, {'event': 'ERROR', 't': 2}]
        runs = iter([ok, bad, ok])
        with tempfile.TemporaryDirectory() as d, \
             patch.object(trials.integrity, 'prepare', return_value={}), patch.object(trials.integrity, 'verify', return_value=[]), \
             patch.object(trials.time, 'sleep'):
            cwd = os.getcwd(); os.chdir(d)
            try:
                out = trials.run({'id': 'k', 'fault': 'pod_kill', 'target': 'x', 'duration_s': 30}, 3,
                                 guard_run=lambda exp: next(runs), snapshot=lambda: {}, cond={'k': 1})
                summary = json.loads(Path(out, 'trials.json').read_text())['summary']
            finally:
                os.chdir(cwd)
        self.assertEqual((summary['valid_trials'], summary['invalid_trials'], summary['breaches']), (2, 1, 0))
        self.assertEqual(summary['evidence'], 'insufficient (<3 valid trials)')

    def test_full_live_loop_with_everything_faked(self):
        workloads = str(next(Path('runs').glob('baseline-study-*/workloads-initial.json')))
        replies = iter([
            {'vulnerabilities': [{'service': 'redis-cart', 'severity': 'critical', 'weakness': 'emptyDir',
                                  'evidence': {'stateful_without_pvc': True}, 'hypothesis': 'kill wipes carts'}]},
            {'plan': [{'vulnerability': 'V1', 'rank': 1, 'fault': 'pod_failure', 'target': 'redis-cart', 'duration_s': 30,
                       'criteria': [{'metric': 'integrity_violations', 'op': '>', 'value': 0}]}]},
            {'plan': [], 'replan_note': 'done'},
            {'summary': 'ok', 'findings': []}])
        step = {'intensity': None, 'run_dir': 'runs/x', 'stopped_by': None,
                'observed': {'error_rate': 0.0, 'p95_ms': 60, 'unhealthy_count': 1, 'breach': None, 'recovery_s': 5}}
        cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as d, \
             patch.object(llm, 'ask', side_effect=lambda *a, **k: next(replies)), \
             patch('chaosmind.monitor.snapshot', return_value={}), \
             patch.object(loop.safety, 'run', return_value={'decision': 'approve', 'reason': '', 'ramp': [None], 'steps': [step]}), \
             patch.object(loop.integrity, 'prepare', return_value={}), \
             patch.object(loop.integrity, 'verify', return_value=[{'check': 'cart_persistence'}]), \
             patch.object(sys, 'argv', ['x', '--budget', '2', '--workloads', str(Path(cwd, workloads)),
                                         '--baseline', str(Path(cwd, 'baseline.json'))]):
            os.chdir(d)
            try:
                loop.main()
                out = next(Path('runs').glob('agents-*'))
                history = json.loads((out / 'history.json').read_text())
                self.assertTrue((out / 'FINDINGS.md').exists())
            finally:
                os.chdir(cwd)
        self.assertEqual(history[0]['verdict'], 'confirmed')  # caught by the integrity check, not HTTP errors
        self.assertLessEqual(history[0]['score']['score'], 60)


if __name__ == '__main__':
    unittest.main()
