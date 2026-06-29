# Version Taskbook: Stage 2 / v2.3 Stage-to-Master Binding V1

```text id="version-stage-02-v2-3-boundary-banner"
VERSION TASKBOOK DRAFT ONLY.
This document defines a candidate Version Execution Taskbook for Stage 2. It
does not authorize execution, executor dispatch, code edits, commit, push,
fetch, pull, route transition, Master mutation, Stage Taskbook mutation,
registry mutation, project final goal mutation, Delivery State Gate transition,
or accepted delivery state.
```

```yaml id="version-taskbook-summary"
version_execution_taskbook:
  document_type: version_execution_taskbook
  schema_version: version_execution_taskbook.discussion_draft.v1
  version_id: stage_02_v2_3_stage_to_master_binding_v1
  version: v2.3
  name: Stage-to-Master Binding V1
  chinese_name: 阶段到主任务书绑定 V1
  parent_stage_id: stage_02_stage_taskbook_management
  parent_stage_name: Stage Taskbook Management
  status: discussion_draft
  authority_status: planning_reference_only
  execution_authorization_status: not_authorized
  dispatch_status: not_authorized
  executor_run_authorized: false
  created_from_head: 3819376
  created_from_head_full: 3819376aa1c4fc3ad8283b049fbfc6f0879be454
  created_from_head_meaning: historical_creation_baseline_not_execution_or_freeze_snapshot
  created_from_head_subject: "docs: add stage 2 registry version taskbook"
  origin_main_observed_local_tracking_ref: 018ff63
  local_tracking_ref_sync_status_at_creation: local_ahead_remote_tracking_ref
  local_ahead_origin_main_at_creation: 18
```

`Stage-to-Master Binding V1` = 阶段到主任务书绑定 V1。中文意思是：定义 Stage
Taskbook 和 Stage registry 如何绑定到同一份 Master Taskbook hash，确保 Stage
不能自己改写 `project_final_goal`，也不能把 Master 的 `freeze_candidate` 状态变成
执行授权。

---

## 1. Parent Binding

```yaml id="parent-binding"
parent_binding:
  master_taskbook_ref:
    path: PROJECT_MASTER_TASKBOOK.md
    raw_snapshot_sha256: 1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34
    review_status: freeze_candidate_confirmed_for_exact_hash
  stage_taskbook_ref:
    path: docs/taskbooks/stages/STAGE_02_STAGE_TASKBOOK_MANAGEMENT.md
    raw_snapshot_sha256: b0e1a55121503df4116d9c49031eb07729858c483cc73e6c97730eca0a067876
    stage_id: stage_02_stage_taskbook_management
  previous_version_ref:
    path: docs/taskbooks/versions/stage-02/VERSION_STAGE_02_V2_2_STAGE_TASKBOOK_REGISTRY_V1.md
    raw_snapshot_sha256: d43c791d76df839b0fa361955dc6208af9cce24a7594d045feb4062892f69050
    version_id: stage_02_v2_2_stage_taskbook_registry_v1
  stage_1_version_set_confirmation_ref:
    path: docs/taskbooks/versions/stage-01/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_01_VERSIONS.md
    raw_snapshot_sha256: c4ef865c84ab634a7b3626cdc6924a4e51420a1d6d94bb274aeb9f13d354fce5
    review_status: hash_specific_freeze_candidate_confirmation_recorded
  supports_project_goal: true
```

This Version Taskbook is subordinate to Stage 2 and must tighten the binding
between registered Stage Taskbooks and the exact Master Taskbook hash. If a
Stage record disagrees with Master, the Stage record is invalid rather than
authoritative.

中文解释：如果 Stage 和 Master 冲突，错的是 Stage 记录，不是 Master 被 Stage 重写。

---

## 2. Task Goal

