# ColaMeta 使用说明书

本文是 ColaMeta 的操作员主手册，面向 Jenn、本地 Codex、网页 GPT、planner、reviewer 和其他通过 MCP 使用 ColaMeta 的 agent。

它解释“日常怎么用”，不是 release 授权、稳定服务替换授权、Delivery State accepted、ReviewDecision 或 GateEvent。

如果你要把一个新项目接入 ColaMeta，先看 [ColaMeta 通用 Onboarding](ONBOARDING.zh-CN.md)。

## 0. 最短路径

如果只是想确认 ColaMeta 当前能不能用：

```text
1. 跑 colameta doctor --json
2. 看 status / primary_blocker / safe_next_action
3. 需要底层 ops 证据时再跑 colameta ops-check --json
4. 跑 colameta console-map --json 看操作台能力地图
5. 在 MCP 里调 get_product_readiness_status 或 get_product_console_map
```

如果要把 ChatGPT Apps 外部 connector 重新接上或做 smoke：

```text
1. colameta connect-chatgpt --json
2. 在 ChatGPT Apps connector 里使用 connector_url
3. 依次调 list_registered_projects -> get_product_readiness_status -> render_commander_app
4. 跑 colameta app-smoke --json 读取外部 smoke 交接包
5. 在 ChatGPT Apps connector 里调 get_apps_connector_smoke_packet
```

如果网页 GPT 或本地 agent 刚连上稳定 MCP：

```text
1. list_registered_projects
2. get_agent_consumer_contract
3. get_service_entry_profile(profile_id="web_gpt_commander")
4. get_agent_operator_flow_packet(project_name="colameta-self-dev", profile_id="web_gpt_commander")
5. get_web_gpt_service_entrypoint
6. get_product_readiness_status(project_name="colameta-self-dev")
7. get_chatgpt_app_readiness(project_name="colameta-self-dev")
8. get_product_console_map(project_name="colameta-self-dev")
9. get_runtime_version_status(project_name="colameta-self-dev")
10. get_stable_replacement_cadence(project_name="colameta-self-dev")
11. get_apps_connector_smoke_packet(project_name="colameta-self-dev")
12. get_connector_runtime_health_status(project_name="colameta-self-dev")
```

如果要开一轮受控优化：

```text
1. run_mcp_workflow workflow=thin_governed_loop_preview input_mode=draft
2. M0-M2 低风险任务：如果 result.codex_execution_packet.packet_status 是 ready，直接把 result.codex_execution_packet.copy_paste_codex_prompt 交给本地 Codex
3. 需要正式 evidence preview 时，才检查 result.generated_input_bundle 并回灌 result.next_request_payload
4. 本地 Codex 按 allowed_files / validation_commands 做实现和验证
5. 审 diff 后再决定 commit / push / stable replacement
```

如果只是想做验收或回归：

```text
1. manage_validation_run action=preview
2. manage_validation_run action=run preview_id=<preview_id>
3. manage_validation_run action=status run_id=<run_id>
4. 把通过/失败结果写成 receipt 或反馈，不直接写 Delivery accepted
```

如果 connector/tunnel 还显示 unverified：

```text
1. 先确认 local_service=healthy
2. 只从 approved status surface 摘 sanitized evidence
3. 回灌 get_connector_runtime_health_status
4. 看到 operator_closeout.decision=ready 后再写 closeout receipt
```

如果你看到说明书和稳定服务返回字段不完全一致：

```text
1. 先看当前 repo 是否 ahead origin/main
2. 再看稳定服务是否已经替换到包含该说明书的 commit
3. 如果 dev repo 比稳定服务新，按稳定服务实际返回为准
4. 不要因为说明书字段较新就直接替换稳定服务；替换必须另有 Jenn 精确授权
```

## 1. 先判断你在用哪个入口

ColaMeta 常见有三类入口：

```text
稳定服务：日常使用入口
dev 测试服务：验证 dev repo 新能力
repo 本地命令：当前 shell 里的开发/维护操作
```

Jenn 当前本机稳定服务：

```text
stable runtime dir: /home/jenn/tools/colameta
stable Web: http://127.0.0.1:8801
stable MCP: http://127.0.0.1:8766/mcp
managed project_name: colameta-self-dev
dev repo: /home/jenn/src/colameta-dev
```

网页 GPT 或外部 agent 默认优先连稳定 MCP。只有在明确验证 dev repo 新能力时，才连 dev 测试 MCP。

