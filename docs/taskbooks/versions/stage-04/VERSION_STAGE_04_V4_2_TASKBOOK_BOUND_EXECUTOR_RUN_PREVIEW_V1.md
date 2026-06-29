# Version Taskbook: Stage 4 / v4.2 Taskbook-bound Executor Run Preview V1

```text id="version-stage-04-v4-2-boundary-banner"
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
  version_id: stage_04_v4_2_taskbook_bound_executor_run_preview_v1
  version: v4.2
  name: Taskbook-bound Executor Run Preview V1
  chinese_name: 任务书绑定执行器运行预览 V1
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

`Taskbook-bound Executor Run Preview V1` = 任务书绑定执行器运行预览 V1。中文意思是：
把一个有效 ExecutionEnvelope 渲染成只读 run preview，让 Commander 看到 executor
如果被授权会做什么；预览本身不授权运行。

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
    path: docs/taskbooks/versions/stage-04/VERSION_STAGE_04_V4_1_MACHINE_CHECKABLE_EXECUTION_ENVELOPE_V1.md
    raw_snapshot_sha256: 22e99e01a854c6d8fe1fc4f0ceba38f5d2b1ce28d796596f80f4292459071dfa
    version_id: stage_04_v4_1_machine_checkable_execution_envelope_v1
  stage_3_version_set_confirmation_ref:
    path: docs/taskbooks/versions/stage-03/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_03_VERSIONS.md
    raw_snapshot_sha256: 8695cf9f9b29608011dfc4691fd12df5a4f21f879e025e999c8bba5ae929e313
    review_status: hash_specific_freeze_candidate_confirmation_recorded
  supports_project_goal: true
```

v4.2 consumes only a valid v4.1 envelope. It can preview what a run would do, but
it must not perform the run.

中文解释：run preview 是“先看会跑什么”，不是“现在开始跑”。

---

## 2. Task Goal

```yaml id="task-goal"
task_goal:
  primary_goal: >
    Define a read-only executor run preview that renders a valid
    ExecutionEnvelope into proposed commands, writable paths, expected
    mutations, validation commands, timeout limits, network and secrets
    policies, stop conditions, and required local execution authorization.
  minimum_readiness_claim: >
    ColaMeta can show a taskbook-bound execution plan before any executor run is
    authorized.
  gate_question: >
    Can Commander review the exact run request before dispatch authority exists?
  explicit_non_goal: >
    This version is not executor dispatch, not local execution receipt, not
    imported receipt adoption, not plan mutation, and not review acceptance.
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
    previous_version_hash: 22e99e01a854c6d8fe1fc4f0ceba38f5d2b1ce28d796596f80f4292459071dfa
    stage_3_version_set_confirmation_hash: 8695cf9f9b29608011dfc4691fd12df5a4f21f879e025e999c8bba5ae929e313
  task_goal_ref: task_goal.primary_goal
  definition_of_good:
    - preview accepts only valid envelope input
    - preview lists proposed commands and writable paths
    - preview labels all mutations as proposed
    - preview requires separate local_execution_authorization_ref before dispatch
    - preview states that no executor run is authorized
  allowed_autonomy_after_explicit_authorization:
    - local file inspection
    - narrow run preview helper creation or update under declared path
    - focused preview tests
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
    - docs/taskbooks/versions/stage-03/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_03_VERSIONS.md
    - runner/**
    - tests/**
  writable_after_separate_execution_authorization:
    - runner/executor_run_preview.py
    - tests/test_executor_run_preview.py
    - docs/taskbooks/versions/stage-04/evidence/VERSION_STAGE_04_V4_2_EXECUTOR_RUN_PREVIEW_REPORT.md
    - docs/taskbooks/versions/stage-04/evidence/zh-CN/VERSION_STAGE_04_V4_2_EXECUTOR_RUN_PREVIEW_REPORT.zh-CN.md
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

## 5. Run Preview Contract

```yaml id="run-preview-contract"
run_preview_contract:
  accepted_input:
    - execution_envelope_ref
    - envelope_validation_result
    - version_taskbook_ref
  required_output_fields:
    - run_preview_id
    - preview_status
    - execution_envelope_ref
    - version_taskbook_ref
    - authority_mode
    - required_local_execution_authorization_ref
    - proposed_commands
    - proposed_writable_paths
    - proposed_observed_mutation_categories
    - validation_commands
    - timeout_limits
    - network_policy
    - secrets_policy
    - destructive_operation_policy
    - stop_conditions
    - authority_boundary
  valid_preview_statuses:
    - preview_ready
    - preview_blocked_invalid_envelope
    - preview_blocked_missing_local_execution_authorization_ref
    - preview_blocked_authority_confusion
  forbidden_output_claims:
    - executor_run_authorized
    - dispatch_started
    - code_changes_authorized
    - commit_authorized
    - push_authorized
    - delivery_state_accepted
