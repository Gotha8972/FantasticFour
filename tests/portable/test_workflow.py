import copy
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from chaosmind.portable.adapters import OfflineAdapter, KubernetesAdapter
from chaosmind.portable.api import create_app
from chaosmind.portable.planning import plan
from chaosmind.portable.schema import ApplicationProfile, Experiment, digest
from chaosmind.portable.store import Store
from chaosmind.portable.workflow import Workflow, RunRequest, create_run, run_assessment, recover_run, wilson

ROOT = Path(__file__).resolve().parents[2]


def profile(name='demo-store'):
    return ApplicationProfile.model_validate_json((ROOT / 'profiles' / (name + '.json')).read_text())


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)
        self.profile = profile()

    def tearDown(self):
        self.temp.cleanup()

    def run_profile(self, p=None, adapter=None, mode='execute'):
        p = p or self.profile
        run_id = create_run(self.store, p, RunRequest(mode=mode))
        result = run_assessment(self.store, run_id, adapter)
        return run_id, result

    def test_two_distinct_applications(self):
        for p in (self.profile, profile('demo-payments')):
            _, report = self.run_profile(p)
            self.assertEqual(report['condition']['experiment']['target'], p.allowed_targets[0])
            self.assertEqual(report['valid_trials'], 3)
            self.assertTrue(report['simulated'])
            self.assertIsNone(report['measured_probability'])
            self.assertIsNone(report['wilson_95_interval'])

    def test_dry_run_does_not_inject(self):
        adapter = OfflineAdapter(self.profile)
        with patch.object(adapter, 'inject', side_effect=AssertionError('must not inject')):
            _, report = self.run_profile(adapter=adapter, mode='dry_run')
        self.assertEqual(report['trials'], [])

    def test_guard_stops_and_cleans_up(self):
        self.profile.fixture['during'][0]['error_rate'] = .2
        adapter = OfflineAdapter(self.profile)
        _, report = self.run_profile(adapter=adapter)
        self.assertEqual(len(report['trials']), 1)
        self.assertTrue(report['trials'][0]['guard_tripped'])
        self.assertTrue(report['trials'][0]['cleanup_confirmed'])
        self.assertIsNone(adapter.active)

    def test_unconfirmed_fault_cannot_enter_probability_estimate(self):
        adapter = OfflineAdapter(self.profile)
        with patch.object(adapter, 'confirmed', return_value=False):
            _, report = self.run_profile(adapter=adapter)
        self.assertEqual(report['valid_trials'], 0)
        self.assertIsNone(report['measured_probability'])
        self.assertTrue(report['trials'][0]['cleanup_confirmed'])

    def test_cancellation_after_creation_cleans_up(self):
        adapter = OfflineAdapter(self.profile)
        run_id = create_run(self.store, self.profile, RunRequest(mode='execute'))
        original = adapter.inject
        def cancel(handle):
            original(handle)
            self.store.cancel(run_id)
        with patch.object(adapter, 'inject', side_effect=cancel):
            report = run_assessment(self.store, run_id, adapter)
        self.assertEqual(report['trials'][0]['status'], 'cancelled')
        self.assertTrue(report['trials'][0]['cleanup_confirmed'])
        self.assertIsNone(adapter.active)

    def test_wrong_traffic_refuses_fault(self):
        self.profile.fixture['baseline']['users'] = 20
        adapter = OfflineAdapter(self.profile)
        with patch.object(adapter, 'inject', side_effect=AssertionError('must not inject')):
            with self.assertRaisesRegex(RuntimeError, 'Traffic level'):
                self.run_profile(adapter=adapter)

    def test_cleanup_failure_retains_lock(self):
        adapter = OfflineAdapter(self.profile)
        with patch.object(adapter, 'cleanup', side_effect=RuntimeError('cleanup failed')):
            run_id, report = self.run_profile(adapter=adapter)
        self.assertEqual(self.store.get(run_id)['status'], 'cleanup_failed')
        self.assertEqual(len(report['trials']), 1)
        with self.assertRaises(RuntimeError):
            self.store.acquire(self.profile.id, 'different-run')

    def test_failed_cleanup_can_be_recovered_without_reinjection(self):
        adapter = OfflineAdapter(self.profile)
        with patch.object(adapter, 'cleanup', side_effect=RuntimeError('cleanup failed')):
            run_id, report = self.run_profile(adapter=adapter)
        with patch.object(adapter, 'inject', side_effect=AssertionError('must not inject')):
            self.assertTrue(recover_run(self.store, run_id, adapter))
        self.store.acquire(self.profile.id, 'new-run')
        self.assertEqual(self.store.get(run_id)['status'], 'recovered')

    def test_journal_replay_never_reinjects(self):
        adapter = OfflineAdapter(self.profile)
        workflow = Workflow(self.profile, self.store, adapter)
        run_id = create_run(self.store, self.profile, RunRequest(mode='execute'))
        topology = adapter.discover()
        experiment = plan(topology, self.profile, [])
        state = {'run_id': run_id, 'request': {'trials': 3}, 'topology': topology, 'experiment': experiment.model_dump()}
        first = workflow.trial(state, 0)
        with patch.object(adapter, 'inject', side_effect=AssertionError('duplicate injection')):
            second = workflow.trial(state, 0)
        self.assertEqual(first, second)

    def test_interrupted_intent_reconciles_without_injection(self):
        adapter = OfflineAdapter(self.profile)
        workflow = Workflow(self.profile, self.store, adapter)
        run_id = create_run(self.store, self.profile, RunRequest(mode='execute'))
        operation = digest([run_id, 0])[:32]
        topology = adapter.discover()
        experiment = plan(topology, self.profile, [])
        handle = adapter.prepare(operation, experiment, topology)
        self.store.save_operation(operation, run_id, {'handle': handle, 'phase': 'intent'})
        with patch.object(adapter, 'inject', side_effect=AssertionError('duplicate injection')):
            result = workflow.trial({'run_id': run_id}, 0)
        self.assertEqual(result['status'], 'invalid')
        self.assertTrue(result['cleanup_confirmed'])

    def test_cancellation_before_injection(self):
        run_id = create_run(self.store, self.profile, RunRequest(mode='execute'))
        self.store.cancel(run_id)
        with self.assertRaisesRegex(RuntimeError, 'cancelled'):
            run_assessment(self.store, run_id)
        self.store.acquire(self.profile.id, 'another-run')

    def test_bounds_reject_model_proposal(self):
        topology = OfflineAdapter(self.profile).discover()
        for proposal in ({'target':'unknown','fault':'pod_kill','duration_s':10},
                         {'target':'catalog','fault':'network_loss','duration_s':10,'params':{'loss_percent':90}},
                         {'target':'catalog','fault':'pod_kill','duration_s':120}):
            with self.assertRaises(ValueError):
                Experiment.model_validate(proposal).check(self.profile, topology)

    def test_completed_run_reuses_report(self):
        run_id, report = self.run_profile()
        self.assertEqual(run_assessment(self.store, run_id, resume=True), report)
        self.assertTrue((Path(self.temp.name) / run_id / 'checkpoints.sqlite').exists())

    def test_probability_is_conditional_and_has_interval(self):
        adapter = OfflineAdapter(self.profile)
        adapter.simulated = False
        workflow = Workflow(self.profile, self.store, adapter)
        topology = adapter.discover()
        run_id = create_run(self.store, self.profile, RunRequest(mode='execute'))
        state = {'run_id':run_id,'request':{'mode':'execute'},'topology':topology,'findings':[],
                 'experiment':plan(topology,self.profile,[]).model_dump(),
                 'trials':[{'status':'passed','confirmed':True,'cleanup_confirmed':True,'breached':False}] * 3}
        report = workflow.report(state)['report']
        self.assertEqual(report['measured_probability'], 0)
        self.assertGreater(report['wilson_95_interval'][1], .5)
        self.assertIsNone(wilson(0,0))


