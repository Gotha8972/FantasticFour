# Smrithi: AI quality, architecture, second-machine setup

Read [GUIDE_00_EVERYONE.md](GUIDE_00_EVERYONE.md) first.

**Your role:**
1. Make the AI's decisions **good**, not just valid, by tuning prompts against real output.
2. Own the **architecture overview** (deliverable #3).
3. Remove our biggest risk: **the cluster only exists on Aashrith's laptop.** You prove it can be rebuilt from the README on a second machine.

---

## 1. Learn the agent code (≈45 min, in this order)
1. `chaosmind/agents/llm.py`: one function, `ask()`, NVIDIA NIM (gpt-oss-20b); it extracts the JSON object from the reply.
2. `facts.py`: plain code; the call graph from `*_ADDR` variables, plus a risk score. Try it:
   ```bash
   python3 -m chaosmind.agents.facts --workloads runs/baseline-study-20261010T072314.832283Z/workloads-initial.json
   ```
3. `cartographer.py`: prompt → ranked vulnerabilities → `verify()` drops invented evidence.
4. `strategist.py`: experiments + predictions + criteria written *before* the run; `evaluate()` (code) gives the verdict.
5. `safety.py`, `remediation.py`, `analyst.py`: same pattern.
6. `__main__.py`: the loop.
7. `test_agents.py` and `test_day2.py`: how we fake the AI to test offline.

## 2. Tune the prompts (≈1.5 h, after Aashrith's dry run)
Read `runs/agents-<time>/vulnerabilities.json`, `plan-1.json` and `history.json` critically:

| Check | Good | If bad, change |
|---|---|---|
| Cartographer ranking | redis-cart critical; productcatalog high; ads/recommendations low | Everything critical → strengthen "don't flag every single-replica service" |
| `rejected` list | Empty or tiny | Many → add an example of copying fact keys exactly |
| Strategist on Redis | `pod_kill` + criterion `integrity_violations > 0` | Wrong fault → strengthen the fault-to-weakness mapping |
| Criteria values | Well above the baseline (p95 ~35 ms, errors ~0.07%) | Would fire on noise → "use ≥ 5× baseline" |
| Safety Checker | Shrinks something risky on checkout | Approves everything → add an explicit rule for the checkout path |
| Analyst `FINDINGS.md` | Fact-check section says all numbers found | Invented numbers → tighten its rules |

**Techniques:**
- **Few-shot:** paste one ideal output into the SYSTEM prompt.
- **Explicit rubric:** "critical = data loss or checkout outage…".
- **Compare models:** `NIM_MODEL=nvidia/nemotron-3.5-lightning-30b-a3b NIM_EXTRA_BODY='{"chat_template_kwargs": {"enable_thinking": false}}'` (see [MODEL_CHECK_FINDINGS.md](log/MODEL_CHECK_FINDINGS.md) for which models our account can reach).
- **Reasoning models ignore temperature;** change effort or the prompt instead.

Change one thing at a time, re-run `--dry-run` (Aashrith, or offline with `--workloads`), and keep a log of what improved. That log is great material for the architecture page.

After each prompt change:
```bash
python3 -m unittest chaosmind.agents.test_agents chaosmind.agents.test_day2
```

## 3. Architecture overview (deliverable #3, ≈30 min)
[docs/ARCHITECTURE.md](../ARCHITECTURE.md) already has the diagram, decision steps and safety table. Your job:
- check it matches what the live run actually did
- add 2–3 lines from your prompt-tuning log
- make a one-slide version (a screenshot of the diagram plus the 7 decision steps) for the video

## 4. Second-machine setup (≈1 h, needs a Linux laptop with Podman)
Follow **only** [docs/RUNNING.md](../RUNNING.md), from a fresh `git clone`, as a judge would:
```bash
git clone https://github.com/Gotha8972/FantasticFour.git && cd FantasticFour
```
Then `scripts/install-kubectl.sh` → `deploy-local.sh` → `install-chaos.sh` → `load.sh start 20 2` → `python3 -m chaosmind.verify --dry-run`.

**Write down every step that fails or is unclear,** and fix the docs (or tell Aashrith). A working second cluster also means the demo survives if Aashrith's laptop dies.

## What to learn
- **Agentic loop design:** observe → decide → act → learn, with a budget and a stop condition
- **Prompt engineering against measurable criteria,** not vibes
- **Grounding:** the AI proposes; code verifies every fact, quote and number
