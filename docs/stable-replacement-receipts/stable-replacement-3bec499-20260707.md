# Stable Replacement Receipt: 3bec499

## Summary

```yaml
date: 2026-07-07
recorded_at_utc: 2026-07-06T17:43:50Z
authorized_target_commit: 3bec499c2633f226b7127d1ca9713bf82e3ecf35
short_commit: 3bec499
previous_stable_head: 4ff91685c07c11a8480bfedd8d54f72348f34ea8
stable_runtime_dir: /home/jenn/tools/colameta
project_root: /home/jenn/src/colameta-dev
service_unit: colameta-stable.service
stable_web_url: http://127.0.0.1:8801
stable_mcp_url: http://127.0.0.1:8766/mcp
stable_auth_mode: none
remote_public_base_url: https://colameta-mcp.skmt617.top
remote_connector_url: https://colameta-mcp.skmt617.top/mcp
remote_auth_mode: external-oauth
```

Jenn explicitly authorized stable runtime promotion to current `main` and a
fresh live remote HTTPS MCP preflight plus ChatGPT connector smoke. The target
commit resolved locally to `3bec499c2633f226b7127d1ca9713bf82e3ecf35`, matching
the local `main` checkout.

## Preflight

```yaml
dev_branch: main
dev_head_before_replacement: 3bec499c2633f226b7127d1ca9713bf82e3ecf35
origin_main_aligned: true
ci:
  workflow: CI
  run_id: 28811075909
  head_sha: 3bec499c2633f226b7127d1ca9713bf82e3ecf35
  status: completed
  conclusion: success
stable_worktree_clean: true
previous_service_pid: 2405733
```

## Backup

```yaml
backup_file: /home/jenn/tools/colameta-stable-backups/stable-before-3bec499-20260707T014244+0800.tar.gz
backup_sha256: 3cba920dc04c12463dbac44014348691f198cc01bef17bc0ec60d079d7e24ce4
backup_size: 14M
backup_excludes:
  - colameta/.venv
  - colameta/.env
  - colameta/.env.*
  - colameta/.colameta/runtime
  - colameta/.colameta/logs
  - colameta/.colameta/local
  - colameta/.colameta/tmp
  - colameta/state-private
```

## Replacement

```yaml
stable_fetch: git -C /home/jenn/tools/colameta fetch origin
stable_checkout: git -C /home/jenn/tools/colameta checkout --detach 3bec499c2633f226b7127d1ca9713bf82e3ecf35
stable_head_after_checkout: 3bec499c2633f226b7127d1ca9713bf82e3ecf35
package_reinstall: /home/jenn/tools/colameta/.venv/bin/python -m pip install --no-deps --force-reinstall /home/jenn/tools/colameta
package_reinstall_result: success
service_restart: systemctl --user restart colameta-stable.service
service_pid_after_restart: 3178764
```

No stable service log was read or written into this receipt.

## Local Stable Smoke

```yaml
systemd_active: true
systemd_substate: running
systemd_pid: 3178764
web_root_http_code: 200
mcp_healthz: ok
mcp_healthz_auth_mode: none
mcp_tools_list: ok
stable_cli_status:
  ok: true
  service_state: running
  service_pid: 3178764
  web_state: healthy
  mcp_state: healthy
  runtime_project_checkout_head: 3bec499c2633f226b7127d1ca9713bf82e3ecf35
  runtime_loaded_code_stale: false
  reload_needed_for_verification: false
  reload_awareness_reason: installed_package_matches_project_checkout
  installed_package_verification: match
  stable_replacement_cadence_status: stable_aligned
```

## Live Remote HTTPS MCP Preflight

```yaml
command: .venv/bin/python scripts/remote_https_mcp_preflight.py https://colameta-mcp.skmt617.top
network_check: run
ok: true
failures: []
healthz_status: 200
mcp_status: 200
protected_resource_metadata_status: 200
authorization_server_metadata_status: 404
authorization_server_metadata_expected_reason: EXTERNAL_AUTH_SERVER
connector_url: https://colameta-mcp.skmt617.top/mcp
protected_resource_metadata_url: https://colameta-mcp.skmt617.top/.well-known/oauth-protected-resource
```

The remote service remains in `external-oauth` resource-server mode. The
preflight output intentionally reported status and JSON field names only.

## Sanitized Tunnel Evidence

```yaml
tunnel_client:
  status: healthy
  reason_code: CLOUDFLARED_SYSTEMD_RUNNING
  evidence_source: "systemctl --user show cloudflared-colameta-mcp-prod.service ActiveState/SubState/MainPID; service active/running; no token/cookie/config/log read"
  last_observed_at: 2026-07-06T17:43:50Z

control_plane:
  status: healthy
  reason_code: CLOUDFLARE_TUNNEL_PUBLIC_PREFLIGHT_READY
  evidence_source: "remote_https_mcp_preflight https://colameta-mcp.skmt617.top ok=true failures=[]; external-oauth protected-resource route reachable"
  last_observed_at: 2026-07-06T17:43:50Z
```

## ChatGPT Connector Smoke

`list_registered_projects` was called successfully through the Apps connector
surface and returned 5 available managed projects including `colameta-self-dev`.

`get_apps_connector_smoke_packet` was then called for `colameta-self-dev` with
the sanitized evidence above.

```yaml
apps_connector_closeout.status: ready
connector_runtime_health.overall_status: healthy
operator_closeout.status: connector_closeout_ready
operator_closeout.decision: ready
evidence_gap_count: 0
external_connector.status: healthy
runtime.status: healthy
local_service.status: healthy
web.status: healthy
mcp.status: healthy
stable_replacement_hint.status: stable_aligned
candidate_head: 3bec499c2633f226b7127d1ca9713bf82e3ecf35
stable_runtime_head: 3bec499c2633f226b7127d1ca9713bf82e3ecf35
```

## Boundary

This replacement and smoke pass did not read or record tokens, cookies, client
secrets, browser login state, tunnel client config, proxy config, provider auth
config, private memory, raw provider responses, or raw logs. It did not restart
tunnel-client and did not modify DNS, Cloudflare, Auth0, proxy, provider, or
tunnel configuration.

This receipt does not write Delivery accepted, ReviewDecision, or GateEvent,
and does not authorize executor runs, releases, package publishing, tag pushes,
or further stable replacement.
