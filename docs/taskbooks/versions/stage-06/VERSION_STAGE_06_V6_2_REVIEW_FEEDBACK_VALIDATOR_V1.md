# Version Taskbook: Stage 6 / v6.2 Review Feedback Validator V1

```text id="version-stage-06-v6-2-boundary-banner"
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
  version_id: stage_06_v6_2_review_feedback_validator_v1
  version: v6.2
  name: Review Feedback Validator V1
  chinese_name: 审查反馈验证器 V1
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

`Review Feedback Validator V1` = 审查反馈验证器 V1。中文意思是：检查反馈是否符合
v6.1 schema、hash 是否匹配、绑定是否完整、PASS 是否有 policy ref；验证失败只能
返回错误，不生成 CommanderDecisionRequest。

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
    path: docs/taskbooks/versions/stage-06/VERSION_STAGE_06_V6_1_REVIEW_FEEDBACK_SCHEMA_V1.md
    raw_snapshot_sha256: 70ec9d9aa6e34299f3c3f0def67fdc0a8ec066cedbc934868dca98542b38ddf7
    version_id: stage_06_v6_1_review_feedback_schema_v1
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
    Define a minimum fail-closed ReviewFeedback validator that checks required
    fields, allowed decision values, PASS alias policy, binding hashes,
    handoff package refs, execution report refs, and forbidden authority claims.
  minimum_readiness_claim: >
    ColaMeta can reject malformed, unbound, mismatched, or authority-laundering
    review feedback before it becomes a preview or decision request.
  gate_question: >
    Can invalid feedback be stopped without mutating plan, route, Git state,
    executor state, review records, or delivery state?
  explicit_non_goal: >
    This version is not feedback preview, not classification, not
    CommanderDecisionRequest generation, not ReviewDecision creation, and not
    GateEvent emission.
```

---

## 3. Validator Contract

```yaml id="review-feedback-validator-contract"
review_feedback_validator_contract:
  required_inputs:
    - review_feedback_candidate
    - review_feedback_schema_ref
    - expected_master_taskbook_hash
    - expected_stage_taskbook_hash
    - expected_version_taskbook_ref
    - expected_reviewer_handoff_package_ref
    - expected_workspace_snapshot_ref
  required_outputs:
    - validation_status
    - validation_errors
    - normalized_review_decision_value
    - pass_alias_policy_check
    - binding_check
    - forbidden_claim_check
  valid_validation_statuses:
    - valid_for_preview
    - invalid_missing_required_field
    - invalid_binding_mismatch
    - invalid_unknown_review_decision
    - invalid_pass_alias_policy_missing
    - invalid_forbidden_authority_claim
  forbidden_outputs:
    - commander_decision_request
    - review_decision_record
    - gate_event
    - delivery_state_transition
```

`valid_for_preview` = 可进入预览。中文意思是：反馈只通过“可以预览下一步请求”的门，
不代表已经接受、已经分类完成或可以改状态。

---

## 4. Validation Rules

```yaml id="validation-rules"
validation_rules:
  required_field_checks:
    - reviewer_identity_or_source_present
    - reviewer_handoff_package_ref_present
    - version_taskbook_ref_present
    - execution_report_ref_present
    - workspace_snapshot_ref_present
    - master_taskbook_hash_present
    - stage_taskbook_hash_present
    - review_decision_value_present
  binding_checks:
    - master_taskbook_hash_matches_expected
    - stage_taskbook_hash_matches_expected
    - version_taskbook_ref_matches_expected
    - reviewer_handoff_package_ref_matches_expected
    - workspace_snapshot_ref_matches_expected
  decision_checks:
    - only_ACCEPT_NEEDS_FIX_PLAN_ADJUST_ABORT_are_native_values
    - PASS_requires_pass_alias_policy_ref
    - PASS_maps_only_to_ReviewDecision_ACCEPT
    - ACCEPT_never_means_delivery_state_accepted
  forbidden_claim_checks:
    - no_plan_mutation_claim
    - no_route_transition_claim
    - no_executor_continuation_claim
    - no_review_acceptance_claim
    - no_delivery_state_transition_claim
```

---

## 5. Candidate Execution Envelope

```yaml id="candidate-execution-envelope"
execution_envelope_candidate:
  authorization_status: not_authorized
  parent_hashes:
    master_taskbook_hash: 1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34
    stage_taskbook_hash: c83c979d447a4ec645d380b6c1dc206730d12d5d644c08582b3cfd04f3e0009d
    previous_version_hash: 70ec9d9aa6e34299f3c3f0def67fdc0a8ec066cedbc934868dca98542b38ddf7
    stage_5_version_set_confirmation_hash: ca23f567af50038469e3198b9a5600b1625e595c3381f20d262ab3aa81d61ea8
  task_goal_ref: task_goal.primary_goal
  definition_of_good:
    - validator fails closed on missing or mismatched bindings
    - validator rejects unknown decision values
    - validator rejects PASS without explicit policy ref
    - validator returns errors instead of next-state authority
```

---

## 6. Allowed Files And Mutations

```yaml id="allowed-files-and-mutations"
allowed_files:
  read_only:
    - PROJECT_MASTER_TASKBOOK.md
    - docs/taskbooks/stages/STAGE_06_REVIEW_FEEDBACK_INTAKE.md
    - docs/taskbooks/versions/stage-06/VERSION_STAGE_06_V6_1_REVIEW_FEEDBACK_SCHEMA_V1.md
    - docs/taskbooks/versions/stage-05/**
    - runner/**
    - tests/**
  writable_after_separate_execution_authorization:
    - runner/review_feedback_validator.py
    - tests/test_review_feedback_validator.py
    - docs/taskbooks/versions/stage-06/evidence/VERSION_STAGE_06_V6_2_REVIEW_FEEDBACK_VALIDATOR_REPORT.md
    - docs/taskbooks/versions/stage-06/evidence/zh-CN/VERSION_STAGE_06_V6_2_REVIEW_FEEDBACK_VALIDATOR_REPORT.zh-CN.md
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
    - required_field_missing
    - binding_mismatch
    - unknown_review_decision_value
    - pass_alias_policy_missing
    - forbidden_authority_claim_present
    - validation_output_claims_next_state_authority
```

---

## 8. Evidence Package Contract

```yaml id="evidence-package-contract"
evidence_package_contract:
  evidence_report_required: true
  evidence_report_must_include:
    - validator_rule_inventory
    - valid_feedback_case
    - binding_mismatch_case
    - unknown_decision_case
    - pass_alias_missing_policy_case
    - forbidden_claim_case
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
    - validator checks all required feedback bindings
    - validator rejects PASS without policy ref
    - validator rejects feedback containing state or route authority claims
    - validator output is validation status only
  must_return_to_draft_when:
    - validator can generate CommanderDecisionRequest
    - validator can create ReviewDecision or GateEvent
    - validator treats ACCEPT as delivery_state accepted
    - Chinese companion weakens fail-closed behavior
```

---

## 10. Next Version Handoff

```yaml id="next-version-handoff"
next_version_handoff:
  next_version: v6.3
  next_version_name: Review Feedback Preview V1
  handoff_condition: >
    v6.3 may define a preview only after v6.2 validates feedback and fails
    closed on invalid input.
  still_not_authorized:
    - implementation
    - executor_run
    - review_decision_creation
    - gate_event_emission
    - delivery_state_transition
```

中文解释：v6.2 是“看这份反馈能不能进入预览”，不是“看完就进入下一状态”。
