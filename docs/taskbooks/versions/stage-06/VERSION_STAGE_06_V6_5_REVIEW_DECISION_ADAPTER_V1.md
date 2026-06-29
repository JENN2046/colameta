# Version Taskbook: Stage 6 / v6.5 Review Decision Adapter V1

```text id="version-stage-06-v6-5-boundary-banner"
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
  version_id: stage_06_v6_5_review_decision_adapter_v1
  version: v6.5
  name: Review Decision Adapter V1
  chinese_name: 审查决策适配器 V1
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

`Review Decision Adapter V1` = 审查决策适配器 V1。中文意思是：把不同来源或旧口径的
审查反馈值规整到 Stage 6 的四个 ReviewDecision 值，但不创建 ReviewDecision 记录，
也不写 GateEvent。

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
    path: docs/taskbooks/versions/stage-06/VERSION_STAGE_06_V6_4_REVIEW_FEEDBACK_CLASSIFICATION_AND_DECISION_REQUEST_V1.md
    raw_snapshot_sha256: 34fd4bdca1a6cb4c21ee03a8836de0d6c35e6c3c9376be543cb9742dcf4ddcd5
    version_id: stage_06_v6_4_review_feedback_classification_and_decision_request_v1
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
    Define a bounded adapter that normalizes review feedback values and legacy
    aliases into the Stage 6 ReviewDecision value set while preserving policy
    refs, alias disclosure, binding refs, CommanderDecisionRequest boundaries,
    and Delivery State Gate separation.
  minimum_readiness_claim: >
    ColaMeta can ingest review feedback from nearby review surfaces without
    confusing legacy PASS, ReviewDecision.ACCEPT, runtime PASSED, or delivery
    state accepted.
  gate_question: >
    Can the adapter normalize review decision language without creating review
    records or state transitions?
  explicit_non_goal: >
    This version is not ReviewDecision persistence, not review acceptance, not
    GateEvent emission, not runtime state mapping, and not delivery state
    transition.
```

---

## 3. Adapter Contract

```yaml id="review-decision-adapter-contract"
review_decision_adapter_contract:
  accepted_native_values:
    - ACCEPT
    - NEEDS_FIX
    - PLAN_ADJUST
    - ABORT
  legacy_alias_values:
    PASS:
      normalized_value: ACCEPT
      requires_policy_ref: true
      must_surface_alias: true
      forbidden_meanings:
        - runtime_PASSED
        - delivery_state_accepted
        - validation_passed_as_review_acceptance
  required_outputs:
    - normalized_review_decision_value
    - alias_policy_ref_when_used
    - alias_disclosure
    - adapter_warnings
    - forbidden_meaning_check
  forbidden_outputs:
    - review_decision_record
    - gate_event
    - delivery_state_transition
    - runtime_state_transition
    - commander_authorization
```

`PASS alias` = PASS 别名。中文意思是：为了兼容旧表述，`PASS` 可以在有明确 policy ref
时映射成 `ReviewDecision.ACCEPT`，但绝不等于 runtime `PASSED` 或 delivery state
`accepted`。

---

## 4. Runtime Compatibility Boundary

```yaml id="runtime-compatibility-boundary"
runtime_compatibility_boundary:
  must_distinguish:
    - ReviewDecision.ACCEPT
    - legacy_PASS_alias
    - runtime_VERSION_PASSED
    - runtime_PASSED
    - delivery_state_accepted
  forbidden_equivalences:
    - PASS_equals_delivery_state_accepted
    - ACCEPT_equals_delivery_state_accepted
    - runtime_PASSED_equals_review_acceptance
    - validation_passed_equals_review_acceptance
  required_disclosures:
    - alias_policy_ref_when_PASS_is_used
    - normalized_value
    - original_value
    - no_delivery_state_transition_notice
```

---

## 5. Stage 6 Set Handoff

