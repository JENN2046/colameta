# Stable Replacement Receipt - 31cf667

Date: 2026-07-02

Status: `completed`

This receipt records the authorized stable service replacement to:

```text
31cf6672aecb568183b50daee1565368b20a663f
```

It is evidence only. It does not create ReviewDecision, GateEvent, Delivery
State accepted, release, deploy, package publish, route transition, executor-run
authority, or further stable replacement authority.

## Authorization

Jenn authorized replacement to the new pushed commit after CI success. The
resolved commit target was:

```text
31cf6672aecb568183b50daee1565368b20a663f
```

## Candidate And CI

```yaml
candidate_commit: 31cf6672aecb568183b50daee1565368b20a663f
candidate_short: 31cf667
origin_main_at_replacement: 31cf6672aecb568183b50daee1565368b20a663f
local_branch: main
local_status_after_push: clean
ci:
  name: CI
  status: completed
  conclusion: success
  run_id: 28534182893
  url: https://github.com/JENN2046/colameta/actions/runs/28534182893
```

## Backup

```yaml
backup_path: /home/jenn/tools/colameta-stable-backups/stable-before-31cf667-20260702T010254+0800.tar.gz
backup_sha256: b49f0048869d8f1e45b2d0b798dbf3d7090238e50ef403e9247a6a0fa36b05e1
previous_stable_head: f22608fa98d8a6f92070cd9b21dcdf4210bb57e3
```

## Replacement Actions

```yaml
stable_runtime_dir: /home/jenn/tools/colameta
stable_head_after_checkout: 31cf6672aecb568183b50daee1565368b20a663f
package_reinstall:
  command: /home/jenn/tools/colameta/.venv/bin/python -m pip install --no-deps --force-reinstall /home/jenn/tools/colameta
  result: success
  installed_distribution: colameta 0.1.2
service_restart:
  previous_pid: 2372850
  previous_pid_terminated_by_exact_term: true
  new_pid: 2412692
  command: "/home/jenn/tools/colameta/.venv/bin/python /home/jenn/tools/colameta/.venv/bin/colameta serve /home/jenn/src/colameta-dev --web-host 127.0.0.1 --web-port 8801 --mcp-host 127.0.0.1 --mcp-port 8766 --auth-mode none"
  detached: true
  start_method: setsid
  pythonpath_override_used: false
```

## Running Service Evidence

```yaml
running_service:
  pid: 2412692
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
  url: http://127.0.0.1:8801
  healthz: ok
  root_page: ok
  csrf_meta_present: true
  web_read_auth_meta_present: true
  read_apis_with_page_headers:
    /api/status: ok
    /api/version-result: ok
    /api/next-plan: ok
    /api/v2/health: ok
mcp:
  url: http://127.0.0.1:8766/mcp
  healthz: ok
  initialize: ok
  tools_list: ok
  tools_count: 25
  required_tools_visible:
    - list_registered_projects
    - get_runtime_version_status
    - get_connector_runtime_health_status
    - run_mcp_workflow
```

## HTTP MCP Notification Fix

This replacement deployed the JSON-RPC notification behavior fix from
`31cf667`.

```yaml
http_mcp_notification_smoke:
  request:
    jsonrpc: "2.0"
    method: notifications/initialized
    id_present: false
  response:
    status: 202
    body_bytes: 0
  previous_stable_behavior:
    status: 200
    body_shape: '{"jsonrpc":"2.0","id":null,"result":{"ok":true}}'
  result: fixed
```

## Runtime Provenance

This block is a replacement-time snapshot captured after the stable service
restart and smoke checks.

```yaml
get_runtime_version_status:
  ok: true
  observed_scope: replacement_time_snapshot
  project_checkout_head: 31cf6672aecb568183b50daee1565368b20a663f
  reload_needed_for_verification: false
```

## Local Codex MCP Follow-Up

```yaml
colameta_local_mcp_config_at_replacement_time:
  name: colameta-local
  transport: stdio
  status: workaround_still_active
http_target_for_closeout: http://127.0.0.1:8766/mcp
next_validation: switch colameta-local back to streamable_http and start a new Codex session
```

## Local Codex HTTP MCP Closeout

This follow-up was completed after the stable replacement smoke and after the
receipt evidence was first recorded.

```yaml
codex_mcp_config_after_closeout:
  name: colameta-local
  enabled: true
  transport: streamable_http
  url: http://127.0.0.1:8766/mcp
  bearer_token_env_var: null
  http_headers: null
  env_http_headers: null
http_mcp_handshake_smoke:
  initialize:
    status: 200
    has_result: true
  notifications_initialized_without_id:
    status: 202
    body_bytes: 0
  tools_list:
    status: 200
    tools_count: 25
    has_list_registered_projects: true
codex_cli_session_startup_smoke:
  command_shape: "timeout 12 codex --no-alt-screen -C /home/jenn/src/colameta-dev"
  exit_reason: timeout_after_startup_observation
  exit_code: 124
  mcp_startup_failed_seen: false
  transport_channel_closed_seen: false
  colameta_local_error_seen: false
  model_prompt_submitted: false
  tool_call_from_model: not_performed
```

The Codex CLI startup smoke verifies that the previous startup failure signature
was not observed after switching `colameta-local` back to HTTP. It does not
claim a model-initiated tool call or Apps connector reauthentication.

## Not Performed

```text
Delivery State accepted
ReviewDecision creation
GateEvent emission
route transition
release
deploy
package publish
executor run
provider/proxy/tunnel config mutation
secret/token/cookie/credential read
provider raw response copy
Apps connector reauth
```

## Notes

At replacement time, the stable runtime directory, stable installed package, dev
checkout, and `origin/main` were all aligned to `31cf667`. The stable service's
HTTP MCP endpoint now follows JSON-RPC notification semantics for no-id
notifications by returning an empty `202` response instead of a JSON-RPC
response with `id: null`.
