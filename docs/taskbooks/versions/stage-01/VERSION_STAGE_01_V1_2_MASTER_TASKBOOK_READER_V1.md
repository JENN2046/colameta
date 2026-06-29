# Version Taskbook: Stage 1 / v1.2 Master Taskbook Reader V1

```text id="version-stage-01-v1-2-boundary-banner"
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
  version_id: stage_01_v1_2_master_taskbook_reader_v1
  version: v1.2
  name: Master Taskbook Reader V1
  chinese_name: 主任务书读取器 V1
  parent_stage_id: stage_01_master_taskbook_anchoring
  parent_stage_name: Master Taskbook Anchoring
  status: discussion_draft
  authority_status: planning_reference_only
  execution_authorization_status: not_authorized
  dispatch_status: not_authorized
  executor_run_authorized: false
  created_from_head: 97fd9be
  created_from_head_meaning: historical_creation_baseline_not_execution_or_freeze_snapshot
  created_from_head_subject: "docs: add stage 1 master registry version taskbook"
  origin_main_observed_local_tracking_ref: 018ff63
  local_tracking_ref_sync_status_at_creation: local_ahead_remote_tracking_ref
  local_ahead_origin_main_at_creation: 9
```

`Master Taskbook Reader V1` = 主任务书读取器 V1。中文意思是：在 registry 合约存在
之后，定义一个只读读取路径，让 ColaMeta 能按登记记录读取 Master 内容和基础元数据，
但不修改 Master、不解释 delivery_state，也不替 validator 做字段合格性判断。

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
  previous_version_taskbook_ref:
    path: docs/taskbooks/versions/stage-01/VERSION_STAGE_01_V1_1_MASTER_TASKBOOK_REGISTRY_V1.md
    raw_snapshot_sha256: 503af0ff7cdac71c55b9fa3d47a09d3fc484c851daffb244a52385ac0dd2b896
    version_id: stage_01_v1_1_master_taskbook_registry_v1
    status: local_baseline_commit_not_pushed_at_creation
  stage_0_6_freeze_packet_ref:
    path: docs/taskbooks/stages/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_0_6.md
    raw_snapshot_sha256: 94ea9101a120e0935e834533ed0315a6fe3e77e3d4ecb48db37fa6851e75b5ce
    review_status: hash_specific_freeze_candidate_confirmation_recorded
  stage_0_version_set_confirmation_ref:
    path: docs/taskbooks/versions/stage-00/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_00_VERSIONS.md
    raw_snapshot_sha256: b3d838f5229a94e88dbaa405a0f65ae76f5208660ab000c1eecd777090897acc
    review_status: hash_specific_freeze_candidate_confirmation_recorded
  supports_project_goal: true
```

This Version Taskbook is subordinate to Stage 1 and follows v1.1. If the reader
contract conflicts with the registry contract, the conflict must be treated as a
taskbook defect.

中文解释：v1.2 必须站在 v1.1 registry 合约后面，不能自己发明另一套 Master 锚点。

---

## 2. Task Goal

```yaml id="task-goal"
task_goal:
  primary_goal: >
    Define a bounded, read-only Master Taskbook reader that loads the registered
    Master path, reads the current Master content, reports observed metadata,
    and refuses to treat read content as active authority or accepted delivery
    state.
  minimum_readiness_claim: >
    Later Stage 1 validator work can consume a stable read result without
    re-opening registry ownership or mutating PROJECT_MASTER_TASKBOOK.md.
  gate_question: >
    Can ColaMeta read the registered Master Taskbook through a controlled local
    pathway while preserving the registry authority boundary?
  explicit_non_goal: >
    This version is not required-field validation, not canonical hashing, not
    mutation control, not registry creation, not executor dispatch, and not a
    CLI or Web status surface.
