"""Resilience score, 0-100. Plain code: documented, recomputable, never AI.

score = 100 - E - L - R - B - I   (never below 0)
  E error impact   = 40 x sqrt(extra error rate / 50%), capped at 40   5% costs 13, 12.5% costs 20, 50%+ costs 40
  L latency impact = 25 x sqrt(extra p95 / 10 s), capped at 25         +1 s costs 8, +3 s costs 14, +10 s costs 25
    Square roots, not straight lines with low caps: the old caps (+10% errors, +2 s) were hit by almost every
    experiment, so a 12% error spike and a total outage scored the same.
  R recovery       = min(15, recovery seconds / 4)                    60 s costs 15
  B blast radius   = 10 x share of the system in the target's blast radius (facts.py), only when customers were
                     hurt (guard limits crossed or an integrity check failed): a contained failure has no blast
  I integrity      = 40 if any business check failed                  silent data loss can never score well
"""
from chaosmind import guard


def score(observed, baseline, recovery_s=None, violations=(), blast_share=0.0):
    observed = observed or {}
    base = (baseline or {}).get('metrics') or {}
    base_err = (base.get('error_rate') or {}).get('mean', 0.0)
    base_p95 = (base.get('p95_ms') or {}).get('mean', 0.0)
    hurt = bool(violations) or (observed.get('error_rate') or 0) > guard.LIMITS['error_rate'] \
        or (observed.get('p95_ms') or 0) > guard.LIMITS['p95_ms']
    breakdown = {
        'E': 40 * min(1.0, max(0.0, (observed.get('error_rate') or 0.0) - base_err) / 0.5) ** 0.5,
        'L': 25 * min(1.0, max(0.0, (observed.get('p95_ms') or 0.0) - base_p95) / 10000) ** 0.5,
        'R': min(15.0, (recovery_s or 0) / 4),
        'B': 10 * blast_share if hurt else 0.0,
        'I': 40.0 if violations else 0.0}
    return {'score': round(max(0.0, 100 - sum(breakdown.values()))),
            'breakdown': {k: round(v, 1) for k, v in breakdown.items()}}
