"""Write lifecycle events and measured metrics to CSV and JSONL immediately."""
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import time

FIELDS = ["timestamp_utc", "t", "event", "experiment_id", "fault", "target", "reason",
          "metric", "value", "limit", "recovery_s", "users", "rps", "requests", "failures",
          "error_rate", "p95_ms", "checkout_success", "unhealthy_services", "restarts", "details_json"]


class RunLog:
    def __init__(self, exp):
        self.exp = exp
        self.start = time.monotonic()
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        self.directory = Path("runs") / f"{exp['id']}-{stamp}"
        self.directory.mkdir(parents=True)
        for name in ("events.csv", "metrics.csv"):
            with (self.directory / name).open("w", newline="") as handle:
                csv.DictWriter(handle, fieldnames=FIELDS).writeheader()
        self.events = []

    def log(self, event, **details):
        record = {"timestamp_utc": datetime.now(timezone.utc).isoformat(),
                  "t": round(time.monotonic() - self.start, 3), "event": event,
                  "experiment_id": self.exp["id"], "fault": self.exp["fault"],
                  "target": self.exp["target"], "artifact_dir": str(self.directory), **details}
        self.events.append(record)
        print(json.dumps(record), flush=True)
        with (self.directory / "events.jsonl").open("a") as handle:
            handle.write(json.dumps(record) + "\n")
        row = {key: record.get(key, "") for key in FIELDS}
        for key in ("unhealthy_services", "restarts"):
            if key in record:
                row[key] = json.dumps(record[key])
        row["details_json"] = json.dumps(details)
        for name in ["events.csv"] + (["metrics.csv"] if event == "SNAPSHOT" else []):
            with (self.directory / name).open("a", newline="") as handle:
                csv.DictWriter(handle, fieldnames=FIELDS).writerow(row)