```

中文解释：v1.2 只回答“能不能按登记记录只读拿到 Master 内容”。它不判断 Master
字段是否合格，那是 v1.3。

---

## 3. Candidate Execution Envelope

This section is an envelope candidate only. It becomes executable only if the
Commander separately authorizes it by exact hash and scope.

```yaml id="candidate-execution-envelope"
execution_envelope_candidate:
  authorization_status: not_authorized
  parent_hashes:
    master_taskbook_hash: 1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34
    stage_taskbook_hash: f880585ed8d37639d215c9f440b37750defa9201f265b2fb7bd63cfdacf6c326
    previous_v1_1_taskbook_hash: 503af0ff7cdac71c55b9fa3d47a09d3fc484c851daffb244a52385ac0dd2b896
  task_goal_ref: task_goal.primary_goal
  definition_of_good:
    - reader loads registry record without mutating it
    - reader resolves Master path within the target repository
    - reader reads Master content without modifying it
    - reader reports raw content hash and observed metadata
    - reader fails closed on missing registry or path escape
    - reader does not validate project_final_goal semantics
    - reader does not claim delivery_state accepted
  allowed_autonomy_after_explicit_authorization:
    - local file inspection
    - narrow reader helper creation
    - focused unit tests for read-only behavior and fail-closed path handling
    - narrow evidence report creation under declared output paths
