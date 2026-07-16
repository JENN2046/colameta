# Work Item Governance operator usage

The feature is project-local and disabled by default. Enable the Shadow Ledger
without making Gate transitions authoritative:

```json
{
  "work_item_governance": {
    "shadow_ledger_enabled": true,
    "gate_mode": "shadow"
  }
}
```

Save this as `.colameta/settings.json` (local/private). Use `gate_mode` values
`off`, `shadow`, or `authoritative`; production authority must advance through
the phase review described in `PHASE_TASKBOOKS.md`.

Creation is always two explicit application commands:

```python
from runner.work_item_commands import WorkItemCommandGateway

gateway = WorkItemCommandGateway(project_root)
preview = gateway.execute(
    "preview_work_item_create",
    {
        "command": {
            "origin": {
                "kind": "manual",
                "ref": "ticket-123",
                "snapshot_digest": "<64 lowercase hex characters>",
            },
            "task": {
                "objective_ref": "ticket://123",
                "plan_version_refs": ["plan:v1"],
            },
            "idempotency_key": "ticket-123:create",
        }
    },
)
created = gateway.execute(
    "apply_work_item_create",
    {"preview": preview["preview"]},
)
```

Reads and ordinary executor runs never perform those commands implicitly. To
bind an existing execution, explicitly call `create_execution_attempt`, pass
the returned Attempt ID through Execution Envelope v2, then register only
digest-bound Artifact References. A retry must call `create_execution_attempt`
again and receive a new ID. New runtime Attempts are rejected for a stale Task
Version, a submitted Work Item, or a terminal Work Item. Legacy linkage uses
the separate `bind_historical_execution_attempt` command with `imported=true`,
a terminal status, and an explicit reason; it can never dispatch runtime work.

Runner `plan.json` may carry `work_item_id`, `task_version`, and an optional
`attempt_id` at the Plan or individual version level. Version fields override
the Plan-level reference. Work Item + Task Version without an Attempt records a
planning association only; Claim/Heartbeat/Session/Run/Report records are bound
only when all three identifiers are explicitly present. Missing identifiers are
never inferred and no Attempt is auto-created.

Transitions use `preview_work_item_transition` followed by
`apply_work_item_transition`. `in_delivery -> submitted` and
`submitted -> accepted` require current Task Version Artifact evidence and a
compatible append-only Review Decision. `PASSED` is not accepted authority.

Decision and transition calls also require a trusted Principal injected outside
the command body:

```python
from runner.work_item_governance import trusted_principal_context
from runner.work_item_commands import WorkItemCommandGateway

# Composition-root example: values must come from an authenticated local,
# OAuth, or Commander session and its policy grants, not request JSON.
principal = trusted_principal_context(
    principal_id="authenticated-reviewer-id",
    principal_kind="human",
    authenticated_by="commander",
    granted_permissions=["work_item.accept", "work_item.return_for_revision"],
    session_ref="commander:verified-session-id",
)
gateway = WorkItemCommandGateway(project_root, principal_context=principal)
```

For the local MCP control plane, the process operator may instead configure
`COLAMETA_WORK_ITEM_PRINCIPAL_ID`, `COLAMETA_WORK_ITEM_PERMISSIONS` (space- or
comma-separated), and an optional `COLAMETA_WORK_ITEM_SESSION_REF`. These
process-owned values produce an `authenticated_by=local_session` Principal;
ordinary request JSON and a generic MCP scope still cannot grant permissions.

To revise submitted work, record `request_changes` or `reject`, then apply the
`submitted -> in_delivery` Gate with
`work_item.return_for_revision`. Only then may `add_task_version` create the
next version. That version must pass submission and acceptance again.

Acceptance atomically freezes the Gate's exact Artifact and Decision IDs in
`accepted_evidence_manifest`. Terminal Work Items reject additional Artifacts.
Stable Promotion reads this frozen manifest and still requires a separate,
exact-commit deployment authorization.

Use `backup_ledger()` / `restore_ledger()` on
`WorkItemApplicationService` for local recovery. Both operations use the SQLite
Backup API and verify `integrity_check`; never copy the active database or its
WAL/SHM files. Restore additionally requires the current
`database_generation` from `service.status()` and fails if any Ledger reader or
writer still holds the maintenance lock. `export_audit_package()` produces a
structured, digest-bound export without the preview signing key or Artifact
bodies.
