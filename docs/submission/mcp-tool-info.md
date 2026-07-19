# MCP Tool Information Evidence

## tool_inventory

- Project: `colameta-self-dev`
- Public MCP exposure profile: `commander`
- Public visible tool count: 7
- Legacy normal-profile inventory: `chatgpt-app-submission.json`
- Legacy inventory SHA-256:
  `35879d78190404893ad9fb6c2796e2a23e49ef4b39222492b8a7b09080cb643d`

The public Commander surface contains exactly these tools, in runtime order:

1. `list_registered_projects`
2. `get_apps_connector_smoke_packet`
3. `render_commander_app`
4. `analyze_project_state`
5. `run_mcp_workflow`
6. `manage_validation_run`
7. `manage_git`

The checked-in submission JSON predates this constrained public profile and
still contains the complete 82-tool normal inventory. It is retained as legacy
evidence only. A fresh seven-tool import artifact must be generated and reviewed
before submission readiness can be marked true.

## scope_map

- `mcp:read`: strictly reads or computes project-scoped evidence.
- `mcp:preview`: creates a bounded preview but does not apply the proposed action.
- `mcp:commit`: performs an explicit, permission-scoped local mutation or run.
- `mcp:plan`: reserved plan authority; denied by the current remote public policy.

Action-dependent tools select their scope from an explicit action or phase. The
Commander-profile annotation audit classifies:

- strictly read-only tools as `readOnlyHint=true`;
- local write, overwrite, delete, or executor tools as `readOnlyHint=false`;
- `manage_git` as `openWorldHint=true` because it can interact with Git remotes;
- overwrite/delete/restore/revert actions as `destructiveHint=true`;
- fixed validation execution as non-read-only but non-destructive.

## side_effects

The generated submission file does not execute tools. Mutating tools retain
their existing preview/apply, confirmation, scope, and project-routing guards.
The remote public service policy continues to deny commit and plan scopes unless
its service configuration explicitly permits them.

## safety_boundaries

Source inspection found no Commander-profile input fields that solicit
passwords, API keys, OAuth secrets, MFA codes, payment data, government
identifiers, biometrics, or health data. All seven public tools declare an
`outputSchema`.

Commander widget CSP uses empty `connectDomains`, `resourceDomains`,
`connect_domains`, and `resource_domains` lists because the widget does not load
external resources. No token, cookie, private browser state, tunnel credential,
provider secret, raw log, request ID, stack trace, or local filesystem path is
required by the seven public tools. The legacy submission JSON must not be used
as proof of the current public surface.

## verification

- Required annotations present on the live Commander surface: 7/7.
- Output schemas present on the live Commander surface: 7/7.
- Positive submission tests: 5.
- Negative submission tests: 3.
- Fresh pull-request CI: Python 3.10-3.14 and quality gates passed.

Human review and regeneration of the seven-tool submission JSON are still
required before `mcp_tool_info_ready=true`.
