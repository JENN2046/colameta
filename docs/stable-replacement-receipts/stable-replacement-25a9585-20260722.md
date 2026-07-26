# Stable Replacement Receipt: 25a9585

## Summary

```yaml
date: 2026-07-22
recorded_at_utc: 2026-07-22T12:37:43Z
authorized_target_commit: 25a95859b474e3ba76308dfdbc371c4b68c2b6f7
previous_stable_head: b660f7b6819dcca1f347d4634036353ca900c11a
stable_runtime_dir: /home/jenn/tools/colameta
project_root: /home/jenn/src/colameta-dev
stable_replacement_result: complete
candidate_traceability: local_exact_commit_not_pushed
remote_ci_validated_exact_target: not_run
```

Jenn explicitly authorized committing the current working-tree changes and then
replacing the stable runtime with that exact commit. The authorization covered
the two service restarts and local read-only acceptance. It did not authorize a
push, tag, release, package publication, App submission, tunnel/DNS/OAuth
change, provider configuration change, or credential access.

## Candidate And Validation

The committed candidate was:

```text
25a95859b474e3ba76308dfdbc371c4b68c2b6f7
feat(mcp): add manifest-bound review resources
```

The source worktree was clean before replacement. Validation completed against
the exact source candidate:

```text
1941 passed
2 skipped
142 subtests passed
Ruff passed
compileall passed
self-hosting smoke passed
agent-consumer smoke passed
git diff --check passed
```

The pytest run retained three pre-existing temporary-directory cleanup warnings.
An initial full run exposed an opaque-resource URI sanitization defect and a
verification-environment bytecode gate; both were corrected before the passing
run. The virtual-environment bytecode cache was then explicitly cleared as a
recreatable validation artifact.

## Preflight And Rollback

The prior stable checkout was detached at `b660f7b`. Two pre-existing untracked
`Zone.Identifier` files were preserved without opening their contents.

```yaml
backup_file: /home/jenn/tools/colameta-stable-backups/stable-before-25a9585-20260722T123255Z.tar.gz
backup_sha256: 9ce288c821bf750abdf8fa1e1560bb147a32f62df420d21e66dad8acff59954a
backup_size_bytes: 4351156
backup_validation: gzip_test_passed
backup_scope: previous_stable_tracked_tree_only
rollback_ref: refs/heads/stable-backup/b660f7b-20260722-before-25a9585
rollback_commit: b660f7b6819dcca1f347d4634036353ca900c11a
```

No credential, token, cookie, browser state, private provider configuration, or
raw service/provider log was read.

## Replacement

The candidate was fetched from the local source repository into the stable
checkout and detached at the exact authorized commit. A source-bound wheel was
built without dependencies or build isolation, checked as a ZIP archive, and
retained with the backup material:

```yaml
validated_wheel: /home/jenn/tools/colameta-stable-backups/wheel-25a9585-20260722T123255Z/colameta-0.1.2-py3-none-any.whl
validated_wheel_sha256: 3866d637150ca8267a0d4148452e77292158462a58456e8d2c7554a12a64e4de
validated_wheel_size_bytes: 1395854
wheel_zip_validation: passed
stable_checkout_head: 25a95859b474e3ba76308dfdbc371c4b68c2b6f7
package_reinstall_result: success
```

The stable virtual environment was reinstalled directly from the exact stable
checkout with `--no-deps --force-reinstall --no-build-isolation`. Only the two
authorized services were restarted:

```yaml
service_state_after_restart:
  colameta-stable.service:
    active_state: active
    sub_state: running
    main_pid: 65855
  colameta-mcp-remote.service:
    active_state: active
    sub_state: running
    main_pid: 66400
```

No tunnel, DNS, OAuth, provider, or network configuration was changed during
the stable replacement.

## Runtime And MCP Acceptance

Web `127.0.0.1:8801`, Commander MCP `127.0.0.1:8766`, and external-OAuth MCP
origin `127.0.0.1:8767` all returned `ok=true`. Each endpoint reported:

```yaml
runtime_project_checkout_head: 25a95859b474e3ba76308dfdbc371c4b68c2b6f7
runtime_loaded_code_stale: false
reload_needed_for_verification: false
installed_package_matches_project_checkout: true
installed_package_verification_status: match
installed_package_project_source_clean: true
```

The stable Commander endpoint exposed exactly seven tools and completed a
read-only manifest-bound review acceptance:

```yaml
review_manifest_schema_published: true
template_status: template_ready
manifest_subject_count: 1
subject_page_count: 6
subject_sha256_verified: true
context_binding: matched
subject_hashes: matched
acceptance_commands_executed: false
side_effects: false
context_mismatch_negative_path: CONTEXT_BINDING_MISMATCH
```

## External Connector Status

The pre-existing public connector incident remains unresolved and is not hidden
by this receipt. The public health endpoint returned HTTP 530 and the existing
authenticated ChatGPT Apps connector returned an internal error after the
earlier tunnel restart/rollback. The stable local external-OAuth origin is
healthy, but public tunnel registration or hostname mapping still requires a
separate, explicitly authorized remediation and connector reconnect.

## Boundary

No push, tag, release, package publication, public App submission, executor
run, validation run through MCP, Git mutation through MCP, tunnel restart,
DNS change, OAuth/provider configuration change, credential read, or delivery
state mutation occurred. This receipt was created after the candidate commit
and remains untracked so it does not alter the exact deployed commit.
