# Version 中文任务书：Stage 0 / v0.1 仓库与运行态现实快照

```yaml id="version-stage-00-v0-1-zh-cn-summary"
chinese_companion:
  source_document: docs/taskbooks/versions/stage-00/VERSION_STAGE_00_V0_1_REPOSITORY_RUNTIME_REALITY_SNAPSHOT.md
  source_sha256: 6393181ffd38f46f319b2d3dd350e3749d59d22c0b588688a558308232897d8d
  translation_status: companion_draft
  authority_status: planning_reference_only
version_execution_taskbook:
  version_id: stage_00_v0_1_repository_runtime_reality_snapshot
  version: v0.1
  chinese_name: 仓库与运行态现实快照
  status: discussion_draft
  created_from_head_meaning: historical_creation_baseline_not_execution_or_freeze_snapshot
  execution_authorization_status: not_authorized
```

## 1. 这份任务书是什么

这是 Stage 0 的第一份 Version 任务书草稿。

`Version Execution Taskbook` = 版本执行任务书。中文意思是：把一个 Stage
下面的一次小交付拆成明确边界，说明目标、能读什么、能写什么、怎么验收、
什么时候停止、需要哪些证据。

本版本叫：

```text
Repository And Runtime Reality Snapshot
```

中文意思是：

```text
仓库与运行态现实快照
```

它的核心任务是：只读地看清当前仓库和运行服务的现实状态，然后把证据写成报告。

它现在不是执行授权，不授权 executor，不授权 commit，不授权 push，不授权服务重启，
也不授权任何 delivery state 变化。

## 2. 父级绑定

这份 Version 绑定到：

- Master Taskbook：`PROJECT_MASTER_TASKBOOK.md`
- Stage Taskbook：`docs/taskbooks/stages/STAGE_00_BASELINE_CLOSEOUT.md`
- Stage 0-6 freeze packet：`docs/taskbooks/stages/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_0_6.md`

中文解释：它只能服务 Stage 0 的“基线收束与执行状态清晰化”，不能反过来改变
Master 或 Stage 的边界。

## 3. 目标

本版本的目标是生成一份只读现实快照报告，报告里要说明：

- 当前分支；
- 当前 HEAD；
- `origin/main`；
- 本地与本地 `origin/main` 跟踪引用是否同步；
- worktree 是否干净；
- 是否有 untracked 文件；
- 稳定服务目录 `/home/jenn/tools/colameta` 是否存在；
- CLI `/home/jenn/tools/colameta/.venv/bin/colameta` 是否存在；
- Web Console 状态接口是否可读；
- runtime loaded-code freshness 是否可解释；
- executor session HEAD 是否匹配或是否未知；
- validation truth source 是什么；
- 哪些东西仍然未知。

这一步的重点是“看清楚并写下来”，不是“修好一切”。

## 4. 执行信封是什么意思

`Execution Envelope` = 执行信封。

中文意思是：真正执行前必须有一封边界信，明确：

- 可以读哪些文件；
- 可以写哪些文件；
- 不能碰哪些文件；
- 可以运行哪些命令；
- 什么时候必须停下；
- 最后报告到哪里。

英文任务书里已经写了一个候选执行信封，但它现在还没有被授权。

## 5. 允许和禁止的文件

未来如果 Commander 单独授权执行，本版本最多只能写两份报告：

- `docs/taskbooks/versions/stage-00/evidence/VERSION_STAGE_00_V0_1_REALITY_SNAPSHOT_REPORT.md`
- `docs/taskbooks/versions/stage-00/evidence/zh-CN/VERSION_STAGE_00_V0_1_REALITY_SNAPSHOT_REPORT.zh-CN.md`

它可以只读查看 Master、Stage、plan、state、runner、tests、Git 状态和服务状态。

`.colameta/state.json` 只能作为易变的运行态观测元数据。它不能作为
delivery_state、accepted、blocked、executor truth 的权威来源，也不能替代实时
仓库和运行服务证据。

它禁止修改：

- `/home/jenn/tools/colameta/**`
- `runner/**`
- `tests/**`
- `PROJECT_MASTER_TASKBOOK.md`
- `docs/taskbooks/stages/**`
- `.colameta/plan.json`
- `.colameta/prompts/**`
- `.git/**`
- `.env`、secret、credential 相关文件。

中文解释：这个版本最多写“报告”，不能顺手修代码，不能改计划，不能动稳定运行目录。

## 6. 候选验收命令

英文任务书列出的候选验收命令包括：

- `git status --short --branch`
- `git rev-parse HEAD`
- `git rev-parse origin/main || true`
- `git rev-list --left-right --count origin/main...HEAD || true`
- `test -x /home/jenn/tools/colameta/.venv/bin/colameta`
- `git log -1 --oneline`
- `git diff --name-status`
- `sha256sum PROJECT_MASTER_TASKBOOK.md docs/taskbooks/stages/STAGE_00_BASELINE_CLOSEOUT.md`
- `curl -fsS http://127.0.0.1:8801/api/status || true`
- `git diff --check` 针对未来报告文件
- `rg -n "known_unknowns|not_validated|remaining_risks|commands_run"` 针对未来报告文件
- `rg -n "source_document|source_sha256|known_unknowns|not_validated|remaining_risks"` 针对未来中文报告文件

这些命令现在只是候选命令，不代表已经执行，也不代表已经授权执行。

如果本地 `origin/main` 跟踪引用或服务接口不可读，不能假装通过，必须写成
known unknown 或 unavailable；不能自动 `fetch`、重启服务、reload 代码或联系远端补齐。

`known unknown` = 已知未知项。中文意思是：我们知道这件事还没确认，并且要写明
为什么未知、怎样才能确认。

## 7. 证据包是什么意思

`Evidence Package` = 证据包。

中文意思是：把“做了什么、看到了什么、哪些命令跑了、哪些没跑、还有什么风险”
收起来给审查者看。证据包不是批准，不会改变 delivery state。

本版本未来的证据包至少要包括：

- snapshot report；
- 中文 snapshot report companion；
- 命令证据摘要；
- Git 状态检查；
- Git 同步检查；
- taskbook hash 检查；
- runtime status probe 或 known unknown；
- report schema check；
- not_validated；
- remaining_risks。

`not_validated` = 未验证项。中文意思是：哪些事情没有被验证，必须明确列出。

`remaining_risks` = 剩余风险。中文意思是：即使报告完成后，仍然有哪些风险。

## 8. 停止条件

遇到以下情况必须停：

- 当前仓库不是 `/home/jenn/src/colameta-dev`；
- 稳定运行目录探测需要修改文件；
- 命令会修改运行时或仓库中不允许的路径；
- 允许输出路径里已有不属于本次授权执行创建的 untracked 文件；
- 服务状态探测需要重启或登录；
- Git 远端探测需要暴露凭据；
- 证据无法区分观测事实和摘要标签；
- 用户请求滑向代码加固或清理工程。

## 9. 不做什么

本版本不做：

- 修改 runner 代码；
- 修改 tests；
- 修改 `.colameta/plan.json`；
- 修改 Master 或 Stage Taskbook；
- 修改 `/home/jenn/tools/colameta`；
- 重启服务；
- 运行 executor；
- 自动清理 stale session；
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

如果未来要真的执行现实快照，需要新的精确授权口令：

```text
AUTHORIZE_STAGE_00_V0_1_REALITY_SNAPSHOT_EXECUTION_FOR_EXACT_HASH_ONLY
```

中文解释：现在只是把第一份 Version 任务书写出来，不能直接开 executor，也不能
直接写报告、commit 或 push。
