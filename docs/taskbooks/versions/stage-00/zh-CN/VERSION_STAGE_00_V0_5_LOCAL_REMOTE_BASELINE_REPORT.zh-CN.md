# Version 中文任务书：Stage 0 / v0.5 本地与远端基线报告

```yaml id="version-stage-00-v0-5-zh-cn-summary"
chinese_companion:
  source_document: docs/taskbooks/versions/stage-00/VERSION_STAGE_00_V0_5_LOCAL_REMOTE_BASELINE_REPORT.md
  source_sha256: a5a1a10aa0c0d73180399a1aa22e50d12a1b1215e762eb9d751299cdd9254bf0
  translation_status: companion_draft
  authority_status: planning_reference_only
version_execution_taskbook:
  version_id: stage_00_v0_5_local_remote_baseline_report
  version: v0.5
  chinese_name: 本地与远端基线报告
  status: discussion_draft
  created_from_head_meaning: historical_creation_baseline_not_execution_or_freeze_snapshot
  execution_authorization_status: not_authorized
  fetch_authorized: false
  push_authorized: false
  route_transition_authorized: false
```

## 1. 这份任务书是什么

这是 Stage 0 的第五份 Version 任务书草稿。

本版本叫：

```text
Local Remote Baseline Report
```

中文意思是：

```text
本地与远端基线报告
```

它的核心任务是：把当前本地分支、本地 HEAD、本地记录的 `origin/main`、ahead/behind、
未提交文件、未 push commit 和未知项分开说清楚。

它现在不是执行授权，不授权 `fetch`，不授权 `push`，不授权 `pull`，不授权 commit，
不授权 route transition，也不授权任何 delivery state 变化。

## 2. 父级绑定

这份 Version 绑定到：

- Master Taskbook：`PROJECT_MASTER_TASKBOOK.md`
- Stage Taskbook：`docs/taskbooks/stages/STAGE_00_BASELINE_CLOSEOUT.md`
- Stage 0-6 freeze packet：`docs/taskbooks/stages/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_0_6.md`
- v0.1：仓库与运行态现实快照
- v0.2：验证真相来源报告
- v0.3：运行态新鲜度报告
- v0.4：执行器会话 HEAD 分类报告

中文解释：v0.5 是 Stage 0 的最后一个方向，用来把“本地领先多少、远端跟踪引用在哪里、
是否有未提交内容”说清楚。

## 3. 目标

本版本未来如果被单独授权执行，要生成一份本地与远端基线报告。报告需要说明：

- 当前分支；
- 当前本地 HEAD；
- 当前本地 HEAD 的 commit subject；
- 本地 `origin/main` 跟踪引用；
- 本地分支相对 `origin/main` 的 ahead 数量；
- 本地分支相对 `origin/main` 的 behind 数量；
- 未 push commit 摘要，或为什么未知；
- worktree 是否 clean；
- staged、unstaged、untracked 文件状态；
- 没有执行 `fetch`、`pull`、`push`、`merge`、`rebase`；
- 哪些远端新鲜度信息因为没有联网同步而仍然未知。

它的目标不是同步远端，也不是推送代码。

## 4. 关键名词是什么意思

`origin/main local tracking ref` = 本地远端跟踪引用。

中文意思是：本地 Git 里记录的 `origin/main` 指针。它不是刚刚联网确认过的远端最新
状态，除非另有授权执行了 `fetch` 或远端探测。

`ahead_count` = 本地领先数量。

中文意思是：当前本地分支相对本地 `origin/main` 引用多出来的 commit 数量。
它不代表这些 commit 已经 push 到远端。

`behind_count` = 本地落后数量。

中文意思是：当前本地分支相对本地 `origin/main` 引用少了多少 commit。同样，它也是
基于本地引用计算出来的，不是实时远端真相。

## 5. 允许和禁止的文件

未来如果 Commander 单独授权执行，本版本最多只能写两份报告：

- `docs/taskbooks/versions/stage-00/evidence/VERSION_STAGE_00_V0_5_LOCAL_REMOTE_BASELINE_REPORT.md`
- `docs/taskbooks/versions/stage-00/evidence/zh-CN/VERSION_STAGE_00_V0_5_LOCAL_REMOTE_BASELINE_REPORT.zh-CN.md`

它可以只读查看 Master、Stage、v0.1、v0.2、v0.3、v0.4、中文 companion policy/index，
以及通过非变异 Git 命令查看 Git metadata。

