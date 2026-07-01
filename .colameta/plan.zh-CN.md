# ColaMeta 机器计划中文镜像

```yaml
chinese_companion:
  source_document: .colameta/plan.json
  source_sha256: 7c3bff7b53e63cfd5b7a7a95eca1632615d9633556ccafc74713cf70461ad27e
  translation_status: companion_draft
  authority_status: planning_reference_only
```

`plan.json` = 机器计划清单。中文意思是：Runner 按这个 JSON 识别项目名称、仓库路径、
运行策略、commit/review 策略、每个版本的 prompt、允许文件、禁止文件、验收命令和
人工验收项。

本中文文件是可读 companion，不替代 `.colameta/plan.json`，也不授权执行、commit、
push、executor run、route transition 或修改 Runner state。

---

## 1. 顶层计划字段

```yaml
project:
  project_name: colameta-self-dev
  project_root: /home/jenn/src/colameta-dev
  plan_version: 1.0.0
  rules_file: /home/jenn/src/colameta-dev/.colameta/rules.md
  runtime_dir: /home/jenn/src/colameta-dev/.colameta/runtime
  logs_dir: /home/jenn/src/colameta-dev/.colameta/logs
  state_file: /home/jenn/src/colameta-dev/.colameta/state.json
```

中文解释：

- `project_name` = 项目名。
- `project_root` = ColaMeta 当前管理的自进化代码仓库目录。
- `rules_file` = Runner 执行时读取的规则文件。
- `runtime_dir` = 运行态临时资料目录。
- `logs_dir` = 日志目录。
- `state_file` = Runner 状态文件路径。

## 2. 执行与控制策略

```yaml
model_execution:
  provider: codex
  mode: manual
  prompt_input_mode: stdin
  stream_output: true
  timeout_seconds: 1800
runner_policy:
  auto_continue_on_pass: false
  max_fix_attempts_per_version: 3
  require_clean_worktree: false
  stop_on_acceptance_failure: true
  stop_on_scope_violation: true
commit_policy:
  enabled: false
  mode: manual_gate
  require_confirm: true
  require_clean_scope: true
  after_acceptance_pass: true
  require_commit_before_continue: false
  include_runner_runtime_files: false
review_policy:
  enabled: false
  mode: manual_gate
  after_versions: []
```

中文解释：

- `model_execution` = 模型执行策略。当前 provider 是 Codex，mode 是 manual，说明执行
  需要受控人工/指挥层驱动，不是完全自动乱跑。
- `runner_policy` = Runner 推进策略。通过验收后不会自动继续；失败或越界时停止。
- `commit_policy` = 提交策略。当前 disabled，但仍声明 commit 必须 manual gate 和 confirm。
- `review_policy` = 审查策略。当前 disabled，mode 仍是 manual gate。

默认验收命令：

- `python3 -m compileall -q .`

---

## 3. 版本任务清单

### v1.0：COMMANDER_AUTHORIZATION / E2C Plan、Patch、State Action Guard

源 prompt：`.colameta/prompts/v1.0.md`

中文 companion：`.colameta/prompts/zh-CN/v1.0.zh-CN.md`

目标：为 Web 危险动作建立 Commander 授权保护，覆盖 plan、patch 和 state action guard
核心路径。

上下文文件：

- `runner/web_console.py`
- `runner/dangerous_action_guard.py`
- `tests/test_dangerous_action_guard.py`
- `tests/test_web_console_security.py`
- `README.md`
- `README.zh-CN.md`

允许修改文件：

- `runner/web_console.py`
- `runner/dangerous_action_guard.py`
- `runner/web_console_v2_assets.py`
- `tests/test_dangerous_action_guard.py`
- `tests/test_web_console_security.py`
- `README.md`
- `README.zh-CN.md`

禁止修改边界：

- GitHub workflow、MCP executor workflow、MCP server、MCP/Git manager、adapters；
- `.colameta/state.json`、runtime、logs、reports、audits、executor sessions、lock files。

