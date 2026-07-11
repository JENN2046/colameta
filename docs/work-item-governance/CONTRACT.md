# ColaMeta Work Item Governance Contract v1

Status: frozen implementation contract. The JSON Schemas in
`schemas/work_item_governance/` are the authoritative wire definitions. The
Python transition policy in `runner/work_item_governance/contracts.py` is the
authoritative executable lifecycle definition.

## Context map and dependency rule

The allowed core dependency direction is:

```text
Project Catalog
  -> Work Item Governance
Planning -> Work Item Governance
Work Item Governance -> Execution Governance
Execution Governance -> Evidence & Artifact
Evidence & Artifact -> Review & Delivery
Core Read Models -> Surface Projections
```

Service Operations, App Productization, and Stable Promotion & Deployment are
side contexts. They may call public application commands or consume public read
models. They may not import a Ledger repository, write Ledger tables, or infer
delivery state. The Work Item core may not import MCP/Web transports, product
submission, connector/OAuth/tunnel/proxy code, stable promotion, or a concrete
Codex/executor provider. CI enforces this direction with an AST import check.

Commander remains one shell with three projections:

- Core: Work Item, Execution, Evidence, Review, Delivery.
- Service Operations: Connector, Tunnel, Proxy, DNS, OAuth, Runtime Health.
- App Submission: submission material, screenshots, logo, localization,
  security review, and release material.

Only the Core application service changes Work Item state. Runner `PASSED`, an
executor completion, a connector result, a stable promotion result, a product
submission, or a generic project decision is evidence only.

## Glossary and identity

- **Work Item** (`wi_<uuidv7>`): task aggregate root. It survives deletion of
  its source and owns lifecycle state.
- **Task Version** (positive integer): immutable task intent/contract snapshot
  within a Work Item. It is not a Plan Version.
- **Execution Attempt** (`attempt_<uuidv7>`): one execution try against one Task
  Version. A retry creates a new Attempt. Runtime Attempts may dispatch only for
  the current nonterminal Task Version; imported historical bindings are
  immutable and never have dispatch authority.
- **Artifact Reference** (`artifact_<uuidv7>`): digest-bound URI and immutable
  source reference; it never copies source/report bodies into the Ledger.
- **Decision Record** (`decision_<uuidv7>`): append-only review action with
  actor, authority basis, and evidence.
- **Gate Event** (`gate_<uuidv7>`): append-only applied/rejected transition fact.
  It never changes state by itself.
- **Principal Context**: trusted authenticated identity, authentication method,
  session reference, and policy-granted Work Item permissions. It is injected
  by the control plane and is never deserialized from a command body.
- **Acceptance Evidence Manifest**: immutable Artifact and Decision set frozen
  by the final applied Acceptance Gate, including its Task Version, Gate ID,
  accepted state version, and deterministic manifest digest.
- **Delivery Receipt** (`delivery_<uuidv7>`): delivery/acknowledgement fact,
  independent of lifecycle state.
- **blocked**: an independently projected condition, not a lifecycle state.

Every origin has `kind`, nullable `ref`, and a SHA-256 `snapshot_digest`.
`origin.ref` is never a primary key. Imported history is explicitly marked
`origin.kind=imported`; ColaMeta never automatically scans, infers, or backfills
historical Plans, Runs, Reports, Taskbooks, or Workflow Records.

## Lifecycle and fail-closed transition policy

```text
proposed -> ready -> in_delivery -> submitted -> accepted
    |          |          ^       |          |
    |          |          +-------+          |
    +----------+-----------------------------+-> cancelled
                       returned_for_revision
```

`accepted` and `cancelled` are irreversible terminal states. The application
service validates and commits a transition in one `BEGIN IMMEDIATE` transaction:

1. derive Actor and authority from a trusted Principal Context, then validate
   current state, current Task Version, Decisions, Artifact evidence, and
   active blockers;
2. compare-and-swap `work_items.state_version`;
3. append the Gate Event;
4. append Audit and Outbox events.

| From | To | Authority basis | Decision | Evidence | Active blockers |
| --- | --- | --- | --- | --- | --- |
| proposed | ready | `work_item.ready` | none | none | allowed |
| ready | in_delivery | `work_item.start_delivery` | none | none | rejected |
| in_delivery | submitted | `work_item.submit` | submit/approval | Artifact required | rejected |
| submitted | accepted | `work_item.accept` | accept/approval | Artifact required | rejected |
| submitted | in_delivery | `work_item.return_for_revision` | request changes/reject | none | allowed |
| any nonterminal | cancelled | `work_item.cancel` | cancel | none | allowed |

