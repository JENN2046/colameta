# Version Taskbook: Stage 1 / v1.3 Master Taskbook Required Field Validator V1

```text id="version-stage-01-v1-3-boundary-banner"
VERSION TASKBOOK DRAFT ONLY.
This document defines a candidate Version Execution Taskbook for Stage 1. It
does not authorize execution, executor dispatch, code edits, commit, push,
fetch, pull, route transition, Delivery State Gate transition, or accepted
delivery state.
```

```yaml id="version-taskbook-summary"
version_execution_taskbook:
  document_type: version_execution_taskbook
  schema_version: version_execution_taskbook.discussion_draft.v1
  version_id: stage_01_v1_3_master_taskbook_required_field_validator_v1
  version: v1.3
  name: Master Taskbook Required Field Validator V1
  chinese_name: 主任务书必填字段校验器 V1
  parent_stage_id: stage_01_master_taskbook_anchoring
  parent_stage_name: Master Taskbook Anchoring
  status: discussion_draft
  authority_status: planning_reference_only
  execution_authorization_status: not_authorized
  dispatch_status: not_authorized
  executor_run_authorized: false
  created_from_head: 00aba94
  created_from_head_meaning: historical_creation_baseline_not_execution_or_freeze_snapshot
  created_from_head_subject: "docs: add stage 1 master reader version taskbook"
  origin_main_observed_local_tracking_ref: 018ff63
  local_tracking_ref_sync_status_at_creation: local_ahead_remote_tracking_ref
  local_ahead_origin_main_at_creation: 10
```

`Master Taskbook Required Field Validator V1` = 主任务书必填字段校验器 V1。中文意思是：
在 reader 能只读拿到 Master 内容之后，定义一层最小字段校验，只判断 Master 是否
具备后续治理必须依赖的锚点字段；缺字段必须 fail closed。

---

## 1. Parent Binding

```yaml id="parent-binding"
parent_binding:
  master_taskbook_ref:
    path: PROJECT_MASTER_TASKBOOK.md
    raw_snapshot_sha256: 1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34
    review_status: freeze_candidate_confirmed_for_exact_hash
  stage_taskbook_ref:
    path: docs/taskbooks/stages/STAGE_01_MASTER_TASKBOOK_ANCHORING.md
    raw_snapshot_sha256: f880585ed8d37639d215c9f440b37750defa9201f265b2fb7bd63cfdacf6c326
    stage_id: stage_01_master_taskbook_anchoring
  previous_version_taskbook_refs:
    - path: docs/taskbooks/versions/stage-01/VERSION_STAGE_01_V1_1_MASTER_TASKBOOK_REGISTRY_V1.md
      raw_snapshot_sha256: 503af0ff7cdac71c55b9fa3d47a09d3fc484c851daffb244a52385ac0dd2b896
      version_id: stage_01_v1_1_master_taskbook_registry_v1
    - path: docs/taskbooks/versions/stage-01/VERSION_STAGE_01_V1_2_MASTER_TASKBOOK_READER_V1.md
      raw_snapshot_sha256: 2f95e2a6d695f4426b8e4eadb6bc184d56382c2120db9970a0cee79483425103
      version_id: stage_01_v1_2_master_taskbook_reader_v1
  supports_project_goal: true
```

This Version Taskbook follows v1.1 registry and v1.2 reader. It validates the
read result; it does not replace the reader, mutate the registry, or mutate the
Master Taskbook.

中文解释：v1.3 只做“读到之后最小字段够不够”的判断，不重新打开 registry 或 reader
边界。

---

## 2. Task Goal

```yaml id="task-goal"
task_goal:
  primary_goal: >
    Define a fail-closed validator for the minimum Master Taskbook fields
    required by the Stage 0-6 Thin Governed Loop, using the v1.2 reader result
    as input and preserving the boundary between validation evidence and
    Delivery State Gate authority.
  minimum_readiness_claim: >
    Later Stage 1 hash binding and mutation-gate work can rely on a declared
    minimum Master field set instead of chat memory or runtime status labels.
  gate_question: >
    Does the Master Taskbook expose the minimum goal, MVP, authority, stage, and
    boundary fields required for downstream taskbooks to bind to it?
  explicit_non_goal: >
    This version is not canonical hash generation, not Master mutation control,
    not registry creation, not reader implementation, not review acceptance,
    and not delivery_state promotion.
```

---

## 3. Candidate Execution Envelope