```

`fail closed` = 失败时关闭。中文意思是：如果 registry 缺失、路径越界、hash 不匹配
或读不到 Master，系统要明确失败，不要假装成功或猜一个结果。

---

## 4. Allowed Files And Mutations

```yaml id="allowed-files-and-mutations"
allowed_files:
  read_only:
    - PROJECT_MASTER_TASKBOOK.md
    - PROJECT_MASTER_TASKBOOK.zh-CN.md
    - .colameta/taskbooks/master_taskbook_registry.json
    - docs/taskbooks/versions/stage-01/VERSION_STAGE_01_V1_1_MASTER_TASKBOOK_REGISTRY_V1.md
    - docs/taskbooks/stages/STAGE_01_MASTER_TASKBOOK_ANCHORING.md
    - docs/taskbooks/CHINESE_COMPANION_POLICY.md
    - docs/taskbooks/CHINESE_COMPANION_INDEX.md
    - .colameta/plan.json
    - .colameta/plan.zh-CN.md
    - runner/**
    - tests/**
  writable_after_separate_execution_authorization:
    - runner/master_taskbook_reader.py
    - tests/test_master_taskbook_reader.py
    - docs/taskbooks/versions/stage-01/evidence/VERSION_STAGE_01_V1_2_MASTER_TASKBOOK_READER_REPORT.md
    - docs/taskbooks/versions/stage-01/evidence/zh-CN/VERSION_STAGE_01_V1_2_MASTER_TASKBOOK_READER_REPORT.zh-CN.md

allowed_mutations:
  - create_or_update_declared_reader_helper_only_after_explicit_execution_authorization
  - create_or_update_declared_reader_tests_only_after_explicit_execution_authorization
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

The registry file is read-only for this version. If the registry is missing,
v1.2 must record a known unknown or fail closed; it must not create the registry
as a side effect.

中文解释：v1.2 只读 registry，不创建 registry。创建 registry 属于 v1.1 的执行范围。

---

## 5. Reader Result Minimum Contract

```yaml id="reader-result-minimum-contract"
reader_result_minimum_contract:
  required_fields:
    - registry_record_id
    - master_taskbook_path
    - resolved_master_taskbook_path
    - path_within_repository
    - raw_content_sha256
    - observed_file_size_bytes
    - observed_git_head
    - registry_review_status_boundary
    - read_status
    - failure_reason_or_none
  forbidden_fields_as_authority:
    - delivery_state
    - accepted
    - executor_authorization
    - active_master_authority
    - review_decision_outcome
```

`Reader Result` = 读取结果。中文意思是：reader 只报告它读到了什么和怎么读的，
不能顺手产出验收结论。

---

## 6. Evidence Package Contract

```yaml id="evidence-package-contract"
evidence_package_contract:
  evidence_package_id: stage_01_v1_2_master_taskbook_reader_evidence
  required_artifacts:
    - reader_contract_summary
    - registry_read_result_or_known_unknown
    - master_path_resolution_check
    - raw_content_hash_check
    - read_only_boundary_check
    - fail_closed_path_escape_check
    - chinese_reader_report_companion
  not_validated: required_even_when_empty
  remaining_risks: required_even_when_empty
  must_not_include_as_authority:
    - chat memory
    - stale executor session state
    - runtime PASSED or COMPLETED labels
    - unaccepted review packet claims
```

中文解释：证据包只证明 reader 的读操作和边界，不证明 Master 内容已经合格。

---

## 7. Candidate Acceptance Commands

These commands are candidates for a later authorized execution. They are not run
by writing this taskbook.

```yaml id="candidate-acceptance-commands"
acceptance_commands:
  preflight_read_only:
    - git status --short --branch
    - git rev-parse HEAD
    - sha256sum PROJECT_MASTER_TASKBOOK.md .colameta/taskbooks/master_taskbook_registry.json || true
  reader_validation:
    - python -m unittest tests.test_master_taskbook_reader
    - python -m compileall runner/master_taskbook_reader.py
  report_validation:
    - git diff --check -- docs/taskbooks/versions/stage-01/evidence/VERSION_STAGE_01_V1_2_MASTER_TASKBOOK_READER_REPORT.md docs/taskbooks/versions/stage-01/evidence/zh-CN/VERSION_STAGE_01_V1_2_MASTER_TASKBOOK_READER_REPORT.zh-CN.md
    - rg -n "reader_result|raw_content_sha256|path_within_repository|failure_reason_or_none|known_gaps|remaining_risks" docs/taskbooks/versions/stage-01/evidence/VERSION_STAGE_01_V1_2_MASTER_TASKBOOK_READER_REPORT.md
    - rg -n "source_document|source_sha256|reader_result|raw_content_sha256|remaining_risks" docs/taskbooks/versions/stage-01/evidence/zh-CN/VERSION_STAGE_01_V1_2_MASTER_TASKBOOK_READER_REPORT.zh-CN.md
```

If the registry file is unavailable, the report must record `known_unknown` or
`registry_missing`; it must not create or repair the registry in this version.

---

## 8. Manual Acceptance Criteria

```yaml id="manual-acceptance"
manual_acceptance:
  reviewer_may_accept_if:
    - reader only reads registry and Master content
    - reader rejects paths outside the repository
    - reader reports raw_content_sha256
    - reader reports failure_reason_or_none
    - reader does not mutate PROJECT_MASTER_TASKBOOK.md
    - reader does not create or update registry records
    - evidence report lists commands_run and commands_not_run separately
    - Chinese report companion explains technical terms in Chinese
  reviewer_must_not_accept_if:
    - reader validates project_final_goal semantics
    - reader claims active Master authority
    - reader maps read success to accepted delivery_state
    - reader creates registry records as a side effect
    - evidence is based only on chat memory or stale runtime labels
```

---

## 9. Stop Conditions

```yaml id="stop-conditions"
stop_conditions:
  must_stop_if:
    - repository_path_is_not_/home/jenn/src/colameta-dev
    - implementation_would_mutate_PROJECT_MASTER_TASKBOOK_md
    - implementation_would_create_or_modify_registry_record
    - implementation_requires_/home/jenn/tools/colameta_changes
    - implementation_requires_fetch_pull_push_or_remote_write
    - reader_result_would_claim_active_master_authority
    - reader_result_would_claim_delivery_state_accepted
    - tests_require_executor_run_or_service_restart
```

---

## 10. Handoff

```yaml id="handoff"
handoff:
  next_version_candidate_after_success: stage_01_v1_3_master_taskbook_required_field_validator_v1
  handoff_contract:
    - reader_result_contains_raw_content
    - reader_result_contains_raw_content_sha256
    - reader_result_preserves_authority_boundary
    - validator_receives_reader_result_as_input_not_authority
  must_not_skip_to:
    - canonical hash binding
    - mutation hard gate
    - external taskbook import
    - executor dispatch
```

中文解释：v1.2 成功后，v1.3 才能拿 reader result 去做字段校验。reader result
本身不是 authority。

---

## 11. Non-Authorization Boundary

```yaml id="non-authorization-boundary"
non_authorization_boundary:
  this_taskbook_does_not_authorize:
    - implementation
    - code_changes
    - registry_mutation
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

中文解释：这份文件只是 Version Taskbook 草稿。真正要实现 Master reader，
还需要 Commander 以后按精确 hash 和范围单独授权。
