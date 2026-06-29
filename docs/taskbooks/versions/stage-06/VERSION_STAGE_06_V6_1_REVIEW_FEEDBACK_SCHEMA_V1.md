# Version Taskbook: Stage 6 / v6.1 Review Feedback Schema V1

```text id="version-stage-06-v6-1-boundary-banner"
VERSION TASKBOOK DRAFT ONLY.
This document defines a candidate Version Execution Taskbook for Stage 6. It
does not authorize implementation, code edits, commit, push, fetch, pull,
executor run, route transition, plan mutation, ReviewDecision creation,
GateEvent emission, review acceptance, Delivery State Gate transition, release,
deploy, or accepted delivery state.
```

```yaml id="version-taskbook-summary"
version_execution_taskbook:
  document_type: version_execution_taskbook
  schema_version: version_execution_taskbook.discussion_draft.v1
  version_id: stage_06_v6_1_review_feedback_schema_v1
  version: v6.1
  name: Review Feedback Schema V1
  chinese_name: 审查反馈模式 V1
  parent_stage_id: stage_06_review_feedback_intake
  parent_stage_name: Review Feedback Intake
  status: discussion_draft
  authority_status: planning_reference_only
  execution_authorization_status: not_authorized
  dispatch_status: not_authorized
  executor_run_authorized: false
  created_from_head: 06a8002
  created_from_head_full: 06a800233d4d0be7068b63fc167a0a5d744126c5
  created_from_head_meaning: historical_creation_baseline_not_execution_or_freeze_snapshot
  created_from_head_subject: "docs: record stage 5 version freeze confirmation"
  origin_main_observed_local_tracking_ref: 018ff63
  local_tracking_ref_sync_status_at_creation: local_ahead_remote_tracking_ref
  local_ahead_origin_main_at_creation: 41
```

`Review Feedback Schema V1` = 审查反馈模式 V1。中文意思是：先定义 Reviewer 反馈
必须携带哪些绑定、证据和判断字段，让反馈不能脱离 handoff package、执行报告和
workspace snapshot 漂进系统。

---

## 1. Parent Binding

```yaml id="parent-binding"
parent_binding:
  master_taskbook_ref:
    path: PROJECT_MASTER_TASKBOOK.md
    raw_snapshot_sha256: 1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34
    review_status: freeze_candidate_confirmed_for_exact_hash
  stage_taskbook_ref:
    path: docs/taskbooks/stages/STAGE_06_REVIEW_FEEDBACK_INTAKE.md
    raw_snapshot_sha256: c83c979d447a4ec645d380b6c1dc206730d12d5d644c08582b3cfd04f3e0009d
    stage_id: stage_06_review_feedback_intake
  stage_5_version_set_confirmation_ref:
    path: docs/taskbooks/versions/stage-05/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_05_VERSIONS.md
    raw_snapshot_sha256: ca23f567af50038469e3198b9a5600b1625e595c3381f20d262ab3aa81d61ea8
    review_status: hash_specific_freeze_candidate_confirmation_recorded
  supports_project_goal: true
```

v6.1 starts Stage 6. It consumes Stage 5 as an upstream planning anchor, but it
does not intake live feedback, create a ReviewDecision, emit a GateEvent, or
request a route transition.

中文解释：先规定“什么样的反馈算可接入”，再谈如何验证和分类。

---

## 2. Task Goal

```yaml id="task-goal"
task_goal:
  primary_goal: >
    Define the minimum machine-checkable ReviewFeedback schema that binds a
    Reviewer response to the reviewer handoff package, Version Taskbook,
    execution report, workspace snapshot, Master hash, Stage hash, reviewer
    identity or source, reviewer authority scope, and review decision value.
  minimum_readiness_claim: >
    ColaMeta can reject vague or unbound feedback before it becomes a Commander
    decision request.
  gate_question: >
    Can review feedback be checked for binding and required fields before any
    next-state request is generated?
  explicit_non_goal: >
    This version is not feedback import, not review decision acceptance, not
    CommanderDecisionRequest generation, not GateEvent emission, and not state
    transition.
```

---

## 3. ReviewFeedback Minimum Contract

```yaml id="review-feedback-minimum-contract"
review_feedback_minimum_contract:
  required_fields:
    - review_feedback_id
    - review_feedback_schema_version
    - reviewer_identity_or_source
    - reviewer_authority_scope
    - reviewer_attestation
    - reviewer_handoff_package_ref
    - version_taskbook_ref
    - execution_report_ref
    - workspace_snapshot_ref
    - master_taskbook_hash
    - stage_taskbook_hash
    - review_decision_value
    - pass_alias_policy_id_when_used
    - charter_alignment
    - task_completion
    - scope_assessment
    - reviewer_notes
    - submitted_at
  allowed_review_decision_values:
    - ACCEPT
    - NEEDS_FIX
    - PLAN_ADJUST
    - ABORT
  legacy_aliases:
    PASS:
      maps_to: ACCEPT
      requires_policy_ref: true
      policy_scope: legacy_alias_only_not_delivery_state_accepted
  forbidden_schema_claims:
    - review_feedback_writes_delivery_state
    - review_feedback_mutates_plan
    - review_feedback_authorizes_executor_continuation
    - accept_means_delivery_state_accepted
```

