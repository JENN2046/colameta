# Version Taskbook: Stage 6 / v6.4 Review Feedback Classification And Decision Request V1

```text id="version-stage-06-v6-4-boundary-banner"
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
  version_id: stage_06_v6_4_review_feedback_classification_and_decision_request_v1
  version: v6.4
  name: Review Feedback Classification And Decision Request V1
  chinese_name: 审查反馈分类与决策请求 V1
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

`Review Feedback Classification And Decision Request V1` = 审查反馈分类与决策请求 V1。
中文意思是：把已验证反馈分类成 Commander 需要决定的请求；它只生成请求，不代替
Commander 授权，也不写 GateEvent。

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
    path: docs/taskbooks/versions/stage-06/VERSION_STAGE_06_V6_3_REVIEW_FEEDBACK_PREVIEW_V1.md
    raw_snapshot_sha256: 008b99f4d6ec793f9aaf83868f2ae91da3c1ea0d6bfdaf8664e075021475f990
    version_id: stage_06_v6_3_review_feedback_preview_v1
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
    Define the minimum classification and CommanderDecisionRequest contract that
    transforms validated ReviewFeedback into a bounded request for Commander
    action while preserving the distinction between reviewer feedback, Commander
    authorization, and Delivery State Gate transitions.
  minimum_readiness_claim: >
    ColaMeta can turn valid review feedback into an explicit Commander question
    without taking the requested action.
  gate_question: >
    Can every accepted feedback classification result in a Commander-owned
    decision request instead of an automatic mutation?
  explicit_non_goal: >
    This version is not Commander authorization, not ReviewDecision record
    creation, not GateEvent emission, not plan mutation, and not state
    transition.
```

---

## 3. Classification Contract

```yaml id="review-feedback-classification-contract"
review_feedback_classification_contract:
  required_inputs:
    - validated_review_feedback
    - validation_status_ref
    - preview_ref
    - mapping_policy_ref
  classification_values:
    - accept_review_feedback
    - needs_fix_review_feedback
    - plan_adjust_review_feedback
    - abort_review_feedback
    - blocked_unclear_review_feedback
  pass_alias_handling:
    allowed_only_with_policy_ref: true
    maps_to: accept_review_feedback
    must_surface_alias_use: true
  forbidden_classification_claims:
    - classification_is_review_acceptance
    - classification_is_delivery_state
    - classification_authorizes_route
    - classification_authorizes_executor
```

---

## 4. CommanderDecisionRequest Contract

```yaml id="commander-decision-request-contract"
commander_decision_request_contract:
  required_fields:
    - commander_decision_request_id
    - request_schema_version
    - source_review_feedback_ref
    - source_review_decision_value
    - normalized_classification
    - reviewer_handoff_package_ref
    - version_taskbook_ref
    - execution_report_ref
    - workspace_snapshot_ref
    - master_taskbook_hash
    - stage_taskbook_hash
    - requested_commander_action
    - allowed_commander_responses
    - non_authority_notice
  allowed_commander_responses:
    - AUTHORIZE_GATE_REVIEW_REQUEST
    - AUTHORIZE_REWORK_PLANNING
    - AUTHORIZE_PLAN_ADJUSTMENT_DRAFT
    - AUTHORIZE_ABORT_HANDLING_DRAFT
    - RETURN_FOR_CLARIFICATION
    - REJECT_REQUEST
  forbidden_request_effects:
    - execute_requested_action
    - mutate_plan
    - emit_gate_event
    - continue_executor
    - commit_or_push
```

`CommanderDecisionRequest` = 指挥官决策请求。中文意思是：系统把“下一步该不该做、
做哪种动作”整理成请求，等 Commander 授权；它不是授权本身。

---

## 5. Decision Mapping

```yaml id="decision-mapping"
decision_mapping:
  ACCEPT:
    classification: accept_review_feedback
    requested_commander_action: ask_whether_to_request_delivery_state_gate_review
    forbidden_effect: delivery_state_accepted
  NEEDS_FIX:
    classification: needs_fix_review_feedback
    requested_commander_action: ask_whether_to_prepare_rework_or_gate_return
    forbidden_effect: automatic_rework_route
  PLAN_ADJUST:
    classification: plan_adjust_review_feedback
    requested_commander_action: ask_whether_to_prepare_plan_adjustment_draft
    forbidden_effect: automatic_plan_mutation
  ABORT:
    classification: abort_review_feedback
    requested_commander_action: ask_whether_to_prepare_abort_or_supersede_handling
    forbidden_effect: automatic_delete_revert_or_runtime_cancel
  PASS_alias:
    classification: accept_review_feedback
    required_policy_ref: pass_alias_policy_ref
    forbidden_effect: delivery_state_passed_or_accepted
```

