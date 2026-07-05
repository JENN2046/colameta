# Stable Replacement Receipt: 189bdee

```yaml
receipt_type: stable_replacement_receipt
recorded_at: 2026-07-03T21:53:50+08:00
project: colameta-self-dev
dev_repo: /home/jenn/src/colameta-dev
stable_runtime_dir: /home/jenn/tools/colameta
target_commit: 189bdeed6b9b1d060674032cb1e67f995cc9e282
target_short_commit: 189bdee
authorization: "Jenn authorized stable replacement to exact commit 189bdeed6b9b1d060674032cb1e67f995cc9e282"
state_transition: not_performed
executor_run: not_performed
tunnel_client_restart: not_performed
```

## Summary

Stable service replacement was completed for exact commit
`189bdeed6b9b1d060674032cb1e67f995cc9e282`.

This receipt records replacement evidence only. It does not mark any delivery,
review, gate, route, release, deploy, package publish, or further service
replacement state.

## Source And CI Evidence

```yaml
source_evidence:
  dev_head: 189bdeed6b9b1d060674032cb1e67f995cc9e282
  origin_main: 189bdeed6b9b1d060674032cb1e67f995cc9e282
  local_branch: main
  local_status: "no tracked changes; untracked stable replacement receipts excluded"
  commit_subject: "Add Apps connector smoke packet tool"
  ci:
    workflow: CI
    run_id: 28664648380
    status: completed
    conclusion: success
    url: https://github.com/JENN2046/colameta/actions/runs/28664648380
```

## Replacement Evidence

```yaml
replacement_evidence:
  previous_stable_head: dd1b99fbfb3465ddd237b5a31729c3d9a6dda40a
  new_stable_head: 189bdeed6b9b1d060674032cb1e67f995cc9e282
  package_reinstalled: true
  installed_distribution: colameta 0.1.2
  backup:
    path: /home/jenn/tools/colameta-stable-backups/stable-before-189bdee-20260703T214938+0800.tar.gz
    sha256: 57a3752f0df101b51de64b2bb14778711c72cc8fdff44a10714c01e20bafec87
    size: 21M
```

## Running Service Evidence

```yaml
running_service:
  pid: 4010303
  project_root: /home/jenn/src/colameta-dev
  web:
    url: http://127.0.0.1:8801
    healthz_status: healthy
  mcp:
    url: http://127.0.0.1:8766/mcp
    healthz_status: healthy
    auth_mode: none
  bind_scope: loopback
  command_observed: "/home/jenn/tools/colameta/.venv/bin/python /home/jenn/tools/colameta/.venv/bin/colameta serve /home/jenn/src/colameta-dev --web-host 127.0.0.1 --web-port 8801 --mcp-host 127.0.0.1 --mcp-port 8766 --auth-mode none"
```

## Smoke Evidence

```yaml
smoke:
  web_api_healthz: ok
  mcp_healthz: ok
  mcp_initialize: ok
  mcp_initialized_notification:
    status: 202
    empty_body: true
  mcp_tools_list:
    status: ok
    tool_count: 28
    has_get_apps_connector_smoke_packet: true
  list_registered_projects:
    status: ok
    project_count: 5
    has_colameta_self_dev: true
  web_root_page:
    status: ok
    has_web_commander_service_entry: true
  web_api_v2_status_with_page_headers:
    status: ok
    web_commander_service_ok: true
    note: "default Web status does not carry external tunnel evidence and stays fail-closed for Apps connector closeout"
```

## Runtime And Connector Evidence

```yaml
runtime_provenance:
  project_checkout_head: 189bdeed6b9b1d060674032cb1e67f995cc9e282
  runtime_loaded_code_stale: false
  reload_needed_for_verification: false
  reload_awareness_reason: installed_package_matches_project_checkout
apps_connector_smoke_without_external_evidence:
  status: needs_attention
  stable_replacement_hint: stable_aligned
  replacement_available: false
sanitized_tunnel_evidence:
  tunnel_client_pid: 4034
  admin_port: 8080
  healthz_ok: true
  readyz_ok: true
connector_runtime_health_with_sanitized_evidence:
  overall_status: healthy
  local_service: healthy
  external_connector: healthy
  operator_decision: ready
  evidence_gap_count: 0
apps_connector_smoke_with_sanitized_evidence:
  status: ready
  project_list_tool: list_registered_projects
  connector_closeout_tool: get_connector_runtime_health_status
  stable_replacement_hint: stable_aligned
```

## Remaining Caveats

```yaml
remaining_caveats:
  web_api_v2_status_default_external_evidence: not_embedded
  default_apps_connector_status_without_evidence: needs_attention
  stable_replacement_available_after_replacement: false
  receipt_commit_status: uncommitted_at_record_time
```

The replacement itself is complete. Connector/tunnel closeout is ready when the
approved sanitized tunnel evidence above is supplied to the MCP read tool.
