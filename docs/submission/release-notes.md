# Initial Plugin Submission Release Notes

ColaMeta is being prepared as an MCP-backed ChatGPT app inside a plugin. It
helps authorized operators discover registered AI engineering projects, inspect
runtime and connector health, open a project-scoped Commander, prepare a
read-only Stage 0–6 governed-loop preview, review bounded validation, and inspect
Git readiness through permission-scoped tools.

This submission candidate provides:

- a production HTTPS MCP endpoint using external OAuth;
- an exact seven-tool public Commander profile;
- explicit `readOnlyHint`, `openWorldHint`, and `destructiveHint` annotations;
- an `outputSchema` for every public tool;
- five positive and three negative reviewer test cases;
- a widget with an empty external-resource CSP; and
- privacy, security, support, and terms documentation.

Runtime verification baseline:

- deployed MCP source target:
  `b6c864c4319ceaa0afc56f4bc2b2ae96998c5f29`;
- MCP endpoint: `https://colameta-mcp.skmt617.top/mcp`;
- submission inventory SHA-256:
  `05877797d7d4115a909f64d024c2b933d089fed27b7a0791fec3412ff3e41296`;
- public preflight: passed with zero failures;
- connector smoke: healthy, ready, and zero evidence gaps.

The public Commander tools are `list_registered_projects`,
`get_apps_connector_smoke_packet`, `render_commander_app`,
`analyze_project_state`, `run_mcp_workflow`, `manage_validation_run`, and
`manage_git`. The separate loopback advanced profile is not part of this
submission inventory.

The final operator must scan the live endpoint in the plugin submission portal,
verify the imported metadata, rerun the five positive cases in ChatGPT web and
mobile, and complete the organization, permissions, reviewer-account, country,
and confirmation checks. This file does not submit or publish the plugin.
