# ColaMeta 代码深度冷评估报告

Date: 2026-07-06
Scope: ColaMeta codebase, static code review only
Review stance: external model perspective, code-first, documentation-independent
Result: FINDINGS_ONLY

## 1. 冷结论

ColaMeta 的核心价值是真实的，但当前不能被称为成熟生产产品。

它更准确的定位是：一个已经跑通真实使用链路、具备强烈安全意识的自托管 Agent 控制平面原型。它能够把 ChatGPT/MCP 调用、本地项目、Git、patch、executor、runtime、receipt 和 stable promotion 流程连接起来，并提供 preview、scope、confirmation、evidence、redaction 等护栏。

但从代码外部视角看，项目现在的主要风险不是“功能不够”，而是“能力太强、边界太多、实现太集中”。远端 MCP 入口、本地执行能力、Git/patch 写能力、Web Console、OAuth、CLI 和状态治理都挤在几个大型 Python 控制器里。安全机制存在，但分散、手工同步、多轨并存。

因此：

- 个人本地使用：可用 Alpha。
- 单一可信操作者 dogfood：可控早期 Beta。
- ChatGPT HTTPS 远端 MCP：可以受控试运行。
- 多用户、企业、SaaS、长期无人值守生产：不够格。

## 2. 代码规模与结构事实

静态结构扫描结果：

- `runner/`、`adapters/`、`scripts/`、`schemas/` Python 代码约 95,695 行。
- `tests/` 约 16,419 行，71 个顶层 `test_*.py` 文件。
- 最大文件：
  - `runner/mcp_server.py`: 10,732 行。
  - `runner/core_orchestrator.py`: 5,076 行。
  - `runner/mcp_executor_workflow.py`: 4,781 行。
  - `scripts/runner_cli.py`: 4,187 行。
  - `runner/web_console.py`: 3,712 行。
- 最大类：
  - `MCPPlanningBridgeServer`: 10,202 行。
  - `WorkflowOrchestrator`: 5,014 行。
  - `MCPExecutorWorkflowManager`: 4,693 行。
  - `WebConsoleServer`: 3,473 行。
- 最大函数：
  - `MCPPlanningBridgeServer.__init__`: 3,037 行。
  - `render_v2_index_page`: 1,930 行。
  - `MCPPlanningBridgeServer.serve_http`: 510 行。

外部判断：这是一个大而集中的控制平面，不是清晰分层的小内核。项目已经超过“单体脚本可自然维护”的复杂度。

## 3. 高风险发现

### 3.1 旧验收执行路径仍然使用 `shell=True`

Evidence:

- `adapters/shell_adapter.py:28`
- `runner/acceptance_runner.py:71`
- `runner/state_machine.py:77`
- `runner/acceptance_workflow.py:55`

`ShellAdapter.run()` 直接执行：

```python
subprocess.run(command, shell=True, ...)
```

该路径由 `AcceptanceRunner`、`RunnerStateMachine` 和 `AcceptanceRerunService` 触达。Web Console 对 `rerun_acceptance` 有 dangerous confirmation 护栏，但确认之后仍会进入旧的字符串命令执行路径。

这不是孤立实现问题，而是“双轨执行语义”问题：

- 新路径 `mcp_validation_run` 已采用 argv、`shell=False`、shell meta 拦截和危险 executable 阻断。
- 旧路径仍保留字符串命令和 `shell=True`。

外部判断：这是当前最需要优先处理的安全债。生产级 Agent 控制面不能保留可达的 shell 字符串执行路径。

### 3.2 MCP/Web 请求体缺少统一硬上限

Evidence:

- `runner/mcp_server.py:3818`
- `runner/mcp_server.py:4011`
- `runner/mcp_server.py:4066`
- `runner/web_console.py:467`

MCP handler 的 `_read_body()` 直接按 `Content-Length` 读取 body。Actions REST 路径有 request size guard，但 `/mcp` JSON-RPC 主路径没有看到同等级保护。Web Console JSON body 读取也缺少统一大小上限。

外部判断：本地 loopback 环境影响有限；一旦走 HTTPS remote MCP，这就是基础 DoS 攻击面。成熟服务必须统一限制 request body、解析时间、连接超时和响应大小。

### 3.3 工具权限策略手工维护，默认姿态不够硬

Evidence:

- `runner/mcp_server.py:5802`
- `runner/mcp_server.py:6131`

`_required_scope_for_tool()` 通过手工 if/elif 判断工具名、action、phase，然后决定 `mcp:read`、`mcp:preview`、`mcp:commit`、`mcp:plan`。

核心问题：

- 默认值是 `mcp:read`。
- 新工具如果忘记加入映射，容易偏向低权限。
- tool schema、handler、scope、side effect profile 没有同源声明。
- 测试覆盖了部分 scope，但无法从结构上强制所有工具都声明权限。

外部判断：这比没有权限模型强很多，但还不是生产级 policy engine。成熟模式应是“注册即声明权限，默认拒绝，测试强制所有工具有 policy”。

