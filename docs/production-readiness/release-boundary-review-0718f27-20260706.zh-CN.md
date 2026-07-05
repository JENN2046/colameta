---
receipt_type: production_readiness_boundary_review
receipt_id: production_readiness_boundary_review_0718f27_20260706
recorded_at_utc: 2026-07-05T16:43:40Z
project_name: colameta-self-dev
candidate_head: 0718f27bca6ee8f27f143e8af19aaef828c6f3db
candidate_short_head: 0718f27
result: private_beta_candidate_not_production_ready
---

# Production Readiness Boundary Review: 0718f27

## 结论

当前候选适合继续作为 Jenn 私有 ChatGPT Developer Mode / 私有 Beta 候选使用，
但不应宣称为成熟生产产品，也不应进入公开提交或多用户生产使用。

```yaml
private_developer_mode_use: ready_with_known_runtime_gap
private_beta_candidate: yes
stable_promotion_review_candidate: no
stable_production_ready: no
public_submission_ready: no
pyproject_status_change_recommended_now: no
```

不建议现在把 `pyproject.toml` 从 `Development Status :: 3 - Alpha` 改成 Beta。
推荐等 `get_stable_promotion_readiness` 达到
`stable_promotion_review_candidate`，并完成 release artifact、rollback
rehearsal、branch reconciliation 和安全审查后，再改为 Beta 或 RC。

## Release Notes

当前分支相对 `origin/main`：

```yaml
ahead_of_origin_main: 6
behind_origin_main: 1
origin_main_head: 822adac33f5dc15582d29e5236ad45f08a66857e
missing_from_candidate:
  - 822adac Merge pull request #3 from JENN2046/codex/project-agents-protocol
```

Candidate commits:

```text
0718f27 Track managed tunnel readiness artifacts
3d44a42 Record external OAuth ChatGPT closeout
8156c1e Add external OAuth resource server mode
8ebd8f1 Record remote HTTPS MCP closeout receipt
3cf9254 Fix remote MCP preflight user agent
7dc30f0 Add remote HTTPS MCP service guardrails
```

Functional summary:

- Adds `external-oauth` MCP resource server mode for Auth0-backed ChatGPT
  connector use.
- Adds HTTPS MCP preflight and remote closeout receipts.
- Adds managed tunnel service documentation, local user service template, and
  safe startup wrapper.
- Records stable replacement receipts that had previously remained untracked.
- Records Auth0 external-oauth + ChatGPT connector smoke closeout evidence.

## Permission Boundary

Current intended private connector boundary:

```yaml
public_mcp_endpoint: https://colameta-mcp.skmt617.top/mcp
local_origin: http://127.0.0.1:8767
auth_mode: external-oauth
idp: Auth0
oauth_resource: https://colameta-mcp.skmt617.top/mcp
scopes:
  - mcp:read
  - mcp:preview
  - mcp:commit
  - mcp:plan
```

Operational boundaries:

- Remote MCP must stay behind HTTPS and external OAuth.
- Web Console and stable MCP should stay loopback-only unless separately
  authorized.
- Public app submission is out of scope.
- Stable replacement, service restart, route transition, release, deploy, tag
  push, package publish, executor run, ReviewDecision, GateEvent, and Delivery
  accepted all require separate action-scoped authorization.
- Receipts and evidence must remain sanitized: no token, cookie, client secret,
  raw provider response, raw log, tunnel config, browser state, or `.env` value.

## Monitoring And Alerting Minimum

Before calling this production-ready, add or document an operator loop for:

- `systemctl --user show colameta-stable.service` active/running state.
- `systemctl --user show colameta-mcp-remote.service` active/running state.
- `systemctl --user show cloudflared-colameta-mcp-prod.service` active/running
  state.
- Public preflight:
  `.venv/bin/python scripts/remote_https_mcp_preflight.py https://colameta-mcp.skmt617.top`
- ChatGPT connector smoke packet with sanitized tunnel/control-plane evidence.
- Auth0 application/API configuration drift review, without exporting client
  secrets or raw logs.
- Backup freshness and rollback receipt availability.

Production alerting is not implemented by this packet. It defines the minimum
signals that a future monitor should collect and summarize.

## Backup And Recovery Minimum

Before stable replacement:

- Persist candidate artifact manifest and sha256.
- Create a new stable backup under `/home/jenn/tools/colameta-stable-backups`.
- Record backup path, backup sha256, previous stable head, target stable head,
  and exact service command.
- Rehearse rollback without modifying stable runtime.

Current read-only rehearsal found existing backup inventory, including:

```yaml
latest_stable_backup_observed: stable-before-98da7e0-20260705T173518+0800.tar.gz
latest_stable_backup_size_bytes: 13554367
```

## Security Review Minimum

Already improved:

- `external-oauth` uses Auth0 as the authorization server and verifies JWTs at
  the ColaMeta MCP resource server.
- `remote_https_mcp_preflight.py` reports endpoint shape and status without
  printing token, cookie, config, or logs.
- Closeout receipts record only sanitized status/reason/evidence fields.
- `.gitignore` now excludes `.env` and `.env.*`.
- Managed tunnel startup keeps keys out of command-line arguments.

Still required before production claim:

- Reconcile branch with `origin/main`.
- Re-run full CI on the final branch/PR.
- Verify runtime loaded-code freshness for the exact candidate head.
- Confirm Auth0 token endpoint auth method, callback URLs, allowed scopes, and
  per-app grants in a redacted configuration receipt.
- Confirm Cloudflare tunnel route and DNS through sanitized status only.
- Define incident response and rollback owner.
- Decide whether `mcp:commit` and `mcp:plan` should be available to ChatGPT by
  default or gated to a stricter connector/profile.

## Product Maturity Decision

```yaml
current_label: Alpha / private Beta candidate
recommended_external_label: Private beta
recommended_pyproject_classifier_now: keep Development Status :: 3 - Alpha
recommended_next_classifier_after_blockers_clear: Development Status :: 4 - Beta
```

Rationale:

- The core workflow and ChatGPT connector are functioning.
- Test and smoke evidence are strong for a small private system.
- Production service promotion is still blocked by runtime freshness evidence.
- Public/multi-user product obligations are not complete.
