"""Apply / revert Chaos Mesh faults via kubectl.

python -m chaosmind.inject apply exp.json | revert exp.json | abort
"""
import json
import re
import subprocess
import sys

NS = "boutique"
MAX_DURATION_S = 120
KINDS = {"pod_failure": "PodChaos", "network_delay": "NetworkChaos"}


def kubectl(*args, stdin=None):
    return subprocess.run(["kubectl", *args], input=stdin, text=True,
                          capture_output=True, check=True).stdout


def validate(exp):
    if exp["fault"] not in KINDS:
        raise ValueError(f"unknown fault {exp['fault']!r}, allowed: {list(KINDS)}")
    if not re.fullmatch(r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?", exp["id"]):
        raise ValueError(f"id {exp['id']!r} must be lowercase letters, digits, dashes")
    if not 0 < exp["duration_s"] <= MAX_DURATION_S:
        raise ValueError(f"duration_s must be 1..{MAX_DURATION_S}")


def manifest(exp):
    p = exp.get("params", {})
    spec = {"mode": "all",
            "duration": f"{exp['duration_s']}s",  # fail-safe: Chaos Mesh ends it even if guard dies
            "selector": {"namespaces": [NS], "labelSelectors": {"app": exp["target"]}}}
    if exp["fault"] == "network_delay":
        spec |= {"action": "delay",
                 "delay": {"latency": p.get("latency", "500ms"), "jitter": p.get("jitter", "50ms"),
                           "correlation": "50"}}
    else:
        spec["action"] = "pod-failure"
    return {"apiVersion": "chaos-mesh.org/v1alpha1", "kind": KINDS[exp["fault"]],
            "metadata": {"name": exp["id"], "namespace": NS}, "spec": spec}


def apply(exp):
    validate(exp)
    kubectl("get", "deploy", exp["target"], "-n", NS)  # raises if target doesn't exist in our namespace
    kubectl("apply", "-f", "-", stdin=json.dumps(manifest(exp)))


def revert(exp):
    kubectl("delete", KINDS[exp["fault"]].lower(), exp["id"], "-n", NS, "--ignore-not-found")


def running():
    return kubectl("get", ",".join(k.lower() for k in set(KINDS.values())), "-n", NS, "-o", "name").split()


def abort_all():
    kubectl("delete", ",".join(k.lower() for k in set(KINDS.values())), "-n", NS, "--all")


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "abort":
        abort_all()
    else:
        exp = json.load(open(sys.argv[2]))
        {"apply": apply, "revert": revert}[cmd](exp)
    print("ok")