### 3.4 MCP 表面与业务内核反向依赖

Evidence:

- `runner/mcp_server.py:531`
- `runner/mcp_workflow_router.py:12`
- `runner/core_orchestrator.py:63`
- `runner/core_orchestrator.py:3183`

`MCPPlanningBridgeServer` 是上帝对象。更重要的是，`core_orchestrator` 内部反向实例化 `MCPPlanningBridgeServer` 来执行 plan version action：

```python
from runner.mcp_server import MCPPlanningBridgeServer
server = MCPPlanningBridgeServer(self.project_root)
return server._tool_manage_plan_version(full_params)
```

这导致业务编排层依赖 MCP 入口层。依赖图出现核心循环：

```text
runner.mcp_server <-> runner.mcp_workflow_router <-> runner.core_orchestrator
```

外部判断：这是架构成熟度硬伤。真正的产品内核应是：

- core domain/service 层提供能力；
- MCP/Web/CLI 只是 adapter；
- adapter 不应被 core 反向实例化。

### 3.5 凭据持久化安全不一致

Evidence:

- `runner/runner_global_config.py:286`
- `runner/runner_global_config.py:528`
- `runner/cloud_pairing.py:49`
- `runner/mcp_oauth.py:137`

全局 auth token 写入后会 chmod 600，这是好的。但 cloud agent pairing credential 直接写 JSON，没有看到相同 chmod/keyring/加密处理。内建 OAuth token store 也以 token 为 key 明文持久化。

外部判断：项目在“输出 redaction”上投入很多，但“静态 credential 存储安全”还不统一。远端服务化后，凭据存储必须作为独立安全面处理。

### 3.6 写操作有 preview，但事务性不统一

Evidence:

- `runner/mcp_project_patch.py:101`
- `runner/mcp_project_patch.py:377`
- `runner/mcp_project_patch.py:597`
- `runner/project_registry.py:1306`
- `runner/state_mutation_gateway.py:23`

项目已有原子写和回滚意识，例如 `project_registry` 的 JSON transaction，以及 `StateMutationGateway`。但 patch apply、多文件写入和部分 legacy workflow 没有统一下沉到同一事务层。

外部判断：preview 不能替代 apply 阶段的失败恢复能力。Agent 写代码的生产化能力需要“失败可恢复、状态可重放、结果可审计”。

### 3.7 Web/CLI 仍是内核工具形态，不是成熟产品界面

Evidence:

- `runner/web_console_v2_assets.py:6`
- `runner/web_console_v2_assets.py:259`
- `scripts/runner_cli.py:1243`
- `scripts/runner_cli.py:4058`

Web Console 是单个 Python 函数生成整页 HTML/CSS/JS。CLI 是 4,000 行级命令路由单文件。两者都有实用价值，但工程形态仍偏“内核操作台”，不是可长期维护的产品界面。

外部判断：当前用户体验和可维护性足够支撑 dogfood，不足以支撑外部交付型产品。

## 4. 正面资产

### 4.1 安全意识是真实存在的

Evidence:

- `runner/web_console.py:429`
- `runner/web_console.py:773`
- `runner/web_console.py:830`
- `tests/test_web_console_security.py:115`

Web Console 对非 loopback bind 有显式限制，写请求检查 Content-Type、Host、Origin/Referer、CSRF，并对高风险动作使用 dangerous confirmation。测试覆盖 remote git mutation 不暴露、缺少确认阻断、确认过期、状态签名不匹配等路径。

外部判断：这不是玩具项目。作者知道把本地自动化暴露给模型很危险，并且写了真实护栏。

### 4.2 路径和文件读取边界相对成熟

Evidence:

- `runner/source_review_bridge.py:722`
- `runner/source_review_bridge.py:745`
- `runner/source_review_bridge.py:775`
- `runner/file_policy_rules.py:266`

路径处理包含项目内相对路径校验、resolve 后根目录约束、deny list、敏感路径阻断、文件大小限制和文本文件判断。

外部判断：文件能力面不是随意开放的，已有比较明确的边界意识。

### 4.3 External OAuth 方向正确

Evidence:

- `runner/mcp_external_oauth.py:57`
- `runner/mcp_external_oauth.py:81`
- `tests/test_mcp_external_oauth.py:62`

external OAuth provider 验证 JWKS、issuer、audience/resource、scope、expired/missing exp。测试覆盖 issuer、audience/resource、scope 变体、过期 token 和 metadata。

外部判断：把正式远端 MCP 切到 external-oauth resource server 模式是正确方向。内建 OAuth 应降级为 local/dev 模式。

### 4.4 输出 redaction 和证据脱敏投入较多

Evidence:

- `runner/sensitive_redaction.py:20`
- `runner/runtime_observability.py:1203`
- `runner/runtime_observability.py:1508`
- `tests/test_mcp_runtime_observability.py:597`

项目对 token、secret、Bearer、API key、URL userinfo、tunnel evidence 等有明确 redaction/sanitization 逻辑和测试。

