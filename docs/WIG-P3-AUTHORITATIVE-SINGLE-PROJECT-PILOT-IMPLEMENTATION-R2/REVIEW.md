# WIG-P3 Single-Project Pilot Implementation R2 Closeout

R2 closes the three independently reproduced authority defects in D1: Lease preparation now requires a consumed, sealed one-shot authorization capability; the explicit v5-to-v6 migration evaluates every frozen postcondition before its single commit; and target project storage is disjoint from the private Pilot runtime root.

The runtime additionally refuses fabricated process/listener transitions, verifies the exact frozen contract bytes when the control plane or Guard is composed, generates a private bearer token rather than accepting caller-asserted token digests, and can construct a schema-valid v4 Preflight from the fresh Ledger/Backup fact.

Verification completed with 1393 passing tests, 2 skips, 55 passing subtests, including contract-level execution of all 96 frozen negative-matrix rows against semantic Rule/error-code or boundary-category mappings, plus Ruff, changed-scope Bandit, pip-audit, and Wheel resource inventory checks. The repository-wide Bandit baseline remains 168 Low, 8 Medium, and 0 High findings; it is recorded rather than rewritten in this remediation.

No deployment, activation, real Work Item operation, Push, Stable Promotion, existing service change, existing Canary change, or main-workspace Ledger creation occurred. The four protected `AGENTS*` assets remain outside the candidate scope.

This closeout does not authorize deployment or Authoritative activation. It prepares one new local exact-commit candidate for independent review.
