# Web GPT Service Entrypoint Guide

状态：`stable_private_app_ready`

本文给网页端 GPT 使用 ColaMeta 项目服务时做入口说明。它不是稳定服务晋升授权，不授权 executor run、commit、push、route transition、release、deploy 或替换 `/home/jenn/tools/colameta`。

服务安装、systemd、stable replacement、验收与回滚见
[ColaMeta 安装与部署说明书](INSTALLATION_AND_DEPLOYMENT.zh-CN.md)。

## 当前服务边界

- 稳定服务目录：`/home/jenn/tools/colameta`
- 稳定服务 MCP：`http://127.0.0.1:8766/mcp`
- 稳定服务 Web：`http://127.0.0.1:8801`
- 私人 App external-OAuth origin：`http://127.0.0.1:8767/mcp`
- loopback advanced MCP：`http://127.0.0.1:8768/mcp`
- 当前 dev repo：`/home/jenn/src/colameta-dev`

网页端 GPT 需要优先连接当前被明确授权的 MCP endpoint。不能从 dev repo 新提交自动推导
stable 已加载；先看 runtime provenance 和真实工具返回。

## 首批工具

网页端 GPT 连接私人 App 后，先读取项目列表：

```json
{
  "name": "list_registered_projects",
  "arguments": {}
}
```

然后读取 connector smoke 和 Commander 面板：

```json
{
  "name": "get_apps_connector_smoke_packet",
  "arguments": {"project_name": "colameta-self-dev"}
}
```

```json
{
  "name": "render_commander_app",
  "arguments": {"project_name": "colameta-self-dev"}
}
```

当前 Commander 恰好暴露 7 个工具：

```text
list_registered_projects
get_apps_connector_smoke_packet
render_commander_app
analyze_project_state
run_mcp_workflow
manage_validation_run
manage_git
```

高级 consumer/runtime/cadence 等工具只在 loopback advanced endpoint 使用，不属于私人 App
默认 surface。

## 推荐首调用顺序

1. `list_registered_projects`
2. `get_apps_connector_smoke_packet`，传入已登记的 `project_name`
3. `render_commander_app`，传入已登记的 `project_name`
4. `analyze_project_state`，传入已登记的 `project_name`
5. 需要业务流程时再用 `run_mcp_workflow`
6. 有界验证用 `manage_validation_run`
7. 审查后的 Git 操作用 `manage_git`

网页端 GPT 使用的默认画像是 `web_gpt_commander`：可以读服务入口、整理 payload、向
Commander 请求明确授权，但不能把 preview/evidence 当成执行授权。

如果使用 `render_commander_app` 打开 ChatGPT Apps 面板，先看顶部的 `Readiness` 和
`Next Step`。`Readiness` 只会是 `ready`、`needs_attention` 或 `blocked`；`Next Step` 展示
primary blocker 和第一条 safe next action。它们都是 read-only 状态解释，不授权 executor run、
commit、push、stable replacement、ReviewDecision、GateEvent 或 Delivery accepted。

`get_apps_connector_smoke_packet` 只接受脱敏的 connector evidence，不读取
tunnel-client/proxy/provider 配置，也不读取 token/cookie/credential。只有 runtime、MCP 与
外部 connector 证据都 healthy 时，才会进入 `connector_closeout_ready / ready`。

```json
{
  "name": "analyze_project_state",
  "arguments": {
    "project_name": "colameta-self-dev"
  }
}
```

## Work Item Gate review

当 Stage 0-6 正向结果请求 Gate review 时，不增加新工具，继续使用
`run_mcp_workflow`：

```json
{
  "name": "run_mcp_workflow",
  "arguments": {
    "workflow": "gate_review_request",
    "phase": "inspect",
    "project_name": "colameta-self-dev"
  }
}
```

验收应看到 `status=succeeded`、`read_only=true`、`side_effects=false`。如果 governance
disabled 且 `candidate_count=0`，这是正确边界；不要伪造 Work Item。preview/apply 必须继续遵守
完整签名 preview、精确 bindings、显式确认、`mcp:commit` 和可信私人 Operator/Work Item
authority 的联合门禁。

## 薄治理闭环输入草稿

网页端 GPT 不应该手拼四个完整 JSON 对象。推荐先让服务生成草稿：

```json
{
  "name": "run_mcp_workflow",
  "arguments": {
    "workflow": "thin_governed_loop_preview",
    "phase": "preview",
    "project_name": "colameta-self-dev",
    "input_mode": "draft",
    "draft_seed": {
      "goal": "Describe the bounded local optimization objective.",
      "task_tier": "M0-M2",
      "allowed_files": ["runner/example.py", "tests/test_example.py"],
      "context_files": ["README.md"],
      "validation_commands": ["python -m unittest tests.test_example", "git diff --check"],
      "review_decision_value": "NEEDS_FIX",
      "reviewer_notes": "Review note here."
    }
  }
}
```

M0-M2 低风险任务优先检查返回的 `result.codex_execution_packet.packet_status`。只有状态为
`ready` 时，才使用 `result.codex_execution_packet.copy_paste_codex_prompt` 交给本地 Codex 执行。
ready packet 包含目标、allowed files、context files、validation commands、closeout summary 和
stale HEAD 恢复建议。blocked packet 说明缺少必要执行边界或 tier 无效，不要执行。

只有需要正式 evidence preview 时，才检查 `result.generated_input_bundle`，然后使用
`result.next_request_payload` 作为新的 `run_mcp_workflow` 参数，不需要手工重拼四个对象。

返回里也会保留等价的 `result.copy_paste_next_request`，用于需要复制整段 formal preview payload
的界面。

等价展开形状如下：

```json
{
  "name": "run_mcp_workflow",
  "arguments": {
    "workflow": "thin_governed_loop_preview",
    "phase": "preview",
    "project_name": "colameta-self-dev",
    "input_mode": "provided",
    "thin_loop_inputs": "<generated_input_bundle>"
  }
}
```

注意：这些输出是 evidence 或本地 Codex 任务包，不是 ColaMeta executor run 授权，也不是 review
acceptance 或 delivery state accepted。

## 验证运行

网页端 GPT 不需要自己拼 shell 命令。推荐：

```json
{
  "name": "manage_validation_run",
  "arguments": {
    "action": "preview",
    "scope": "target_files",
    "project_name": "colameta-self-dev",
    "target_files": ["runner/example.py", "tests/test_example.py"]
  }
}
```

拿到 `preview_id` 后：

```json
{
  "name": "manage_validation_run",
  "arguments": {
    "action": "run",
    "project_name": "colameta-self-dev",
    "preview_id": "<preview_id>"
  }
}
```

拿到 `run_id` 后轮询：

```json
{
  "name": "manage_validation_run",
  "arguments": {
    "action": "status",
    "project_name": "colameta-self-dev",
    "run_id": "<run_id>"
  }
}
```

## 禁止动作

除非 Commander 给出明确、当前有效、范围精确的授权，网页端 GPT 不得：

- 替换稳定服务
- push
- executor run
- route transition
- release / deploy
- 创建 ReviewDecision
- emit GateEvent
- 写 Delivery State accepted
- 修改 `/home/jenn/tools/colameta`

## 手感检查

网页端 GPT 使用服务时，应能回答：

- 我连接的是 dev 测试服务还是稳定服务？
- 当前目标 `project_name` 是什么？
- 最近 workflow 证据在哪里？
- 这一步是 read-only、preview、run 还是 commit？
- 输出是 evidence，还是 Commander 已授权的状态迁移？

如果这些问题回答不清楚，应先停在只读检查，不进入写操作。
