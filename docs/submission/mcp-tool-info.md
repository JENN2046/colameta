# MCP Tool Information Evidence

## tool_inventory

- Project: `colameta-self-dev`
- Public MCP exposure profile: `commander`
- Public visible tool count: 7
- Seven-tool candidate artifact: `chatgpt-app-submission.json`
- Candidate source commit: `b6c864c4319ceaa0afc56f4bc2b2ae96998c5f29`
- Candidate artifact SHA-256:
  `05877797d7d4115a909f64d024c2b933d089fed27b7a0791fec3412ff3e41296`

The public Commander surface contains exactly these tools, in runtime order:

1. `list_registered_projects`
2. `get_apps_connector_smoke_packet`
3. `render_commander_app`
4. `analyze_project_state`
5. `run_mcp_workflow`
6. `manage_validation_run`
7. `manage_git`

The checked-in submission JSON now contains exactly this seven-tool Commander
inventory, five positive tests, and three negative tests. It is a candidate
generated from `b6c864c`, not a submission-readiness grant. The currently loaded
stable `ad170ce` descriptor still describes the Stage 3–6 thin loop, while this
candidate describes Stage 0–6, so an exact live tool scan and human review remain
required after any separately authorized target alignment.

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
required by the seven public tools. The candidate JSON must not be used as proof
that the currently loaded stable service already contains `b6c864c`.

## verification

- Required annotations present on the live Commander surface: 7/7.
- Output schemas present on the live Commander surface: 7/7.
- Positive submission tests: 5.
- Negative submission tests: 3.
- Candidate JSON matches the source Commander annotations: pending branch validation.

Human review and an exact live descriptor comparison are still required before
`mcp_tool_info_ready=true`.
