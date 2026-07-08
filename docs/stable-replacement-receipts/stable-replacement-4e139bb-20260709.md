# Stable Replacement Receipt: 4e139bb

## Summary

```yaml
date: 2026-07-09
recorded_at_utc: 2026-07-08T20:03:57Z
authorized_target_commit: 4e139bbbe7126c571103819cfb531f12c2b40d1f
short_commit: 4e139bb
previous_stable_head: 3bec499c2633f226b7127d1ca9713bf82e3ecf35
stable_runtime_dir: /home/jenn/tools/colameta
project_root: /home/jenn/src/colameta-dev
service_unit: colameta-stable.service
stable_web_url: http://127.0.0.1:8801
stable_mcp_url: http://127.0.0.1:8766/mcp
stable_auth_mode: none
remote_public_base_url: https://colameta-mcp.skmt617.top
```

Jenn explicitly authorized stable service replacement to `4e139bb`. The target
resolved locally to `4e139bbbe7126c571103819cfb531f12c2b40d1f`, which is
`origin/main` and includes PR #12.

## Preflight

```yaml
target_in_origin_main: true
main_ci:
  workflow: CI
  run_id: 28960356126
  head_sha: 4e139bbbe7126c571103819cfb531f12c2b40d1f
  status: completed
  conclusion: success
previous_service_pid: 3178764
previous_service_state: active/running
stable_worktree_tracked_state_before_replacement:
  deleted:
    - AGENTS.md
stable_worktree_untracked_state_before_replacement:
  - AGENTS - 副本.md:Zone.Identifier
  - AGENTS.md:Zone.Identifier
```

The stable runtime worktree was backed up before mutation. The tracked
`AGENTS.md` deletion was restored from the authorized target commit so the
stable runtime checkout could align with `4e139bb`. The untracked
Zone.Identifier files were left in place and were not committed or deleted.

## Backup

```yaml
backup_file: /home/jenn/tools/colameta-stable-backups/stable-before-4e139bb-20260709T040204+0800.tar.gz
backup_sha256: 5ff6cc1ba8934aab284e4a3fc424b380d5835548b1d6ad685ccc167b10c18396
backup_size: 15M
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
stable_fetch: git -C /home/jenn/tools/colameta fetch /home/jenn/src/colameta-dev 4e139bbbe7126c571103819cfb531f12c2b40d1f
stable_checkout: git -C /home/jenn/tools/colameta checkout --detach 4e139bbbe7126c571103819cfb531f12c2b40d1f
restore_tracked_file: git -C /home/jenn/tools/colameta restore --source=HEAD -- AGENTS.md
stable_head_after_checkout: 4e139bbbe7126c571103819cfb531f12c2b40d1f
package_reinstall: /home/jenn/tools/colameta/.venv/bin/python -m pip install --no-deps --force-reinstall /home/jenn/tools/colameta
package_reinstall_result: success
service_restart: systemctl --user restart colameta-stable.service
service_pid_after_restart: 1673119
service_started_at: 2026-07-09T04:02:50+0800
```

No stable service log was read or recorded in this receipt.

## Local Stable Smoke

```yaml
systemd_active: true
systemd_substate: running
systemd_pid: 1673119
web_root_http_code: 200
web_healthz:
  ok: true
  service: colameta-web-console
  runtime_project_checkout_head: 4e139bbbe7126c571103819cfb531f12c2b40d1f
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
  runtime_project_checkout_head: 4e139bbbe7126c571103819cfb531f12c2b40d1f
  runtime_loaded_code_stale: false
  reload_needed_for_verification: false
  reload_awareness_reason: installed_package_matches_project_checkout
  installed_package_matches_project_checkout: true
  installed_package_verification_status: match
  installed_package_project_source_clean: true
  installed_package_source_cleanliness_status: clean
stable_cli_status:
  ok: true
  service_state: running
  service_pid: 1673119
  web_state: healthy
  mcp_state: healthy
  runtime_project_checkout_head: 4e139bbbe7126c571103819cfb531f12c2b40d1f
  runtime_loaded_code_stale: false
  reload_needed_for_verification: false
  reload_awareness_reason: installed_package_matches_project_checkout
  installed_package_verification: match
  installed_distribution_file_count: 186
  installed_filesystem_file_count: 186
  installed_runtime_file_count: 186
  extra_installed_file_count: 0
  stable_runtime_head: 4e139bbbe7126c571103819cfb531f12c2b40d1f
```

## Production Ops Check

`ops-check --no-network` was run with
`--expected-head 4e139bbbe7126c571103819cfb531f12c2b40d1f`.

```yaml
overall_status: needs_attention
stable_runtime: ready
stable_service: ready
local_stable_health: ready
backup_inventory: ready
rollback_rehearsal: ready
secret_redaction: ready
remote_https_mcp_preflight: needs_attention
remote_https_mcp_preflight_reason: REMOTE_PREFLIGHT_NOT_RUN
connector_smoke: needs_attention
connector_smoke_reason: CONNECTOR_SMOKE_MISSING
origin_main: needs_attention
origin_main_reason: ORIGIN_MAIN_NOT_ALIGNED
```

The `origin_main` attention item came from running the check while the dev
worktree was still on the already-merged PR branch head `761d001`; `origin/main`
itself was `4e139bb`.

## Live Remote HTTPS MCP Preflight

```yaml
command: /home/jenn/tools/colameta/.venv/bin/python /home/jenn/tools/colameta/scripts/remote_https_mcp_preflight.py https://colameta-mcp.skmt617.top
ok: false
failure: remote MCP public_base_url must not use localhost, loopback, private, link-local, multicast, local-only DNS, or otherwise non-public/non-unicast hosts.
local_resolution_observed:
  host: colameta-mcp.skmt617.top
  address: 198.18.0.218
  is_global: false
  is_private: true
  is_loopback: false
  is_link_local: false
  is_multicast: false
```

The replacement itself succeeded locally. The live remote preflight did not
prove the public connector ready because the current local resolver returned a
RFC 2544 benchmarking/private-like address. No DNS, tunnel, proxy, Cloudflare,
Auth0, or provider configuration was read or modified.

## Boundary

This replacement and receipt did not read or record tokens, cookies, client
secrets, browser login state, tunnel-client config, proxy config, provider auth
config, private memory, raw provider responses, or raw logs. It did not restart
tunnel-client and did not modify DNS, Cloudflare, Auth0, proxy, provider, or
tunnel configuration.

This receipt does not write Delivery accepted, ReviewDecision, or GateEvent,
and does not authorize executor runs, releases, package publishing, tag pushes,
rollback, restore, or further stable replacement.
