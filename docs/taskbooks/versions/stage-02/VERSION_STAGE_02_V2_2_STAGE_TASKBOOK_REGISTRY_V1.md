# Version Taskbook: Stage 2 / v2.2 Stage Taskbook Registry V1

```text id="version-stage-02-v2-2-boundary-banner"
VERSION TASKBOOK DRAFT ONLY.
This document defines a candidate Version Execution Taskbook for Stage 2. It
does not authorize execution, executor dispatch, code edits, commit, push,
fetch, pull, route transition, Master mutation, Stage Taskbook mutation,
registry mutation, Delivery State Gate transition, or accepted delivery state.
```

```yaml id="version-taskbook-summary"
version_execution_taskbook:
  document_type: version_execution_taskbook
  schema_version: version_execution_taskbook.discussion_draft.v1
  version_id: stage_02_v2_2_stage_taskbook_registry_v1
  version: v2.2
  name: Stage Taskbook Registry V1
  chinese_name: 阶段任务书登记表 V1
  parent_stage_id: stage_02_stage_taskbook_management
  parent_stage_name: Stage Taskbook Management
  status: discussion_draft
  authority_status: planning_reference_only
  execution_authorization_status: not_authorized
  dispatch_status: not_authorized
  executor_run_authorized: false
  created_from_head: 8f31fd8
  created_from_head_full: 8f31fd8b2b1736f48c765a3dd187d7cddd6b04ad
  created_from_head_meaning: historical_creation_baseline_not_execution_or_freeze_snapshot
  created_from_head_subject: "docs: add stage 2 schema validator version taskbook"
  origin_main_observed_local_tracking_ref: 018ff63
  local_tracking_ref_sync_status_at_creation: local_ahead_remote_tracking_ref
  local_ahead_origin_main_at_creation: 17
```

`Stage Taskbook Registry V1` = 阶段任务书登记表 V1。中文意思是：定义一份最小机器
可读 registry，用来记录每个 Stage Taskbook 的 stage_id、path、hash、Master 绑定、
校验结果和 gate-readiness summary。

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
    path: docs/taskbooks/versions/stage-02/VERSION_STAGE_02_V2_1_STAGE_TASKBOOK_SCHEMA_VALIDATOR_V1.md
    raw_snapshot_sha256: 76c3c12c191609f94c16d292e40217db08c8020792157639011b046cb977c429
    version_id: stage_02_v2_1_stage_taskbook_schema_validator_v1
  stage_0_6_freeze_packet_ref:
    path: docs/taskbooks/stages/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_0_6.md
    raw_snapshot_sha256: 94ea9101a120e0935e834533ed0315a6fe3e77e3d4ecb48db37fa6851e75b5ce
    review_status: hash_specific_freeze_candidate_confirmation_recorded
  stage_1_version_set_confirmation_ref:
    path: docs/taskbooks/versions/stage-01/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_01_VERSIONS.md
    raw_snapshot_sha256: c4ef865c84ab634a7b3626cdc6924a4e51420a1d6d94bb274aeb9f13d354fce5
    review_status: hash_specific_freeze_candidate_confirmation_recorded
  supports_project_goal: true
