# Version 中文任务书：Stage 0 / v0.4 执行器会话 HEAD 分类报告

```yaml id="version-stage-00-v0-4-zh-cn-summary"
chinese_companion:
  source_document: docs/taskbooks/versions/stage-00/VERSION_STAGE_00_V0_4_EXECUTOR_SESSION_HEAD_CLASSIFICATION_REPORT.md
  source_sha256: e7efc8b3560c8e3476d5ebeb9bc44659e74a95c725911ee82eaa27a33643452c
  translation_status: companion_draft
  authority_status: planning_reference_only
version_execution_taskbook:
  version_id: stage_00_v0_4_executor_session_head_classification_report
  version: v0.4
  chinese_name: 执行器会话 HEAD 分类报告
  status: discussion_draft
  created_from_head_meaning: historical_creation_baseline_not_execution_or_freeze_snapshot
  execution_authorization_status: not_authorized
  session_cleanup_authorized: false
  executor_run_authorized: false
```

## 1. 这份任务书是什么

这是 Stage 0 的第四份 Version 任务书草稿。

本版本叫：

```text
Executor Session HEAD Classification Report
```

中文意思是：

```text
执行器会话 HEAD 分类报告
```

它的核心任务是：把 executor session 记录的 HEAD 和当前 Git HEAD 的关系说清楚。
如果出现 HEAD mismatch，要区分它到底是正在运行的旧 HEAD 风险、历史 stale session
metadata、证据不足的 unknown，还是没有 mismatch。

它现在不是执行授权，不授权清理 session，不授权启动或恢复 executor，不授权 commit，
不授权 push，也不授权任何 delivery state 变化。

## 2. 父级绑定

这份 Version 绑定到：

- Master Taskbook：`PROJECT_MASTER_TASKBOOK.md`
- Stage Taskbook：`docs/taskbooks/stages/STAGE_00_BASELINE_CLOSEOUT.md`
- Stage 0-6 freeze packet：`docs/taskbooks/stages/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_0_6.md`
- v0.1：仓库与运行态现实快照
- v0.2：验证真相来源报告
- v0.3：运行态新鲜度报告
- v1.10：Executor Session Head Mismatch Classification 既有实现历史

中文解释：v0.4 不是重新实现 v1.10，而是把 v1.10 的分类规则作为报告边界来观察。

## 3. 目标

本版本未来如果被单独授权执行，要生成一份 executor session HEAD 分类报告。报告需要说明：

- 当前 Git HEAD；
- executor session 里记录的 HEAD，或为什么未知；
- session HEAD 是否匹配当前 HEAD；
- operation 是否 running，或为什么未知；
- runner/latest-run 状态，或为什么未知；
- worktree 是否 clean，或为什么未知；
- 分类结果；
- 操作者提示信息；
- 哪些证据没拿到；
- 哪些风险仍然存在。

它的目标不是清理 session，也不是启动 executor。

## 4. 分类词是什么意思

本版本只允许使用这些分类：

- `none` = 没有 mismatch，或没有 session，或 session HEAD 和当前 Git HEAD 一致；
- `active_operation_head_mismatch` = 有活跃 operation，且 session HEAD 和当前 Git HEAD 不同；
- `completed_idle_stale_session` = 历史完成的 idle session metadata 记录了旧 HEAD，但证据显示没有活跃 operation；
- `unknown_head_mismatch` = 存在 HEAD mismatch，但证据不足，无法判断是活跃风险还是历史 metadata。

中文解释：这些分类只是解释 executor session 风险，不是 delivery_state，不是授权。

## 5. 允许和禁止的文件

未来如果 Commander 单独授权执行，本版本最多只能写两份报告：

- `docs/taskbooks/versions/stage-00/evidence/VERSION_STAGE_00_V0_4_EXECUTOR_SESSION_HEAD_CLASSIFICATION_REPORT.md`
- `docs/taskbooks/versions/stage-00/evidence/zh-CN/VERSION_STAGE_00_V0_4_EXECUTOR_SESSION_HEAD_CLASSIFICATION_REPORT.zh-CN.md`

