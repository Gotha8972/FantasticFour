"""① Strategist: turn vulnerabilities into experiments that prove or refute them.

The AI picks fault, target, prediction and pass/fail criteria BEFORE the run.
Code validates the experiment and decides confirmed/refuted against those criteria.
"""
import json
import re

from chaosmind import inject
from chaosmind.agents import llm

METRICS = ('error_rate', 'p95_ms', 'unhealthy_count')

SYSTEM = f"""You design chaos experiments that PROVE or REFUTE suspected vulnerabilities.

Faults you may use (exact names and limits):
- pod_failure: service unavailable for duration_s. params: {{}}
- pod_kill: pod killed once and recreated (tests state loss / restart). params: {{}}
- network_delay: params {{"latency": "<n>ms"}} (max 2000ms)
- network_loss: params {{"loss": <percent>}} (max 50)
- cpu_stress: params {{"load": <1-100>, "workers": 1}}
duration_s: 20-60. Pick a moderate intensity; the Safety Checker ramps it up gradually.

Match the fault to the weakness: stateful/no persistence -> pod_kill; high fan-in or latency propagation -> network_delay;
flaky dependency -> network_loss; resource pressure -> cpu_stress; plain availability -> pod_failure.

For each experiment write pass/fail "criteria" BEFORE it runs. The hypothesis is CONFIRMED if ANY criterion is met
during the fault. Allowed metrics: {', '.join(METRICS)} ("unhealthy_count" = number of unavailable services).
Use the baseline to set values well above normal (e.g. p95 at least 5x baseline).
If a hypothesis can't be measured with these metrics (e.g. silent data loss), set "criteria": [] and say so in "reason".

Given "history": never repeat a fault+target already run; use confirmed/refuted results to re-rank what's left
and explain what changed in "replan_note".

Return JSON:
{{"plan": [{{"vulnerability": "V1", "rank": 1, "fault": "...", "target": "<service>", "params": {{}}, "duration_s": 30,
  "reason": "...", "prediction": {{"affected": ["services"], "summary": "expected effect vs baseline"}},
  "criteria": [{{"metric": "p95_ms", "op": ">", "value": 500}}]}}],
 "replan_note": "..."}}"""


def experiment_id(item):
    raw = f"{item.get('vulnerability', 'v')}-{item['fault']}-{item['target']}".lower().replace('_', '-')
    return re.sub(r'[^a-z0-9-]', '', raw)[:55].strip('-')


def valid_criteria(criteria):
    return [c for c in criteria if isinstance(c, dict) and c.get('metric') in METRICS
            and c.get('op') in ('>', '<') and type(c.get('value')) in (int, float)]


def plan(vulnerabilities, baseline, history=(), budget=5):
    done = {(h['experiment']['fault'], h['experiment']['target']) for h in history}
    reply = llm.ask(SYSTEM, {'vulnerabilities': vulnerabilities, 'baseline': baseline,
                             'history': list(history), 'max_experiments': budget})
    items, dropped = [], []
    for item in reply.get('plan', []):
        try:
            exp = {'id': experiment_id(item), 'fault': item['fault'], 'target': item['target'],
                   'params': item.get('params') or {}, 'duration_s': int(item.get('duration_s', 30))}
            inject.validate(exp)
        except (KeyError, TypeError, ValueError) as error:
            dropped.append({'item': item, 'reason': str(error)})
            continue
        if (exp['fault'], exp['target']) in done:
            dropped.append({'item': item, 'reason': 'already run'})
            continue
        done.add((exp['fault'], exp['target']))
        items.append({**item, 'experiment': exp, 'criteria': valid_criteria(item.get('criteria', []))})
    items.sort(key=lambda i: i.get('rank', 99))
    return {'plan': items[:budget], 'dropped': dropped, 'replan_note': reply.get('replan_note', '')}


def evaluate(criteria, observed):
    """Code, not AI, decides the verdict."""
    if observed is None:
        return 'inconclusive', []
    if not criteria:
        return 'needs_integrity_check', []
    met = [c for c in criteria if (observed[c['metric']] > c['value'] if c['op'] == '>'
                                   else observed[c['metric']] < c['value'])]
    return ('confirmed' if met else 'refuted'), met
