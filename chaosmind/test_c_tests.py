"""Offline checks for the C checkpoint runner; no cluster mutations."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from chaosmind import c_tests, inject

GOOD = {'error_rate': 0, 'p95_ms': 30, 'unhealthy_services': [], 'users': 20, 'rps': 5}


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir='/tmp')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.patch = patch.object(inject, 'ROOT', self.root)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.stdout = contextlib.redirect_stdout(io.StringIO())
        self.stdout.__enter__()
        self.addCleanup(self.stdout.__exit__, None, None, None)
        self.evidence = c_tests.Evidence('unit')

    def test_cart_count_distinguishes_errors_from_empty(self):
        self.assertEqual(c_tests.cart_count('<h3>Cart (1)</h3>'), 1)
        self.assertEqual(c_tests.cart_count('Your shopping cart is empty!'), 0)
        with self.assertRaises(RuntimeError):
            c_tests.cart_count('HTTP Status: 500 Internal Server Error')

    def test_evidence_csv_and_json_preserved(self):
        self.evidence.result('case', 'FINDING', value=3)
        self.assertTrue((self.evidence.directory / 'evidence.csv').exists())
        summary = json.loads((self.evidence.directory / 'summary.json').read_text())
        self.assertEqual(summary[0]['value'], 3)
        self.assertEqual(summary[0]['outcome'], 'FINDING')

    def test_guard_partial_json_line_ignored(self):
        path = self.root / 'partial.jsonl'
        path.write_text('{"event":"CREATED"}\n{"event":"INJ')
        self.assertEqual(c_tests.guard_events(path), [{'event': 'CREATED'}])

    def test_preflight_existing_fault_refuses_before_metrics(self):
        with patch.object(inject, 'running', return_value=['PodChaos/other']), \
                patch.object(c_tests, 'snapshot') as snap:
            with self.assertRaises(RuntimeError):
                c_tests.preflight(self.evidence, 'test')
            snap.assert_not_called()

    def test_ad_error_first_is_finding_not_health_pass(self):
        events = [{'event': 'INJECTED', 'artifact_dir': '/tmp/guard'},
                  {'event': 'BREACH', 'metric': 'error_rate', 'value': .3, 'limit': .2},
                  {'event': 'REVERTED'}, {'event': 'HEALTHY'}]
        with patch.object(c_tests, 'preflight'), patch.object(c_tests.guard, 'run', return_value=events), \
                patch.object(c_tests, 'save_logs'):
            c_tests.health_trigger(self.evidence)
        self.assertEqual(self.evidence.results[0]['outcome'], 'FINDING')

    def test_ad_failed_recovery_cannot_pass(self):
        events = [{'event': 'INJECTED'}, {'event': 'NOT_RECOVERED'}]
        with patch.object(c_tests, 'preflight'), patch.object(c_tests.guard, 'run', return_value=events):
            with self.assertRaises(RuntimeError):
                c_tests.health_trigger(self.evidence)

    def test_abort_cleanup_attempts_both_after_error(self):
        with patch.object(c_tests, 'preflight'), patch.object(inject, 'apply'), \
                patch.object(c_tests, 'wait_for'), patch.object(inject, 'abort_all', side_effect=RuntimeError('API')), \
                patch.object(inject, 'revert', side_effect=[RuntimeError('first'), None]) as revert:
            with self.assertRaises(RuntimeError):
                c_tests.abort_checkpoint(self.evidence)
            self.assertEqual(revert.call_count, 2)

    def test_crash_observes_recovery_before_cleanup(self):
        process = Mock()
        process.pid = 12345
        process.poll.return_value = -9
        process.wait.return_value = -9
        paths = self.root / 'runs' / 'c-crash-fixed-run'
        paths.mkdir(parents=True)
        (paths / 'events.jsonl').write_text('{"event":"INJECTED"}\n')
        exp = {'id': 'c-crash-fixed', 'target': 'adservice', 'fault': 'pod_failure',
               'duration_s': 60, '_run_token': 'token'}
        def resource(condition):
            return {'metadata': {'annotations': {'chaosmind/run-token': 'token'}},
                    'status': {'conditions': [{'type': condition, 'status': 'True'}]}}
        calls = []
        def state(exp):
            calls.append('status')
            return resource('AllInjected' if len(calls) == 1 else 'AllRecovered')
        with patch.object(c_tests, 'preflight'), patch.object(c_tests, 'experiment', return_value=exp), \
                patch.object(c_tests.subprocess, 'Popen', return_value=process), \
                patch.object(inject, 'status', side_effect=state), \
                patch.object(c_tests, 'healthy'), patch.object(c_tests, 'save_logs'), \
                patch.object(inject, 'kubectl', return_value=json.dumps(resource('AllRecovered'))), \
                patch.object(inject, 'revert', side_effect=lambda exp: calls.append('delete')):
            c_tests.crash_failsafe(self.evidence)
        self.assertEqual(calls, ['status', 'status', 'delete'])
        process.kill.assert_called_once()
        self.assertEqual(self.evidence.results[0]['outcome'], 'PASS')

    def test_redis_compares_same_session_after_new_ready_pod(self):
        deployment = {'spec': {'replicas': 1, 'template': {'spec': {
            'containers': [{'volumeMounts': [{'name': 'data', 'mountPath': '/data'}]}],
            'volumes': [{'name': 'data', 'emptyDir': {}}]}}}}
        old = {'items': [{'metadata': {'name': 'redis-old', 'uid': 'old'}}]}
        new = {'items': [{'metadata': {'name': 'redis-new', 'uid': 'new'},
                          'status': {'conditions': [{'type': 'Ready', 'status': 'True'}]}}]}
        before = '<h3>Cart (1)</h3> SKU #OLJCESPC7Z'
        after = 'Your shopping cart is empty!'
        responses = []
        for html in (before, after):
            response = Mock()
            response.__enter__ = Mock(return_value=response)
            response.__exit__ = Mock(return_value=False)
            response.read.return_value = html.encode()
            responses.append(response)
        with patch.object(c_tests, 'preflight'), patch.object(c_tests, 'healthy'), \
                patch.object(c_tests, 'save_logs'), \
                patch.object(inject, 'kubectl', side_effect=[json.dumps(deployment), json.dumps(old), '', json.dumps(new)]) as kubectl, \
                patch.object(c_tests.request, 'urlopen', side_effect=responses) as urlopen:
            c_tests.redis_finding(self.evidence, 'http://127.0.0.1:8080')
        result = self.evidence.results[0]
        self.assertTrue(result['cart_wiped'])
        self.assertTrue(result['data_empty_dir'])
        self.assertEqual(result['before_count'], 1)
        cookies = [call.args[0].get_header('Cookie') for call in urlopen.call_args_list]
        self.assertEqual(cookies[0], cookies[1])
        deleted = json.loads(kubectl.call_args_list[2].kwargs['stdin'])
        self.assertEqual(deleted['metadata']['name'], 'redis-old')
        self.assertTrue((self.evidence.directory / 'redis-finding.txt').exists())
        self.assertTrue((self.root / 'runs' / 'redis-finding.txt').exists())

    def test_redis_unverified_cart_prevents_pod_deletion(self):
        deployment = {'spec': {'replicas': 1, 'template': {'spec': {'containers': [], 'volumes': []}}}}
        pods = {'items': [{'metadata': {'name': 'redis-old', 'uid': 'old'}}]}
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = b'Your shopping cart is empty!'
        with patch.object(c_tests, 'preflight'), \
                patch.object(inject, 'kubectl', side_effect=[json.dumps(deployment), json.dumps(pods)]) as kubectl, \
                patch.object(c_tests.request, 'urlopen', return_value=response):
            with self.assertRaises(RuntimeError):
                c_tests.redis_finding(self.evidence, 'http://127.0.0.1:8080')
        self.assertEqual(kubectl.call_count, 2)


if __name__ == '__main__':
    unittest.main()
