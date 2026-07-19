# Stable Replacement Receipt: ad170ce

## Summary

```yaml
date: 2026-07-19
recorded_at_utc: 2026-07-19T05:36:31Z
authorized_target_commit: ad170ced2bd576215bcda0ea1078dd6d6f41cf9f
short_commit: ad170ce
previous_stable_head: 7b8f5dbe2f7505fe5706d878615356960cc0cb99
stable_runtime_dir: /home/jenn/tools/colameta
project_root: /home/jenn/src/colameta-dev
service_units:
  - colameta-stable.service
  - colameta-mcp-remote.service
stable_mcp_url: http://127.0.0.1:8766/mcp
remote_oauth_health_url: http://127.0.0.1:8767/healthz
```

Jenn explicitly authorized replacing the stable runtime with the current
Commander exposure-profile fix and restarting the Private Beta services. The
target is the local commit `ad170ce`, which adds the read-only
`get_apps_connector_smoke_packet` tool to the exact Commander allowlist while
retaining fail-closed denial for hidden tools.

## Preflight

```yaml
target_worktree_tracked_clean: true
stable_worktree_tracked_clean: true
previous_stable_head: 7b8f5dbe2f7505fe5706d878615356960cc0cb99
previous_services:
  colameta-stable.service: active/running
  colameta-mcp-remote.service: active/running
```

Only tracked state was inspected for the stable checkout. No token, cookie,
credential, private runtime state, provider response, configuration, or raw log
was read.

## Validation Before Replacement

```yaml
focused_mcp_tests:
  passed: 25
  failed: 0
compileall: passed
git_diff_check: passed
full_pytest:
  passed: 1492
  skipped: 2
  failed: 1
  failed_node: tests/test_work_item_r3_closeout_runner.py::test_frozen_toolchain_record_and_environment_root_are_verified
  classification: local_frozen_toolchain_environment_drift
  failure_code: CLOSEOUT_TOOLCHAIN_PREIMPORT_BYTECODE
```

The full-suite failure was isolated from the MCP behavior change: it detected
pre-import bytecode in the existing exact-toolchain environment. Commander
allowlist, external OAuth metadata, ChatGPT submission annotations, Private
Beta systemd contracts, Apps connector smoke behavior, compile, and whitespace
checks passed.

## Backup

```yaml
backup_file: /home/jenn/tools/colameta-stable-backups/stable-before-ad170ce-20260719T053329Z.tar.gz
backup_sha256: 460714c0720abc692ba719dbdc57907dbee87d3261f5616ea9de8246870616b2
backup_size_bytes: 4141549
backup_scope: previous stable HEAD tracked source only
archive_validation: gzip_test_passed
```

The backup was created before stable mutation. Because it was generated from
the previous Git tree, it excludes `.venv`, untracked files, secrets, ignored
runtime state, and other private local state by construction.

## Replacement

```yaml
stable_fetch: git fetch from the authorized local project commit
stable_checkout: detached ad170ced2bd576215bcda0ea1078dd6d6f41cf9f
stable_head_after_checkout: ad170ced2bd576215bcda0ea1078dd6d6f41cf9f
package_reinstall: local no-dependency force reinstall
package_reinstall_result: success
built_wheel_sha256: ba71ef7e8e641bd462025e95e68617019e4505eb15c836a0111ded5506e3ba48
service_restart:
  colameta-stable.service: success
  colameta-mcp-remote.service: success
service_state_after_restart:
  colameta-stable.service: active/running
  colameta-mcp-remote.service: active/running
```

The advanced MCP service, tunnel client, public edge, OAuth configuration,
DNS, and provider configuration were not modified or restarted.

## Local Runtime Verification

Both `127.0.0.1:8766/healthz` and `127.0.0.1:8767/healthz` returned:

```yaml
ok: true
runtime_project_checkout_head: ad170ced2bd576215bcda0ea1078dd6d6f41cf9f
runtime_loaded_code_stale: false
reload_needed_for_verification: false
reload_awareness_reason: installed_package_matches_project_checkout
installed_package_matches_project_checkout: true
installed_package_verification_status: match
installed_package_project_source_clean: true
installed_package_source_cleanliness_status: clean
```

The external-OAuth origin remained in `external-oauth` mode; no authorization
material was inspected or recorded.

## Remote Tool Surface

Remote `list_registered_projects` returned `ok=true` and included
`colameta-self-dev` with `available=true` and `runner_managed=true`.

Remote `analyze_project_state` returned:

```yaml
ok: true
project_name: colameta-self-dev
mcp_exposure_profile: commander
visible_tool_count: 7
visible_tool_names:
  - list_registered_projects
  - get_apps_connector_smoke_packet
  - render_commander_app
  - analyze_project_state
  - run_mcp_workflow
  - manage_validation_run
  - manage_git
```

## ChatGPT Apps Connector Smoke

Sanitized evidence came only from the approved loopback tunnel health endpoints
and systemd state: `healthz` returned `live`, `readyz` returned `ready`, and the
tunnel-client unit was `active/running`. No tunnel configuration or raw log was
read.

```yaml
tool: get_apps_connector_smoke_packet
ok: true
scope: mcp:read
read_only: true
side_effects: false
project_name: colameta-self-dev
apps_connector_closeout_status: ready
apps_connector_reachability: proved_by_successful_apps_tool_call
connector_overall_status: healthy
operator_closeout_status: connector_closeout_ready
operator_closeout_decision: ready
evidence_gap_count: 0
runtime_head: ad170ced2bd576215bcda0ea1078dd6d6f41cf9f
runtime_loaded_code_stale: false
stable_replacement_status: stable_aligned
stable_runtime_head: ad170ced2bd576215bcda0ea1078dd6d6f41cf9f
reason_codes:
  - RUNTIME_LOADED_CODE_CURRENT
  - LOCAL_SERVICE_HEALTHY
  - WEB_ENDPOINT_HEALTHY
  - MCP_ENDPOINT_HEALTHY
  - TUNNEL_CLIENT_HEALTHZ_READY
  - TUNNEL_CONTROL_PLANE_READYZ_READY
```

## Decision

```yaml
stable_replacement_result: ready
commander_seven_tool_surface_loaded: true
remote_project_list_ready: true
apps_connector_smoke_ready: true
rollback_backup_available: true
```

## Boundary

This replacement did not push commits, create or push tags, publish a package,
create a release, execute an executor workflow, modify OAuth/DNS/Cloudflare or
tunnel configuration, read tokens/cookies/browser state/private memory/raw
logs, or write Delivery accepted, ReviewDecision, or GateEvent. This receipt
does not authorize any further stable replacement or service restart.
