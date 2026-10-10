#!/usr/bin/env python3
"""Six real model dry runs with frozen identical inputs; no injection or remediation."""
from datetime import datetime, timezone
import json
import hashlib
import os
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parents[1] / 'docs/team/alternatives'))
os.environ['AI_PROVIDER']='openai'
os.environ['OPENAI_MODEL']='gpt-5.6-luna'
os.environ['OPENAI_REASONING_EFFORT']='low'
from chaosmind.graph import build
from chaosmind.agents import safety, steps
from chaosmind_lc.__main__ import build as alternative, review


def main():
    inputs=Path('runs/bakeoff-inputs')
    facts=json.loads((inputs/'facts.json').read_text())
    health=json.loads((inputs/'health.json').read_text())
    baseline='baseline.json'
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    manifest={'model':'gpt-5.6-luna','reasoning_effort':'low','facts':str(inputs/'facts.json'),
              'baseline':baseline,'health':str(inputs/'health.json'),'ours':[],'alternative':[],'errors':[]}
    manifest['inputs_sha256']={name:hashlib.sha256(Path(manifest[name]).read_bytes()).hexdigest() for name in ['facts','baseline','health']}
    manifest['execution']='dry_run_no_injection'
    manifest['input_policy']='Frozen identical inputs, including health; not a live freshness assessment at each model call.'
    folder=Path('runs')/('bakeoff-'+stamp);folder.mkdir(parents=True)
    for label in ('ours','alternative'):
        for n in range(1,4):
            out=Path('runs')/f'agents-{label}-{stamp}-{n}';out.mkdir(parents=True)
            state={'out_dir':str(out),'budget':4,'dry_run':True,'remediate':False,'auto_approve':False,
                   'allow_unverified':False,'workloads':None,'baseline_path':baseline}
            print('Running',label,n,flush=True)
            try:
                if label=='ours':
                    with patch('chaosmind.agents.facts.collect',return_value=facts),patch('chaosmind.agents.steps._health',return_value=health):
                        build().compile().invoke(state)
                else:
                    alternative().invoke({**state,'facts_path':str(inputs/'facts.json'),'health':health})
                manifest[label].append(str(out))
            except Exception as exc:
                manifest['errors'].append({'implementation':label,'run':n,'error':str(exc)})
                (out/'failure.txt').write_text(str(exc)+'\n')
                print(type(exc).__name__,str(exc),flush=True)
            (folder/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    risky=json.loads(Path('experiments/risky-checkout.json').read_text())
    base=steps.load_baseline(baseline)
    for label,checker in [('ours',safety.review),('alternative',review)]:
        try:
            response=checker(risky,health,base)
            (folder/f'safety-{label}.json').write_text(json.dumps(response,indent=2)+'\n')
            print('Risky case',label,response['decision'],flush=True)
        except Exception as exc:
            manifest['errors'].append({'implementation':label,'safety_error':str(exc)})
    (folder/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print('Bakeoff manifest:',folder/'manifest.json',flush=True)


if __name__=='__main__':
    main()