```yaml id="stage-6-set-handoff"
stage_6_set_handoff:
  stage_set_readiness_claim: >
    v6.1-v6.5 define the minimum review feedback intake protocol from schema,
    validation, preview, classification, CommanderDecisionRequest generation,
    and review decision adapter boundary.
  package_review_requires:
    - all previous_version_ref hashes resolved
    - all Chinese companion source hashes resolved
    - no ReviewDecision creation authority wording
    - no GateEvent emission authority wording
    - no plan mutation authority wording
    - no route transition authority wording
    - no delivery_state accepted wording
    - PASS alias requires explicit policy ref
  must_not_handoff_as:
    - review_acceptance
    - gate_event
    - delivery_state_accepted
    - plan_mutation
    - route_transition
    - executor_continuation
```

---

## 6. Candidate Execution Envelope

```yaml id="candidate-execution-envelope"
execution_envelope_candidate:
  authorization_status: not_authorized
  parent_hashes:
    master_taskbook_hash: 1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34
    stage_taskbook_hash: c83c979d447a4ec645d380b6c1dc206730d12d5d644c08582b3cfd04f3e0009d
    previous_version_hash: 34fd4bdca1a6cb4c21ee03a8836de0d6c35e6c3c9376be543cb9742dcf4ddcd5
    stage_5_version_set_confirmation_hash: ca23f567af50038469e3198b9a5600b1625e595c3381f20d262ab3aa81d61ea8
  task_goal_ref: task_goal.primary_goal
  definition_of_good:
    - adapter accepts only native values and policy-bound aliases
    - adapter surfaces original value normalized value and alias policy
    - adapter rejects runtime state equivalence
    - adapter does not create ReviewDecision or GateEvent
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
    - runner/review_decision_adapter.py
    - tests/test_review_decision_adapter.py
    - docs/taskbooks/versions/stage-06/evidence/VERSION_STAGE_06_V6_5_REVIEW_DECISION_ADAPTER_REPORT.md
    - docs/taskbooks/versions/stage-06/evidence/zh-CN/VERSION_STAGE_06_V6_5_REVIEW_DECISION_ADAPTER_REPORT.zh-CN.md
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
    - unknown_review_value
    - PASS_alias_without_policy_ref
    - alias_policy_ref_missing_or_untrusted
    - adapter_output_claims_review_decision_record
    - adapter_output_claims_gate_event
    - adapter_output_claims_delivery_state_transition
    - adapter_equates_runtime_PASSED_with_review_acceptance
```

---

## 9. Evidence Package Contract

```yaml id="evidence-package-contract"
evidence_package_contract:
  evidence_report_required: true
  evidence_report_must_include:
    - native_value_mapping_cases
    - pass_alias_policy_case
    - unknown_value_rejection_case
    - runtime_state_equivalence_rejection_case
    - forbidden_output_check
    - commands_run
    - commands_not_run
    - remaining_risks
  evidence_report_must_not_claim:
    - review_decision_created
    - gate_event_emitted
    - delivery_state_transitioned
```

---

## 10. Manual Acceptance Criteria For This Version

```yaml id="manual-acceptance-criteria"
manual_acceptance_criteria:
  can_be_accepted_for_next_step_when:
    - adapter preserves original value normalized value and policy ref
    - PASS alias requires explicit policy ref
    - runtime PASSED and delivery_state accepted remain separate
    - adapter output cannot create ReviewDecision GateEvent or state transition
  must_return_to_draft_when:
    - PASS can imply accepted delivery state
    - ACCEPT can imply accepted delivery state
    - adapter hides alias use
    - Chinese companion weakens runtime compatibility boundary
```

---

## 11. Thin Governed Loop Handoff

```yaml id="thin-governed-loop-handoff"
thin_governed_loop_handoff:
  stage_0_6_loop_readiness_claim: >
    Stage 0 through Stage 6 now have Version Taskbook candidate sets defining
    the minimum thin governed loop from baseline reality through reviewer
    feedback intake.
  still_not_authorized:
    - implementation
    - executor_run
    - review_decision_creation
    - gate_event_emission
    - delivery_state_transition
    - route_transition
    - push
```

中文解释：v6.5 把旧审查词和运行态词分开，防止 `PASS / PASSED / ACCEPT / accepted`
混成一团。Stage 0-6 到这里完成的是“最小治理闭环的计划骨架”，不是实现闭环。