```yaml id="candidate-execution-envelope"
execution_envelope_candidate:
  authorization_status: not_authorized
  parent_hashes:
    master_taskbook_hash: 1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34
    stage_taskbook_hash: f880585ed8d37639d215c9f440b37750defa9201f265b2fb7bd63cfdacf6c326
    previous_v1_1_taskbook_hash: 503af0ff7cdac71c55b9fa3d47a09d3fc484c851daffb244a52385ac0dd2b896
    previous_v1_2_taskbook_hash: 2f95e2a6d695f4426b8e4eadb6bc184d56382c2120db9970a0cee79483425103
  task_goal_ref: task_goal.primary_goal
  definition_of_good:
    - validator consumes reader result as input
    - validator checks required field presence
    - validator distinguishes missing, empty, malformed, and present fields
    - validator fails closed on missing project_final_goal
    - validator reports validation_result without writing delivery_state
    - validator does not mutate PROJECT_MASTER_TASKBOOK.md
    - validator does not rewrite registry records
  allowed_autonomy_after_explicit_authorization:
    - local file inspection
    - narrow validator helper creation
    - focused unit tests for required field and fail-closed behavior
    - narrow evidence report creation under declared output paths
```

`Validation Result` = 校验结果。中文意思是：说明字段是否存在、是否为空、是否格式
明显不合格；它不是 accepted，也不是 Delivery State Gate 事件。

---

## 4. Allowed Files And Mutations

```yaml id="allowed-files-and-mutations"
allowed_files:
  read_only:
    - PROJECT_MASTER_TASKBOOK.md
    - PROJECT_MASTER_TASKBOOK.zh-CN.md
    - .colameta/taskbooks/master_taskbook_registry.json
    - runner/master_taskbook_reader.py
    - docs/taskbooks/versions/stage-01/VERSION_STAGE_01_V1_1_MASTER_TASKBOOK_REGISTRY_V1.md
    - docs/taskbooks/versions/stage-01/VERSION_STAGE_01_V1_2_MASTER_TASKBOOK_READER_V1.md
    - docs/taskbooks/stages/STAGE_01_MASTER_TASKBOOK_ANCHORING.md
    - docs/taskbooks/CHINESE_COMPANION_POLICY.md
    - docs/taskbooks/CHINESE_COMPANION_INDEX.md
    - runner/**
    - tests/**
  writable_after_separate_execution_authorization:
    - runner/master_taskbook_validator.py
    - tests/test_master_taskbook_validator.py
    - docs/taskbooks/versions/stage-01/evidence/VERSION_STAGE_01_V1_3_MASTER_TASKBOOK_REQUIRED_FIELD_VALIDATOR_REPORT.md
    - docs/taskbooks/versions/stage-01/evidence/zh-CN/VERSION_STAGE_01_V1_3_MASTER_TASKBOOK_REQUIRED_FIELD_VALIDATOR_REPORT.zh-CN.md

allowed_mutations:
  - create_or_update_declared_validator_helper_only_after_explicit_execution_authorization
  - create_or_update_declared_validator_tests_only_after_explicit_execution_authorization
  - create_or_update_declared_evidence_report_only_after_explicit_execution_authorization

forbidden_files:
  mutation_targets:
    - /home/jenn/tools/colameta/**
    - PROJECT_MASTER_TASKBOOK.md
    - PROJECT_MASTER_TASKBOOK.zh-CN.md
    - .colameta/taskbooks/master_taskbook_registry.json
    - docs/taskbooks/stages/**
    - docs/taskbooks/versions/stage-00/**
    - .colameta/state.json
    - .colameta/runtime/**
    - .git/**
    - "**/.env"
    - "**/*secret*"
    - "**/*credential*"
```

中文解释：validator 可以被设计成未来的代码，但不能借校验之名修改 Master 或 registry。

---

## 5. Required Field Minimum Contract

```yaml id="required-field-minimum-contract"
required_field_minimum_contract:
  required_fields:
    - project_final_goal
    - mvp_stage_scope
    - master_stage_taskbook_architecture
    - authority_boundaries
    - delivery_state_gate_boundary
    - review_decision_mapping_boundary
    - evidence_package_minimum
    - stage_0_6_thin_governed_loop
    - forbidden_claims_or_boundary_law
    - versioning_policy
  field_result_values:
    - present
    - missing
    - empty
    - malformed
    - known_unknown
  fail_closed_fields:
    - project_final_goal
    - authority_boundaries
    - delivery_state_gate_boundary
```

`Required Field Minimum Contract` = 必填字段最小合约。中文意思是：先规定最少要能
找到哪些字段，不把 validator 做成完整语义审计系统。

---

## 6. Evidence Package Contract

```yaml id="evidence-package-contract"
evidence_package_contract:
  evidence_package_id: stage_01_v1_3_master_taskbook_required_field_validator_evidence
  required_artifacts:
    - validator_contract_summary
    - reader_result_input_or_known_unknown
    - required_field_check_table
    - fail_closed_result
    - validation_result
    - chinese_validator_report_companion
  not_validated: required_even_when_empty
  remaining_risks: required_even_when_empty
  must_not_include_as_authority:
    - chat memory
    - stale executor session state
    - runtime PASSED or COMPLETED labels
    - delivery_state accepted
```