```

This Version Taskbook is subordinate to Stage 2 and must consume the v2.1 schema
and validator contract. It must not bypass validation in order to register a
Stage Taskbook.

中文解释：v2.2 只定义“登记记录长什么样”。它不能绕过 v2.1 校验，也不能靠登记记录
授予执行或 accepted。

---

## 2. Task Goal

```yaml id="task-goal"
task_goal:
  primary_goal: >
    Define a minimal Stage Taskbook registry contract that records stage id,
    path, source hash, master_taskbook_ref, validator result, gate-readiness
    summary, and authority boundary for registered Stage Taskbooks.
  minimum_readiness_claim: >
    Later Version Taskbooks can reference a registered stage_taskbook_ref without
    treating the registry as execution or delivery-state authority.
  gate_question: >
    Can the project identify which Stage Taskbook hash is registered, which
    Master hash it binds to, and whether it passed the v2.1 validator?
  explicit_non_goal: >
    This version is not bootstrap migration, not automatic Stage generation, not
    registry mutation authorization, not executor dispatch, and not accepted
    delivery state.
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
    previous_version_hash: 76c3c12c191609f94c16d292e40217db08c8020792157639011b046cb977c429
    stage_0_6_freeze_packet_hash: 94ea9101a120e0935e834533ed0315a6fe3e77e3d4ecb48db37fa6851e75b5ce
    stage_1_version_set_confirmation_hash: c4ef865c84ab634a7b3626cdc6924a4e51420a1d6d94bb274aeb9f13d354fce5
  task_goal_ref: task_goal.primary_goal
  definition_of_good:
    - registry record schema is explicit and machine-checkable
    - registry requires validator_result from v2.1-compatible validator
    - registry stores exact stage_taskbook_hash and master_taskbook_ref
    - registry distinguishes gate-readiness from delivery_state accepted
    - registry mutation is separately authorized and receipt-backed
  allowed_autonomy_after_explicit_authorization:
    - local file inspection
    - narrow registry contract creation or update under declared path
    - focused registry parsing and validation tests
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
    - docs/taskbooks/stages/**
    - docs/taskbooks/versions/stage-00/**
    - docs/taskbooks/versions/stage-01/**
    - docs/taskbooks/CHINESE_COMPANION_POLICY.md
    - docs/taskbooks/CHINESE_COMPANION_INDEX.md
    - runner/**
    - tests/**
  writable_after_separate_execution_authorization:
    - .colameta/taskbooks/stage_taskbook_registry.json
    - runner/stage_taskbook_registry.py
    - tests/test_stage_taskbook_registry.py
    - docs/taskbooks/versions/stage-02/evidence/VERSION_STAGE_02_V2_2_STAGE_TASKBOOK_REGISTRY_REPORT.md
    - docs/taskbooks/versions/stage-02/evidence/zh-CN/VERSION_STAGE_02_V2_2_STAGE_TASKBOOK_REGISTRY_REPORT.zh-CN.md
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

中文解释：v2.2 的候选写入范围是 registry 合约、registry helper、测试和证据报告。
现在写这份任务书不授权实际写 registry。

---

## 5. Stage Registry Minimum Contract

```yaml id="stage-registry-minimum-contract"
stage_registry_minimum_contract:
  registry_path_candidate: .colameta/taskbooks/stage_taskbook_registry.json
  record_key: stage_id
  required_fields:
    - stage_id
    - stage_name
    - stage_taskbook_path
    - stage_taskbook_raw_snapshot_sha256
    - master_taskbook_ref
    - supports_project_goal
    - validator_result
    - gate_readiness_summary
    - non_goals_summary
    - authority_boundary
    - source_version_taskbook_ref
    - observed_git_head
    - created_at
  forbidden_authority_claims:
    - registered_stage_is_accepted_delivery_state
    - registered_stage_authorizes_execution
    - registry_can_mutate_stage_taskbook
    - registry_can_override_delivery_state_gate
```

`Stage Registry` = 阶段登记表。中文意思是：机器可读地记录每个 Stage Taskbook 的
路径、hash、Master 绑定和校验结果。登记表不是执行授权。

---

## 6. Evidence Package Contract

```yaml id="evidence-package-contract"
evidence_package_contract:
  evidence_package_id: stage_02_v2_2_stage_taskbook_registry_evidence
  required_artifacts:
    - registry_contract_summary
    - registry_record_schema
    - validator_result_consumption_check
    - registered_stage_hash_check
    - authority_boundary_check
    - commands_run
    - commands_not_run
    - known_gaps
    - remaining_risks
    - chinese_report_companion
  must_not_include_as_authority:
    - chat memory
    - runtime labels
    - registry existence as execution authorization
    - reviewer acceptance
    - delivery_state
```

---

## 7. Candidate Acceptance Commands

```yaml id="candidate-acceptance-commands"
acceptance_commands:
  preflight_read_only:
    - git status --short --branch
    - git rev-parse HEAD
    - sha256sum docs/taskbooks/stages/STAGE_02_STAGE_TASKBOOK_MANAGEMENT.md docs/taskbooks/versions/stage-02/VERSION_STAGE_02_V2_1_STAGE_TASKBOOK_SCHEMA_VALIDATOR_V1.md
  registry_validation:
    - python -m unittest tests.test_stage_taskbook_registry
    - python -m compileall runner/stage_taskbook_registry.py
  report_validation:
    - git diff --check -- docs/taskbooks/versions/stage-02/evidence/VERSION_STAGE_02_V2_2_STAGE_TASKBOOK_REGISTRY_REPORT.md docs/taskbooks/versions/stage-02/evidence/zh-CN/VERSION_STAGE_02_V2_2_STAGE_TASKBOOK_REGISTRY_REPORT.zh-CN.md
    - rg -n "registry_contract_summary|validator_result_consumption_check|registered_stage_hash_check|authority_boundary_check|remaining_risks" docs/taskbooks/versions/stage-02/evidence/VERSION_STAGE_02_V2_2_STAGE_TASKBOOK_REGISTRY_REPORT.md
```

These commands are candidates for later authorized execution only.

---

## 8. Manual Acceptance Criteria

```yaml id="manual-acceptance"
manual_acceptance:
  reviewer_may_accept_if:
    - registry record schema includes exact stage_taskbook_path and hash
    - registry record binds a Stage Taskbook to exact master_taskbook_ref
    - registry record consumes validator_result instead of bypassing validation
    - registry record distinguishes gate-readiness from delivery_state accepted
    - evidence report separates commands_run from commands_not_run
  reviewer_must_not_accept_if:
    - registry can mark a Stage accepted
    - registry can authorize execution
    - registry mutates Stage Taskbook source files
    - registry accepts missing validator_result
```

---

## 9. Stop Conditions

```yaml id="stop-conditions"
stop_conditions:
  must_stop_if:
    - repository_path_is_not_/home/jenn/src/colameta-dev
    - implementation_would_mutate_stage_taskbook_sources
    - implementation_would_mutate_PROJECT_MASTER_TASKBOOK_md
    - implementation_requires_/home/jenn/tools/colameta_changes
    - implementation_requires_fetch_pull_push_or_remote_write
    - registry_would_claim_delivery_state_accepted
    - registry_would_grant_execution_authority
    - required_hashes_do_not_match_declared_parent_hashes
```

---

## 10. Next Version Handoff

```yaml id="next-version-handoff"
next_version_handoff:
  next_version: v2.3 Stage-to-Master Binding V1
  handoff_requires:
    - registry record can store exact master_taskbook_ref
    - registry record stores validator_result
    - registry record preserves authority boundary
  must_not_handoff_as:
    - execution_authorization
    - accepted_delivery_state
```
