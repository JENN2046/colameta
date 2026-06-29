# Version Taskbook: Stage 2 / v2.4 Stage Taskbook Gate-Readiness Contract V1

```text id="version-stage-02-v2-4-boundary-banner"
VERSION TASKBOOK DRAFT ONLY.
This document defines a candidate Version Execution Taskbook for Stage 2. It
does not authorize execution, executor dispatch, code edits, commit, push,
fetch, pull, route transition, Master mutation, Stage Taskbook mutation,
registry mutation, review acceptance, Delivery State Gate transition, or
accepted delivery state.
```

```yaml id="version-taskbook-summary"
version_execution_taskbook:
  document_type: version_execution_taskbook
  schema_version: version_execution_taskbook.discussion_draft.v1
  version_id: stage_02_v2_4_stage_taskbook_gate_readiness_contract_v1
  version: v2.4
  name: Stage Taskbook Gate-Readiness Contract V1
  chinese_name: 阶段任务书状态门就绪契约 V1
  parent_stage_id: stage_02_stage_taskbook_management
  parent_stage_name: Stage Taskbook Management
  status: discussion_draft
  authority_status: planning_reference_only
  execution_authorization_status: not_authorized
  dispatch_status: not_authorized
  executor_run_authorized: false
  created_from_head: c7b0276
  created_from_head_full: c7b027610600843550b65dc6770899d2a8d4cca6
  created_from_head_meaning: historical_creation_baseline_not_execution_or_freeze_snapshot
  created_from_head_subject: "docs: add stage 2 master binding version taskbook"
  origin_main_observed_local_tracking_ref: 018ff63
  local_tracking_ref_sync_status_at_creation: local_ahead_remote_tracking_ref
  local_ahead_origin_main_at_creation: 19
```

`Stage Taskbook Gate-Readiness Contract V1` = 阶段任务书状态门就绪契约 V1。中文意思是：
定义一个 Stage Taskbook 什么时候可以被后续 Version 引用为 `stage_taskbook_ref`。
这个状态只表示“具备进入后续审查/引用的最低条件”，不表示 accepted。

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
    path: docs/taskbooks/versions/stage-02/VERSION_STAGE_02_V2_3_STAGE_TO_MASTER_BINDING_V1.md
    raw_snapshot_sha256: 0699376b9162c0e4ef276996482820c26327e60f5d8371a7193860dbfce6594e
    version_id: stage_02_v2_3_stage_to_master_binding_v1
  stage_1_version_set_confirmation_ref:
    path: docs/taskbooks/versions/stage-01/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_01_VERSIONS.md
    raw_snapshot_sha256: c4ef865c84ab634a7b3626cdc6924a4e51420a1d6d94bb274aeb9f13d354fce5
    review_status: hash_specific_freeze_candidate_confirmation_recorded
  supports_project_goal: true
