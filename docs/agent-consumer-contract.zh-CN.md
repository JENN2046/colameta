# Agent Consumer Contract = Agent 消费者契约

本文件描述 Agent 使用 ColaMeta MCP 服务时应遵守的最小消费契约。

适用对象包括：

- 本地 Codex / Commander agent
- 网页 GPT
- Reviewer / 审查 agent
- Planner / 规划 agent
- Source Observer / 源码观察 agent
- 其他通过 MCP 调用 ColaMeta 的本地 agent

## 统一返回 envelope

每个 MCP tool 调用外层都应按下面的形状判断：

```json
{
  "ok": true,
  "tool": "<tool_name>",
  "data": {}
}
```

失败时：

```json
{
  "ok": false,
  "tool": "<tool_name>",
  "error_code": "<machine_readable_code>",
  "message": "<human_readable_message>",
  "details": {}
}
```

Agent 应先看外层 `ok`。如果 `ok=false`，不要继续把返回内容当成业务结果使用。

## data 内推荐字段

对于新的或已产品化的 payload，`data` 内推荐包含：

```json
{
  "ok": true,
  "read_only": true,
  "side_effects": false
}
```

含义：

- `ok`: payload 自己的成功状态。
- `read_only`: 当前 tool 是否只读或只生成 preview/evidence。
- `side_effects`: 当前 payload 是否声明有状态副作用。

旧 payload 可能没有这三个字段。Agent 不应该因为旧 payload 缺字段就判定失败，但新工具应逐步补齐。

## project_name 路由

服务模式下，项目级工具必须显式传 `project_name`。

正确顺序：

1. `list_registered_projects`
2. `get_agent_consumer_contract`
3. `get_service_entry_profile`
4. `get_web_gpt_service_entrypoint`
5. 带 `project_name` 调用项目级工具

不要在使用 `project_name` 的同时传 `project_root`。

关键错误码：

- `PROJECT_NAME_REQUIRED`: 缺少 `project_name`。
- `INVALID_PROJECT_NAME`: `project_name` 格式非法。
- `PROJECT_ROOT_OVERRIDE_NOT_ALLOWED`: 试图用 `project_root` 覆盖路由。
- `PROJECT_MODE_UNSUPPORTED`: 对 source-only 项目调用 managed-only workflow。

## Service Entry Profiles = 服务入口画像

`get_agent_consumer_contract` 和 `get_web_gpt_service_entrypoint` 会返回 `service_entry_profiles`。

`Service Entry Profiles` 的意思是：不同类型的 agent 进入 ColaMeta 服务时，不应该都走同一套脑内路线，而应该先按自己的角色读取最小必要信息。

如果 agent 只想读取自己的画像，可以调用：

```json
{
  "name": "get_service_entry_profile",
  "arguments": {
    "profile_id": "web_gpt_commander"
  }
}
```

不传 `profile_id` 时，默认返回 `web_gpt_commander`。未知 `profile_id` 会 fail closed，返回 `UNKNOWN_SERVICE_ENTRY_PROFILE`，不会猜测。

当前最小画像：

- `web_gpt_commander`: 网页 GPT 指挥入口。适合从 ChatGPT 网页端通过 MCP 读取项目、生成 thin loop payload、等待 Commander 明确授权。
- `local_codex_commander`: 本地 Codex 指挥入口。适合在本地 repo 内做代码修改和验证，同时用 MCP 读取项目事实和 evidence。
- `reviewer_agent`: 审查 agent。只读 evidence、workflow 记录和 executor report，不创建 `ReviewDecision`，不发 `GateEvent`。
- `planner_agent`: 规划 agent。主要生成 `thin_governed_loop_preview` 的 draft/provided 输入，不调度 executor。
- `source_observer`: 源码观察 agent。只读取源码态和 runtime 事实，source-only 项目不能被当成 managed workflow 项目。

每个画像至少包含：

- `profile_id`: 机器可读画像 ID。
- `display_name`: 人类可读名称。
- `consumer_kind`: 消费者类型。
- `default_authority`: 默认权限边界。
- `first_reads`: 进入服务后的推荐首批读取工具。
- `primary_workflow`: 主要使用路径。
- `next_payload_rule`: 下一步 payload 如何产生或消费。
- `write_boundary`: 哪些动作不能由这个画像自行推出。

## 大结果 packaged 形态

当结果过大时，MCP 可能返回 compact manifest：

```json
{
  "ok": true,
  "tool": "<tool_name>",
  "packaged": true,
  "package_mode": "manifest",
  "summary": {},
  "omitted_fields": ["data"],
  "recommended_next_reads": []
}
```

Agent 应按 `recommended_next_reads` 分步续读，不要把 packaged manifest 当作完整业务 payload。

## Thin Governed Loop 使用规则

推荐流程：

1. `run_mcp_workflow` with `workflow=thin_governed_loop_preview`, `input_mode=draft`
2. 检查 `result.generated_input_bundle`
3. 直接发送 `result.next_request_payload`

`thin_governed_loop_preview` 始终是 evidence preview：

- 不授权 executor dispatch
- 不创建 ReviewDecision
- 不发出 GateEvent
- 不写 Delivery State accepted
- 不 commit / push

## 权威边界

任何 read-only tool 输出都不能单独授权：

- stable service replacement
- executor run
- route transition
- ReviewDecision creation
- GateEvent emission
- Delivery State accepted
- commit / push / release / deploy

这些动作必须另走 Commander 精确授权。