```yaml id="task-goal"
task_goal:
  primary_goal: >
    Define the minimum Stage-to-Master binding rule that each registered Stage
    Taskbook must carry the exact master_taskbook_ref, preserve
    project_final_goal_ref, and fail closed when the Master hash or review-status
    boundary is missing, mismatched, or reinterpreted.
  minimum_readiness_claim: >
    A registered Stage Taskbook can prove which Master snapshot it serves and why
    it supports project_final_goal without becoming state authority.
  gate_question: >
    Can Stage records be rejected when they lack exact Master binding or try to
    reinterpret Master freeze_candidate status as execution authority?
  explicit_non_goal: >
    This version is not Master mutation, not project_final_goal editing, not
    Stage generation, not registry migration, not executor dispatch, and not
    delivery-state acceptance.
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
    stage_taskbook_hash: b0e1a55121503df4116d9c49031eb07729858c483cc73e6c97730eca0a067876
    previous_version_hash: d43c791d76df839b0fa361955dc6208af9cce24a7594d045feb4062892f69050
    stage_1_version_set_confirmation_hash: c4ef865c84ab634a7b3626cdc6924a4e51420a1d6d94bb274aeb9f13d354fce5
  task_goal_ref: task_goal.primary_goal
  definition_of_good:
    - binding contract requires exact master_taskbook_ref path and raw snapshot hash
    - binding contract requires project_final_goal_ref preservation
    - binding contract fails closed on missing or mismatched Master hash
    - binding contract rejects freeze_candidate_as_execution_authority
    - binding evidence distinguishes bound planning artifact from delivery_state accepted
  allowed_autonomy_after_explicit_authorization:
    - local file inspection
    - narrow binding helper creation or update under declared path
    - focused binding tests for missing, mismatched, and valid Master refs
    - narrow evidence report and Chinese report companion update
```

---

## 4. Allowed Files And Mutations

```yaml id="allowed-files-and-mutations"
allowed_files:
  read_only:
    - PROJECT_MASTER_TASKBOOK.md
    - docs/taskbooks/stages/STAGE_02_STAGE_TASKBOOK_MANAGEMENT.md
    - docs/taskbooks/versions/stage-02/VERSION_STAGE_02_V2_1_STAGE_TASKBOOK_SCHEMA_VALIDATOR_V1.md
    - docs/taskbooks/versions/stage-02/VERSION_STAGE_02_V2_2_STAGE_TASKBOOK_REGISTRY_V1.md
    - docs/taskbooks/stages/**
    - docs/taskbooks/versions/stage-00/**
    - docs/taskbooks/versions/stage-01/**
    - runner/**
    - tests/**
  writable_after_separate_execution_authorization:
    - runner/stage_to_master_binding.py
    - tests/test_stage_to_master_binding.py
    - docs/taskbooks/versions/stage-02/evidence/VERSION_STAGE_02_V2_3_STAGE_TO_MASTER_BINDING_REPORT.md
    - docs/taskbooks/versions/stage-02/evidence/zh-CN/VERSION_STAGE_02_V2_3_STAGE_TO_MASTER_BINDING_REPORT.zh-CN.md
forbidden_files:
  mutation_targets:
    - /home/jenn/tools/colameta/**
    - PROJECT_MASTER_TASKBOOK.md
    - PROJECT_MASTER_TASKBOOK.zh-CN.md
    - docs/taskbooks/stages/**
    - docs/taskbooks/versions/stage-00/**
    - docs/taskbooks/versions/stage-01/**
    - .colameta/state.json
    - .colameta/runtime/**
    - .git/**
    - "**/.env"
    - "**/*secret*"
    - "**/*credential*"
```

中文解释：v2.3 可以定义未来绑定 helper 和测试的候选路径，但不能现在修改 Master、
Stage Taskbook 或 registry。

---

## 5. Stage-to-Master Binding Minimum Contract

```yaml id="stage-to-master-binding-minimum-contract"
stage_to_master_binding_minimum_contract:
  required_fields:
    - master_taskbook_ref.path
    - master_taskbook_ref.raw_snapshot_sha256
    - master_taskbook_ref.review_status
    - project_final_goal_ref
    - supports_project_goal
    - support_rationale
    - source_stage_taskbook_ref
    - source_registry_record_ref
  fail_closed_when:
    - missing_master_taskbook_ref
    - master_hash_mismatch
    - missing_project_final_goal_ref
    - supports_project_goal_is_false_or_missing
    - stage_claims_master_mutation_authority
    - stage_claims_freeze_candidate_is_execution_authority
    - stage_claims_delivery_state_accepted
```

