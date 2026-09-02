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
`continuation_id`。当高层 `preview_ids` envelope 与嵌套 result/next-action 中的
typed handle 同时存在时，投影优先保留 `patch_id` 等精确类型，不把它降级成
generic `preview_id`。

对于 generic `preview_id`，`allowed_next_actions` 从生产 next-action 的实际
`action` 或 workflow `phase` 派生，例如 `commit`、`run_once`、`run_bounded`。
只有 handle、没有消费上下文时返回空列表和原因，不猜测 `status/apply`。

当入口已解析出注册项目时，canonical action 的 `params` / `arguments` 和
`required_arguments` 都携带同一个 `project_name`。Agent 复制该 action 后仍会
走原来的 registry route；这只是上下文绑定，不授予额外 authority。

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

Recovery fallback 遵循 `known retry, unknown stop`：只有 exact error code 已被
审查为 transient 且同调用幂等时才可进入 `retry_same_call` allowlist；未分类的
ColaMeta application error 返回 `operator_action_required`、`agent_should_stop: true`
和 `retryable: false`。

## Routing registry 与 profiles

`runner.agent_routing_registry` 以审计过的 exact tool-name map 对运行时 catalog 生成机器可读 domain、canonical
primary tool、`PRIMARY` / `ADVANCED` / `LEGACY_OR_INTERNAL`、推荐 profile 和
side-effect level。高层投影直接消费这个 registry，因此它不是只存在于文档中
的静态清单。新工具在完成显式分类前显示为 `unclassified`，不会按名称猜测 domain。

side-effect level 优先采用已审计的固定 action/scope 语义：例如
`manage_workflow_run` 仅提供读取动作，标记为 `READ_ONLY`；legacy
`manage_plan_workflow` 仅生成预览，标记为 `PREVIEW`。只有没有固定分类的
`manage_*` surface 才使用 `DYNAMIC_BY_ACTION` 命名 fallback。

通过 `project_name` 路由到登记项目时，内部 routed server 保留当前 serving
exposure profile。Commander 因而继续使用 `web_gpt_commander` reachability；
只读 executor preflight 不会推荐、泄露或要求确认 Commander 无法调用的
`manage_executor_workflow`。

支持的 Agent guidance profiles 包括：

- `web_gpt_commander`
- `local_codex_commander`
- `planner_agent`
- `reviewer_agent`
- `source_observer`

当前 Commander 已经通过既有注册机制物理暴露 9 个工具。R1 保留该机制，不做
动态注册重写，也不删除 Owner/advanced/compatibility catalog 中的工具。
`auto_preview` 会用当前 profile 的 primary/advanced guidance 过滤
`primary_next_action`；如果现有 workflow 只能给出 profile 不可达的底层工具，
它返回 `null`，不会建议 Agent 调用不可见工具。这个约束只应用于
`auto_preview` 的 canonical routing projection，不会重写既有 operator-flow
packet 自身的 route contract。

`source_observer` 的推荐表只包含 read-only 工具；混合读写的 `manage_files`
不会作为其 advanced tool 出现。

## Progressive disclosure

状态选择器只对可证明的状态返回唯一、保守的下一步。例如：

- executor running → 查询同一 `run_id` 的 status；
- executor completed / validation pending → validation preview；
- validation passed / commit pending → commit preview；
- context changed / preview expired → 重新读取 canonical state；
- parallel stage → 读取 stage next-action packet；
- Stable not ready → 读取 readiness，不执行 Stable 变更。

所有未知状态均 fail closed 到 `primary_next_action: null`。
同一入口生成的 `refresh_project_state` fallback 也不会再次成为该入口的 primary
action；Router 会选择下一条可用建议，或者返回 `null`，从而避免刷新自循环。
英文 routing keyword 采用 whole-token 匹配，并显式接纳常见词形变化，例如
`editing`、`patching`、`committed` 和 `committing`；短词不会因为出现在
`expired` 等无关单词内部而误触发路由。下划线按 token 分隔符处理，因此
`plan_update`、`git_commit`、`small_project_patch` 和 `executor_preflight`
等 canonical workflow 名称仍可直接路由。
