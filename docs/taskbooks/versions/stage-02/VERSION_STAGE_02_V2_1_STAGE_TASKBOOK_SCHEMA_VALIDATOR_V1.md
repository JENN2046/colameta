# Version Taskbook: Stage 2 / v2.1 Stage Taskbook Schema And Validator V1

```text id="version-stage-02-v2-1-boundary-banner"
VERSION TASKBOOK DRAFT ONLY.
This document defines a candidate Version Execution Taskbook for Stage 2. It
does not authorize execution, executor dispatch, code edits, commit, push,
fetch, pull, route transition, Master mutation, Stage Taskbook mutation,
Delivery State Gate transition, or accepted delivery state.
```

```yaml id="version-taskbook-summary"
version_execution_taskbook:
  document_type: version_execution_taskbook
  schema_version: version_execution_taskbook.discussion_draft.v1
  version_id: stage_02_v2_1_stage_taskbook_schema_validator_v1
  version: v2.1
  name: Stage Taskbook Schema And Validator V1
  chinese_name: 阶段任务书模式与校验器 V1
  parent_stage_id: stage_02_stage_taskbook_management
  parent_stage_name: Stage Taskbook Management
  status: discussion_draft
  authority_status: planning_reference_only
  execution_authorization_status: not_authorized
  dispatch_status: not_authorized
  executor_run_authorized: false
  created_from_head: 5662499
  created_from_head_full: 566249949b05bf65a1cdc51495406bd05f4d313a
  created_from_head_meaning: historical_creation_baseline_not_execution_or_freeze_snapshot
  created_from_head_subject: "docs: record stage 1 version freeze confirmation"
  origin_main_observed_local_tracking_ref: 018ff63
  local_tracking_ref_sync_status_at_creation: local_ahead_remote_tracking_ref
  local_ahead_origin_main_at_creation: 16
```

`Version Execution Taskbook` = 版本执行任务书。中文意思是：它把某个 Stage
下面的一次小交付切成可验证、可审查、可授权的执行边界。

`Stage Taskbook Schema And Validator V1` = 阶段任务书模式与校验器 V1。中文意思是：
先定义 Stage Taskbook 必须长什么样，并定义一个最小 fail-closed 校验器，让 Stage
Taskbook 不能缺少 Master 绑定、阶段目标、非目标、gate-readiness criteria 和证据包。

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
  stage_0_6_freeze_packet_ref:
    path: docs/taskbooks/stages/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_0_6.md
    raw_snapshot_sha256: 94ea9101a120e0935e834533ed0315a6fe3e77e3d4ecb48db37fa6851e75b5ce
    review_status: hash_specific_freeze_candidate_confirmation_recorded
  stage_0_version_set_confirmation_ref:
    path: docs/taskbooks/versions/stage-00/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_00_VERSIONS.md
    raw_snapshot_sha256: b3d838f5229a94e88dbaa405a0f65ae76f5208660ab000c1eecd777090897acc
    review_status: hash_specific_freeze_candidate_confirmation_recorded
  stage_1_version_set_confirmation_ref:
    path: docs/taskbooks/versions/stage-01/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_01_VERSIONS.md
    raw_snapshot_sha256: c4ef865c84ab634a7b3626cdc6924a4e51420a1d6d94bb274aeb9f13d354fce5
    review_status: hash_specific_freeze_candidate_confirmation_recorded
  supports_project_goal: true
```

This Version Taskbook is subordinate to Stage 2. If it conflicts with the
Master or Stage 2 Taskbook, the conflict must be treated as a taskbook defect,
not as authority to reinterpret the parent documents.

中文解释：这份 Version 只能服务 Stage 2 的“阶段任务书管理”，不能反过来改写 Master、
Stage 2，或已经确认的 Stage 0/1 Version set。

---

## 2. Task Goal

```yaml id="task-goal"
task_goal:
  primary_goal: >
    Define the first Stage 2 implementation slice for a minimal Stage Taskbook
    schema and validator that can check required fields, Master binding,
    project-goal support, non-goals, gate-readiness criteria, and minimum
    evidence package requirements.
  minimum_readiness_claim: >
    A Stage Taskbook can be checked as a bounded planning artifact before it is
    registered or referenced by Version Taskbooks.
  gate_question: >
    Can the project reject a Stage Taskbook that lacks required fields,
    master_taskbook_ref, non-goals, gate-readiness criteria, or evidence-package
    expectations?
  explicit_non_goal: >
    This version is not a stage registry, not a migration engine, not automatic
    Stage generation, not executor dispatch, not review acceptance, and not a
    Delivery State Gate transition.
