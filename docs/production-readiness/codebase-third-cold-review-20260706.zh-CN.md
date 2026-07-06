# ColaMeta 第三轮外部视角代码审查报告

date: 2026-07-06
review_type: code_only_cold_review_third_pass
reviewer_position: external_large_model_code_reviewer
language: zh-CN
secret_handling: no_token_no_cookie_no_client_secret_no_env_values_no_logs
git_branch_observed: codex/stable-replacement-4ff9168-receipt
write_scope: report_only

## 0. 结论

第三轮审查的结论比前两轮更明确：

ColaMeta 已经具备一个可运行的私有 Agent 控制平面形态，并且代码里有大量真实安全意识：OAuth/JWT 验证、preview/apply、Git 状态校验、executor claim、TTL、Web Console dangerous confirmation、输出脱敏等都不是装饰。

但从公网 HTTPS MCP 产品视角，它还不能称为成熟生产产品，也不应该进入通用生产交付。当前最硬的问题不是功能缺失，而是远端 MCP 一旦获得 `mcp:commit`，就拥有过大的真实本机副作用能力；同时 `external-oauth` 的本机 scope 配置没有被服务端当作最终 allowlist 强制执行。

外部判定：

```text
product_state: private_alpha_or_controlled_pilot
production_ready: false
rc_ready: false
main_blocker_class: remote_authorization_boundary_too_wide
```

在修复本文 P0 之前，只建议把远端 ChatGPT connector 限定为：

```text
mcp:read
mcp:preview
```

不要默认开放：

```text
mcp:commit
mcp:plan
```

## 1. 审查范围

本轮审查只看代码和测试，不以项目说明、愿景文档、介绍文本作为成熟度依据。

重点路径：

- `external-oauth` resource server。
- MCP tool scope enforcement。
- `mcp:commit` 下的真实副作用能力。
- Git remote push/apply。
- executor run/apply。
- HTTP MCP 请求读取。
- 相关测试覆盖。

本轮没有读取：

- token
- cookie
- client secret
- `.env` 值
- 私钥
- 浏览器状态
- provider 原始日志
- tunnel 配置明文

## 2. P0 发现：external-oauth 的 configured scopes 未作为服务端 allowlist 强制执行

### 证据

`ExternalOAuthConfig` 有 `scopes` 配置：

- `runner/mcp_external_oauth.py:21`
- `runner/mcp_external_oauth.py:26`

Provider 初始化时保存了 `self.scopes`：

- `runner/mcp_external_oauth.py:40`

metadata 会公布 `scopes_supported`：

- `runner/mcp_external_oauth.py:45`
- `runner/mcp_external_oauth.py:51`

但真正的授权判断只检查 token payload 里是否存在 required scope：

- `runner/mcp_external_oauth.py:81`
- `runner/mcp_external_oauth.py:82`

当前逻辑等价于：

```text
required_scope in token_scopes
```

缺少：

```text
required_scope in configured_server_allowed_scopes
and required_scope in token_scopes
```

### 影响

这意味着 `--oauth-scopes` 或全局 `oauth_scopes` 当前更像 metadata 声明，而不是服务端最终授权边界。

如果本机服务配置为只公开：

```text
mcp:read,mcp:preview
```

但 Auth0 access token 因应用权限、误配置或未来策略变化携带了：

```text
mcp:commit
```

服务端仍会接受这个 token 对 `mcp:commit` 工具的调用。

这是生产级 OAuth resource server 的硬缺陷，因为 resource server 必须保有自己的最终权限收口，而不能完全信任 IdP 返回的 scope 集合。

### 风险等级

```text
severity: P0
blocker_for: Beta/RC/production
exploitability: configuration_or_idp_scope_misgrant
blast_radius: local_file_write_git_push_executor_run_state_mutation
```

### 修复要求

把 `ExternalOAuthProvider.validate_scope()` 改为同时要求：

```text
required_scope in self.scopes
required_scope in extracted_token_scopes
```