```

This Version Taskbook is subordinate to Stage 2 and must consume the v2.1-v2.3
contracts. It must not treat gate-ready as accepted delivery state.

中文解释：v2.4 是 Stage 2 的收束门。它让后续 Version 能引用合格的 Stage Taskbook，
但不能把“合格可引用”说成“交付已通过”。

---

## 2. Task Goal

```yaml id="task-goal"
task_goal:
  primary_goal: >
    Define the minimum gate-readiness contract for a Stage Taskbook reference:
    schema validation passed, registry record exists, exact Master binding
    passed, evidence package minimum is present, non-goals are explicit, and the
    result remains distinct from accepted delivery state.
  minimum_readiness_claim: >
    A Version Taskbook can reference a Stage Taskbook only after Stage 2 can
    prove the Stage Taskbook is registered, validated, Master-bound, and
    gate-ready.
  gate_question: >
    Can later Version Taskbooks reject unregistered, unvalidated, unbound, or
    authority-confused Stage Taskbook references?
  explicit_non_goal: >
    This version is not review acceptance, not Delivery State Gate transition,
    not executor dispatch, not workflow automation, and not automatic Stage
    generation.
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
    previous_version_hash: 0699376b9162c0e4ef276996482820c26327e60f5d8371a7193860dbfce6594e
    stage_1_version_set_confirmation_hash: c4ef865c84ab634a7b3626cdc6924a4e51420a1d6d94bb274aeb9f13d354fce5
  task_goal_ref: task_goal.primary_goal
  definition_of_good:
    - gate-readiness contract requires schema validation pass
    - gate-readiness contract requires registry record
    - gate-readiness contract requires exact Stage-to-Master binding pass
    - gate-readiness contract requires minimum evidence package
    - gate-readiness contract rejects accepted delivery state wording
    - later Version Taskbooks can reference only registered gate-ready stage_taskbook_ref values
  allowed_autonomy_after_explicit_authorization:
    - local file inspection
    - narrow gate-readiness helper creation or update under declared path
    - focused tests for valid and invalid stage_taskbook_ref values
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
    - docs/taskbooks/versions/stage-02/VERSION_STAGE_02_V2_3_STAGE_TO_MASTER_BINDING_V1.md
    - docs/taskbooks/stages/**
    - docs/taskbooks/versions/stage-00/**
    - docs/taskbooks/versions/stage-01/**
    - runner/**
    - tests/**
  writable_after_separate_execution_authorization:
    - runner/stage_taskbook_gate_readiness.py
    - tests/test_stage_taskbook_gate_readiness.py
    - docs/taskbooks/versions/stage-02/evidence/VERSION_STAGE_02_V2_4_STAGE_TASKBOOK_GATE_READINESS_REPORT.md
    - docs/taskbooks/versions/stage-02/evidence/zh-CN/VERSION_STAGE_02_V2_4_STAGE_TASKBOOK_GATE_READINESS_REPORT.zh-CN.md
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

中文解释：v2.4 可以定义未来 gate-readiness helper 和测试的候选路径，但不能现在修改
Stage Taskbook、registry、Master 或任何运行态状态。

---

## 5. Gate-Readiness Minimum Contract

```yaml id="gate-readiness-minimum-contract"
gate_readiness_minimum_contract:
  required_inputs:
    - stage_taskbook_ref
    - stage_taskbook_raw_snapshot_sha256
    - validator_result
    - registry_record_ref
    - master_binding_result
    - minimum_evidence_package
    - non_goals_summary
  required_result_fields:
    - readiness_result
    - stage_id
    - stage_taskbook_ref
    - master_taskbook_ref
    - evidence_package_ref
    - blocking_reasons
    - authority_boundary
  valid_readiness_results:
    - gate_ready
    - not_gate_ready
    - blocked_needs_review
  forbidden_result_claims:
    - accepted_delivery_state
    - execution_authorized
    - executor_dispatch_authorized
    - route_transition_authorized
    - registry_mutation_authorized
```

`gate_ready` = 状态门就绪。中文意思是：资料够完整，可以被后续 Version 引用或拿去
审查；它不是 accepted，也不是执行授权。

---

## 6. Stage Taskbook Ref Consumption Rule

```yaml id="stage-taskbook-ref-consumption-rule"
stage_taskbook_ref_consumption_rule:
  later_version_taskbooks_may_reference_stage_taskbook_ref_only_when:
    - readiness_result_is_gate_ready
    - exact_stage_taskbook_hash_matches_registry
    - master_taskbook_ref_matches_binding_result
    - evidence_package_ref_exists_or_known_unknown_is_documented
    - authority_boundary_is_explicit
  later_version_taskbooks_must_reject_when:
    - stage_taskbook_ref_is_unregistered
    - validator_result_failed_or_missing
    - master_binding_failed_or_missing
    - evidence_package_missing_without_known_unknown
    - readiness_result_claims_accepted_or_execution_authority
```

---

## 7. Evidence Package Contract

```yaml id="evidence-package-contract"
evidence_package_contract:
  evidence_package_id: stage_02_v2_4_stage_taskbook_gate_readiness_evidence
  required_artifacts:
    - gate_readiness_contract_summary
    - stage_taskbook_ref_consumption_rule
    - positive_case_result
    - negative_case_results
    - authority_boundary_check
    - commands_run
    - commands_not_run
    - known_gaps
    - remaining_risks
    - chinese_report_companion
  must_not_include_as_authority:
    - reviewer acceptance
    - delivery_state
    - runtime labels
    - executor status
```

---

## 8. Candidate Acceptance Commands

```yaml id="candidate-acceptance-commands"
acceptance_commands:
  preflight_read_only:
    - git status --short --branch
    - git rev-parse HEAD
    - sha256sum docs/taskbooks/stages/STAGE_02_STAGE_TASKBOOK_MANAGEMENT.md docs/taskbooks/versions/stage-02/VERSION_STAGE_02_V2_3_STAGE_TO_MASTER_BINDING_V1.md
  gate_readiness_validation:
    - python -m unittest tests.test_stage_taskbook_gate_readiness
    - python -m compileall runner/stage_taskbook_gate_readiness.py
  report_validation:
    - git diff --check -- docs/taskbooks/versions/stage-02/evidence/VERSION_STAGE_02_V2_4_STAGE_TASKBOOK_GATE_READINESS_REPORT.md docs/taskbooks/versions/stage-02/evidence/zh-CN/VERSION_STAGE_02_V2_4_STAGE_TASKBOOK_GATE_READINESS_REPORT.zh-CN.md
    - rg -n "gate_readiness_contract_summary|stage_taskbook_ref_consumption_rule|positive_case_result|negative_case_results|remaining_risks" docs/taskbooks/versions/stage-02/evidence/VERSION_STAGE_02_V2_4_STAGE_TASKBOOK_GATE_READINESS_REPORT.md
```

These commands are candidates for later authorized execution only.

---

## 9. Manual Acceptance Criteria

```yaml id="manual-acceptance"
manual_acceptance:
  reviewer_may_accept_if:
    - gate-readiness requires validator_result pass
    - gate-readiness requires registry record
    - gate-readiness requires exact Master binding pass
    - later Version Taskbooks must reject unregistered or unvalidated stage_taskbook_ref values
    - gate_ready is explicitly not accepted delivery state
    - evidence report separates commands_run from commands_not_run
  reviewer_must_not_accept_if:
    - gate_ready authorizes execution
    - gate_ready maps to accepted delivery state
    - unregistered stage_taskbook_ref can be consumed
    - failed validator_result can still be gate_ready
```

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
    - gate_ready_would_claim_delivery_state_accepted
    - gate_ready_would_grant_execution_authority
    - required_hashes_do_not_match_declared_parent_hashes
```

---

## 11. Stage 2 Closeout Readiness

```yaml id="stage-2-closeout-readiness"
stage_2_closeout_readiness:
  version_set:
    - v2.1 Stage Taskbook Schema And Validator V1
    - v2.2 Stage Taskbook Registry V1
    - v2.3 Stage-to-Master Binding V1
    - v2.4 Stage Taskbook Gate-Readiness Contract V1
  package_review_ready_when:
    - all version taskbooks exist
    - all Chinese companions exist
    - all source hashes are current
    - previous-version hashes match current sources
    - no version claims execution authorization or delivery_state accepted
```

中文解释：v2.4 是 Stage 2 这一组 Version 草稿的最后一刀。之后可以做 Stage 2
Version set 包级审查和 freeze packet 草稿，但仍然不能直接执行实现。
