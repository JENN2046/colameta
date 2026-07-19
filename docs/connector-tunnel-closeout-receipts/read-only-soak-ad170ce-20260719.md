# Read-Only Private Beta Soak: ad170ce

## Scope

```yaml
date: 2026-07-19
stable_loaded_code_target: ad170ced2bd576215bcda0ea1078dd6d6f41cf9f
project_name: colameta-self-dev
soak_kind: bounded_initial_read_only_sampling
sample_count: 3
sample_interval_seconds: 15
final_confirmation_at_utc: 2026-07-19T06:35:37Z
stable_replacement_performed: false
service_restart_performed: false
external_configuration_mutated: false
```

This is an initial bounded soak, not a 72-hour soak or a submission-readiness
claim. It used health surfaces, the seven-tool MCP inventory, project listing,
and the read-only connector smoke packet. It did not read credentials, tokens,
cookies, browser state, private configuration, raw logs, or ignored runtime
artifacts.

## Repeated Samples

Three samples separated by approximately 15 seconds returned the same result:

```yaml
stable_healthz:
  ok: true
  runtime_project_checkout_head: ad170ced2bd576215bcda0ea1078dd6d6f41cf9f
  runtime_loaded_code_stale: false
  installed_package_matches_project_checkout: true
remote_oauth_healthz:
  ok: true
  runtime_project_checkout_head: ad170ced2bd576215bcda0ea1078dd6d6f41cf9f
  runtime_loaded_code_stale: false
  installed_package_matches_project_checkout: true
service_units_at_initial_samples:
  colameta-stable.service: active/running
  colameta-mcp-remote.service: active/running
  colameta-tunnel-client.service: active/running
  restart_count: 0
tunnel_admin:
  healthz: live
  readyz: ready
registered_project:
  project_name: colameta-self-dev
  available: true
  runner_managed: true
connector_smoke:
  ok: true
  read_only: true
  side_effects: false
  apps_status: ready
  overall_status: healthy
  operator_status: connector_closeout_ready
  operator_decision: ready
  evidence_gap_count: 0
```

The final confirmation again returned healthy `8766` and `8767` health
responses, `live` and `ready` tunnel-admin responses, a successful
`list_registered_projects` call, and a successful
`get_apps_connector_smoke_packet` call using only sanitized component status.
The final shell could not reconnect to the user-session D-Bus, so that last
sample used process presence plus the same health surfaces instead of claiming
a fourth systemd-state sample.

## Seven-Tool Surface

The loaded stable service exposed exactly:

1. `list_registered_projects`
2. `get_apps_connector_smoke_packet`
3. `render_commander_app`
4. `analyze_project_state`
5. `run_mcp_workflow`
6. `manage_validation_run`
7. `manage_git`

All seven loaded descriptors included `readOnlyHint`, `openWorldHint`, and
`destructiveHint`, and all seven included an `outputSchema`.

## Provenance Boundary

The stable health endpoint proves the loaded service code is `ad170ce`. The
project-scoped smoke packet separately reports the current registered project
checkout, which is `b6c864c4319ceaa0afc56f4bc2b2ae96998c5f29`; that value is
project-source provenance, not proof that stable loaded `b6c864c`.

The stable `run_mcp_workflow` descriptor still describes the Stage 3–6 thin
loop, while the `b6c864c` source candidate describes Stage 0–6. Consequently a
submission artifact generated from `b6c864c` must not be represented as an
exact descriptor snapshot of the currently loaded stable service.

## Decision

```yaml
bounded_soak_result: pass
loaded_stable_remains_ad170ce: true
seven_tool_surface_healthy: true
connector_smoke_healthy: true
long_duration_soak_complete: false
submission_ready_claim: false
b6c864c_stable_replacement_authorized: false
```

Advancing `b6c864c` into stable remains outside this receipt and requires a new
explicit authorization naming that exact target.
