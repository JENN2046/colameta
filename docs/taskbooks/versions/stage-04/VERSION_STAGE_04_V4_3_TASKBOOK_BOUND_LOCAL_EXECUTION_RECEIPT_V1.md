# Version Taskbook: Stage 4 / v4.3 Taskbook-bound Local Execution Receipt V1

```text id="version-stage-04-v4-3-boundary-banner"
VERSION TASKBOOK DRAFT ONLY.
This document defines a candidate Version Execution Taskbook for Stage 4. It
does not authorize execution, executor dispatch, code edits, commit, push,
fetch, pull, route transition, plan mutation, allowed_files expansion, import
adoption, review acceptance, Delivery State Gate transition, or accepted
delivery state.
```

```yaml id="version-taskbook-summary"
version_execution_taskbook:
  document_type: version_execution_taskbook
  schema_version: version_execution_taskbook.discussion_draft.v1
  version_id: stage_04_v4_3_taskbook_bound_local_execution_receipt_v1
  version: v4.3
  name: Taskbook-bound Local Execution Receipt V1
  chinese_name: 任务书绑定本地执行回执 V1
  parent_stage_id: stage_04_bounded_execution_and_evidence
  parent_stage_name: Bounded Execution And Evidence
  status: discussion_draft
  authority_status: planning_reference_only
  execution_authorization_status: not_authorized
  dispatch_status: not_authorized
  executor_run_authorized: false
  created_from_head: 1a42cc8
  created_from_head_full: 1a42cc8179fab81087b75e562eb4885a1af77cce
  created_from_head_meaning: historical_creation_baseline_not_execution_or_freeze_snapshot
  created_from_head_subject: "docs: record stage 3 version freeze confirmation"
  origin_main_observed_local_tracking_ref: 018ff63
  local_tracking_ref_sync_status_at_creation: local_ahead_remote_tracking_ref
  local_ahead_origin_main_at_creation: 30
```

`Taskbook-bound Local Execution Receipt V1` = 任务书绑定本地执行回执 V1。中文意思是：
定义本地执行已经发生之后必须留下什么证据；它不授权执行，只约束回执格式和真实性。

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
    path: docs/taskbooks/versions/stage-04/VERSION_STAGE_04_V4_2_TASKBOOK_BOUND_EXECUTOR_RUN_PREVIEW_V1.md
    raw_snapshot_sha256: e4f02abe34af18ea0b1ef8cc94006dc5dddf04e0e80f0ca65f9f393ae8b617a2
    version_id: stage_04_v4_2_taskbook_bound_executor_run_preview_v1
  stage_3_version_set_confirmation_ref:
    path: docs/taskbooks/versions/stage-03/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_03_VERSIONS.md
    raw_snapshot_sha256: 8695cf9f9b29608011dfc4691fd12df5a4f21f879e025e999c8bba5ae929e313
    review_status: hash_specific_freeze_candidate_confirmation_recorded
  supports_project_goal: true
```

v4.3 defines receipt shape for later authorized local execution. It must not
turn a receipt into reviewer acceptance or delivery state accepted.

中文解释：回执是“实际发生了什么”的证据，不是“审查已经通过”的判决。

---

## 2. Task Goal

```yaml id="task-goal"
task_goal:
  primary_goal: >
    Define a taskbook-bound local execution receipt contract that records exact
    authorization ref, envelope ref, run preview ref, command attempts,
    timestamps, touched files, observed mutations, validation commands,
    validation results, failures, blocked states, and residual risks.
  minimum_readiness_claim: >
    ColaMeta can record local execution evidence without confusing executed,
    validated, reviewed, and accepted.
  gate_question: >
    Can a local executor run leave enough evidence for later review without
    self-accepting the delivery?
  explicit_non_goal: >
    This version is not executor dispatch, not imported receipt adoption, not
    executor report aggregation, not plan mutation, and not review acceptance.
```

---

## 3. Candidate Execution Envelope

This section is an envelope candidate only. It becomes executable only if the
Commander separately authorizes it by exact hash and scope.

```yaml id="candidate-execution-envelope"
execution_envelope_candidate:
  authorization_status: not_authorized
  parent_hashes:
    master_taskbook_hash: 1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34
    stage_taskbook_hash: 05e6114a666942c0641c635905c2295feaa62b98bd9e7b5166babd662e015a41
    previous_version_hash: e4f02abe34af18ea0b1ef8cc94006dc5dddf04e0e80f0ca65f9f393ae8b617a2
    stage_3_version_set_confirmation_hash: 8695cf9f9b29608011dfc4691fd12df5a4f21f879e025e999c8bba5ae929e313
  task_goal_ref: task_goal.primary_goal
  definition_of_good:
    - receipt binds to exact local_execution_authorization_ref
    - receipt binds to execution_envelope_ref and run_preview_ref
    - receipt distinguishes executed from validated
    - receipt records command outcomes and touched files
    - receipt cannot claim review acceptance or delivery_state accepted
  allowed_autonomy_after_explicit_authorization:
    - local file inspection
    - narrow local receipt helper creation or update under declared path
    - focused receipt tests
    - narrow evidence report and Chinese report companion update
