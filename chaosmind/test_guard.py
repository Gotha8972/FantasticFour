"""Offline behavior tests: python3 -m chaosmind.test_guard."""
import contextlib
import csv
import io
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from chaosmind import capture, guard, inject, monitor

EXP = {'id': 'exp-001', 'fault': 'network_delay', 'target': 'productcatalogservice',
       'params': {'latency': '500ms'}, 'duration_s': 1}
GOOD = {'ts': 1, 'error_rate': 0.01, 'p95_ms': 150, 'unhealthy_services': [], 'users': 20,
        'rps': 4, 'requests': 100, 'failures': 1, 'checkout_success': 1.0, 'restarts': {}}
INJECTED = {'status': {'conditions': [{'type': 'AllInjected', 'status': 'True'}]}}


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir='/tmp')
        self.cwd = os.getcwd()
        os.chdir(self.temp.name)
        self.addCleanup(self.restore)

    def restore(self):
        os.chdir(self.cwd)
        self.temp.cleanup()

    def exercise(self, snaps=None, status=INJECTED, apply_error=None, active=None):
        with patch.object(inject, 'running', return_value=active or []), \
             patch.object(inject, 'apply', side_effect=apply_error) as apply, \
             patch.object(inject, 'revert') as revert, \
             patch.object(inject, 'status', return_value=status), \
             patch.object(guard, 'snapshot', side_effect=snaps or [GOOD, GOOD | {'p95_ms': 2500}, GOOD]), \
             contextlib.redirect_stdout(io.StringIO()):
            events = guard.run(EXP)
            return events, apply, revert

    def test_breach_reverts_and_recovers(self):
        events, apply, revert = self.exercise()
        self.assertIn('BREACH', [e['event'] for e in events])
        self.assertEqual(events[-1]['event'], 'HEALTHY')
        revert.assert_called_once()

    def test_unhealthy_preflight_never_injects(self):
        events, apply, revert = self.exercise(snaps=[GOOD | {'unhealthy_services': ['cartservice']}])
        self.assertEqual(events[-1]['event'], 'REFUSED')
        apply.assert_not_called()
        revert.assert_not_called()

    def test_existing_fault_never_injects(self):
        events, apply, revert = self.exercise(active=['NetworkChaos/shipping-delay'])
        self.assertEqual(events[-1]['event'], 'REFUSED')
        apply.assert_not_called()

    def test_monitor_failure_before_creation(self):
        events, apply, revert = self.exercise(snaps=[RuntimeError('CSV missing')])
        self.assertEqual(events[-1]['event'], 'ERROR')
        apply.assert_not_called()

    def test_monitor_failure_after_creation_reverts(self):
        events, apply, revert = self.exercise(snaps=[GOOD, RuntimeError('CSV stale'), GOOD])
        self.assertIn('ERROR', [e['event'] for e in events])
        revert.assert_called_once()

    def test_creation_failure_still_attempts_cleanup(self):
        events, apply, revert = self.exercise(snaps=[GOOD, GOOD], apply_error=RuntimeError('connection lost after create'))
        revert.assert_called_once()
        self.assertNotIn('INJECTED', [e['event'] for e in events])

    def test_failed_injection_is_not_reported_as_injected(self):
        failed = {'status': {'experiment': {'containerRecords': [{'events': [
            {'type': 'Failed', 'message': 'iptables error'}]}]}}}
        events, apply, revert = self.exercise(snaps=[GOOD, GOOD], status=failed)
        self.assertNotIn('INJECTED', [e['event'] for e in events])
        self.assertIn('iptables error', next(e['reason'] for e in events if e['event'] == 'ERROR'))
        revert.assert_called_once()

    def test_ctrl_c_reverts(self):
        events, apply, revert = self.exercise(snaps=[GOOD, KeyboardInterrupt(), GOOD])
        self.assertIn('INTERRUPTED', [e['event'] for e in events])
        revert.assert_called_once()

    def test_limits_cannot_be_loosened(self):
        for limits in ({'p95_ms': 3000}, {'poll_s': 10}, {'error_rate': float('nan')}):
            with self.assertRaises(ValueError):
                guard.run(EXP, limits)

    def test_csv_contains_real_snapshots_and_lifecycle(self):
        self.exercise()
        event_file = next(Path('runs').glob('*/events.csv'))
        with event_file.open(newline='') as handle:
            rows = list(csv.DictReader(handle))
        self.assertTrue(any(r['event'] == 'INJECTED' for r in rows))
        metric_file = next(Path('runs').glob('*/metrics.csv'))
        with metric_file.open(newline='') as handle:
            metrics = list(csv.DictReader(handle))
        self.assertEqual(metrics[0]['rps'], '4')
        self.assertEqual(metrics[0]['requests'], '100')

    def test_scope_and_duration(self):
        manifest = inject.manifest(EXP)
        self.assertEqual(manifest['metadata']['namespace'], 'online-boutique')
        self.assertEqual(manifest['spec']['mode'], 'one')
        for bad in ({'duration_s': 999}, {'duration_s': True}, {'namespace': 'kube-system'},
                    {'target': '../bad'}, {'params': {'latency': '500s'}}):
            with self.assertRaises(ValueError):
                inject.validate(EXP | bad)

    def test_foreign_resource_cannot_be_deleted(self):
        with patch.object(inject, 'kubectl', return_value=json.dumps({'metadata': {'labels': {}}})) as kube:
            with self.assertRaises(ValueError):
                inject.revert(EXP)
            self.assertEqual(kube.call_count, 1)

    def test_pod_logs_csv_preserves_quotes_and_commas(self):
        pod = {'metadata': {'name': 'locust-pod'}, 'spec': {'containers': [{'name': 'main'}]}}
        with patch.object(inject, 'kubectl', side_effect=[json.dumps({'items': [pod]}),
                         '2026-10-10T06:00:00Z message with comma, and "quotes"\n']):
            capture.logs('logs.csv', inject.NS, 'app=loadgenerator', '10m')
        with Path('logs.csv').open(newline='') as handle:
            row = next(csv.DictReader(handle))
        self.assertEqual(row['message'], 'message with comma, and "quotes"')

    def test_monitor_reads_real_metrics_and_rejects_stale_data(self):
        total = {'Request Count': '100', 'Failure Count': '3'}
        recent = {'Timestamp': str(int(time.time())), 'User Count': '20', 'Requests/s': '10',
                  'Failures/s': '1', '95%': '550'}
        data = {'aggregate': total, 'recent': recent, 'checkout': []}
        with patch.object(inject, 'kubectl', side_effect=[json.dumps({'items': []}), json.dumps(data)]):
            sample = monitor.snapshot()
        self.assertEqual(sample['error_rate'], 0.1)
        self.assertEqual(sample['p95_ms'], 550)
        data['recent']['Timestamp'] = '1'
        with patch.object(inject, 'kubectl', side_effect=[json.dumps({'items': []}), json.dumps(data)]):
            with self.assertRaises(RuntimeError):
                monitor.snapshot()


if __name__ == '__main__':
    unittest.main()
