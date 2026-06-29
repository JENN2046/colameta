# Version Taskbook: Stage 1 / v1.4 Master Hash Binding V1

```text id="version-stage-01-v1-4-boundary-banner"
VERSION TASKBOOK DRAFT ONLY.
This document defines a candidate Version Execution Taskbook for Stage 1. It
does not authorize execution, executor dispatch, code edits, commit, push,
fetch, pull, route transition, Delivery State Gate transition, canonical receipt
finalization, or accepted delivery state.
```

```yaml id="version-taskbook-summary"
version_execution_taskbook:
  document_type: version_execution_taskbook
  schema_version: version_execution_taskbook.discussion_draft.v1
  version_id: stage_01_v1_4_master_hash_binding_v1
  version: v1.4
  name: Master Hash Binding V1
  chinese_name: 主任务书哈希绑定 V1
  parent_stage_id: stage_01_master_taskbook_anchoring
  parent_stage_name: Master Taskbook Anchoring
  status: discussion_draft
  authority_status: planning_reference_only
  execution_authorization_status: not_authorized
  dispatch_status: not_authorized
  executor_run_authorized: false
  created_from_head: ab97951
  created_from_head_meaning: historical_creation_baseline_not_execution_or_freeze_snapshot
  created_from_head_subject: "docs: add stage 1 master validator version taskbook"
  origin_main_observed_local_tracking_ref: 018ff63
  local_tracking_ref_sync_status_at_creation: local_ahead_remote_tracking_ref
  local_ahead_origin_main_at_creation: 11
```

`Master Hash Binding V1` = 主任务书哈希绑定 V1。中文意思是：把 reader 实际读到的
Master 内容 hash、registry 声明的 Master hash、validator 看到的 Master 输入
绑定成一份可审查证据；如果不一致，必须 fail closed。

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
  supports_project_goal: true
```

中文解释：v1.4 依赖 v1.1 的 registry、v1.2 的 reader、v1.3 的 validator。它不能
跳过这些输入自己重新发明 Master 事实。

---

## 2. Task Goal

```yaml id="task-goal"
task_goal:
  primary_goal: >
    Define a deterministic Master hash binding check that compares the
    registered Master raw snapshot hash, the reader raw_content_sha256, and the
    validator input hash, then records a fail-closed binding result.
  minimum_readiness_claim: >
    Later mutation-gate work can distinguish an unchanged Master anchor from a
    drifted or mismatched Master input without relying on runtime labels.
  gate_question: >
    Do the registry, reader, and validator all refer to the same Master content
    hash and the same project_final_goal anchor?
  explicit_non_goal: >
    This version is not canonical receipt finalization, not canonical payload
    policy mutation, not Master mutation control, not registry creation, not
    review acceptance, and not delivery_state promotion.
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
  task_goal_ref: task_goal.primary_goal
  definition_of_good:
    - hash binding consumes registry, reader result, and validator result
    - binding compares raw snapshot hash values deterministically
    - binding distinguishes match, mismatch, missing_input, and known_unknown
    - mismatch fails closed
    - canonical payload hash is explicitly not finalized in this version
    - binding does not mutate PROJECT_MASTER_TASKBOOK.md
    - binding does not write delivery_state
  allowed_autonomy_after_explicit_authorization:
    - local file inspection
    - narrow hash-binding helper creation
    - focused unit tests for match, mismatch, missing input, and known unknown
    - narrow evidence report creation under declared output paths
```

`Hash Binding` = 哈希绑定。中文意思是：把多个来源声称的同一份 Master 内容 hash
放到一起核对，确认它们是否真的指向同一份内容。

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
    - docs/taskbooks/versions/stage-01/VERSION_STAGE_01_V1_1_MASTER_TASKBOOK_REGISTRY_V1.md
    - docs/taskbooks/versions/stage-01/VERSION_STAGE_01_V1_2_MASTER_TASKBOOK_READER_V1.md
    - docs/taskbooks/versions/stage-01/VERSION_STAGE_01_V1_3_MASTER_TASKBOOK_REQUIRED_FIELD_VALIDATOR_V1.md
    - docs/taskbooks/stages/STAGE_01_MASTER_TASKBOOK_ANCHORING.md
    - runner/**
    - tests/**
  writable_after_separate_execution_authorization:
    - runner/master_taskbook_hash_binding.py
    - tests/test_master_taskbook_hash_binding.py
    - docs/taskbooks/versions/stage-01/evidence/VERSION_STAGE_01_V1_4_MASTER_HASH_BINDING_REPORT.md
    - docs/taskbooks/versions/stage-01/evidence/zh-CN/VERSION_STAGE_01_V1_4_MASTER_HASH_BINDING_REPORT.zh-CN.md

allowed_mutations:
  - create_or_update_declared_hash_binding_helper_only_after_explicit_execution_authorization
  - create_or_update_declared_hash_binding_tests_only_after_explicit_execution_authorization
  - create_or_update_declared_evidence_report_only_after_explicit_execution_authorization

forbidden_files:
  mutation_targets:
    - /home/jenn/tools/colameta/**
    - PROJECT_MASTER_TASKBOOK.md
    - PROJECT_MASTER_TASKBOOK.zh-CN.md
    - .colameta/taskbooks/master_taskbook_registry.json
    - docs/taskbooks/stages/**
    - docs/taskbooks/versions/stage-00/**
    - FREEZE_CANDIDATE_REVIEW_PACKET.md
    - .colameta/state.json
    - .colameta/runtime/**
    - .git/**
    - "**/.env"
    - "**/*secret*"
    - "**/*credential*"
```

