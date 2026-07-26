# Stable Replacement Receipt — b53e47c

Date: 2026-07-22

## Authorization and target

- Authorization: Jenn explicitly authorized the manifest-read compatibility implementation, commit, and a new stable replacement.
- Source commit: `b53e47cde7c2ff45a3f4313846f0d4bb6a0f9946` (`feat(mcp): add manifest read compatibility`).
- Replaced stable commit: `2b98c59481b7e2ffcf791b801ef1864dcaf444c6`.
- Stable checkout was confirmed at the exact source commit after replacement.

## Delivered behavior

`run_mcp_workflow(workflow="review_manifest", phase="read")` is a read-only compatibility route for ChatGPT hosts whose generic resource proxy does not route dynamic resource-template URIs.

- It remains inside the existing seven-tool Commander surface.
- It requires the short-lived inspect-issued manifest ID, a manifest-declared subject index, and a bounded page number.
- Every call rechecks the project context and the selected subject SHA-256 before returning text.
- Inspect returns an exact typed `read_call`; each non-final page returns the next bound call.
- Standard `resources/templates/list` and `resources/read` remain available for MCP clients that support dynamic template URIs.

## Pre-replacement validation

| Check | Result |
| --- | --- |
| Targeted manifest/Commander/policy/canary tests | `142 passed` |
| Focused Ruff and compileall | passed |
| Full test suite | `1944 passed, 2 skipped, 142 subtests passed` |
| Self-hosting smoke | passed |
| Agent-consumer smoke | passed |
| Full Ruff | passed |
| `git diff --check` | passed |

Regression coverage includes full page reconstruction, page and subject bounds, subject-hash failure after mutation, service-mode project routing, read-scope declaration, and exact ChatGPT Commander content preservation for a manifest-authorized subject.

## Backup and rollback

- Pre-replacement tracked-tree archive: `/home/jenn/tools/colameta-stable-backups/stable-before-b53e47c-20260722T133759Z.tar.gz`
- Archive SHA-256: `53f3304865987c93cbb01337d1f7f5530e855a1340880a546470173f4eb5424d`
- Archive integrity check: passed
- Retained candidate wheel: `/home/jenn/tools/colameta-stable-backups/wheel-b53e47c-20260722T133759Z/colameta-0.1.2-py3-none-any.whl`
- Wheel SHA-256: `e03b046fe91b93e563cbbc015512b73dc54115afed4cf7f081cbe4ae96099acc`
- Wheel archive integrity check: passed through Python's standard zip verifier
- Rollback ref: `stable-backup/2b98c59-20260722-before-b53e47c`

## Replacement and local runtime acceptance

- Stable checkout moved to the exact source commit.
- The stable virtual environment was force-reinstalled from the retained exact candidate wheel without dependency resolution.
- `colameta-stable.service` and `colameta-mcp-remote.service` were restarted and active.
- Stable API, Commander MCP, and remote MCP health endpoints returned HTTP 200.
- The stable status command reported `installed_package_matches_project_checkout=true`, `runtime_loaded_code_stale=false`, and `reload_needed_for_verification=false` for the stable checkout.
- The generic healthz projection remained conservative (`unknown_runtime_or_checkout_head`) because its listener runtime-root provenance was not injected; this did not override the stable status result or direct protocol acceptance.
- Direct local Commander MCP confirmed the exact seven tools, all three static resource templates, a six-page compatibility read, full content SHA-256 reconstruction, and final context/hash verification.

## Actual ChatGPT App acceptance

The real App reached `b53e47c` and completed the intended compatibility flow:

1. `review_manifest inspect` returned the current binding template.
2. A fresh external manifest for `docs/USAGE.md` was accepted with one subject and six pages.
3. The App invoked the returned `read_call` for pages 1 through 6. Every page reported matched context and subject hash; the next-page continuation was present.
4. `review_manifest verify` returned matched context, matched subject hashes, and one verified subject.

The generic App `resources/read` still returned `Unknown resource` for the valid dynamic manifest URI. This is the observed proxy limitation that the new typed compatibility phase addresses; it is not treated as a passing generic-resource acceptance.

## Boundaries observed

- No source push, tag, release, package publication, credential inspection, tunnel/DNS change, or external-network binding was performed.
- No executor, validation command, commit, push, ReviewDecision, GateEvent, or delivery-acceptance action was authorized by the read workflow.
- This receipt is intentionally local and untracked pending any separate documentation-delivery decision.
