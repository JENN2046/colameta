# MCP Tool Information Evidence

## tool_inventory

- Project: `colameta-self-dev`
- MCP exposure profile: `normal`
- Visible tool count: 82
- Submission inventory: `chatgpt-app-submission.json`
- Submission inventory SHA-256:
  `35879d78190404893ad9fb6c2796e2a23e49ef4b39222492b8a7b09080cb643d`

The submission JSON contains every normal-profile tool in runtime order. Each
entry records the three mandatory ChatGPT Apps hints and one-sentence
justifications. The inventory covers project discovery, Commander/readiness,
release evidence, runtime and connector health, stage-parallel workflows, Git,
plans, docs, files, executor and validation workflows, and Work Item lifecycle
commands.

## scope_map

- `mcp:read`: strictly reads or computes project-scoped evidence.
- `mcp:preview`: creates a bounded preview but does not apply the proposed action.
- `mcp:commit`: performs an explicit, permission-scoped local mutation or run.
- `mcp:plan`: reserved plan authority; denied by the current remote public policy.

Action-dependent tools select their scope from an explicit action or phase. The
normal-profile annotation audit classified:

- strictly read-only tools as `readOnlyHint=true`;
- local write, overwrite, delete, or executor tools as `readOnlyHint=false`;
- `manage_git` as `openWorldHint=true` because it can interact with Git remotes;
- overwrite/delete/restore/revert tools as `destructiveHint=true`;
- fixed validation execution as non-read-only but non-destructive.

## side_effects

The generated submission file does not execute tools. Mutating tools retain their
existing preview/apply, confirmation, scope, and project-routing guards. The
remote public service policy continues to deny commit and plan scopes unless its
service configuration explicitly permits them.

## safety_boundaries

Source inspection found no normal-profile input fields that solicit passwords,
API keys, OAuth secrets, MFA codes, payment data, government identifiers,
biometrics, or health data. All 82 tools declare an `outputSchema`.

Commander widget CSP uses empty `connectDomains`, `resourceDomains`,
`connect_domains`, and `resource_domains` lists because the widget does not load
external resources. No token, cookie, private browser state, tunnel credential,
provider secret, raw log, request ID, stack trace, or local filesystem path is
included in `chatgpt-app-submission.json`.

## verification

- Required annotations present: 82/82.
- Output schemas present: 82/82.
- Positive submission tests: 5.
- Negative submission tests: 3.
- Full project tests: 1467 passed, 2 skipped, 55 subtests passed.

Human review is still required before `mcp_tool_info_ready=true`.
