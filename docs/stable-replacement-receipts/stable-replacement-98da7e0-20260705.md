# Stable Replacement Receipt: 98da7e0

## Summary

```yaml
date: 2026-07-05
authorized_target_commit: 98da7e0bc74b394e6c48561c24b6ab464e55c764
short_commit: 98da7e0
previous_stable_head: 611446d5b633e423eb2dcc62d944a264ec7f5775
stable_runtime_dir: /home/jenn/tools/colameta
project_root: /home/jenn/src/colameta-dev
service_unit: colameta-stable.service
web_url: http://127.0.0.1:8801
mcp_url: http://127.0.0.1:8766/mcp
auth_mode: none
```

Jenn authorized replacing stable to `98da7e0`. The short SHA resolved locally to
`98da7e0bc74b394e6c48561c24b6ab464e55c764`, which matched dev HEAD and
`origin/main`.

## Preflight

```yaml
dev_head: 98da7e0bc74b394e6c48561c24b6ab464e55c764
target_is_on_origin_main: true
ci:
  workflow: CI
  run_id: 28736278152
  status: completed
  conclusion: success
stable_worktree_clean: true
previous_service_pid: 1815304
```

## Backup

```yaml
backup_file: /home/jenn/tools/colameta-stable-backups/stable-before-98da7e0-20260705T173518+0800.tar.gz
backup_sha256: 4c65e37d058663c447cd0524a746c68426fad7c873c971231ebef7e324bb3464
backup_size: 13M
backup_excludes:
  - colameta/.venv
```

## Replacement

```yaml
stable_fetch: git -C /home/jenn/tools/colameta fetch origin
stable_checkout: git -C /home/jenn/tools/colameta checkout 98da7e0bc74b394e6c48561c24b6ab464e55c764
stable_head_after_checkout: 98da7e0bc74b394e6c48561c24b6ab464e55c764
package_reinstall: /home/jenn/tools/colameta/.venv/bin/python -m pip install --no-deps --force-reinstall /home/jenn/tools/colameta
package_reinstall_result: success
service_log: /home/jenn/tools/colameta-stable-backups/stable-service-98da7e0-20260705T173518+0800.log
service_pid_after_start: 1846865
```

The stable service was restarted as a transient user systemd unit with:

```text
/home/jenn/tools/colameta/.venv/bin/python /home/jenn/tools/colameta/.venv/bin/colameta serve /home/jenn/src/colameta-dev --web-host 127.0.0.1 --web-port 8801 --mcp-host 127.0.0.1 --mcp-port 8766 --auth-mode none
```

## Verification

```yaml
systemd_active: true
systemd_pid: 1846865
web_healthz: ok
mcp_healthz: ok
mcp_initialize: ok
mcp_initialized_notification: 202_empty_body
mcp_tools_list_count: 44
has_get_agent_operator_flow_packet: true
has_render_commander_app: true
has_get_apps_connector_smoke_packet: true
runtime_project_checkout_head: 98da7e0bc74b394e6c48561c24b6ab464e55c764
runtime_loaded_code_stale: false
reload_needed_for_verification: false
reload_awareness_reason: installed_package_matches_project_checkout
web_page_contains_web_commander_service_entry: true
commander_manifest_profile_id_support:
  requested_profile_id: reviewer_agent
  manifest_profile_id: reviewer_agent
  flow_profile_id: reviewer_agent
  persona_safe_next_tool: manage_workflow_run
stable_cli_status:
  connector_overall: healthy
  operator_closeout: connector_closeout_ready
  stable_replacement_cadence_status: stable_aligned
```

Sanitized tunnel evidence was collected with:

```text
/home/jenn/tools/tunnel-client/bin/tunnel-client health --port 8080 --pid 4034 --json
```

The evidence showed `/healthz` live and `/readyz` ready. Only sanitized evidence
fields were passed back into ColaMeta.

```yaml
connector_runtime_health_with_sanitized_tunnel_evidence:
  overall_status: healthy
  local_service: healthy
  external_connector: healthy
  operator_closeout: connector_closeout_ready
  decision: ready
  evidence_gap_count: 0
apps_connector_tool_surface:
  list_registered_projects: ok
  project_count: 5
  colameta_self_dev_available: true
  get_connector_runtime_health_status: ok
  connector_closeout: connector_closeout_ready
apps_smoke_with_sanitized_tunnel_evidence:
  status: ready
  connector_closeout: connector_closeout_ready
  stable_hint: stable_aligned
```

## Boundary

This replacement did not read tokens, cookies, browser login state, tunnel
client config, raw tunnel logs, provider auth config, private memory, or raw
provider responses. It did not restart tunnel-client and did not modify
proxy/provider/auth configuration.

This receipt does not write Delivery accepted, ReviewDecision, or GateEvent, and
does not authorize executor runs, commits, pushes, releases, or further stable
replacement.
