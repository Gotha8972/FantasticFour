"""Kill switch: preflight -> inject -> watch -> auto-revert -> confirm recovery.

python -m chaosmind.guard exp.json ['{"max_unhealthy": 0}']   # optional limit overrides as JSON
"""
import json
import pathlib
import sys
import time

from chaosmind import inject

LIMITS = {"error_rate": 0.20, "p95_ms": 2000, "max_unhealthy": 2,
          "poll_s": 2, "recovery_timeout_s": 120}


def snapshot():
    # ponytail: stub until B's monitor.snapshot() lands; only health is real, error_rate/p95 are 0. Same shape, swap the import.
    deps = json.loads(inject.kubectl("get", "deploy", "-n", inject.NS, "-o", "json"))["items"]
    bad = [d["metadata"]["name"] for d in deps
           if d["status"].get("readyReplicas", 0) < d["spec"]["replicas"]]
    return {"ts": time.time(), "error_rate": 0.0, "p95_ms": 0, "unhealthy_services": bad}


def breach(snap, lim):
    """Return (metric, value, limit) for the first limit crossed, else None."""
    for metric, value, limit in [("error_rate", snap["error_rate"], lim["error_rate"]),
                                 ("p95_ms", snap["p95_ms"], lim["p95_ms"]),
                                 ("unhealthy", len(snap["unhealthy_services"]), lim["max_unhealthy"])]:
        if value > limit:
            return metric, value, limit
    return None


def run(exp, limits=None):
    lim = LIMITS | (limits or {})
    out = pathlib.Path("runs") / f"{exp['id']}.jsonl"
    out.parent.mkdir(exist_ok=True)
    t0 = time.monotonic()
    events = []

    def log(event, **kw):
        e = {"t": round(time.monotonic() - t0, 1), "event": event, **kw}
        events.append(e)
        print(json.dumps(e), flush=True)
        with out.open("a") as f:
            f.write(json.dumps(e) + "\n")

    # 1. preflight
    snap = snapshot()
    if inject.running():
        log("REFUSED", reason="another chaos experiment is already running")
        return events
    if b := breach(snap, lim):
        log("REFUSED", reason="system already unhealthy", metric=b[0], value=b[1], limit=b[2])
        return events

    # 2-3. inject + watch; finally guarantees revert on breach, timeout, crash or Ctrl-C
    inject.apply(exp)
    log("INJECTED", fault=exp["fault"], target=exp["target"], params=exp.get("params", {}))
    try:
        while time.monotonic() - t0 < exp["duration_s"]:
            time.sleep(lim["poll_s"])
            if b := breach(snapshot(), lim):
                log("BREACH", metric=b[0], value=b[1], limit=b[2])
                break
        else:
            log("ENDED", reason="planned duration reached")
    finally:
        inject.revert(exp)
        log("REVERTED")

    # 4. confirm recovery
    reverted_at = time.monotonic()
    while time.monotonic() - reverted_at < lim["recovery_timeout_s"]:
        snap = snapshot()
        if not snap["unhealthy_services"] and not breach(snap, lim):
            log("HEALTHY", recovery_s=round(time.monotonic() - reverted_at, 1))
            return events
        time.sleep(lim["poll_s"])
    log("NOT_RECOVERED", unhealthy=snap["unhealthy_services"])  # this is a finding, not a bug
    return events


if __name__ == "__main__":
    run(json.load(open(sys.argv[1])), json.loads(sys.argv[2]) if len(sys.argv) > 2 else None)
