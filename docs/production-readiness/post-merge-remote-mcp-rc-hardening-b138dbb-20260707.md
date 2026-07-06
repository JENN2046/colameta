# Post-Merge Closeout Receipt: Remote MCP RC Hardening

date: 2026-07-07
recorded_at_utc: 2026-07-06T17:31:33Z
recorded_at_local: 2026-07-07T01:31:33+0800
receipt_type: post_merge_remote_mcp_rc_hardening_closeout
secret_handling: no_token_no_cookie_no_client_secret_no_env_values_no_logs

## Summary

PR #7 was merged into `main` and the local development checkout was
fast-forwarded to the merged `origin/main` head.

```yaml
pr_number: 7
pr_title: "[codex] harden remote MCP RC boundaries"
pr_url: https://github.com/JENN2046/colameta/pull/7
pr_state: MERGED
base_branch: main
head_branch: codex/remote-mcp-rc-hardening
merged_at_utc: 2026-07-06T17:27:24Z
merged_by: JENN2046
merge_commit: b138dbb43bc6a1b7c8f17d250d80761462e6125d
local_main_head_after_fast_forward: b138dbb43bc6a1b7c8f17d250d80761462e6125d
origin_main_head_after_fetch: b138dbb43bc6a1b7c8f17d250d80761462e6125d
```

## Scope Closed

This closeout covers the RC hardening batch for remote HTTPS MCP and
`external-oauth` resource-server operation.

Closed items:

- external OAuth configured scopes are enforced as a server-side allowlist.
- `external-oauth` remote public access is read/preview-only by default.
- `mcp:commit` and `mcp:plan` are denied for remote public OAuth callers.
- Durable project-memory, todo, decision, and runner-record mutations are
  scoped as `mcp:commit`, not `mcp:preview`.
- MCP request body size and request timeout boundaries are enforced.
- MCP rate-limit bucket growth is bounded and random unauthenticated paths are
  normalized.
- `prompt_to_plan` workflow policy mapping is covered by a matrix regression
  test.
- Git remote push branch and remote allowlist policy is enforced.
- Legacy acceptance command execution no longer uses `shell=True`.
- Project patch apply uses file transaction rollback semantics.

## Review Thread Closeout

```yaml
review_thread_id: PRRT_kwDOTFFH1c6OqqLx
finding: "Deny preview-scoped writes for external OAuth"
resolution: resolved
resolved_by: JENN2046
resolved_with_commit: 70b5462784819721d3141195655ee4074b2af029
```

## GitHub CI Evidence

Latest PR #7 checks before merge:

```yaml
python_3_10: pass
python_3_11: pass
python_3_12: pass
python_3_13: pass
python_3_14: pass
quality_gates: pass
```

## Post-Merge Local Smoke

After switching to `main` and fast-forwarding to `origin/main`, the following
local smoke checks passed:

```yaml
compileall_adapters_runner_schemas_scripts_tests: pass
targeted_mcp_policy_rate_limit_tests: "11 passed"
service_auth_baseline_tests: "6 passed"
full_pytest: "743 passed, 55 subtests passed"
self_hosting_smoke: pass
git_diff_check: pass
worktree_clean_after_smoke: true
```

## Boundary

This receipt did not read or record tokens, cookies, client secrets, private
keys, `.env` values, browser state, tunnel configuration, provider auth config,
private runtime state, raw provider responses, or raw logs.

This closeout did not:

- tag a release;
- publish a package;
- deploy;
- replace stable runtime;
- restart tunnel or stable services;
- mutate Cloudflare, Auth0, DNS, provider, proxy, or tunnel configuration;
- write Delivery accepted, ReviewDecision, or GateEvent.

## Remaining Decisions

This receipt records merge and local smoke closure only. It does not authorize
production promotion, public app submission, package release, tag push, stable
runtime replacement, or executor/validation command execution through the public
ChatGPT connector.
