# Version Taskbook: Stage 4 / v4.4 Imported Execution Receipt V1

```text id="version-stage-04-v4-4-boundary-banner"
VERSION TASKBOOK DRAFT ONLY.
This document defines a candidate Version Execution Taskbook for Stage 4. It
does not authorize execution, executor dispatch, code edits, commit, push,
fetch, pull, route transition, plan mutation, allowed_files expansion, imported
receipt adoption, review acceptance, Delivery State Gate transition, or accepted
delivery state.
```

```yaml id="version-taskbook-summary"
version_execution_taskbook:
  document_type: version_execution_taskbook
  schema_version: version_execution_taskbook.discussion_draft.v1
  version_id: stage_04_v4_4_imported_execution_receipt_v1
  version: v4.4
  name: Imported Execution Receipt V1
  chinese_name: 导入执行回执 V1
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

`Imported Execution Receipt V1` = 导入执行回执 V1。中文意思是：定义外部或人工提供的
执行回执如何被登记为 claim-only evidence；它不是本地执行，也不会自动采纳为事实。

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
    path: docs/taskbooks/versions/stage-04/VERSION_STAGE_04_V4_3_TASKBOOK_BOUND_LOCAL_EXECUTION_RECEIPT_V1.md
    raw_snapshot_sha256: d1ff43bf57a3279ed801a6440d7a8ead382d23873035878d560c74bf277d1342
    version_id: stage_04_v4_3_taskbook_bound_local_execution_receipt_v1
  stage_3_version_set_confirmation_ref:
    path: docs/taskbooks/versions/stage-03/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_03_VERSIONS.md
    raw_snapshot_sha256: 8695cf9f9b29608011dfc4691fd12df5a4f21f879e025e999c8bba5ae929e313
    review_status: hash_specific_freeze_candidate_confirmation_recorded
  supports_project_goal: true
```

v4.4 is the imported counterpart to v4.3. It must keep local execution authority
and imported receipt adoption authority separate.

---

## 2. Task Goal

```yaml id="task-goal"
task_goal:
  primary_goal: >
    Define an imported execution receipt contract that records external receipt
    provenance, imported_receipt_authorization_ref, source hash, claimed
    commands, claimed mutations, claimed validation results, confidence level,
    known gaps, and adoption blockers without treating the import as local
    execution or accepted delivery.
  minimum_readiness_claim: >
    ColaMeta can receive externally supplied execution evidence as a bounded
    claim without confusing it with local execution or review acceptance.
  gate_question: >
    Can imported execution evidence be represented without authorizing local
    dispatch, plan mutation, or delivery acceptance?
  explicit_non_goal: >
    This version is not local execution, not imported receipt adoption, not
    executor report aggregation, not review acceptance, and not delivery state
    accepted.
```

---

## 3. Candidate Execution Envelope

```yaml id="candidate-execution-envelope"
execution_envelope_candidate:
  authorization_status: not_authorized
  parent_hashes:
    master_taskbook_hash: 1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34
    stage_taskbook_hash: 05e6114a666942c0641c635905c2295feaa62b98bd9e7b5166babd662e015a41
    previous_version_hash: d1ff43bf57a3279ed801a6440d7a8ead382d23873035878d560c74bf277d1342
    stage_3_version_set_confirmation_hash: 8695cf9f9b29608011dfc4691fd12df5a4f21f879e025e999c8bba5ae929e313
  task_goal_ref: task_goal.primary_goal
  definition_of_good:
    - imported receipt requires imported_receipt_authorization_ref
    - imported receipt records provenance and source hash
    - imported receipt labels command and mutation data as claimed
    - imported receipt cannot authorize local dispatch
    - imported receipt cannot claim review acceptance or delivery_state accepted
  allowed_autonomy_after_explicit_authorization:
    - local file inspection
    - narrow imported receipt helper creation or update under declared path
    - focused imported receipt tests
    - narrow evidence report and Chinese report companion update
```

---

## 4. Allowed Files And Mutations

```yaml id="allowed-files-and-mutations"
allowed_files:
  read_only:
    - PROJECT_MASTER_TASKBOOK.md
    - docs/taskbooks/stages/STAGE_04_BOUNDED_EXECUTION_AND_EVIDENCE.md
    - docs/taskbooks/versions/stage-04/VERSION_STAGE_04_V4_3_TASKBOOK_BOUND_LOCAL_EXECUTION_RECEIPT_V1.md
    - docs/taskbooks/versions/stage-03/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_03_VERSIONS.md
    - runner/**
    - tests/**
  writable_after_separate_execution_authorization:
    - runner/imported_execution_receipt.py
    - tests/test_imported_execution_receipt.py
    - docs/taskbooks/versions/stage-04/evidence/VERSION_STAGE_04_V4_4_IMPORTED_EXECUTION_RECEIPT_REPORT.md
    - docs/taskbooks/versions/stage-04/evidence/zh-CN/VERSION_STAGE_04_V4_4_IMPORTED_EXECUTION_RECEIPT_REPORT.zh-CN.md
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
    - "**/.env"
    - "**/*secret*"
    - "**/*credential*"
```

