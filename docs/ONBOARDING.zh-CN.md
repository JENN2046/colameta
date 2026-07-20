# ColaMeta 通用 Onboarding

本文面向第一次把一个本地项目接入 ColaMeta 的操作者或 agent。它讲通用接入路径，不授权 executor run、stable replacement、release、deploy、ReviewDecision、GateEvent 或 Delivery State accepted。

安装或部署 ColaMeta 本身，先读
[ColaMeta 安装与部署说明书](INSTALLATION_AND_DEPLOYMENT.zh-CN.md)。

## 1. 先选接入模式

ColaMeta 有两种常用项目模式：

```text
source-only
  轻量接入。适合先让 Web/MCP/agent 读取源码、项目状态和基本 evidence。
  不启用完整 Runner version plan。

managed
  受控推进。适合让 ColaMeta 管理版本计划、validation、receipt、review handoff 和 Git 闭环。
```

选择规则：

```text
只是观察一个项目
  先用 source-only。

要持续推进版本、记录证据、让 agent 按 allowed_files / validation_commands 工作
  用 managed。

不确定
  先 source-only，再用受控 preview 转 managed。
```

## 2. 登记项目

在本地 shell 里登记项目：

```bash
colameta add /path/to/project source-only
```

或：

```bash
colameta add /path/to/project managed
```

登记后先检查：

```bash
colameta status /path/to/project
```

如果服务已经在跑，确认：

```text
Web Console: healthy
MCP Endpoint: healthy
```

## 3. Agent 首读顺序

Agent 连接 MCP 后不要先 run，也不要先写状态。私人 App Commander 按七工具入口读取：

```text
list_registered_projects
get_apps_connector_smoke_packet
render_commander_app
analyze_project_state
只在需要 read/preview workflow 时调用 run_mcp_workflow
有界验证使用 manage_validation_run
审查后的 Git 操作使用 manage_git
```

consumer contract、独立 runtime/cadence 和其他底层诊断属于 loopback advanced endpoint，
不是七工具私人 App contract。

项目级工具必须带 `project_name`。如果不知道项目名，先 `list_registered_projects`。

本节后续 role/profile packet 属于 **advanced loopback** 能力。选择 profile 后，优先调
`get_agent_operator_flow_packet(project_name=..., profile_id=...)`。它是一个只读的角色化导航
packet：只给一个 `primary_next_action`，同时保留 `advanced_actions` 给需要完整上下文的 agent。

需要一句话私人 App 决策时，看 `render_commander_app` 在 ChatGPT Apps 面板
`Readiness` 和 `Next Step` 区块内嵌的 readiness。advanced endpoint 可从
`get_commander_app_manifest` 读取同一信号，Web `/api/v2/status` 则提供
`service_readiness_summary`。它会把 runtime、本地服务和 connector closeout 收敛成
`ready`、`needs_attention` 或 `blocked`；这是 read-only 状态解释，不授权 executor run、
commit、push、stable replacement、ReviewDecision 或 GateEvent。
ChatGPT Apps connector 交接时，也读 `apps_connector_closeout`。私人 App 使用
`get_apps_connector_smoke_packet`；advanced endpoint 还可以带 sanitized tunnel evidence 调
`get_connector_runtime_health_status`。`token_expired` 是 Apps session 重新连接问题，
不是本地 Web/MCP 服务坏了的证据。
如果当前服务暴露 `get_apps_connector_smoke_packet`，优先用它做同一个只读交接。
它还会返回 stable replacement drift hint；这只是提示，不是替换授权。

## 4. 新项目最小 smoke

接入后最小 smoke checklist：

```text
私人 App Commander：
项目出现在 list_registered_projects
get_apps_connector_smoke_packet 返回 read_only=true
render_commander_app 内嵌 ready、needs_attention 或 blocked
analyze_project_state 能返回项目模式和建议下一步
source-only 项目不会被当成 managed workflow 项目
managed 项目能进入 thin governed loop preview
gate_review_request inspect 保持只读，并返回脱敏候选或 candidate_count=0

可选 loopback advanced smoke（http://127.0.0.1:8768/mcp）：
选中的 profile 能读到
get_runtime_version_status 返回 read_only=true
get_stable_replacement_cadence 对普通 dev/stable drift 返回 stable_replacement_not_required
get_connector_runtime_health_status 返回 read_only=true
service_readiness_summary/readiness 返回 ready、needs_attention 或 blocked
```

