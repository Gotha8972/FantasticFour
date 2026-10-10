# Agent bakeoff alternative

The alternative reasoning graph is archived here after the first bakeoff. The team uses `python -m chaosmind.graph`; see [BAKEOFF_RESULT.md](../BAKEOFF_RESULT.md).

The alternative supports only dry runs and reuses the team's deterministic contracts. It is retained for reproducibility. `scripts/run-agent-bakeoff.py` imports it explicitly from this archive and compares it with the current team graph using frozen facts, health and baseline inputs. It does not inject faults or apply fixes.