并增加测试：

```text
configured scopes: mcp:read,mcp:preview
token scopes: mcp:read,mcp:preview,mcp:commit
required: mcp:commit
expected: false
```

## 3. P0 发现：mcp:commit 是真实本机副作用权限，external-oauth 没有本机二次确认

### 证据

OAuth scope enforcement 位于：

- `runner/mcp_server.py:6131`
- `runner/mcp_server.py:6144`
- `runner/mcp_server.py:6145`
- `runner/mcp_server.py:6147`

逻辑是：如果 OAuth provider 的 `validate_scope(token_payload, required_scope)` 返回 true，则放行工具执行。

Cloud Relay 有本地确认拦截：

- `runner/cloud_agent_client.py:158`
- `runner/cloud_agent_client.py:166`
- `runner/cloud_agent_client.py:172`
- `runner/cloud_agent_client.py:175`

但这条本地确认机制只存在于 cloud-relay bridge，不覆盖 `external-oauth` 的 HTTP MCP 路径。

`manage_git_remote` 的 `push_apply` 属于 `mcp:commit`：

- `runner/mcp_server.py:5832`
- `runner/mcp_server.py:5840`
- `runner/mcp_server.py:5843`

`push_apply` 最终执行真实 git push：

- `runner/mcp_git_remote.py:163`
- `runner/mcp_git_remote.py:224`
- `runner/mcp_git_remote.py:234`

executor workflow 的 `run_once` 属于 `mcp:commit`：

- `runner/mcp_server.py:6019`
- `runner/mcp_server.py:6025`
- `runner/mcp_server.py:6032`

`run_once` 会启动本地后台 worker：

- `runner/mcp_executor_workflow.py:623`
- `runner/mcp_executor_workflow.py:765`
- `runner/mcp_executor_workflow.py:812`

### 影响

`mcp:commit` 不是普通写权限。它覆盖：

- 文件 apply。
- Git commit 类操作。
- Git remote push。
- validation run。
- executor workflow run。
- state mutation apply。
- closeout/state lineage apply。

从外部产品视角，这些都是高危本机副作用。只用 OAuth scope 作为唯一确认机制，不足以支撑公网生产 connector。

尤其是 ChatGPT connector 场景下，用户授权体验和工具调用执行之间没有本地 operator confirmation。只要 connector 获得 `mcp:commit`，远端模型就可能在合法 token 下触发本机写操作。

### 风险等级

```text
severity: P0
blocker_for: production_default_connector
blast_radius: local_project_mutation_git_remote_mutation_executor_dispatch
```

### 修复要求

生产默认策略应改为：

```text
remote_public_default_scopes:
  - mcp:read
  - mcp:preview
```

对 `mcp:commit` / `mcp:plan` 至少需要一个额外闸：

- 本机一次性 confirmation token。
- 本机 operator approve queue。
- per-tool dangerous action confirmation。
- 独立非 ChatGPT 的 trusted operator channel。
- 或远端服务模式直接禁用 commit/plan tool surface。

## 4. P1 发现：/mcp JSON-RPC 请求体没有统一大小上限

### 证据

HTTP body 读取直接按 `Content-Length` 读入：

- `runner/mcp_server.py:3818`
- `runner/mcp_server.py:3821`
- `runner/mcp_server.py:3826`

Actions REST tool path 有请求大小检查：

- `runner/mcp_server.py:4011`
- `runner/mcp_server.py:4012`
- `runner/mcp_server.py:5370`
- `runner/mcp_server.py:5377`

但 `/mcp` JSON-RPC path 直接调用 `_read_json_body()`：

- `runner/mcp_server.py:4062`
- `runner/mcp_server.py:4066`

没有同等大小检查。

### 影响

公网 HTTPS MCP 下，攻击者或误用客户端可以发送超大 `Content-Length` 请求，导致服务线程直接读入内存。即使 OAuth 后置失败，读取行为本身也会消耗资源。

