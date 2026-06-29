# Version Taskbook: Stage 4 / v4.7 Validation Truth Integration V1

```text id="version-stage-04-v4-7-boundary-banner"
VERSION TASKBOOK DRAFT ONLY.
This document defines a candidate Version Execution Taskbook for Stage 4. It
does not authorize execution, executor dispatch, code edits, commit, push,
fetch, pull, route transition, plan mutation, review acceptance, Delivery State
Gate transition, or accepted delivery state.
```

```yaml id="version-taskbook-summary"
version_execution_taskbook:
  document_type: version_execution_taskbook
  schema_version: version_execution_taskbook.discussion_draft.v1
  version_id: stage_04_v4_7_validation_truth_integration_v1
  version: v4.7
  name: Validation Truth Integration V1
  chinese_name: 验证真相集成 V1
  parent_stage_id: stage_04_bounded_execution_and_evidence
  parent_stage_name: Bounded Execution And Evidence
  status: discussion_draft
  authority_status: planning_reference_only
  execution_authorization_status: not_authorized
  dispatch_status: not_authorized
  executor_run_authorized: false
  created_from_head: 6194279
  created_from_head_full: 619427962eee7c5415d1893be9a5b07c5a7cb285
  created_from_head_meaning: historical_creation_baseline_not_execution_or_freeze_snapshot
  created_from_head_subject: "docs: add stage 4 execution receipt taskbooks"
  origin_main_observed_local_tracking_ref: 018ff63
  local_tracking_ref_sync_status_at_creation: local_ahead_remote_tracking_ref
  local_ahead_origin_main_at_creation: 32
```

`Validation Truth Integration V1` = 验证真相集成 V1。中文意思是：把 validation
commands、实际结果、失败原因和未运行状态统一成可审查的真相字段，防止把失败或
未运行包装成 passed。

---

## 1. Parent Binding

```yaml id="parent-binding"
parent_binding:
  master_taskbook_ref:
    path: PROJECT_MASTER_TASKBOOK.md
    raw_snapshot_sha256: 1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34
    review_status: freeze_candidate_confirmed_for_exact_hash
  stage_taskbook_ref:
    path: docs/taskbooks/stages/STAGE_04_BOUNDED_EXECUTION_AND_EVIDENCE.md
    raw_snapshot_sha256: 05e6114a666942c0641c635905c2295feaa62b98bd9e7b5166babd662e015a41
    stage_id: stage_04_bounded_execution_and_evidence
  previous_version_ref:
    path: docs/taskbooks/versions/stage-04/VERSION_STAGE_04_V4_6_EXECUTION_EVIDENCE_RECEIPT_V1.md
    raw_snapshot_sha256: 320366232e7ad5b436d73178a60452766d3ce526c1fdf963a7a6e9395a62c8a4
    version_id: stage_04_v4_6_execution_evidence_receipt_v1
  stage_3_version_set_confirmation_ref:
    path: docs/taskbooks/versions/stage-03/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_03_VERSIONS.md
    raw_snapshot_sha256: 8695cf9f9b29608011dfc4691fd12df5a4f21f879e025e999c8bba5ae929e313
    review_status: hash_specific_freeze_candidate_confirmation_recorded
  supports_project_goal: true
```

---

## 2. Task Goal

```yaml id="task-goal"
task_goal:
  primary_goal: >
    Define a validation truth integration contract that records validation
    command identity, execution status, exit code, output summary, failure or
    blocker reason, evidence reference, and trust boundary for each validation.
  minimum_readiness_claim: >
    ColaMeta can distinguish passed, failed, blocked, not_run, and unvalidated
    results without collapsing them into a single PASSED label.
  gate_question: >
    Can later review rely on command-level validation truth instead of runtime
    summary labels?
  explicit_non_goal: >
    This version is not executor dispatch, not validation execution, not review
    acceptance, and not delivery state accepted.
```

