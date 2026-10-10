"""Offline tests, no cluster or API key: python3 -m unittest chaosmind.agents.test_agents"""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from chaosmind.agents import cartographer, facts, llm, safety, strategist

WORKLOADS = next(Path('runs').glob('baseline-study-*/workloads-initial.json'))
FACTS = facts.collect(json.loads(WORKLOADS.read_text()))
EXP = {'id': 'v2-delay', 'fault': 'network_delay', 'target': 'productcatalogservice',
       'params': {'latency': '400ms'}, 'duration_s': 60}


def snap(stage, p95, unhealthy=()):
    return {'event': 'SNAPSHOT', 'stage': stage, 'error_rate': 0.0, 'p95_ms': p95,
            'unhealthy_services': list(unhealthy), 'artifact_dir': 'runs/x'}


class AgentTests(unittest.TestCase):
    def test_facts_from_real_cluster_data(self):
        s = FACTS['services']
        self.assertEqual(next(iter(s)), 'redis-cart')  # highest risk
        self.assertTrue(s['redis-cart']['stateful_without_pvc'])
        self.assertEqual(s['productcatalogservice']['callers'],
                         ['checkoutservice', 'frontend', 'recommendationservice'])
        self.assertNotIn('loadgenerator', s)
        self.assertNotIn('shoppingassistantservice', s['frontend']['calls'])  # not deployed
        self.assertLess(s['adservice']['risk_score'], s['cartservice']['risk_score'])

    def test_cartographer_drops_invented_evidence(self):
        reply = {'vulnerabilities': [
            {'service': 'redis-cart', 'severity': 'critical', 'weakness': 'no persistence',
             'evidence': {'replicas': 1, 'stateful_without_pvc': True, 'liveness_probe': False}},
            {'service': 'adservice', 'severity': 'high', 'evidence': {'replicas': 3}},
            {'service': 'ghost', 'evidence': {'replicas': 1}}]}
        with patch.object(llm, 'ask', return_value=reply):
            out = cartographer.audit(FACTS)
        self.assertEqual([v['service'] for v in out['vulnerabilities']], ['redis-cart'])
        self.assertEqual(out['vulnerabilities'][0]['unverified_evidence_dropped'], {'liveness_probe': False})
        self.assertEqual(len(out['rejected']), 2)

    def test_strategist_validates_and_never_repeats(self):
        reply = {'plan': [
            {'vulnerability': 'V2', 'rank': 1, 'fault': 'network_delay', 'target': 'productcatalogservice',
             'params': {'latency': '300ms'}, 'duration_s': 30,
             'criteria': [{'metric': 'p95_ms', 'op': '>', 'value': 500}, {'metric': 'vibes', 'op': '>', 'value': 1}]},
            {'vulnerability': 'V9', 'fault': 'delete_cluster', 'target': 'frontend'},
            {'vulnerability': 'V1', 'fault': 'pod_kill', 'target': 'redis-cart', 'duration_s': 30, 'criteria': []}]}
        history = [{'experiment': {'fault': 'pod_kill', 'target': 'redis-cart'}}]
        with patch.object(llm, 'ask', return_value=reply):
            out = strategist.plan([{'id':'V2','service':'productcatalogservice'}, {'id':'V1','service':'redis-cart'}], {}, history, allowed_faults={'network_delay', 'pod_kill'})
        self.assertEqual([i['experiment']['target'] for i in out['plan']], ['productcatalogservice'])
        self.assertEqual(out['plan'][0]['criteria'], [{'metric': 'p95_ms', 'op': '>', 'value': 500}])
        self.assertEqual(len(out['dropped']), 2)

    def test_trivial_pod_criteria_dropped(self):
        crit = [{'metric': 'unhealthy_count', 'op': '>', 'value': 0}, {'metric': 'error_rate', 'op': '>', 'value': 0.05}]
        self.assertEqual([c['metric'] for c in strategist.valid_criteria(crit, 'pod_kill')], ['error_rate'])
        self.assertEqual(len(strategist.valid_criteria(crit, 'network_delay')), 2)

    def test_code_decides_verdict(self):
        crit = [{'metric': 'p95_ms', 'op': '>', 'value': 500}]
        self.assertEqual(strategist.evaluate(crit, {'p95_ms': 3500})[0], 'confirmed')
        self.assertEqual(strategist.evaluate(crit, {'p95_ms': 90})[0], 'refuted')
        self.assertEqual(strategist.evaluate([], {'p95_ms': 90})[0], 'needs_integrity_check')
        self.assertEqual(strategist.evaluate(crit, None)[0], 'inconclusive')

    def test_safety_never_sees_cumulative_counters(self):
        seen = {}
        with patch.object(llm, 'ask', side_effect=lambda system, user: seen.update(user) or {'decision': 'reject'}):
            safety.review(EXP, {'error_rate': 0.0, 'checkout_success': 0.989, 'failures': 21}, {})
        self.assertEqual(seen['current_health'], {'error_rate': 0.0})

    def test_safety_cannot_enlarge(self):
        bigger = {'decision': 'shrink', 'experiment': {**EXP, 'params': {'latency': '1500ms'}}, 'ramp': [100]}
        with patch.object(llm, 'ask', return_value=bigger):
            self.assertEqual(safety.review(EXP, {}, {})['decision'], 'reject')
        retarget = {'decision': 'approve', 'experiment': {**EXP, 'target': 'frontend'}}
        with patch.object(llm, 'ask', return_value=retarget):
            self.assertEqual(safety.review(EXP, {}, {})['decision'], 'reject')

    def test_ramp_stops_at_breaking_point(self):
        reply = {'decision': 'approve', 'reason': 'ok', 'experiment': EXP, 'ramp': [100, 200, 400]}
        calls = []

        def fake_guard(step):
            calls.append(step['params']['latency'])
            p95 = {'100ms': 300, '200ms': 2400}[step['params']['latency']]
            events = [snap('injected', p95)]
            if p95 > 2000:
                events.append({'event': 'BREACH', 'metric': 'p95_ms', 'value': p95, 'limit': 2000})
            return events + [{'event': 'HEALTHY', 'recovery_s': 12.0}]

        with patch.object(llm, 'ask', return_value=reply):
            out = safety.run(EXP, {}, {}, guard_run=fake_guard)
        self.assertEqual(calls, ['100ms', '200ms'])  # never reached 400ms
        self.assertEqual((out['tolerated_up_to'], out['limit_crossed_at']), (100, 200))
        self.assertTrue(all(s['observed'] and s['observed']['recovery_s'] == 12.0 for s in out['steps']))

    def test_bad_ramp_replaced_and_guard_refusal_stops(self):
        reply = {'decision': 'approve', 'experiment': EXP, 'ramp': [10, 400]}  # 40x jump
        with patch.object(llm, 'ask', return_value=reply):
            self.assertEqual(safety.review(EXP, {}, {})['ramp'], [50, 100, 200, 400])
            out = safety.run(EXP, {}, {}, guard_run=lambda step: [{'event': 'REFUSED'}])
        self.assertEqual(len(out['steps']), 1)
        self.assertEqual(out['status'], 'aborted: REFUSED')


if __name__ == '__main__':
    unittest.main()
