# Stable Replacement Receipt — 2b98c59

Date: 2026-07-22

## Authorization and target

- Authorization: Jenn explicitly authorized a new stable replacement after the manifest resource-template implementation and regression tests.
- Source commit: `2b98c59481b7e2ffcf791b801ef1864dcaf444c6` (`feat(mcp): advertise review resource templates`).
- Replaced stable commit: `25a95859b474e3ba76308dfdbc371c4b68c2b6f7`.
- Source and stable checkouts were confirmed at the source commit after replacement.

## Delivered behavior

The MCP server now advertises three static, parameterized review-resource URI shapes through `resources/templates/list`:

1. review manifest;
2. manifest subject;
3. manifest subject page.

The response contains only static protocol shapes. It does not expose live manifest handles, project paths, or subject contents. Existing read-time capability, context, path, HEAD, and hash checks remain authoritative.

## Pre-replacement validation

| Check | Result |
| --- | --- |
| Targeted MCP/review/canary tests | `67 passed` |
| Focused Ruff and compileall | passed |
| Full test suite | `1942 passed, 2 skipped, 142 subtests passed` |
| Self-hosting smoke | passed |
| Agent-consumer smoke | passed |
| Full Ruff | passed |
| `git diff --check` | passed |
| Direct local `resources/templates/list` probe | three expected static templates returned |

The first full-suite attempt detected `.pyc` files that a prior compile check had written inside the disposable virtual environment. Those files were removed only from the explicit virtual-environment path, then the suite was rerun with bytecode writing disabled and passed.

## Backup and rollback

- Pre-replacement tracked-tree archive: `/home/jenn/tools/colameta-stable-backups/stable-before-2b98c59-20260722T130937Z.tar.gz`
- Archive SHA-256: `bdba132c315231c39a11449182641fee8bee7c9264c7d116d3eab761159a3d8c`
- Archive integrity check: passed
- Retained candidate wheel: `/home/jenn/tools/colameta-stable-backups/wheel-2b98c59-20260722T130937Z/colameta-0.1.2-py3-none-any.whl`
- Wheel SHA-256: `11bf4f52f13907b8ee4218bb3c0ae4fde071c08bf9633e29abe79b4292d707e3`
- Wheel archive integrity check: passed
- Rollback ref: `stable-backup/25a9585-20260722-before-2b98c59`

## Replacement and runtime acceptance

- Stable checkout moved to the exact source commit.
- The stable virtual environment was reinstalled from that checkout without dependencies or network resolution.
- `colameta-stable.service` and `colameta-mcp-remote.service` were restarted and active.
- Health endpoints on the stable API, remote MCP, and local MCP all returned HTTP 200.
- Runtime observability reported the expected commit, no stale loaded code, no verification reload needed, and an installed package matching the checkout.
- Commander exposure remained the expected seven tools.
- A direct local MCP acceptance created a bound review manifest, enumerated all six subject pages, and verified the bound context and source hashes. No acceptance command was run.

## ChatGPT App observation

The actual ChatGPT App reached the new commit and successfully created a valid hash-bound manifest. A deliberately stale source hash was rejected as `REVIEW_MANIFEST_SUBJECT_HASH_MISMATCH`, then the current source hash was accepted.

After the required post-deployment App refresh, a fresh actual-App manifest was created successfully and `phase=verify` reported matched context and subject hashes. The generic App resource proxy nevertheless returned `Unknown resource` for both the manifest root URI and its subject URI. The local MCP server accepts the same URI shapes and passed six-page read/verify acceptance, so the remaining gap is specifically the App resource-proxy handling of dynamic resource templates. It is not a hash-binding, context-binding, or runtime-version failure.

## Boundaries observed

- No source push, tag, release, package publication, credential inspection, tunnel/DNS change, or external-network binding was performed as part of this replacement.
- This receipt is intentionally local and untracked pending any separate documentation-delivery decision.
