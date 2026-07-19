# Stable Replacement Receipt: fcfab88

## Summary

```yaml
date: 2026-07-19
completed_at_utc: 2026-07-19T08:20:47Z
authorized_target_commit: fcfab88b5feed0cdf669905b085775c39f8ca621
previous_stable_head: b6c864c4319ceaa0afc56f4bc2b2ae96998c5f29
stable_runtime_dir: /home/jenn/tools/colameta
project_root: /home/jenn/src/colameta-dev
replacement_result: completed
service_restart_completed: true
```

Jenn explicitly authorized stable replacement and ColaMeta Private Beta service
restart for the exact full target commit above. The authorization did not cover
a different target, Git push, tag, release, package publication, Dashboard
submission, OAuth/DNS/tunnel configuration change, or any later stable
replacement.

## Preflight

```yaml
target_commit_exists: true
target_commit_subject: "fix: minimize commander public responses"
target_is_successor_of_previous_stable: true
task_worktree_clean: true
stable_worktree_tracked_clean: true
previous_stable_head_verified: true
previous_services:
  colameta-stable.service: active/running
  colameta-mcp-remote.service: active/running
  colameta-tunnel-client.service: active/running
  colameta-mcp-advanced.service: active/running
previous_restart_counts: 0
```

The stable worktree contained two pre-existing untracked `Zone.Identifier`
sidecar files. Their contents were not read, they did not collide with target
tracked paths, and they were preserved unchanged throughout replacement.

## Rollback Backup

```yaml
backup_file: /home/jenn/tools/colameta-stable-backups/stable-before-fcfab88-20260719T081512Z.tar.gz
backup_sha256: c99a890c45b31d8c819384e2dc74b4a979d8b5488c6ecbba1f30065d3efc4506
backup_size_bytes: 4149978
archive_entry_count: 817
archive_validation: gzip_test_passed
backup_scope: previous stable HEAD tracked source only
```

The archive was generated from Git-tracked `b6c864c` content. It excludes the
virtual environment, untracked sidecars, ignored runtime state, credentials,
and other private local state.

## Replacement

```yaml
stable_fetch: authorized target fetched from the local ColaMeta repository
stable_checkout: detached fcfab88b5feed0cdf669905b085775c39f8ca621
package_reinstall: local no-dependency force reinstall
package_reinstall_result: success
built_wheel_sha256: 7714577a596b94cf5ff72dcb125dafd6f7e1f2b53dac5a784b4f376221fe1281
restarted_units:
  colameta-stable.service:
    main_pid_before: 19087
    main_pid_after: 64511
    state: active/running
    restart_count: 0
  colameta-mcp-remote.service:
    main_pid_before: 19096
    main_pid_after: 64520
    state: active/running
    restart_count: 0
unchanged_units:
  colameta-tunnel-client.service:
    main_pid: 59509
    state: active/running
  colameta-mcp-advanced.service:
    main_pid: 58955
    state: active/running
```

The first unprivileged system-service restart request was rejected by Polkit
and did not restart either service. The same authorized restart was then
completed through the existing non-interactive privileged service-control
path. The tunnel and advanced MCP units were not restarted.

## Runtime Verification

Both `127.0.0.1:8766/healthz` and `127.0.0.1:8767/healthz` returned the following
facts after restart and again after the connector smoke:

```yaml
ok: true
runtime_project_checkout_head: fcfab88b5feed0cdf669905b085775c39f8ca621
runtime_loaded_code_stale: false
reload_needed_for_verification: false
installed_package_matches_project_checkout: true
installed_package_verification_status: match
installed_package_project_source_clean: true
```

The stable and remote service PIDs changed while the unchanged tunnel and
advanced service PIDs remained stable.

## Public HTTPS Preflight

Two read-only public preflights against
`https://colameta-mcp.skmt617.top`, each pinned to the exact expected target,
returned:

```yaml
ok: true
failures: []
healthz_http_status: 200
mcp_metadata_http_status: 200
protected_resource_metadata_http_status: 200
expected_runtime_head: fcfab88b5feed0cdf669905b085775c39f8ca621
runtime_project_checkout_head: fcfab88b5feed0cdf669905b085775c39f8ca621
runtime_loaded_code_stale: false
installed_package_matches_project_checkout: true
```

A generic unauthenticated Python URL client received an edge-layer HTTP 403 on
one later health request. This was not treated as a successful probe; the
purpose-built preflight immediately passed afterward, and authenticated remote
connector calls also completed successfully. No token, OAuth secret, cookie,
browser session, provider response body, private configuration, or service log
was read or recorded.

## Seven-Tool And Public-Minimization Smoke

The restarted stable MCP service exposed exactly:

1. `list_registered_projects`
2. `get_apps_connector_smoke_packet`
3. `render_commander_app`
4. `analyze_project_state`
5. `run_mcp_workflow`
6. `manage_validation_run`
7. `manage_git`

Every descriptor contained an `outputSchema` and the expected safety
annotations. `list_registered_projects` was called first and confirmed
`colameta-self-dev` with `available=true` and `runner_managed=true` without
printing other registry values or project roots.

All seven tools were then exercised through read-only actions on the loaded
stable service: connector smoke, Commander render, project analysis,
`project_status` inspect, validation inspect, and Git status. Every call
returned `ok=true`. The connector-smoke result reported `read_only=true`,
`side_effects=false`, and `runtime_aligned=true`.

A recursive public-result scan over each returned `data` object found:

```yaml
forbidden_internal_keys: []
absolute_local_path_values: 0
hidden_tool_references: []
```

The exact public-projection regression module also passed: `12 passed`.

## Remote Connector And Dashboard Re-review State

The installed remote connector successfully called, in order,
`list_registered_projects` followed by the five other tools currently present
in its cached callable inventory. All six remote calls returned minimized
results with no forbidden internal keys, absolute local paths, or hidden-tool
references.

The remote `render_commander_app` result advertised the full seven-tool server
surface and included `get_apps_connector_smoke_packet`. The current Codex
connector inventory, however, still exposed only six callable entries and did
not yet include that smoke tool. This is recorded as an external connector
inventory refresh/re-review item, not as evidence that the stable server failed
to load the seven-tool profile. No Dashboard refresh, re-import, submission, or
publication was performed under this authorization.

## Boundary

This operation did not push a commit, create or push a tag, publish a package,
create a release, submit or publish the ChatGPT App, mutate the Master Taskbook
or submission metadata, run an executor, create an apply preview, change OAuth,
DNS, Cloudflare, tunnel configuration, or restart the tunnel and advanced MCP
units. This receipt authorizes no future stable replacement.
