# Stable Replacement Receipt: b660f7b

## Summary

```yaml
date: 2026-07-22
recorded_at_utc: 2026-07-21T16:28:44Z
finalized_at_utc: 2026-07-21T16:50:16Z
authorized_target_commit: b660f7b6819dcca1f347d4634036353ca900c11a
previous_stable_head: 4d7b6951c518af3aa094365d7357b7520e6c2b8f
stable_runtime_dir: /home/jenn/tools/colameta
project_root: /home/jenn/src/colameta-dev
stable_replacement_result: complete
stable_endpoint_seven_tool_result: pass
sanitized_external_evidence_result: pass
public_https_oauth_preflight_result: pass
private_app_authenticated_session_result: pass
private_app_connector_result: ready
authenticated_apps_verified_at_utc: 2026-07-21T16:48:13Z
gate_review_live_inspect_result: pass
candidate_remote_traceability: origin_main
candidate_present_on_origin_main: true
remote_ci_validated_exact_target: true
source_pr: https://github.com/JENN2046/colameta/pull/181
```

Jenn explicitly authorized replacement of the existing stable runtime with
`b660f7b6819dcca1f347d4634036353ca900c11a` and restart of
`colameta-stable.service` and `colameta-mcp-remote.service`. The authorization
also covered read-only seven-tool and sanitized external-evidence acceptance.
It did not authorize a tag, release, package publication, public App
submission, DNS/tunnel configuration change, provider configuration change,
or credential access.

## Candidate And CI Evidence

The exact target equalled `origin/main` and PR #181 was merged at that commit.
All six recorded checks succeeded for the exact PR head included by the merge:

```text
Python 3.10
Python 3.11
Python 3.12
Python 3.13
Python 3.14
Quality gates
```

The final local validation bound by the Commander convergence taskbook was
1,919 passed tests, 2 skips, 142 subtests, self-hosting smoke, compileall,
Ruff, `git diff --check`, and zero retained bytecode.

## Preflight And Rollback

The stable tracked worktree was clean at `4d7b695`. Two pre-existing untracked
`Zone.Identifier` files were preserved and their contents were not opened.
Both authorized services were active/running before replacement, and Web,
Commander MCP, external-OAuth MCP, tunnel health, and tunnel readiness checks
were healthy.

```yaml
backup_file: /home/jenn/tools/colameta-stable-backups/stable-before-b660f7b-20260721T162312Z.tar.gz
backup_sha256: 226677529d0f10830725f7eab52196e1ec4e01975613e333562cb8f65f8f5de8
backup_size_bytes: 4273414
backup_validation: gzip_test_passed
backup_scope: previous_stable_tracked_tree_only
rollback_ref: refs/heads/stable-backup/4d7b695-20260722-before-b660f7b
rollback_commit: 4d7b6951c518af3aa094365d7357b7520e6c2b8f
```

No credential, token, cookie, browser state, private configuration content,
provider raw response, or service log was read.

## Replacement

The stable checkout fetched local `origin/main` and detached to the exact
authorized commit. A no-dependency, no-build-isolation wheel was built and
validated as a ZIP archive. The stable virtual environment was then reinstalled
directly from the exact stable checkout using `--no-deps --force-reinstall
--no-build-isolation` so runtime provenance retained its checkout binding.

```yaml
validated_wheel: colameta-0.1.2-py3-none-any.whl
validated_wheel_file: /home/jenn/tools/colameta-stable-backups/colameta-b660f7b-20260721T162312Z.whl
validated_wheel_sha256: 04ec2f7e93e5dc038aa5a84b1d9b69344166722b8e82902106bd6387ab0cbe75
validated_wheel_size_bytes: 1378510
wheel_zip_validation: passed
validated_wheel_retained: true
stable_checkout_head: b660f7b6819dcca1f347d4634036353ca900c11a
package_reinstall_result: success
source_bound_install_build_sha256_observed: 9e2318458dd37c4c8990223e9cc6cbe9e3ac2fbab9850e98440071378d0b9e0d
source_bound_install_wheel_retained: false
```

Only the two explicitly authorized services were restarted. Their pre-restart
PIDs were 66654 and 66666; the final processes were new and running:

```yaml
service_state_after_restart:
  colameta-stable.service:
    active_state: active
    sub_state: running
    main_pid: 30831
  colameta-mcp-remote.service:
    active_state: active
    sub_state: running
    main_pid: 30861
```

The services retained their existing loopback origins: Web `127.0.0.1:8801`,
Commander MCP `127.0.0.1:8766`, and external-OAuth MCP origin
`127.0.0.1:8767`. No tunnel, DNS, OAuth, provider, or network configuration was
changed or restarted.

## Runtime Verification

All three service health endpoints returned `ok=true`. Package/source evidence
bound the running services to the exact stable checkout:

```yaml
runtime_project_checkout_head: b660f7b6819dcca1f347d4634036353ca900c11a
runtime_loaded_code_stale: false
reload_needed_for_verification: false
reload_awareness_reason: installed_package_matches_project_checkout
installed_package_matches_project_checkout: true
installed_package_verification_status: match
installed_package_project_source_clean: true
installed_package_source_cleanliness_status: clean
stable_replacement_cadence_status: stable_aligned
candidate_differs_from_stable: false
web_8801: healthy
mcp_8766: healthy
mcp_8767: healthy
```

