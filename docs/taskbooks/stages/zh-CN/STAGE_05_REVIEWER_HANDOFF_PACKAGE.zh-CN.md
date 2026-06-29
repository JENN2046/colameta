# Stage 5 中文任务书：审查者交接包

```yaml id="stage-05-zh-cn-summary"
chinese_companion:
  source_document: docs/taskbooks/stages/STAGE_05_REVIEWER_HANDOFF_PACKAGE.md
  source_sha256: 532d36ab5c99d37c1a88b094fbe9c37bdc342e17e572447468a0918afbdce43c
  translation_status: companion_draft
  authority_status: planning_reference_only
stage:
  stage_id: stage_05_reviewer_handoff_package
  chinese_name: 审查者交接包
  status: discussion_draft
```

## 1. 阶段定位

Stage 5 在有边界执行或 receipt intake 后，生成 self-contained review package，让
Reviewer 不必重建完整上下文，也能判断任务完成度、scope、validation、risk 和
goal alignment。

它不是 acceptance 本身。

英文源文件里的 `created_from_head` 是历史创建基线，不是当前 freeze snapshot HEAD。

## 2. 绑定要求

Reviewer handoff package 需要绑定：

- master_taskbook_ref；
- stage_taskbook_ref；
- version_taskbook_ref；
- execution_receipt_ref。

本阶段显式绑定 `master_taskbook_ref`，并声明 `supports_project_goal=true`。

## 3. 进入条件

进入 Stage 5 需要：

- execution receipt 或 imported receipt 存在；
- validation truth status 已知；
- changed files 或 touched artifacts 已知；
- taskbook bindings 已知。

不需要 Reviewer decision、delivery_state promotion 或 automatic semantic alignment
claim。

## 4. 退出条件

Stage 5 完成时，handoff package 需要包含：

- master-goal summary；
- stage-goal summary；
- version-task summary；
- changed_files；
- validation truth；
- scope evidence；
- drift 判断问题；
- 有限 decision options；
- decision options 只能是 ACCEPT、NEEDS_FIX、PLAN_ADJUST、ABORT；
- ACCEPT 只能作为 Reviewer 可选的 ReviewDecision 值，不是 generator 推荐，也不是
  delivery_state accepted。

## 5. 版本方向

Stage 5 后续版本方向：

- Reviewer Handoff Schema V1；
- Reviewer Handoff Generator V1；
- Alignment Questions V1；
- Drift Question Pack V1；
- Reviewer Package Report Surface V1。

这些只生成审查材料，不替 Reviewer 决策。

## 5.1 Stage 0-6 就绪契约

```yaml id="stage-0-6-readiness-contract-zh-cn"
stage_0_6_readiness_contract:
  stage_id: stage_05_reviewer_handoff_package
  minimum_readiness_claim: Reviewer handoff 是自包含的。
  required_evidence:
    - claim-to-evidence package
    - validation status
    - risks
    - known gaps
  gate_question: Reviewer 是否能不重建上下文就做判断？
  explicit_non_goal: 不做 acceptance 本身。
```

## 6. 最小 handoff 模板

最小 handoff package 需要：

- handoff_package_id；
- master_taskbook_ref；
- stage_taskbook_ref；
- version_taskbook_ref；
- execution_receipt_ref；
- claim_summary；
- changed_files；
- validation_truth；
- scope_evidence；
- known_risks；
- reviewer_questions；
- allowed_review_decisions。

allowed_review_decisions 只能是 ACCEPT、NEEDS_FIX、PLAN_ADJUST、ABORT。

handoff generator 不得推荐 ACCEPT。Reviewer decisions 是 Reviewer 选择的 review
records，不写 delivery_state，也不替代 Delivery State Gate review。

## 7. 最小证据包

最小证据包需要 review_package_id、master_goal_summary、stage_goal_summary、
version_task_summary、execution_receipt_ref、changed_files、validation_truth_summary、
scope_evidence、known_risks、reviewer_questions。

不能包括 acceptance claim、delivery_state transition、Commander authorization 作为权威。

## 8. 非目标

Stage 5 不替代 Reviewer、不自动声明 aligned、不自动 release next version、不把
handoff package 当作 acceptance pass、不授权 commit/push。