验收命令：

- `python3 -m compileall -q runner scripts adapters schemas tests`
- `python3 -m unittest discover -s tests`
- `python3 scripts/self_hosting_smoke.py`
- `git diff --check`
- `git status --short`

人工验收：缺少 confirmation 时必须阻断危险 Web routes；stale state/plan/patch signature
必须被拒；有效 confirmation 前不能 mutation；E2A/E2B 测试继续通过；不泄漏 executor、
commit、push、preview/apply；confirmation id 必须脱敏。

非目标：MCP parity、Git local/remote guard、executor internals、provider adapter sandboxing、
workflow file changes、release/tag/upstream PR、server-side workdir synchronization。

### v1.1：E2D Git Commit Confirm Web Guard

源 prompt：`.colameta/prompts/v1.1.md`

中文 companion：`.colameta/prompts/zh-CN/v1.1.zh-CN.md`

目标：为本地 Git commit confirm 的 Web route 增加 dangerous-action confirmation 保护；
只收窄 `/api/commit-confirm`，`/api/commit-preview` 仍只是 metadata preview。

允许修改文件：

- `runner/web_console.py`
- `tests/test_web_console_security.py`
- `README.md`
- `README.zh-CN.md`

禁止修改边界：

- `runner/mcp_git_commit.py`
- `runner/mcp_git_remote.py`
- `runner/mcp_git_history.py`
- `runner/mcp_server.py`
- adapters、workflow、state、runtime、logs、reports、audits、executor sessions、lock files。

验收命令：compileall、full unittest discovery、self-hosting smoke、`git diff --check`、
`git status --short`。

人工验收：missing confirmation 和 stale preview signature 必须在 commit dispatch 前被拒；
valid confirmation 才进入既有 commit confirm flow；响应中只返回 redacted receipt；
`/api/commit-preview` 不进入危险确认；MCP Git manager internals 不变；不增加 Web push/pull apply route。

非目标：MCP Git manager hardening、Web push/pull apply routes、remote Git guard changes、
restore/revert hardening、executor internals、workflow changes、release/tag/upstream PR、
Runner lineage reconciliation。

### v1.2：E2E Web Remote Git Mutation Policy Baseline

源 prompt：`.colameta/prompts/v1.2.md`

中文 companion：`.colameta/prompts/zh-CN/v1.2.zh-CN.md`

目标：把 Web Console 远端 Git mutation 禁止策略写成基线；Web 远端 Git 状态只能只读，
不能增加 push/pull/fetch apply route。

允许修改文件：

- `README.md`
- `README.zh-CN.md`
- `tests/test_web_console_security.py`
- `runner/web_console.py`

禁止修改边界：

- MCP Git remote/commit/history managers；
- MCP server；
- adapters、workflow、state、runtime、logs、reports、audits、executor sessions、lock files。

验收命令：compileall、full unittest discovery、self-hosting smoke、`git diff --check`、
`git status --short`。

人工验收：Web remote Git status 保持 read-only；不增加 Web push/pull/fetch apply route；
代表性远端 mutation route 在 dispatch 前缺失或拒绝；安全测试能防未来误加；MCPGitRemoteManager
internals 不变。

非目标：实现 Web push/pull/fetch apply、改 MCPGitRemoteManager、改 MCPGitCommitManager、
remote Git guard implementation beyond prohibition baseline、Git history restore/revert guard、
executor internals、workflow changes、release/tag/upstream PR、Runner lineage reconciliation。

### v1.3：Platform-Blocked Operator Handoff RFC

源 prompt：`.colameta/prompts/v1.3.md`

中文 companion：`.colameta/prompts/zh-CN/v1.3.zh-CN.md`

目标：写 docs-only RFC，处理 ChatGPT 平台级 tool-call block 时的 operator handoff，不绕过
ColaMeta preview/apply 控制。

允许修改文件：

- `docs/platform-blocked-operator-handoff.md`
- `README.md`
- `README.zh-CN.md`

禁止修改边界：

