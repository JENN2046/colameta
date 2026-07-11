# Work Item Governance phased taskbooks

Each phase is an independently reviewable authorization boundary. A later phase
must not be used to justify an unreviewed earlier-phase mutation.

## Phase 0 — contract freeze

Scope: context map, glossary, versioned Schemas, lifecycle matrix, current-model
mapping, data classification, privacy/retention/export/backup/restore contract,
architecture rule, and this phase plan. No Runner behavior or module move.

Acceptance: every Schema loads as Draft 2020-12; executable transition tests
match the matrix; no automatic history backfill exists; all four pre-existing
`AGENTS*` workspace items retain their pre-phase SHA-256.

Rollback: documentation/schema-only revert. No persistent migration exists.

## Phase 1 — read-only Shadow Ledger

Scope: forward-only SQLite repository; explicit signed and expiring
create/import preview/apply; Work Item list/get/timeline; immutable Task Version,
Attempt and Artifact references; project-level default-off feature flag; Backup
API and integrity verification. No delivery transition is emitted.

Acceptance: multi-version/multi-attempt relationships, origin independence,
idempotent apply/registration, permissions, WAL/foreign-key/busy-timeout,
concurrency, migration rollback and verified backup/restore tests. Restore must
hold the maintenance lock, reject active connections, and match the authorized
database generation.

Rollback: disable the flag; preserve or restore a verified Phase 1 backup. The
legacy unbound path remains authoritative.

## Phase 2 — execution and evidence references

Scope: Execution Envelope v2 with optional governance references and
caller-supplied Taskbook binding; Claim/Heartbeat/Session/Run/Report references;
new Attempt per retry; digest-verified artifact registration; idempotent
completion; compatible optional fields on Local/Imported/Evidence receipts.
Runtime creation is current-version/nonterminal only; explicit historical
binding is imported, terminal, immutable, and has no dispatch authority.

Acceptance: repeated completion is a no-op, failed attempts remain queryable,
digest mismatch fails closed, and every pre-existing unbound execution test
still passes.

Rollback: stop dual-reference writes and read old records. Do not delete the
Ledger or rewrite attempts.

## Phase 3 — review, gate, and delivery

Scope: trusted Principal-bound append-only Decision/Gate/Audit records,
transactional CAS lifecycle, returned-for-revision loop, immutable Acceptance
Evidence Manifest, blocker condition, Outbox/Inbox dedupe and recovery,
independent retryable Delivery Receipts, and preview/apply transitions.

Acceptance: `PASSED` cannot accept delivery; missing evidence/decision fails
closed; repeated apply changes state once; delivery retry never changes state;
terminal states are irreversible; a caller cannot self-assert identity or
authority; post-acceptance Artifacts cannot drift the accepted evidence set.

Rollback: return to gate shadow mode. Preserve all append-only facts; do not
reverse accepted/cancelled records or downgrade schema.

## Phase 4 — surface and side-context isolation

Scope: Commander Core, Service Operations, and App Submission projections; side
contexts consume only public commands/read models; stable promotion consumes an
accepted read model plus exact commit, artifact manifest and deployment
authorization, with no reverse write.

Acceptance: connector/OAuth/tunnel failures do not mutate Work Items; stable
promotion consumes only a final frozen Acceptance Manifest and cannot bypass
Gate; App Submission has no table/repository dependency; the real Commander
manifest uses the three owned projections.

Rollback: disable a projection independently; Core application commands remain
available.

## Phase 5 — responsibility cleanup

Scope: transport-only MCP/Web/CLI composition, application-service extraction
from the legacy orchestrator, runtime-only Runner State, referenced Workflow
Record audit, Project Knowledge decisions, CI dependency checks, and measured
deprecation of unbound/legacy paths.

Acceptance: domain tests start no transport/provider; transports call public
commands; all legacy regressions pass. Compatibility deletion requires a later,
separately authorized deprecation cycle based on measured usage.

Rollback: retain compatibility adapters. Stable runtime replacement remains a
separate exact-head release operation.
