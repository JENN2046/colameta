# Version 中文任务书：Stage 0 / v0.3 运行时代码新鲜度报告

```yaml id="version-stage-00-v0-3-zh-cn-summary"
chinese_companion:
  source_document: docs/taskbooks/versions/stage-00/VERSION_STAGE_00_V0_3_RUNTIME_FRESHNESS_REPORT.md
  source_sha256: 7234b7a38116fcd72115023d8cf35335bb5b8f7324ecbc6613153c7946b7ea1c
  translation_status: companion_draft
  authority_status: planning_reference_only
version_execution_taskbook:
  version_id: stage_00_v0_3_runtime_freshness_report
  version: v0.3
  chinese_name: 运行时代码新鲜度报告
  status: discussion_draft
  created_from_head_meaning: historical_creation_baseline_not_execution_or_freeze_snapshot
  execution_authorization_status: not_authorized
  service_restart_authorized: false
  runtime_reload_authorized: false
```

## 1. 这份任务书是什么

这是 Stage 0 的第三份 Version 任务书草稿。

本版本叫：

```text
Runtime Freshness Report
```

中文意思是：

```text
运行时代码新鲜度报告
```

它的核心任务是：说明当前正在运行的 ColaMeta 服务是否能被解释清楚。比如服务
是不是从 `/home/jenn/tools/colameta` 这个稳定运行目录启动，服务接口是否可读，
运行中的代码是否可能是当前期望版本，哪些地方仍然未知。

它现在不是执行授权，不授权重启服务，不授权 runtime reload，不授权 executor，
不授权 commit，不授权 push，也不授权任何 delivery state 变化。

## 2. 父级绑定

这份 Version 绑定到：

- Master Taskbook：`PROJECT_MASTER_TASKBOOK.md`
- Stage Taskbook：`docs/taskbooks/stages/STAGE_00_BASELINE_CLOSEOUT.md`
- Stage 0-6 freeze packet：`docs/taskbooks/stages/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_0_6.md`
- v0.1：仓库与运行态现实快照
- v0.2：验证真相来源报告

中文解释：v0.1 看整体现实，v0.2 看验证证据，v0.3 专门看正在运行的服务代码
是否“新鲜”和可解释。

## 3. 目标

本版本未来如果被单独授权执行，要生成一份运行态新鲜度报告。报告需要说明：

- 稳定服务运行目录；
- 稳定 CLI 路径；
- 自进化 repo 路径；
- 稳定 CLI 是否存在；
- Web Console 状态接口是否可读；
- MCP endpoint 路径是否可解释；
- 服务状态接口返回了什么，或为什么不可用；
- 进程证据是否能看到；
- 运行代码是否 current、stale、unavailable 或 unknown；
- 哪些未知项需要后续处理。

它的目标不是重启服务，也不是修运行态。

## 4. 运行时代码新鲜度是什么意思

`Runtime Freshness` = 运行态新鲜度。

中文意思是：不是只问“服务有没有跑”，而是要问：

- 服务从哪里启动？
- 运行目录是不是 `/home/jenn/tools/colameta`？
- 它管理的项目 repo 是不是 `/home/jenn/src/colameta-dev`？
- 它加载的代码是否和当前期望版本一致？
- 如果看不出来，要明确写成 unknown。

## 5. 允许和禁止的文件

未来如果 Commander 单独授权执行，本版本最多只能写两份报告：

- `docs/taskbooks/versions/stage-00/evidence/VERSION_STAGE_00_V0_3_RUNTIME_FRESHNESS_REPORT.md`
- `docs/taskbooks/versions/stage-00/evidence/zh-CN/VERSION_STAGE_00_V0_3_RUNTIME_FRESHNESS_REPORT.zh-CN.md`

它可以只读查看 Master、Stage、v0.1、v0.2、plan、state、runner、tests、Git 状态、
以及稳定 CLI 路径 `/home/jenn/tools/colameta/.venv/bin/colameta`。

`/home/jenn/tools/colameta` 只能只读观察。不能修改、重装、reload、restart，也不能
把证据写进去。