它不能修改 `.git`，不能创建 commit，不能移动分支，不能 `fetch`，不能 `pull`，
不能 `push`，不能 `merge`，不能 `rebase`。

## 6. 本地远端跟踪引用边界

本版本必须明确：

- `origin/main` 是本地远端跟踪引用；
- ahead/behind 是基于本地引用算出来的；
- 没有单独授权 `fetch` 时，远端实时新鲜度没有验证；
- 没有执行远端同步；
- 本地 ahead commit 不等于已经 push。

中文解释：这个版本要防止一种常见误读：看到 `origin/main` 就以为已经看到了远端此刻
最新状态。没有 `fetch`，就不能这么说。

## 7. 候选验收命令

英文任务书列出的候选命令都是本地只读 Git 命令，不是同步命令：

- `git status --short --branch`
- `git rev-parse --abbrev-ref HEAD`
- `git rev-parse HEAD`
- `git rev-parse --verify origin/main || true`
- `git rev-list --left-right --count origin/main...HEAD || true`
- `git log --oneline --decorate --max-count=20 origin/main..HEAD || true`
- `git log --oneline --decorate --max-count=5 HEAD`
- `git diff --name-status`
- `git diff --cached --name-status`
- `git ls-files --others --exclude-standard`
- `sha256sum` 检查 Master、Stage、v0.1、v0.2、v0.3、v0.4 的 hash
- `git diff --check` 针对未来报告文件
- `rg -n` 检查未来报告是否包含关键字段

这些命令现在只是候选命令，不代表已经执行，也不代表已经授权执行。

本版本刻意不包含 `git fetch`、`git pull`、`git push`、`git merge`、`git rebase`。
如果本地 `origin/main` 跟踪引用不存在，报告必须把 `origin/main`、ahead/behind
和未 push commit inventory 写成 `known_unknown`，不能自动 `fetch` 或联系远端补齐。

## 8. 证据包是什么意思

`Evidence Package` = 证据包。

中文意思是：把当前本地 HEAD、本地 `origin/main`、ahead/behind、worktree 状态、
未 push commit、未知项和剩余风险收起来给审查者看。证据包不是批准，不会改变
delivery state。

本版本未来的证据包至少要包括：

- local remote baseline report；
- 中文 local remote baseline report companion；
- local head summary；
- local remote tracking ref summary；
- worktree status summary；
- branch_head_check；
- local_remote_tracking_ref_check；
- ahead_behind_check_from_local_refs；
- worktree_inventory_check；
- no_remote_action_check；
- report_schema_check；
- not_validated；
- remaining_risks。

## 9. 停止条件

遇到以下情况必须停：

- 当前仓库不是 `/home/jenn/src/colameta-dev`；
- 命令会执行 `fetch`、`pull`、`push`、`merge`、`rebase` 或更新 Git refs；
- 命令会在没有单独授权时联系远端；
- 命令会修改 `.git`；
- 命令会修改运行时或仓库中不允许的路径；
- 允许输出路径里已有不属于本次授权执行创建的 untracked 文件；
- 命令需要凭据或会暴露带凭据的 remote URL；
- 证据无法区分本地引用和实时远端真相；
- 用户请求滑向 push、release、deploy 或 route transition。

## 10. 不做什么

本版本不做：

- git fetch；
- git pull；
- git push；
- git merge；
- git rebase；
- 创建分支；
- 删除分支；
- 创建 tag；
- release 或 deploy；
- remote write；
- executor dispatch；
- service restart；
- runtime reload；
- 修改代码；
- 修改 `/home/jenn/tools/colameta`；
- 修改 runner 代码；
- 修改 tests；
- 修改 `.colameta` 文件；
- 判断 delivery_state；
- 产生 GateEvent；
- commit；
- route transition。

`GateEvent` = 状态门事件。中文意思是：只有 Delivery State Gate 产生的事件，
才能真正写入 delivery state 或 blocked 状态。本版本没有这个权力。

## 11. 下一道 Commander Gate

当前状态是：

```text
taskbook_draft_created
```

下一步应该先审查或修改这份 Version Taskbook。

如果未来要真的执行本地与远端基线报告，需要新的精确授权口令：

```text
AUTHORIZE_STAGE_00_V0_5_LOCAL_REMOTE_BASELINE_REPORT_EXECUTION_FOR_EXACT_HASH_ONLY
```

中文解释：现在只是把第五份 Version 任务书写出来，不能 `fetch`、不能 `push`、
不能写报告、不能 commit 或 route transition。
