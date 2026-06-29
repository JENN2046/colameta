# Version Taskbook: Stage 3 / v3.1 External Taskbook Schema V1

```text id="version-stage-03-v3-1-boundary-banner"
VERSION TASKBOOK DRAFT ONLY.
This document defines a candidate Version Execution Taskbook for Stage 3. It
does not authorize execution, executor dispatch, code edits, commit, push,
fetch, pull, route transition, plan mutation, allowed_files expansion, import
adoption, review acceptance, Delivery State Gate transition, or accepted
delivery state.
```

```yaml id="version-taskbook-summary"
version_execution_taskbook:
  document_type: version_execution_taskbook
  schema_version: version_execution_taskbook.discussion_draft.v1
  version_id: stage_03_v3_1_external_taskbook_schema_v1
  version: v3.1
  name: External Taskbook Schema V1
  chinese_name: 外部任务书模式 V1
  parent_stage_id: stage_03_external_taskbook_import
  parent_stage_name: External Taskbook Import Protocol
  status: discussion_draft
  authority_status: planning_reference_only
  execution_authorization_status: not_authorized
  dispatch_status: not_authorized
  executor_run_authorized: false
  created_from_head: 9725de7
  created_from_head_full: 9725de7e5f5f053a155814d04bb50c1251eb7d5e
  created_from_head_meaning: historical_creation_baseline_not_execution_or_freeze_snapshot
  created_from_head_subject: "docs: record stage 2 version freeze confirmation"
  origin_main_observed_local_tracking_ref: 018ff63
  local_tracking_ref_sync_status_at_creation: local_ahead_remote_tracking_ref
  local_ahead_origin_main_at_creation: 24
```

`External Taskbook Schema V1` = 外部任务书模式 V1。中文意思是：先定义一份外部
Version Execution Taskbook 进入 ColaMeta 前必须携带的字段。外部任务书进入时只是
claim，不是事实、计划修改或执行命令。

---

## 1. Parent Binding

```yaml id="parent-binding"
parent_binding:
  master_taskbook_ref:
    path: PROJECT_MASTER_TASKBOOK.md
    raw_snapshot_sha256: 1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34
    review_status: freeze_candidate_confirmed_for_exact_hash
  stage_taskbook_ref:
    path: docs/taskbooks/stages/STAGE_03_EXTERNAL_TASKBOOK_IMPORT.md
    raw_snapshot_sha256: c5402734ef6990687a6a03ec6b17769f598ff0319b350b6a2371144985ece7ff
    stage_id: stage_03_external_taskbook_import
  stage_0_6_freeze_packet_ref:
    path: docs/taskbooks/stages/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_0_6.md
    raw_snapshot_sha256: 94ea9101a120e0935e834533ed0315a6fe3e77e3d4ecb48db37fa6851e75b5ce
    review_status: hash_specific_freeze_candidate_confirmation_recorded
  stage_2_version_set_confirmation_ref:
    path: docs/taskbooks/versions/stage-02/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_02_VERSIONS.md
    raw_snapshot_sha256: 3de9f207f7a80ce1ec3f2cb374c1f10b4903014be18d0dbe6d2defa1224e8f58
    review_status: hash_specific_freeze_candidate_confirmation_recorded
  supports_project_goal: true
```

This Version Taskbook is subordinate to Stage 3. If it conflicts with the
Master, Stage 3, or Stage 2 confirmation record, the conflict must be treated as
a taskbook defect, not as authority to reinterpret the parent documents.

中文解释：v3.1 只能服务“外部任务书导入协议”。它不能把外部任务书直接变成内部计划。

---

## 2. Task Goal