这不是复杂漏洞，是基础资源控制缺口。

### 风险等级

```text
severity: P1
blocker_for: public_internet_production
blast_radius: memory_pressure_thread_exhaustion_slow_request_pressure
```

### 修复要求

统一实现：

- 全路径 request body hard cap。
- 超限返回 `413 Payload Too Large` 或项目统一错误码。
- 对 `/mcp`、`/token`、`/register`、Actions REST 路径一致生效。
- 增加测试覆盖 JSON-RPC `/mcp` 超限。

## 5. P1 发现：Git remote push 有状态校验，但缺少生产级 branch/remote policy

### 正面证据

Git remote manager 已有不少有效防护：

- preview_id 校验与 TTL：
  - `runner/mcp_git_remote.py:163`
  - `runner/mcp_git_remote.py:188`
- HEAD / branch / upstream 变化检查：
  - `runner/mcp_git_remote.py:1082`
  - `runner/mcp_git_remote.py:1095`
  - `runner/mcp_git_remote.py:1104`
  - `runner/mcp_git_remote.py:1113`
- 工作区阻断性脏状态检查：
  - `runner/mcp_git_remote.py:1122`
- behind 检查：
  - `runner/mcp_git_remote.py:1131`
- ahead 数量检查：
  - `runner/mcp_git_remote.py:1140`
- 非 force push：
  - `runner/mcp_git_remote.py:234`

### 缺口

`_build_status_blockers()` 没有看到 protected branch / release branch / production branch policy：

- `runner/mcp_git_remote.py:917`
- `runner/mcp_git_remote.py:947`

`push_apply` 最终仍会执行：

```text
git push <remote_name> HEAD:<upstream_branch>
```

对应代码：

- `runner/mcp_git_remote.py:234`

当前代码保护的是“状态一致”和“非强推”，不是“生产分支策略”。

### 影响

如果当前 branch/upstream 指向高风险分支，MCP 远端在 `mcp:commit` 下可以合法触发 push。GitHub 保护分支可能挡住一部分，但产品不能把安全边界外包给远端 Git 托管平台。

### 风险等级

```text
severity: P1
blocker_for: remote_commit_scope_enablement
```

### 修复要求

增加服务端 Git remote policy：

- deny branch: `main`, `master`, `production`, `release/*`, `v*`。
- allow branch pattern: `codex/*` 或项目配置 allowlist。
- remote allowlist: 默认只允许经过配置的 non-production delivery remote。
- push 前输出 policy decision receipt。
- 测试：protected branch push preview/apply 必须 fail closed。

## 6. P2 发现：测试没有覆盖关键生产误配路径

### 证据

external OAuth 测试覆盖了 JWT 基础验证：

- `tests/test_mcp_external_oauth.py:62`
- `tests/test_mcp_external_oauth.py:73`
- `tests/test_mcp_external_oauth.py:79`
- `tests/test_mcp_external_oauth.py:94`

但当前测试还接受 token 中的 `permissions=["mcp:commit"]`：

- `tests/test_mcp_external_oauth.py:102`
- `tests/test_mcp_external_oauth.py:106`
- `tests/test_mcp_external_oauth.py:111`

没有覆盖：

```text
configured server scopes exclude mcp:commit
token includes mcp:commit
validate_scope(payload, "mcp:commit") must be false
```

也没有看到 `/mcp` JSON-RPC request body 超限测试。

### 影响

当前测试能证明“token 声明了 scope 时可以识别”，但不能证明“服务端配置能收窄远端能力”。这正是生产 OAuth resource server 最关键的防误配能力。

### 修复要求

新增至少这些测试：

1. `external_oauth_configured_scopes_are_enforced_as_allowlist`
2. `external_oauth_commit_scope_rejected_when_not_configured`
3. `mcp_jsonrpc_request_body_too_large_rejected_before_parse`
4. `remote_mcp_commit_scope_requires_local_confirmation_or_policy`
5. `manage_git_remote_push_apply_rejects_protected_branch`

