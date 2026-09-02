# Agent UX / Tool Routing R1

ColaMeta 的 Agent 操作面采用“状态优先、权限分离”的兼容投影。现有 MCP
工具、typed handle、OAuth scope、preview、context binding 和 confirmation gate
保持不变；R1 只帮助 Agent 理解当前事实与下一步。

## 三个高层入口

R1 首先覆盖：

- `analyze_project_state`
- `get_agent_operator_flow_packet`
- `run_mcp_workflow` 的 `auto_preview`

这些入口保留原有字段，并追加同一版本的 `agent_state` 投影：

```yaml
agent_projection_schema_version: colameta.agent_state_projection.v1
agent_state:
  project:
  goal:
  current_phase:
  current_version:
  status:

primary_next_action:
  tool:
  action:
  reason:
  required_arguments:
  optional_arguments:

blocked_next_actions:
  exhaustive: false
  items: []

continuation:
recovery:
authority:
routing:
```

若当前事实不能证明唯一安全动作，`primary_next_action` 为 `null`，并返回
`why_no_unique_action`。Router 不会为了填字段而猜测。

## Navigation 不等于 authority

`primary_next_action`、`blocked_next_actions`、`routing`、`continuation` 和
`recovery` 都是导航信息，不是授权来源。即使 Router 推荐某个动作，调用方仍须
满足原工具要求的 scope、typed preview、context binding、显式确认和状态机 gate。

`blocked_next_actions.exhaustive` 固定为 `false`。未列出的动作不会因此自动获得
允许；所有工具仍独立执行自己的权限和上下文校验。

`authority` 中每个动作域都明确带有 `granted_by_projection: false`。特别是投影不
授予 executor、commit、push、merge、Stable replacement、delivery、deploy 或
release 权限。所有 scope 值均为现有协议值 `mcp:read`、`mcp:preview`、
`mcp:plan` 或 `mcp:commit`；validation 按 inspect/preview/run 动作分别表达，
不会制造伪 scope。

## Typed continuation

R1 统一的是 handle 的解释信息，不是 handle 本身。投影继续区分：

- `preview_id`
- `patch_id`
- `run_id`
- `workflow_id`
- `review_manifest_id`
- `artifact_id`
- `gate_preview_id`
- `batch_preview_id`

下游工具仍必须接收原来的 typed 字段；不存在通用的 authority-bearing
`continuation_id`。

## Recovery classes

ColaMeta 控制的高层错误可以投影为：

- `retry_same_call`
- `refresh_state_then_retry`
- `new_preview_required`
- `operator_action_required`
- `authorization_required`
- `context_changed`
- `wait_for_running_operation`
- `unsupported_by_current_surface`
- `hard_stop`

`error_origin` 区分 application、workflow、state gate、connector、OAuth、
transport、host、external provider 和 unknown。无法由 ColaMeta 证明的外部错误
不会获得虚假的自动恢复承诺。包含 OAuth/scope 字样的 Connector 错误仍归属
Connector 边界，并要求 operator action，不会被误判为可自动重试。

## Routing registry 与 profiles

`runner.agent_routing_registry` 以审计过的 exact tool-name map 对运行时 catalog 生成机器可读 domain、canonical
primary tool、`PRIMARY` / `ADVANCED` / `LEGACY_OR_INTERNAL`、推荐 profile 和
side-effect level。高层投影直接消费这个 registry，因此它不是只存在于文档中
的静态清单。新工具在完成显式分类前显示为 `unclassified`，不会按名称猜测 domain。

支持的 Agent guidance profiles 包括：

- `web_gpt_commander`
- `local_codex_commander`
- `planner_agent`
- `reviewer_agent`
- `source_observer`

当前 Commander 已经通过既有注册机制物理暴露 9 个工具。R1 保留该机制，不做
动态注册重写，也不删除 Owner/advanced/compatibility catalog 中的工具。

## Progressive disclosure

状态选择器只对可证明的状态返回唯一、保守的下一步。例如：

- executor running → 查询同一 `run_id` 的 status；
- executor completed / validation pending → validation preview；
- validation passed / commit pending → commit preview；
- context changed / preview expired → 重新读取 canonical state；
- parallel stage → 读取 stage next-action packet；
- Stable not ready → 读取 readiness，不执行 Stable 变更。

所有未知状态均 fail closed 到 `primary_next_action: null`。