`.colameta/state.json` 只能作为易变运行态观测元数据。它不能作为 runtime freshness、
delivery_state、accepted、blocked、executor truth 的权威来源，也不能替代 endpoint
或 process 证据。

## 6. 候选验收命令

英文任务书列出的候选命令都是观察命令，不是服务控制命令：

- `git status --short --branch`
- `git rev-parse HEAD`
- `git rev-parse origin/main || true`
- `git rev-list --left-right --count origin/main...HEAD || true`
- `test -x /home/jenn/tools/colameta/.venv/bin/colameta`
- `readlink -f /home/jenn/tools/colameta/.venv/bin/colameta`
- `ps -ef | rg "colameta|8801|8766" || true`
- `curl -fsS http://127.0.0.1:8801/api/status || true`
- `sha256sum` 检查 Master、Stage、v0.1、v0.2 的 hash
- `git diff --check` 针对未来报告文件
- `rg -n` 检查未来报告是否包含关键字段，包括 `not_validated`

这些命令现在只是候选命令，不代表已经执行，也不代表已经授权执行。

如果 `curl` 失败，报告必须写成 unavailable 或 known_unknown，不能顺手重启服务。
`|| true` 的作用是让 endpoint 不可用也能继续记录证据，而不是把失败伪装成通过。
如果本地 `origin/main` 跟踪引用不存在，报告必须写成 `known_unknown`，不能自动
`fetch` 或联系远端。

`ps -ef` 看到的进程命令行证据必须先脱敏再写进报告。报告不能写入 secrets、
tokens、credential paths、私有环境值或无关进程细节。

## 7. 证据包是什么意思

`Evidence Package` = 证据包。

中文意思是：把运行目录、CLI 路径、endpoint 结果、进程证据、新鲜度分类、未知项、
剩余风险收起来给审查者看。证据包不是批准，不会改变 delivery state。

本版本未来的证据包至少要包括：

- runtime freshness report；
- 中文 runtime freshness report companion；
- endpoint 或 unavailable 摘要；
- process evidence 或 known_unknown 摘要；
- runtime path check；
- endpoint probe 或 unavailable reason；
- freshness classification boundary check；
- report schema check；
- not_validated；
- remaining_risks。

`freshness_classification` = 新鲜度分类。中文意思是：把运行态分成 current、stale、
unavailable、unknown，但这个分类只是证据判断，不是 delivery_state。

## 8. 停止条件

遇到以下情况必须停：

- 当前仓库不是 `/home/jenn/src/colameta-dev`；
- 稳定运行目录探测需要修改文件；
- 服务探测需要重启、reload 或登录；
- 命令会修改运行时或仓库中不允许的路径；
- 允许输出路径里已有不属于本次授权执行创建的 untracked 文件；
- 命令需要 localhost 以外网络或凭据；
- 证据无法区分已加载 runtime 和自进化 repo；
- 用户请求滑向 runtime reload、restart 或 deploy。

## 9. 不做什么

本版本不做：

- 重启服务；
- reload runtime code；
- 修改 `/home/jenn/tools/colameta`；
- 重装或更新依赖；
- 运行 executor；
- 跑测试；
- 修改 runner 代码；
- 修改 tests；
- 修改 `.colameta/plan.json`；
- 修改 Master 或 Stage Taskbook；
- 修复 runtime freshness；
- 判断 delivery_state；
- 产生 GateEvent；
- commit；
- push；
- release 或 deploy。

`GateEvent` = 状态门事件。中文意思是：只有 Delivery State Gate 产生的事件，
才能真正写入 delivery state 或 blocked 状态。本版本没有这个权力。

## 10. 下一道 Commander Gate

当前状态是：

```text
taskbook_draft_created
```

下一步应该先审查或修改这份 Version Taskbook。

如果未来要真的执行运行态新鲜度报告，需要新的精确授权口令：

```text
AUTHORIZE_STAGE_00_V0_3_RUNTIME_FRESHNESS_REPORT_EXECUTION_FOR_EXACT_HASH_ONLY
```

中文解释：现在只是把第三份 Version 任务书写出来，不能直接重启服务、reload、
开 executor、写报告、commit 或 push。
