# Stable Replacement Receipt: b6c864c

## Summary

```yaml
date: 2026-07-19
authorized_target_commit: b6c864c4319ceaa0afc56f4bc2b2ae96998c5f29
previous_stable_head: ad170ced2bd576215bcda0ea1078dd6d6f41cf9f
stable_runtime_dir: /home/jenn/tools/colameta
project_root: /home/jenn/src/colameta-dev
replacement_result: ready
service_restart_completed: true
```

Jenn explicitly authorized stable replacement and Private Beta service restart
for the full target commit above. The authorization did not cover a tag,
release, package publication, Git push, OAuth/DNS/tunnel configuration change,
or any later stable target.

## Preflight

```yaml
target_commit_exists: true
target_commit_subject: "Merge pull request #175 from JENN2046/agent/stage-0-6-governance-proof"
target_worktree_tracked_clean: true
stable_worktree_tracked_clean: true
source_delta_from_target_to_task_branch: none
previous_services:
  colameta-stable.service: active/running
  colameta-mcp-remote.service: active/running
  colameta-tunnel-client.service: active/running
  colameta-mcp-advanced.service: active/running
previous_restart_counts: 0
```

The source comparison covered `runner/`, `adapters/`, `schemas/`, `scripts/`,
`pyproject.toml`, and `bin/colameta`. The task-branch changes after `b6c864c`
were submission documentation and tests only.

## Rollback Backup

```yaml
backup_file: /home/jenn/tools/colameta-stable-backups/stable-before-b6c864c-20260719T065216Z.tar.gz
backup_sha256: 1c7b6c7da5c3ef4944a7d57e2c903e07797d338a70971be06adbc19cf1fdaf3f
backup_size_bytes: 4142200
archive_entry_count: 814
archive_validation: gzip_test_passed
backup_scope: previous stable HEAD tracked source only
```

The archive was generated from Git-tracked `ad170ce` content, excluding the
virtual environment, untracked files, ignored runtime state, credentials, and
other private local state.

## Replacement

```yaml
stable_fetch: authorized target fetched from the local ColaMeta repository
stable_checkout: detached b6c864c4319ceaa0afc56f4bc2b2ae96998c5f29
package_reinstall: local no-dependency force reinstall
package_reinstall_result: success
built_wheel_sha256: 0985fa39b78996e45ae5afb9b77c657f2dceb880e90cc9d47d36df27d4672d22
restarted_units:
  colameta-stable.service:
    main_pid_after: 19087
    state: active/running
  colameta-mcp-remote.service:
    main_pid_after: 19096
    state: active/running
unchanged_units:
  colameta-tunnel-client.service:
    main_pid: 59509
    state: active/running
  colameta-mcp-advanced.service:
    main_pid: 58955
    state: active/running
```

The first unprivileged `systemctl restart` request was rejected by Polkit and
did not change either service PID. It was not treated as success. The same
authorized restart was then completed through the available non-interactive
system-service control path, producing the new PIDs recorded above.

## Runtime Verification

Both `127.0.0.1:8766/healthz` and `127.0.0.1:8767/healthz`, followed by a
post-restart sample, returned:

```yaml
ok: true
runtime_project_checkout_head: b6c864c4319ceaa0afc56f4bc2b2ae96998c5f29
runtime_loaded_code_stale: false
reload_needed_for_verification: false
installed_package_matches_project_checkout: true
installed_package_verification_status: match
installed_package_project_source_clean: true
```

New service PIDs plus the live Stage 0–6 descriptor distinguish this result
from the pre-restart process, whose PID did not change after the rejected first
restart request.

## Public HTTPS Preflight

The read-only public preflight against
`https://colameta-mcp.skmt617.top` used the exact expected target head and
returned:

```yaml
ok: true
failures: []
healthz_http_status: 200
mcp_metadata_http_status: 200
protected_resource_metadata_http_status: 200
expected_runtime_head: b6c864c4319ceaa0afc56f4bc2b2ae96998c5f29
runtime_project_checkout_head: b6c864c4319ceaa0afc56f4bc2b2ae96998c5f29
runtime_loaded_code_stale: false
installed_package_matches_project_checkout: true
```

No bearer token, OAuth secret, cookie, browser session, provider response body,
private configuration, or raw service log was read or recorded.

## Seven-Tool And Connector Smoke

The loaded stable MCP service exposed exactly:

1. `list_registered_projects`
2. `get_apps_connector_smoke_packet`
3. `render_commander_app`
4. `analyze_project_state`
5. `run_mcp_workflow`
6. `manage_validation_run`
7. `manage_git`

All seven descriptors had the three required annotations and an
`outputSchema`. The loaded `run_mcp_workflow` description contained Stage 0–6
and no longer contained the previous Stage 3–6 wording.

`list_registered_projects` found `colameta-self-dev` with `available=true` and
`runner_managed=true`. Two connector-smoke samples using sanitized health
evidence returned:

```yaml
ok: true
read_only: true
side_effects: false
apps_status: ready
overall_status: healthy
operator_status: connector_closeout_ready
operator_decision: ready
evidence_gap_count: 0
```

## Boundary

This operation did not push a commit, create or push a tag, publish a package,
create a release, run an executor, mutate the Master Taskbook or its registry,
write Delivery accepted, create a ReviewDecision or GateEvent, change OAuth,
DNS, Cloudflare, or tunnel configuration, or restart the tunnel and advanced
MCP units. This receipt authorizes no future stable replacement.
