# Version Taskbook: Stage 3 / v3.4 Taskbook-to-Version-Candidate Mapping V1

```text id="version-stage-03-v3-4-boundary-banner"
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
  version_id: stage_03_v3_4_taskbook_to_version_candidate_mapping_v1
  version: v3.4
  name: Taskbook-to-Version-Candidate Mapping V1
  chinese_name: 任务书到版本候选映射 V1
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

`Taskbook-to-Version-Candidate Mapping V1` = 任务书到版本候选映射 V1。中文意思是：
把 v3.3 的只读预览映射成 ColaMeta 内部 Version candidate 的结构化候选对象；它仍然
不是采用，不会写入 `.colameta/plan.json`。

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
    path: docs/taskbooks/versions/stage-03/VERSION_STAGE_03_V3_3_TASKBOOK_IMPORT_PREVIEW_V1.md
    raw_snapshot_sha256: 8443c5ac8b9927a308da382bd2fd3e39992636b27f059539f0de46f802c78768
    version_id: stage_03_v3_3_taskbook_import_preview_v1
  stage_2_version_set_confirmation_ref:
    path: docs/taskbooks/versions/stage-02/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_02_VERSIONS.md
    raw_snapshot_sha256: 3de9f207f7a80ce1ec3f2cb374c1f10b4903014be18d0dbe6d2defa1224e8f58
    review_status: hash_specific_freeze_candidate_confirmation_recorded
  supports_project_goal: true
```

v3.4 consumes only v3.3 import preview output. It must not map a blocked preview,
and it must not write the mapped candidate into the plan.

中文解释：映射是“把外部说法翻译成 ColaMeta 内部候选格式”，不是“已经采纳”。

---

## 2. Task Goal

```yaml id="task-goal"
task_goal:
  primary_goal: >
    Define the mapping from a valid import preview to a ColaMeta Version
    candidate object. The mapping must preserve source hash, parent bindings,
    candidate version identity, candidate allowed_files, forbidden files,
    acceptance command candidates, manual acceptance requirements, evidence
    requirements, known gaps, and required Commander decisions.
  minimum_readiness_claim: >
    ColaMeta can represent an imported taskbook as an internal Version
    candidate without treating it as a committed plan item or executable route.
  gate_question: >
    Can a validated and previewed external taskbook be translated into an
    internal candidate object while preserving all authority boundaries?
  explicit_non_goal: >
    This version is not adoption, not plan insertion, not allowed_files
    expansion, not executor dispatch, and not review acceptance.
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
    previous_version_hash: 8443c5ac8b9927a308da382bd2fd3e39992636b27f059539f0de46f802c78768
    stage_2_version_set_confirmation_hash: 3de9f207f7a80ce1ec3f2cb374c1f10b4903014be18d0dbe6d2defa1224e8f58
  task_goal_ref: task_goal.primary_goal
  definition_of_good:
    - mapping consumes only preview_ready inputs
    - mapping preserves source taskbook hash and preview hash
    - mapping marks every output as candidate-only
    - mapping rejects plan insertion and executor authority claims
    - mapping lists adoption blockers and required Commander decisions
  allowed_autonomy_after_explicit_authorization:
    - local file inspection
    - narrow mapping helper creation or update under declared path
    - focused mapping tests
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
    - docs/taskbooks/versions/stage-03/VERSION_STAGE_03_V3_3_TASKBOOK_IMPORT_PREVIEW_V1.md
    - docs/taskbooks/versions/stage-02/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_02_VERSIONS.md
    - runner/**
    - tests/**
  writable_after_separate_execution_authorization:
    - runner/taskbook_version_candidate_mapping.py
    - tests/test_taskbook_version_candidate_mapping.py
    - docs/taskbooks/versions/stage-03/evidence/VERSION_STAGE_03_V3_4_TASKBOOK_TO_VERSION_CANDIDATE_MAPPING_REPORT.md
    - docs/taskbooks/versions/stage-03/evidence/zh-CN/VERSION_STAGE_03_V3_4_TASKBOOK_TO_VERSION_CANDIDATE_MAPPING_REPORT.zh-CN.md
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

## 5. Mapping Contract

```yaml id="mapping-contract"
mapping_contract:
  accepted_input:
    - import_preview_id
    - import_preview_hash
    - preview_status
    - source_taskbook_hash
    - normalized_claims_candidate
    - required_commander_decisions
  required_output_fields:
    - version_candidate_id
    - mapping_status
    - source_taskbook_ref
    - import_preview_ref
    - candidate_parent_refs
    - candidate_version_identity
    - candidate_allowed_files
    - candidate_forbidden_files
    - candidate_acceptance_commands
    - candidate_manual_acceptance
    - candidate_evidence_requirements
    - candidate_out_of_scope
    - adoption_blockers
    - required_commander_decisions
    - authority_boundary
  valid_mapping_statuses:
    - mapping_ready
    - mapping_blocked_preview_not_ready
    - mapping_blocked_scope_conflict
    - mapping_blocked_authority_confusion
  forbidden_output_claims:
    - plan_item_inserted
    - plan_mutation_authorized
    - allowed_files_expansion_authorized
    - executor_dispatch_authorized
    - delivery_state_accepted
