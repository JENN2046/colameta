# Version Taskbook: Stage 3 / v3.2 External Taskbook Validator V1

```text id="version-stage-03-v3-2-boundary-banner"
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
  version_id: stage_03_v3_2_external_taskbook_validator_v1
  version: v3.2
  name: External Taskbook Validator V1
  chinese_name: 外部任务书校验器 V1
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

`External Taskbook Validator V1` = 外部任务书校验器 V1。中文意思是：读取外部任务书
claim，检查最小字段、hash 权威引用、Master/Stage 绑定、allowed/forbidden 文件、
acceptance commands 和 forbidden authority claims；不通过就 fail closed。

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
    path: docs/taskbooks/versions/stage-03/VERSION_STAGE_03_V3_1_EXTERNAL_TASKBOOK_SCHEMA_V1.md
    raw_snapshot_sha256: 0d92e1d7779db1d89253986cd40c045dc75b25c0b2f31dbb46143d3b5d1f3232
    version_id: stage_03_v3_1_external_taskbook_schema_v1
  stage_2_version_set_confirmation_ref:
    path: docs/taskbooks/versions/stage-02/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_02_VERSIONS.md
    raw_snapshot_sha256: 3de9f207f7a80ce1ec3f2cb374c1f10b4903014be18d0dbe6d2defa1224e8f58
    review_status: hash_specific_freeze_candidate_confirmation_recorded
  supports_project_goal: true
```

v3.2 consumes the v3.1 schema contract. It must reject invalid external
taskbooks; it must not repair them by silently adding missing authority.

中文解释：校验器只能判断“这份外部任务书 claim 是否合格”，不能替用户补授权。

---

## 2. Task Goal

```yaml id="task-goal"
task_goal:
  primary_goal: >
    Define a fail-closed validator for external taskbook claims that checks
    required fields, provenance, hash authority, Master and Stage references,
    allowed_files, forbidden_files, acceptance_commands, manual_acceptance,
    out_of_scope, and forbidden authority claims.
  minimum_readiness_claim: >
    ColaMeta can reject malformed, under-scoped, over-authorizing, or
    hash-confused external taskbook claims before preview or mapping.
  gate_question: >
    Can invalid or authority-confused external taskbooks be rejected without
    mutating plan, expanding scope, or dispatching an executor?
  explicit_non_goal: >
    This version is not import preview, not taskbook mapping, not adoption, not
    plan mutation, not executor dispatch, and not review acceptance.
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
    previous_version_hash: 0d92e1d7779db1d89253986cd40c045dc75b25c0b2f31dbb46143d3b5d1f3232
    stage_2_version_set_confirmation_hash: 3de9f207f7a80ce1ec3f2cb374c1f10b4903014be18d0dbe6d2defa1224e8f58
  task_goal_ref: task_goal.primary_goal
  definition_of_good:
    - validator requires all v3.1 schema fields
    - validator fails closed on missing expected_hash_authority_ref
    - validator fails closed on Master or Stage binding mismatch
    - validator rejects automatic plan mutation and executor authority claims
    - validator reports rejected_fields and rejection_reasons
  allowed_autonomy_after_explicit_authorization:
    - local file inspection
    - narrow validator helper creation or update under declared path
    - focused positive and negative validator tests
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
    - docs/taskbooks/versions/stage-02/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_02_VERSIONS.md
    - runner/**
    - tests/**
  writable_after_separate_execution_authorization:
    - runner/external_taskbook_validator.py
    - tests/test_external_taskbook_validator.py
    - docs/taskbooks/versions/stage-03/evidence/VERSION_STAGE_03_V3_2_EXTERNAL_TASKBOOK_VALIDATOR_REPORT.md
    - docs/taskbooks/versions/stage-03/evidence/zh-CN/VERSION_STAGE_03_V3_2_EXTERNAL_TASKBOOK_VALIDATOR_REPORT.zh-CN.md
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

## 5. Validator Behavior Contract

```yaml id="validator-behavior-contract"
validator_behavior_contract:
  accepted_input:
    - external_taskbook_document
    - expected_master_taskbook_ref
    - expected_stage_taskbook_ref
    - expected_schema_version
  required_outputs:
    - validation_result
    - recognized_fields
    - rejected_fields
    - rejection_reasons
    - known_conflicts
    - normalized_claims_candidate
  fail_closed_when:
    - missing_source_or_provenance
    - missing_external_taskbook_hash
    - missing_expected_hash_authority_ref
    - master_taskbook_ref_missing_or_mismatched
    - stage_taskbook_ref_missing_or_mismatched
    - allowed_files_missing
    - forbidden_files_missing
    - acceptance_commands_missing
    - manual_acceptance_missing
    - out_of_scope_missing
    - claims_plan_mutation_authority
    - claims_executor_dispatch_authority
    - claims_delivery_state_accepted