```yaml id="task-goal"
task_goal:
  primary_goal: >
    Define the minimal schema for externally authored Version Execution
    Taskbooks entering ColaMeta as claims, including provenance, external hash,
    expected hash authority, Master and Stage references, allowed and forbidden
    files, acceptance commands, manual acceptance requirements, out-of-scope
    boundaries, and stage/master goal support.
  minimum_readiness_claim: >
    ColaMeta can identify whether an external taskbook carries the minimum
    fields needed for validation and preview before any adoption or mutation is
    considered.
  gate_question: >
    Can an external taskbook be represented as a bounded claim without being
    trusted as a plan mutation, execution command, or accepted delivery state?
  explicit_non_goal: >
    This version is not an import validator, not an import preview renderer, not
    a plan mutation engine, not executor dispatch, and not import adoption.
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
    stage_taskbook_hash: c5402734ef6990687a6a03ec6b17769f598ff0319b350b6a2371144985ece7ff
    stage_2_version_set_confirmation_hash: 3de9f207f7a80ce1ec3f2cb374c1f10b4903014be18d0dbe6d2defa1224e8f58
  task_goal_ref: task_goal.primary_goal
  definition_of_good:
    - external taskbook schema required fields are explicit and machine-checkable
    - schema distinguishes external claims from trusted internal facts
    - schema requires allowed_files and forbidden_files
    - schema requires acceptance_commands and manual_acceptance
    - schema requires expected_hash_authority_ref
    - schema does not authorize plan mutation or executor dispatch
  allowed_autonomy_after_explicit_authorization:
    - local file inspection
    - narrow schema-file creation or update under declared path
    - focused schema tests for valid and invalid examples
    - narrow evidence report and Chinese report companion update
```

---

## 4. Allowed Files And Mutations

```yaml id="allowed-files-and-mutations"
allowed_files:
  read_only:
    - PROJECT_MASTER_TASKBOOK.md
    - docs/taskbooks/stages/STAGE_03_EXTERNAL_TASKBOOK_IMPORT.md
    - docs/taskbooks/stages/zh-CN/STAGE_03_EXTERNAL_TASKBOOK_IMPORT.zh-CN.md
    - docs/taskbooks/versions/stage-02/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_02_VERSIONS.md
    - docs/taskbooks/versions/stage-02/zh-CN/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_02_VERSIONS.zh-CN.md
    - docs/taskbooks/CHINESE_COMPANION_POLICY.md
    - docs/taskbooks/CHINESE_COMPANION_INDEX.md
    - runner/**
    - tests/**
  writable_after_separate_execution_authorization:
    - .colameta/taskbooks/external_taskbook_schema.json
    - runner/external_taskbook_schema.py
    - tests/test_external_taskbook_schema.py
    - docs/taskbooks/versions/stage-03/evidence/VERSION_STAGE_03_V3_1_EXTERNAL_TASKBOOK_SCHEMA_REPORT.md
    - docs/taskbooks/versions/stage-03/evidence/zh-CN/VERSION_STAGE_03_V3_1_EXTERNAL_TASKBOOK_SCHEMA_REPORT.zh-CN.md
forbidden_files:
  mutation_targets:
    - /home/jenn/tools/colameta/**
    - PROJECT_MASTER_TASKBOOK.md
    - PROJECT_MASTER_TASKBOOK.zh-CN.md
    - docs/taskbooks/stages/**
    - docs/taskbooks/versions/stage-00/**
    - docs/taskbooks/versions/stage-01/**
    - docs/taskbooks/versions/stage-02/**
    - .colameta/plan.json
    - .colameta/state.json
    - .colameta/runtime/**
    - .git/**
    - "**/.env"
    - "**/*secret*"
    - "**/*credential*"
```

中文解释：v3.1 可以定义未来 schema 怎么写，但不能现在修改 plan、Stage、Master 或
稳定服务目录。

---

## 5. External Taskbook Schema Minimum Contract

```yaml id="external-taskbook-schema-minimum-contract"
external_taskbook_schema_minimum_contract:
  required_fields:
    - source
    - provenance
    - external_taskbook_hash
    - expected_hash_authority_ref
    - master_taskbook_ref
    - stage_taskbook_ref
    - allowed_files
    - forbidden_files
    - acceptance_commands
    - manual_acceptance
    - out_of_scope
    - supports_stage_and_master_goals
  rejection_fields:
    - rejected_fields
    - rejection_reasons
    - known_conflicts
  normalized_output_fields:
    - normalized_claims
    - normalized_output_candidate
    - version_candidate_mapping
  forbidden_authority_claims:
    - external_taskbook_is_trusted_fact
    - external_taskbook_mutates_plan
    - external_taskbook_authorizes_execution
    - external_taskbook_expands_allowed_files
    - manual_acceptance_means_delivery_state_accepted
```