---

## 3. Validation Truth Contract

```yaml id="validation-truth-contract"
validation_truth_contract:
  required_fields:
    - validation_truth_id
    - validation_command
    - command_source_ref
    - execution_status
    - exit_code
    - output_summary
    - evidence_ref
    - failure_reason
    - blocker_reason
    - known_gaps
    - authority_boundary
  valid_execution_statuses:
    - passed
    - failed
    - blocked
    - not_run
    - unvalidated
  forbidden_claims:
    - failed_summarized_as_passed
    - not_run_summarized_as_passed
    - unvalidated_summarized_as_passed
    - runtime_label_alone_as_truth
    - delivery_state_accepted
```

---

## 4. Candidate Execution Envelope

```yaml id="candidate-execution-envelope"
execution_envelope_candidate:
  authorization_status: not_authorized
  parent_hashes:
    master_taskbook_hash: 1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34
    stage_taskbook_hash: 05e6114a666942c0641c635905c2295feaa62b98bd9e7b5166babd662e015a41
    previous_version_hash: 320366232e7ad5b436d73178a60452766d3ce526c1fdf963a7a6e9395a62c8a4
    stage_3_version_set_confirmation_hash: 8695cf9f9b29608011dfc4691fd12df5a4f21f879e025e999c8bba5ae929e313
  task_goal_ref: task_goal.primary_goal
  definition_of_good:
    - validation truth distinguishes passed failed blocked not_run and unvalidated
    - validation truth binds to command evidence
    - validation truth rejects runtime label alone
    - validation truth cannot claim review acceptance
```

---

## 5. Allowed Files And Mutations

```yaml id="allowed-files-and-mutations"
allowed_files:
  read_only:
    - PROJECT_MASTER_TASKBOOK.md
    - docs/taskbooks/stages/STAGE_04_BOUNDED_EXECUTION_AND_EVIDENCE.md
    - docs/taskbooks/versions/stage-04/VERSION_STAGE_04_V4_6_EXECUTION_EVIDENCE_RECEIPT_V1.md
    - runner/**
    - tests/**
  writable_after_separate_execution_authorization:
    - runner/validation_truth.py
    - tests/test_validation_truth.py
    - docs/taskbooks/versions/stage-04/evidence/VERSION_STAGE_04_V4_7_VALIDATION_TRUTH_REPORT.md
    - docs/taskbooks/versions/stage-04/evidence/zh-CN/VERSION_STAGE_04_V4_7_VALIDATION_TRUTH_REPORT.zh-CN.md
forbidden_files:
  mutation_targets:
    - /home/jenn/tools/colameta/**
    - PROJECT_MASTER_TASKBOOK.md
    - docs/taskbooks/stages/**
    - docs/taskbooks/versions/stage-00/**
    - docs/taskbooks/versions/stage-01/**
    - docs/taskbooks/versions/stage-02/**
    - docs/taskbooks/versions/stage-03/**
    - .colameta/plan.json
    - .colameta/state.json
    - .git/**
```

---

## 6. Manual Acceptance Criteria

```yaml id="manual-acceptance"
manual_acceptance:
  reviewer_may_accept_if:
    - validation statuses distinguish passed failed blocked not_run and unvalidated
    - every passed claim has command evidence
    - failed validation cannot be summarized as passed
    - runtime PASSED label alone is rejected as validation truth
  reviewer_must_not_accept_if:
    - not_run is treated as passed
    - unvalidated is treated as passed
    - delivery_state accepted is inferred from validation status
```

---

## 7. Next Version Handoff

```yaml id="next-version-handoff"
next_version_handoff:
  next_version: v4.8 Scope Evidence Pack V1
  handoff_requires:
    - validation truth statuses are explicit
    - command evidence requirement is explicit
    - runtime label alone is non-authoritative
  must_not_handoff_as:
    - review_acceptance
    - delivery_state_accepted
```