做角色化 agent 交接时，先调
`get_agent_operator_flow_packet(project_name=..., profile_id=...)`。它会返回一个
`primary_next_action`、该动作的 gate level，以及给聪明 agent 继续判断的
`advanced_actions`。这个 packet 本身只读，不创建 preview artifact、不启动 executor、不
merge、不 commit、不 push、不替换 stable。

需要一句话服务决策时，看 `get_commander_app_manifest(project_name=...)` 的 `readiness`，
或 Web `/api/v2/status` 的 `service_readiness_summary`。它返回 `ready`、`needs_attention`
或 `blocked`，并给 safe next actions。这只是 read-only 状态解释，不授权 executor run、
commit、push、stable replacement、ReviewDecision、GateEvent 或 Delivery accepted。

ChatGPT Apps connector 收口看同一输出里的 `apps_connector_closeout`。它是只读 smoke
包，顺序是：

```text
Apps connector reachable -> project list includes project_name -> connector closeout ready
```

它会给出 `list_registered_projects` 和 `get_connector_runtime_health_status` 调用形状，
以及 sanitized tunnel evidence 模板。如果 Apps connector 返回 `HTTP 401 token_expired`，
这是 Apps session reconnect 问题，不是本地 ColaMeta 服务故障；不要读取 token、cookie、
browser login state、tunnel-client config、raw logs 或 provider response。

如果需要一次性给 ChatGPT Apps 做 smoke 交接，调用
`get_apps_connector_smoke_packet(project_name=...)`。它会返回
`apps_connector_closeout`、安全 operator sequence、token_expired 恢复指引、
connector runtime health，以及 stable replacement drift hint。stable hint 可以提示
“可替换”，但实际替换仍然必须有 Jenn 的精确授权：

产品级 readiness 入口是 `get_product_readiness_status(project_name=...)`。它把
ops-check、stable runtime、远端 preflight、cloudflared 和 Apps connector smoke 聚合成
一个产品状态，重点看：

```text
status: ready / needs_attention / blocked
ready: 是否可以作为公开 Beta 入口继续使用
primary_blocker: 当前最先需要处理的阻塞项
safe_next_action: 下一步只读或 runbook 动作
```

`get_chatgpt_app_readiness(project_name=...)` 返回同一 readiness 外加 `connector_url`
和推荐工具顺序。它只用于连接和 smoke 交接，不授权 executor run、commit、push、重启服务
或 stable replacement。

项目操作台能力地图入口是：

```text
colameta console-map --json
get_product_console_map(project_name="colameta-self-dev")
```

它把 ColaMeta 当前能做的事情分成四组：

```text
connect_and_readiness: 连接 ChatGPT、产品 readiness、Apps connector smoke
plan_and_review: operator flow、review context、stage parallel preview
controlled_full_loop: full-loop authority、executor、validation、commit、push
stable_and_release: stable promotion readiness、release/submission readiness
```

这个 map 只告诉操作者“入口在哪里、需要什么 scope、当前是否 blocked/available/preview_required”。
它不执行任何入口动作，不启动 executor、不跑验证、不 commit、不 push、不替换 stable、不发布。

Release / ChatGPT App submission 的只读准备状态入口是：

```text
colameta release-readiness --json
colameta release-readiness --submission-materials docs/chatgpt-app-submission-materials.example.json --json
get_release_submission_readiness(project_name="colameta-self-dev")
```

它检查的是本地可证明或操作者显式声明的材料状态：

```text
public MCP / product readiness
Apps connector smoke
app name / logo / description
company URL / privacy policy URL
MCP server details / tool information
screenshots
test prompts and expected responses
localization information
App management permission confirmation
security/privacy review
metadata snapshot review
submission confirmations
```

这些材料可以通过命令行 flag 临时声明，也可以放进一个可复用的 JSON manifest：

```json
{
  "schema_version": "chatgpt_app_submission_materials.v1",
  "app_name": "ColaMeta",
  "app_description": "Project console for local AI engineering workflows.",
  "company_url": "https://example.com",
  "privacy_policy_url": "https://example.com/privacy",
  "logo_ready": true,
  "screenshots_ready": true,
  "test_prompts_ready": true,
  "test_responses_ready": true,
  "localization_ready": true,
  "mcp_tool_info_ready": true,
  "app_management_permissions_confirmed": true,
  "security_review_ready": true,
  "metadata_snapshot_reviewed": true,
  "submission_confirmations_ready": true,
  "evidence": {
    "screenshots": ["docs/submission/screenshot-1.png"],
    "test_prompts": ["docs/submission/test-prompts.md"]
  }
}
```

