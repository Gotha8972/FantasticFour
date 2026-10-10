# Operator notes

Frontend remediation was explicitly approved by the user. Two replicas were applied, customers settled, and the comparison score improved from 18 to 97 with zero customer errors and zero integrity violations. The fix was retained.

The subsequent Redis pod kill preserved cart integrity (zero violations) but raised p95 to 3,200 ms. The Remediation model falsely said Redis used emptyDir and had lost cart state. Both audit facts and the live deployment show a PVC, and Redis still runs with `--appendonly yes`. The operator declined the redundant redis-persistence proposal. The graph records this as `not_approved`; this was an operator rejection of an incorrect proposal, not a missing approval for the already-applied Redis fix.

Cartservice remediation was subsequently approved by the user. After settling, the comparison score improved 20 → 65, errors fell to zero, and no integrity violations occurred. p95 still reached 2,700 ms and tripped the guard. The fix was kept. The graph finished all three experiments and generated FINDINGS.md.
