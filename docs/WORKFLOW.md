# Agent workflow (LangGraph)

Generated from the real graph with `.venv/bin/python -m chaosmind.graph --draw`; this diagram *is* the code ([chaosmind/graph.py](../chaosmind/graph.py)). Dashed arrows are decisions made by code.

```mermaid
---
config:
  flowchart:
    curve: linear
---
graph TD;
	__start__([<p>__start__</p>]):::first
	setup(setup)
	audit(audit)
	plan(plan)
	execute(execute)
	judge(judge)
	propose_fix(propose_fix)
	apply_fix(apply_fix)
	report(report)
	approve_fix(approve_fix)
	skip_fix(skip_fix)
	__end__([<p>__end__</p>]):::last
	__start__ --> setup;
	apply_fix -.-> plan;
	apply_fix -.-> report;
	approve_fix -.-> apply_fix;
	approve_fix -.-> skip_fix;
	audit --> plan;
	execute --> judge;
	judge -.-> plan;
	judge -.-> propose_fix;
	judge -.-> report;
	plan -.-> execute;
	plan -.-> report;
	propose_fix --> approve_fix;
	setup --> audit;
	skip_fix -.-> plan;
	skip_fix -.-> report;
	report --> __end__;
	classDef default fill:#f2f0ff,line-height:1.2
	classDef first fill-opacity:0
	classDef last fill:#bfb6fc
```

| Node | Agent / code | What happens |
|---|---|---|
| `setup` | `facts.py` (code) | Read the live deployments; load the baseline |
| `audit` | **Cartographer** (AI + verification) | Rank architecture vulnerabilities; drop unverifiable evidence |
| `plan` | **Strategist** (AI + validation) | Experiments, predictions and pass/fail criteria; re-plans with every new result |
| `execute` | **Safety Checker** (AI) → `guard.py` (code) | Approve/shrink/reject, ramp intensity through the kill switch; integrity checks before and after |
| `judge` | code | Verdict against the pre-written criteria; resilience score; stop if cleanup failed |
| `propose_fix` | **Remediation** (AI) | Pick a reviewed fix from the catalog |
| `approve_fix` | **human** (LangGraph interrupt) | Nothing touches the cluster without a yes (`--auto-approve` for recorded runs) |
| `apply_fix` / `skip_fix` | code | Apply, re-run the identical experiment, keep only if the score improves |
| `report` | **Analyst** (AI + fact-check) | `FINDINGS.md` |

**Checkpointing:** every finished node is saved to `runs/agents-…/checkpoints.sqlite`; `--resume runs/agents-…` continues an interrupted run, including one paused at the approval gate.
**Model-agnostic:** nodes call `chaosmind/agents/llm.py` (NVIDIA NIM, gpt-oss-20b by default); no LangChain dependency.
