# Version Taskbook: Stage 5 / v5.1 Reviewer Handoff Schema V1

```text id="version-stage-05-v5-1-boundary-banner"
VERSION TASKBOOK DRAFT ONLY.
This document defines a candidate Version Execution Taskbook for Stage 5. It
does not authorize implementation, code edits, commit, push, fetch, pull,
executor run, route transition, review acceptance, Delivery State Gate
transition, release, deploy, or accepted delivery state.
```

```yaml id="version-taskbook-summary"
version_execution_taskbook:
  document_type: version_execution_taskbook
  schema_version: version_execution_taskbook.discussion_draft.v1
  version_id: stage_05_v5_1_reviewer_handoff_schema_v1
  version: v5.1
  name: Reviewer Handoff Schema V1
  chinese_name: 审查者交接模式 V1
  parent_stage_id: stage_05_reviewer_handoff_package
  parent_stage_name: Reviewer Handoff Package
  status: discussion_draft
  authority_status: planning_reference_only
  execution_authorization_status: not_authorized
  dispatch_status: not_authorized
  executor_run_authorized: false
  created_from_head: 9ca292d
  created_from_head_full: 9ca292d6f8de44cdbeebed00692febef8f733171
  created_from_head_meaning: historical_creation_baseline_not_execution_or_freeze_snapshot
  created_from_head_subject: "docs: record stage 4 version freeze confirmation"
  origin_main_observed_local_tracking_ref: 018ff63
  local_tracking_ref_sync_status_at_creation: local_ahead_remote_tracking_ref
  local_ahead_origin_main_at_creation: 37
```

`Reviewer Handoff Schema V1` = 审查者交接模式 V1。中文意思是：先把交给
Reviewer 的 package 字段边界定义清楚，让后续 generator 只能填充材料，不能偷偷
替 Reviewer 下结论。

---

## 1. Parent Binding

```yaml id="parent-binding"
parent_binding:
  master_taskbook_ref:
    path: PROJECT_MASTER_TASKBOOK.md
    raw_snapshot_sha256: 1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34
    review_status: freeze_candidate_confirmed_for_exact_hash
  stage_taskbook_ref:
    path: docs/taskbooks/stages/STAGE_05_REVIEWER_HANDOFF_PACKAGE.md
    raw_snapshot_sha256: 532d36ab5c99d37c1a88b094fbe9c37bdc342e17e572447468a0918afbdce43c
    stage_id: stage_05_reviewer_handoff_package
  stage_4_version_set_confirmation_ref:
    path: docs/taskbooks/versions/stage-04/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_04_VERSIONS.md
    raw_snapshot_sha256: b1da3ea7e105d48f5018c5be17bb59e0164779bfe06e8a36f8e7265b62031c6f
    review_status: hash_specific_freeze_candidate_confirmation_recorded
  supports_project_goal: true
```

v5.1 starts Stage 5. It consumes the Stage 4 confirmation record as an upstream
planning anchor, but it does not execute anything and does not complete review.

中文解释：Stage 4 把“证据从哪里来”定清楚；Stage 5 从“交给审查者的包长什么样”
开始。

---

## 2. Task Goal

```yaml id="task-goal"
task_goal:
  primary_goal: >
    Define the minimum machine-checkable ReviewerHandoffPackage schema that
    binds to Master, Stage, Version Taskbook, Stage 4 audit/evidence package,
    changed files, validation truth, scope evidence, known risks, reviewer
    questions, and allowed review decision values.
  minimum_readiness_claim: >
    ColaMeta can describe exactly what a reviewer handoff package must contain
    without implying review acceptance or Delivery State Gate transition.
  gate_question: >
    Can a generated handoff package be validated for completeness before a
    Reviewer is asked to decide?
  explicit_non_goal: >
    This version is not a generator implementation, not a Reviewer replacement,
    not review acceptance, not state transition, and not delivery accepted.
```

---

## 3. ReviewerHandoffPackage Minimum Contract

```yaml id="reviewer-handoff-package-minimum-contract"
reviewer_handoff_package_minimum_contract:
  required_fields:
    - handoff_package_id
    - handoff_schema_version
    - master_taskbook_ref
    - stage_taskbook_ref
    - version_taskbook_ref
    - stage_4_audit_package_ref
    - execution_receipt_refs
    - claim_summary
    - changed_files
    - validation_truth
    - scope_evidence
    - known_risks
    - known_gaps
    - reviewer_questions
    - allowed_review_decisions
    - forbidden_generator_claims
    - generated_at
  allowed_review_decisions:
    - ACCEPT
    - NEEDS_FIX
    - PLAN_ADJUST
    - ABORT
  forbidden_generator_claims:
    - recommend_accept
    - delivery_state_accepted
    - review_acceptance_recorded
    - commander_authorized_next_route
    - scope_aligned_without_reviewer_judgment
```