```

---

## 4. Allowed Files And Mutations

```yaml id="allowed-files-and-mutations"
allowed_files:
  read_only:
    - PROJECT_MASTER_TASKBOOK.md
    - docs/taskbooks/stages/STAGE_04_BOUNDED_EXECUTION_AND_EVIDENCE.md
    - docs/taskbooks/versions/stage-04/VERSION_STAGE_04_V4_1_MACHINE_CHECKABLE_EXECUTION_ENVELOPE_V1.md
    - docs/taskbooks/versions/stage-04/VERSION_STAGE_04_V4_2_TASKBOOK_BOUND_EXECUTOR_RUN_PREVIEW_V1.md
    - docs/taskbooks/versions/stage-03/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_03_VERSIONS.md
    - runner/**
    - tests/**
  writable_after_separate_execution_authorization:
    - runner/local_execution_receipt.py
    - tests/test_local_execution_receipt.py
    - docs/taskbooks/versions/stage-04/evidence/VERSION_STAGE_04_V4_3_LOCAL_EXECUTION_RECEIPT_REPORT.md
    - docs/taskbooks/versions/stage-04/evidence/zh-CN/VERSION_STAGE_04_V4_3_LOCAL_EXECUTION_RECEIPT_REPORT.zh-CN.md
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

## 5. Local Execution Receipt Contract

```yaml id="local-execution-receipt-contract"
local_execution_receipt_contract:
  required_fields:
    - receipt_id
    - receipt_schema_version
    - receipt_kind
    - local_execution_authorization_ref
    - execution_envelope_ref
    - run_preview_ref
    - version_taskbook_ref
    - master_taskbook_hash
    - stage_taskbook_hash
    - started_at
    - completed_at
    - command_attempts
    - touched_files
    - observed_mutations
    - validation_commands
    - validation_results
    - scope_check_result
    - blocked_or_failed_reasons
    - known_gaps
    - remaining_risks
  valid_receipt_kinds:
    - local_execution_receipt
  valid_execution_results:
    - executed
    - executed_with_failures
    - blocked_before_execution
    - failed_scope_check
  valid_validation_results:
    - passed
    - failed
    - blocked
    - not_run
    - unvalidated
  forbidden_claims:
    - review_accepted
    - delivery_state_accepted
    - plan_mutation_authorized
    - commit_authorized
    - push_authorized
```

---

## 6. Receipt Truth Rules

```yaml id="receipt-truth-rules"
receipt_truth_rules:
  must_distinguish:
    - executed
    - validated
    - reviewed
    - accepted
  must_fail_closed_when:
    - local_execution_authorization_ref_missing
    - execution_envelope_ref_missing
    - run_preview_ref_missing
    - command_attempts_missing
    - touched_files_unknown_without_known_gap
    - validation_failed_but_summary_claims_passed
    - receipt_claims_delivery_state_accepted
```

---

## 7. Evidence Package Contract

```yaml id="evidence-package-contract"
evidence_package_contract:
  evidence_package_id: stage_04_v4_3_local_execution_receipt_evidence
  required_artifacts:
    - receipt_contract_summary
    - executed_positive_case
    - blocked_before_execution_case
    - validation_failed_case
    - scope_violation_case
    - truth_distinction_check
    - commands_run
    - commands_not_run
    - known_gaps
    - remaining_risks
    - chinese_report_companion
  must_not_include_as_authority:
    - executor self-acceptance
    - validation summary without command evidence
    - runtime PASSED label alone
    - delivery_state
```

---

## 8. Candidate Acceptance Commands

```yaml id="candidate-acceptance-commands"
acceptance_commands:
  preflight_read_only:
    - git status --short --branch
    - git rev-parse HEAD
    - sha256sum docs/taskbooks/stages/STAGE_04_BOUNDED_EXECUTION_AND_EVIDENCE.md docs/taskbooks/versions/stage-04/VERSION_STAGE_04_V4_2_TASKBOOK_BOUND_EXECUTOR_RUN_PREVIEW_V1.md
  receipt_validation:
    - python -m unittest tests.test_local_execution_receipt
    - python -m compileall runner/local_execution_receipt.py
  report_validation:
    - git diff --check -- docs/taskbooks/versions/stage-04/evidence/VERSION_STAGE_04_V4_3_LOCAL_EXECUTION_RECEIPT_REPORT.md docs/taskbooks/versions/stage-04/evidence/zh-CN/VERSION_STAGE_04_V4_3_LOCAL_EXECUTION_RECEIPT_REPORT.zh-CN.md
    - rg -n "receipt_contract_summary|truth_distinction_check|validation_failed_case|remaining_risks" docs/taskbooks/versions/stage-04/evidence/VERSION_STAGE_04_V4_3_LOCAL_EXECUTION_RECEIPT_REPORT.md
```

These commands are candidates for later authorized execution only.

---

## 9. Manual Acceptance Criteria

```yaml id="manual-acceptance"
manual_acceptance:
  reviewer_may_accept_if:
    - receipt binds to local_execution_authorization_ref
    - receipt binds to execution_envelope_ref and run_preview_ref
    - receipt distinguishes executed from validated
    - receipt records touched files and observed mutations
    - evidence report separates commands_run from commands_not_run
  reviewer_must_not_accept_if:
    - receipt claims review acceptance
    - receipt claims delivery_state accepted
    - receipt hides validation failure
    - receipt treats runtime PASSED label alone as proof
```

---

## 10. Stop Conditions

```yaml id="stop-conditions"
stop_conditions:
  must_stop_if:
    - repository_path_is_not_/home/jenn/src/colameta-dev
    - implementation_would_mutate_colameta_plan
    - implementation_requires_/home/jenn/tools/colameta_changes
    - implementation_requires_fetch_pull_push_or_remote_write
    - receipt_would_claim_review_acceptance
    - receipt_would_claim_delivery_state_accepted
    - required_hashes_do_not_match_declared_parent_hashes
```

---

## 11. Next Version Handoff

```yaml id="next-version-handoff"
next_version_handoff:
  next_version: v4.4 Imported Execution Receipt V1
  handoff_requires:
    - local execution receipt contract is explicit
    - executed and validated are distinguished
    - receipt cannot self-accept delivery
  must_not_handoff_as:
    - imported_receipt_adoption_authorization
    - review_acceptance
    - delivery_state_accepted
```
