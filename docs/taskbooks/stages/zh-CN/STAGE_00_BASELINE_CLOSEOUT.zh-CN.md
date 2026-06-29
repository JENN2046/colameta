# Stage 0 中文任务书：基线收束与执行状态清晰化

```yaml id="stage-00-zh-cn-summary"
chinese_companion:
  source_document: docs/taskbooks/stages/STAGE_00_BASELINE_CLOSEOUT.md
  source_sha256: 12103877ba181c48056299b800c546e55ac7f68b7df82f4f657a4bd2f0e91489
  translation_status: companion_draft
  authority_status: planning_reference_only
stage:
  stage_id: stage_00_baseline_closeout
  chinese_name: 基线收束与执行状态清晰化
  status: discussion_draft
```

## 1. 阶段定位

Stage 0 的任务是让当前现实足够清楚：代码库状态、远端同步状态、运行时状态、
验证事实、executor session 是否过期、已知未知项，都必须能被解释。

它不是新产品能力阶段，也不是清理工程，更不是“自动修复一切状态问题”。

英文源文件里的 `created_from_head` 是历史创建基线，不是当前 freeze snapshot HEAD。

## 2. Master 绑定

本阶段绑定到 `PROJECT_MASTER_TASKBOOK.md`，源 Master hash 为：

`1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34`

Master 中 Stage 0 的阶段状态引用是 `active_closeout`。但这份 Stage 中文任务书
自身仍是 `discussion_draft`，不拥有状态权威。

本阶段显式绑定 `master_taskbook_ref`，并声明 `supports_project_goal=true`。

## 3. 进入条件

进入 Stage 0 草稿讨论需要这些事实可观察：

- 项目仓库路径是 `/home/jenn/src/colameta-dev`；
- 稳定服务运行目录是 `/home/jenn/tools/colameta`；
- 本地 Git 分支和 origin 跟踪状态可以观察；
- 当前计划和 runtime 状态可以只读读取。

不需要 active Master authority、executor run、runtime cleanup 或 dashboard。

## 4. 退出条件

Stage 0 可作为后续阶段基线时，需要满足：

- 验证真相来源和摘要标签可区分；
- executor 报告能区分 executed、validated、blocked、failed、stale；
- runtime loaded-code freshness 可解释；
- executor-session HEAD mismatch 可无变异分类；
- local HEAD 和 remote sync state 分开记录；
- known unknowns 不被伪装成成功。

## 5. 交付方向

Stage 0 的交付方向包括：

- validation truth source hardening = 验证真相来源加固；
- executor report truth source = executor 报告真相来源；
- runtime loaded-code verification = 运行时加载代码验证；
- executor-session head mismatch classification = executor session HEAD 不匹配分类；
- local/remote baseline report = 本地/远端基线报告。

这些是证据和能力方向，不是代码修改授权。任何代码 hardening 都必须另有
Version Execution Taskbook 和 execution envelope 授权。

## 6. 版本方向

Stage 0 后续可拆成这些版本任务：

- Baseline Snapshot V1 = 基线快照；
- Validation Truth Source Report V1 = 验证真相来源报告；
- Runtime Freshness Report V1 = 运行时新鲜度报告；
- Executor Session HEAD Classification Report V1 = executor session HEAD 分类报告；
- Local Remote Baseline Report V1 = 本地远端基线报告。

## 7. 状态门就绪条件

Stage 0 的 gate-readiness 重点是：

- 验证失败不能被总结为 passed；
- validation_inconsistent 可以识别；
- audit package 暴露真相来源证据；
- runtime loaded-code freshness 可解释；
- executor-session HEAD mismatch 可无变异分类；
- local commit 和 remote sync state 分开记录。

## 7.1 Stage 0-6 就绪契约

```yaml id="stage-0-6-readiness-contract-zh-cn"
stage_0_6_readiness_contract:
  stage_id: stage_00_baseline_closeout
  minimum_readiness_claim: 基线状态已清楚到足以开始治理声明。
  required_evidence:
    - 基线快照
    - 已知未知项
    - 本地运行态状态说明
  gate_question: 后续声明是否从已声明的基线开始？
  explicit_non_goal: 不做完整审计、清理工程或 dashboard。
```

## 8. 最小证据包

最小证据包需要包含：

- git_head；
- origin_sync_state；
- worktree_status；
- current_version_status；
- validation_truth_status；
- runtime_loaded_code_status；
- executor_session_head_match_status；
- known_unknowns。

不能把 stale executor session metadata、runtime summary label alone、chat memory
当作权威。

## 9. 非目标

Stage 0 不做：

- 新产品治理能力扩展；
- executor 权限扩展；
- review feedback system；
- dashboard；
- 自动 runtime cleanup；
- commit 或 push 授权。

## 10. 下一步建议

只有当具体 stale-state bug 阻塞后续 gate 时，才回补 Stage 0。不要把 Stage 0
变成无限清理项目。