```

`version_candidate_id` = 版本候选 ID。中文意思是：候选对象可以有内部编号，但这个编号
不表示它已经进入计划。

---

## 6. Mapping Preservation Rules

```yaml id="mapping-preservation-rules"
mapping_preservation_rules:
  must_preserve_exactly:
    - source_taskbook_hash
    - import_preview_hash
    - master_taskbook_ref
    - stage_taskbook_ref
    - proposed_version_identity
    - candidate_scope
    - candidate_allowed_files
    - candidate_forbidden_files
    - manual_acceptance_requirements
  may_normalize:
    - field_order
    - whitespace
    - display_labels
  must_not_normalize_away:
    - authority_boundary
    - blockers
    - known_gaps
    - rejected_fields
    - required_commander_decisions
```

---

## 7. Evidence Package Contract

```yaml id="evidence-package-contract"
evidence_package_contract:
  evidence_package_id: stage_03_v3_4_taskbook_to_version_candidate_mapping_evidence
  required_artifacts:
    - mapping_contract_summary
    - preview_ready_positive_case
    - preview_blocked_negative_case
    - preservation_check
    - authority_boundary_check
    - commands_run
    - commands_not_run
    - known_gaps
    - remaining_risks
    - chinese_report_companion
  must_not_include_as_authority:
    - plan insertion
    - allowed_files expansion
    - executor status
    - reviewer acceptance
    - delivery_state
```

---

## 8. Candidate Acceptance Commands

```yaml id="candidate-acceptance-commands"
acceptance_commands:
  preflight_read_only:
    - git status --short --branch
    - git rev-parse HEAD
    - sha256sum docs/taskbooks/stages/STAGE_03_EXTERNAL_TASKBOOK_IMPORT.md docs/taskbooks/versions/stage-03/VERSION_STAGE_03_V3_3_TASKBOOK_IMPORT_PREVIEW_V1.md
  mapping_validation:
    - python -m unittest tests.test_taskbook_version_candidate_mapping
    - python -m compileall runner/taskbook_version_candidate_mapping.py
  report_validation:
    - git diff --check -- docs/taskbooks/versions/stage-03/evidence/VERSION_STAGE_03_V3_4_TASKBOOK_TO_VERSION_CANDIDATE_MAPPING_REPORT.md docs/taskbooks/versions/stage-03/evidence/zh-CN/VERSION_STAGE_03_V3_4_TASKBOOK_TO_VERSION_CANDIDATE_MAPPING_REPORT.zh-CN.md
    - rg -n "mapping_contract_summary|preview_ready_positive_case|preview_blocked_negative_case|preservation_check|remaining_risks" docs/taskbooks/versions/stage-03/evidence/VERSION_STAGE_03_V3_4_TASKBOOK_TO_VERSION_CANDIDATE_MAPPING_REPORT.md
```

These commands are candidates for later authorized execution only.

---

## 9. Manual Acceptance Criteria

```yaml id="manual-acceptance"
manual_acceptance:
  reviewer_may_accept_if:
    - mapping consumes only preview_ready inputs
    - mapping preserves source and preview hashes
    - mapping marks output as candidate-only
    - mapping rejects plan insertion and executor dispatch claims
    - evidence report separates commands_run from commands_not_run
  reviewer_must_not_accept_if:
    - mapping consumes blocked preview output
    - mapping drops blockers or known gaps
    - mapping writes to .colameta/plan.json
    - mapping maps manual_acceptance to delivery_state accepted
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
    - mapping_would_consume_blocked_preview
    - mapping_would_claim_plan_insertion_authority
    - mapping_would_claim_delivery_state_accepted
    - required_hashes_do_not_match_declared_parent_hashes
```

---

## 11. Next Version Handoff

```yaml id="next-version-handoff"
next_version_handoff:
  next_version: v3.5 Taskbook Import Adoption Preview V1
  handoff_requires:
    - version candidate mapping is candidate-only
    - source taskbook hash and preview hash are preserved
    - adoption blockers and Commander decisions are explicit
  must_not_handoff_as:
    - import_adoption_authorization
    - plan_mutation_authorization
    - execution_authorization
```
