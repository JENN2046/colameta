# ColaMeta 通用 Onboarding

本文面向第一次把一个本地项目接入 ColaMeta 的操作者或 agent。它讲通用接入路径，不授权 executor run、stable replacement、release、deploy、ReviewDecision、GateEvent 或 Delivery State accepted。

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

Agent 连接 MCP 后不要先 run，也不要先写状态。先读：

```text
list_registered_projects
get_agent_consumer_contract
get_service_entry_profile
get_web_gpt_service_entrypoint
get_runtime_version_status
get_connector_runtime_health_status
```

项目级工具必须带 `project_name`。如果不知道项目名，先 `list_registered_projects`。

## 4. 新项目最小 smoke

接入后最小 smoke checklist：

```text
项目出现在 list_registered_projects
选中的 profile 能读到
get_runtime_version_status 返回 read_only=true
get_connector_runtime_health_status 返回 read_only=true
analyze_project_state 能返回项目模式和建议下一步
source-only 项目不会被当成 managed workflow 项目
managed 项目能进入 thin governed loop preview
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
result.generated_input_bundle
result.next_request_payload
```

然后把 `result.next_request_payload` 原样回灌到 `run_mcp_workflow`，进入 provided preview。

preview 仍然只是 evidence，不是 executor 授权。

## 6. 验证运行

用 `manage_validation_run`，不要让网页 GPT 自己拼 shell：

```text
action=preview
action=run
action=status
```

`run` 之前必须有 `preview_id`。验收通过后也不要直接写 Delivery accepted；先记录 receipt 或 review handoff。

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