- Web Console、MCP Git managers、MCP server、runner、scripts、adapters、schemas、tests、
  assets、workflow、state、runtime、logs、reports、audits、executor sessions、lock files。

验收命令：compileall、full unittest discovery、self-hosting smoke、`git diff --check`、
`git status --short`。

人工验收：RFC 不授权 Web Console remote Git mutation；push/fetch/pull apply 排除在 Web
handoff MVP 外；receipt 是 claim 不是 proof；closeout 要求 read-only state verification；
approved operator surfaces 必须 action-specific；不碰实现文件。

非目标：handoff generation tools、Web Console handoff routes、receipt verification tools、
MCP Git managers、Web routing/action dispatch、remote Git mutation fallback、shell fallback、
manual state edits、unbound apply、tag/release、pull/restore/revert fallback。

### v1.4：Platform-Blocked Operator Handoff Schema Validator V1

源 prompt：`.colameta/prompts/v1.4.md`

中文 companion：`.colameta/prompts/zh-CN/v1.4.zh-CN.md`

目标：实现 platform-blocked operator handoff RFC 的第一片：纯 schema/validator 模块和聚焦测试。
不增加 Web route、MCP action、executor behavior、operator execution surface、remote Git mutation
或 state mutation flow。

允许修改文件：

- `runner/operator_handoff.py`
- `tests/test_operator_handoff.py`
- `docs/platform-blocked-operator-handoff.md`

禁止修改边界：

- Web Console、MCP server、MCP Git managers、executor workflow、continue workflow、project patch、
  dangerous action guard、state machine/mutation/gateway、workflow engine；
- adapters、scripts、schemas、既有安全测试、workflow、state、runtime、logs、reports、audits、
  executor sessions、lock files。

验收命令：compileall、`tests.test_operator_handoff`、full unittest discovery、self-hosting smoke、
`git diff --check`、`git status --short`。

人工验收：只修改允许的 validator/test/doc note；不加 Web route、MCP action、operator execution
surface、remote Git mutation surface；禁止 push/fetch/pull apply、restore/revert、tag/release、
force push、shell fallback、manual state edit、unbound apply；commit_apply 只能是 existing guarded-only；
receipt 是 claim 不是 proof；必须声明 read-only closeout verification；拒绝 generic shell/file
editor/state editor/HTTP client surface；拒绝 remote_git_mutation=true 和 secrets_included=true。

非目标：Web Console handoff route、MCP handoff tool、operator execution UI、executor workflow
changes、plan version apply changes、continue-next-version behavior changes、project patch manager changes、
Git commit/remote manager changes、dangerous action guard changes、remote Git mutation support、shell fallback、
manual state edits、tag/release、pull/restore/revert fallback。

### v1.5：Runtime Version Observability Read-Only Surface

源 prompt：`.colameta/prompts/v1.5.md`

中文 companion：`.colameta/prompts/zh-CN/v1.5.zh-CN.md`

目标：增加很窄的只读 runtime observability slice，暴露 process start time、loaded source/build
HEAD、current checkout HEAD、restart-needed status，用于操作员判断，不执行 restart/reload/kill。

允许修改文件：

- `runner/runtime_observability.py`
- `tests/test_runtime_observability.py`
- `runner/mcp_server.py`
- `tests/test_mcp_runtime_observability.py`

禁止修改边界：

- Web Console、MCP Git managers、MCP executor workflow、continue workflow、project patch、
  dangerous action guard、state/workflow/service lifecycle files；
- scripts、adapters、schemas、workflow、state、runtime、logs、reports、audits、executor sessions、lock files。

验收命令：compileall、runtime observability tests、MCP runtime observability tests、full unittest discovery、
self-hosting smoke、`git diff --check`、`git status --short`。

人工验收：只改 runtime observability 和最小只读 MCP exposure；返回 process_start_time、loaded_source_head
或 build_head、checkout_head、restart_needed/status；HEAD 已知且不同才 true，已知且相同才 false，否则
unknown；不增加 restart/reload/kill/service lifecycle/config mutation、Web business route、Git remote mutation、
fetch/pull/push/tag/release、shell fallback、direct Git command；不暴露 secrets。