---

## 6. Candidate Execution Envelope

```yaml id="candidate-execution-envelope"
execution_envelope_candidate:
  authorization_status: not_authorized
  parent_hashes:
    master_taskbook_hash: 1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34
    stage_taskbook_hash: c83c979d447a4ec645d380b6c1dc206730d12d5d644c08582b3cfd04f3e0009d
    previous_version_hash: 008b99f4d6ec793f9aaf83868f2ae91da3c1ea0d6bfdaf8664e075021475f990
    stage_5_version_set_confirmation_hash: ca23f567af50038469e3198b9a5600b1625e595c3381f20d262ab3aa81d61ea8
  task_goal_ref: task_goal.primary_goal
  definition_of_good:
    - classification maps all allowed decision values
    - CommanderDecisionRequest carries binding refs
    - request effect is separated from requested action
    - ACCEPT maps to gate review request only not accepted delivery state
```

---

## 7. Allowed Files And Mutations

```yaml id="allowed-files-and-mutations"
allowed_files:
  read_only:
    - PROJECT_MASTER_TASKBOOK.md
    - docs/taskbooks/stages/STAGE_06_REVIEW_FEEDBACK_INTAKE.md
    - docs/taskbooks/versions/stage-06/**
    - docs/taskbooks/versions/stage-05/**
    - runner/**
    - tests/**
  writable_after_separate_execution_authorization:
    - runner/review_feedback_classification.py
    - runner/commander_decision_request.py
    - tests/test_review_feedback_classification.py
    - tests/test_commander_decision_request.py
    - docs/taskbooks/versions/stage-06/evidence/VERSION_STAGE_06_V6_4_REVIEW_FEEDBACK_CLASSIFICATION_AND_DECISION_REQUEST_REPORT.md
    - docs/taskbooks/versions/stage-06/evidence/zh-CN/VERSION_STAGE_06_V6_4_REVIEW_FEEDBACK_CLASSIFICATION_AND_DECISION_REQUEST_REPORT.zh-CN.md
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

## 8. Rejection Rules

```yaml id="rejection-rules"
rejection_rules:
  reject_when:
    - validation_status_not_valid_for_preview
    - review_decision_value_unmapped
    - pass_alias_without_policy_ref
    - request_missing_binding_refs
    - request_claims_commander_authorization
    - request_claims_gate_event_emission
    - request_claims_delivery_state_transition
    - request_claims_plan_mutation_or_executor_continuation
```

---

## 9. Evidence Package Contract

```yaml id="evidence-package-contract"
evidence_package_contract:
  evidence_report_required: true
  evidence_report_must_include:
    - classification_mapping_inventory
    - commander_decision_request_field_inventory
    - accept_request_case
    - needs_fix_request_case
    - plan_adjust_request_case
    - abort_request_case
    - pass_alias_request_case
    - forbidden_effect_check
    - commands_run
    - commands_not_run
    - remaining_risks
  evidence_report_must_not_claim:
    - commander_authorization_granted
    - review_decision_created
    - gate_event_emitted
    - delivery_state_transitioned
```

---

## 10. Manual Acceptance Criteria For This Version

```yaml id="manual-acceptance-criteria"
manual_acceptance_criteria:
  can_be_accepted_for_next_step_when:
    - all allowed review decisions map to bounded CommanderDecisionRequest shapes
    - request includes source feedback and binding refs
    - request clearly separates requested action from authorized action
    - ACCEPT never maps to delivery_state accepted
  must_return_to_draft_when:
    - request can execute itself
    - request can emit GateEvent
    - request can mutate plan or route
    - Chinese companion weakens Commander authority boundary
```

---

## 11. Next Version Handoff

```yaml id="next-version-handoff"
next_version_handoff:
  next_version: v6.5
  next_version_name: Review Decision Adapter V1
  handoff_condition: >
    v6.5 may define adapter boundaries only after v6.4 separates classification,
    CommanderDecisionRequest, Commander authorization, and GateEvent emission.
  still_not_authorized:
    - implementation
    - executor_run
    - review_decision_creation
    - gate_event_emission
    - delivery_state_transition
```

中文解释：v6.4 可以“生成请求”，但请求不会自己执行。真正动作仍要 Commander 再授权。
