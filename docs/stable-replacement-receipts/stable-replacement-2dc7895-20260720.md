# Stable Replacement Receipt: 2dc7895

## Summary

```yaml
date: 2026-07-20
recorded_at_utc: 2026-07-20T21:30:55Z
authorized_target_commit: 2dc78955ac284c88d56feee71fa5ebbb02c5d8f8
previous_stable_head: 238cfec7fa2925f4383786278e34c07dedcb23e4
stable_runtime_dir: /home/jenn/tools/colameta
project_root: /home/jenn/src/colameta-dev
stable_replacement_result: complete
private_app_connector_result: ready
gate_review_live_inspect_result: pass
```

Jenn explicitly authorized replacement to the exact target commit and restart of
`colameta-stable.service` and `colameta-mcp-remote.service`. This was a ColaMeta
private App runtime replacement, not a plugin marketplace, package publication,
tag, release, or public App submission.

## Preflight And Rollback

The candidate commit existed locally and the stable tracked worktree was clean.
Two pre-existing untracked `Zone.Identifier` files in the stable checkout were
preserved and were not opened. Both authorized services were active/running
before replacement.

```yaml
backup_file: /home/jenn/tools/colameta-stable-backups/stable-before-2dc7895-20260720T212734Z.tar.gz
backup_sha256: 324c2364badd3816c5b13252128f15312a5f6956da0d7c528770021b1ef40fe0
backup_size_bytes: 4242431
backup_validation: gzip_test_passed
backup_scope: previous_stable_tracked_tree_only
rollback_ref: stable-backup/238cfec-20260720-gate-review
rollback_commit: 238cfec7fa2925f4383786278e34c07dedcb23e4
```

No credential, token, cookie, browser state, private configuration content,
provider raw response, or service log was read.

## Replacement

The stable checkout fetched the exact commit from the local development
repository and switched to detached
`2dc78955ac284c88d56feee71fa5ebbb02c5d8f8`. A single local wheel was built with
`--no-deps --no-build-isolation` and installed into the stable virtual
environment with `--no-deps --force-reinstall`.

```yaml
built_wheel: colameta-0.1.2-py3-none-any.whl
built_wheel_sha256: 218bce0dcaa547b7d129e5781f348ec447dbb39cebbc930b26e84d1b68ad81a3
package_reinstall_result: success
service_restart:
  colameta-stable.service: success
  colameta-mcp-remote.service: success
service_state_after_restart:
  colameta-stable.service:
    active_state: active
    sub_state: running
    main_pid: 3506
  colameta-mcp-remote.service:
    active_state: active
    sub_state: running
    main_pid: 3556
```

The services listen only on their existing loopback origins, `127.0.0.1:8766`
and `127.0.0.1:8767`. No tunnel, DNS, provider, OAuth, or network configuration
was changed or restarted.

## Runtime Verification

Allowlisted runtime status proved the exact loaded target:

```yaml
loaded_runtime_head: 2dc78955ac284c88d56feee71fa5ebbb02c5d8f8
project_checkout_head: 2dc78955ac284c88d56feee71fa5ebbb02c5d8f8
runtime_project_checkout_head: 2dc78955ac284c88d56feee71fa5ebbb02c5d8f8
runtime_loaded_code_stale: false
reload_needed_for_verification: false
reload_awareness_reason: installed_package_matches_project_checkout
web_8766: healthy
mcp_8766: healthy
mcp_8767: healthy
```

The installed stable package imported `gate_review_request` with the expected
26,000-character copyable-apply and 56,000-character workflow-result bounds.

## Real Private App Acceptance

The real authorized ColaMeta private App connector completed the following
read-only calls after service restart:

1. `list_registered_projects` returned `ok=true`, five registered projects, and
   `colameta-self-dev` as available and Runner-managed.
2. `analyze_project_state` returned the Commander profile with exactly seven
   tools and project HEAD `2dc7895`.
3. `run_mcp_workflow(workflow=gate_review_request, phase=inspect)` returned
   `status=succeeded`, `read_only=true`, `side_effects=false`, and the existing
   Work Item Gate authority boundary.
4. `get_apps_connector_smoke_packet` returned runtime aligned,
   `overall_status=healthy`, `connector_closeout_ready / ready`, and zero
   evidence gaps using sanitized evidence from those successful authorized App
   calls.
5. `render_commander_app` returned `ok=true`, `read_only=true`, and
   `side_effects=false`.

The repository Work Item governance ledger remains intentionally disabled and
the live inspect returned `candidate_count=0`. No Work Item, ReviewDecision,
GateEvent, or Delivery State transition was fabricated. The full
`inspect -> preview -> apply` positive path remains covered by the validated
service-mode/private-OAuth loopback E2E suite.

## Boundary

No Git push, tag, release, PyPI publication, plugin publication, ChatGPT App
publication/submission, tunnel restart, DNS change, provider configuration
change, credential read, executor run, or real Delivery State mutation occurred.
The existing unrelated untracked logo in the development worktree and the two
stable `Zone.Identifier` files were preserved.

This receipt records the one exact replacement authorized for
`2dc78955ac284c88d56feee71fa5ebbb02c5d8f8`; it does not authorize another
stable replacement or service restart.
