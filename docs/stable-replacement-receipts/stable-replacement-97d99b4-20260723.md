# Stable Replacement Receipt: 97d99b4

## Summary

```yaml
date: 2026-07-23
authorized_target_commit: 97d99b4bc9bfb2bd7e87048cda135effba24006f
previous_stable_head: c830fa2e52f4b67b190e5a24c11b5bae3d6def57
stable_runtime_dir: /home/jenn/tools/colameta
project_root: /home/jenn/src/colameta-dev
stable_replacement_result: complete
private_app_connector_result: ready
packaged_result_acceptance: partial
candidate_remote_traceability: local_only
candidate_present_on_origin_main: false
remote_ci_validated_exact_target: false
```

Jenn explicitly authorized replacement of the stable ColaMeta services to the
exact local commit above, followed by real ChatGPT App acceptance. This was a
local private-Beta runtime replacement, not a Git push, tag, release, package
publication, public App submission, or provider configuration change.

The target had passed local targeted and full validation before replacement. It
was not pushed and no remote CI claim is made for this exact object.

## Preflight And Rollback

The stable worktree was at `c830fa2` and contained only two pre-existing
untracked `Zone.Identifier` files; both were preserved without being opened.

```yaml
backup_file: /home/jenn/tools/colameta-stable-backups/stable-before-c830fa2-20260723T005457Z.tar.gz
backup_sha256: 2d2f2e7288da5ff66f74d33426a52b229f2a8bb34dfadf6d8bcb48782bbf73de
backup_size_bytes: 4398696
backup_validation: gzip_test_passed
backup_scope: previous_stable_tracked_tree_only
rollback_ref: stable-backup/c830fa2-20260723-result-artifact
rollback_commit: c830fa2e52f4b67b190e5a24c11b5bae3d6def57
```

No credential, token, cookie, browser login state, provider response, tunnel
configuration, or raw service log was read.

## Replacement And Runtime Verification

The stable checkout fetched the exact object from the local development remote,
switched to detached `97d99b4bc9bfb2bd7e87048cda135effba24006f`, installed the
candidate wheel, and reinstalled directly from that exact checkout to preserve
source-provenance verification. Both authorized services restarted successfully.

```yaml
wheel_preflight:
  filename: colameta-0.1.2-py3-none-any.whl
  sha256: a9915bf8b3140d4f5909765adc1f2afbe4c07b5c9e57c5b398558d2f477bc8e5
  install_from_wheel: success
source_provenance_reinstall: success
service_restart:
  colameta-stable.service: success
  colameta-mcp-remote.service: success
runtime_project_checkout_head: 97d99b4bc9bfb2bd7e87048cda135effba24006f
runtime_loaded_code_stale: false
reload_needed_for_verification: false
installed_package_matches_project_checkout: true
installed_package_project_source_clean: true
web_mcp_8766: healthy
external_oauth_mcp_8767: healthy
public_https_mcp_preflight: passed
```

## Real ChatGPT App Acceptance

The real authorized App connector completed read-only calls after replacement:

1. `list_registered_projects` returned `ok=true` and included
   `colameta-self-dev`.
2. `analyze_project_state` returned exact HEAD `97d99b4`, the expected seven
   exposed Commander tools, and the running runtime proof. The only reported
   development-worktree changes were the preserved untracked historical
   replacement receipts.
3. A deliberately large, read-only `manage_git(history_show)` response was
   returned as `packaged=true` with a short-lived opaque artifact handle,
   `page_count=8`, a first-page `resource_uri`, a later-page URI template, and
   a 64-character `content_sha256` (`b48ff0fa74e52feba050bf492297ac50f7a290c098abde532a92071d1bfd8e2f`).
   This proves the deployed ChatGPT-facing tool returns a recoverable packaged
   result rather than dropping oversized content.
4. `get_apps_connector_smoke_packet`, supplied only sanitized loopback
   health/ready observations, returned connector closeout `ready`, overall
   status `healthy`, and zero evidence gaps.

The final continuation substep remains **not accepted**. After a ChatGPT App
refresh, a freshly issued eight-page artifact was retried and the host's
dynamic-resource proxy again returned generic `Unknown resource` for its known
URI. In the same refreshed session, `resources/read` successfully returned the
static Commander widget resource. The failure is therefore specific to dynamic
resource-template routing and occurred before a server-level artifact-read
result. Real-App retrieval of all eight pages and end-to-end SHA-256 reassembly
cannot be claimed from this session.

The deployed server's deterministic regression suite covers the resource-read
and hash path; this receipt deliberately distinguishes that local proof from
the blocked host acceptance. The next product change, if authorized, is a
typed, read-only artifact-page compatibility route analogous to the existing
manifest-read fallback. It can preserve the same opaque handle, paging, expiry,
and SHA-256 contract while working around this host limitation.

## Boundary

No Git push, tag, release, PyPI publication, public App submission, tunnel or
DNS change, OAuth/provider configuration change, credential read, raw log read,
or Delivery State mutation occurred. This receipt records only the exact stable
replacement to `97d99b4`; it does not authorize a future replacement or
restart.
