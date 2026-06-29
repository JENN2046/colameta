# Version Taskbook: Stage 1 / v1.5 Master Mutation Hard Gate V1

```text id="version-stage-01-v1-5-boundary-banner"
VERSION TASKBOOK DRAFT ONLY.
This document defines a candidate Version Execution Taskbook for Stage 1. It
does not authorize execution, executor dispatch, code edits, commit, push,
fetch, pull, route transition, Delivery State Gate transition, Master Taskbook
mutation, or accepted delivery state.
```

```yaml id="version-taskbook-summary"
version_execution_taskbook:
  document_type: version_execution_taskbook
  schema_version: version_execution_taskbook.discussion_draft.v1
  version_id: stage_01_v1_5_master_mutation_hard_gate_v1
  version: v1.5
  name: Master Mutation Hard Gate V1
  chinese_name: 主任务书变更硬门 V1
  parent_stage_id: stage_01_master_taskbook_anchoring
  parent_stage_name: Master Taskbook Anchoring
  status: discussion_draft
  authority_status: planning_reference_only
  execution_authorization_status: not_authorized
  dispatch_status: not_authorized
  executor_run_authorized: false
  created_from_head: ebf7ce6
  created_from_head_meaning: historical_creation_baseline_not_execution_or_freeze_snapshot
  created_from_head_subject: "docs: add stage 1 master hash binding version taskbook"
  origin_main_observed_local_tracking_ref: 018ff63
  local_tracking_ref_sync_status_at_creation: local_ahead_remote_tracking_ref
  local_ahead_origin_main_at_creation: 12
```

`Master Mutation Hard Gate V1` = 主任务书变更硬门 V1。中文意思是：定义普通
Version 任务、executor、review packet、runtime 状态都不能静默修改 Master；任何
Master governance 内容变更都必须进入 Commander hard gate。

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
    - path: docs/taskbooks/versions/stage-01/VERSION_STAGE_01_V1_3_MASTER_TASKBOOK_REQUIRED_FIELD_VALIDATOR_V1.md
      raw_snapshot_sha256: 450d35760130672b2d3e145e821a9b9bc58ba3e1369d6021f7d01e991a6f9d07
      version_id: stage_01_v1_3_master_taskbook_required_field_validator_v1
    - path: docs/taskbooks/versions/stage-01/VERSION_STAGE_01_V1_4_MASTER_HASH_BINDING_V1.md
      raw_snapshot_sha256: c8e7f2d41ad1094495f687f4e7b10b012f415823174d1fe988b2d05f83bcb0ff
      version_id: stage_01_v1_4_master_hash_binding_v1
  supports_project_goal: true
```

中文解释：v1.5 是 Stage 1 的收束门。它使用 v1.1-v1.4 的 registry、reader、
validator、hash binding 作为证据输入，但不能替 Commander 批准 Master 变更。

---

## 2. Task Goal

```yaml id="task-goal"
task_goal:
  primary_goal: >
    Define a hard gate policy and check surface for Master Taskbook mutation so
    ordinary Version tasks, executor runs, runtime state, and review packets
    cannot silently modify PROJECT_MASTER_TASKBOOK.md or reinterpret Master
    freeze_candidate status as active authority.
  minimum_readiness_claim: >
    Stage 2 can safely bind to master_taskbook_ref knowing that Master
    governance content changes require an explicit Commander hard gate.
  gate_question: >
    Are attempted Master mutations detected, classified, and blocked unless a
    Commander hard-gate authorization is present?
  explicit_non_goal: >
    This version is not a Master edit flow, not a policy acceptance flow, not a
    route transition, not a delivery_state transition, and not an executor
    authorization mechanism.
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
    previous_v1_3_taskbook_hash: 450d35760130672b2d3e145e821a9b9bc58ba3e1369d6021f7d01e991a6f9d07
    previous_v1_4_taskbook_hash: c8e7f2d41ad1094495f687f4e7b10b012f415823174d1fe988b2d05f83bcb0ff
  task_goal_ref: task_goal.primary_goal
  definition_of_good:
    - mutation gate detects Master path changes in candidate change sets
    - mutation gate blocks ordinary tasks from mutating Master governance content
    - mutation gate requires explicit Commander hard-gate authorization for Master mutation
    - mutation gate distinguishes read-only Master access from mutation attempts
    - mutation gate records blocked mutation attempts as evidence not delivery_state
    - mutation gate does not itself edit PROJECT_MASTER_TASKBOOK.md
  allowed_autonomy_after_explicit_authorization:
    - local file inspection
    - narrow mutation-gate helper creation
    - focused unit tests for allowed read-only access and blocked mutation attempts
    - narrow evidence report creation under declared output paths