CLI 的 `--submission-materials PATH` 只读取一个本地 JSON object，大小上限 64 KiB；
显式命令行 flag 会覆盖 manifest 中的同名 ready 状态。MCP 工具只接受结构化
`submission_materials` object，不接受本机文件路径。manifest 里的未知字段会被标为
`SUBMISSION_MATERIALS_MANIFEST_HAS_UNKNOWN_FIELDS`，防止拼写错误被静默忽略。

它不会创建 OpenAI App draft、不会提交 review、不会发布、不会调用 OpenAI Dashboard/API、
不会读取 token/cookie/provider config。即使返回 `ready`，也只是说明本地 submission
证据齐了；真正提交仍由人到 OpenAI Dashboard 手动完成。

Controlled Full Loop 的状态入口是：

```text
colameta full-loop-status --json
get_full_loop_authority_status(project_name="colameta-self-dev")
```

默认状态是 `disabled`，有效权限仍是 `read_preview_only`。即使命令或 MCP 参数显式传入
`enable_full_loop=true`，它也只会检查这些控制项是否齐备：

```text
confirmation_mode=preview_confirm
operator_confirmation_ref 存在
executor_run / validation_run / local_commit / remote_push gate 全部显式允许
```

这个 packet 本身仍然只读：不启动 executor、不跑验证、不 commit、不 push、不替换 stable、
不发布。每一个实际写动作仍必须走自己的 preview-confirm 和 scope gate。Stable replacement
永远不由通用 full-loop status 打开，仍需要精确 commit 授权和 replacement receipt。
`授权替换稳定服务到 <exact_commit_sha>`。

如果 HTTP MCP `tools/list` 已经能看到 `get_apps_connector_smoke_packet`，但当前
ChatGPT Apps connector 工具选择器还看不到，按 Apps metadata cache stale 处理。
开新 ChatGPT/Codex 窗口，或重新连接 ColaMeta Apps connector，然后再调
`list_registered_projects`。metadata 刷新前，可以继续用
`get_connector_runtime_health_status` 加同一份 sanitized tunnel evidence 作为只读
fallback。不要读取 token、cookie、browser login state、connector config 或 raw log。

先分清这两个版本状态：

```text
dev repo HEAD
  你正在修改、提交、push 的代码和说明书。

stable service HEAD
  /home/jenn/tools/colameta 当前实际运行的代码。

origin/main
  GitHub 上 CI 会验证的远端 main。
```

日常使用看 stable service。开发、修复、说明书更新看 dev repo。只有完成 push、CI success，并且 Jenn 明确授权“替换稳定服务到 <exact_commit_sha>”后，stable service 才会切到新的 dev commit。

确认服务：

```bash
/home/jenn/tools/colameta/.venv/bin/colameta status /home/jenn/src/colameta-dev
```

如果已有 tunnel-client admin port 和 PID，可以让 `status` 显式带入 sanitized
tunnel evidence：

```bash
/home/jenn/tools/colameta/.venv/bin/colameta status /home/jenn/src/colameta-dev --tunnel-admin-port 8080 --tunnel-pid 4034
```

这只探测 loopback admin `/healthz` 和 `/readyz`，不读取 token、cookie、
tunnel-client config、proxy config 或 raw logs。

健康判断：

```text
Web healthy + MCP healthy = 本地 ColaMeta 服务可用
runtime_loaded_code_stale=false = 运行时代码和 checkout/package 对齐
external_connector=healthy = 外部 tunnel/control-plane 证据闭合
```

小白读状态时先用这张表：

```text
Web healthy + MCP healthy
  本地 ColaMeta 可以用。

runtime_loaded_code_stale=false
  当前运行代码已被证明和 checkout/package 对齐。

reload_needed_for_verification=true
  不是一定坏了，通常表示运行中稳定服务还不能证明自己等于当前 dev checkout；
  如果 dev repo ahead，而稳定服务未替换，这是正常的“版本未对齐”信号。

external_connector=unverified
  本地 Web/MCP 可用，但还没有 tunnel-client / control-plane 的安全摘要证据。

operator_closeout.decision=blocked
  closeout 不能收口；不等于本地服务不可用。
```

## 2. Agent 连接后先读什么

MCP 连接后先做只读校准，不要直接 run、commit、push 或写状态。

推荐首读顺序：

```json
{"name": "list_registered_projects", "arguments": {}}
```

```json
{"name": "get_agent_consumer_contract", "arguments": {}}
```

```json
{
  "name": "get_service_entry_profile",
  "arguments": {"profile_id": "web_gpt_commander"}
}
```

```json
{
  "name": "get_web_gpt_service_entrypoint",
  "arguments": {}
}
```

项目级工具必须带 `project_name`：