如果 smoke 失败，先看 `error_code`，不要猜参数。

常见错误：

```text
PROJECT_NAME_REQUIRED
  缺 project_name。先 list_registered_projects。

PROJECT_NOT_REGISTERED
  registry 里没有这个项目。先 colameta add。

PROJECT_MODE_UNSUPPORTED
  对 source-only 项目调用了 managed-only workflow。
```

## 5. 进入受控优化

managed 项目使用 thin governed loop preview：

```json
{
  "name": "run_mcp_workflow",
  "arguments": {
    "workflow": "thin_governed_loop_preview",
    "phase": "preview",
    "project_name": "<project_name>",
    "input_mode": "draft",
    "draft_seed": {
      "goal": "Describe the bounded objective.",
      "allowed_files": ["docs/example.md"],
      "validation_commands": ["git diff --check"],
      "review_decision_value": "NEEDS_FIX",
      "reviewer_notes": "Keep this bounded."
    }
  }
}
```

检查：

```text
result.codex_execution_packet
result.codex_execution_packet.packet_status
result.codex_execution_packet.copy_paste_codex_prompt
```

M0-M2 低风险本地任务，只有在 `packet_status` 为 `ready` 时，才直接把
`result.codex_execution_packet.copy_paste_codex_prompt` 交给本地 Codex。ready packet 会包含目标、
allowed files、context files、validation commands、closeout summary 和 stale HEAD 恢复建议。
blocked packet 说明缺少必要执行边界或 tier 无效，不要执行。

只有需要正式 evidence preview 时，才检查 `result.generated_input_bundle`，然后把
`result.next_request_payload` 原样回灌到 `run_mcp_workflow`，进入 provided preview。

preview 和本地 Codex packet 仍然只是有边界的 evidence/task guidance，不是 executor 授权、
review acceptance、commit、push 或 delivery state accepted。

## 6. 验证运行

用 `manage_validation_run`，不要让网页 GPT 自己拼 shell：

```text
action=preview
action=run
action=status
```

`run` 之前必须有 `preview_id`。验收通过后也不要直接写 Delivery accepted；先记录 receipt 或 review handoff。

执行器状态轮询按 profile 分级：

```text
web_gpt_commander
  3 秒一次，最多 3 次。

local_codex_commander
  5 秒一次，最多 24 次。
```

本地 Codex 跟进执行器时，在 `manage_executor_workflow action=status` 中传：

```text
profile_id="local_codex_commander"
```

看到 `terminal=true` 或 `polling_exhausted=true` 就停止轮询。

## 7. Connector / tunnel 证据

本地 Web/MCP healthy 只说明 ColaMeta 本地服务可用。

外部 connector/tunnel 还需要额外安全摘要证据：

```text
tunnel_client.status
tunnel_client.reason_code
tunnel_client.evidence_source
control_plane.status
control_plane.reason_code
control_plane.evidence_source
```

只允许 sanitized evidence。不要读取或粘贴：

```text
token
cookie
credential
provider raw response
tunnel-client config
proxy config
logs raw content
```

## 8. Git 和稳定服务

普通项目推进通常是：

```text
本地修改
本地验证
commit
push
CI
review / receipt
```

稳定服务替换不是普通步骤。必须有精确授权：

```text
授权替换稳定服务到 <exact_commit_sha>
```

没有这句授权时，只能做 preflight、receipt、preview 和建议，不能替换 stable runtime。
backup、精确 checkout、wheel reinstall、restart、私人 App 验收和 rollback 顺序见
[ColaMeta 安装与部署说明书](INSTALLATION_AND_DEPLOYMENT.zh-CN.md)。

## 9. Agent 边界

Agent 可以帮助：

```text
读项目事实
生成 preview
整理 evidence
修改 bounded allowed_files
运行本地验证
准备 commit
写 receipt
```

Agent 不应自行：

```text
force push
git tag
release / deploy / publish
stable replacement
executor run
route transition
ReviewDecision creation
GateEvent emission
Delivery State accepted
读取或输出 secrets
```

## 10. 判断是否接入成功

一个项目可以算接入成功，当：

```text
项目在 registry 里可见
服务入口契约可读
profile 能选择
runtime health 可读
connector health 可读
项目状态可读
下一步 workflow preview 可生成
失败时有明确 error_code
```

这表示 ColaMeta 可以作为指挥入口使用。它不表示项目已经完成交付，也不表示 stable replacement、release、deploy 或 Delivery accepted 已经发生。