```

`Commander hard gate` = 指挥官硬门。中文意思是：只有 Commander 通过精确范围、
精确 hash、明确 token 单独授权，Master governance 内容才可以被改。

---

## 4. Allowed Files And Mutations

```yaml id="allowed-files-and-mutations"
allowed_files:
  read_only:
    - PROJECT_MASTER_TASKBOOK.md
    - PROJECT_MASTER_TASKBOOK.zh-CN.md
    - .colameta/taskbooks/master_taskbook_registry.json
    - runner/master_taskbook_reader.py
    - runner/master_taskbook_validator.py
    - runner/master_taskbook_hash_binding.py
    - docs/taskbooks/versions/stage-01/VERSION_STAGE_01_V1_1_MASTER_TASKBOOK_REGISTRY_V1.md
    - docs/taskbooks/versions/stage-01/VERSION_STAGE_01_V1_2_MASTER_TASKBOOK_READER_V1.md
    - docs/taskbooks/versions/stage-01/VERSION_STAGE_01_V1_3_MASTER_TASKBOOK_REQUIRED_FIELD_VALIDATOR_V1.md
    - docs/taskbooks/versions/stage-01/VERSION_STAGE_01_V1_4_MASTER_HASH_BINDING_V1.md
    - docs/taskbooks/stages/STAGE_01_MASTER_TASKBOOK_ANCHORING.md
    - runner/**
    - tests/**
  writable_after_separate_execution_authorization:
    - runner/master_taskbook_mutation_gate.py
    - tests/test_master_taskbook_mutation_gate.py
    - docs/taskbooks/versions/stage-01/evidence/VERSION_STAGE_01_V1_5_MASTER_MUTATION_HARD_GATE_REPORT.md
    - docs/taskbooks/versions/stage-01/evidence/zh-CN/VERSION_STAGE_01_V1_5_MASTER_MUTATION_HARD_GATE_REPORT.zh-CN.md

allowed_mutations:
  - create_or_update_declared_mutation_gate_helper_only_after_explicit_execution_authorization
  - create_or_update_declared_mutation_gate_tests_only_after_explicit_execution_authorization
  - create_or_update_declared_evidence_report_only_after_explicit_execution_authorization

forbidden_files:
  mutation_targets:
    - /home/jenn/tools/colameta/**
    - PROJECT_MASTER_TASKBOOK.md
    - PROJECT_MASTER_TASKBOOK.zh-CN.md
    - FREEZE_CANDIDATE_REVIEW_PACKET.md
    - docs/taskbooks/stages/**
    - docs/taskbooks/versions/stage-00/**
    - .colameta/state.json
    - .colameta/runtime/**
    - .git/**
    - "**/.env"
    - "**/*secret*"
    - "**/*credential*"
```

中文解释：v1.5 可以定义未来 gate helper，但不能借“保护 Master”之名直接修改 Master。

---

## 5. Hard Gate Minimum Contract

```yaml id="hard-gate-minimum-contract"
hard_gate_minimum_contract:
  protected_paths:
    - PROJECT_MASTER_TASKBOOK.md
    - PROJECT_MASTER_TASKBOOK.zh-CN.md
    - FREEZE_CANDIDATE_REVIEW_PACKET.md
    - FREEZE_CANDIDATE_REVIEW_PACKET.zh-CN.md
  mutation_attempt_classes:
    - no_master_mutation
    - read_only_master_access
    - unauthorized_master_mutation_attempt
    - commander_authorized_master_mutation_candidate
    - unknown_master_mutation_risk
  required_decision_fields:
    - protected_path
    - attempted_action
    - detected_from
    - commander_authorization_token_or_none
    - authorization_scope_hash_or_none
    - gate_result
    - failure_reason_or_none
  gate_result_values:
    - allow_read_only
    - block_unauthorized_mutation
    - require_commander_hard_gate
    - known_unknown
  never_allowed_by_default:
    - silent_master_mutation
    - runtime_state_authorized_master_mutation
    - review_packet_authorized_master_mutation
    - executor_session_authorized_master_mutation
