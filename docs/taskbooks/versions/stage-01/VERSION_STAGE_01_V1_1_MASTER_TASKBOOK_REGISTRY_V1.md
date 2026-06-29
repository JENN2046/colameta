# Version Taskbook: Stage 1 / v1.1 Master Taskbook Registry V1

```text id="version-stage-01-v1-1-boundary-banner"
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
  version_id: stage_01_v1_1_master_taskbook_registry_v1
  version: v1.1
  name: Master Taskbook Registry V1
  chinese_name: 主任务书登记表 V1
  parent_stage_id: stage_01_master_taskbook_anchoring
  parent_stage_name: Master Taskbook Anchoring
  status: discussion_draft
  authority_status: planning_reference_only
  execution_authorization_status: not_authorized
  dispatch_status: not_authorized
  executor_run_authorized: false
  created_from_head: 9662dc6
  created_from_head_meaning: historical_creation_baseline_not_execution_or_freeze_snapshot
  created_from_head_subject: "docs: record stage 0 version freeze confirmation"
  origin_main_observed_local_tracking_ref: 018ff63
  local_tracking_ref_sync_status_at_creation: local_ahead_remote_tracking_ref
  local_ahead_origin_main_at_creation: 8
```

`Version Execution Taskbook` = 版本执行任务书。中文意思是：它把某个 Stage
下面的一次小交付切成可验证、可审查、可授权的执行边界。

`Master Taskbook Registry V1` = 主任务书登记表 V1。中文意思是：先把
`PROJECT_MASTER_TASKBOOK.md` 的路径、hash、审查状态边界和当前观察 HEAD 登记成
一个最小治理记录，让后续 reader、validator、hash binding 和 mutation gate 都能
引用同一个 Master 锚点。

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

This Version Taskbook is subordinate to Stage 1. If it conflicts with the
Master or Stage 1 Taskbook, the conflict must be treated as a taskbook defect,
not as authority to reinterpret the parent documents.

中文解释：这份 Version 只能服务 Stage 1 的“主任务书锚定”，不能反过来改写
Master、Stage 1，或 Stage 0 的确认记录。

---

## 2. Task Goal

```yaml id="task-goal"
task_goal:
  primary_goal: >
    Define the first Stage 1 implementation slice for a minimal Master Taskbook
    registry that records the exact Master Taskbook path, raw snapshot hash,
    review-status boundary, observed local repository HEAD, observed local
    origin/main tracking-ref state, and mutation boundary.
  minimum_readiness_claim: >
    Later Stage 1 work can refer to a stable Master registry contract without
    treating Master freeze_candidate status as active execution authority.
  gate_question: >
    Can the project identify the single Master Taskbook anchor by path, hash,
    review status, observed HEAD, and mutation boundary before any reader or
    validator is implemented?
  explicit_non_goal: >
    This version is not a full taskbook platform, not a Master reader, not a
    Master validator, not a canonical hash engine, not a CLI status surface,
    not executor dispatch, and not delivery-state acceptance.
```

