---
receipt_type: stable_promotion_rehearsal_packet
receipt_id: stable_promotion_rehearsal_0718f27_20260706
recorded_at_utc: 2026-07-05T16:43:40Z
project_name: colameta-self-dev
candidate_head: 0718f27bca6ee8f27f143e8af19aaef828c6f3db
candidate_short_head: 0718f27
result: partial
---

# Stable Promotion Rehearsal Packet: 0718f27

This packet records a read-only stable promotion and rollback rehearsal for the
current candidate. It does not replace `/home/jenn/tools/colameta`, does not
restart `colameta-stable.service`, does not reinstall packages, and does not
change network, proxy, Auth0, Cloudflare, or systemd state.

## Current Candidate

```yaml
candidate_repo: /home/jenn/src/colameta-dev
candidate_branch: codex/external-oauth-resource-server
candidate_head: 0718f27bca6ee8f27f143e8af19aaef828c6f3db
candidate_worktree_clean: true
artifact_manifest_sha256: 17d551ca0993578dacb0dc1f8739e6173fd21c2382414402d6bb31550269843a
```

## Stable Runtime Observation

Observed with read-only commands only.

```yaml
stable_runtime_dir: /home/jenn/tools/colameta
stable_git_head: 98da7e0bc74b394e6c48561c24b6ab464e55c764
stable_git_status_short: clean
stable_service_unit: colameta-stable.service
stable_service_state: active/running
stable_service_pid: 1846865
stable_service_started_at: Sun 2026-07-05 17:36:12 CST
stable_service_unit_source: /run/user/1000/systemd/transient/colameta-stable.service
```

The stable runtime is still on `98da7e0`, not the candidate `0718f27`.

## Read-Only Rehearsal Checks

```yaml
checked_candidate_git_head: pass
checked_candidate_worktree_clean: pass
checked_stable_git_head: pass
checked_stable_worktree_status: pass
checked_stable_service_state: pass
checked_backup_archive_inventory: pass
checked_tunnel_service_unit_static_syntax: pass
checked_tunnel_start_script_static_syntax: pass
```

Validation commands used:

```text
git status --short --branch
git rev-parse HEAD
git -C /home/jenn/tools/colameta rev-parse HEAD
git -C /home/jenn/tools/colameta status --short
systemctl --user show colameta-stable.service --property=ActiveState,SubState,MainPID,ExecMainStartTimestamp,FragmentPath,LoadState
find /home/jenn/tools/colameta-stable-backups -maxdepth 1 -type f -name 'stable-before-*.tar.gz' -printf '<name> <size>'
bash -n scripts/colameta_tunnel_client_service.sh
systemd-analyze verify systemd/user/colameta-tunnel-client.service
```

The `scripts/colameta_tunnel_client_service.sh check` mode was intentionally not
run because it reads `.env.local` to verify key presence. Static syntax checks
were used instead.

## Rollback Rehearsal

Rollback was rehearsed as a command and evidence plan only. It was not executed.

Latest observed stable backup archive:

```yaml
backup_file: stable-before-98da7e0-20260705T173518+0800.tar.gz
backup_size_bytes: 13554367
backup_root: /home/jenn/tools/colameta-stable-backups
```

Rollback plan, requiring a separate exact authorization before execution:

```text
1. Confirm target rollback backup and target stable commit.
2. Stop only the exact stable service process or unit identified in the active authorization.
3. Restore `/home/jenn/tools/colameta` from the selected backup or checkout the authorized rollback commit.
4. Reinstall package into `/home/jenn/tools/colameta/.venv` without reading secrets.
5. Start `colameta-stable.service` with the previous loopback-only command.
6. Verify Web/MCP health on `127.0.0.1:8801` and `127.0.0.1:8766`.
7. Record a stable replacement or rollback receipt with backup path, sha256, health evidence, and safety boundary.
```

## Current Blocker

```yaml
readiness_status: not_ready_for_stable_promotion_review
remaining_local_blocker: RUNTIME_RELOAD_NEEDED_FOR_VERIFICATION
reason: running stable service cannot prove it has loaded current checkout code
required_next_evidence: runtime loaded-code freshness for candidate head
```

Clearing this blocker requires a service reload/restart or an equivalent
current-checkout runtime verification surface. This packet does not authorize or
perform that action.

## Boundary

```yaml
stable_service_restarted: false
stable_runtime_modified: false
package_reinstalled: false
network_or_proxy_modified: false
auth_provider_modified: false
executor_run_performed: false
delivery_state_accepted: false
review_decision_created: false
gate_event_emitted: false
tokens_or_cookies_read: false
env_values_read: false
raw_logs_read: false
```
