# Stage 6 中文任务书：审查反馈接入

```yaml id="stage-06-zh-cn-summary"
chinese_companion:
  source_document: docs/taskbooks/stages/STAGE_06_REVIEW_FEEDBACK_INTAKE.md
  source_sha256: c83c979d447a4ec645d380b6c1dc206730d12d5d644c08582b3cfd04f3e0009d
  translation_status: companion_draft
  authority_status: planning_reference_only
stage:
  stage_id: stage_06_review_feedback_intake
  chinese_name: 审查反馈接入
  status: discussion_draft
```

## 1. 阶段定位

Stage 6 把 Reviewer feedback 结构化，分类成 `CommanderDecisionRequest`。它保留
Reviewer opinion、Commander authority、Delivery State Gate state transition 之间的
边界。

它不自动改 plan、不自动提升 delivery_state、不自动继续 executor。

英文源文件里的 `created_from_head` 是历史创建基线，不是当前 freeze snapshot HEAD。

## 2. 绑定要求

Stage 6 feedback 必须绑定：

- master_taskbook_ref；
- stage_taskbook_ref；
- version_taskbook_ref；
- reviewer_handoff_package_ref；
- execution_report_ref；
- workspace_snapshot_ref。

本阶段显式绑定 `master_taskbook_ref`，并声明 `supports_project_goal=true`。

## 3. 关键概念

- `ReviewDecision` = 审查决策记录。它是审查者判断记录，不是状态写入。
- `CommanderDecisionRequest` = 指挥官决策请求。系统整理“下一步需要 Commander
  授权什么”，但不替 Commander 决定。
- `GateEvent` = 状态门事件。真正写入交付状态变化的事件记录。

## 4. 进入条件

进入 Stage 6 需要：

- reviewer handoff package 存在；
- review feedback 绑定 execution report；
- workspace snapshot ref 已知；
- master/stage hash 已知。

不需要 plan mutation、delivery_state promotion、executor continuation。

## 5. 退出条件

Stage 6 完成时需要：

- ACCEPT、NEEDS_FIX、PLAN_ADJUST、ABORT 可识别；
- PASS 只在明确 policy-mapped 时作为 ReviewDecision.ACCEPT 的 legacy alias；
- PASS alias policy id 记录；
- ReviewDecision.ACCEPT 永远不等于 delivery_state accepted；
- feedback 绑定 reviewer_handoff_package_ref、version_taskbook_ref、
  execution_report_ref、workspace_snapshot_ref、master_taskbook_hash、
  stage_taskbook_hash；
- binding mismatch fail closed；
- 输出是 CommanderDecisionRequest，不是 state transition。

## 6. 状态门就绪条件

关键规则：

- PASS alias 只有显式 authorized `pass_alias_policy_ref` 时才有效，否则 fail closed；
- ACCEPT 创建 CommanderDecisionRequest，询问是否请求 Delivery State Gate review；
- NEEDS_FIX 创建 CommanderDecisionRequest，询问是否请求 Delivery State Gate review；
- ACCEPT、NEEDS_FIX、PASS alias 都不能自动打开 gate route；
- PLAN_ADJUST 只创建 Commander 决策请求，不自动改 plan；
- ABORT 只创建 Commander 决策请求，不自动取消、删除或 revert；
- feedback classification 不自动改 plan、route、delivery state、Git state、memory、
  executor continuation、commit 或 push。

## 6.1 Stage 0-6 就绪契约

```yaml id="stage-0-6-readiness-contract-zh-cn"
stage_0_6_readiness_contract:
  stage_id: stage_06_review_feedback_intake
  minimum_readiness_claim: Feedback 会变成 Commander 下一状态请求。
  required_evidence:
    - feedback receipt
    - classification
    - requested next-state decision
  gate_question: Commander 能否授权 stop、rework、defer、accept 或 next loop？
  explicit_non_goal: 不做 plan mutation、state promotion 或 execution continuation。
```

## 7. 最小证据包

最小证据包需要：

- review_feedback_ref；
- reviewer_identity_or_source；
- reviewer_authority_scope；
- reviewer_attestation；
- reviewer_handoff_package_ref；
- version_taskbook_ref；
- execution_report_ref；
- workspace_snapshot_ref；
- master_taskbook_hash；
- stage_taskbook_hash；
- review_decision_value；
- pass_alias_policy_id_when_used；
- charter_alignment；
- task_completion；
- scope_assessment；
- requested_commander_decision。

不能包括 automatic delivery_state transition、plan mutation、route transition、
executor continuation 作为权威。

## 8. 非目标

Stage 6 不自动推断 review conclusion、不接入含糊 feedback、不接受 unbound report
feedback、不自动改 plan、不自动 state transition、不自动 executor continuation、
不自动 commit。