## 7. 正面评价

第三轮不是全盘否定。项目已经有很多成熟工程的影子：

### 7.1 Web Console 安全边界比 MCP 远端边界更成熟

Web Console 明确屏蔽 remote git mutation：

- `runner/web_console.py:193`
- `runner/web_console.py:207`

测试覆盖：

- `tests/test_web_console_security.py:116`
- `tests/test_web_console_security.py:123`
- `tests/test_web_console_security.py:127`

### 7.2 Git remote manager 不是裸 push

它有 preview、TTL、HEAD 不变、upstream 不变、dirty check、behind check、非 force push、输出脱敏。

这说明代码作者知道 Git remote mutation 是高风险行为，只是还没有把这种谨慎提升为公网 MCP 产品策略。

### 7.3 Executor workflow 有 preview/claim/heartbeat

`run_once` 不是无条件同步裸跑。它需要 preview、claim，并启动后台 worker，后续有 heartbeat/finalize。

这说明执行器系统已经接近“受控调度”的形态，但远端授权边界仍然过宽。

### 7.4 external-oauth 方向正确

JWT issuer、audience/resource、exp、JWKS、algorithm、scope claim 的基础验证方向正确。问题不是选错 IdP，而是 resource server 自身还缺最终权限收口。

## 8. 产品成熟度判断

| 维度 | 判断 |
|---|---|
| 本地开发使用 | 可用 |
| 私有 ChatGPT connector smoke | 可用 |
| 受控单人试运行 | 可用，但应 read/preview only |
| 团队内部 Beta | 未达标 |
| 公网生产 | 未达标 |
| 可交付成熟产品 | 未达标 |

当前更准确的定位：

```text
ColaMeta is a working private agent-control-plane prototype with strong safety intent,
but not yet a production-grade remote MCP product.
```

中文判断：

```text
这是一个已经跑通真实链路、工程安全意识很强的私有 Agent 控制平面原型；
但它还不是成熟生产产品。
```

## 9. 最小整改顺序

### Step 1：修 external-oauth scope allowlist

目标：

```text
configured_scopes must be enforced server-side
```

验收：

```text
configured=mcp:read,mcp:preview
token=mcp:read,mcp:preview,mcp:commit
required=mcp:commit
result=false
```

### Step 2：远端服务默认降权

目标：

```text
public ChatGPT connector default scopes = mcp:read,mcp:preview
```

`mcp:commit` 和 `mcp:plan` 需要独立授权模式。

### Step 3：为 commit/plan 增加本机确认或 policy gate

至少覆盖：

- Git push。
- executor run。
- validation run。
- file apply。
- state mutation apply。
- closeout apply。

### Step 4：统一 HTTP body limit

覆盖：

- `/mcp`
- Actions REST tool paths
- `/register`
- `/token`
- `/revoke`

### Step 5：Git remote policy

默认拒绝：

- `main`
- `master`
- `production`
- `release/*`
- tag push
- force push

默认只允许安全交付分支。

### Step 6：补测试

优先补 P0/P1 的 negative-path tests。

## 10. 推荐状态标签

在 P0 修复前：

```text
status_label: Alpha
public_claim: controlled private preview
production_claim: not_allowed
```

P0 修复、远端默认 read/preview、body limit 完成后：

```text
status_label: Beta candidate
public_claim: private beta for read/preview workflows
production_claim: still_requires_security_review
```

只有在 commit/plan 本机确认、Git branch policy、HTTP hardening、监控告警、备份恢复演练都完成后，才考虑：

```text
status_label: RC
```

## 11. 本轮审查产物状态

本报告只记录代码审查判断，不代表 release acceptance，不代表 stable promotion acceptance，不代表生产上线许可。

本报告不包含：

- token
- cookie
- client secret
- private key
- `.env` 值
- provider 日志
- tunnel 配置明文

本报告包含的路径和行号均来自代码静态审查。
