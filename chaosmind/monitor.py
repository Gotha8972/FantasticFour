"""Real Locust CSV statistics and Kubernetes deployment/pod health."""
import json
import time
from chaosmind import inject

READ_STATS = r'''
import csv, json
def rows(path):
    with open(path, newline='') as f:
        return list(csv.DictReader(f))
stats = rows('/stats/load_stats.csv')
history = rows('/stats/load_stats_history.csv')
aggregate = next(r for r in stats if r['Name'] == 'Aggregated')
recent = next(r for r in reversed(history) if r.get('Name') == 'Aggregated')
checkout = [r for r in stats if r.get('Name') == '/cart/checkout']
print(json.dumps({'aggregate': aggregate, 'recent': recent, 'checkout': checkout}))
'''


def snapshot():
    workloads = json.loads(inject.kubectl("get", "deployments,pods", "-n", inject.NS, "-o", "json"))["items"]
    bad, restarts = [], {}
    for item in workloads:
        name = item["metadata"]["name"]
        if item["kind"] == "Deployment" and item["spec"].get("replicas", 1) > 0:
            if item.get("status", {}).get("readyReplicas", 0) < item["spec"].get("replicas", 1):
                bad.append(name)
        elif item["kind"] == "Pod":
            service = item["metadata"].get("labels", {}).get("app", name)
            restarts[service] = restarts.get(service, 0) + sum(
                c.get("restartCount", 0) for c in item.get("status", {}).get("containerStatuses", []))
    data = json.loads(inject.kubectl("exec", "-i", "deployment/loadgenerator", "-n", inject.NS,
                                     "-c", "main", "--", "python", "-", stdin=READ_STATS))
    total, recent = data["aggregate"], data["recent"]
    age = time.time() - float(recent["Timestamp"])
    users = int(recent["User Count"])
    if age > 15 or age < -5 or users < 1 or int(total["Request Count"]) < 1:
        raise RuntimeError(f"Locust metrics are stale or traffic is absent (age={age:.1f}s, users={users})")
    rps = float(recent["Requests/s"])
    failures_per_s = float(recent["Failures/s"])
    if rps <= 0:
        raise RuntimeError("Locust reports zero completed RPS; refusing to treat missing traffic as healthy")
    checkout_requests = sum(int(r["Request Count"]) for r in data["checkout"])
    checkout_failures = sum(int(r["Failure Count"]) for r in data["checkout"])
    return {"ts": time.time(), "error_rate": min(1.0, failures_per_s / rps),
            "p95_ms": float(recent["95%"]), "users": users, "rps": rps,
            "requests": int(total["Request Count"]), "failures": int(total["Failure Count"]),
            "checkout_success": 1 - checkout_failures / checkout_requests if checkout_requests else None,
            "unhealthy_services": sorted(bad), "restarts": restarts, "metrics_age_s": age,
            "source": "locust_csv_and_kubernetes"}
