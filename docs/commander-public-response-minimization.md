# Commander Public Response Minimization

## Contract

The seven-tool `commander` exposure profile applies
`commander_public_minimal.v1` to successful tool results before they are
returned through MCP `tools/call`, the legacy agent-call path, or the REST
Actions adapter. The `normal`, `maintainer`, `legacy`, and loopback advanced
profiles retain their existing full engineering responses.

The projection applies to:

- `list_registered_projects`;
- `get_apps_connector_smoke_packet`;
- `render_commander_app`;
- `analyze_project_state`;
- `run_mcp_workflow`;
- `manage_validation_run`; and
- `manage_git`.

## Removed public fields

The public projection removes local or diagnostic implementation details that
are not required for the user-facing workflow, including:

- registry and project identifiers;
- absolute project, workspace, runtime, settings, evidence, and log paths;
- process identifiers;
- timestamps, latency, elapsed-time, and workflow-record metadata;
- raw logs, stdout, stderr, and internal audit/report/request/session IDs;
- recent-commit summaries and ignored/runtime file inventories from the broad
  read-only Commander and analysis views; and
- nested recommended actions that name tools outside the active seven-tool
  exposure profile.

Local paths embedded in otherwise useful human-readable text are replaced with
`<project>` or `<local-path>`. Removed diagnostics are dropped rather than moved
into tool-result `_meta`, so the widget does not receive an unnecessary hidden
copy.

## Preserved operational fields

The projection preserves information required to complete an explicitly
requested tool workflow:

- registered `project_name`, display name, mode, and availability facts;
- connector, readiness, stale/reload, blocker, and safe-next-action facts;
- `preview_id`, `run_id`, and `validation_run_id` when a follow-up call requires
  them;
- Git-relative files, requested diff content, and commit identifiers when they
  are part of the `manage_git` job; and
- the Commander resource binding and safe widget metadata.

The connector smoke replaces raw checkout heads with a boolean
`runtime_aligned` fact plus the existing stale/reload decision fields.

## Validation boundary

Unit coverage exercises all seven tools, the MCP result envelope, the REST
Actions envelope, hidden-tool filtering, local-path redaction, operational
continuation fields, and normal-profile compatibility. A stable/public runtime
must still be replaced at an explicitly authorized exact commit before live
connector and Dashboard re-review can treat this contract as deployed.