## Seven-Tool Acceptance

Direct `tools/list` on the stable Commander endpoint returned exactly seven
tools, and every tool completed one bounded read-only, inspect, or status call:

```text
list_registered_projects
get_apps_connector_smoke_packet
render_commander_app
analyze_project_state
run_mcp_workflow
manage_validation_run
manage_git
```

Observed results:

- `list_registered_projects`: `ok=true`, five projects, including
  `colameta-self-dev`;
- `get_apps_connector_smoke_packet`: `ok=true`, `read_only=true`,
  `side_effects=false`, closeout `ready`;
- `render_commander_app`: `ok=true`, `read_only=true`, `side_effects=false`,
  seven visible tools, closeout `ready`;
- `analyze_project_state`: `ok=true`, `read_only=true`, `side_effects=false`,
  clean `main` at `b660f7b`, seven visible tools;
- `run_mcp_workflow` with `gate_review_request/inspect`: `status=succeeded`,
  result `read_only=true`, `side_effects=false`, `candidate_count=0`;
- `manage_validation_run` with `action=inspect`: `ok=true`;
- `manage_git` with `action=status`: `ok=true`, clean `main`.

Work Item governance remains intentionally disabled, so `candidate_count=0`
is the truthful inspect result. No synthetic Work Item, ReviewDecision,
GateEvent, Delivery State transition, executor run, validation run, Git write,
or preview confirmation was created.

## Sanitized External Evidence

Real loopback tunnel observability returned `live` from `/healthz` and `ready`
from `/readyz` at `2026-07-21T16:26:47Z`. Only these allowlisted facts were
projected into the smoke call:

```yaml
tunnel_client:
  status: healthy
  reason_code: TUNNEL_CLIENT_HEALTHZ_READY
  evidence_source: loopback tunnel-client healthz returned live
control_plane:
  status: healthy
  reason_code: TUNNEL_CONTROL_PLANE_READYZ_READY
  evidence_source: loopback tunnel-client readyz returned ready
connector_runtime_health:
  overall_status: healthy
  operator_closeout: connector_closeout_ready
  decision: ready
  evidence_gap_count: 0
```

The public HTTPS/OAuth preflight against
`https://colameta-mcp.skmt617.top` returned `ok=true`, no failures, HTTP 200 for
health, MCP discovery, and protected-resource metadata, and exact runtime head
`b660f7b6819dcca1f347d4634036353ca900c11a`.

## Authenticated Apps Acceptance

Jenn completed the final read-only acceptance through a real authorized
ChatGPT Apps session after reconnecting the `ColaMeta` connector. The session
showed one connector, no legacy `ColaMeta MCP v2` connector, and exactly the
same seven tools listed above. Every tool completed one bounded call:

- `list_registered_projects`: `ok=true`, five projects, including
  `colameta-self-dev`;
- `get_apps_connector_smoke_packet`: `ok=true`, `read_only=true`,
  `side_effects=false`, closeout `ready`, overall health `healthy`, operator
  decision `ready`, and zero evidence gaps;
- `render_commander_app`: `ok=true`, `read_only=true`, `side_effects=false`,
  seven visible tools, closeout `ready`;
- `analyze_project_state`: `ok=true`, `read_only=true`, `side_effects=false`,
  branch `main`, short HEAD `b660f7b`, clean worktree, seven visible tools,
  runtime current/aligned, and stable already aligned;
- `run_mcp_workflow` with `gate_review_request/inspect`: `ok=true`,
  `status=succeeded`, inner result `read_only=true`, `side_effects=false`, no
  preview IDs, governance disabled, and `candidate_count=0`;
- `manage_validation_run` with `inspect/current_version`: `ok=true`; no preview
  or validation run occurred;
- `manage_git` with `status`: `ok=true`, branch `main`, with empty changed,
  untracked, and status lists.

Before that authenticated acceptance, this receipt was temporarily moved from
the project root to the controlled backup directory, so `main@b660f7b` was
clean for the observed `analyze_project_state` and `manage_git status` calls.
It was restored to this path only after the Apps acceptance passed, then
updated with the final result. Its current untracked status therefore
postdates—and does not contradict—the clean worktree observed by ChatGPT Apps.

No `token_expired` error occurred. The response included only generic recovery
guidance for that error code. The authenticated session did not execute a
workflow preview/apply/run, validation run, Git write, file mutation, executor
start, ReviewDecision, GateEvent, Delivery State mutation, service lifecycle
action, or stable replacement. No token, cookie, credential, browser login
state, or raw log was read or recorded.

## Boundary

No Git commit or push, tag, release, package publication, plugin publication,
public App submission, tunnel restart, DNS change, provider configuration
change, credential read, executor run, validation run, Git mutation, or real
Delivery State mutation occurred. This receipt records only the replacement
authorized for `b660f7b6819dcca1f347d4634036353ca900c11a`; it does not authorize
another stable replacement or service restart.
