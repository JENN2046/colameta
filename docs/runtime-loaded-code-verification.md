# Runtime Loaded-Code Verification

## Status

Status: v1.9+ read-only runtime/reload awareness.

`get_runtime_version_status` now reports whether the running ColaMeta MCP/Web process appears to be serving code loaded from the current project checkout, from a matching installed package, or from stale/unknown module sources. This is read-only proof only. It does not restart, reload, kill, apply, fetch, pull, push, tag, release, mutate service lifecycle state, mutate executor workflow state, mutate config, or mutate Git remote state.

## What Is Verified

The status result compares three independent pieces of evidence:

- The loaded runtime HEAD captured by the running process against the current project checkout HEAD read directly from local `.git` files.
- Import-time SHA-256 fingerprints for loaded `runner.*` Python modules against the current on-disk source files for those loaded modules.
- Installed package source files under runtime-relevant roots against the same relative files in the project checkout when the process is loaded from `site-packages`.

The implementation uses direct filesystem reads. It does not use shell fallback, subprocesses, remote Git operations, service lifecycle operations, or executor workflow mutation.

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
- `installed_package_verification`: detailed read-only comparison between the installed `colameta` package runtime files and the project checkout, when applicable.

## Behavior Matrix

| Evidence | `runtime_loaded_code_stale` | `reload_needed_for_verification` | `reload_awareness_reason` |
| --- | --- | --- | --- |
| Loaded runtime HEAD and project checkout HEAD are known and equal; loaded module fingerprints match current source | `false` | `false` | `loaded_code_verified_current` |
| Loaded runtime HEAD and project checkout HEAD are known and differ | `true` | `true` | `loaded_head_differs_from_project_head` |
| Runtime HEAD is unavailable because the process is loaded from an installed package, installed package runtime files match the project checkout, and loaded module fingerprints remain verified | `false` | `false` | `installed_package_matches_project_checkout` |
| A loaded runner module source file changed after import | `true` | `true` | `loaded_module_source_changed` |
| Loaded runtime HEAD or project checkout HEAD is unknown | `null` | `true` | `unknown_runtime_or_checkout_head` |
| Loaded module fingerprints cannot be checked | `null` | `true` | `loaded_module_fingerprint_unknown` |

If multiple risks exist, the result remains fail-closed: `reload_needed_for_verification` is `true`, and the changed module or unknown evidence remains visible in the detailed fields.

## Worktree Cleanliness Limitation

This verification does not claim full Git worktree cleanliness. It does not scan every tracked or untracked file, and it does not prove that files outside the checked runtime roots are clean. It only proves one of these limited facts:

- The loaded runtime HEAD matches the current checkout HEAD and captured loaded module fingerprints still match their current source files.
- Or, for an installed package without a runtime `.git` directory, the installed package runtime files match the same relative files in the project checkout.

Installed package verification must not invent a Git HEAD for `site-packages`. It can clear `reload_needed_for_verification` only by proving file equivalence between the installed package and the project checkout for runtime-relevant roots while loaded module fingerprints remain verified. That evidence is still weaker than full deployment authority and does not prove remote traceability by itself.

Changed loaded source files are classified as reload verification risk because the running process may still be using code imported before the edit.

## Non-Authorization Rule

The fields are observability signals only. A stale or unknown result can support an operator handoff notice, but it does not authorize an automatic restart, reload, kill, apply, service lifecycle mutation, executor workflow mutation, config mutation, or Git remote mutation.