非目标：restart preview/apply、reload apply、kill process、service manager integration、config write、
Web Console business route、Web remote Git mutation route、Git push/fetch/pull/tag/release、executor workflow
changes、state mutation changes、operator handoff execution surface、auth changes、notification/background monitor。

### v1.6：Runtime Version Status Documentation + Operator Decision Contract

源 prompt：`.colameta/prompts/v1.6.md`

中文 companion：`.colameta/prompts/zh-CN/v1.6.zh-CN.md`

目标：为 v1.5 的只读 observability 写决策契约与测试，说明 `restart_needed_state` 如何解释，
但不授权自动 restart/reload/kill/apply。

允许修改文件：

- `docs/runtime-version-status-decision-contract.md`
- `tests/test_runtime_version_status_decision_contract.py`
- `README.md`
- `README.zh-CN.md`

禁止修改边界：

- runtime observability implementation、MCP server、Web Console、MCP Git managers、executor workflow、
  continue workflow、project patch、dangerous action guard、state/workflow/service lifecycle files；
- scripts、adapters、schemas、workflow、state、runtime、logs、reports、audits、executor sessions、lock files。

验收命令：compileall、decision contract test、full unittest discovery、self-hosting smoke、
`git diff --check`、`git status --short`。

人工验收：v1.6 是 docs/tests-only 或解释偏离；不加 restart/reload/kill/apply；不加 Web business route；
不加 MCP mutation tool；不 mutate service lifecycle；不授权 Git fetch/pull/push/tag/release；needed 只产生
operator handoff；unknown 只产生 bounded read-only diagnostics；任何 state 都不授权 automatic action。

非目标：同 v1.5 的 service/restart/reload/Git mutation/executor/state/operator execution/auth/notification 边界。

### v1.6.1：State Lineage Reconciliation Support V1

源 prompt：`.colameta/prompts/v1.6.1.md`

中文 companion：`.colameta/prompts/zh-CN/v1.6.1.zh-CN.md`

目标：增加 preview-first Runner state lineage reconciliation，让人工完成 receipt 能受控绑定回
Runner state，为 v1.7 执行前修正 Git reality 和 Runner state 的分歧。

允许修改文件：

- `runner/state_lineage_reconciliation.py`
- `runner/mcp_executor_workflow.py`
- `runner/mcp_server.py`
- `tests/test_state_lineage_reconciliation.py`

禁止修改边界：

- runtime observability、runtime version decision、Web Console、MCP Git managers、service lifecycle；
- scripts、adapters、schemas、workflow、state、runtime、logs、reports、audits、executor sessions、lock files。

验收命令：compileall、state lineage reconciliation test、full unittest discovery、self-hosting smoke、
`git diff --check`、`git status --short`。

人工验收：preview 生成可审计 before/after summary 且不运行 executor；apply 要求 explicit preview_id，
并在 HEAD、worktree cleanliness、plan membership、local commit presence 或 evidence 变化时 fail closed；
可将 v1.5 绑定 `582f047...`、v1.6 绑定 `8fb86aa...`，保持 v1.7 NOT_STARTED/next runnable；apply 只能碰
`.colameta/state.json` 和 controlled preview bookkeeping；不改 source/docs/tests/plan/prompt；不 executor run、
Git remote operation、tag/release、restart/reload/kill 或 service lifecycle mutation。

非目标：executor run/bounded loop/fix round、v1.7 evaluator implementation、Web Console route changes、
Web mutation surface、Git remote mutation、service lifecycle mutation、直接手工编辑 state、commit/push。

### v1.7：Runtime Version Status Decision Evaluator V1

源 prompt：`.colameta/prompts/v1.7.md`

中文 companion：`.colameta/prompts/zh-CN/v1.7.zh-CN.md`

