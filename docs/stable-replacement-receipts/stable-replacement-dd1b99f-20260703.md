# Stable Replacement Receipt - dd1b99f

Date: 2026-07-03

Status: `completed_with_web_read_auth_boundary`

This receipt records the authorized stable service replacement to:

```text
dd1b99fbfb3465ddd237b5a31729c3d9a6dda40a
```

It is evidence only. It does not create release, deploy, package publish,
executor-run authority, project acceptance, or further stable replacement
authority.

## Authorization

Jenn explicitly authorized:

```text
授权替换稳定服务到 dd1b99fbfb3465ddd237b5a31729c3d9a6dda40a
```

## Candidate And CI

```yaml
candidate_commit: dd1b99fbfb3465ddd237b5a31729c3d9a6dda40a
candidate_short: dd1b99f
origin_main_at_replacement: dd1b99fbfb3465ddd237b5a31729c3d9a6dda40a
local_branch: main
local_status_after_push: clean
ci:
  name: CI
  status: completed
  conclusion: success
  run_id: 28660309677
```

## Backup

```yaml
backup_path: /home/jenn/tools/colameta-stable-backups/stable-before-dd1b99f-20260703T203248+0800.tar.gz
backup_sha256: eb88f4511cbe7e5e2570fa0cf8973894fafc5498c9c3fe6492de98955799612f
previous_stable_head: 2f32509d052ac67789b4985cae0ac9450ad29e71
```

## Replacement Actions

```yaml
stable_runtime_dir: /home/jenn/tools/colameta
stable_head_after_checkout: dd1b99fbfb3465ddd237b5a31729c3d9a6dda40a
package_reinstall:
  command: /home/jenn/tools/colameta/.venv/bin/python -m pip install --no-deps --force-reinstall /home/jenn/tools/colameta
  result: success
  installed_distribution: colameta 0.1.2
service_restart:
  previous_pid: 2985397
  previous_pid_terminated_by_exact_term: true
  new_pid: 3946278
  command: "/home/jenn/tools/colameta/.venv/bin/python /home/jenn/tools/colameta/.venv/bin/colameta serve /home/jenn/src/colameta-dev --web-host 127.0.0.1 --web-port 8801 --mcp-host 127.0.0.1 --mcp-port 8766 --auth-mode none"
  detached: true
  start_method: setsid
  pythonpath_override_used: false
  log_path: /home/jenn/tools/colameta-stable-backups/stable-service-dd1b99f-20260703T203327+0800.log
```

## Running Service Evidence

```yaml
running_service:
  pid: 3946278
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

## Web And MCP Smoke

```yaml
web:
  healthz: ok
  root_page_contains_web_commander_entrypoint: true
  api_v2_status_without_read_auth:
    http_status: 403
    result: not_validated_without_web_read_token
    boundary: web_read_token_not_read_or_extracted
mcp:
  healthz: ok
  initialize: ok
  initialized_notification:
    status: 202
    body_empty: true
  tools_list: ok
  tools_count: 27
  required_tools_visible:
    - list_registered_projects
    - get_runtime_version_status
    - get_connector_runtime_health_status
    - get_commander_app_manifest
  list_registered_projects:
    ok: true
    project_count: 5
```

## Runtime And Connector Evidence

```yaml
get_runtime_version_status:
  ok: true
  project_checkout_head: dd1b99fbfb3465ddd237b5a31729c3d9a6dda40a
  loaded_runtime_head: null
  runtime_loaded_code_stale: false
  reload_needed_for_verification: false
  reload_awareness_reason: installed_package_matches_project_checkout
get_connector_runtime_health_status_with_sanitized_tunnel_evidence:
  overall_status: healthy
  local_service: healthy
  external_connector: healthy
  operator_closeout: connector_closeout_ready
  decision: ready
  evidence_gap_count: 0
colameta_status_with_tunnel_evidence:
  pid: 3946278
  web: healthy
  mcp: healthy
  external_connector: healthy
  closeout: connector_closeout_ready
```

## Commander Readiness

```yaml
get_commander_app_manifest_without_tunnel_evidence:
  ok: true
  readiness_status: needs_attention
  status_line: "needs_attention | runtime_current"
  summary: "Local runtime and Web/MCP are healthy, but external connector/tunnel evidence is still unverified."
  primary_blocker: CONNECTOR_HEALTH_UNVERIFIED
explanation:
  - get_commander_app_manifest is read-only and does not accept tunnel evidence.
  - get_connector_runtime_health_status closes out after sanitized tunnel evidence is supplied.
  - web /api/v2/status.service_readiness_summary was not read because read-auth token extraction was outside the active boundary.
```
