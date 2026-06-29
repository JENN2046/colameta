# Version Taskbook: Stage 4 / v4.6 Execution Evidence Receipt V1

```text id="version-stage-04-v4-6-boundary-banner"
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
  version_id: stage_04_v4_6_execution_evidence_receipt_v1
  version: v4.6
  name: Execution Evidence Receipt V1
  chinese_name: 执行证据回执 V1
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

`Execution Evidence Receipt V1` = 执行证据回执 V1。中文意思是：把执行报告、回执和
关键证据打成一个可引用的 evidence receipt，但它仍然不是 review decision。

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
    path: docs/taskbooks/versions/stage-04/VERSION_STAGE_04_V4_5_TASKBOOK_BOUND_EXECUTOR_REPORT_V1.md
    raw_snapshot_sha256: 55bf66619ecf07ea0aa71a39a9795018f7f45d03b9788301eaf4846ae9582b2f
    version_id: stage_04_v4_5_taskbook_bound_executor_report_v1
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
    Define an evidence receipt that packages executor report refs, receipt refs,
    changed file summary, validation truth summary, scope summary, known gaps,
    risks, and hash references into a stable reviewable evidence object.
  minimum_readiness_claim: >
    ColaMeta can provide a compact evidence object for later review without
    conflating evidence with review acceptance.
  gate_question: >
    Can execution evidence be referenced by later review packages without
    granting accepted delivery state?
  explicit_non_goal: >
    This version is not executor dispatch, not validation truth integration, not
    scope evidence pack, not review acceptance, and not delivery state accepted.
```

---

## 3. Candidate Execution Envelope

```yaml id="candidate-execution-envelope"
execution_envelope_candidate:
  authorization_status: not_authorized
  parent_hashes:
    master_taskbook_hash: 1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34
    stage_taskbook_hash: 05e6114a666942c0641c635905c2295feaa62b98bd9e7b5166babd662e015a41
    previous_version_hash: 55bf66619ecf07ea0aa71a39a9795018f7f45d03b9788301eaf4846ae9582b2f
    stage_3_version_set_confirmation_hash: 8695cf9f9b29608011dfc4691fd12df5a4f21f879e025e999c8bba5ae929e313
  task_goal_ref: task_goal.primary_goal
  definition_of_good:
    - evidence receipt binds report refs and receipt refs
    - evidence receipt records hashes for key evidence objects
    - evidence receipt preserves known gaps and remaining risks
    - evidence receipt is compact enough for reviewer handoff
    - evidence receipt cannot claim review acceptance or delivery_state accepted
```

---

## 4. Evidence Receipt Contract

```yaml id="evidence-receipt-contract"
execution_evidence_receipt_contract:
  required_fields:
    - evidence_receipt_id
    - evidence_receipt_schema_version
    - version_taskbook_ref
    - master_taskbook_hash
    - stage_taskbook_hash
    - executor_report_refs
    - execution_receipt_refs
    - changed_files_summary_ref
    - validation_truth_summary_ref
    - scope_summary_ref
    - evidence_hashes
    - known_gaps
    - remaining_risks
    - authority_boundary
  forbidden_claims:
    - review_accepted
    - delivery_state_accepted
    - executor_self_acceptance
    - validation_passed_without_command_evidence
```

---

## 5. Allowed Files And Mutations

```yaml id="allowed-files-and-mutations"
allowed_files:
  read_only:
    - PROJECT_MASTER_TASKBOOK.md
    - docs/taskbooks/stages/STAGE_04_BOUNDED_EXECUTION_AND_EVIDENCE.md
    - docs/taskbooks/versions/stage-04/VERSION_STAGE_04_V4_5_TASKBOOK_BOUND_EXECUTOR_REPORT_V1.md
    - runner/**
    - tests/**
  writable_after_separate_execution_authorization:
    - runner/execution_evidence_receipt.py
    - tests/test_execution_evidence_receipt.py
    - docs/taskbooks/versions/stage-04/evidence/VERSION_STAGE_04_V4_6_EXECUTION_EVIDENCE_RECEIPT_REPORT.md
    - docs/taskbooks/versions/stage-04/evidence/zh-CN/VERSION_STAGE_04_V4_6_EXECUTION_EVIDENCE_RECEIPT_REPORT.zh-CN.md
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
    - .git/**
```

---

## 6. Evidence Package Contract

```yaml id="evidence-package-contract"
evidence_package_contract:
  evidence_package_id: stage_04_v4_6_execution_evidence_receipt_evidence
  required_artifacts:
    - evidence_receipt_contract_summary
    - report_ref_integrity_case
    - receipt_ref_integrity_case
    - known_gap_preservation_check
    - non_acceptance_boundary_check
    - commands_run
    - commands_not_run
    - remaining_risks
    - chinese_report_companion
```

---

## 7. Manual Acceptance Criteria

```yaml id="manual-acceptance"
manual_acceptance:
  reviewer_may_accept_if:
    - evidence receipt binds executor report refs
    - evidence receipt binds execution receipt refs
    - evidence receipt preserves evidence hashes
    - evidence receipt preserves known gaps and remaining risks
  reviewer_must_not_accept_if:
    - evidence receipt claims review acceptance
    - evidence receipt claims delivery_state accepted
    - evidence receipt drops validation truth summary
    - evidence receipt hides scope summary
```

---

## 8. Next Version Handoff

```yaml id="next-version-handoff"
next_version_handoff:
  next_version: v4.7 Validation Truth Integration V1
  handoff_requires:
    - evidence receipt is reviewable and non-accepting
    - report refs and receipt refs are preserved
    - evidence hashes are explicit
  must_not_handoff_as:
    - validation_pass_authority
    - review_acceptance
    - delivery_state_accepted
```
