# Web GPT Service Entrypoint Guide

状态：`dev_runtime_ready_for_web_gpt_trial`

本文给网页端 GPT 使用 ColaMeta 项目服务时做入口说明。它不是稳定服务晋升授权，不授权 executor run、commit、push、route transition、release、deploy 或替换 `/home/jenn/tools/colameta`。

## 当前服务边界

- 稳定服务目录：`/home/jenn/tools/colameta`
- 稳定服务 MCP：`http://127.0.0.1:8766/mcp`
- 稳定服务 Web：`http://127.0.0.1:8801`
- 当前 dev 测试服务 MCP：`http://127.0.0.1:8776/mcp`
- 当前 dev 测试服务 Web：`http://127.0.0.1:8811`
- 当前 dev repo：`/home/jenn/src/colameta-dev`

网页端 GPT 需要优先连接当前被明确授权的 MCP endpoint。没有稳定晋升授权时，使用 dev 测试服务验证新能力；不要假定稳定服务已经包含 dev repo 最新能力。

## 首批工具

网页端 GPT 连接 MCP 后，先读取项目列表和 Agent 消费者契约：

```json
{
  "name": "list_registered_projects",
  "arguments": {}
}
```

```json
{
  "name": "get_agent_consumer_contract",
  "arguments": {}
}
```

然后调用服务入口卡片：

```json
{
  "name": "get_web_gpt_service_entrypoint",
  "arguments": {}
}
```

这个工具只读，返回：

- 服务 profile
- Agent 消费者契约入口
- 是否需要 `project_name`
- 已登记项目摘要
- 推荐首调用顺序
- 薄治理闭环 `draft -> provided` 用法
- 验证运行 `preview -> run -> status` 用法
- 禁止动作边界

## 推荐首调用顺序

1. `list_registered_projects`
2. `get_agent_consumer_contract`
3. `get_service_entry_profile`，传入 `profile_id=web_gpt_commander`
4. `get_web_gpt_service_entrypoint`
5. `get_stable_promotion_readiness`，必须传入已登记的 `project_name`
6. `get_connector_runtime_health_status`，必须传入已登记的 `project_name`
7. `analyze_project_state`，必须传入已登记的 `project_name`
8. `manage_workflow_run`，用 `action=list` 查看最近证据

网页端 GPT 应选择 `service_entry_profiles` 里的 `web_gpt_commander` 画像。这个画像的意思是：网页 GPT 可以负责读服务入口、整理 payload、向 Commander 请求明确授权，但不能把 preview/evidence 当成执行授权。

示例：

```json
{
  "name": "get_stable_promotion_readiness",
  "arguments": {
    "project_name": "colameta-self-dev"
  }
}
```

这个工具只读，用来判断当前服务候选是否只是 dev 试用、是否可进入稳定晋升审查、以及还有哪些 local blockers / warnings。它不授权替换稳定服务。

```json
{
  "name": "get_connector_runtime_health_status",
  "arguments": {
    "project_name": "colameta-self-dev"
  }
}
```

这个工具只读，用来区分本地 runtime/Web/MCP 健康和外部 connector/tunnel 真实可用性。缺少
`tunnel_client` 或 `control_plane` sanitized evidence 时，closeout 必须保持 blocked；
只有本地 runtime、Web/MCP、tunnel-client、control-plane 证据都 healthy 时，才会进入
`connector_closeout_ready`。它不读取 tunnel-client/proxy/provider 配置，不读取 token/cookie/
credential，也不授权网络修复或稳定服务替换。

```json
{
  "name": "analyze_project_state",
  "arguments": {
    "project_name": "colameta-self-dev"
  }
}
```

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
