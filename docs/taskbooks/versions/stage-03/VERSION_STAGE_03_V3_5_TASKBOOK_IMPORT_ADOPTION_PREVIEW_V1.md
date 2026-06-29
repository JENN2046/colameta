# Version Taskbook: Stage 3 / v3.5 Taskbook Import Adoption Preview V1

```text id="version-stage-03-v3-5-boundary-banner"
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
  version_id: stage_03_v3_5_taskbook_import_adoption_preview_v1
  version: v3.5
  name: Taskbook Import Adoption Preview V1
  chinese_name: 任务书导入采纳预览 V1
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

`Taskbook Import Adoption Preview V1` = 任务书导入采纳预览 V1。中文意思是：在真正采纳
外部任务书之前，生成一份窄授权请求草稿，列出精确 hash、候选 diff、风险、阻塞项和
Commander 必须确认的事项；它自己不执行采纳。

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
    path: docs/taskbooks/versions/stage-03/VERSION_STAGE_03_V3_4_TASKBOOK_TO_VERSION_CANDIDATE_MAPPING_V1.md
    raw_snapshot_sha256: a1ef7d80d50655dc24b19c23d696cd69a16bbc0fbaa0aa35811b858c41e849b1
    version_id: stage_03_v3_4_taskbook_to_version_candidate_mapping_v1
  stage_2_version_set_confirmation_ref:
    path: docs/taskbooks/versions/stage-02/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_02_VERSIONS.md
    raw_snapshot_sha256: 3de9f207f7a80ce1ec3f2cb374c1f10b4903014be18d0dbe6d2defa1224e8f58
    review_status: hash_specific_freeze_candidate_confirmation_recorded
  supports_project_goal: true
```

v3.5 consumes only v3.4 mapping output. It must generate an adoption preview and
Commander decision request, not perform adoption.

中文解释：v3.5 是 Stage 3 的收束门，只回答“如果要采纳，必须精确授权什么”。

---

## 2. Task Goal

```yaml id="task-goal"
task_goal:
  primary_goal: >
    Define a final adoption preview for imported taskbook candidates. The
    preview must bind source taskbook hash, import preview hash, mapping hash,
    target plan path, candidate diff summary, candidate allowed_files delta,
    blockers, risks, and a Commander decision request. It must not apply the
    adoption.
  minimum_readiness_claim: >
    ColaMeta can prepare a precise, hash-bound adoption request for a mapped
    external taskbook while keeping plan mutation and execution unauthorized.
  gate_question: >
    Can the Commander see the exact adoption request before any plan mutation,
    route transition, or executor dispatch can occur?
  explicit_non_goal: >
    This version is not adoption execution, not plan mutation, not executor
    dispatch, not route transition, not review acceptance, and not delivery
    state accepted.
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
    previous_version_hash: a1ef7d80d50655dc24b19c23d696cd69a16bbc0fbaa0aa35811b858c41e849b1
    stage_2_version_set_confirmation_hash: 3de9f207f7a80ce1ec3f2cb374c1f10b4903014be18d0dbe6d2defa1224e8f58
  task_goal_ref: task_goal.primary_goal
  definition_of_good:
    - adoption preview consumes only mapping_ready inputs
    - adoption preview binds source, preview, and mapping hashes
    - adoption preview lists exact Commander authorization requirements
    - adoption preview marks proposed plan mutation as candidate-only
    - adoption preview does not write .colameta/plan.json or dispatch executor
  allowed_autonomy_after_explicit_authorization:
    - local file inspection
    - narrow adoption preview helper creation or update under declared path
    - focused adoption preview tests
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
    - docs/taskbooks/versions/stage-03/VERSION_STAGE_03_V3_4_TASKBOOK_TO_VERSION_CANDIDATE_MAPPING_V1.md
    - docs/taskbooks/versions/stage-02/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_02_VERSIONS.md
    - runner/**
    - tests/**
  writable_after_separate_execution_authorization:
    - runner/taskbook_import_adoption_preview.py
    - tests/test_taskbook_import_adoption_preview.py
    - docs/taskbooks/versions/stage-03/evidence/VERSION_STAGE_03_V3_5_TASKBOOK_IMPORT_ADOPTION_PREVIEW_REPORT.md
    - docs/taskbooks/versions/stage-03/evidence/zh-CN/VERSION_STAGE_03_V3_5_TASKBOOK_IMPORT_ADOPTION_PREVIEW_REPORT.zh-CN.md
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

## 5. Adoption Preview Contract

```yaml id="adoption-preview-contract"
adoption_preview_contract:
  accepted_input:
    - version_candidate_id
    - mapping_status
    - source_taskbook_hash
    - import_preview_hash
    - mapping_hash
    - candidate_parent_refs
    - candidate_allowed_files
    - required_commander_decisions
  required_output_fields:
    - adoption_preview_id
    - adoption_preview_status
    - source_taskbook_ref
    - import_preview_ref
    - mapping_ref
    - target_plan_path
    - candidate_plan_diff_summary
    - candidate_allowed_files_delta
    - candidate_forbidden_files_summary
    - candidate_acceptance_commands_summary
    - candidate_manual_acceptance_summary
    - required_exact_hash_authorization
    - commander_decision_request
    - blockers
    - risks
    - authority_boundary
  valid_adoption_preview_statuses:
    - adoption_preview_ready
    - adoption_preview_blocked_mapping_not_ready
    - adoption_preview_blocked_plan_scope_conflict
    - adoption_preview_blocked_authority_confusion
  forbidden_output_claims:
    - adoption_executed
    - plan_mutation_authorized
    - allowed_files_expansion_authorized
    - executor_dispatch_authorized
    - delivery_state_accepted