Unknown transitions, stale Task Versions, missing/foreign evidence, missing
authority, incompatible Decisions, expired/project-mismatched previews, digest
mismatches, and CAS conflicts fail closed. After the Ledger exists, transition
rejections are recorded as `transition_rejected` Gate/Audit events without a
state change. No Runner status is a transition input.

The `submitted -> in_delivery` transition records
`transition_result=returned_for_revision`. A submitted Work Item cannot receive
a new Task Version until that Gate succeeds. The new Task Version increments
`state_version`; all Decisions and evidence remain Task-Version scoped, so the
revised version must pass its own submission and acceptance Gates.

Decision and Gate commands reject caller-provided `actor`, `authority_basis`,
or serialized principal fields. The authenticated MCP/Auth/local control plane
must inject an opaque `PrincipalContext`; a policy evaluator derives both Actor
and authority basis from its granted permissions. A generic `mcp:commit` scope
does not grant any Work Item permission. Pre-trust Decision records migrated
from an earlier development Ledger are not valid Gate authority.

An applied Acceptance Gate atomically appends one Acceptance Evidence Manifest.
Terminal Work Items reject new Artifact References and runtime Attempts;
idempotent replays of already recorded facts remain readable. Stable Promotion
may consume only the frozen manifest attached to the final applied Gate, on the
same Task Version and accepted state version. It must independently obtain
exact-commit deployment authorization and can never write acceptance back.

## Existing-record reference map

| Current record | New reference, when explicitly supplied | Authority retained |
| --- | --- | --- |
| Plan / Plan Version | `task_versions.plan_version_refs` | Planning only |
| Executor Claim / Session / Run | `execution_attempts.attempt_id` | Execution runtime only |
| Executor Report / Validation | `artifact_refs` (`report`/`validation`) | Evidence only |
| Git Commit / Diff / File / Test report | `artifact_refs` | Evidence only |
| Taskbook | Task Version payload/contract reference | Planning constraint only |
| Workflow Record | Audit timeline reference | Tool-operation audit only |
| Generic Project Decision | Project Knowledge reference | no review authority |
| Local / Imported / Evidence Receipt | Work Item, Task Version, Attempt and Artifact IDs | Evidence only |

All references are optional on compatibility paths. An unbound Plan/Run/Report
continues to behave as before and does not create a Work Item.

## Data layout, security, privacy, and recovery

`.colameta/ledger/work-items.sqlite3` is `project_local_durable`: private,
project-bound, excluded from Git, outside `.colameta/runtime/**`, and retained
until the project owner explicitly deletes it. Its directory mode is `0700` and
database/backup mode is `0600`. SQLite enables foreign keys, WAL and a bounded
busy timeout; writes use `BEGIN IMMEDIATE`. Migrations are forward-only and
transactional. Unsupported future schemas fail closed.

The Ledger stores canonical JSON, identifiers, minimal metadata, digests and
URIs. It must not store source bodies, report bodies, credentials, OAuth tokens,
connector secrets, prompt secrets, or unrestricted environment snapshots.
Application limits reject oversized JSON, text, and URIs. Exports redact the
Ledger signing key and contain a manifest plus deterministic record digests.

Backups and restores use SQLite's Backup API; copying an active database, WAL,
or SHM file is forbidden. Restore acquires the project-local
`.colameta/ledger/work-items.restore.lock` exclusively and non-blocking, which
drains/blocks readers, writers, and Ledger-backed outbox dispatch. It requires
an expected database-generation CAS token, stages through a private temporary
database, checkpoints/removes staged WAL state, and verifies both staged and
final copies with `integrity_check` and `foreign_key_check`. The generation is
incremented after a successful restore. Rollback means disabling the feature
flag and restoring a verified pre-phase backup. Schema downgrades are never
attempted.

## Feature rollout

Phase 1 defaults off behind the project setting
`work_item_governance.shadow_ledger_enabled`. Phase 2 only adds optional
references. Phase 3 begins in shadow evaluation before becoming authoritative.
Phase 4/5 isolation follows only after authority is stable. Stable promotion
always requires separate exact-commit authorization and is never triggered by
this contract.
