# Version Taskbook: Stage 3 / v3.3 Taskbook Import Preview V1

```text id="version-stage-03-v3-3-boundary-banner"
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
  version_id: stage_03_v3_3_taskbook_import_preview_v1
  version: v3.3
  name: Taskbook Import Preview V1
  chinese_name: 任务书导入预览 V1
  parent_stage_id: stage_03_external_taskbook_import
  parent_stage_name: External Taskbook Import Protocol
  status: discussion_draft
  authority_status: planning_reference_only
  execution_authorization_status: not_authorized
  dispatch_status: not_authorized
  executor_run_authorized: false
  created_from_head: a435681
  created_from_head_full: a43568112e58e31ee9f47d7d90c0a799c054e8e9
  created_from_head_meaning: historical_creation_baseline_not_execution_or_freeze_snapshot
  created_from_head_subject: "docs: add stage 3 schema validator taskbooks"
  origin_main_observed_local_tracking_ref: 018ff63
  local_tracking_ref_sync_status_at_creation: local_ahead_remote_tracking_ref
  local_ahead_origin_main_at_creation: 25
```

`Taskbook Import Preview V1` = 任务书导入预览 V1。中文意思是：把已通过 v3.2 校验的
外部任务书 claim 转成只读预览，让 Commander 和 Reviewer 能看清它会影响什么；这个
预览不是采用、不是计划修改、不是执行授权。

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
  previous_version_ref:
    path: docs/taskbooks/versions/stage-03/VERSION_STAGE_03_V3_2_EXTERNAL_TASKBOOK_VALIDATOR_V1.md
    raw_snapshot_sha256: 7bdf06889b25439f9ca8ed70a2e93962f1ab6bec9566fe7b752aa47ad9ebb927
    version_id: stage_03_v3_2_external_taskbook_validator_v1
  stage_2_version_set_confirmation_ref:
    path: docs/taskbooks/versions/stage-02/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_02_VERSIONS.md
    raw_snapshot_sha256: 3de9f207f7a80ce1ec3f2cb374c1f10b4903014be18d0dbe6d2defa1224e8f58
    review_status: hash_specific_freeze_candidate_confirmation_recorded
  supports_project_goal: true
```

v3.3 consumes only v3.2 validation output. It must not preview a taskbook that
failed validation, and it must not convert a valid preview into adoption.

中文解释：预览只是“先给你看会发生什么”，不是“已经同意这么做”。

---

## 2. Task Goal

```yaml id="task-goal"
task_goal:
  primary_goal: >
    Define a read-only import preview for validated external taskbook claims.
    The preview must summarize recognized claims, rejected claims, proposed
    Version candidate identity, scope impact, allowed_files candidate delta,
    acceptance command candidates, manual acceptance requirements, blockers,
    and required Commander decisions.
  minimum_readiness_claim: >
    ColaMeta can show what a validated external taskbook would request without
    mutating plan, expanding allowed_files, dispatching an executor, or treating
    the request as accepted.
  gate_question: >
    Can a user inspect an external taskbook import request before any adoption
    or implementation authority exists?
  explicit_non_goal: >
    This version is not taskbook-to-version mapping, not adoption, not plan
    mutation, not executor dispatch, and not review acceptance.
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
    previous_version_hash: 7bdf06889b25439f9ca8ed70a2e93962f1ab6bec9566fe7b752aa47ad9ebb927
    stage_2_version_set_confirmation_hash: 3de9f207f7a80ce1ec3f2cb374c1f10b4903014be18d0dbe6d2defa1224e8f58
  task_goal_ref: task_goal.primary_goal
  definition_of_good:
    - preview accepts only validator_result pass
    - preview identifies recognized and rejected claim fields
    - preview separates candidate allowed_files delta from authorized allowed_files
    - preview lists required Commander decisions before adoption
    - preview states that no plan mutation or executor dispatch is authorized
  allowed_autonomy_after_explicit_authorization:
    - local file inspection
    - narrow import preview helper creation or update under declared path
    - focused preview rendering tests
    - narrow evidence report and Chinese report companion update
