# Version Taskbook: Stage 6 / v6.3 Review Feedback Preview V1

```text id="version-stage-06-v6-3-boundary-banner"
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
  version_id: stage_06_v6_3_review_feedback_preview_v1
  version: v6.3
  name: Review Feedback Preview V1
  chinese_name: 审查反馈预览 V1
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

`Review Feedback Preview V1` = 审查反馈预览 V1。中文意思是：在反馈通过验证后，
展示它将如何被分类、可能生成什么 CommanderDecisionRequest，但不真正创建请求、
不写状态、不改计划。

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
  previous_version_ref:
    path: docs/taskbooks/versions/stage-06/VERSION_STAGE_06_V6_2_REVIEW_FEEDBACK_VALIDATOR_V1.md
    raw_snapshot_sha256: 679f462641f49ebd5bce077c1a387fda2977f5d3ce5707560aacffff3fd8d4f6
    version_id: stage_06_v6_2_review_feedback_validator_v1
  stage_5_version_set_confirmation_ref:
    path: docs/taskbooks/versions/stage-05/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_05_VERSIONS.md
    raw_snapshot_sha256: ca23f567af50038469e3198b9a5600b1625e595c3381f20d262ab3aa81d61ea8
    review_status: hash_specific_freeze_candidate_confirmation_recorded
  supports_project_goal: true
```

---

## 2. Task Goal

```yaml id="task-goal"
task_goal:
  primary_goal: >
    Define a non-authoritative preview that shows how validated ReviewFeedback
    would map to a next-step classification and candidate
    CommanderDecisionRequest without creating that request or mutating any
    state.
  minimum_readiness_claim: >
    ColaMeta can show Commander what the system would ask next before creating
    an actionable request.
  gate_question: >
    Can the system preview the next-state request while preserving Commander
    authority and avoiding route or delivery state mutation?
  explicit_non_goal: >
    This version is not classification finalization, not
    CommanderDecisionRequest creation, not ReviewDecision creation, not
    GateEvent emission, and not state transition.
```

---

## 3. Preview Contract

```yaml id="review-feedback-preview-contract"
review_feedback_preview_contract:
  required_inputs:
    - validated_review_feedback
    - validation_status_ref
    - reviewer_handoff_package_ref
    - version_taskbook_ref
    - execution_report_ref
    - workspace_snapshot_ref
  required_outputs:
    - preview_id
    - source_feedback_ref
    - validation_status_ref
    - candidate_classification
    - candidate_commander_decision_request_shape
    - missing_information
    - boundary_notice
  candidate_classification_values:
    - candidate_accept_path
    - candidate_needs_fix_path
    - candidate_plan_adjust_path
    - candidate_abort_path
    - candidate_blocked_unclear_feedback
  forbidden_outputs:
    - commander_decision_request_id
    - review_decision_record
    - gate_event
    - delivery_state_transition
    - plan_mutation
    - executor_continuation
```

`candidate_commander_decision_request_shape` = 候选指挥官决策请求形状。中文意思是：
只展示将来可能向 Commander 请求什么字段，不创建真正的请求编号或授权对象。

---

## 4. Preview Mapping

```yaml id="preview-mapping"
preview_mapping:
  ACCEPT:
    preview_path: candidate_accept_path
    preview_question: Ask Commander whether to request Delivery State Gate review.
    must_not_do:
      - mark_delivery_state_accepted
      - emit_gate_event
      - continue_executor
  NEEDS_FIX:
    preview_path: candidate_needs_fix_path
    preview_question: Ask Commander whether to request rework or return work through the gate.
    must_not_do:
      - open_rework_route
      - mutate_plan
      - continue_executor
  PLAN_ADJUST:
    preview_path: candidate_plan_adjust_path
    preview_question: Ask Commander whether planning changes should be prepared.
    must_not_do:
      - mutate_plan
      - edit_master_or_stage
  ABORT:
    preview_path: candidate_abort_path
    preview_question: Ask Commander whether stop or supersede handling is needed.
    must_not_do:
      - delete_files
      - revert_work
      - cancel_runtime
  PASS_alias:
    preview_path: candidate_accept_path
    requires_policy_ref: true
    must_not_do:
      - treat_PASS_as_delivery_state_passed
      - hide_alias_mapping
```

---

## 5. Candidate Execution Envelope

