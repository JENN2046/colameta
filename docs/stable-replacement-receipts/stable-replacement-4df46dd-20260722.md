# Stable Replacement Receipt: 4df46dd

## Summary

```yaml
date: 2026-07-22
recorded_at_utc: 2026-07-22T14:52:39Z
authorized_target_commit: 4df46ddd53d742d7ccf8ed9001d497ad5ddd2c77
previous_stable_head: b53e47cde7c2ff45a3f4313846f0d4bb6a0f9946
stable_runtime_dir: /home/jenn/tools/colameta
project_root: /home/jenn/src/colameta-dev
stable_replacement_result: complete
candidate_remote_traceability: local_only
candidate_present_on_local_origin_main: false
remote_ci_validated_exact_target: false
local_full_pytest: 1948 passed, 3 warnings, 142 subtests
stable_endpoint_seven_tool_result: pass
public_https_oauth_preflight_result: pass
chatgpt_connector_session_result: pass
gate_review_live_inspect_result: pass
connector_smoke_result: ready
```

Jenn explicitly authorized replacement of the stable runtime with the exact
commit `4df46ddd53d742d7ccf8ed9001d497ad5ddd2c77`. The authorization covered the
bounded checkout, package reinstall, restart of `colameta-stable.service` and
`colameta-mcp-remote.service`, and read-only verification. It did not authorize
a Git push, tag, release, package publication, tunnel or OAuth configuration
change, or credential access.

## Candidate Evidence

The exact target was available in the local development checkout and passed the
full local test suite before replacement:

```text
1948 passed, 3 warnings, 142 subtests passed
```

At preflight, the target was not contained by the locally available
`origin/main` reference. This receipt therefore records local validation only;
it does not claim remote CI validation or remote traceability.

## Preflight And Rollback

The previous stable tracked checkout was clean at `b53e47c`. Two pre-existing
untracked `Zone.Identifier` files were preserved and their contents were not
read.

```yaml
backup_file: /home/jenn/tools/colameta-stable-backups/stable-before-4df46dd-20260722T144702Z.tar.gz
backup_sha256: eb676ef464df581f93269268e61964c4aa607ffb6a89ff83d6e3494ad46236fd
backup_size_bytes: 4381095
backup_validation: gzip_test_passed
backup_scope: previous_stable_tracked_tree_only
rollback_ref: refs/heads/stable-backup/b53e47c-20260722-before-4df46dd
rollback_commit: b53e47cde7c2ff45a3f4313846f0d4bb6a0f9946
```

The initial non-privileged system-service restart was rejected before either
service restarted. The replacement guard restored the previous checkout and
installed package. A subsequent non-interactive, host-policy-approved
`sudo -n systemctl` restart completed the authorized replacement.

## Replacement

The stable checkout imported the exact object from the local development
repository, detached to `4df46dd`, and reinstalled ColaMeta directly from that
checkout with `--no-deps --force-reinstall --no-build-isolation --no-compile`.
A wheel was built and ZIP-validated as independent package evidence.

```yaml
stable_checkout_head: 4df46ddd53d742d7ccf8ed9001d497ad5ddd2c77
validated_wheel: /home/jenn/tools/colameta-stable-backups/colameta-4df46dd-20260722T144702Z.whl
validated_wheel_sha256: 8cd3c72f5f4e54ca7b17e228727249968d0efc077ed4e9a43c9e74b928746795
validated_wheel_size_bytes: 1397878
wheel_zip_validation: passed
package_reinstall_result: success
```

Only the two authorized services were restarted:

```yaml
service_state_after_restart:
  colameta-stable.service:
    active_state: active
    sub_state: running
    pre_restart_main_pid: 15275
    post_restart_main_pid: 96963
  colameta-mcp-remote.service:
    active_state: active
    sub_state: running
    pre_restart_main_pid: 15311
    post_restart_main_pid: 96990
```

No tunnel, DNS, OAuth, provider, or network configuration was changed.

## Runtime Verification

The stable Web, Commander MCP, and external-OAuth MCP loopback health endpoints
all returned HTTP 200. Runtime/package evidence bound the services to the exact
stable checkout:

```yaml
runtime_project_checkout_head: 4df46ddd53d742d7ccf8ed9001d497ad5ddd2c77
runtime_loaded_code_stale: false
reload_needed_for_verification: false
reload_awareness_reason: installed_package_matches_project_checkout
installed_package_verification_status: match
installed_package_matches_project_checkout: true
installed_package_project_source_clean: true
installed_package_source_cleanliness_status: clean
installed_runtime_file_count: 235
matched_runtime_file_count: 235
stable_replacement_cadence_status: stable_aligned
```

The aggregate local status command also observed an unrelated development
service record as stale; its runtime subpacket for the stable checkout remained
current and did not affect the restarted stable endpoints or the public
preflight.

## Seven-Tool And Connector Acceptance

Direct MCP `tools/list` on `127.0.0.1:8766/mcp` returned exactly these seven
tools:

```text
list_registered_projects
get_apps_connector_smoke_packet
render_commander_app
analyze_project_state
run_mcp_workflow
manage_validation_run
manage_git
```

Each tool completed its bounded read-only call for `colameta-self-dev`.
`run_mcp_workflow` with `gate_review_request/inspect` returned `succeeded`,
`read_only=true`, `side_effects=false`, and `candidate_count=0`. No Work Item,
executor run, validation run, Git write, ReviewDecision, GateEvent, or delivery
state transition was created.

The installed ChatGPT connector in this session repeated the seven-tool
read-only acceptance. Its connector smoke returned `ready`,
`connector_closeout_ready`, decision `ready`, and zero evidence gaps after
allowlisted loopback tunnel facts only:

```yaml
tunnel_client: healthz returned live
control_plane: readyz returned ready
```

The public HTTPS MCP preflight passed for the exact target and verified:

```yaml
runtime_project_checkout_head: 4df46ddd53d742d7ccf8ed9001d497ad5ddd2c77
runtime_loaded_code_stale: false
reload_needed_for_verification: false
installed_package_matches_project_checkout: true
installed_package_verification_status: match
installed_package_project_source_clean: true
installed_package_source_cleanliness_status: clean
```

No token, cookie, provider response, browser state, tunnel configuration, or
raw service log was read or retained.

## Boundary

This receipt records a completed local stable replacement. It does not claim a
Git push, remote CI result, tag, release, package publication, DNS/tunnel
change, OAuth change, or delivery acceptance.