```json
{
  "name": "render_commander_app",
  "arguments": {"project_name": "colameta-self-dev"}
}
```

`render_commander_app` 是 ChatGPT Apps 侧 ColaMeta Commander 面板入口。
它返回只读 manifest 和 widget metadata。只需要数据时调用：

```json
{
  "name": "get_commander_app_manifest",
  "arguments": {"project_name": "colameta-self-dev"}
}
```

Apps 客户端可通过 `resources/list` 和 `resources/read` 发现并读取 widget
resource。这个面板只展示服务事实、profile-aware 入口、connector health、
preview-first 路线和显式授权闸门；不授权 executor run、commit、push、
stable service replacement、ReviewDecision、GateEvent 或 Delivery accepted。

```json
{
  "name": "get_runtime_version_status",
  "arguments": {"project_name": "colameta-self-dev"}
}
```

```json
{
  "name": "get_connector_runtime_health_status",
  "arguments": {"project_name": "colameta-self-dev"}
}
```

如果返回 `PROJECT_NAME_REQUIRED`，先调用 `list_registered_projects`，再用返回的 `project_name` 重试。

如果不用 GPT connector，而是本地直接打 HTTP MCP，外层是 JSON-RPC：

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "list_registered_projects",
    "arguments": {}
  }
}
```

读取结果时看：

```text
result.structuredContent.ok
result.structuredContent.data
```

`result.content[0].text` 只是给 MCP 客户端显示的短文本，不是主要结构化结果。

最小 Python 调用示例：

```bash
python3 - <<'PY'
import json, urllib.request

payload = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
        "name": "list_registered_projects",
        "arguments": {},
    },
}
request = urllib.request.Request(
    "http://127.0.0.1:8766/mcp",
    data=json.dumps(payload).encode("utf-8"),
    headers={"Content-Type": "application/json"},
)
with urllib.request.urlopen(request, timeout=10) as response:
    body = json.load(response)

print(json.dumps(body["result"]["structuredContent"], ensure_ascii=False, indent=2))
PY
```

最小 `curl` 调用示例：

```bash
curl -sS http://127.0.0.1:8766/mcp \
  -H 'Content-Type: application/json' \
  --data '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"list_registered_projects","arguments":{}}}'
```

`curl` 会返回完整 JSON-RPC envelope。人工阅读时优先找 `result.structuredContent`。

工具结果的通用读法：

```text
ok=true
  读取 data；继续看 read_only、side_effects、recommended_next_reads。

ok=false
  先读 error_code、message、details；不要猜参数。

packaged=true
  当前结果被压成 manifest；按 recommended_next_reads 分段续读。
```

最常见的错误处理：

```text
PROJECT_NAME_REQUIRED
  先 list_registered_projects，再带 project_name 重试。

PROJECT_ROOT_OVERRIDE_NOT_ALLOWED
  服务模式不接受任意 project_root，只能使用 registry 中的 project_name。

UNKNOWN_SERVICE_ENTRY_PROFILE
  先 get_agent_consumer_contract，看 service_entry_profiles 里的 profile_id。
```

## 3. 五种常用角色

使用 `get_service_entry_profile` 选择入口画像：

```text
web_gpt_commander
  网页 GPT 指挥入口。读事实、生成 payload、请求 Jenn 授权。

local_codex_commander
  本地 Codex 入口。可在 repo 内做安全范围内的代码修改、验证、提交、push。

planner_agent
  规划入口。生成 thin loop preview 输入，不调度 executor。

reviewer_agent
  审查入口。只读 evidence、diff、报告，不创建 ReviewDecision。

source_observer
  源码观察入口。读源码态/runtime 事实，不把 source-only 当 managed workflow。