```

---

## 4. Allowed Files And Mutations

```yaml id="allowed-files-and-mutations"
allowed_files:
  read_only:
    - PROJECT_MASTER_TASKBOOK.md
    - docs/taskbooks/stages/STAGE_03_EXTERNAL_TASKBOOK_IMPORT.md
    - docs/taskbooks/versions/stage-03/VERSION_STAGE_03_V3_1_EXTERNAL_TASKBOOK_SCHEMA_V1.md
    - docs/taskbooks/versions/stage-03/VERSION_STAGE_03_V3_2_EXTERNAL_TASKBOOK_VALIDATOR_V1.md
    - docs/taskbooks/versions/stage-02/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_02_VERSIONS.md
    - runner/**
    - tests/**
  writable_after_separate_execution_authorization:
    - runner/taskbook_import_preview.py
    - tests/test_taskbook_import_preview.py
    - docs/taskbooks/versions/stage-03/evidence/VERSION_STAGE_03_V3_3_TASKBOOK_IMPORT_PREVIEW_REPORT.md
    - docs/taskbooks/versions/stage-03/evidence/zh-CN/VERSION_STAGE_03_V3_3_TASKBOOK_IMPORT_PREVIEW_REPORT.zh-CN.md
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

---

## 5. Import Preview Contract

```yaml id="import-preview-contract"
import_preview_contract:
  accepted_input:
    - external_taskbook_hash
    - validator_result_ref
    - normalized_claims_candidate
    - rejected_fields
    - rejection_reasons
  required_output_fields:
    - preview_id
    - preview_status
    - source_claim_ref
    - validator_result_ref
    - recognized_claims_summary
    - rejected_claims_summary
    - proposed_version_candidate_identity
    - proposed_scope_summary
    - proposed_allowed_files_candidate_delta
    - proposed_forbidden_files_summary
    - proposed_acceptance_commands_summary
    - proposed_manual_acceptance_summary
    - required_commander_decisions
    - blockers
    - authority_boundary
  valid_preview_statuses:
    - preview_ready
    - preview_blocked_invalid_validator_result
    - preview_blocked_authority_confusion
    - preview_blocked_missing_required_claim
  forbidden_output_claims:
    - adoption_authorized
    - plan_mutation_authorized
    - allowed_files_expansion_authorized
    - executor_dispatch_authorized
    - delivery_state_accepted
```

`proposed_allowed_files_candidate_delta` = 候选 allowed_files 变化。中文意思是：只是告诉
你外部任务书“想改哪些范围”，不是现在允许它改。

---

## 6. Preview Rendering Rules

```yaml id="preview-rendering-rules"
preview_rendering_rules:
  must_show:
    - source_taskbook_hash
    - schema_version_claim
    - validation_result
    - recognized_fields
    - rejected_fields
    - proposed_version_id
    - proposed_target_stage
    - candidate_file_scope
    - forbidden_file_scope
    - manual_acceptance_required
    - commander_decisions_required_before_adoption
  must_label_as_non_authoritative:
    - proposed_version_id
    - proposed_allowed_files_delta
    - proposed_acceptance_commands
    - proposed_manual_acceptance
  must_fail_closed_when:
    - validation_result_is_not_pass
    - validator_result_ref_missing
    - source_taskbook_hash_missing
    - preview_contains_adoption_or_execution_authority
```

---

## 7. Evidence Package Contract

```yaml id="evidence-package-contract"
evidence_package_contract:
  evidence_package_id: stage_03_v3_3_taskbook_import_preview_evidence
  required_artifacts:
    - preview_contract_summary
    - valid_preview_example
    - invalid_validator_result_example
    - authority_boundary_check
    - candidate_delta_labeling_check
    - commands_run
    - commands_not_run
    - known_gaps
    - remaining_risks
    - chinese_report_companion
  must_not_include_as_authority:
    - import adoption
    - plan mutation
    - allowed_files expansion
    - executor status
    - delivery_state
```

---

## 8. Candidate Acceptance Commands

```yaml id="candidate-acceptance-commands"
acceptance_commands:
  preflight_read_only:
    - git status --short --branch
    - git rev-parse HEAD
    - sha256sum docs/taskbooks/stages/STAGE_03_EXTERNAL_TASKBOOK_IMPORT.md docs/taskbooks/versions/stage-03/VERSION_STAGE_03_V3_2_EXTERNAL_TASKBOOK_VALIDATOR_V1.md
  preview_validation:
    - python -m unittest tests.test_taskbook_import_preview
    - python -m compileall runner/taskbook_import_preview.py
  report_validation:
    - git diff --check -- docs/taskbooks/versions/stage-03/evidence/VERSION_STAGE_03_V3_3_TASKBOOK_IMPORT_PREVIEW_REPORT.md docs/taskbooks/versions/stage-03/evidence/zh-CN/VERSION_STAGE_03_V3_3_TASKBOOK_IMPORT_PREVIEW_REPORT.zh-CN.md
    - rg -n "preview_contract_summary|valid_preview_example|authority_boundary_check|candidate_delta_labeling_check|remaining_risks" docs/taskbooks/versions/stage-03/evidence/VERSION_STAGE_03_V3_3_TASKBOOK_IMPORT_PREVIEW_REPORT.md
```

These commands are candidates for later authorized execution only.

---

## 9. Manual Acceptance Criteria

```yaml id="manual-acceptance"
manual_acceptance:
  reviewer_may_accept_if:
    - preview rejects validator_result values other than pass
    - preview labels all deltas as candidate-only
    - preview lists required Commander decisions before adoption
    - preview does not mutate plan or allowed_files
    - evidence report separates commands_run from commands_not_run
  reviewer_must_not_accept_if:
    - preview treats external taskbook claim as trusted fact
    - preview authorizes adoption
    - preview expands allowed_files
    - preview maps manual_acceptance to delivery_state accepted
```

---

## 10. Stop Conditions

```yaml id="stop-conditions"
stop_conditions:
  must_stop_if:
    - repository_path_is_not_/home/jenn/src/colameta-dev
    - implementation_would_mutate_colameta_plan
    - implementation_requires_/home/jenn/tools/colameta_changes
    - implementation_requires_fetch_pull_push_or_remote_write
    - preview_would_accept_failed_validator_result
    - preview_would_claim_adoption_authority
    - preview_would_claim_delivery_state_accepted
    - required_hashes_do_not_match_declared_parent_hashes
```

---

## 11. Next Version Handoff

```yaml id="next-version-handoff"
next_version_handoff:
  next_version: v3.4 Taskbook-to-Version-Candidate Mapping V1
  handoff_requires:
    - import preview output is candidate-only
    - required Commander decisions are explicit
    - proposed deltas are non-authoritative
  must_not_handoff_as:
    - import_adoption_authorization
    - plan_mutation_authorization
    - execution_authorization
```