```

---

## 6. Evidence Package Contract

```yaml id="evidence-package-contract"
evidence_package_contract:
  evidence_package_id: stage_04_v4_2_executor_run_preview_evidence
  required_artifacts:
    - run_preview_contract_summary
    - valid_preview_example
    - invalid_envelope_negative_case
    - proposed_mutations_labeling_check
    - dispatch_non_authorization_check
    - commands_run
    - commands_not_run
    - known_gaps
    - remaining_risks
    - chinese_report_companion
  must_not_include_as_authority:
    - run preview
    - envelope existence
    - executor status
    - runtime labels
    - delivery_state
```

---

## 7. Candidate Acceptance Commands

```yaml id="candidate-acceptance-commands"
acceptance_commands:
  preflight_read_only:
    - git status --short --branch
    - git rev-parse HEAD
    - sha256sum docs/taskbooks/stages/STAGE_04_BOUNDED_EXECUTION_AND_EVIDENCE.md docs/taskbooks/versions/stage-04/VERSION_STAGE_04_V4_1_MACHINE_CHECKABLE_EXECUTION_ENVELOPE_V1.md
  preview_validation:
    - python -m unittest tests.test_executor_run_preview
    - python -m compileall runner/executor_run_preview.py
  report_validation:
    - git diff --check -- docs/taskbooks/versions/stage-04/evidence/VERSION_STAGE_04_V4_2_EXECUTOR_RUN_PREVIEW_REPORT.md docs/taskbooks/versions/stage-04/evidence/zh-CN/VERSION_STAGE_04_V4_2_EXECUTOR_RUN_PREVIEW_REPORT.zh-CN.md
    - rg -n "run_preview_contract_summary|invalid_envelope_negative_case|dispatch_non_authorization_check|remaining_risks" docs/taskbooks/versions/stage-04/evidence/VERSION_STAGE_04_V4_2_EXECUTOR_RUN_PREVIEW_REPORT.md
```

These commands are candidates for later authorized execution only.

---

## 8. Manual Acceptance Criteria

```yaml id="manual-acceptance"
manual_acceptance:
  reviewer_may_accept_if:
    - preview consumes only valid envelope input
    - preview lists proposed commands and writable paths
    - preview labels mutations as proposed only
    - preview does not start dispatch
    - evidence report separates commands_run from commands_not_run
  reviewer_must_not_accept_if:
    - preview authorizes executor run
    - preview treats proposed writable paths as already authorized mutations
    - preview hides missing local_execution_authorization_ref
    - preview maps validation summary to delivery_state accepted
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
    - preview_would_start_executor_dispatch
    - preview_would_claim_delivery_state_accepted
    - required_hashes_do_not_match_declared_parent_hashes
```

---

## 10. Next Version Handoff

```yaml id="next-version-handoff"
next_version_handoff:
  next_version: v4.3 Taskbook-bound Local Execution Receipt V1
  handoff_requires:
    - run preview output is read-only
    - proposed commands and writable paths are explicit
    - local execution authorization requirement is explicit
  must_not_handoff_as:
    - executor_run_authorization
    - local_execution_receipt
    - delivery_state_accepted
```