```

`commander_decision_request` = 指挥官决策请求。中文意思是：它只是把 Commander 需要
确认的话术和 hash 列出来，不代表 Commander 已经确认。

---

## 6. Commander Decision Request Minimum

```yaml id="commander-decision-request-minimum"
commander_decision_request_minimum:
  required_fields:
    - target_repository_path
    - current_head
    - source_taskbook_hash
    - import_preview_hash
    - mapping_hash
    - target_plan_path
    - candidate_plan_diff_hash
    - candidate_allowed_files_delta_hash
    - explicit_authorized_actions
    - explicit_unauthorized_actions
    - invalidation_rule
  must_authorize_separately:
    - plan_mutation
    - allowed_files_expansion
    - commit
    - executor_dispatch
    - route_transition
    - remote_write
  must_not_bundle:
    - implementation
    - delivery_state_accepted
    - release_or_deploy
```

---

## 7. Evidence Package Contract

```yaml id="evidence-package-contract"
evidence_package_contract:
  evidence_package_id: stage_03_v3_5_taskbook_import_adoption_preview_evidence
  required_artifacts:
    - adoption_preview_contract_summary
    - mapping_ready_positive_case
    - mapping_blocked_negative_case
    - commander_decision_request_example
    - authority_boundary_check
    - commands_run
    - commands_not_run
    - known_gaps
    - remaining_risks
    - chinese_report_companion
  must_not_include_as_authority:
    - executed adoption
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
    - sha256sum docs/taskbooks/stages/STAGE_03_EXTERNAL_TASKBOOK_IMPORT.md docs/taskbooks/versions/stage-03/VERSION_STAGE_03_V3_4_TASKBOOK_TO_VERSION_CANDIDATE_MAPPING_V1.md
  adoption_preview_validation:
    - python -m unittest tests.test_taskbook_import_adoption_preview
    - python -m compileall runner/taskbook_import_adoption_preview.py
  report_validation:
    - git diff --check -- docs/taskbooks/versions/stage-03/evidence/VERSION_STAGE_03_V3_5_TASKBOOK_IMPORT_ADOPTION_PREVIEW_REPORT.md docs/taskbooks/versions/stage-03/evidence/zh-CN/VERSION_STAGE_03_V3_5_TASKBOOK_IMPORT_ADOPTION_PREVIEW_REPORT.zh-CN.md
    - rg -n "adoption_preview_contract_summary|commander_decision_request_example|authority_boundary_check|remaining_risks" docs/taskbooks/versions/stage-03/evidence/VERSION_STAGE_03_V3_5_TASKBOOK_IMPORT_ADOPTION_PREVIEW_REPORT.md
```

These commands are candidates for later authorized execution only.

---

## 9. Manual Acceptance Criteria

```yaml id="manual-acceptance"
manual_acceptance:
  reviewer_may_accept_if:
    - adoption preview consumes only mapping_ready inputs
    - adoption preview binds source taskbook, import preview, and mapping hashes
    - Commander decision request lists exact authorized and unauthorized actions
    - adoption preview marks plan diff and allowed_files delta as candidate-only
    - evidence report separates commands_run from commands_not_run
  reviewer_must_not_accept_if:
    - adoption preview mutates .colameta/plan.json
    - adoption preview bundles implementation or executor dispatch authority
    - adoption preview treats Commander decision request as confirmation
    - adoption preview maps manual_acceptance to delivery_state accepted
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
    - adoption_preview_would_apply_plan_diff
    - adoption_preview_would_claim_commander_confirmation
    - adoption_preview_would_claim_delivery_state_accepted
    - required_hashes_do_not_match_declared_parent_hashes
```

---

## 11. Stage 3 Set Handoff

```yaml id="stage-3-set-handoff"
stage_3_set_handoff:
  stage_set_readiness_claim: >
    v3.1-v3.5 define the minimum external taskbook import protocol from schema,
    validation, read-only preview, candidate mapping, and adoption preview.
  package_review_requires:
    - all previous_version_ref hashes resolved
    - all Chinese companion source hashes resolved
    - no adoption authority wording
    - no plan mutation authority wording
    - no executor dispatch authority wording
  must_not_handoff_as:
    - import_adoption_authorization
    - plan_mutation_authorization
    - execution_authorization
    - delivery_state_accepted
```