目标：增加纯 decision evaluator，把 runtime version status 翻译成结构化决策对象，不授权
restart/reload/kill/apply。

允许修改文件：

- `runner/runtime_version_decision.py`
- `tests/test_runtime_version_decision.py`

禁止修改边界：

- runtime observability、MCP server、Web Console、MCP Git managers、executor workflow、continue workflow、
  project patch、dangerous action guard、state/workflow/service lifecycle files；
- scripts、adapters、schemas、workflow、state、runtime、logs、reports、audits、executor sessions、lock files。

验收命令：compileall、runtime version decision test、decision contract test、full unittest discovery、
self-hosting smoke、`git diff --check`、`git status --short`。

人工验收：只新增 pure evaluator；输入 `restart_needed_state`，输出 `decision_kind`、
`operator_notice_required`、`diagnostics_required`、`forbidden_actions`；not_needed 映射 normal operation；
needed 只映射 operator handoff notice；unknown 只映射 bounded read-only diagnostics；unknown/invalid fail closed；
不增加 MCP tool、Web route、service lifecycle mutation、state mutation、executor workflow mutation 或 Git remote mutation。

非目标：restart/reload/kill/apply、service/config/Web/MCP mutation、Git push/fetch/pull/tag/release、
executor/state/operator execution/auth/notification/background monitor。

### v1.8：Validation Report Truth-Source Hardening

源 prompt：`.colameta/prompts/v1.8.md`

中文 companion：`.colameta/prompts/zh-CN/v1.8.zh-CN.md`

目标：加固 executor validation reporting，确保 structured reports 和 audit packages 不会把失败或冲突
的 command evidence 总结为 passed。command records 和 exit codes 是真相源。

允许修改文件：

- `runner/executor_validation_truth.py`
- `runner/executor_run_reports.py`
- `runner/executor_run_workflow.py`
- `runner/mcp_executor_workflow.py`
- `tests/test_executor_validation_truth.py`
- `tests/test_executor_run_reports_truth_source.py`

禁止修改边界：

- runtime observability、runtime version decision、Web Console、MCP Git managers、continue workflow、
  project patch、dangerous action guard、state/workflow/service lifecycle files；
- scripts、adapters、schemas、workflow、state、runtime、logs、reports、audits、executor sessions、lock files。

验收命令：

- `python3 -m compileall -q runner scripts adapters schemas tests`
- `python3 -m unittest tests.test_executor_validation_truth`
- `python3 -m unittest tests.test_executor_run_reports_truth_source`
- `python3 scripts/self_hosting_smoke.py`
- `git diff --check`
- `git status --short`

人工验收：exit_code 非零不能产生 `validation_status_summary=passed`；status/exit_code mismatch 要暴露
`validation_inconsistent=true`；覆盖 v1.7 incident shape；executor-run 和 version audit packages 保留
structured command evidence；`get_audit_package(section='validation')` 暴露 Commander 审查所需 truth-source fields；
不改变 runtime/version feature，不新增 Web route、Git remote mutation、service lifecycle mutation 或 Runner state mutation；
full unittest discovery 若因环境 socket block 失败，不得谎报 passed。

非目标：runtime/version feature work、v1.7 rerun 或 state lineage reapply、restart/reload/kill/apply、
Web Console route changes、Git remote operations、service lifecycle mutation、Runner state mutation 或
continue-next-version、manual validation apply、刷新旧 v1.7 audit packages、commit/push/tag/release。

### v1.9：Runtime Loaded-Code Verification / Post-Commit Reload Awareness

源 prompt：`.colameta/prompts/v1.9.md`

中文 companion：`.colameta/prompts/zh-CN/v1.9.zh-CN.md`

目标：增加只读 runtime loaded-code verification，让 MCP/Web operator 能判断 running process 是否仍在
服务旧 module source。只报告 reload awareness，不授权也不执行 restart/reload/kill/apply。

允许修改文件：