---

## 7. Candidate Acceptance Commands

These commands are candidates for a later authorized execution. They are not run
by writing this taskbook.

```yaml id="candidate-acceptance-commands"
acceptance_commands:
  preflight_read_only:
    - git status --short --branch
    - git rev-parse HEAD
    - sha256sum PROJECT_MASTER_TASKBOOK.md docs/taskbooks/versions/stage-01/VERSION_STAGE_01_V1_2_MASTER_TASKBOOK_READER_V1.md
  validator_validation:
    - python -m unittest tests.test_master_taskbook_validator
    - python -m compileall runner/master_taskbook_validator.py
  report_validation:
    - git diff --check -- docs/taskbooks/versions/stage-01/evidence/VERSION_STAGE_01_V1_3_MASTER_TASKBOOK_REQUIRED_FIELD_VALIDATOR_REPORT.md docs/taskbooks/versions/stage-01/evidence/zh-CN/VERSION_STAGE_01_V1_3_MASTER_TASKBOOK_REQUIRED_FIELD_VALIDATOR_REPORT.zh-CN.md
    - rg -n "required_field_check_table|project_final_goal|authority_boundaries|delivery_state_gate_boundary|validation_result|remaining_risks" docs/taskbooks/versions/stage-01/evidence/VERSION_STAGE_01_V1_3_MASTER_TASKBOOK_REQUIRED_FIELD_VALIDATOR_REPORT.md
    - rg -n "source_document|source_sha256|必填字段|校验结果|remaining_risks" docs/taskbooks/versions/stage-01/evidence/zh-CN/VERSION_STAGE_01_V1_3_MASTER_TASKBOOK_REQUIRED_FIELD_VALIDATOR_REPORT.zh-CN.md
```

If reader output is unavailable, the validator report must record
`reader_result_missing` or `known_unknown`; it must not reimplement the reader
inside this version.

---

## 8. Manual Acceptance Criteria

```yaml id="manual-acceptance"
manual_acceptance:
  reviewer_may_accept_if:
    - validator consumes reader result as input
    - validator checks every required field in the minimum contract
    - validator fails closed on missing project_final_goal
    - validator reports missing, empty, malformed, present, or known_unknown
    - validator does not mutate PROJECT_MASTER_TASKBOOK.md
    - validator does not write delivery_state
    - evidence report lists commands_run and commands_not_run separately
    - Chinese report companion explains technical terms in Chinese
  reviewer_must_not_accept_if:
    - validator modifies Master content
    - validator treats runtime labels as validation authority
    - validator claims accepted delivery_state
    - validator silently ignores missing fail_closed fields
    - validator rewrites registry or reader output
```

---

## 9. Stop Conditions

```yaml id="stop-conditions"
stop_conditions:
  must_stop_if:
    - repository_path_is_not_/home/jenn/src/colameta-dev
    - implementation_would_mutate_PROJECT_MASTER_TASKBOOK_md
    - implementation_would_create_or_modify_registry_record
    - implementation_would_reimplement_reader_instead_of_consuming_reader_result
    - implementation_requires_/home/jenn/tools/colameta_changes
    - implementation_requires_fetch_pull_push_or_remote_write
    - validator_result_would_claim_delivery_state_accepted
    - tests_require_executor_run_or_service_restart
```

---

## 10. Handoff

```yaml id="handoff"
handoff:
  next_version_candidate_after_success: stage_01_v1_4_master_hash_binding_v1
  handoff_contract:
    - validator_result_has_required_field_check_table
    - validator_result_has_fail_closed_result
    - validator_result_does_not_write_delivery_state
    - hash_binding_receives_validation_result_as_evidence_not_authority
  must_not_skip_to:
    - mutation hard gate
    - external taskbook import
    - executor dispatch
    - delivery_state acceptance
```

中文解释：v1.4 可以使用 validator result 作为证据输入，但不能把 validator result
当成 accepted。

---

## 11. Non-Authorization Boundary

```yaml id="non-authorization-boundary"
non_authorization_boundary:
  this_taskbook_does_not_authorize:
    - implementation
    - code_changes
    - registry_mutation
    - reader_mutation
    - master_taskbook_mutation
    - commit
    - push
    - fetch
    - pull
    - executor_run
    - service_restart
    - route_transition
    - remote_write
    - release
    - deploy
    - delivery_state_transition
```

中文解释：这份文件只是 Version Taskbook 草稿。真正要实现 Master validator，
还需要 Commander 以后按精确 hash 和范围单独授权。
