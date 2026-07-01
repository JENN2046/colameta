# ColaMeta 使用说明书

本文是 ColaMeta 的操作员主手册，面向 Jenn、本地 Codex、网页 GPT、planner、reviewer 和其他通过 MCP 使用 ColaMeta 的 agent。

它解释“日常怎么用”，不是 release 授权、稳定服务替换授权、Delivery State accepted、ReviewDecision 或 GateEvent。

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

确认服务：

```bash
/home/jenn/tools/colameta/.venv/bin/colameta status /home/jenn/src/colameta-dev
```

健康判断：

```text
Web healthy + MCP healthy = 本地 ColaMeta 服务可用
runtime_loaded_code_stale=false = 运行时代码和 checkout/package 对齐
external_connector=healthy = 外部 tunnel/control-plane 证据闭合
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
      "allowed_files": ["runner/example.py", "tests/test_example.py"],
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
result.generated_input_bundle
result.next_request_payload
```

确认内容没问题后，直接发送 `result.next_request_payload`，进入 provided 预览。

注意：thin governed loop preview 是 evidence，不是 executor run 授权。

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
```

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

## 9. 常见故障

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