class KubernetesTests(unittest.TestCase):
    def test_service_and_workload_same_name_do_not_confuse_discovery(self):
        p = profile()
        p = ApplicationProfile.model_validate({**p.model_dump(), 'adapter':'kubernetes',
            'kubernetes':{'namespace':'sample','prometheus_url':'http://localhost:9090',
                          'queries':{k:'metric' for k in ('error_rate','p95_ms','rps','users','source_age_s')}}})
        adapter = KubernetesAdapter(p)
        resources = [{'kind':'Deployment','metadata':{'name':'catalog'},'spec':{
            'selector':{'matchLabels':{'app':'catalog'}},'replicas':2,
            'template':{'metadata':{'labels':{'app':'catalog'}},'spec':{'containers':[{'image':'catalog:1','name':'catalog'}]}}}},
            {'kind':'Service','metadata':{'name':'catalog'},'spec':{'selector':{'app':'catalog'}}}]
        with patch.object(adapter,'kubectl',return_value={'items':resources}):
            discovered = adapter.discover()
        self.assertEqual(discovered['services']['catalog']['replicas'],2)

    def test_exact_pod_selector_with_two_replicas(self):
        p = profile()
        p = ApplicationProfile.model_validate({**p.model_dump(), 'adapter':'kubernetes', 'allowed_targets':['catalog'],
            'kubernetes':{'namespace':'other-app','prometheus_url':'http://localhost:9090',
                          'queries':{k:'metric' for k in ('error_rate','p95_ms','rps','users','source_age_s')}}})
        adapter = KubernetesAdapter(p)
        topology = {'services':{'catalog':{'replicas':2,'pods':[{'name':'catalog-b','uid':'b','ready':True},{'name':'catalog-a','uid':'a','ready':True}]}}}
        exp = Experiment(target='catalog',fault='pod_kill',duration_s=10)
        handle = adapter.prepare('abc123',exp,topology)
        self.assertEqual(handle['manifest']['spec']['selector'], {'pods':{'other-app':['catalog-a']}})
        self.assertEqual(handle['manifest']['spec']['mode'],'one')
        self.assertEqual(handle['manifest']['spec']['duration'],'10s')
        with self.assertRaisesRegex(RuntimeError,'ownership'):
            adapter.owned({'metadata':{'annotations':{}}},handle)