```

## 4. 开一轮受控优化 preview

先让 ColaMeta 生成草稿，不要手拼完整 `thin_loop_inputs`。

```json
{
  "name": "run_mcp_workflow",
  "arguments": {
    "workflow": "thin_governed_loop_preview",
    "phase": "preview",
    "project_name": "colameta-self-dev",
    "input_mode": "draft",
    "draft_seed": {
      "goal": "Describe the bounded optimization objective.",
      "task_tier": "M0-M2",
      "allowed_files": ["runner/example.py", "tests/test_example.py"],
      "context_files": ["README.md"],
      "validation_commands": [
        ".venv/bin/python -m pytest tests/test_example.py -q",
        "git diff --check"
      ],
      "review_decision_value": "NEEDS_FIX",
      "reviewer_notes": "Keep this bounded and do not mutate state."
    }
  }
}
```

检查返回：

```text
result.codex_execution_packet
result.codex_execution_packet.packet_status
result.codex_execution_packet.copy_paste_codex_prompt
```

M0-M2 低风险任务只有在 `result.codex_execution_packet.packet_status` 为 `ready` 时，才直接把
`copy_paste_codex_prompt` 交给本地 Codex 执行。ready packet 已经包含：

```text
task packet
allowed_files / forbidden_files
context_files
validation_commands
closeout summary template
executor_session_recovery
```

ready direct packet 必须有 `allowed_files` 和 `validation_commands`。如果缺少任一项，或
`task_tier` 不是 M0-M2 低风险 tier，packet 会返回 `blocked`；它不会继承 example 文件、命令或
validation evidence。

如果只是 repo/docs/小修复，不需要再走 `insert_preview -> apply -> continue -> validation preview -> run -> closeout preview -> apply`。

如果需要正式 evidence preview，再检查 `result.generated_input_bundle`，然后发送
`result.next_request_payload` 进入 provided 预览。

注意：thin governed loop preview 是 evidence，不是 executor run 授权。
`codex_execution_packet` 也只授权本地 Codex 在 Jenn/AGENTS 边界内直接工作；不授权
Delivery accepted、ReviewDecision、GateEvent、commit、push 或 stable replacement。

## 5. 验证运行怎么做

网页 GPT 不需要自己拼 shell 命令。用 `manage_validation_run`：

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

轮询：

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

执行器状态轮询使用 `manage_executor_workflow action=status`。轮询口径按 profile 分级：

```text
web_gpt_commander
  next_poll_after_seconds=3
  max_poll_attempts=3
  总观察窗口约 9 秒

local_codex_commander
  next_poll_after_seconds=5
  max_poll_attempts=24
  总观察窗口约 120 秒