中文解释：这一步只先定义“Master 应该怎样被登记”。它不做完整读取器、不做字段
校验器、不做 CLI，也不声称 Master 已经变成 active authority。

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
    stage_0_6_freeze_packet_hash: 94ea9101a120e0935e834533ed0315a6fe3e77e3d4ecb48db37fa6851e75b5ce
    stage_0_version_set_confirmation_hash: b3d838f5229a94e88dbaa405a0f65ae76f5208660ab000c1eecd777090897acc
  task_goal_ref: task_goal.primary_goal
  definition_of_good:
    - master registry contract is explicit and machine-checkable
    - registry record distinguishes review status from active authority
    - registry record includes observed local HEAD and local tracking-ref state
    - registry record includes mutation boundary for PROJECT_MASTER_TASKBOOK.md
    - implementation does not mutate PROJECT_MASTER_TASKBOOK.md
    - implementation does not claim delivery_state accepted
  allowed_autonomy_after_explicit_authorization:
    - local file inspection
    - narrow registry-file creation or update under declared path
    - focused unit tests for registry parsing and fail-closed behavior
    - narrow documentation companion update for the created registry contract
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
    - FREEZE_CANDIDATE_REVIEW_PACKET.md
    - FREEZE_CANDIDATE_REVIEW_PACKET.zh-CN.md
    - docs/taskbooks/stages/README.md
    - docs/taskbooks/stages/STAGE_01_MASTER_TASKBOOK_ANCHORING.md
    - docs/taskbooks/stages/zh-CN/STAGE_01_MASTER_TASKBOOK_ANCHORING.zh-CN.md
    - docs/taskbooks/stages/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_0_6.md
    - docs/taskbooks/stages/zh-CN/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_0_6.zh-CN.md
    - docs/taskbooks/versions/stage-00/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_00_VERSIONS.md
    - docs/taskbooks/versions/stage-00/zh-CN/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_00_VERSIONS.zh-CN.md
    - docs/taskbooks/CHINESE_COMPANION_POLICY.md
    - docs/taskbooks/CHINESE_COMPANION_INDEX.md
    - .colameta/plan.json
    - .colameta/plan.zh-CN.md
    - .colameta/state.json
    - runner/**
    - tests/**
  writable_after_separate_execution_authorization:
    - .colameta/taskbooks/master_taskbook_registry.json
    - runner/master_taskbook_registry.py
    - tests/test_master_taskbook_registry.py
    - docs/taskbooks/versions/stage-01/evidence/VERSION_STAGE_01_V1_1_MASTER_TASKBOOK_REGISTRY_REPORT.md
    - docs/taskbooks/versions/stage-01/evidence/zh-CN/VERSION_STAGE_01_V1_1_MASTER_TASKBOOK_REGISTRY_REPORT.zh-CN.md

allowed_mutations:
  - create_or_update_declared_master_registry_only_after_explicit_execution_authorization
  - create_or_update_declared_registry_helper_only_after_explicit_execution_authorization
  - create_or_update_declared_registry_tests_only_after_explicit_execution_authorization
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

The candidate registry path and helper files are not authorized by this
document. They become writable only under a later exact execution authorization.

中文解释：这份任务书现在只是草稿。它可以描述未来可能写哪里，但不能现在就改
registry、runner、tests 或 Master。

---

## 5. Master Registry Minimum Contract

```yaml id="master-registry-minimum-contract"
master_registry_minimum_contract:
  registry_record_id: master_taskbook.current
  required_fields:
    - project
    - workspace
    - master_taskbook_path
    - master_raw_snapshot_sha256
    - master_review_status
    - master_authority_boundary
    - project_final_goal_ref
    - source_stage_taskbook_ref
    - source_version_taskbook_ref
    - observed_git_head
    - observed_origin_main_local_tracking_ref
    - ahead_behind_from_local_refs
    - live_remote_status_not_validated
    - mutation_boundary
    - created_at
  forbidden_authority_claims:
    - master_is_active_execution_authority
    - master_is_accepted_delivery_state
    - freeze_candidate_implies_executor_authority
    - registry_record_can_mutate_master
    - registry_record_can_override_delivery_state_gate
```

`Registry Record` = 登记记录。中文意思是：一条机器可读的治理记录，说明当前
项目使用哪份 Master、它的 hash 是什么、它的审查状态是什么，以及它不能被当成
什么。

`master_authority_boundary` = Master 权威边界。中文意思是：明确
`freeze_candidate` 只是审查状态，不是 active authority，不授权实现、executor、
route transition 或 accepted。

---

## 6. Evidence Package Contract

```yaml id="evidence-package-contract"
evidence_package_contract:
  evidence_package_id: stage_01_v1_1_master_taskbook_registry_evidence
  required_artifacts:
    - registry_contract_summary
    - registry_file_or_known_unknown
    - master_hash_check
    - observed_git_head_check
    - local_tracking_ref_check
    - mutation_boundary_check
    - fail_closed_validation_check
    - chinese_registry_report_companion
  not_validated: required_even_when_empty
  remaining_risks: required_even_when_empty
  must_not_include_as_authority:
    - chat memory
    - stale executor session state
    - runtime PASSED or COMPLETED labels
    - unaccepted review packet claims
    - live remote state unless explicitly probed under authorization
```

`Evidence Package` = 证据包。中文意思是：把“做了什么、看到了什么、哪些命令跑了、
哪些没跑、还有什么风险”收起来给审查者看。证据包不是批准，不会改变
delivery_state。

---

## 7. Candidate Acceptance Commands

These commands are candidates for a later authorized execution. They are not run
by writing this taskbook.

```yaml id="candidate-acceptance-commands"
acceptance_commands:
  preflight_read_only:
    - git status --short --branch
    - git rev-parse HEAD
    - git rev-parse origin/main || true
    - git rev-list --left-right --count origin/main...HEAD || true
    - sha256sum PROJECT_MASTER_TASKBOOK.md docs/taskbooks/stages/STAGE_01_MASTER_TASKBOOK_ANCHORING.md
  registry_validation:
    - python -m unittest tests.test_master_taskbook_registry
    - python -m compileall runner/master_taskbook_registry.py
  report_validation:
    - git diff --check -- docs/taskbooks/versions/stage-01/evidence/VERSION_STAGE_01_V1_1_MASTER_TASKBOOK_REGISTRY_REPORT.md docs/taskbooks/versions/stage-01/evidence/zh-CN/VERSION_STAGE_01_V1_1_MASTER_TASKBOOK_REGISTRY_REPORT.zh-CN.md
    - rg -n "master_taskbook_path|master_raw_snapshot_sha256|master_review_status|master_authority_boundary|mutation_boundary|known_gaps|remaining_risks" docs/taskbooks/versions/stage-01/evidence/VERSION_STAGE_01_V1_1_MASTER_TASKBOOK_REGISTRY_REPORT.md
    - rg -n "source_document|source_sha256|master_taskbook_path|mutation_boundary|known_gaps|remaining_risks" docs/taskbooks/versions/stage-01/evidence/zh-CN/VERSION_STAGE_01_V1_1_MASTER_TASKBOOK_REGISTRY_REPORT.zh-CN.md
```

If the local `origin/main` tracking ref is unavailable, the report must record
`known_unknown`; it must not auto-fetch or contact the remote. If registry tests
are not authorized, they must be listed under `commands_not_run`.

中文解释：这些是未来执行时的候选验收命令。现在写在任务书里，不代表已经执行，
也不代表已经授权执行。

---

## 8. Manual Acceptance Criteria

```yaml id="manual-acceptance"
manual_acceptance:
  reviewer_may_accept_if:
    - registry record exists at the declared path or a known_unknown explains why not
    - registry record binds PROJECT_MASTER_TASKBOOK.md by exact raw snapshot hash
    - registry record distinguishes freeze_candidate review status from active authority
    - registry record preserves project_final_goal_ref
    - registry record includes mutation_boundary for Master governance content
    - registry helper fails closed on missing required fields
    - evidence report lists commands_run and commands_not_run separately
    - Chinese report companion explains technical terms in Chinese
  reviewer_must_not_accept_if:
    - registry claims Master active execution authority
    - registry mutates PROJECT_MASTER_TASKBOOK.md
    - registry maps freeze_candidate to accepted delivery_state
    - evidence is based only on chat memory or stale runtime labels
    - tests or report validation fail without documented known_unknowns
```

`Manual Acceptance Criteria` = 人工验收条件。中文意思是：审查者可以根据这些条件
判断结果是否够格，但审查记录本身仍不等于 Delivery State Gate 的 accepted。

---

## 9. Stop Conditions

```yaml id="stop-conditions"
stop_conditions:
  must_stop_if:
    - repository_path_is_not_/home/jenn/src/colameta-dev
    - implementation_would_mutate_PROJECT_MASTER_TASKBOOK_md
    - implementation_requires_/home/jenn/tools/colameta_changes
    - implementation_requires_fetch_pull_push_or_remote_write
    - registry_record_would_claim_active_master_authority
    - registry_record_would_claim_delivery_state_accepted
    - required_hashes_do_not_match_declared_parent_hashes
    - tests_require_executor_run_or_service_restart
```

中文解释：这些情况一出现就必须停，不能把“登记 Master”悄悄扩成“改 Master”
或“让 Master 直接生效”。

---

## 10. Handoff

```yaml id="handoff"
handoff:
  next_version_candidates_after_success:
    - stage_01_v1_2_master_taskbook_reader_v1
    - stage_01_v1_3_master_taskbook_required_field_validator_v1
    - stage_01_v1_4_master_hash_binding_v1
    - stage_01_v1_5_master_mutation_hard_gate_v1
  must_not_skip_to:
    - full taskbook management platform
    - external taskbook import
    - executor dispatch
    - delivery_state acceptance
```

中文解释：v1.1 成功后，下一刀才考虑 reader 或 validator。不要直接跳去完整平台、
外部导入或 executor。

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

中文解释：这份文件只是 Version Taskbook 草稿。真正要实现 Master registry，
还需要 Commander 以后按精确 hash 和范围单独授权。