---

## 5. Imported Receipt Contract

```yaml id="imported-receipt-contract"
imported_execution_receipt_contract:
  required_fields:
    - receipt_id
    - receipt_kind
    - imported_receipt_authorization_ref
    - source_provenance
    - source_receipt_hash
    - version_taskbook_ref
    - master_taskbook_hash
    - stage_taskbook_hash
    - claimed_execution_envelope_ref
    - claimed_commands
    - claimed_touched_files
    - claimed_mutations
    - claimed_validation_results
    - confidence_level
    - known_gaps
    - adoption_blockers
    - authority_boundary
  valid_receipt_kinds:
    - imported_execution_receipt
  forbidden_claims:
    - local_execution_performed
    - local_dispatch_authorized
    - imported_receipt_adopted_as_fact
    - review_accepted
    - delivery_state_accepted
```

---

## 6. Evidence Package Contract

```yaml id="evidence-package-contract"
evidence_package_contract:
  evidence_package_id: stage_04_v4_4_imported_execution_receipt_evidence
  required_artifacts:
    - imported_receipt_contract_summary
    - valid_imported_receipt_claim_case
    - missing_authorization_negative_case
    - local_dispatch_confusion_negative_case
    - adoption_boundary_check
    - commands_run
    - commands_not_run
    - known_gaps
    - remaining_risks
    - chinese_report_companion
  must_not_include_as_authority:
    - imported receipt reputation alone
    - local executor status
    - review acceptance
    - delivery_state
```

---

## 7. Candidate Acceptance Commands

```yaml id="candidate-acceptance-commands"
acceptance_commands:
  preflight_read_only:
    - git status --short --branch
    - git rev-parse HEAD
    - sha256sum docs/taskbooks/stages/STAGE_04_BOUNDED_EXECUTION_AND_EVIDENCE.md docs/taskbooks/versions/stage-04/VERSION_STAGE_04_V4_3_TASKBOOK_BOUND_LOCAL_EXECUTION_RECEIPT_V1.md
  receipt_validation:
    - python -m unittest tests.test_imported_execution_receipt
    - python -m compileall runner/imported_execution_receipt.py
  report_validation:
    - git diff --check -- docs/taskbooks/versions/stage-04/evidence/VERSION_STAGE_04_V4_4_IMPORTED_EXECUTION_RECEIPT_REPORT.md docs/taskbooks/versions/stage-04/evidence/zh-CN/VERSION_STAGE_04_V4_4_IMPORTED_EXECUTION_RECEIPT_REPORT.zh-CN.md
```

These commands are candidates for later authorized execution only.

---

## 8. Manual Acceptance Criteria

```yaml id="manual-acceptance"
manual_acceptance:
  reviewer_may_accept_if:
    - imported receipt requires imported_receipt_authorization_ref
    - imported receipt records provenance and source hash
    - imported commands and mutations are labeled as claimed
    - imported receipt cannot authorize local dispatch
    - evidence report separates commands_run from commands_not_run
  reviewer_must_not_accept_if:
    - imported receipt claims local execution occurred
    - imported receipt is adopted as fact without separate adoption authority
    - imported receipt claims review acceptance
    - imported receipt claims delivery_state accepted
```

---

## 9. Stop Conditions

```yaml id="stop-conditions"
stop_conditions:
  must_stop_if:
    - repository_path_is_not_/home/jenn/src/colameta-dev
    - implementation_would_mutate_colameta_plan
    - implementation_requires_/home/jenn/tools/colameta_changes
    - implementation_requires_fetch_pull_push_or_remote_write
    - receipt_would_claim_local_dispatch_authority
    - receipt_would_claim_delivery_state_accepted
    - required_hashes_do_not_match_declared_parent_hashes
```

---

## 10. Next Version Handoff

```yaml id="next-version-handoff"
next_version_handoff:
  next_version: v4.5 Taskbook-bound Executor Report V1
  handoff_requires:
    - imported receipt contract is claim-only
    - local and imported authority modes are distinct
    - imported receipt cannot self-accept delivery
  must_not_handoff_as:
    - local_execution_authorization
    - imported_receipt_adoption_authorization
    - delivery_state_accepted
```
