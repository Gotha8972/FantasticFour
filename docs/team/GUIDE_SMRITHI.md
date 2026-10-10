# Smrithi: AI lead: Cartographer, Strategist, orchestrator

Read [GUIDE_00_EVERYONE.md](GUIDE_00_EVERYONE.md) first.

**Your role:** you own the **brain** and the **loop**. The Cartographer and Strategist are already built (offline-tested). Your job is to **make them good with the real Mistral model**, add **prediction scoring**, and **wire every other agent into one end-to-end run**. When judges ask "show me the AI", it's your loop they'll see.

---

## Part 0: Understand what exists (≈30 min, read the code in this order)
1. **`chaosmind/agents/llm.py`:** `ask(system, user, model)` posts to Mistral's chat API in **JSON mode** (`response_format: json_object`), retries once on bad JSON, and returns a dict.
2. **`chaosmind/agents/facts.py`:** **plain code.** Reads every Deployment and builds the call graph from `*_ADDR` env vars. For each service it computes `callers`, `dependents` (everything that breaks if this breaks), `on_checkout_path`, `stateful_without_pvc`, probes, limits, and a `risk_score`. Try it offline:
   ```bash
   python3 -m chaosmind.agents.facts --workloads runs/baseline-study-20261010T072314.832283Z/workloads-initial.json
   ```
3. **`cartographer.py`:** sends the facts plus the SYSTEM prompt; the AI returns ranked `vulnerabilities`, each with `evidence`. **`verify()` drops any evidence that doesn't match the real config exactly.** This is how we stop hallucinations.
4. **`strategist.py`:** turns vulnerabilities into experiments, with a `prediction` and pass/fail `criteria` **written before the run**. `plan()` validates every experiment with `inject.validate()` and refuses repeats. **`evaluate()` is code**: it decides confirmed/refuted, so the AI never grades itself.
5. **`__main__.py`:** the loop: facts → audit → plan → for each experiment: Safety Checker (inject via guard) → evaluate → **re-plan** with the results (`history`).
6. **`test_agents.py`:** 7 offline tests. Read them to see how we fake the AI with `patch.object(llm, 'ask', …)`.

Run the offline tests:
```bash
python3 -m unittest chaosmind.agents.test_agents
```

---

## Part 1: Make the AI actually good (≈1.5 h)
Once Aashrith's dry run works, you'll have a real `runs/agents-<time>/` folder with `vulnerabilities.json`, `plan-1.json` and `history.json`. **Read every AI output critically:**

| Check | Good | Bad → what to change |
|---|---|---|
| Cartographer ranking | `redis-cart` critical, `productcatalogservice` high, ads/recommendations low | Everything is "critical" → strengthen the "don't flag every single-replica service" rule |
| `rejected` list | Empty or tiny | Many rejections → the model isn't copying fact keys exactly; add an example to the prompt |
| Strategist fault choice | Redis → `pod_kill`; catalog → `network_delay`; cart→Redis link → `network_partition` | Random faults → strengthen the "match fault to weakness" mapping |
| Criteria | Numbers well above the baseline (p95 ~35 ms, errors ~0.07%) | Criteria that would trigger on normal noise → tell it to use ≥5× the baseline |
| `replan_note` (live runs) | Changes the plan based on results | Ignores results → pass `history` more prominently |

**Prompt-engineering techniques to try** (change one thing at a time, re-run `--dry-run`, compare):
1. **Few-shot:** put one perfect example output in the SYSTEM prompt.
2. **Explicit ranking rubric:** "critical = data loss or checkout outage; high = site-wide slowdown; low = optional feature".
3. **Model size:** `MISTRAL_LARGE=mistral-large-latest` for the Cartographer and Strategist. Compare quality vs speed.
4. **Temperature** is 0.2 in `llm.py` (fairly deterministic). Keep it low for planning.

Keep a short log of what you changed and what improved. It's great material for the architecture page ("how the AI makes decisions").

---

## Part 2: Prediction scoring (≈45 min)
**Concept:** the Strategist predicts *before* each experiment (`prediction.affected` = services it expects to be hurt, plus `criteria`). After the run, **code** compares:
- **Verdict accuracy:** already done (`confirmed` / `refuted` from the criteria).
- **Blast-radius accuracy:** predicted `affected` vs the Observer's `nodes_affected` (Aashrith). Compute precision (how many predicted were really hit) and recall (how many really hit were predicted).

Add to the end of the loop:
```python
summary = {"hypotheses": n, "confirmed": c, "refuted": r,
           "blast_radius": {"precision": 0.8, "recall": 0.67}}
```
Save it as `runs/agents-<time>/prediction_scorecard.json`. **Demo line:** "Our AI predicted the blast radius with 80% precision before breaking anything."

---

## Part 3: Wire everything into the loop (≈1.5 h): `chaosmind/agents/__main__.py`
Target order, inside the loop for each experiment:
```
state = integrity.prepare()                         # Harshil: before the fault
result = safety.run(exp, snapshot(), baseline)      # Srinavith: inject + ramp (exists)
events = load events of the last step               # from result['steps'][-1]['run_dir']/events.jsonl
impact = observer.observe(events, baseline, facts)  # Aashrith
violations = integrity.verify(state)                # Harshil: silent failures
cause = log_detective.explain(exp, events)          # Aashrith
verdict = strategist.evaluate(criteria, observed)   # exists. If violations: treat as confirmed
s = score.score(observed, baseline, recovery_s, violations)   # Harshil
history.append({... all of the above ...})
if verdict == 'confirmed' and args.remediate:
    fix = remediation.propose(...); remediation.check(...); remediation.apply_and_verify(...)  # Srinavith
plan = strategist.plan(... history ...)             # re-plan (exists)
```
After the loop: `documentor.write(out_dir)` (Harshil) → `FINDINGS.md`.

**Rules for integration:**
- **Each new agent is optional** until it exists. Wrap each call so a missing module or an exception is **logged into history and doesn't stop the run**. Remember: the guard's safety never depends on any agent.
- Add flags: `--remediate` (off by default, since it changes the cluster) and `--budget`.
- Every step saves its JSON into `runs/agents-<time>/`, so everything is replayable offline.
- Keep `--dry-run` working (no injection, no remediation).

**Test offline:** extend `test_agents.py` with a "full loop with every agent faked" test: patch `llm.ask`, `guard.run`, `monitor.snapshot` and the new agents, then assert `history.json` has every field.

---

## Part 4: The architecture page (deliverable #3, ≈30 min)
One page or slide:
- **Components:** the diagram from GUIDE_00, section 4.
- **How the AI decides:** facts → audit → hypotheses with pre-registered criteria → ramp → verdict by code → re-plan.
- **Safety controls:** the 9 layers from the README's "Safety controls".

Put it in `docs/architecture.md`, or as an image, and link it from the README.

## Hand-offs
- **You call everyone's code.** Agree the function signatures in their guides with them at H1. If something changes, the agent's owner tells you.
- **The Live run** happens on Aashrith's laptop. Pair with him for the H3–4 integration run.

## What to learn while doing this
- **Agentic loop design:** observe → decide → act → learn, with a budget and a stop condition
- **Prompt engineering against measurable criteria,** not vibes
- **Grounding and verification:** the AI proposes, code verifies, every time
- **Evaluation:** precision and recall of predictions, the same metrics ML engineers use
