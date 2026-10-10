"""Offline tests, no cluster or API key: python3 -m unittest chaosmind.agents.test_agents"""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from chaosmind.agents import cartographer, facts, llm, safety, strategist

WORKLOADS = sorted(Path('runs').glob('baseline-study-*/workloads-initial.json'))[0]  # earliest: the original config; glob order varies by filesystem
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
        replies = iter([reply, {'plan': []}])
        with patch.object(llm, 'ask', side_effect=lambda system, user: next(replies)):
            out = strategist.plan([{'id':'V2','service':'productcatalogservice'}, {'id':'V1','service':'redis-cart'}], {}, history, allowed_faults={'network_delay', 'pod_kill'})
        self.assertEqual([i['experiment']['target'] for i in out['plan']], ['productcatalogservice'])
        self.assertEqual(out['plan'][0]['criteria'], [{'metric': 'p95_ms', 'op': '>', 'value': 500}])
        self.assertEqual(len(out['dropped']), 2)
        self.assertIn('already run', out['feedback'])

    def test_strategist_drops_contradicted_data_loss_prediction_then_gets_it_corrected(self):
        vulns = [{'id': 'V1', 'service': 'redis-cart'}]
        crit = [{'metric': 'integrity_violations', 'op': '>', 'value': 0}]
        item = {'vulnerability': 'V1', 'fault': 'pod_kill', 'target': 'redis-cart', 'duration_s': 30, 'criteria': crit}
        wrong = {'plan': [{**item, 'prediction': {'summary': 'Expect cart data loss and increased latency.'}}]}
        right = {'plan': [{**item, 'prediction': {'summary': 'brief cart errors; the PVC prevents data loss'}}]}
        replies, seen = iter([wrong, right]), []
        with patch.object(llm, 'ask', side_effect=lambda system, user: seen.append(user) or next(replies)):
            out = strategist.plan(vulns, {}, allowed_faults={'pod_kill'}, persistent=['redis-cart'])
        self.assertEqual(seen[0]['services_with_persistent_volume'], ['redis-cart'])
        self.assertIn('persistent volume', seen[1]['feedback'])
        self.assertEqual([i['prediction'] for i in out['plan']], [right['plan'][0]['prediction']])
        self.assertIn('persistent volume', out['dropped'][0]['reason'])
        with patch.object(llm, 'ask', return_value=wrong):  # original emptyDir Redis: the same prediction is true
            self.assertEqual(len(strategist.plan(vulns, {}, allowed_faults={'pod_kill'})['plan']), 1)

    def test_strategist_asks_once_for_fault_diversity(self):
        vulns = [{'id': 'V1', 'service': 'cartservice'}, {'id': 'V2', 'service': 'productcatalogservice'}]
        crit = [{'metric': 'error_rate', 'op': '>', 'value': 0.05}]
        kill = lambda v, t: {'vulnerability': v, 'fault': 'pod_kill', 'target': t, 'duration_s': 30, 'criteria': crit}
        mono = {'plan': [kill('V1', 'cartservice'), kill('V2', 'productcatalogservice')]}
        extra = {'plan': [kill('V1', 'cartservice'), {**kill('V2', 'productcatalogservice'), 'fault': 'network_delay',
                                                      'params': {'latency': '200ms'}}]}
        replies, seen = iter([mono, extra]), []
        with patch.object(llm, 'ask', side_effect=lambda system, user: seen.append(user) or next(replies)):
            out = strategist.plan(vulns, {}, allowed_faults={'pod_kill', 'network_delay'})
        self.assertEqual(len(seen), 2)
        self.assertIn('at least 2 different fault types', seen[1]['feedback'])
        self.assertEqual([i['fault'] for i in out['plan']], ['pod_kill', 'pod_kill', 'network_delay'])  # repeat dropped

    def test_experiments_ranked_by_blast_radius_times_criticality(self):
        s = FACTS['services']
        self.assertEqual((len(s['frontend']['blast_radius']), s['redis-cart']['blast_radius']),
                         (len(s), ['cartservice', 'checkoutservice', 'frontend', 'redis-cart']))
        vulns = [{'id': 'V1', 'service': 'adservice', 'severity': 'low', 'blast_radius': s['adservice']['blast_radius']},
                 {'id': 'V2', 'service': 'redis-cart', 'severity': 'critical', 'blast_radius': s['redis-cart']['blast_radius']}]
        crit = [{'metric': 'integrity_violations', 'op': '>', 'value': 0}]
        reply = {'plan': [  # the model ranks the harmless ads test first
            {'vulnerability': 'V1', 'rank': 1, 'fault': 'pod_failure', 'target': 'adservice', 'duration_s': 30, 'criteria': crit},
            {'vulnerability': 'V2', 'rank': 2, 'fault': 'network_delay', 'target': 'redis-cart', 'duration_s': 30,
             'params': {'latency': '100ms'}, 'criteria': crit}]}
        with patch.object(llm, 'ask', return_value=reply):
            out = strategist.plan(vulns, {}, allowed_faults={'pod_failure', 'network_delay'})
        self.assertEqual([(i['target'], i['rank'], i['priority']['score']) for i in out['plan']],
                         [('redis-cart', 1, 16), ('adservice', 2, 2)])  # 4 services x critical(4) vs 2 x low(1)

    def test_criteria_baseline_noise_could_meet_are_raised(self):
        # Real gpt-oss criterion: "error_rate > 0" is confirmed by one failed request, so it could never refute.
        base = {'metrics': {'error_rate': {'mean': 0.0006}, 'p95_ms': {'mean': 68, 'max': 110}}}
        crit = strategist.valid_criteria([{'metric': 'error_rate', 'op': '>', 'value': 0},
                                          {'metric': 'p95_ms', 'op': '>', 'value': 255},
                                          {'metric': 'p95_ms', 'op': '>', 'value': 1000}], 'pod_kill', base)
        self.assertEqual([(c['value'], c.get('raised_from')) for c in crit], [(0.01, 0), (340, 255), (1000, None)])
        self.assertEqual(strategist.evaluate(crit, {'error_rate': 0.004, 'p95_ms': 120})[0], 'refuted')  # noise

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

    def test_llm_calls_nvidia_nim_gpt_oss(self):
        import io
        sent = []

        class Response(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def fake_urlopen(request, timeout):
            sent.append((request.full_url, json.loads(request.data)))
            return Response(json.dumps({'choices': [{'message': {'content': 'Here: ```json\n{"ok": true}\n```'}}]}).encode())

        with patch.object(llm, 'api_key', return_value='test-key'), patch.object(llm.urllib.request, 'urlopen', fake_urlopen):
            self.assertEqual(llm.ask('SYSTEM RULES', {'x': 1}), {'ok': True})
        url, body = sent[0]
        self.assertEqual(url, 'https://integrate.api.nvidia.com/v1/chat/completions')
        self.assertEqual(body['model'], 'openai/gpt-oss-20b')  # open weights on NVIDIA's endpoint, not the OpenAI API
        self.assertEqual(body['reasoning_effort'], 'low')  # measured: dry run 45 s instead of minutes
        self.assertEqual([m['role'] for m in body['messages']], ['user'])  # system folded in: works on any chat template
        self.assertTrue(body['messages'][0]['content'].startswith('SYSTEM RULES'))
        self.assertNotIn('openai', url)

    def test_safety_never_sees_cumulative_counters(self):
        seen = {}
        with patch.object(llm, 'ask', side_effect=lambda system, user: seen.update(user) or {'decision': 'reject'}):
            safety.review(EXP, {'error_rate': 0.0, 'checkout_success': 0.989, 'failures': 21}, {})
        self.assertEqual(seen['current_health'], {'error_rate': 0.0})

    def test_cartographer_accepts_stringified_facts_and_files_cluster_wide_claims_as_systemic(self):
        # Real gpt-oss output: correct facts written as strings; 7 of 8 claims were rejected for the type alone.
        reply = {'vulnerabilities': [
            {'service': 'frontend', 'severity': 'critical', 'evidence': {'replicas': '1', 'entrypoint': 'true', 'pdb': 'false'}},
            {'service': 'all', 'weakness': 'no PDBs anywhere', 'evidence': {'pdb': 'false'}},
            {'service': 'cartservice', 'severity': 'high', 'evidence': {'replicas': True}},  # True is not 1
            {'service': 'redis-cart', 'severity': 'medium', 'evidence': {'volumes': ['emptyDir']}}]}
        with patch.object(llm, 'ask', return_value=reply):
            out = cartographer.audit(FACTS)
        kept = {v['service']: v for v in out['vulnerabilities']}
        self.assertEqual(kept['frontend']['evidence'], {'replicas': 1, 'entrypoint': True, 'pdb': False})
        self.assertEqual(kept['redis-cart']['severity'], 'critical')  # rated medium; facts say it loses data
        self.assertIn('medium → critical', kept['redis-cart']['severity_raised_by_code'])
        self.assertIn('no PDBs anywhere', out['systemic'])
        self.assertEqual([r['service'] for r in out['rejected']], ['cartservice'])

    def test_cartographer_rejects_data_loss_claim_when_persisted(self):
        persisted = {**FACTS, 'services': {**FACTS['services'], 'redis-cart': {
            **FACTS['services']['redis-cart'], 'volumes': ['persistentVolumeClaim'], 'stateful_without_pvc': False}}}
        reply = {'vulnerabilities': [
            {'service': 'redis-cart', 'severity': 'critical', 'weakness': 'single replica',
             'evidence': {'replicas': 1}, 'hypothesis': 'a pod kill wipes all carts'},
            {'service': 'redis-cart', 'severity': 'high', 'weakness': 'single replica',
             'evidence': {'replicas': 1}, 'hypothesis': 'a pod kill makes cartservice lose connection; cart page errors'}]}
        with patch.object(llm, 'ask', return_value=reply):
            out = cartographer.audit(persisted)
        self.assertEqual([v['severity'] for v in out['vulnerabilities']], ['high'])  # availability claim kept
        self.assertIn('persistent volume', out['rejected'][0]['rejected_because'])
        with patch.object(llm, 'ask', return_value=reply):  # same claim, no PVC (original emptyDir): kept
            self.assertEqual(len(cartographer.audit(FACTS)['vulnerabilities']), 2)

    def test_safety_hard_bounds_and_baseline_enforced_in_code(self):
        risky = json.loads(Path('experiments/risky-checkout.json').read_text())
        with patch.object(llm, 'ask', return_value={'decision': 'approve', 'experiment': risky, 'ramp': [2000]}):
            out = safety.review(risky, {}, {})
        self.assertEqual((out['decision'], out['experiment']['params']['latency'], out['experiment']['duration_s']),
                         ('shrink', '500ms', 30))
        self.assertEqual(out['ramp'], [62.5, 125, 250, 500])
        ads = {**risky, 'target': 'adservice'}
        with patch.object(llm, 'ask', return_value={'decision': 'approve', 'experiment': ads}):
            self.assertEqual(safety.review(ads, {}, {}, revenue_path=['checkoutservice'])['decision'], 'approve')
        with patch.object(llm, 'ask', side_effect=AssertionError('model must not be asked')):
            self.assertEqual(safety.review(EXP, {}, {'baseline_suitable': False})['decision'], 'reject')

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
