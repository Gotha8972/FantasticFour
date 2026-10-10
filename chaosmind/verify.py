"""Run the two imported experiments sequentially and save their real evidence."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from chaosmind import capture, guard, inject
from chaosmind.monitor import snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="check baseline and admission without injecting")
    args = parser.parse_args()
    summary = []
    directory = Path("runs") / ("verification-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ"))
    directory.mkdir(parents=True)
    try:
        active = inject.running()
        if active:
            raise RuntimeError(f"Remove unrecovered experiments first: {active}")
        baseline = snapshot()
        if baseline["unhealthy_services"] or guard.breach(baseline, guard.LIMITS):
            raise RuntimeError("Baseline is unhealthy; refusing verification injections")
        (directory / "baseline.json").write_text(json.dumps(baseline, indent=2))
        for name in ("test-delay", "test-down"):
            exp = json.loads((inject.ROOT / "experiments" / f"{name}.json").read_text())
            inject.apply(exp, dry_run=True)
            if args.dry_run:
                summary.append({"experiment": name, "admission_accepted": True, "injected": False})
                continue
            # This threshold specifically verifies the pod-health kill switch.
            limits = {"max_unhealthy": 0} if name == "test-down" else None
            events = guard.run(exp, limits)
            names = [event["event"] for event in events]
            passed = "INJECTED" in names and "HEALTHY" in names and not any(
                name in names for name in ("ERROR", "REVERT_FAILED", "NOT_RECOVERED", "INTERRUPTED"))
            if exp["fault"] == "pod_failure":
                passed = passed and "BREACH" in names
            result = {"experiment": exp["id"], "injected": "INJECTED" in names,
                      "recovered": "HEALTHY" in names, "breach_detected": "BREACH" in names,
                      "passed": passed, "artifact_dir": events[0]["artifact_dir"] if events else None,
                      "collection_errors": []}
            if result["artifact_dir"]:
                artifacts = Path(result["artifact_dir"])
                for label, namespace, selector in (
                        ("loadgenerator", inject.NS, "app=loadgenerator"),
                        ("frontend", inject.NS, "app=frontend"),
                        ("target", inject.NS, f"app={exp['target']}"),
                        ("chaos-daemon", "chaos-mesh", "app.kubernetes.io/component=chaos-daemon")):
                    try:
                        capture.logs(artifacts / f"{label}-logs.csv", namespace, selector, "10m")
                    except Exception as error:
                        result["collection_errors"].append(getattr(error, "stderr", None) or str(error))
            summary.append(result)
            if not passed:
                break
    except Exception as error:
        summary.append({"error": getattr(error, "stderr", None) or str(error), "injected": False})
    finally:
        (directory / "summary.json").write_text(json.dumps(summary, indent=2))
        print(json.dumps(summary, indent=2))
        print(f"Verification summary: {directory / 'summary.json'}")
    return 1 if any("error" in result or result.get("passed") is False or result.get("collection_errors")
                    for result in summary) else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