外部判断：输出安全比许多原型项目成熟，但仍需补齐静态 credential 存储安全和统一策略。

### 4.5 测试数量和安全路径覆盖不是空壳

Evidence:

- 71 个顶层测试文件。
- 约 16,419 行测试。
- CI 覆盖 Python 3.10 到 3.14。
- CI 执行 compileall、pytest、self-hosting smoke、git diff check。

Evidence:

- `.github/workflows/ci.yml:20`
- `.github/workflows/ci.yml:40`
- `.github/workflows/ci.yml:43`
- `.github/workflows/ci.yml:46`

外部判断：测试基础存在，但缺少静态类型检查、lint、coverage、SAST、dependency audit 和基于策略注册的强制覆盖。

## 5. 成熟度复判

| 维度 | 外部判断 |
|---|---|
| 核心价值 | 强，有真实场景和真实问题意识 |
| 本地个人使用 | 可用 Alpha |
| 单一可信操作者 | 可控早期 Beta |
| HTTPS remote MCP | 可受控试运行 |
| 多用户生产 | 不成熟 |
| 企业/合规交付 | 不成熟 |
| 安全架构 | 有护栏，但分散且手工同步 |
| 可维护性 | 当前单体复杂度偏高 |
| 测试可信度 | 有覆盖，但缺产品级质量门 |

一句话：这是一个真实有价值的 Agent OS 内核原型，不是成熟产品。

## 6. 最小整改路线

### P0：安全硬化，阻断最明显生产风险

1. 废弃或隔离 `AcceptanceRunner` 的 `shell=True` 路径。
2. 将所有 acceptance command 统一到 argv + `shell=False` + allowlist validator。
3. 给 `/mcp` JSON-RPC、Actions REST、Web POST 全部加统一 request body limit。
4. 给 HTTP 层加统一 timeout、request id、结构化错误和基础 rate limit。
5. external OAuth 保持为正式远端认证唯一推荐路径。

### P1：权限和策略收口

1. 建立 tool registry：handler、input schema、output schema、scope、side effect、confirmation policy 同源声明。
2. 未声明 scope 的工具启动时失败，而不是默认 `mcp:read`。
3. 写操作必须声明 apply/preview/status 三段语义。
4. 添加测试：所有 exposed tools 必须有 policy，所有 commit/plan/executor 能力必须 fail closed。

### P2：架构拆分

1. 把 `MCPPlanningBridgeServer` 拆成 transport adapter、tool registry、auth middleware、JSON-RPC handler、Actions REST handler。
2. 让 `core_orchestrator` 只依赖 domain services，不再实例化 MCP server。
3. 把 `runner_cli.py` 命令路由拆成子模块。
4. 把 `web_console_v2_assets.py` 从 Python 字符串页面升级为可测试、可构建的前端资产，或至少拆分 template/static JS。

### P3：状态、凭据和事务

1. 统一 credential storage：chmod 600、keyring 或加密存储策略。
2. 内建 OAuth store 标记为 dev-only 或替换为成熟 IdP/resource-server 模式。
3. 对 patch/apply、多文件写入、state mutation 建立统一 transaction gateway。
4. 为 failed apply 提供 rollback receipt。

### P4：产品质量门

1. 引入 ruff/black 或等价格式和 lint。
2. 引入 mypy/pyright 的渐进类型检查。
3. 引入 coverage gate，先覆盖 auth、tool policy、patch apply、executor run。
4. 引入 bandit/semgrep/pip-audit 或等价安全扫描。
5. 建立 threat model 和 production readiness checklist。

## 7. 最终外部评价

ColaMeta 不是空壳，也不是简单脚本。它已经拥有真实的控制循环、真实的安全护栏、真实的 ChatGPT/MCP 链路，以及真实的本地自动化能力。

但当前项目的根本问题是：能力已经接近“生产控制面”，代码结构仍像“快速演进的自托管内核”。这会导致安全策略靠人工记忆，危险能力靠多层 if/confirmation 堆叠，核心行为靠少数大文件协调。

最诚实的定位是：

> ColaMeta 是受控 Alpha 到早期 Beta 的自托管 Agent 操作系统内核。
> 它值得继续做，但不能包装成成熟生产产品。

下一阶段不应继续优先堆功能，而应优先收敛权限、统一执行语义、拆分核心入口、硬化 HTTP/OAuth 边界和建立产品级质量门。

## 8. Review Method

本报告基于代码静态阅读、AST 结构统计和文本扫描。

已检查的重点包括：

- MCP server/tool registry/scope mapping。
- Web Console auth、CSRF、dangerous confirmation。
- External OAuth resource-server verifier。
- legacy OAuth/token store。
- Acceptance runner 和 validation runner。
- Patch/apply/write path。
- Project registry/state mutation atomic write。
- Cloud relay/pairing credential path。
- CI/test 配置。

本次未执行：

- 未运行测试。
- 未启动服务。
- 未读取 `.env`、token、cookie、client secret、私有状态或运行日志。
- 未触发部署、发布、tag、push、stable replacement 或外部 provider 写操作。