```

中文解释：v2.1 先做“能不能看懂并校验 Stage Taskbook”。它不负责登记、不负责迁移、
不负责执行，更不能把 Stage Taskbook 的文字当成 accepted。

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
    stage_0_6_freeze_packet_hash: 94ea9101a120e0935e834533ed0315a6fe3e77e3d4ecb48db37fa6851e75b5ce
    stage_0_version_set_confirmation_hash: b3d838f5229a94e88dbaa405a0f65ae76f5208660ab000c1eecd777090897acc
    stage_1_version_set_confirmation_hash: c4ef865c84ab634a7b3626cdc6924a4e51420a1d6d94bb274aeb9f13d354fce5
  task_goal_ref: task_goal.primary_goal
  definition_of_good:
    - stage taskbook schema required fields are explicit and machine-checkable
    - validator fails closed when master_taskbook_ref is missing or malformed
    - validator fails closed when stage purpose, non-goals, gate-readiness criteria, or minimum evidence package is missing
    - validator distinguishes stage readiness claims from accepted delivery state
    - implementation does not mutate Stage Taskbook source documents
    - implementation does not claim executor or delivery-state authority
  allowed_autonomy_after_explicit_authorization:
    - local file inspection
    - narrow schema-file creation or update under declared path
    - narrow validator helper creation or update under declared path
    - focused unit tests for valid and invalid Stage Taskbook examples
    - narrow evidence report and Chinese report companion update
```

`Execution Envelope` = 执行信封。中文意思是：真正执行前必须有一封“边界信”，
写清楚能读什么、能写什么、不能做什么、怎么验证。这里还不是授权。

---

## 4. Allowed Files And Mutations

```yaml id="allowed-files-and-mutations"
allowed_files:
  read_only:
    - PROJECT_MASTER_TASKBOOK.md
    - PROJECT_MASTER_TASKBOOK.zh-CN.md
    - docs/taskbooks/stages/README.md
    - docs/taskbooks/stages/STAGE_02_STAGE_TASKBOOK_MANAGEMENT.md
    - docs/taskbooks/stages/zh-CN/STAGE_02_STAGE_TASKBOOK_MANAGEMENT.zh-CN.md
    - docs/taskbooks/stages/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_0_6.md
    - docs/taskbooks/stages/zh-CN/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_0_6.zh-CN.md
    - docs/taskbooks/versions/stage-00/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_00_VERSIONS.md
    - docs/taskbooks/versions/stage-00/zh-CN/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_00_VERSIONS.zh-CN.md
    - docs/taskbooks/versions/stage-01/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_01_VERSIONS.md
    - docs/taskbooks/versions/stage-01/zh-CN/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_01_VERSIONS.zh-CN.md
    - docs/taskbooks/CHINESE_COMPANION_POLICY.md
    - docs/taskbooks/CHINESE_COMPANION_INDEX.md
    - runner/**
    - tests/**
  writable_after_separate_execution_authorization:
    - .colameta/taskbooks/stage_taskbook_schema.json
    - runner/stage_taskbook_validator.py
    - tests/test_stage_taskbook_validator.py
    - docs/taskbooks/versions/stage-02/evidence/VERSION_STAGE_02_V2_1_STAGE_TASKBOOK_SCHEMA_VALIDATOR_REPORT.md
    - docs/taskbooks/versions/stage-02/evidence/zh-CN/VERSION_STAGE_02_V2_1_STAGE_TASKBOOK_SCHEMA_VALIDATOR_REPORT.zh-CN.md

allowed_mutations:
  - create_or_update_declared_stage_taskbook_schema_only_after_explicit_execution_authorization
  - create_or_update_declared_validator_helper_only_after_explicit_execution_authorization
  - create_or_update_declared_validator_tests_only_after_explicit_execution_authorization
  - create_or_update_declared_evidence_report_only_after_explicit_execution_authorization

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

The candidate schema and validator paths are not authorized by this document.
They become writable only under a later exact execution authorization.

中文解释：这份任务书现在只是草稿。它可以描述未来可能写哪里，但不能现在就改
schema、runner、tests、Stage Taskbook 或 Master。

---

## 5. Stage Taskbook Schema Minimum Contract

```yaml id="stage-taskbook-schema-minimum-contract"
stage_taskbook_schema_minimum_contract:
  required_fields:
    - stage_id
    - stage_name
    - chinese_name
    - status
    - authority_status
    - master_taskbook_ref
    - supports_project_goal
    - stage_purpose
    - entry_criteria
    - exit_criteria
    - deliverables
    - gate_readiness_criteria
    - minimum_evidence_package
    - non_goals
  readiness_contract_fields:
    - minimum_readiness_claim
    - required_evidence
    - gate_question
    - explicit_non_goal
  boundary_fields:
    - state_authority_boundary
    - execution_authorization_boundary
    - mutation_boundary
  bootstrap_registration_mode:
    allowed: true
    scope: initial_stage_0_6_discussion_drafts_only
    requires_separate_authorization: true
    one_time_only: true
    hash_bound: true
    receipt_required: true
