# Version 中文任务书：Stage 0 / v0.2 验证真相来源报告

```yaml id="version-stage-00-v0-2-zh-cn-summary"
chinese_companion:
  source_document: docs/taskbooks/versions/stage-00/VERSION_STAGE_00_V0_2_VALIDATION_TRUTH_SOURCE_REPORT.md
  source_sha256: c2d903ce992e96f02a1672c61269a0a990cb8a163db7b8c56ccec4ccc68fcb26
  translation_status: companion_draft
  authority_status: planning_reference_only
version_execution_taskbook:
  version_id: stage_00_v0_2_validation_truth_source_report
  version: v0.2
  chinese_name: 验证真相来源报告
  status: discussion_draft
  created_from_head_meaning: historical_creation_baseline_not_execution_or_freeze_snapshot
  execution_authorization_status: not_authorized
  test_execution_authorized: false
```

## 1. 这份任务书是什么

这是 Stage 0 的第二份 Version 任务书草稿。

本版本叫：

```text
Validation Truth Source Report
```

中文意思是：

```text
验证真相来源报告
```

它的核心任务是：说明验证结论到底来自哪里。比如一个地方写了 `PASSED`，
我们要知道这到底是某个命令真的跑过并通过，还是只是 runtime summary label，
或者只是历史报告里的摘要。

它现在不是执行授权，不授权跑测试，不授权 executor，不授权 commit，不授权 push，
也不授权任何 delivery state 变化。

## 2. 父级绑定

这份 Version 绑定到：

- Master Taskbook：`PROJECT_MASTER_TASKBOOK.md`
- Stage Taskbook：`docs/taskbooks/stages/STAGE_00_BASELINE_CLOSEOUT.md`
- Stage 0-6 freeze packet：`docs/taskbooks/stages/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_0_6.md`
- 前一份 Version：`docs/taskbooks/versions/stage-00/VERSION_STAGE_00_V0_1_REPOSITORY_RUNTIME_REALITY_SNAPSHOT.md`

中文解释：v0.1 负责看清仓库和运行态现实，v0.2 负责把验证相关的“真凭实据”
和“摘要标签”分开。

## 3. 目标

本版本未来如果被单独授权执行，要生成一份验证真相来源报告。报告需要说明：

- 当前有哪些验证声明；
- 哪些验证命令被声明过；
- 哪些验证命令只是存在，但没有运行；
- 哪些状态只是标签，比如 `PASSED`、`COMPLETED`、`BLOCKED`、`VERSION_PASSED`；
- 哪些标签有当前命令证据支撑；
- 哪些标签没有当前命令证据支撑；
- 哪些验证还没有做；
- 哪些未知项需要后续处理。

它的目标不是修验证系统，也不是跑完整测试。

## 4. 验证真相来源是什么意思

`Validation Truth Source` = 验证真相来源。

中文意思是：不要只相信“通过/失败”几个字，而是要追问：

- 哪个命令跑了？
- 输出在哪里？
- 什么时候跑的？
- 跑的是当前代码吗？
- 有没有只是旧报告或 runtime summary？
- 没跑的检查有没有明确写出来？

## 5. 允许和禁止的文件

未来如果 Commander 单独授权执行，本版本最多只能写两份报告：

- `docs/taskbooks/versions/stage-00/evidence/VERSION_STAGE_00_V0_2_VALIDATION_TRUTH_SOURCE_REPORT.md`
- `docs/taskbooks/versions/stage-00/evidence/zh-CN/VERSION_STAGE_00_V0_2_VALIDATION_TRUTH_SOURCE_REPORT.zh-CN.md`

它可以只读查看 Master、Stage、v0.1、plan、state、runner、tests、Git 状态和
验证配置文件。

`.colameta/state.json` 只能作为易变运行态观测元数据。它不能作为 validation truth、
delivery_state、accepted、blocked、executor truth 的权威来源，也不能替代命令证据。

它禁止修改：

- `/home/jenn/tools/colameta/**`
- `runner/**`
- `tests/**`
- `PROJECT_MASTER_TASKBOOK.md`
- `docs/taskbooks/stages/**`
- v0.1 Version Taskbook；
- `.colameta/plan.json`
- `.colameta/prompts/**`
- `.git/**`
- `.env`、secret、credential 相关文件。

## 6. 候选验收命令

英文任务书列出的候选命令主要是盘点命令，不是执行测试命令：

- `git status --short --branch`
- `git rev-parse HEAD`
- `git rev-parse origin/main`
- `git rev-list --left-right --count origin/main...HEAD`
- `rg -n "unittest|pytest|compileall|smoke|validation|acceptance_commands|manual_acceptance|VERSION_PASSED|PASSED|COMPLETED|BLOCKED" runner tests docs .colameta`
- `find runner tests docs .colameta -maxdepth 3` 查找受控目录里的验证配置文件
- `find . -maxdepth 1` 只查找 repo 顶层验证配置文件
- `git log -5 --oneline`
- `sha256sum` 检查 Master、Stage、v0.1 的 hash
- `git diff --check` 针对未来报告文件
- `rg -n` 检查未来报告是否包含关键字段

这些命令现在只是候选命令，不代表已经执行，也不代表已经授权执行。

跑 unit tests、smoke tests 或 executor validation 都不在本版本范围内。报告可以
盘点这些命令，但必须把它们标成 `commands_not_run`。

## 7. 证据包是什么意思

`Evidence Package` = 证据包。

中文意思是：把验证声明、命令盘点、标签来源、没跑的检查、未知项、剩余风险收起来
给审查者看。证据包不是批准，不会改变 delivery state。

本版本未来的证据包至少要包括：

- validation truth source report；
- 中文 validation truth source report companion；
- command inventory summary；
- validation inventory check；
- taskbook hash check；
- label vs evidence boundary check；
- report schema check；
- not_validated；
- remaining_risks。

`commands_run` = 已运行命令。中文意思是：本次授权执行中实际跑过的命令。

`commands_not_run` = 未运行命令。中文意思是：存在或被声明过，但本次没有跑的命令。

`labels_observed` = 观察到的标签。中文意思是：例如 `PASSED` 这类被看到的状态词。

## 8. 停止条件

遇到以下情况必须停：

- 当前仓库不是 `/home/jenn/src/colameta-dev`；
- 验证盘点需要真的跑测试；
- 命令会修改运行时或仓库中不允许的路径；
- 允许输出路径里已有不属于本次授权执行创建的 untracked 文件；
- 命令需要网络或凭据；
- 证据无法区分观测事实和摘要标签；
- 用户请求滑向验证修复或测试执行。

## 9. 不做什么

本版本不做：

- 跑测试；
- 修改 runner 代码；
- 修改 tests；
- 修改验证命令；
- 修改 `.colameta/plan.json`；
- 修改 Master 或 Stage Taskbook；
- 修改 `/home/jenn/tools/colameta`；
- 重启服务；
- 运行 executor；
- 修复验证真相来源；
- 判断 delivery state；
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

如果未来要真的执行验证真相来源报告，需要新的精确授权口令：

```text
AUTHORIZE_STAGE_00_V0_2_VALIDATION_TRUTH_SOURCE_REPORT_EXECUTION_FOR_EXACT_HASH_ONLY
```

中文解释：现在只是把第二份 Version 任务书写出来，不能直接跑测试、开 executor、
写报告、commit 或 push。