- `runner/runtime_observability.py`
- `runner/mcp_server.py`
- `tests/test_runtime_observability.py`
- `tests/test_mcp_runtime_observability.py`
- `tests/test_runtime_loaded_code_verification.py`
- `docs/runtime-loaded-code-verification.md`
- `README.md`
- `README.zh-CN.md`

禁止修改边界：

- runtime version decision、Web Console、MCP Git managers、executor workflow、continue workflow、project patch、
  dangerous action guard、state/workflow/service lifecycle files；
- scripts、adapters、schemas、workflow、state、runtime、logs、reports、audits、executor sessions、lock files。

验收命令：compileall、runtime observability tests、MCP runtime observability tests、runtime loaded-code
verification test、self-hosting smoke、`git diff --check`、`git status --short`。

人工验收：`get_runtime_version_status` 保持 MCP read-only tool、`mcp:read`、`read_only=true`、
`side_effects=false`；响应暴露 `runtime_loaded_code_stale` 和 `reload_needed_for_verification`，且只是只读状态；
HEAD 和 module hashes 都匹配时报 not stale；project checkout HEAD 不同或 loaded module source changed 时报 stale；
unknown HEAD fail closed 到 reload needed for verification；dirty/changed source evidence 只产生 operator-facing reload awareness；
不授权 restart、reload、kill、apply、service lifecycle mutation、executor workflow mutation 或 Git remote mutation。

非目标：automatic restart/reload、kill process、service lifecycle mutation、reload preview/apply、Web business route、
MCP mutation tool、Git fetch/pull/push/tag/release、executor workflow mutation、state mutation、background monitor/
notification system、通过 shell fallback 或 remote Git operation 做 full Git dirty detection。

### v1.10：Executor Session Head Mismatch Classification

源 prompt：`.colameta/prompts/v1.10.md`

中文 companion：`.colameta/prompts/zh-CN/v1.10.zh-CN.md`

目标：把 executor-session HEAD mismatch 分类为 active operation risk、completed idle stale metadata 或
unknown fail-closed state，并暴露清楚的只读 status message；不 mutate runtime、Git 或 service lifecycle state。

允许修改文件：

- `runner/executor_session_head_mismatch.py`
- `runner/executor_session.py`
- `runner/web_console_presenter.py`
- `runner/web_console.py`
- `tests/test_executor_session_head_mismatch.py`
- `tests/test_web_console_security.py`

禁止修改边界：

- `/home/jenn/tools/colameta/**`
- runtime observability、runtime version decision、MCP Git managers、dangerous action guard、state/service lifecycle files；
- scripts、adapters、schemas、workflow、state、runtime、logs、reports、audits、executor sessions、lock files。

验收命令：

- `python3 -m compileall -q runner scripts adapters schemas tests`
- `python3 -m unittest tests.test_executor_session_head_mismatch`
- `python3 -m unittest tests.test_runtime_loaded_code_verification`
- `python3 -m unittest tests.test_executor_run_reports_truth_source`
- `python3 -m unittest discover -s tests`
- `python3 scripts/self_hosting_smoke.py`
- `git diff --check`
- `git status --short`

人工验收：`completed_idle_stale_session` 必须显示为历史 resume metadata，不是 executor 正在运行；
`active_operation_head_mismatch` 阻止 automatic resume/start 并要求 operator judgment；`unknown_head_mismatch`
fail closed 且带 reason/message；任何分类都不授权 restart/reload/kill/apply/commit/push；status surface 显示可读
classification message，不只是 raw `head_mismatch`；v1.9 runtime loaded-code verification 和 validation truth-source
行为不回退。

非目标：清理、删除或重写 executor-session.json；restart/reload/kill/service lifecycle/runtime process management；
启动 executor 或运行 bounded loop；Git commit/push/fetch/pull/tag/release/remote mutation；修改
`/home/jenn/tools/colameta`；修改 dangerous action guards 或 Git remote mutation policy。

### v1.16：Connector Runtime Health MCP Closeout Tool V1

源 prompt：`.colameta/prompts/v1.16.md`

