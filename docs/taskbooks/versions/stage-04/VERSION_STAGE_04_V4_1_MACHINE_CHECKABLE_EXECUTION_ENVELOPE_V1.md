# Version Taskbook: Stage 4 / v4.1 Machine-checkable Execution Envelope V1

```text id="version-stage-04-v4-1-boundary-banner"
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
  version_id: stage_04_v4_1_machine_checkable_execution_envelope_v1
  version: v4.1
  name: Machine-checkable Execution Envelope V1
  chinese_name: 机器可检查执行信封 V1
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

`Machine-checkable Execution Envelope V1` = 机器可检查执行信封 V1。中文意思是：
把一次候选执行允许做什么、禁止做什么、绑定哪个 Version Taskbook、用什么命令验证，
全部变成机器可检查的边界对象；它本身不授权 dispatch。

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
  stage_3_version_set_confirmation_ref:
    path: docs/taskbooks/versions/stage-03/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_03_VERSIONS.md
    raw_snapshot_sha256: 8695cf9f9b29608011dfc4691fd12df5a4f21f879e025e999c8bba5ae929e313
    review_status: hash_specific_freeze_candidate_confirmation_recorded
  supports_project_goal: true
```

v4.1 begins Stage 4. It consumes Stage 3 as an upstream planning anchor, but it
does not import an external taskbook, mutate a plan, or dispatch an executor.

中文解释：先把执行边界做成“信封”，再谈能不能跑；信封存在不等于可以跑。

---

## 2. Task Goal

```yaml id="task-goal"
task_goal:
  primary_goal: >
    Define a minimum machine-checkable ExecutionEnvelope contract for bounded
    local execution. The envelope must bind to Master, Stage, Version Taskbook,
    authority mode, allowed files, forbidden files, command set, validation
    expectations, timeout limits, network policy, secret policy, and stop
    conditions.
  minimum_readiness_claim: >
    ColaMeta can reject an execution request before dispatch when its envelope
    is missing authority, scope, command, validation, or safety boundaries.
  gate_question: >
    Can a candidate execution be checked for boundaries before any executor run
    is allowed?
  explicit_non_goal: >
    This version is not executor dispatch, not run preview, not local execution,
    not imported receipt adoption, not plan mutation, and not review acceptance.
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
    stage_3_version_set_confirmation_hash: 8695cf9f9b29608011dfc4691fd12df5a4f21f879e025e999c8bba5ae929e313
  task_goal_ref: task_goal.primary_goal
  definition_of_good:
    - envelope schema is explicit and machine-checkable
    - envelope requires version_taskbook_ref
    - envelope requires local_execution_authorization_ref when authority_mode is local_execution
    - envelope requires imported_receipt_authorization_ref when authority_mode is imported_receipt
    - envelope rejects missing allowed_files or forbidden_files
    - envelope existence does not authorize dispatch
  allowed_autonomy_after_explicit_authorization:
    - local file inspection
    - narrow envelope schema helper creation or update under declared path
    - focused envelope validation tests
    - narrow evidence report and Chinese report companion update
```

---

## 4. Allowed Files And Mutations

```yaml id="allowed-files-and-mutations"
allowed_files:
  read_only:
    - PROJECT_MASTER_TASKBOOK.md
    - docs/taskbooks/stages/STAGE_04_BOUNDED_EXECUTION_AND_EVIDENCE.md
    - docs/taskbooks/versions/stage-03/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_03_VERSIONS.md
    - runner/**
    - tests/**
  writable_after_separate_execution_authorization:
    - runner/execution_envelope.py
    - tests/test_execution_envelope.py
    - docs/taskbooks/versions/stage-04/evidence/VERSION_STAGE_04_V4_1_EXECUTION_ENVELOPE_REPORT.md
    - docs/taskbooks/versions/stage-04/evidence/zh-CN/VERSION_STAGE_04_V4_1_EXECUTION_ENVELOPE_REPORT.zh-CN.md
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

## 5. ExecutionEnvelope Minimum Contract

```yaml id="execution-envelope-minimum-contract"
execution_envelope_minimum_contract:
  required_fields:
    - envelope_id
    - envelope_schema_version
    - version_taskbook_ref
    - master_taskbook_ref
    - stage_taskbook_ref
    - authority_mode
    - local_execution_authorization_ref
    - imported_receipt_authorization_ref
    - allowed_files
    - forbidden_files
    - allowed_commands
    - validation_commands
    - timeout_limits
    - network_policy
    - secrets_policy
    - destructive_operation_policy
    - retry_policy
    - stop_conditions
  valid_authority_modes:
    - local_execution
    - imported_receipt
    - validation_only
  forbidden_claims:
    - dispatch_authorized_by_envelope_existence
    - allowed_files_expansion_authorized
    - plan_mutation_authorized
    - commit_authorized
    - push_authorized
    - delivery_state_accepted
