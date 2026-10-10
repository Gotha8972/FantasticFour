"""Summarise a steady-load metrics CSV into baseline.json.

python3 -m chaosmind.baseline_summary runs/baseline-5min.csv > baseline.json
"""
import csv
import json
import statistics
import sys

FIELDS = ("error_rate", "p95_ms", "rps", "checkout_success")


def summarise(rows):
    out = {"samples": len(rows)}
    for f in FIELDS:
        vals = [float(r[f]) for r in rows if r.get(f) not in (None, "", "null")]
        if vals:
            out[f] = {"mean": round(statistics.mean(vals), 4), "min": min(vals), "max": max(vals)}
    out["unhealthy_samples"] = sum(1 for r in rows if r.get("unhealthy_services", "[]") not in ("", "[]"))
    return out


if __name__ == "__main__":
    with open(sys.argv[1], newline="") as fh:
        print(json.dumps(summarise(list(csv.DictReader(fh))), indent=2))
