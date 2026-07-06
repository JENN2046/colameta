# Stable Replacement Receipt: 4ff9168

## Summary

```yaml
date: 2026-07-06
recorded_at_utc: 2026-07-06T05:16:26Z
authorized_target_commit: 4ff91685c07c11a8480bfedd8d54f72348f34ea8
short_commit: 4ff9168
previous_stable_head: 3b4dbbda9ef8689b08e3f37e049798cdf5d97e38
stable_runtime_dir: /home/jenn/tools/colameta
project_root: /home/jenn/src/colameta-dev
service_unit: colameta-stable.service
web_url: http://127.0.0.1:8801
mcp_url: http://127.0.0.1:8766/mcp
auth_mode: none
```

Jenn explicitly authorized stable replacement to `4ff9168` and rerunning live
smoke. The target commit resolved locally to
`4ff91685c07c11a8480bfedd8d54f72348f34ea8`, which matched `origin/main`.

## Preflight

```yaml
dev_head_before_replacement: 4ff91685c07c11a8480bfedd8d54f72348f34ea8
target_is_on_origin_main: true
ci:
  workflow: CI
  run_id: 28769247001
  head_sha: 4ff91685c07c11a8480bfedd8d54f72348f34ea8
  status: completed
  conclusion: success
stable_worktree_clean: true
previous_service_pid: 2278107
```

The development checkout was fast-forwarded locally to `origin/main` before the
replacement so runtime freshness and stable alignment would compare against the
same target head.

## Backup

```yaml
backup_file: /home/jenn/tools/colameta-stable-backups/stable-before-4ff9168-20260706T131400+0800.tar.gz
backup_sha256: b3cabb5da85f4aad7147818da5d5cabf1be7f427b80d2f62b4bcb6086dd2a776
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
stable_checkout: git -C /home/jenn/tools/colameta checkout --detach 4ff91685c07c11a8480bfedd8d54f72348f34ea8
stable_head_after_checkout: 4ff91685c07c11a8480bfedd8d54f72348f34ea8
package_reinstall: /home/jenn/tools/colameta/.venv/bin/python -m pip install --no-deps --force-reinstall /home/jenn/tools/colameta
package_reinstall_result: success
service_restart: systemctl --user restart colameta-stable.service
service_pid_after_restart: 2405733
```

No stable service log was read or written into this receipt.

## Verification

```yaml
systemd_active: true
systemd_substate: running
systemd_pid: 2405733
web_root_http_code: 200
web_root_contains_colameta_marker: true
mcp_healthz: ok
mcp_healthz_auth_mode: none
runtime_project_checkout_head: 4ff91685c07c11a8480bfedd8d54f72348f34ea8
runtime_loaded_code_stale: false
reload_needed_for_verification: false
reload_awareness_reason: installed_package_matches_project_checkout
installed_package_verification: match
stable_replacement_cadence_status: stable_aligned
```

The Web server does not expose `/healthz` on port `8801`; a direct
`/healthz` request returned 404. Runtime observability still reported the Web
endpoint as healthy, and the Web root returned HTTP 200 with a ColaMeta marker.

## Sanitized Tunnel Evidence

```yaml
tunnel_client:
  status: healthy
  reason_code: CLOUDFLARED_SYSTEMD_RUNNING
  evidence_source: "systemctl --user show cloudflared-colameta-mcp-prod.service ActiveState/SubState/MainPID; service active/running; no token/cookie/config/log read"
  last_observed_at: 2026-07-06T05:15:37Z

control_plane:
  status: healthy
  reason_code: CLOUDFLARE_TUNNEL_PUBLIC_PREFLIGHT_READY
  evidence_source: "remote_https_mcp_preflight https://colameta-mcp.skmt617.top ok=true failures=[]; external-oauth protected-resource route reachable"
  last_observed_at: 2026-07-06T05:15:37Z
```

## Apps Connector Live Smoke

`get_apps_connector_smoke_packet` was called with the sanitized evidence above.

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
stable_runtime_head: 4ff91685c07c11a8480bfedd8d54f72348f34ea8
candidate_head: 4ff91685c07c11a8480bfedd8d54f72348f34ea8
```

## Boundary

This replacement did not read tokens, cookies, client secrets, browser login
state, tunnel client config, proxy config, provider auth config, private memory,
raw provider responses, or raw logs. It did not restart tunnel-client and did
not modify DNS, Cloudflare, Auth0, proxy, provider, or tunnel configuration.

This receipt does not write Delivery accepted, ReviewDecision, or GateEvent,
and does not authorize executor runs, releases, package publishing, tag pushes,
or further stable replacement.
