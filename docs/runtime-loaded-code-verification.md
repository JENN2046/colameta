# Runtime Loaded-Code Verification

## Status

Status: v1.9+ read-only runtime/reload awareness.

`get_runtime_version_status` now reports whether the running ColaMeta MCP/Web process appears to be serving code loaded from the current project checkout, from a matching installed package, or from stale/unknown module sources. This is read-only proof only. It does not restart, reload, kill, apply, fetch, pull, push, tag, release, mutate service lifecycle state, mutate executor workflow state, mutate config, or mutate Git remote state.

## What Is Verified

The status result compares three independent pieces of evidence:

- The loaded runtime HEAD captured by the running process against the current project checkout HEAD read directly from local `.git` files.
- Import-time SHA-256 fingerprints for loaded `runner.*` Python modules against the current on-disk source files for those loaded modules.
- Installed package source files under runtime-relevant roots against the expected project checkout package-installable runtime file set when the process is loaded from `site-packages`.

For `/healthz` runtime provenance, the project checkout used for these runtime
fields is the loaded runtime source checkout, not necessarily the project being
served. When ColaMeta is running from a non-editable package install,
`direct_url.json` is used to recover the local source checkout that installed the
package, so `runtime_project_checkout_head` and source-clean/package-match fields
describe the stable runtime source rather than an unrelated served project.

The implementation uses direct filesystem reads and read-only local Git metadata checks. It does not use shell fallback, remote Git operations, service lifecycle operations, or executor workflow mutation.

## Operator Fields

Important fields added to `get_runtime_version_status`:

- `loaded_runtime_head`: the sanitized runtime HEAD captured by the process.
- `project_checkout_head`: the sanitized current checkout HEAD.
- `runtime_loaded_code_stale`: `true`, `false`, or `null` when the status cannot be proven.
- `reload_needed_for_verification`: `true` when an operator should treat a process reload/restart as needed before trusting loaded-code freshness.
- `reload_awareness_reason`: one of the machine-readable reasons below.
- `loaded_module_source_changed`: `true`, `false`, or `null` when loaded module source verification cannot be proven.
- `changed_loaded_modules`: loaded modules whose import-time SHA-256 differs from the current source file.
- `possibly_stale_surfaces`: read-only classification of surfaces that may be stale, such as MCP tool results, Web Console handlers, executor workflow code paths, or runtime observability.
- `loaded_module_verification`: detailed fingerprint verification evidence and limitations.
- `installed_package_verification`: detailed read-only comparison between the installed `colameta` package runtime files and the project checkout, when applicable, plus source-root cleanliness evidence for the runtime-relevant Git checkout paths.

## Behavior Matrix

| Evidence | `runtime_loaded_code_stale` | `reload_needed_for_verification` | `reload_awareness_reason` |
| --- | --- | --- | --- |
| Loaded runtime HEAD and project checkout HEAD are known and equal; loaded module fingerprints match current source | `false` | `false` | `loaded_code_verified_current` |
| Loaded runtime HEAD and project checkout HEAD are known and differ | `true` | `true` | `loaded_head_differs_from_project_head` |
| Runtime HEAD is unavailable because the process is loaded from an installed package, every expected project checkout package-installable runtime file exists in the installed package, no installed package runtime file exists outside the expected checkout file set, all compared files match, runtime source roots are clean against Git HEAD, and loaded module fingerprints remain verified | `false` | `false` | `installed_package_matches_project_checkout` |
| Runtime HEAD is unavailable and installed package runtime files match dirty source-root working-tree changes | `null` | `true` | `installed_package_project_checkout_dirty` |
| A loaded runner module source file changed after import | `true` | `true` | `loaded_module_source_changed` |
| Loaded runtime HEAD or project checkout HEAD is unknown | `null` | `true` | `unknown_runtime_or_checkout_head` |
| Loaded module fingerprints cannot be checked | `null` | `true` | `loaded_module_fingerprint_unknown` |

If multiple risks exist, the result remains fail-closed: `reload_needed_for_verification` is `true`, and the changed module or unknown evidence remains visible in the detailed fields.

## Worktree Cleanliness Limitation

This verification does not claim full Git worktree cleanliness. It does not scan every tracked or untracked file, and it does not prove that files outside the checked runtime roots are clean. It only proves one of these limited facts:

- The loaded runtime HEAD matches the current checkout HEAD and captured loaded module fingerprints still match their current source files.
- Or, for an installed package without a runtime `.git` directory, the installed package contains and matches every expected project checkout package-installable runtime file, contains no installed-only package-installable runtime files, and the runtime source roots are clean against Git HEAD.

Readiness gates may use installed-package provenance only when
`loaded_runtime_head` is unavailable. A reported `loaded_runtime_head` that
differs from the expected commit is stale running-code evidence and must not be
overridden by package or checkout fallback fields.

Installed package verification must not invent a Git HEAD for `site-packages`. It can clear `reload_needed_for_verification` only by proving file equivalence between the installed package and the expected package-installable project checkout file set for runtime-relevant roots, proving those source roots are clean against Git HEAD, and keeping loaded module fingerprints verified. Missing expected package files, extra installed package runtime files, dirty source roots, or unverified source-root cleanliness remain fail-closed; non-package operational files such as standalone shell scripts do not make a correct non-editable Python package look incomplete. That evidence is still weaker than full deployment authority and does not prove remote traceability by itself.

Changed loaded source files are classified as reload verification risk because the running process may still be using code imported before the edit.

Health endpoints expose only a short-TTL cached provenance summary. The cache key includes the runtime checkout identity, source-root cleanliness, a lightweight installed runtime package file-state stamp, and the TTL bucket, so packaged-runtime readiness evidence is not reused indefinitely across package changes.

## Non-Authorization Rule

The fields are observability signals only. A stale or unknown result can support an operator handoff notice, but it does not authorize an automatic restart, reload, kill, apply, service lifecycle mutation, executor workflow mutation, config mutation, or Git remote mutation.