```yaml id="candidate-execution-envelope"
execution_envelope_candidate:
  authorization_status: not_authorized
  parent_hashes:
    master_taskbook_hash: 1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34
    stage_taskbook_hash: c83c979d447a4ec645d380b6c1dc206730d12d5d644c08582b3cfd04f3e0009d
    previous_version_hash: 679f462641f49ebd5bce077c1a387fda2977f5d3ce5707560aacffff3fd8d4f6
    stage_5_version_set_confirmation_hash: ca23f567af50038469e3198b9a5600b1625e595c3381f20d262ab3aa81d61ea8
  task_goal_ref: task_goal.primary_goal
  definition_of_good:
    - preview shows candidate request shape only
    - preview does not create request id
    - preview preserves missing information and unclear status
    - preview maps ACCEPT without delivery_state accepted
```

---

## 6. Allowed Files And Mutations

```yaml id="allowed-files-and-mutations"
allowed_files:
  read_only:
    - PROJECT_MASTER_TASKBOOK.md
    - docs/taskbooks/stages/STAGE_06_REVIEW_FEEDBACK_INTAKE.md
    - docs/taskbooks/versions/stage-06/VERSION_STAGE_06_V6_1_REVIEW_FEEDBACK_SCHEMA_V1.md
    - docs/taskbooks/versions/stage-06/VERSION_STAGE_06_V6_2_REVIEW_FEEDBACK_VALIDATOR_V1.md
    - docs/taskbooks/versions/stage-05/**
    - runner/**
    - tests/**
  writable_after_separate_execution_authorization:
    - runner/review_feedback_preview.py
    - tests/test_review_feedback_preview.py
    - docs/taskbooks/versions/stage-06/evidence/VERSION_STAGE_06_V6_3_REVIEW_FEEDBACK_PREVIEW_REPORT.md
    - docs/taskbooks/versions/stage-06/evidence/zh-CN/VERSION_STAGE_06_V6_3_REVIEW_FEEDBACK_PREVIEW_REPORT.zh-CN.md
forbidden_files:
  mutation_targets:
    - /home/jenn/tools/colameta/**
    - PROJECT_MASTER_TASKBOOK.md
    - docs/taskbooks/stages/**
    - docs/taskbooks/versions/stage-00/**
    - docs/taskbooks/versions/stage-01/**
    - docs/taskbooks/versions/stage-02/**
    - docs/taskbooks/versions/stage-03/**
    - docs/taskbooks/versions/stage-04/**
    - docs/taskbooks/versions/stage-05/**
    - .colameta/plan.json
    - .colameta/state.json
    - .git/**
```

---

## 7. Rejection Rules

```yaml id="rejection-rules"
rejection_rules:
  reject_when:
    - validation_status_not_valid_for_preview
    - candidate_request_shape_missing_boundary_notice
    - preview_creates_request_id
    - preview_claims_review_decision_recorded
    - preview_claims_gate_event_emitted
    - preview_claims_delivery_state_transition
    - preview_hides_unclear_or_missing_information
```

---

## 8. Evidence Package Contract

```yaml id="evidence-package-contract"
evidence_package_contract:
  evidence_report_required: true
  evidence_report_must_include:
    - preview_mapping_inventory
    - accept_preview_case
    - needs_fix_preview_case
    - plan_adjust_preview_case
    - abort_preview_case
    - pass_alias_preview_case
    - boundary_notice_check
    - commands_run
    - commands_not_run
    - remaining_risks
  evidence_report_must_not_claim:
    - commander_decision_request_created
    - review_decision_created
    - gate_event_emitted
    - delivery_state_transitioned
```

---

## 9. Manual Acceptance Criteria For This Version

```yaml id="manual-acceptance-criteria"
manual_acceptance_criteria:
  can_be_accepted_for_next_step_when:
    - preview maps all decision values to candidate paths
    - preview creates no actionable request id
    - preview preserves missing information
    - preview keeps ACCEPT separate from delivery_state accepted
  must_return_to_draft_when:
    - preview can authorize next route
    - preview can create CommanderDecisionRequest
    - preview can emit GateEvent
    - Chinese companion weakens preview-only boundary
```

---

## 10. Next Version Handoff

```yaml id="next-version-handoff"
next_version_handoff:
  next_version: v6.4
  next_version_name: Review Feedback Classification And Decision Request V1
  handoff_condition: >
    v6.4 may define actual classification and CommanderDecisionRequest output
    only after v6.3 preserves a non-authoritative preview boundary.
  still_not_authorized:
    - implementation
    - executor_run
    - review_decision_creation
    - gate_event_emission
    - delivery_state_transition
```

中文解释：v6.3 是“先给 Commander 看将会问什么”，不是“已经问了也不是已经批准了”。