目标：把 connector/runtime 真实可用性闭环暴露成只读 MCP 工具。它同时看 runtime freshness、
本地 Web/MCP 服务证据，以及调用方提供的 sanitized tunnel-client / control-plane 证据；没有外部
connector 证据时必须 fail closed，不能把本地健康误写成外部可用。

允许修改文件：

- `runner/runtime_observability.py`
- `runner/mcp_server.py`
- `scripts/runner_cli.py`
- `tests/test_mcp_runtime_observability.py`
- `tests/test_runner_cli.py`
- `docs/connector-runtime-health-observability.md`
- `docs/web-gpt-service-entrypoint.zh-CN.md`

禁止修改边界：

- `.env`、secrets、tokens、credentials、cookies、provider/auth/proxy config；
- `/home/jenn/tools/tunnel-client/**`、`/home/jenn/tools/colameta/**`、`~/.codex/**`、
  `~/.config/tunnel-client/**`；
- `.colameta/state.json`、`.colameta/decisions.json`、`.colameta/memory.md`、
  `.colameta/todolist.json`。

验收命令：compileall runtime/MCP/CLI，focused MCP runtime observability 和 CLI tests，`git diff --check`。

人工验收：`get_connector_runtime_health_status` 在 normal MCP profile 可见，仍是 `mcp:read`、
`read_only=true`、`side_effects=false`；缺 tunnel-client/control-plane evidence 时 closeout blocked；
有 sanitized healthy evidence 时可以进入 `connector_closeout_ready`；任何 token、Bearer、secret、
credential、cookie、api key、provider raw response 字符串不得回显。

非目标：读取 tunnel-client config/logs/runtime key、修网络/代理/provider、重启 tunnel-client、
替换稳定服务、外部 paid provider probe、executor run、route transition、ReviewDecision、GateEvent、
Delivery State accepted、push、release、deploy。

### v1.17：Connector Tunnel Evidence Receipt And Closeout Packet V1

源 prompt：`.colameta/prompts/v1.17.md`

目标：补一份受控 connector/tunnel closeout receipt 格式，把真实可用性证据、缺口和 closeout decision
写成可审查证据包。它只消费 approved status surface 的 sanitized evidence，不读取 secret-bearing
原始材料，也不自动修复 connector/tunnel。

允许修改文件：

- `docs/connector-runtime-health-observability.md`
- `docs/stable-replacement-receipts/*.md`
- `docs/connector-tunnel-closeout-receipts/*.md`
- `tests/test_mcp_runtime_observability.py`

禁止修改边界：同 v1.16，额外强调不写 Delivery State accepted，不创建 ReviewDecision / GateEvent，
不做 stable service replacement、executor run、route transition、push、release 或 deploy。

验收命令：focused MCP runtime observability test，`git diff --check`。

人工验收：receipt 能区分 local Web/MCP healthy、runtime fresh、tunnel-client healthy/unverified/degraded、
control-plane healthy/unverified/degraded；receipt 不包含 raw token、cookie、credential、provider response、
tunnel-client config、proxy config 或 private memory；任一外部证据缺失时 closeout 仍 blocked。

非目标：自动 connector repair、tunnel-client restart、proxy/provider mutation、stable replacement、
executor run、route transition、Delivery State accepted、ReviewDecision、GateEvent、commit、push、release、
deploy。

---

## 4. 总体边界复述

这份 plan 的共同边界是：

- plan/prompt 可以定义版本任务，但不自动授权 commit、push、executor run 或 route transition；
- allowed_files 只在对应 version 执行时成立，不能跨版本借用；
- forbidden_files 明确保护 state、runtime、logs、reports、audits、executor sessions、lock files 和远端 Git mutation 面；
- acceptance command 的失败不能被写成通过；
- Web remote Git mutation、service lifecycle mutation、restart/reload/kill/apply 都需要单独授权，不能从只读 status 信号中推导。

中文解释：这份中文镜像的作用是让 Commander 能读懂机器计划；它不是新的执行令牌。