`expected_hash_authority_ref` = 预期哈希权威引用。中文意思是：说明外部任务书的
期望 hash 应该由哪份授权材料或回执来提供，不能凭空声称 hash 正确。

---

## 6. Evidence Package Contract

```yaml id="evidence-package-contract"
evidence_package_contract:
  evidence_package_id: stage_03_v3_1_external_taskbook_schema_evidence
  required_artifacts:
    - schema_contract_summary
    - required_field_table
    - forbidden_authority_claims_check
    - example_valid_claim_shape
    - example_rejected_claim_shape
    - commands_run
    - commands_not_run
    - known_gaps
    - remaining_risks
    - chinese_report_companion
  must_not_include_as_authority:
    - source reputation alone
    - user silence
    - previous memory
    - runtime status labels
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
    - sha256sum PROJECT_MASTER_TASKBOOK.md docs/taskbooks/stages/STAGE_03_EXTERNAL_TASKBOOK_IMPORT.md
  schema_validation:
    - python -m unittest tests.test_external_taskbook_schema
    - python -m compileall runner/external_taskbook_schema.py
  report_validation:
    - git diff --check -- docs/taskbooks/versions/stage-03/evidence/VERSION_STAGE_03_V3_1_EXTERNAL_TASKBOOK_SCHEMA_REPORT.md docs/taskbooks/versions/stage-03/evidence/zh-CN/VERSION_STAGE_03_V3_1_EXTERNAL_TASKBOOK_SCHEMA_REPORT.zh-CN.md
    - rg -n "schema_contract_summary|required_field_table|forbidden_authority_claims_check|remaining_risks" docs/taskbooks/versions/stage-03/evidence/VERSION_STAGE_03_V3_1_EXTERNAL_TASKBOOK_SCHEMA_REPORT.md
```

These commands are candidates for later authorized execution only.

---

## 8. Manual Acceptance Criteria

```yaml id="manual-acceptance"
manual_acceptance:
  reviewer_may_accept_if:
    - schema includes all Stage 3 minimum external taskbook fields
    - schema requires allowed_files and forbidden_files
    - schema requires acceptance_commands and manual_acceptance
    - schema rejects plan mutation and execution authority claims
    - evidence report separates commands_run from commands_not_run
  reviewer_must_not_accept_if:
    - schema treats external taskbook as trusted fact
    - schema allows automatic plan mutation
    - schema allows automatic allowed_files expansion
    - schema maps manual_acceptance to delivery_state accepted
```

---

## 9. Stop Conditions

```yaml id="stop-conditions"
stop_conditions:
  must_stop_if:
    - repository_path_is_not_/home/jenn/src/colameta-dev
    - implementation_would_mutate_PROJECT_MASTER_TASKBOOK_md
    - implementation_would_mutate_colameta_plan
    - implementation_would_mutate_stage_taskbook_sources
    - implementation_requires_/home/jenn/tools/colameta_changes
    - implementation_requires_fetch_pull_push_or_remote_write
    - schema_would_claim_execution_authority
    - schema_would_claim_delivery_state_accepted
    - required_hashes_do_not_match_declared_parent_hashes
```

---

## 10. Next Version Handoff

```yaml id="next-version-handoff"
next_version_handoff:
  next_version: v3.2 External Taskbook Validator V1
  handoff_requires:
    - external taskbook schema minimum contract is explicit
    - forbidden authority claims are explicit
    - schema treats external taskbooks as claims only
  must_not_handoff_as:
    - import_adoption_authorization
    - plan_mutation_authorization
    - execution_authorization
```
