# ColaMeta Remote MCP RC Hardening Receipt

date: 2026-07-06
receipt_type: remote_mcp_rc_hardening
secret_handling: no_token_no_cookie_no_client_secret_no_env_values_no_logs

## 结论

本记录对应第三轮代码审查后的 RC 硬化批次。目标是收窄公网
`external-oauth` MCP 的授权边界，并补齐基础请求体和 Git remote policy
防护。

本批次完成后，远端 HTTPS MCP 的默认建议仍是：

```text
mcp:read
mcp:preview
```

`external-oauth` remote public 模式是 read/preview-only。`mcp:commit` 与
`mcp:plan` 在 OAuth scope 验证后、工具 handler 执行前默认拒绝。

## 已实施边界

1. `external-oauth` configured scopes 成为服务端最终 allowlist。

   JWT token 中携带的 scope 必须同时存在于服务端 configured scopes 中，才会
   通过 `validate_scope()`。

2. `external-oauth` 增加 `remote_public` tool policy。

   该 policy 在 OAuth scope 验证之后、工具执行之前生效。它允许
   `mcp:read` / `mcp:preview`，并默认拒绝所有 `mcp:commit` / `mcp:plan`
   远端动作。

3. `/mcp` JSON-RPC 与 OAuth endpoint 请求体增加统一 hard cap。

   超限请求返回 `MCP_REQUEST_TOO_LARGE`，避免在公网入口无界读取请求体。

4. Git remote push 增加 branch/remote policy。

   默认只允许 `origin` 上的 `codex/*` 分支，拒绝 `main`、`master`、
   `production`、`release/*`、`v*` 以及非 allowlist 分支。

5. Legacy acceptance command 执行路径移除 `shell=True`。

   `ShellAdapter` 现在把命令解析为 argv，拒绝 shell 操作符和非 allowlist
   executable，再用 `shell=False` 执行。

## 验证覆盖

新增或更新的测试覆盖：

- configured scope allowlist 收窄；
- token 额外携带 `mcp:commit` 时仍被服务端拒绝；
- remote policy 拒绝 Git remote apply；
- remote policy 拒绝 executor run 和 validation run；
- remote policy 拒绝 `mcp:plan`；
- 非高危 commit 工具也会被 policy 拒绝；
- `/mcp` JSON-RPC 超大请求体返回 `MCP_REQUEST_TOO_LARGE`；
- Git remote policy 拒绝 protected branch 和非 allowlist branch；
- Git remote `push_apply` 重新检查 protected branch policy；
- `codex/*` branch 可以进入原有 push preview 流程。
- acceptance command 拒绝 shell 操作符且不会执行后续副作用；
- acceptance command 拒绝非 allowlist executable；
- allowlist 内的 argv 命令可正常执行。

## 剩余限制

这不是生产上线许可。本批次仍不授权：

- public app submission；
- stable service replacement；
- release/tag/package publish；
- Git push 到 protected/release/main 分支；
- executor/validation command execution through public ChatGPT connector；
- provider profile mutation through public ChatGPT connector。
