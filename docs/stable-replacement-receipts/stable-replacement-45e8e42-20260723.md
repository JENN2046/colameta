# Stable replacement receipt — 45e8e42

Date: 2026-07-23T12:57:15+08:00

## Result

`PASSED`

## Candidate and rollback

```text
previous stable HEAD: 97d99b4bc9bfb2bd7e87048cda135effba24006f
candidate stable HEAD: 45e8e42bbcfdee4fa47ff9890cfd84a412ff00bf
rollback ref: stable-backup/97d99b4-20260723-artifact-page-compat
backup archive: /home/jenn/tools/colameta-stable-backups/stable-before-45e8e42-20260723T130000Z.tar.gz
backup archive SHA-256: e97564ae5b6512bf4f31634a6dbf08f052d3d1a2b376e0bde6aa11fb1cb32835
```

The archive was created from the prior stable tracked tree, verified with
`gzip -t`, and the rollback ref resolves to the prior exact commit.

## Candidate verification before promotion

```text
targeted artifact/context/OAuth pytest: 94 passed
MCP and Commander regression set: 388 passed, 3 warnings, 3 subtests passed
compileall: passed
full pytest: 1962 passed, 2 skipped, 3 warnings, 142 subtests passed
self-hosting smoke: passed
git diff --check: passed
```

The full pytest run used `PYTHONDONTWRITEBYTECODE=1` after clearing only the
local `.venv` bytecode cache required by the closeout environment check.

## Stable runtime verification

Both `colameta-stable.service` and `colameta-mcp-remote.service` were restarted
and returned `active`.

The local and public `/healthz` runtime facts reported:

```text
runtime_project_checkout_head: 45e8e42bbcfdee4fa47ff9890cfd84a412ff00bf
runtime_loaded_code_stale: false
reload_needed_for_verification: false
installed_package_matches_project_checkout: true
installed_package_verification_status: match
installed_package_project_source_clean: true
```

`scripts/remote_https_mcp_preflight.py` against the public HTTPS MCP endpoint
with `--expected-head 45e8e42bbcfdee4fa47ff9890cfd84a412ff00bf` passed with no
failures.

## Real ChatGPT artifact recovery acceptance

A live ChatGPT App `manage_git history_show` call produced a `packaged=true`
result with eight pages. The existing seven-tool `run_mcp_workflow` surface then
read every page through:

```text
workflow=result_artifact
phase=read
artifact_page=1..8
```

Acceptance facts:

```text
page lengths: 12000, 12000, 12000, 12000, 12000, 12000, 12000, 4286
same opaque artifact ID across pages: true
same expiry across pages: true
same advertised SHA-256 across pages: true
read_only=true and side_effects=false across pages: true
reconstructed JSON: true
advertised SHA-256: b48ff0fa74e52feba050bf492297ac50f7a290c098abde532a92071d1bfd8e2f
recomputed SHA-256: b48ff0fa74e52feba050bf492297ac50f7a290c098abde532a92071d1bfd8e2f
SHA-256 matched: true
```

No executor, validation, Git mutation, delivery transition, push, or stable
replacement authority was granted by the artifact-page call.

## Fresh ChatGPT schema discoverability confirmation

In a newly opened ChatGPT conversation, the caller invoked:

```text
run_mcp_workflow(workflow=result_artifact, phase=read)
```

without an `artifact_id`. The server returned the expected fail-closed error:

```text
RESULT_ARTIFACT_ID_REQUIRED
```

This proves the fresh ChatGPT tool schema accepts `result_artifact` as a valid
workflow enum value. No write was performed.

## Delivery boundary

This receipt is intentionally untracked evidence. No Git push, tag, release,
or external account configuration change was performed.