```

`Schema Minimum Contract` = 模式最小合约。中文意思是：先把 Stage Taskbook
必须具备的字段钉住，后面的 registry 和引用检查才能有东西可验。

---

## 6. Validator Behavior Contract

```yaml id="validator-behavior-contract"
validator_behavior_contract:
  accepted_input:
    - stage_taskbook_markdown_path
    - parsed_yaml_blocks_from_stage_taskbook
    - expected_master_taskbook_hash
  required_outputs:
    - validation_result
    - missing_fields
    - malformed_fields
    - warning_fields
    - stage_id
    - stage_taskbook_hash
    - master_taskbook_ref
    - supports_project_goal
  fail_closed_when:
    - missing_master_taskbook_ref
    - master_hash_mismatch
    - missing_stage_purpose
    - missing_non_goals
    - missing_gate_readiness_criteria
    - missing_minimum_evidence_package
    - stage_claims_delivery_state_accepted
    - stage_claims_execution_authority
```

`fail closed` = 失败时关闭。中文意思是：校验不清楚时按“不通过”处理，不能默认放行。

---

## 7. Evidence Package Contract

```yaml id="evidence-package-contract"
evidence_package_contract:
  evidence_package_id: stage_02_v2_1_stage_taskbook_schema_validator_evidence
  required_artifacts:
    - schema_contract_summary
    - validator_behavior_summary
    - required_field_check_table
    - master_binding_check
    - fail_closed_negative_case_results
    - commands_run
    - commands_not_run
    - known_gaps
    - remaining_risks
    - chinese_report_companion
  must_not_include_as_authority:
    - chat memory
    - runtime PASSED or COMPLETED labels
    - reviewer acceptance
    - delivery_state
    - live remote state unless explicitly probed under authorization
