# Stable Replacement Receipt: 4d7b695

## Summary

```yaml
date: 2026-07-21
recorded_at_utc: 2026-07-21T01:20:10Z
authorized_target_commit: 4d7b6951c518af3aa094365d7357b7520e6c2b8f
previous_stable_head: 2dc78955ac284c88d56feee71fa5ebbb02c5d8f8
stable_runtime_dir: /home/jenn/tools/colameta
project_root: /home/jenn/src/colameta-dev
stable_replacement_result: complete
private_app_connector_result: ready
gate_review_live_inspect_result: pass
candidate_remote_traceability: origin_main
candidate_present_on_origin_main: true
remote_ci_validated_exact_target: true
source_pr: https://github.com/JENN2046/colameta/pull/178
```

Jenn explicitly authorized a separately bound exact stable replacement after
PR #178 merged. The authorization was bound to merge commit
`4d7b6951c518af3aa094365d7357b7520e6c2b8f` and covered replacement of the
existing stable runtime plus restart of `colameta-stable.service` and
`colameta-mcp-remote.service`. It did not authorize a tag, release, PyPI
publication, plugin publication, public App submission, DNS/tunnel change, or
provider configuration change.

## Candidate And CI Evidence

The exact target equalled `origin/main`. GitHub PR #178 was merged at that exact
commit and all six recorded checks succeeded:

```text
Python 3.10
Python 3.11
Python 3.12
Python 3.13
Python 3.14
Quality gates
```

Local pre-merge validation had also passed with 1,837 pytest tests, 2 skips,
55 subtests, self-hosting smoke, compileall, the frozen toolchain gate, the
private-Beta systemd tests, document links/fences, and `git diff --check`.

## Preflight And Rollback

The stable tracked worktree was clean at
`2dc78955ac284c88d56feee71fa5ebbb02c5d8f8`. Two pre-existing untracked
`Zone.Identifier` files were preserved and were not opened. Both authorized
services were active/running before replacement.

```yaml
backup_file: /home/jenn/tools/colameta-stable-backups/stable-before-4d7b695-20260721T011341Z.tar.gz
backup_sha256: 66540f19fc4b14a17222c15c1b633877a341fd73306ee1ad3ef4f1a29bb39557
backup_size_bytes: 4262383
backup_validation: gzip_test_passed
backup_scope: previous_stable_tracked_tree_only
rollback_ref: refs/heads/stable-backup/2dc7895-20260721-main-sync
rollback_commit: 2dc78955ac284c88d56feee71fa5ebbb02c5d8f8
```

No credential, token, cookie, browser state, private configuration content,
provider raw response, or service log was read.

## Replacement

The target was exported from the exact Git object into a temporary clean source
tree. A wheel was built with `--no-deps --no-build-isolation`, validated as a
ZIP archive, and installed into the stable virtual environment.

```yaml
validated_prebuilt_wheel: colameta-0.1.2-py3-none-any.whl
validated_prebuilt_wheel_sha256: fc96b4c8fa6c6f5e4804132878cb9722297ecb7cd3d3e86893fb020cfb1369dc
stable_checkout_head: 4d7b6951c518af3aa094365d7357b7520e6c2b8f
package_reinstall_result: success
```

The first restart after installing the standalone wheel returned healthy HTTP
services but unverified source provenance. The replacement therefore remained
not ready. ColaMeta was reinstalled from the exact stable checkout with
`--no-deps --force-reinstall --no-build-isolation`, which created the required
source-checkout binding. The exact source build reported wheel SHA-256
`cb075e91d6c2b4fb6c6cfebe12bf507a0470a1cbd247a7ab16dcabdc1b0cbb57`.
After the corrective restart, provenance and all acceptance gates passed.

```yaml
service_state_after_final_restart:
  colameta-stable.service:
    active_state: active
    sub_state: running
    main_pid: 66654
  colameta-mcp-remote.service:
    active_state: active
    sub_state: running
    main_pid: 66666
```

The services retained their existing loopback origins: Web `127.0.0.1:8801`,
Commander MCP `127.0.0.1:8766`, and external-OAuth MCP origin
`127.0.0.1:8767`. No tunnel, DNS, provider, OAuth, or network configuration was
changed or restarted.

## Runtime Verification

All three health endpoints returned `ok=true`. The installed-package evidence
bound the running package to the exact stable checkout:

```yaml
loaded_runtime_head: null
runtime_project_checkout_head: 4d7b6951c518af3aa094365d7357b7520e6c2b8f
runtime_loaded_code_stale: false
reload_needed_for_verification: false
reload_awareness_reason: installed_package_matches_project_checkout
installed_package_matches_project_checkout: true
installed_package_verification_status: match
installed_package_project_source_clean: true
installed_package_source_cleanliness_status: clean
web_8801: healthy
mcp_8766: healthy
mcp_8767: healthy
```

`loaded_runtime_head` remained unavailable because the runtime was installed as
a package. The contract accepts the exact installed-package/source-checkout
comparison as the provenance authority; it proved the target and reported no
reload requirement.

## Seven-Tool And Real Private App Acceptance

Direct `tools/list` on the stable Commander endpoint returned exactly:

```text
list_registered_projects
get_apps_connector_smoke_packet
render_commander_app
analyze_project_state
run_mcp_workflow
manage_validation_run
manage_git
```

The real authorized ColaMeta private App connector then completed these
read-only calls:

1. `list_registered_projects` returned `ok=true`, five registered projects, and
   included `colameta-self-dev`.
2. `analyze_project_state(project_name="colameta-self-dev")` returned the
   Commander profile, exactly seven visible tools, and project HEAD `4d7b695`.
3. `run_mcp_workflow(workflow="gate_review_request", phase="inspect")` returned
   `status=succeeded`, `read_only=true`, `side_effects=false`, and
   `candidate_count=0`.
4. `get_apps_connector_smoke_packet` returned `overall_status=healthy`,
   `connector_closeout_ready / ready`, zero evidence gaps,
   `read_only=true`, and `side_effects=false` using only allowlisted sanitized
   evidence from successful authorized App calls.
5. `render_commander_app` returned `ok=true`, `read_only=true`, and
   `side_effects=false`.

The repository Work Item governance ledger remains intentionally disabled, so
`candidate_count=0` is the truthful inspect result. No synthetic Work Item,
ReviewDecision, GateEvent, Delivery State transition, executor run, or Git write
was created.

## Boundary

No Git push, tag, release, PyPI publication, plugin publication, ChatGPT App
publication/submission, tunnel restart, DNS change, provider configuration
change, credential read, executor run, or real Delivery State mutation occurred.
The unrelated untracked logo in the development worktree and both stable
`Zone.Identifier` files were preserved.

This receipt records only the exact replacement authorized for
`4d7b6951c518af3aa094365d7357b7520e6c2b8f`; it does not authorize another
stable replacement or service restart.