```

本地 Codex 跟进执行器时显式传 profile：

```json
{
  "name": "manage_executor_workflow",
  "arguments": {
    "action": "status",
    "project_name": "colameta-self-dev",
    "run_id": "<run_id>",
    "profile_id": "local_codex_commander",
    "poll_attempt": 1
  }
}
```

看到 `terminal=true`、`polling_exhausted=true`，或 provider/auth/quota/network
明确失败时停止轮询。如果 heartbeat 还在但 `last_meaningful_progress.stale=true`，
按疑似 stalled 处理，不要无限轮询。

## 6. Connector / tunnel closeout 怎么看

先读基础健康：

```json
{
  "name": "get_connector_runtime_health_status",
  "arguments": {"project_name": "colameta-self-dev"}
}
```

不带外部 evidence 时，正常可能是：

```text
local_service=healthy
external_connector=unverified
operator_closeout=local_runtime_ready_external_connector_unverified
decision=blocked
```

这表示本地 ColaMeta 可用，但还没有 tunnel-client / control-plane 证据。

最顺手的本地闭环是让 `colameta status` 显式采集安全摘要：

```bash
colameta status /home/jenn/src/colameta-dev --tunnel-admin-port <admin_port> --tunnel-pid <tunnel_client_pid>
```

该命令只接受 loopback admin host，只读探测 `/healthz` 和 `/readyz`，并把
`status/reason_code/evidence_source/last_observed_at` 安全摘要传入
`get_connector_runtime_health_status`。裸 `colameta status` 仍然保持
`external_connector=unverified` 的 fail-closed 行为。
同一个 status 输出也会打印 `Apps connector:` 交接行，包含项目列表检查、connector
closeout 状态和安全的 Apps reconnect 下一步。它不会打印 token、cookie、raw log 或 config。

脚本或 GPT handoff 包可以加 `--json`：

```bash
colameta status /home/jenn/src/colameta-dev --json --tunnel-admin-port <admin_port> --tunnel-pid <tunnel_client_pid>
```

JSON 输出会包含 `connector_runtime_health` 和 `apps_connector_closeout`，调用方不需要解析终端文本。

只有使用 approved status surface 得到 sanitized evidence 后，才可以回灌。
例如当前环境若有 tunnel-client admin port 和 PID，可以先由本地操作员运行：

```bash
/home/jenn/tools/tunnel-client/bin/tunnel-client health --port <admin_port> --pid <tunnel_client_pid> --json
```

然后只摘取 `ok/status/reason_code` 这类安全摘要，不粘贴原始响应、日志、配置或 key。

回灌示例：

```json
{
  "name": "get_connector_runtime_health_status",
  "arguments": {
    "project_name": "colameta-self-dev",
    "tunnel_client": {
      "status": "healthy",
      "reason_code": "TUNNEL_CLIENT_HEALTHZ_READY",
      "evidence_source": "tunnel-client health --port <admin_port> --pid <tunnel_client_pid> --json healthz_ok",
      "last_observed_at": "<observed_at_iso8601>"
    },
    "control_plane": {
      "status": "healthy",
      "reason_code": "TUNNEL_CONTROL_PLANE_READYZ_READY",
      "evidence_source": "tunnel-client health --port <admin_port> --pid <tunnel_client_pid> --json readyz_ok",
      "last_observed_at": "<observed_at_iso8601>"
    }
  }
}
```

目标结果：

```text
external_connector=healthy
operator_closeout=connector_closeout_ready
decision=ready
evidence_gap_count=0
operator_closeout.evidence_gaps=[]
```

Web Commander 和 `get_commander_app_manifest` 也会暴露 `apps_connector_closeout`。
当下一位操作者是 ChatGPT Apps 时，用它先调 `list_registered_projects`，再用
sanitized tunnel evidence 调 `get_connector_runtime_health_status`。如果返回
`token_expired`，按 Apps session 重新连接处理，不要误判成本地 ColaMeta 服务故障。
如果当前服务有 `get_apps_connector_smoke_packet(project_name=...)`，优先用它把同一
交接打成一次只读调用，并同时读取 stable replacement drift hint。
Web Commander 也会暴露 `Apps smoke packet` 复制按钮；优先复制这一项，只有当前
Apps metadata 还没刷新出新工具时，才用 connector health fallback。

禁止把 raw token、cookie、credential、provider response、tunnel-client config、proxy config 或 logs 放进 evidence。

## 7. Receipt 什么时候写

Receipt 是证据，不是状态迁移。

适合写 receipt 的时机：

```text
稳定服务替换完成
Web/MCP smoke 完成
runtime provenance 验证完成
connector/tunnel closeout 完成或 blocked 原因明确
CI success 后需要留下可追溯证据
```

Receipt 应记录：

```text
commit
CI run
backup path + sha256
PID / port
Web/MCP smoke
runtime provenance
connector closeout status
remaining caveats
not_performed 边界
```

Receipt 不得写：

```text
Delivery State accepted
ReviewDecision
GateEvent
route transition
executor run
raw secrets / provider raw responses
```

## 8. Git / stable replacement 路线

普通代码或文档优化路线：

```text
1. 本地修改
2. 本地验证
3. 本地 commit
4. git push origin main
5. 等 CI success
```

稳定服务替换是硬边界，必须 Jenn 精确授权：

```text
授权替换稳定服务到 <exact_commit_sha>
```

stable replacement cadence：

```text
小产品化 commit -> 只 push + CI
dev ahead of stable -> 正常开发状态
stable_replacement_not_required -> 继续攒 dev 批次
batch_when_ready -> 阶段批次完成后再替换 stable
```

不要因为 `dev HEAD != stable HEAD` 就向 Jenn 要 stable replacement 授权。这个
drift 应报告成 `dev_ahead_stable`，不是紧急替换请求。只有以下情况才请求精确
stable 授权：

```text
stable 服务故障，修复已经在 dev
Jenn 明确要现在在 stable 使用新能力
安全或正确性修复必须进入 stable
一组产品化批次已经完成，Jenn 决定晋升
```

这个判断优先读 `get_stable_replacement_cadence(project_name=...)`，或 Web
`/api/v2/status.stable_replacement_cadence`。`colameta status --json` 也会返回
同一份 cadence packet。
当 dev ahead stable 时，cadence packet 会包含 `dev_batch_summary`，列出从 stable
以来的 commit 数、最近 commit subject、`batch_size` 和 `promotion_posture`。这只是
后续批次审查证据，不是替换请求。
它还会包含 `batch_review_summary`，汇总本批主题、涉及 surface（`MCP`、`Web`、
`CLI`、`docs`、`tests`）、风险级别和 `suggested_review_action`。
`ready_for_human_review` 表示可以审查这批 dev，不表示授权或请求 stable replacement。

替换流程必须包含：

```text
preflight: HEAD / origin/main / CI success
backup: /home/jenn/tools/colameta-stable-backups/*.tar.gz + sha256
checkout stable dir to exact commit
pip reinstall stable package
restart stable Web/MCP
Web/MCP smoke
runtime provenance check
receipt
```

不要把 CI success、read-only evidence、preview 或 receipt 自动理解为 stable replacement 授权。

## 9. Stage parallel plan preview

使用 `get_stage_parallel_plan_preview(project_name=...)` 预览未来的阶段级并行自动化。
这个 packet 会把候选任务拆成 task shards，列出 allowed file 边界、涉及 surface、
文件 overlap 风险，以及 `ready_for_parallel_run_preview` 或
`refine_task_boundaries` 这类下一步建议。

这只是 read-only planning evidence。它不创建 executor preview、不启动 executor、
不创建 branch/worktree、不 merge、不 commit、不 push、不替换 stable。下一步产品化仍应是
preview-first 的 `stage_parallel_run_preview` 一类入口。

使用 `get_stage_parallel_run_preview(project_name=...)` 预览下一层编排。它会生成确定性的
`parallel_group_id`，为每个 shard 提议隔离 worktree 和 branch，并展示未来
`manage_executor_workflow action=run_once_preview` 的请求形状。它仍然不创建 worktree、
不创建 executor preview artifact、不启动 executor run，也不合并结果。

本地并行阶段编排 packet 链路是：

1. `get_stage_parallel_plan_preview`
2. `get_stage_parallel_run_preview`
3. `get_stage_parallel_worktree_assignment_preview`
4. `get_stage_parallel_next_action_packet`
5. `manage_stage_parallel_shard_inputs action=preview`
6. `get_stage_parallel_executor_group_preview`
7. `manage_stage_parallel_executor_runs action=preview`
8. `get_stage_parallel_executor_results_packet`
9. `get_stage_parallel_group_status`
10. `get_stage_parallel_merge_preview`
11. `manage_stage_parallel_merges action=preview`
12. `get_stage_parallel_closeout_packet`

这组工具让 ChatGPT/Jenn 在任何 mutation 前先读完整并行阶段路径。
`group_status`、`merge_preview` 和 `closeout_packet` 可以接收调用方提供的 sanitized
executor result 摘要，但它们不读 raw logs，也不创建 worktree、不创建 executor preview、
不启动 executor、不 merge、不 commit、不 push、不写 Delivery accepted、不创建
ReviewDecision/GateEvent，也不替换 stable。

第一个受控 mutation 闸门是 `manage_stage_parallel_worktrees`。
先用 `action=preview` 生成短期 preview artifact，并校验 base HEAD、dirty state、
branch name 和隔离 worktree path；再用 `action=apply` 携带这个 `preview_id`
创建隔离 git worktree。这个 apply 仍然不创建 executor preview、不启动 executor、不 merge、
不 commit、不 push、不写 Delivery accepted、不创建 ReviewDecision/GateEvent，也不替换
stable。

当前阶段状态不清楚时，使用 `get_stage_parallel_next_action_packet`。它会读取当前
worktree、shard input、executor preview、claim 和 report metadata，然后返回一个
`copyable_tool_call` 指向下一步安全工具调用。它不创建 preview artifact、不写 shard
input、不启动 executor、不 merge、不 commit、不 push、不写 Delivery accepted、不创建
ReviewDecision/GateEvent，也不替换 stable。

隔离 worktree 已存在后，使用 `manage_stage_parallel_shard_inputs`。
`action=preview` 会校验每个 worktree 已存在、位于预期 branch/head 且工作区干净；
`action=apply` 会在每个 worktree 的
`.colameta/runtime/stage-parallel-shard-inputs/current/` 下写入 shard-specific
runtime `plan.json`、`state.json` 和 prompt overlay。它不改变 Git baseline、不创建
executor preview、不启动 executor、不 merge、不 commit、不 push、不写 Delivery
accepted、不创建 ReviewDecision/GateEvent，也不替换 stable。

shard inputs 已存在后，使用 `manage_stage_parallel_executor_group`。
`action=preview` 会校验每个 worktree 已存在、位于预期 branch/head、工作区干净，并且
executor preflight 使用 shard input overlay 可通过；`action=apply` 会在每个 worktree
内创建一个 `manage_executor_workflow action=run_once_preview` artifact。它仍然不启动
executor、不 merge、不 commit、不 push、不写 Delivery accepted、不创建
ReviewDecision/GateEvent，也不替换 stable。

这些 `run_once_preview` artifacts 已存在后，使用
`manage_stage_parallel_executor_runs`。`action=preview` 会校验每个 worktree 都有未消费、
未过期且匹配当前 branch/head/provider 的 preview artifact；`action=apply` 会用
`executor_session_mode=start_new` 为每个隔离 worktree 启动一个 executor run。它仍然不把
结果 merge 回 main、不 commit main、不 push、不写 Delivery accepted、不创建
ReviewDecision/GateEvent，也不替换 stable。

executor runs 已启动或完成后，使用
`get_stage_parallel_executor_results_packet` 读取隔离 worktree 里的 structured preview、
claim 和 report metadata。它会输出可交给 `get_stage_parallel_group_status` 和 merge
preview 的 sanitized `executor_results`。它不读 raw logs、不启动 executor、不 merge、不
commit、不 push、不写 Delivery accepted、不创建 ReviewDecision/GateEvent，也不替换 stable。

merge preview ready 后，使用 `manage_stage_parallel_merges`。
`action=preview` 会冻结 target branch/head、source branch heads、干净 target 状态和 merge
sequence；`action=apply` 会用这个 `preview_id` 顺序执行本地
`git merge --no-ff --no-edit`。它可以创建本地 merge commits，但仍然不 push、不写
Delivery accepted、不创建 ReviewDecision/GateEvent，也不替换 stable。

## 10. 常见故障

### 说明书 smoke checklist

每次改完说明书或稳定服务后，最小验收：

```text
colameta status 显示 running
Web /api/healthz OK
MCP /healthz OK
tools/list 能看到关键入口工具
list_registered_projects 能看到 colameta-self-dev
get_runtime_version_status(project_name) 能返回 runtime_loaded_code_stale / reload_awareness_reason
get_connector_runtime_health_status(project_name) 能返回 local_service / external_connector / operator_closeout
run_mcp_workflow thin_governed_loop_preview input_mode=draft 能返回 codex_execution_packet / generated_input_bundle / next_request_payload
```

如果这些都通过，说明日常指挥入口可用。connector/tunnel 仍可能是 `unverified`，那是外部证据未闭合，不等于本地 ColaMeta Web/MCP 不可用。

如果 smoke 结果里缺少说明书提到的新字段，先检查 dev repo 是否有未部署到 stable service 的 commit。稳定服务没有替换前，新字段不会自动出现。

### `PROJECT_NAME_REQUIRED`

原因：服务模式下项目级工具没传 `project_name`。

处理：

```text
先 call list_registered_projects
选择 project_name
重试原工具
```

### Web API 403

原因：读 API 需要页面嵌入的 CSRF 和 Web read auth header。

处理：

```text
先打开 Web root page
读取 meta:
  colameta-csrf-token
  colameta-web-read-auth
请求 API 时带:
  X-ColaMeta-CSRF
  X-ColaMeta-Read-Auth
```

不要打印或提交 token。

### `runtime_loaded_code_stale=true`

原因：运行进程加载的代码和 checkout/package 不一致。

处理：

```text
先读 get_runtime_version_status
确认 reload_awareness_reason
如需替换/重启稳定服务，必须 Jenn 精确授权
```

### `external_connector=unverified`

原因：没有 tunnel-client / control-plane sanitized evidence。

处理：

```text
使用 approved status surface，例如 tunnel-client health
只提取 ok/status/reason_code 等安全摘要
回灌 get_connector_runtime_health_status
检查 operator_closeout.evidence_gaps
写 connector closeout receipt
```

### `UNSAFE_CONNECTOR_EVIDENCE`

原因：传入 external evidence 时带了额外字段，例如 raw token/log/config。

处理：

```text
只保留:
  status
  reason_code
  evidence_source
  last_observed_at
```

### CI 失败

处理：

```text
gh run list --commit <sha>
gh run view <run_id> --log
先定位失败 job
修复后本地验证
再 push
```

不要在 CI 失败时替换稳定服务。

## 10. 最小安全边界

除非 Jenn 给出明确、当前有效、范围精确的授权，不要执行：

```text
stable service replacement
executor run
route transition
ReviewDecision creation
GateEvent emission
Delivery State accepted
git tag
force push
release / deploy / publish
database write
provider/auth/proxy config mutation
tunnel-client restart
```

永远不要读取、打印、复制、提交：

```text
.env
tokens
cookies
credentials
runtime keys
provider raw responses
tunnel-client config/log raw content
private memory
browser login state
```

## 11. 当前可交付判断

当前 ColaMeta 适合做：

```text
项目登记
项目事实读取
Web/MCP 指挥入口
thin governed loop preview
受控验证
review handoff
receipt/evidence 归档
本地 Git 提交/推送辅助
稳定服务晋升前证据整理
connector/tunnel closeout 证据判断
```

当前 ColaMeta 不应被当成：

```text
无人监管自动发布系统
绕过 Commander 授权的 executor dispatch 系统
自动修改 provider/proxy/tunnel 配置的运维系统
替代人工验收和产品判断的 Reviewer
```

最稳妥的工作方式是：

```text
ColaMeta 负责证据和受控流程
GPT/Codex 负责推进和审查
Jenn 负责方向、授权和最终判断
```