```

`Evidence Package` = 证据包。中文意思是：把“做了什么、看到了什么、哪些命令跑了、
哪些没跑、还有什么风险”收起来给审查者看。证据包不是批准，不会改变
delivery_state。

---

## 8. Candidate Acceptance Commands

These commands are candidates for a later authorized execution. They are not run
by writing this taskbook.

```yaml id="candidate-acceptance-commands"
acceptance_commands:
  preflight_read_only:
    - git status --short --branch
    - git rev-parse HEAD
    - git rev-parse origin/main || true
    - git rev-list --left-right --count origin/main...HEAD || true
    - sha256sum PROJECT_MASTER_TASKBOOK.md docs/taskbooks/stages/STAGE_02_STAGE_TASKBOOK_MANAGEMENT.md
  validator_validation:
    - python -m unittest tests.test_stage_taskbook_validator
    - python -m compileall runner/stage_taskbook_validator.py
  report_validation:
    - git diff --check -- docs/taskbooks/versions/stage-02/evidence/VERSION_STAGE_02_V2_1_STAGE_TASKBOOK_SCHEMA_VALIDATOR_REPORT.md docs/taskbooks/versions/stage-02/evidence/zh-CN/VERSION_STAGE_02_V2_1_STAGE_TASKBOOK_SCHEMA_VALIDATOR_REPORT.zh-CN.md
    - rg -n "schema_contract_summary|validator_behavior_summary|required_field_check_table|fail_closed_negative_case_results|remaining_risks" docs/taskbooks/versions/stage-02/evidence/VERSION_STAGE_02_V2_1_STAGE_TASKBOOK_SCHEMA_VALIDATOR_REPORT.md
    - rg -n "source_document|source_sha256|模式|校验器|失败时关闭|remaining_risks" docs/taskbooks/versions/stage-02/evidence/zh-CN/VERSION_STAGE_02_V2_1_STAGE_TASKBOOK_SCHEMA_VALIDATOR_REPORT.zh-CN.md
```

If the local `origin/main` tracking ref is unavailable, the report must record
`known_unknown`; it must not auto-fetch or contact the remote. If validator tests
are not authorized, they must be listed under `commands_not_run`.

中文解释：这些是未来执行时的候选验收命令。现在写在任务书里，不代表已经执行，
也不代表已经授权执行。

---

## 9. Manual Acceptance Criteria

```yaml id="manual-acceptance"
manual_acceptance:
  reviewer_may_accept_if:
    - schema required fields match the Stage 2 Required Field Matrix
    - validator rejects missing master_taskbook_ref
    - validator rejects missing non_goals and gate_readiness_criteria
    - validator rejects any Stage Taskbook claim that implies accepted delivery state
    - evidence report lists commands_run and commands_not_run separately
    - Chinese report companion explains technical terms in Chinese
  reviewer_must_not_accept_if:
    - validator treats missing fields as warnings only
    - schema allows Stage Taskbook to claim state authority
    - implementation mutates Stage Taskbook source files
    - evidence is based only on chat memory or stale runtime labels
    - tests or report validation fail without documented known_unknowns
```

`Manual Acceptance Criteria` = 人工验收条件。中文意思是：审查者可以根据这些条件
判断结果是否够格，但审查记录本身仍不等于 Delivery State Gate 的 accepted。

---

## 10. Stop Conditions

```yaml id="stop-conditions"
stop_conditions:
  must_stop_if:
    - repository_path_is_not_/home/jenn/src/colameta-dev
    - implementation_would_mutate_PROJECT_MASTER_TASKBOOK_md
    - implementation_would_mutate_stage_taskbook_sources
    - implementation_requires_/home/jenn/tools/colameta_changes
    - implementation_requires_fetch_pull_push_or_remote_write
    - validator_would_claim_delivery_state_accepted
    - validator_would_grant_execution_authority
    - required_hashes_do_not_match_declared_parent_hashes
    - tests_require_executor_run_or_service_restart
```

中文解释：这些情况一出现就必须停，不能把“校验 Stage Taskbook”悄悄扩成“改 Stage”
或“让 Stage 直接生效”。

---

## 11. Next Version Handoff

```yaml id="next-version-handoff"
next_version_handoff:
  next_version: v2.2 Stage Taskbook Registry V1
  handoff_requires:
    - schema minimum contract is explicit
    - validator behavior contract is explicit
    - registry work must consume validator result, not bypass it
  must_not_handoff_as:
    - execution_authorization
    - registry_mutation_authorization
    - delivery_state_acceptance
```

中文解释：v2.1 给 v2.2 的交接物是“schema 和 validator 合约”，不是 registry
实现授权，也不是状态推进。