`allowed_review_decisions` = 允许的审查决策选项。中文意思是：Reviewer 可以从这些
选项里做判断，但 generator 不能推荐 `ACCEPT`，也不能把选项写成已经接受。

---

## 4. Candidate Execution Envelope

```yaml id="candidate-execution-envelope"
execution_envelope_candidate:
  authorization_status: not_authorized
  parent_hashes:
    master_taskbook_hash: 1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34
    stage_taskbook_hash: 532d36ab5c99d37c1a88b094fbe9c37bdc342e17e572447468a0918afbdce43c
    stage_4_version_set_confirmation_hash: b1da3ea7e105d48f5018c5be17bb59e0164779bfe06e8a36f8e7265b62031c6f
  task_goal_ref: task_goal.primary_goal
  definition_of_good:
    - schema is explicit and machine-checkable
    - schema binds to Master Stage Version and Stage 4 evidence package
    - schema separates review package generation from review decision records
    - schema carries known risks and known gaps
    - schema forbids generator acceptance claims
```

---

## 5. Allowed Files And Mutations

```yaml id="allowed-files-and-mutations"
allowed_files:
  read_only:
    - PROJECT_MASTER_TASKBOOK.md
    - docs/taskbooks/stages/STAGE_05_REVIEWER_HANDOFF_PACKAGE.md
    - docs/taskbooks/versions/stage-04/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_04_VERSIONS.md
    - docs/taskbooks/versions/stage-04/**
    - runner/**
    - tests/**
  writable_after_separate_execution_authorization:
    - runner/reviewer_handoff_schema.py
    - tests/test_reviewer_handoff_schema.py
    - docs/taskbooks/versions/stage-05/evidence/VERSION_STAGE_05_V5_1_REVIEWER_HANDOFF_SCHEMA_REPORT.md
    - docs/taskbooks/versions/stage-05/evidence/zh-CN/VERSION_STAGE_05_V5_1_REVIEWER_HANDOFF_SCHEMA_REPORT.zh-CN.md
forbidden_files:
  mutation_targets:
    - /home/jenn/tools/colameta/**
    - PROJECT_MASTER_TASKBOOK.md
    - PROJECT_MASTER_TASKBOOK.zh-CN.md
    - docs/taskbooks/stages/**
    - docs/taskbooks/versions/stage-00/**
    - docs/taskbooks/versions/stage-01/**
    - docs/taskbooks/versions/stage-02/**
    - docs/taskbooks/versions/stage-03/**
    - docs/taskbooks/versions/stage-04/**
    - .colameta/plan.json
    - .colameta/state.json
    - .colameta/runtime/**
    - .git/**
```

---

## 6. Rejection Rules

```yaml id="rejection-rules"
rejection_rules:
  reject_when:
    - master_taskbook_ref_missing_or_mismatched
    - stage_taskbook_ref_missing_or_mismatched
    - version_taskbook_ref_missing
    - stage_4_audit_package_ref_missing
    - validation_truth_missing
    - changed_files_missing
    - scope_evidence_missing
    - reviewer_questions_missing
    - allowed_review_decisions_missing_or_expanded
    - generator_recommends_accept
    - package_claims_delivery_state_accepted
    - package_claims_review_acceptance_recorded
```

---

## 7. Evidence Package Contract

```yaml id="evidence-package-contract"
evidence_package_contract:
  evidence_report_required: true
  evidence_report_must_include:
    - schema_field_inventory
    - required_field_validation_examples
    - rejection_case_examples
    - forbidden_claim_check_examples
    - commands_run
    - commands_not_run
    - remaining_risks
  evidence_report_must_not_claim:
    - implementation_completed_without_execution_authorization
    - review_decision_created
    - delivery_state_transitioned
```

---

## 8. Manual Acceptance Criteria For This Version

```yaml id="manual-acceptance-criteria"
manual_acceptance_criteria:
  can_be_accepted_for_next_step_when:
    - schema requires Master Stage Version and Stage 4 evidence bindings
    - schema requires validation truth and scope evidence
    - schema keeps allowed decisions to ACCEPT NEEDS_FIX PLAN_ADJUST ABORT
    - schema forbids generator recommendation of ACCEPT
    - schema distinguishes handoff package from ReviewDecision and GateEvent
  must_return_to_draft_when:
    - package schema can be read as review acceptance
    - package schema can mutate delivery state
    - package schema allows decision option expansion without Commander review
    - Chinese companion changes the authority boundary
```

---

## 9. Next Version Handoff

```yaml id="next-version-handoff"
next_version_handoff:
  next_version: v5.2
  next_version_name: Reviewer Handoff Generator V1
  handoff_condition: >
    v5.2 may define a generator only after v5.1 defines the minimum package
    schema and rejection rules.
  still_not_authorized:
    - implementation
    - executor_run
    - review_acceptance
    - delivery_state_transition
```

中文解释：先把“包的格式”锁住，再写“怎么生成这个包”。格式本身不等于审查通过。
