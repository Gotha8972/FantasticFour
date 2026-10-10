import json
from pathlib import Path
import unittest
from unittest.mock import patch
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'docs/team/alternatives'))
from chaosmind_lc.__main__ import review, plan
from chaosmind import inject
from chaosmind.agents import strategist


class BakeoffTests(unittest.TestCase):
    def test_winning_planner_rejects_scope_mismatch_and_missing_integrity(self):
        vulnerabilities=[{'id':'V1','service':'redis-cart'},{'id':'V2','service':'frontend'}]
        proposals=[{'vulnerability':'V1','fault':'pod_kill','target':'redis-cart','params':{},'duration_s':30,'criteria':[]},
                   {'vulnerability':'V2','fault':'pod_kill','target':'redis-cart','params':{},'duration_s':30,'criteria':[{'metric':'integrity_violations','op':'>','value':0}]}]
        with patch('chaosmind.agents.llm.ask',return_value={'plan':proposals}):
            result=strategist.plan(vulnerabilities,{},allowed_faults={'pod_kill'})
        self.assertEqual(result['plan'],[])
        self.assertEqual(len(result['dropped']),2)

    def test_safety_cannot_change_scope(self):
        original={'id':'check','fault':'network_delay','target':'checkoutservice','params':{'latency':'2000ms'},'duration_s':120}
        reply={'decision':'approve','experiment':{**original,'target':'frontend'}}
        with patch('chaosmind.agents.llm.ask',return_value=reply):
            result=review(original,{'error_rate':0,'p95_ms':10,'metrics_age_s':1,'unhealthy_services':[]},{})
        self.assertEqual(result['decision'],'reject')

    def test_risky_case_bounded_even_if_model_approves(self):
        original={'id':'check','fault':'network_delay','target':'checkoutservice','params':{'latency':'2000ms'},'duration_s':120}
        reply={'decision':'approve','experiment':original,'ramp':[2000]}
        with patch('chaosmind.agents.llm.ask',return_value=reply):
            result=review(original,{'error_rate':0,'p95_ms':10,'metrics_age_s':1,'unhealthy_services':[]},{})
        self.assertEqual(result['decision'],'shrink')
        self.assertEqual(result['experiment']['params']['latency'],'500ms')
        self.assertLessEqual(result['experiment']['duration_s'],30)
        inject.validate(result['experiment'])

    def test_unhealthy_current_health_rejected_by_code(self):
        original={'id':'check','fault':'pod_kill','target':'checkoutservice','params':{},'duration_s':30}
        with patch('chaosmind.agents.llm.ask',return_value={'decision':'approve','experiment':original}):
            result=review(original,{'unhealthy_services':['checkoutservice'],'error_rate':0,'p95_ms':10,'metrics_age_s':1},{})
        self.assertEqual(result['decision'],'reject')


if __name__=='__main__':
    unittest.main()
