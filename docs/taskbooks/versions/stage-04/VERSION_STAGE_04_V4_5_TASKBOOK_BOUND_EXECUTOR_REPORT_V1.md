# Version Taskbook: Stage 4 / v4.5 Taskbook-bound Executor Report V1

```text id="version-stage-04-v4-5-boundary-banner"
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
  version_id: stage_04_v4_5_taskbook_bound_executor_report_v1
  version: v4.5
  name: Taskbook-bound Executor Report V1
  chinese_name: 任务书绑定执行器报告 V1
  parent_stage_id: stage_04_bounded_execution_and_evidence
  parent_stage_name: Bounded Execution And Evidence
  status: discussion_draft
  authority_status: planning_reference_only
  execution_authorization_status: not_authorized
  dispatch_status: not_authorized
  executor_run_authorized: false
  created_from_head: 588fb94
  created_from_head_full: 588fb94f2674bb9bcb417de600f6571b383054ed
  created_from_head_meaning: historical_creation_baseline_not_execution_or_freeze_snapshot
  created_from_head_subject: "docs: add stage 4 execution envelope taskbooks"
  origin_main_observed_local_tracking_ref: 018ff63
  local_tracking_ref_sync_status_at_creation: local_ahead_remote_tracking_ref
  local_ahead_origin_main_at_creation: 31
```

`Taskbook-bound Executor Report V1` = 任务书绑定执行器报告 V1。中文意思是：把本地
执行回执或导入回执整理成面向审查者的报告，但报告不能替代 receipt，也不能自我验收。

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
    path: docs/taskbooks/versions/stage-04/VERSION_STAGE_04_V4_4_IMPORTED_EXECUTION_RECEIPT_V1.md
    raw_snapshot_sha256: 24adc55f8176e41280ab2b7281d556f727cf714d86e7435124f66a6ed9c7ebc8
    version_id: stage_04_v4_4_imported_execution_receipt_v1
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
    Define a taskbook-bound executor report that summarizes one or more local
    or imported receipts, preserving receipt refs, authority modes, command
    results, changed files, validation truth, scope violations, known gaps, and
    remaining risks without claiming acceptance.
  minimum_readiness_claim: >
    ColaMeta can present execution evidence in a reviewable form while keeping
    receipts, reports, reviews, and delivery state distinct.
  gate_question: >
    Can a reviewer inspect execution evidence without the report laundering
    receipt claims into accepted delivery?
  explicit_non_goal: >
    This version is not executor dispatch, not evidence receipt hash, not review
    acceptance, not plan mutation, and not delivery state accepted.
```

---

## 3. Candidate Execution Envelope

```yaml id="candidate-execution-envelope"
execution_envelope_candidate:
  authorization_status: not_authorized
  parent_hashes:
    master_taskbook_hash: 1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34
    stage_taskbook_hash: 05e6114a666942c0641c635905c2295feaa62b98bd9e7b5166babd662e015a41
    previous_version_hash: 24adc55f8176e41280ab2b7281d556f727cf714d86e7435124f66a6ed9c7ebc8
    stage_3_version_set_confirmation_hash: 8695cf9f9b29608011dfc4691fd12df5a4f21f879e025e999c8bba5ae929e313
  task_goal_ref: task_goal.primary_goal
  definition_of_good:
    - report binds every claim to receipt refs
    - report preserves authority_mode
    - report separates executed, imported, validated, reviewed, and accepted
    - report includes changed files and validation truth
    - report cannot claim delivery_state accepted
```

---

## 4. Allowed Files And Mutations

```yaml id="allowed-files-and-mutations"
allowed_files:
  read_only:
    - PROJECT_MASTER_TASKBOOK.md
    - docs/taskbooks/stages/STAGE_04_BOUNDED_EXECUTION_AND_EVIDENCE.md
    - docs/taskbooks/versions/stage-04/VERSION_STAGE_04_V4_3_TASKBOOK_BOUND_LOCAL_EXECUTION_RECEIPT_V1.md
    - docs/taskbooks/versions/stage-04/VERSION_STAGE_04_V4_4_IMPORTED_EXECUTION_RECEIPT_V1.md
    - runner/**
    - tests/**
  writable_after_separate_execution_authorization:
    - runner/executor_report.py
    - tests/test_executor_report.py
    - docs/taskbooks/versions/stage-04/evidence/VERSION_STAGE_04_V4_5_EXECUTOR_REPORT.md
    - docs/taskbooks/versions/stage-04/evidence/zh-CN/VERSION_STAGE_04_V4_5_EXECUTOR_REPORT.zh-CN.md
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
    - .colameta/plan.json
    - .colameta/state.json
    - .colameta/runtime/**
    - .git/**
```

---

## 5. Executor Report Contract

```yaml id="executor-report-contract"
executor_report_contract:
  required_fields:
    - executor_report_id
    - report_schema_version
    - version_taskbook_ref
    - master_taskbook_hash
    - stage_taskbook_hash
    - receipt_refs
    - authority_modes
    - command_result_summary
    - changed_files_summary
    - validation_truth_summary
    - scope_check_summary
    - failures_and_blockers
    - known_gaps
    - remaining_risks
    - authority_boundary
  forbidden_claims:
    - receipt_without_ref
    - validation_passed_without_command_evidence
    - review_accepted
    - delivery_state_accepted
    - executor_self_acceptance
```

---

## 6. Evidence Package Contract

```yaml id="evidence-package-contract"
evidence_package_contract:
  evidence_package_id: stage_04_v4_5_executor_report_evidence
  required_artifacts:
    - executor_report_contract_summary
    - local_receipt_report_case
    - imported_receipt_report_case
    - validation_truth_summary_check
    - receipt_ref_integrity_check
    - commands_run
    - commands_not_run
    - known_gaps
    - remaining_risks
    - chinese_report_companion
```

---

## 7. Manual Acceptance Criteria

```yaml id="manual-acceptance"
manual_acceptance:
  reviewer_may_accept_if:
    - report binds claims to receipt refs
    - report preserves authority modes
    - report separates execution result from validation result
    - report includes failures, blockers, known gaps, and remaining risks
  reviewer_must_not_accept_if:
    - report claims review acceptance
    - report claims delivery_state accepted
    - report hides receipt refs
    - report summarizes validation as passed without command evidence
```

---

## 8. Next Version Handoff

```yaml id="next-version-handoff"
next_version_handoff:
  next_version: v4.6 Execution Evidence Receipt V1
  handoff_requires:
    - executor report preserves receipt refs
    - executor report is reviewable but non-accepting
    - validation truth and changed files are explicit
  must_not_handoff_as:
    - review_acceptance
    - delivery_state_accepted
```