```

`recognized_fields` = 已识别字段。中文意思是：校验器能看懂哪些字段要列出来。
`rejected_fields` = 被拒字段。中文意思是：不能采信或越权的字段也要列出来。

---

## 6. Evidence Package Contract

```yaml id="evidence-package-contract"
evidence_package_contract:
  evidence_package_id: stage_03_v3_2_external_taskbook_validator_evidence
  required_artifacts:
    - validator_behavior_summary
    - positive_case_result
    - negative_case_results
    - rejected_fields_table
    - authority_confusion_check
    - commands_run
    - commands_not_run
    - known_gaps
    - remaining_risks
    - chinese_report_companion
  must_not_include_as_authority:
    - auto_repaired_missing_authority
    - source reputation alone
    - runtime labels
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
    - sha256sum docs/taskbooks/stages/STAGE_03_EXTERNAL_TASKBOOK_IMPORT.md docs/taskbooks/versions/stage-03/VERSION_STAGE_03_V3_1_EXTERNAL_TASKBOOK_SCHEMA_V1.md
  validator_validation:
    - python -m unittest tests.test_external_taskbook_validator
    - python -m compileall runner/external_taskbook_validator.py
  report_validation:
    - git diff --check -- docs/taskbooks/versions/stage-03/evidence/VERSION_STAGE_03_V3_2_EXTERNAL_TASKBOOK_VALIDATOR_REPORT.md docs/taskbooks/versions/stage-03/evidence/zh-CN/VERSION_STAGE_03_V3_2_EXTERNAL_TASKBOOK_VALIDATOR_REPORT.zh-CN.md
    - rg -n "validator_behavior_summary|negative_case_results|rejected_fields_table|authority_confusion_check|remaining_risks" docs/taskbooks/versions/stage-03/evidence/VERSION_STAGE_03_V3_2_EXTERNAL_TASKBOOK_VALIDATOR_REPORT.md
```

These commands are candidates for later authorized execution only.

---

## 8. Manual Acceptance Criteria

```yaml id="manual-acceptance"
manual_acceptance:
  reviewer_may_accept_if:
    - validator fails closed on missing required fields
    - validator fails closed on missing expected_hash_authority_ref
    - validator rejects plan mutation and executor dispatch claims
    - validator emits rejected_fields and rejection_reasons
    - evidence report separates commands_run from commands_not_run
  reviewer_must_not_accept_if:
    - validator silently fills missing authority
    - validator treats external taskbook as trusted fact
    - validator accepts automatic allowed_files expansion
    - validator maps manual_acceptance to delivery_state accepted
```

---

## 9. Stop Conditions

```yaml id="stop-conditions"
stop_conditions:
  must_stop_if:
    - repository_path_is_not_/home/jenn/src/colameta-dev
    - implementation_would_mutate_colameta_plan
    - implementation_requires_/home/jenn/tools/colameta_changes
    - implementation_requires_fetch_pull_push_or_remote_write
    - validator_would_auto_repair_authority
    - validator_would_claim_execution_authority
    - validator_would_claim_delivery_state_accepted
    - required_hashes_do_not_match_declared_parent_hashes
```

---

## 10. Next Version Handoff

```yaml id="next-version-handoff"
next_version_handoff:
  next_version: v3.3 Taskbook Import Preview V1
  handoff_requires:
    - validator output includes recognized_fields
    - validator output includes rejected_fields and rejection_reasons
    - validator output preserves claim-only boundary
  must_not_handoff_as:
    - import_adoption_authorization
    - plan_mutation_authorization
    - execution_authorization
```