它可以只读查看 Master、Stage、v0.1、v0.2、v0.3、v1.10 prompt、相关 runner/test 文件、
`.colameta/state.json` 和 `.colameta/runtime/**`。

`.colameta/runtime/**` 和 `.colameta/state.json` 只能作为易变运行态观测元数据。
它们不能作为 delivery_state、accepted、blocked、executor truth 的权威来源，也不能
变成清理、重写、启动、恢复或 kill executor/session 的许可。

## 6. 候选验收命令

英文任务书列出的候选命令都是观察命令，不是 executor 控制命令：

- `git status --short --branch`
- `git rev-parse HEAD`
- `git rev-parse origin/main`
- `git rev-list --left-right --count origin/main...HEAD`
- `test -e .colameta/runtime/executor-session.json && sha256sum ... || true`
- `curl -fsS http://127.0.0.1:8801/api/status || true`
- `rg -n "active_operation_head_mismatch|completed_idle_stale_session|unknown_head_mismatch|head_mismatch|executor_session_head_mismatch" runner/executor_session.py runner/web_console.py runner/web_console_presenter.py tests/test_executor_session_head_mismatch.py .colameta/prompts/v1.10.md`
- `sha256sum` 检查 Master、Stage、v0.1、v0.2、v0.3 的 hash
- `git diff --check` 针对未来报告文件
- `rg -n` 检查未来报告是否包含关键字段

这些命令现在只是候选命令，不代表已经执行，也不代表已经授权执行。

如果 session 文件或 status endpoint 不可用，报告必须写成 known_unknown 或 unavailable，
不能顺手创建、清理、重写或删除 session metadata。

## 7. 证据包是什么意思

`Evidence Package` = 证据包。

中文意思是：把 Git HEAD、session HEAD、operation running 证据、分类结果、
未知项、剩余风险收起来给审查者看。证据包不是批准，不会改变 delivery state。

本版本未来的证据包至少要包括：

- executor session HEAD classification report；
- 中文 executor session HEAD classification report companion；
- session 或 known_unknown 摘要；
- classification boundary summary；
- git_head_check；
- session_inventory_or_known_unknown；
- classification_vocabulary_check；
- dangerous_action_non_authorization_check；
- report_schema_check；
- not_validated；
- remaining_risks。

## 8. 停止条件

遇到以下情况必须停：

- 当前仓库不是 `/home/jenn/src/colameta-dev`；
- session 探测需要写入或清理 session metadata；
- 服务探测需要重启、reload 或登录；
- 命令会修改运行时或仓库中不允许的路径；
- 允许输出路径里已有不属于本次授权执行创建的 untracked 文件；
- 命令需要 localhost 以外网络或凭据；
- 证据无法区分 active operation 和 historical idle metadata；
- 用户请求滑向 executor start、resume、cleanup 或 runtime reload。

## 9. 不做什么

本版本不做：

- start executor；
- resume executor；
- kill executor；
- clean executor session；
- rewrite executor session；
- restart service；
- reload runtime code；
- 修改 `/home/jenn/tools/colameta`；
- 跑测试；
- 修改 runner 代码；
- 修改 tests；
- 修改 `.colameta/plan.json`；
- 修改 Master 或 Stage Taskbook；
- 修复 classification implementation；
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

如果未来要真的执行 executor session HEAD 分类报告，需要新的精确授权口令：

```text
AUTHORIZE_STAGE_00_V0_4_EXECUTOR_SESSION_HEAD_CLASSIFICATION_REPORT_EXECUTION_FOR_EXACT_HASH_ONLY
```

中文解释：现在只是把第四份 Version 任务书写出来，不能清理 session、开 executor、
写报告、commit 或 push。