`ReviewFeedback` = 审查反馈。中文意思是：Reviewer 给出的结构化反馈输入；它不是
ReviewDecision 的最终权威写入，也不是 Delivery State Gate 事件。

---

## 4. Candidate Execution Envelope

```yaml id="candidate-execution-envelope"
execution_envelope_candidate:
  authorization_status: not_authorized
  parent_hashes:
    master_taskbook_hash: 1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34
    stage_taskbook_hash: c83c979d447a4ec645d380b6c1dc206730d12d5d644c08582b3cfd04f3e0009d
    stage_5_version_set_confirmation_hash: ca23f567af50038469e3198b9a5600b1625e595c3381f20d262ab3aa81d61ea8
  task_goal_ref: task_goal.primary_goal
  definition_of_good:
    - schema requires handoff package execution report and workspace snapshot refs
    - schema recognizes only ACCEPT NEEDS_FIX PLAN_ADJUST and ABORT
    - PASS requires explicit policy ref and maps only to ReviewDecision.ACCEPT
    - schema does not write plan route delivery state or Git state
```

---

## 5. Allowed Files And Mutations

```yaml id="allowed-files-and-mutations"
allowed_files:
  read_only:
    - PROJECT_MASTER_TASKBOOK.md
    - docs/taskbooks/stages/STAGE_06_REVIEW_FEEDBACK_INTAKE.md
    - docs/taskbooks/versions/stage-05/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_05_VERSIONS.md
    - docs/taskbooks/versions/stage-05/**
    - runner/**
    - tests/**
  writable_after_separate_execution_authorization:
    - runner/review_feedback_schema.py
    - tests/test_review_feedback_schema.py
    - docs/taskbooks/versions/stage-06/evidence/VERSION_STAGE_06_V6_1_REVIEW_FEEDBACK_SCHEMA_REPORT.md
    - docs/taskbooks/versions/stage-06/evidence/zh-CN/VERSION_STAGE_06_V6_1_REVIEW_FEEDBACK_SCHEMA_REPORT.zh-CN.md
forbidden_files:
  mutation_targets:
    - /home/jenn/tools/colameta/**
    - PROJECT_MASTER_TASKBOOK.md
    - PROJECT_MASTER_TASKBOOK.zh-CN.md
    - docs/taskbooks/stages/**
    - docs/taskbooks/versions/stage-00/**
    - docs/taskbooks/versions/stage-01/**
    - docs/taskbooks/versions/stage-02/**
    - docs/taskbooks/versions/stage-03/**
    - docs/taskbooks/versions/stage-04/**
    - docs/taskbooks/versions/stage-05/**
    - .colameta/plan.json
    - .colameta/state.json
    - .colameta/runtime/**
    - .git/**
```

---

## 6. Rejection Rules

```yaml id="rejection-rules"
rejection_rules:
  reject_when:
    - reviewer_handoff_package_ref_missing
    - version_taskbook_ref_missing
    - execution_report_ref_missing
    - workspace_snapshot_ref_missing
    - master_or_stage_hash_missing
    - review_decision_value_unknown
    - pass_alias_used_without_policy_ref
    - feedback_claims_delivery_state_transition
    - feedback_claims_plan_mutation
    - feedback_claims_executor_continuation
```

---

## 7. Evidence Package Contract

```yaml id="evidence-package-contract"
evidence_package_contract:
  evidence_report_required: true
  evidence_report_must_include:
    - schema_field_inventory
    - valid_feedback_example
    - rejection_case_examples
    - pass_alias_policy_example
    - forbidden_state_claim_check
    - commands_run
    - commands_not_run
    - remaining_risks
  evidence_report_must_not_claim:
    - review_decision_created
    - gate_event_emitted
    - delivery_state_transitioned
```

---

## 8. Manual Acceptance Criteria For This Version

```yaml id="manual-acceptance-criteria"
manual_acceptance_criteria:
  can_be_accepted_for_next_step_when:
    - schema requires all feedback binding refs
    - schema limits review decision values to ACCEPT NEEDS_FIX PLAN_ADJUST and ABORT
    - PASS alias is disabled unless explicit policy ref is present
    - schema rejects feedback claiming plan route executor or state authority
  must_return_to_draft_when:
    - feedback can be accepted without binding refs
    - PASS can mean delivery_state accepted
    - schema can directly create ReviewDecision GateEvent or route transition
    - Chinese companion weakens the non-authority boundary
```

---

## 9. Next Version Handoff

```yaml id="next-version-handoff"
next_version_handoff:
  next_version: v6.2
  next_version_name: Review Feedback Validator V1
  handoff_condition: >
    v6.2 may define validation only after v6.1 defines the feedback schema and
    fail-closed rejection rules.
  still_not_authorized:
    - implementation
    - executor_run
    - review_decision_creation
    - gate_event_emission
    - delivery_state_transition
```

中文解释：v6.1 是“反馈输入的形状”，不是“收到反馈就自动往前走”。
