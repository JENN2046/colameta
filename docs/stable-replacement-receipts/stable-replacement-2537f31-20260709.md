# Stable Replacement Receipt: 2537f31

## Summary

```yaml
date: 2026-07-09
recorded_at_utc: 2026-07-08T21:44:10Z
authorized_target_commit: 2537f31e178e5a61059cca2505bb5d4f01e498ec
short_commit: 2537f31
previous_stable_head: 4e139bbbe7126c571103819cfb531f12c2b40d1f
stable_runtime_dir: /home/jenn/tools/colameta
project_root: /home/jenn/src/colameta-dev
service_unit: colameta-stable.service
stable_web_url: http://127.0.0.1:8801
stable_mcp_url: http://127.0.0.1:8766/mcp
stable_auth_mode: none
remote_public_base_url: https://colameta-mcp.skmt617.top
```

Jenn explicitly authorized stable runtime promotion from `4e139bb` to the
current project head `2537f31`. The target resolved locally to
`2537f31e178e5a61059cca2505bb5d4f01e498ec`, matching `origin/main`.

## Preflight

```yaml
target_head: 2537f31e178e5a61059cca2505bb5d4f01e498ec
target_matches_origin_main: true
previous_stable_head: 4e139bbbe7126c571103819cfb531f12c2b40d1f
previous_stable_service:
  active_state: active
  sub_state: running
  main_pid: 1673119
stable_worktree_untracked_state_before_replacement:
  - AGENTS - 副本.md:Zone.Identifier
  - AGENTS.md:Zone.Identifier
```

The untracked Zone.Identifier files were left in place and were not committed
or deleted.

## Backup

```yaml
backup_file: /home/jenn/tools/colameta-stable-backups/stable-before-2537f31-20260709T054310+0800.tar.gz
backup_sha256: a72bed7d276f60d6ec2ffa2432ad41d4c62ab6d400a9937d9565383337b30c58
backup_size: 24M
backup_source: /home/jenn/tools/colameta
```

The backup archive was created before mutating the stable checkout.

## Replacement

```yaml
stable_fetch: git -C /home/jenn/tools/colameta fetch origin main
stable_checkout: git -C /home/jenn/tools/colameta checkout --detach 2537f31e178e5a61059cca2505bb5d4f01e498ec
stable_head_after_checkout: 2537f31e178e5a61059cca2505bb5d4f01e498ec
package_reinstall: /home/jenn/tools/colameta/.venv/bin/python -m pip install --no-deps --force-reinstall /home/jenn/tools/colameta
package_reinstall_result: success
wheel_sha256: fc0bb2041fe50b886bcbe6aa50b7aaa3482e4e5523a66102262b6f09b7e04283
service_restart: systemctl --user restart colameta-stable.service
service_pid_after_restart: 2116930
service_started_at: 2026-07-09T05:43:56+0800
```

No stable service log file was read or recorded in this receipt.

## Local Stable Smoke

```yaml
systemd_active: true
systemd_substate: running
systemd_pid: 2116930
web_healthz:
  ok: true
  service: colameta-web-console
  runtime_project_checkout_head: 2537f31e178e5a61059cca2505bb5d4f01e498ec
  runtime_loaded_code_stale: false
  reload_needed_for_verification: false
  reload_awareness_reason: installed_package_matches_project_checkout
  installed_package_matches_project_checkout: true
  installed_package_verification_status: match
  installed_package_project_source_clean: true
  installed_package_source_cleanliness_status: clean
mcp_healthz:
  ok: true
  service: colameta-mcp
  auth_mode: none
  runtime_project_checkout_head: 2537f31e178e5a61059cca2505bb5d4f01e498ec
  runtime_loaded_code_stale: false
  reload_needed_for_verification: false
  reload_awareness_reason: installed_package_matches_project_checkout
  installed_package_matches_project_checkout: true
  installed_package_verification_status: match
  installed_package_project_source_clean: true
  installed_package_source_cleanliness_status: clean
```

## Production Ops Check

`ops-check` was run with
`--expected-head 2537f31e178e5a61059cca2505bb5d4f01e498ec` and fresh
connector smoke evidence.

```yaml
overall_status: ready
ops_check_ready: true
connector_smoke_ready: true
beta_gate_ready: true
stable_runtime: ready
stable_service: ready
local_stable_health: ready
remote_https_mcp_preflight: ready
cloudflared_service: ready
backup_inventory: ready
rollback_rehearsal: ready
secret_redaction: ready
blocker_codes: []
needs_attention_codes: []
```

## Live Remote HTTPS MCP Preflight

```yaml
command: /home/jenn/tools/colameta/.venv/bin/python /home/jenn/tools/colameta/scripts/remote_https_mcp_preflight.py https://colameta-mcp.skmt617.top --expected-head 2537f31e178e5a61059cca2505bb5d4f01e498ec
ok: true
network_check: run
failures: []
responses:
  healthz: 200
  mcp: 200
  protected_resource_metadata: 200
  authorization_server_metadata: 404
healthz_runtime:
  loaded_runtime_head: 2537f31e178e5a61059cca2505bb5d4f01e498ec
  runtime_project_checkout_head: 2537f31e178e5a61059cca2505bb5d4f01e498ec
  runtime_loaded_code_stale: false
  reload_needed_for_verification: false
  installed_package_verification_status: match
```

The authorization-server metadata URL on the MCP service itself returned 404,
which is expected for this external OAuth mode because the protected-resource
metadata delegates to the external Auth0 issuer.

## ChatGPT Apps Connector Smoke

```yaml
tool_surface: ChatGPT ColaMeta MCP
tool: get_apps_connector_smoke_packet
ok: true
apps_connector_closeout:
  status: ready
connector_closeout_check:
  current_operator_closeout: connector_closeout_ready
  current_decision: ready
  current_evidence_gap_count: 0
connector_runtime_health:
  overall_status: healthy
  reason_codes:
    - RUNTIME_LOADED_CODE_CURRENT
    - LOCAL_SERVICE_HEALTHY
    - WEB_ENDPOINT_DISABLED
    - MCP_ENDPOINT_HEALTHY
    - CLOUDFLARED_REGISTERED_PUBLIC_EDGE_CONNECTIONS
    - REMOTE_PREFLIGHT_READY
stable_replacement_hint:
  status: stable_aligned
  stable_runtime_head: 2537f31e178e5a61059cca2505bb5d4f01e498ec
```

## Decision

```yaml
stable_replacement_result: ready
stable_aligned_to_origin_main: true
beta_gate_ready: true
external_connector_ready: true
rollback_backup_available: true
```

## Boundary

This replacement and receipt did not read or record tokens, cookies, client
secrets, browser login state, tunnel-client config, proxy config, provider auth
config, private memory, raw provider responses, or raw logs. It did not modify
Cloudflare, Auth0, DNS, proxy, provider, or tunnel configuration.

This receipt does not write Delivery accepted, ReviewDecision, or GateEvent,
and does not authorize executor runs, releases, package publishing, tag pushes,
rollback, restore, or further stable replacement.