`support_rationale` = 支持理由。中文意思是：Stage 必须说明自己为什么服务项目最终目标，
不能只填一个布尔值。

---

## 6. Evidence Package Contract

```yaml id="evidence-package-contract"
evidence_package_contract:
  evidence_package_id: stage_02_v2_3_stage_to_master_binding_evidence
  required_artifacts:
    - binding_contract_summary
    - master_hash_match_check
    - project_final_goal_ref_preservation_check
    - freeze_candidate_boundary_check
    - negative_case_results
    - commands_run
    - commands_not_run
    - known_gaps
    - remaining_risks
    - chinese_report_companion
  must_not_include_as_authority:
    - Master mutation by Stage record
    - project_final_goal mutation by Stage record
    - delivery_state
    - runtime labels
```

---

## 7. Candidate Acceptance Commands

```yaml id="candidate-acceptance-commands"
acceptance_commands:
  preflight_read_only:
    - git status --short --branch
    - git rev-parse HEAD
    - sha256sum PROJECT_MASTER_TASKBOOK.md docs/taskbooks/stages/STAGE_02_STAGE_TASKBOOK_MANAGEMENT.md docs/taskbooks/versions/stage-02/VERSION_STAGE_02_V2_2_STAGE_TASKBOOK_REGISTRY_V1.md
  binding_validation:
    - python -m unittest tests.test_stage_to_master_binding
    - python -m compileall runner/stage_to_master_binding.py
  report_validation:
    - git diff --check -- docs/taskbooks/versions/stage-02/evidence/VERSION_STAGE_02_V2_3_STAGE_TO_MASTER_BINDING_REPORT.md docs/taskbooks/versions/stage-02/evidence/zh-CN/VERSION_STAGE_02_V2_3_STAGE_TO_MASTER_BINDING_REPORT.zh-CN.md
    - rg -n "binding_contract_summary|master_hash_match_check|project_final_goal_ref_preservation_check|freeze_candidate_boundary_check|remaining_risks" docs/taskbooks/versions/stage-02/evidence/VERSION_STAGE_02_V2_3_STAGE_TO_MASTER_BINDING_REPORT.md
```

These commands are candidates for later authorized execution only.

---

## 8. Manual Acceptance Criteria

```yaml id="manual-acceptance"
manual_acceptance:
  reviewer_may_accept_if:
    - binding rule requires exact Master path and raw snapshot hash
    - binding rule preserves project_final_goal_ref
    - binding rule rejects missing or mismatched Master refs
    - binding rule rejects Master freeze_candidate as execution authority
    - evidence report separates commands_run from commands_not_run
  reviewer_must_not_accept_if:
    - Stage record can override project_final_goal
    - Stage record can mutate Master
    - missing Master hash is accepted
    - binding result claims delivery_state accepted
```

---

## 9. Stop Conditions

```yaml id="stop-conditions"
stop_conditions:
  must_stop_if:
    - repository_path_is_not_/home/jenn/src/colameta-dev
    - implementation_would_mutate_PROJECT_MASTER_TASKBOOK_md
    - implementation_would_mutate_stage_taskbook_sources
    - implementation_would_mutate_project_final_goal
    - implementation_requires_/home/jenn/tools/colameta_changes
    - implementation_requires_fetch_pull_push_or_remote_write
    - binding_would_claim_delivery_state_accepted
    - binding_would_grant_execution_authority
    - required_hashes_do_not_match_declared_parent_hashes
```

---

## 10. Next Version Handoff

```yaml id="next-version-handoff"
next_version_handoff:
  next_version: v2.4 Stage Taskbook Gate-Readiness Contract V1
  handoff_requires:
    - exact Master binding contract is explicit
    - project_final_goal_ref preservation is explicit
    - freeze_candidate boundary is explicit
  must_not_handoff_as:
    - Master_mutation_authorization
    - execution_authorization
    - accepted_delivery_state
```