中文解释：v1.4 可以定义未来 hash-binding helper，但不能修改 Master、registry 或
任何 freeze/confirmation packet。

---

## 5. Hash Binding Minimum Contract

```yaml id="hash-binding-minimum-contract"
hash_binding_minimum_contract:
  required_inputs:
    - registry_master_raw_snapshot_sha256
    - reader_raw_content_sha256
    - validator_input_raw_content_sha256
    - observed_git_head
    - source_version_taskbook_refs
  result_values:
    - match
    - mismatch
    - missing_input
    - known_unknown
  fail_closed_values:
    - mismatch
    - missing_input
  explicitly_deferred:
    - canonical_payload_hash_finalization
    - canonical_receipt_generation
    - active_master_authority
    - delivery_state_transition
```

`canonical_payload_hash_finalization` = 规范载荷 hash 最终化。中文意思是：对抽取后的
规范字段载荷算最终 hash。v1.4 先不做这件事，只做 raw snapshot hash 绑定。

---

## 6. Evidence Package Contract

```yaml id="evidence-package-contract"
evidence_package_contract:
  evidence_package_id: stage_01_v1_4_master_hash_binding_evidence
  required_artifacts:
    - hash_binding_contract_summary
    - registry_hash_input_or_known_unknown
    - reader_hash_input_or_known_unknown
    - validator_hash_input_or_known_unknown
    - hash_binding_result
    - fail_closed_result
    - chinese_hash_binding_report_companion
  not_validated: required_even_when_empty
  remaining_risks: required_even_when_empty
  must_not_include_as_authority:
    - chat memory
    - stale executor session state
    - runtime PASSED or COMPLETED labels
    - canonical receipt claims not generated by this version
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
    - sha256sum PROJECT_MASTER_TASKBOOK.md docs/taskbooks/versions/stage-01/VERSION_STAGE_01_V1_3_MASTER_TASKBOOK_REQUIRED_FIELD_VALIDATOR_V1.md
  hash_binding_validation:
    - python -m unittest tests.test_master_taskbook_hash_binding
    - python -m compileall runner/master_taskbook_hash_binding.py
  report_validation:
    - git diff --check -- docs/taskbooks/versions/stage-01/evidence/VERSION_STAGE_01_V1_4_MASTER_HASH_BINDING_REPORT.md docs/taskbooks/versions/stage-01/evidence/zh-CN/VERSION_STAGE_01_V1_4_MASTER_HASH_BINDING_REPORT.zh-CN.md
    - rg -n "hash_binding_result|registry_master_raw_snapshot_sha256|reader_raw_content_sha256|validator_input_raw_content_sha256|fail_closed_result|remaining_risks" docs/taskbooks/versions/stage-01/evidence/VERSION_STAGE_01_V1_4_MASTER_HASH_BINDING_REPORT.md
    - rg -n "source_document|source_sha256|哈希绑定|绑定结果|remaining_risks" docs/taskbooks/versions/stage-01/evidence/zh-CN/VERSION_STAGE_01_V1_4_MASTER_HASH_BINDING_REPORT.zh-CN.md
```

If any input is unavailable, the binding result must be `missing_input` or
`known_unknown`; it must not substitute chat memory, runtime labels, or guessed
hashes.

---

## 8. Manual Acceptance Criteria

```yaml id="manual-acceptance"
manual_acceptance:
  reviewer_may_accept_if:
    - binding consumes registry, reader result, and validator result
    - binding compares raw hash values deterministically
    - binding fails closed on mismatch or missing input
    - binding explicitly defers canonical receipt generation
    - binding does not mutate PROJECT_MASTER_TASKBOOK.md
    - binding does not write delivery_state
    - evidence report lists commands_run and commands_not_run separately
    - Chinese report companion explains technical terms in Chinese
  reviewer_must_not_accept_if:
    - binding guesses missing hashes
    - binding treats canonical payload hash as finalized
    - binding claims active Master authority
    - binding claims accepted delivery_state
    - binding rewrites registry, reader output, or validator output
```

---

## 9. Stop Conditions

```yaml id="stop-conditions"
stop_conditions:
  must_stop_if:
    - repository_path_is_not_/home/jenn/src/colameta-dev
    - implementation_would_mutate_PROJECT_MASTER_TASKBOOK_md
    - implementation_would_create_or_modify_registry_record
    - implementation_would_finalize_canonical_receipt
    - implementation_requires_/home/jenn/tools/colameta_changes
    - implementation_requires_fetch_pull_push_or_remote_write
    - binding_result_would_claim_delivery_state_accepted
    - tests_require_executor_run_or_service_restart
```

---

## 10. Handoff

```yaml id="handoff"
handoff:
  next_version_candidate_after_success: stage_01_v1_5_master_mutation_hard_gate_v1
  handoff_contract:
    - hash_binding_result_exists
    - mismatch_and_missing_input_fail_closed
    - canonical_receipt_generation_is_deferred
    - mutation_gate_receives_hash_binding_result_as_evidence_not_authority
  must_not_skip_to:
    - external taskbook import
    - executor dispatch
    - delivery_state acceptance
```

中文解释：v1.5 可以使用 hash binding result 作为证据输入，但不能把它当成 accepted。

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
    - master_taskbook_mutation
    - canonical_receipt_generation
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

中文解释：这份文件只是 Version Taskbook 草稿。真正要实现 Master hash binding，
还需要 Commander 以后按精确 hash 和范围单独授权。