```

`authority_mode` = 权限模式。中文意思是：说明这个信封是为本地执行、外部回执还是
只验证而准备；不同模式不能混用授权。

---

## 6. Rejection Rules

```yaml id="rejection-rules"
rejection_rules:
  reject_when:
    - version_taskbook_ref_missing
    - master_taskbook_ref_missing_or_mismatched
    - stage_taskbook_ref_missing_or_mismatched
    - authority_mode_missing_or_unknown
    - local_execution_mode_without_local_execution_authorization_ref
    - imported_receipt_mode_without_imported_receipt_authorization_ref
    - allowed_files_missing_or_empty
    - forbidden_files_missing
    - validation_commands_missing
    - network_policy_missing
    - secrets_policy_missing
    - destructive_operation_policy_missing
    - envelope_claims_dispatch_authority
    - envelope_claims_delivery_state_accepted
```

---

## 7. Evidence Package Contract

```yaml id="evidence-package-contract"
evidence_package_contract:
  evidence_package_id: stage_04_v4_1_execution_envelope_evidence
  required_artifacts:
    - envelope_contract_summary
    - valid_envelope_example
    - rejected_envelope_examples
    - authority_mode_check
    - boundary_non_authorization_check
    - commands_run
    - commands_not_run
    - known_gaps
    - remaining_risks
    - chinese_report_companion
  must_not_include_as_authority:
    - envelope existence
    - executor status
    - runtime labels
    - reviewer acceptance
    - delivery_state
```

---

## 8. Candidate Acceptance Commands

```yaml id="candidate-acceptance-commands"
acceptance_commands:
  preflight_read_only:
    - git status --short --branch
    - git rev-parse HEAD
    - sha256sum PROJECT_MASTER_TASKBOOK.md docs/taskbooks/stages/STAGE_04_BOUNDED_EXECUTION_AND_EVIDENCE.md
  envelope_validation:
    - python -m unittest tests.test_execution_envelope
    - python -m compileall runner/execution_envelope.py
  report_validation:
    - git diff --check -- docs/taskbooks/versions/stage-04/evidence/VERSION_STAGE_04_V4_1_EXECUTION_ENVELOPE_REPORT.md docs/taskbooks/versions/stage-04/evidence/zh-CN/VERSION_STAGE_04_V4_1_EXECUTION_ENVELOPE_REPORT.zh-CN.md
    - rg -n "envelope_contract_summary|rejected_envelope_examples|authority_mode_check|remaining_risks" docs/taskbooks/versions/stage-04/evidence/VERSION_STAGE_04_V4_1_EXECUTION_ENVELOPE_REPORT.md
```

These commands are candidates for later authorized execution only.

---

## 9. Manual Acceptance Criteria

```yaml id="manual-acceptance"
manual_acceptance:
  reviewer_may_accept_if:
    - envelope requires version_taskbook_ref
    - envelope requires authority_mode
    - envelope rejects missing allowed_files or validation_commands
    - envelope rejects dispatch authority claims
    - evidence report separates commands_run from commands_not_run
  reviewer_must_not_accept_if:
    - envelope existence authorizes dispatch
    - local_execution_authorization_ref authorizes imported receipt adoption
    - imported_receipt_authorization_ref authorizes local dispatch
    - envelope maps validation summary to delivery_state accepted
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
    - envelope_would_authorize_dispatch_by_itself
    - envelope_would_claim_delivery_state_accepted
    - required_hashes_do_not_match_declared_parent_hashes
```

---

## 11. Next Version Handoff

```yaml id="next-version-handoff"
next_version_handoff:
  next_version: v4.2 Taskbook-bound Executor Run Preview V1
  handoff_requires:
    - envelope schema is explicit
    - rejection rules are explicit
    - envelope existence is non-authoritative for dispatch
  must_not_handoff_as:
    - executor_run_authorization
    - plan_mutation_authorization
    - delivery_state_accepted
```