class ApiTests(unittest.TestCase):
    def test_auth_profile_allowlist_and_run(self):
        with tempfile.TemporaryDirectory() as temp:
            app = create_app(ROOT/'profiles',temp,'x'*32)
            with TestClient(app) as client:
                self.assertEqual(client.get('/applications').status_code,401)
                headers={'Authorization':'Bearer '+'x'*32}
                self.assertEqual(client.post('/runs',headers=headers,json={'application_id':'unknown'}).status_code,404)
                self.assertEqual(client.post('/runs',headers=headers,json={'application_id':'demo-store','profile':{'id':'evil'}}).status_code,422)
                response = client.post('/runs',headers=headers,json={'application_id':'demo-store','mode':'execute'})
                self.assertEqual(response.status_code,202)
                run_id=response.json()['run_id']
                for _ in range(100):
                    response=client.get('/runs/'+run_id,headers=headers)
                    if response.json()['status'] not in ('queued','running'):
                        break
                    time.sleep(.02)
                self.assertEqual(response.json()['status'],'completed',response.text)
                self.assertTrue(response.json()['result']['simulated'])
                self.assertNotIn('profile',response.json())
                self.assertTrue(client.get('/runs/'+run_id+'/events',headers=headers).json())


if __name__ == '__main__':
    unittest.main()
