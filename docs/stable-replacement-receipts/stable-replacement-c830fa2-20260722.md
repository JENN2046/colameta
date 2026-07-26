# Stable Replacement Receipt: c830fa2

## Summary

```yaml
date: 2026-07-22
authorized_target_commit: c830fa2e52f4b67b190e5a24c11b5bae3d6def57
previous_stable_head: 4df46ddd53d742d7ccf8ed9001d497ad5ddd2c77
stable_runtime_dir: /home/jenn/tools/colameta
project_root: /home/jenn/src/colameta-dev
stable_replacement_result: complete
private_app_connector_result: ready
candidate_remote_traceability: local_only
candidate_present_on_origin_main: false
remote_ci_validated_exact_target: false
```

Jenn explicitly authorized replacement of the stable ColaMeta services to the
exact local commit above, followed by real ChatGPT App acceptance. This was a
local private-Beta runtime replacement, not a Git push, tag, release, package
publication, public App submission, or provider configuration change.

The target was validated locally before replacement. It was not pushed and no
remote CI claim is made for this exact object.

## Preflight And Rollback

The stable worktree was at `4df46dd` and contained only two pre-existing
untracked `Zone.Identifier` files; both were preserved without being opened.
Both authorized services were active before the replacement.

```yaml
backup_file: /home/jenn/tools/colameta-stable-backups/stable-before-4df46dd-20260722T165614Z.tar.gz
backup_sha256: 49cf91a05ba3de670517d1dbb957b762d50249be286d5ffc12587ac75aa37b6c
backup_size_bytes: 4384067
backup_validation: gzip_test_passed
backup_scope: previous_stable_tracked_tree_only
rollback_ref: stable-backup/4df46dd-20260722-context-binding
rollback_commit: 4df46ddd53d742d7ccf8ed9001d497ad5ddd2c77
```

No credential, token, cookie, browser login state, provider response, tunnel
configuration, or raw service log was read.

## Replacement

The stable checkout fetched the exact object from the local development remote
and switched to detached `c830fa2e52f4b67b190e5a24c11b5bae3d6def57`.

```yaml
wheel_preflight:
  filename: colameta-0.1.2-py3-none-any.whl
  sha256: 2da6dc26ffffd4342efbbcceecd49f71ccebba176f49047f9fab61703f0a5b5b
  install_from_wheel: success
source_provenance_reinstall:
  result: success
  reason: restore the installed package direct-source binding to the exact stable checkout
service_restart:
  colameta-stable.service: success
  colameta-mcp-remote.service: success
```

The source-provenance reinstall used the same exact stable checkout and did not
introduce another source revision. It was needed because installing directly
from a wheel alone does not retain the local source checkout binding used by
runtime provenance verification.

## Runtime Verification

Both restarted services were active/running and their allowlisted health
responses proved the exact installed-package equivalence:

```yaml
runtime_project_checkout_head: c830fa2e52f4b67b190e5a24c11b5bae3d6def57
runtime_loaded_code_stale: false
reload_needed_for_verification: false
reload_awareness_reason: installed_package_matches_project_checkout
installed_package_matches_project_checkout: true
installed_package_project_source_clean: true
web_mcp_8766: healthy
external_oauth_mcp_8767: healthy
```

## Real ChatGPT App Acceptance

The real authorized App connector completed these calls after the stable
services restarted:

1. `list_registered_projects` returned `ok=true`, five registered projects,
   and `colameta-self-dev` as available and Runner-managed.
2. `analyze_project_state` returned exactly seven Commander tools, HEAD
   `c830fa2`, and `colameta.canonical_project_state.v1`. Its state separated
   current Git/Runner observation from runtime and connector freshness instead
   of treating unobserved external evidence as unavailable.
3. `run_mcp_workflow(workflow=git_commit, phase=inspect)` returned the shared
   `colameta.project_context_binding.v1` contract, with the exact branch, HEAD,
   Runner plan digest, current version, review unit, and workflow intent.
4. `manage_validation_run(inspect -> preview)` returned the same bound context
   and generated a copyable `run` next action containing it. The subsequent
   real App `run` attempt was denied with `REMOTE_POLICY_DENIED`, as expected
   for the external OAuth remote policy; no validation command, source write,
   commit, or push occurred.
5. `get_apps_connector_smoke_packet` received only sanitized loopback
   health/ready status and returned `apps_connector_closeout.status=ready`,
   `overall_status=healthy`, and zero evidence gaps.
6. `render_commander_app` returned `ok=true`, `read_only=true`, the Commander
   MCP Apps widget resource, `interactive-decoupled` archetype, and visible
   tool count seven.

The work-item governance ledger remains disabled/shadow. No Work Item,
ReviewDecision, GateEvent, Delivery State transition, executor run, Git commit,
or push was fabricated during acceptance.

## Boundary

No Git push, tag, release, PyPI publication, public App submission, tunnel or
DNS change, OAuth/provider configuration change, credential read, raw log read,
or Delivery State mutation occurred. This receipt records only the exact stable
replacement to `c830fa2`; it does not authorize a future replacement or restart.