```

`protected_paths` = 受保护路径。中文意思是：这些文件是 Master 治理内容，普通任务
不能静默修改。

`gate_result` = 门禁结果。中文意思是：这次访问是只读允许、未授权修改阻断、需要
Commander hard gate，还是证据不足的 known unknown。

---

## 6. Evidence Package Contract

```yaml id="evidence-package-contract"
evidence_package_contract:
  evidence_package_id: stage_01_v1_5_master_mutation_hard_gate_evidence
  required_artifacts:
    - mutation_gate_contract_summary
    - protected_path_check
    - mutation_attempt_classification
    - commander_hard_gate_requirement_check
    - gate_result
    - blocked_attempt_or_none
    - chinese_mutation_gate_report_companion
  not_validated: required_even_when_empty
  remaining_risks: required_even_when_empty
  must_not_include_as_authority:
    - chat memory
    - stale executor session state
    - runtime PASSED or COMPLETED labels
    - unaccepted review packet claims
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
    - sha256sum PROJECT_MASTER_TASKBOOK.md docs/taskbooks/versions/stage-01/VERSION_STAGE_01_V1_4_MASTER_HASH_BINDING_V1.md
  mutation_gate_validation:
    - python -m unittest tests.test_master_taskbook_mutation_gate
    - python -m compileall runner/master_taskbook_mutation_gate.py
  report_validation:
    - git diff --check -- docs/taskbooks/versions/stage-01/evidence/VERSION_STAGE_01_V1_5_MASTER_MUTATION_HARD_GATE_REPORT.md docs/taskbooks/versions/stage-01/evidence/zh-CN/VERSION_STAGE_01_V1_5_MASTER_MUTATION_HARD_GATE_REPORT.zh-CN.md
    - rg -n "protected_path_check|mutation_attempt_classification|commander_hard_gate_requirement_check|gate_result|blocked_attempt_or_none|remaining_risks" docs/taskbooks/versions/stage-01/evidence/VERSION_STAGE_01_V1_5_MASTER_MUTATION_HARD_GATE_REPORT.md
    - rg -n "source_document|source_sha256|硬门|门禁结果|remaining_risks" docs/taskbooks/versions/stage-01/evidence/zh-CN/VERSION_STAGE_01_V1_5_MASTER_MUTATION_HARD_GATE_REPORT.zh-CN.md
```

If the change set cannot be inspected, the gate result must be `known_unknown`
or `require_commander_hard_gate`; it must not silently allow Master mutation.

---

## 8. Manual Acceptance Criteria

```yaml id="manual-acceptance"
manual_acceptance:
  reviewer_may_accept_if:
    - protected paths are explicit
    - read-only Master access is distinguished from mutation attempts
    - unauthorized Master mutation attempts are blocked
    - Commander hard-gate requirement is explicit
    - runtime state cannot authorize Master mutation
    - review packets cannot authorize Master mutation
    - executor session state cannot authorize Master mutation
    - evidence report lists commands_run and commands_not_run separately
    - Chinese report companion explains technical terms in Chinese
  reviewer_must_not_accept_if:
    - ordinary version task can mutate Master silently
    - runtime PASSED or COMPLETED labels authorize Master mutation
    - gate writes delivery_state
    - gate mutates PROJECT_MASTER_TASKBOOK.md
    - gate treats missing evidence as allow
```

---

## 9. Stop Conditions

```yaml id="stop-conditions"
stop_conditions:
  must_stop_if:
    - repository_path_is_not_/home/jenn/src/colameta-dev
    - implementation_would_mutate_PROJECT_MASTER_TASKBOOK_md
    - implementation_requires_/home/jenn/tools/colameta_changes
    - implementation_requires_fetch_pull_push_or_remote_write
    - gate_would_treat_runtime_state_as_master_mutation_authority
    - gate_would_treat_review_packet_as_master_mutation_authority
    - gate_would_claim_delivery_state_accepted
    - tests_require_executor_run_or_service_restart
```

---

## 10. Stage 1 Closeout Readiness

```yaml id="stage-1-closeout-readiness"
stage_1_closeout_readiness:
  readiness_after_v1_1_to_v1_5_drafts:
    - registry_contract_defined
    - reader_contract_defined
    - validator_contract_defined
    - hash_binding_contract_defined
    - mutation_hard_gate_contract_defined
  next_packet_candidate:
    - stage_01_version_set_freeze_candidate_review_packet_draft
  still_not_authorized:
    - implementation
    - executor_run
    - push
    - delivery_state_accepted
```

中文解释：v1.5 是 Stage 1 这一组 Version 草稿的最后一刀。之后可以做 Stage 1
Version set 包级审查和 freeze packet 草稿，但仍不能直接实现。

---

## 11. Non-Authorization Boundary

```yaml id="non-authorization-boundary"
non_authorization_boundary:
  this_taskbook_does_not_authorize:
    - implementation
    - code_changes
    - registry_mutation
    - reader_mutation
    - validator_mutation
    - hash_binding_mutation
    - master_taskbook_mutation
    - commander_hard_gate_token_generation
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

中文解释：这份文件只是 Version Taskbook 草稿。真正要实现 Master mutation hard gate，
还需要 Commander 以后按精确 hash 和范围单独授权。
