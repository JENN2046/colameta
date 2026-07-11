# WIG R1 authority and lifecycle closeout

Stage: `WIG_R1_AUTHORITY_AND_LIFECYCLE_CLOSEOUT`

This package closes the authority/lifecycle findings from the external Phase
0–5 implementation review. It does not enable authoritative mode, commit the
workspace, push a branch, or authorize stable promotion.

## R1-A — trusted Principal

- `PrincipalContext` is an opaque in-process capability issued only by a
  composition root from authenticated local/OAuth/Commander facts.
- MCP establishes a request-scoped Principal before dispatching a Work Item
  command. A generic `mcp:commit` scope is deliberately not mapped to Work Item
  permissions.
- Review Decision and transition command bodies reject caller-provided Actor,
  authority basis, or Principal fields.
- Policy evaluation derives Actor and authority basis from the Principal's
  granted permission. Decision and Gate records persist the trusted Principal
  binding; migrated pre-trust records fail closed as Gate authority.
- Direct Python callers must explicitly provide a trusted execution context.

## R1-B — revision loop

- The executable lifecycle adds `submitted -> in_delivery` with
  `transition_result=returned_for_revision`.
- It requires `request_changes` or `reject` and
  `work_item.return_for_revision` authority.
- `add_task_version` rejects a submitted Work Item. After a successful revision
  Gate, the next Task Version increments aggregate `state_version`.
- Decisions and evidence are Task-Version scoped, so the revised version must
  pass submission and acceptance again.

## R1-C — Acceptance Manifest

- The Acceptance Gate atomically freezes Task Version, Artifact IDs and their
  immutable metadata/digests, Decision IDs, Principal, Gate ID, accepted state
  version, and deterministic Artifact manifest digest.
- Acceptance Manifest rows are append-only. Reads recompute the digest and ID
  binding and fail closed on out-of-band tampering.
- Terminal Work Items reject new Artifact References. Existing idempotent facts
  remain replayable.
- Stable Promotion accepts only Artifacts in the frozen final Acceptance
  Manifest, on the same Task Version and accepted state version. Exact-commit
  deployment authorization remains a separate mandatory input.

## R1-D — Attempt lifecycle

- `create_execution_attempt` creates runtime Attempts only for the current Task
  Version of a nonterminal, non-submitted Work Item.
- `bind_historical_execution_attempt` is separate, requires `imported=true`, an
  explicit historical reason and a terminal status, and grants no dispatch
  authority.
- Executor preflight checks dispatch authority for a complete Work Item binding.
  Unbound compatibility execution remains unchanged.

## R1-E — restore safety

- Every Ledger read/write/backup holds a shared project maintenance lock.
- Restore takes `.colameta/ledger/work-items.restore.lock` exclusively and
  non-blocking, thereby rejecting active readers/writers/dispatchers.
- Restore requires an expected database-generation token, stages with SQLite's
  Backup API, checkpoints staged WAL state, performs integrity/foreign-key
  checks, atomically replaces the database, and increments the generation.

## R1-F — production composition and isolation

- The real Commander manifest invokes `CommanderProjectionService` for Core,
  Service Operations, and App Submission projections.
- Release Submission readiness references Work Items through
  `AppSubmissionWorkItemCommands`; its create path remains explicit
  `preview_work_item_create -> apply_work_item_create`.
- Stable readiness/evidence can bind a candidate to the frozen Acceptance
  Manifest but remains ineligible without separate deployment authorization.
- Architecture checks use an explicit side-context manifest plus forward-looking
  connector/tunnel/OAuth/product/operations/stable discovery patterns.

## Required negative tests

- `test_caller_cannot_self_assert_commander_authority`
- `test_untrusted_actor_cannot_record_accept_decision`
- `test_submitted_task_cannot_add_new_version_without_revision_gate`
- `test_returned_for_revision_requires_request_changes_decision`
- `test_new_task_version_must_pass_submission_gate`
- `test_terminal_work_item_rejects_new_runtime_attempt`
- `test_stale_task_version_rejects_new_runtime_attempt`
- `test_historical_attempt_has_no_dispatch_authority`
- `test_post_accept_artifact_not_part_of_acceptance_manifest`
- `test_stable_promotion_rejects_artifact_not_bound_to_acceptance_gate`
- `test_restore_rejects_active_writer`
- `test_commander_runtime_uses_three_owned_projections`

Actual commands, timestamps, source binding, exit codes, coverage/security
summaries, wheel contents, and protected-asset hashes are recorded in
`R1_CLOSEOUT_RECEIPT.json` after the final verification run.

## Rollback and authority boundary

Disable `work_item_governance.shadow_ledger_enabled` or return `gate_mode` to
`shadow`; preserve append-only facts. Restore only from a verified Backup-API
snapshot using the expected generation. Do not downgrade the schema, rewrite an
Acceptance Manifest, or turn historical Attempts into runtime Attempts.

No part of this closeout is exact-HEAD deployment authorization. Stable service
replacement remains prohibited until a separately reviewed clean commit and
explicit promotion authorization exist.
