# Version Taskbook: Stage 4 / v4.9 Audit Package Taskbook Binding V1

```text id="version-stage-04-v4-9-boundary-banner"
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
  version_id: stage_04_v4_9_audit_package_taskbook_binding_v1
  version: v4.9
  name: Audit Package Taskbook Binding V1
  chinese_name: 审计包任务书绑定 V1
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

`Audit Package Taskbook Binding V1` = 审计包任务书绑定 V1。中文意思是：把 Stage 4 的
envelope、receipt、report、validation truth 和 scope evidence 绑定成一个 taskbook
bound audit package，供 Stage 5 reviewer handoff 使用。

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
    path: docs/taskbooks/versions/stage-04/VERSION_STAGE_04_V4_8_SCOPE_EVIDENCE_PACK_V1.md
    raw_snapshot_sha256: aef8eb8b4ba30ba640923f19045080166ecc31cf20a6f7213078d627241050e2
    version_id: stage_04_v4_8_scope_evidence_pack_v1
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
    Define a taskbook-bound audit package that references the execution envelope,
    run preview, local or imported receipts, executor report, evidence receipt,
    validation truth summary, scope evidence pack, risks, known gaps, and
    authority boundary for Stage 5 reviewer handoff.
  minimum_readiness_claim: >
    ColaMeta can hand off a bounded execution evidence package for review
    without claiming review acceptance or delivery state transition.
  gate_question: >
    Can Stage 5 receive a coherent audit package tied to the exact Version
    Taskbook and evidence objects?
  explicit_non_goal: >
    This version is not reviewer handoff implementation, not review decision,
    not executor dispatch, and not delivery state accepted.
```

---

## 3. Audit Package Contract

```yaml id="audit-package-contract"
audit_package_taskbook_binding_contract:
  required_fields:
    - audit_package_id
    - version_taskbook_ref
    - master_taskbook_hash
    - stage_taskbook_hash
    - execution_envelope_ref
    - run_preview_ref
    - execution_receipt_refs
    - executor_report_ref
    - execution_evidence_receipt_ref
    - validation_truth_summary_ref
    - scope_evidence_pack_ref
    - known_gaps
    - remaining_risks
    - handoff_readiness
    - authority_boundary
  valid_handoff_readiness:
    - ready_for_reviewer_handoff
    - blocked_missing_evidence
    - blocked_scope_violation
    - blocked_validation_failure
    - blocked_unknown_needs_review
  forbidden_claims:
    - reviewer_handoff_completed
    - review_accepted
    - delivery_state_accepted
    - executor_self_acceptance
```

---

## 4. Candidate Execution Envelope

```yaml id="candidate-execution-envelope"
execution_envelope_candidate:
  authorization_status: not_authorized
  parent_hashes:
    master_taskbook_hash: 1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34
    stage_taskbook_hash: 05e6114a666942c0641c635905c2295feaa62b98bd9e7b5166babd662e015a41
    previous_version_hash: aef8eb8b4ba30ba640923f19045080166ecc31cf20a6f7213078d627241050e2
    stage_3_version_set_confirmation_hash: 8695cf9f9b29608011dfc4691fd12df5a4f21f879e025e999c8bba5ae929e313
  task_goal_ref: task_goal.primary_goal
  definition_of_good:
    - audit package binds to exact version taskbook
    - audit package references envelope receipt report validation and scope objects
    - handoff readiness does not mean review acceptance
    - package carries known gaps and remaining risks
```

---

## 5. Allowed Files And Mutations

```yaml id="allowed-files-and-mutations"
allowed_files:
  read_only:
    - PROJECT_MASTER_TASKBOOK.md
    - docs/taskbooks/stages/STAGE_04_BOUNDED_EXECUTION_AND_EVIDENCE.md
    - docs/taskbooks/versions/stage-04/**
    - runner/**
    - tests/**
  writable_after_separate_execution_authorization:
    - runner/audit_package_taskbook_binding.py
    - tests/test_audit_package_taskbook_binding.py
    - docs/taskbooks/versions/stage-04/evidence/VERSION_STAGE_04_V4_9_AUDIT_PACKAGE_TASKBOOK_BINDING_REPORT.md
    - docs/taskbooks/versions/stage-04/evidence/zh-CN/VERSION_STAGE_04_V4_9_AUDIT_PACKAGE_TASKBOOK_BINDING_REPORT.zh-CN.md
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

## 6. Stage 4 Set Handoff

```yaml id="stage-4-set-handoff"
stage_4_set_handoff:
  stage_set_readiness_claim: >
    v4.1-v4.9 define the minimum bounded execution evidence protocol from
    envelope, run preview, local/imported receipts, executor report, evidence
    receipt, validation truth, scope evidence, and audit package binding.
  package_review_requires:
    - all previous_version_ref hashes resolved
    - all Chinese companion source hashes resolved
    - no executor run authority wording
    - no review acceptance wording
    - no delivery_state accepted wording
  must_not_handoff_as:
    - executor_run_authorization
    - reviewer_handoff_completion
    - review_acceptance
    - delivery_state_accepted
```
