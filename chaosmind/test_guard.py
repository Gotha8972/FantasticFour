"""No cluster needed: python -m chaosmind.test_guard"""
from chaosmind.guard import LIMITS, breach
from chaosmind.inject import manifest, validate

ok = {"error_rate": 0.01, "p95_ms": 150, "unhealthy_services": []}
assert breach(ok, LIMITS) is None
assert breach(ok | {"p95_ms": 2500}, LIMITS) == ("p95_ms", 2500, 2000)
assert breach(ok | {"unhealthy_services": ["a", "b", "c"]}, LIMITS) == ("unhealthy", 3, 2)
assert breach(ok | {"unhealthy_services": ["a"]}, LIMITS | {"max_unhealthy": 0})[0] == "unhealthy"

exp = {"id": "exp-001", "fault": "network_delay", "target": "productcatalogservice",
       "params": {"latency": "500ms"}, "duration_s": 60}
validate(exp)
m = manifest(exp)
assert m["kind"] == "NetworkChaos" and m["spec"]["duration"] == "60s"
assert m["spec"]["selector"]["namespaces"] == ["boutique"]
assert manifest(exp | {"fault": "pod_failure"})["spec"]["action"] == "pod-failure"

for bad in [{"duration_s": 999}, {"fault": "delete_everything"}, {"id": "Bad_ID"}]:
    try:
        validate(exp | bad)
        raise AssertionError(f"accepted {bad}")
    except ValueError:
        pass
print("all checks passed")
