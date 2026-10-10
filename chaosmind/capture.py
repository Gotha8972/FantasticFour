"""Export real pod logs, live metric samples, or existing JSONL events as CSV."""
import argparse
import csv
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import time

from chaosmind import inject
from chaosmind.monitor import snapshot
from chaosmind.runlog import FIELDS

METRICS = ["timestamp_utc", "phase", "ts", "users", "rps", "requests", "failures", "error_rate",
           "p95_ms", "checkout_success", "unhealthy_services", "restarts", "metrics_age_s", "source", "error"]


def destination(path, fields):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents overwriting evidence from an earlier run.
    handle = path.open("x", newline="")
    writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    handle.flush()
    return handle, writer


def metrics(output, duration, interval, phase):
    handle, writer = destination(output, METRICS)
    deadline = time.monotonic() + duration
    try:
        while True:
            row = {"timestamp_utc": datetime.now(timezone.utc).isoformat(), "phase": phase}
            try:
                row.update(snapshot())
                row["unhealthy_services"] = json.dumps(row["unhealthy_services"])
                row["restarts"] = json.dumps(row["restarts"])
            except Exception as error:
                row["error"] = getattr(error, "stderr", None) or str(error)
                writer.writerow(row)
                handle.flush()
                raise
            writer.writerow(row)
            handle.flush()
            print(json.dumps(row), flush=True)
            if time.monotonic() >= deadline:
                break
            time.sleep(min(interval, max(0, deadline - time.monotonic())))
    finally:
        handle.close()


def logs(output, namespace, selector, since):
    pods = json.loads(inject.kubectl("get", "pods", "-n", namespace, "-l", selector, "-o", "json"))["items"]
    if not pods:
        raise RuntimeError(f"No pods matched {selector} in {namespace}")
    fields = ["collected_at_utc", "timestamp_utc", "namespace", "pod", "container", "message", "collection_error"]
    handle, writer = destination(output, fields)
    failures = 0
    try:
        for pod in pods:
            for container in pod["spec"]["containers"]:
                base = {"collected_at_utc": datetime.now(timezone.utc).isoformat(),
                        "namespace": namespace, "pod": pod["metadata"]["name"], "container": container["name"]}
                try:
                    content = inject.kubectl("logs", base["pod"], "-n", namespace, "-c", base["container"],
                                             "--timestamps=true", f"--since={since}")
                    for line in content.splitlines():
                        stamp, separator, message = line.partition(" ")
                        writer.writerow(base | {"timestamp_utc": stamp if separator else "",
                                                "message": message if separator else line})
                except Exception as error:
                    failures += 1
                    writer.writerow(base | {"collection_error": getattr(error, "stderr", None) or str(error)})
                handle.flush()
    finally:
        handle.close()
    if failures:
        raise RuntimeError(f"{failures} container log collections failed; see collection_error in CSV")


def convert(source, output):
    handle, writer = destination(output, FIELDS)
    try:
        with Path(source).open() as records:
            for line in records:
                if not line.strip():
                    continue
                event = json.loads(line)
                row = {key: event.get(key, "") for key in FIELDS}
                for key in ("unhealthy_services", "restarts"):
                    if key in event:
                        row[key] = json.dumps(event[key])
                row["details_json"] = json.dumps(event)
                writer.writerow(row)
    finally:
        handle.close()


def positive(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return number


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    metric_parser = subparsers.add_parser("metrics")
    metric_parser.add_argument("--duration", type=positive, default=60)
    metric_parser.add_argument("--interval", type=positive, default=2)
    metric_parser.add_argument("--phase", default="baseline")
    metric_parser.add_argument("--output", required=True)
    log_parser = subparsers.add_parser("logs")
    log_parser.add_argument("--namespace", choices=[inject.NS, "chaos-mesh"], default=inject.NS)
    log_parser.add_argument("--selector", default="app=loadgenerator")
    log_parser.add_argument("--since", default="10m")
    log_parser.add_argument("--output", required=True)
    convert_parser = subparsers.add_parser("convert")
    convert_parser.add_argument("source")
    convert_parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.command == "metrics":
        metrics(args.output, args.duration, args.interval, args.phase)
    elif args.command == "logs":
        logs(args.output, args.namespace, args.selector, args.since)
    else:
        convert(args.source, args.output)
    print(f"Saved {args.output}")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(getattr(error, "stderr", None) or str(error))
        raise SystemExit(1)
