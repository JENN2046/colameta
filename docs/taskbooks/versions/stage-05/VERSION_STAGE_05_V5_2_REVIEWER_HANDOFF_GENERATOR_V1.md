# Version Taskbook: Stage 5 / v5.2 Reviewer Handoff Generator V1

```text id="version-stage-05-v5-2-boundary-banner"
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
  version_id: stage_05_v5_2_reviewer_handoff_generator_v1
  version: v5.2
  name: Reviewer Handoff Generator V1
  chinese_name: 审查者交接生成器 V1
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

`Reviewer Handoff Generator V1` = 审查者交接生成器 V1。中文意思是：把已有的
Stage 4 audit/evidence package 转换成审查者可读的 handoff package，但只生成材料，
不推荐结论，不写 ReviewDecision，也不改 Delivery State Gate。

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
  previous_version_ref:
    path: docs/taskbooks/versions/stage-05/VERSION_STAGE_05_V5_1_REVIEWER_HANDOFF_SCHEMA_V1.md
    raw_snapshot_sha256: 7c1d5d95f02a1ff7b22712678d05e50a88fff00f5f43af0969d0292920d50e54
    version_id: stage_05_v5_1_reviewer_handoff_schema_v1
  stage_4_version_set_confirmation_ref:
    path: docs/taskbooks/versions/stage-04/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_04_VERSIONS.md
    raw_snapshot_sha256: b1da3ea7e105d48f5018c5be17bb59e0164779bfe06e8a36f8e7265b62031c6f
    review_status: hash_specific_freeze_candidate_confirmation_recorded
  supports_project_goal: true
```

---

## 2. Task Goal

```yaml id="task-goal"
task_goal:
  primary_goal: >
    Define a minimum ReviewerHandoffPackage generator that reads the v5.1 schema
    and a taskbook-bound Stage 4 audit package, then emits a complete review
    package with claim summary, changed files, validation truth, scope evidence,
    known risks, known gaps, reviewer questions, and allowed review decision
    options.
  minimum_readiness_claim: >
    ColaMeta can prepare review materials from bounded execution evidence
    without making the review decision for the Reviewer.
  gate_question: >
    Can the generator produce a complete handoff package while preserving all
    authority boundaries from v5.1?
  explicit_non_goal: >
    This version is not ReviewDecision creation, not GateEvent emission, not
    Commander authorization, not state transition, and not accepted delivery.
```

---

## 3. Generator Contract

```yaml id="reviewer-handoff-generator-contract"
reviewer_handoff_generator_contract:
  required_inputs:
    - reviewer_handoff_schema_ref
    - master_taskbook_ref
    - stage_taskbook_ref
    - version_taskbook_ref
    - stage_4_audit_package_ref
    - validation_truth_source_ref
    - changed_files_source_ref
    - scope_evidence_source_ref
  required_outputs:
    - reviewer_handoff_package
    - generation_summary
    - missing_input_report
    - forbidden_claim_check
  required_behavior:
    - preserve_exact_allowed_review_decisions
    - preserve_known_risks
    - preserve_known_gaps
    - preserve_validation_truth_without_relabeling_it_as_acceptance
    - surface missing evidence as blocked_for_reviewer_handoff
    - ask reviewer to judge drift
  forbidden_behavior:
    - recommend_accept
    - infer_review_decision
    - create_review_decision_record
    - emit_gate_event
    - mutate_delivery_state
    - hide_validation_failure
```

`blocked_for_reviewer_handoff` = 审查交接受阻。中文意思是：材料不够，不能把包交给
Reviewer；这不是 delivery state 的 blocked，也不是最终失败。

---

## 4. Candidate Execution Envelope

```yaml id="candidate-execution-envelope"
execution_envelope_candidate:
  authorization_status: not_authorized
  parent_hashes:
    master_taskbook_hash: 1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34
    stage_taskbook_hash: 532d36ab5c99d37c1a88b094fbe9c37bdc342e17e572447468a0918afbdce43c
    previous_version_hash: 7c1d5d95f02a1ff7b22712678d05e50a88fff00f5f43af0969d0292920d50e54
    stage_4_version_set_confirmation_hash: b1da3ea7e105d48f5018c5be17bb59e0164779bfe06e8a36f8e7265b62031c6f
  task_goal_ref: task_goal.primary_goal
  definition_of_good:
    - generator consumes schema instead of inventing fields
    - generator fails closed on missing evidence
    - generator preserves validation truth and scope evidence
    - generator does not recommend ACCEPT
    - generator does not create ReviewDecision or GateEvent objects
```

---

## 5. Allowed Files And Mutations

```yaml id="allowed-files-and-mutations"
allowed_files:
  read_only:
    - PROJECT_MASTER_TASKBOOK.md
    - docs/taskbooks/stages/STAGE_05_REVIEWER_HANDOFF_PACKAGE.md
    - docs/taskbooks/versions/stage-05/VERSION_STAGE_05_V5_1_REVIEWER_HANDOFF_SCHEMA_V1.md
    - docs/taskbooks/versions/stage-04/**
    - runner/**
    - tests/**
  writable_after_separate_execution_authorization:
    - runner/reviewer_handoff_generator.py
    - tests/test_reviewer_handoff_generator.py
    - docs/taskbooks/versions/stage-05/evidence/VERSION_STAGE_05_V5_2_REVIEWER_HANDOFF_GENERATOR_REPORT.md
    - docs/taskbooks/versions/stage-05/evidence/zh-CN/VERSION_STAGE_05_V5_2_REVIEWER_HANDOFF_GENERATOR_REPORT.zh-CN.md
forbidden_files:
  mutation_targets:
    - /home/jenn/tools/colameta/**
    - PROJECT_MASTER_TASKBOOK.md
    - docs/taskbooks/stages/**
    - docs/taskbooks/versions/stage-00/**
    - docs/taskbooks/versions/stage-01/**
    - docs/taskbooks/versions/stage-02/**
    - docs/taskbooks/versions/stage-03/**
    - docs/taskbooks/versions/stage-04/**
    - .colameta/plan.json
    - .colameta/state.json
    - .git/**
```

---

## 6. Rejection Rules

```yaml id="rejection-rules"
rejection_rules:
  reject_when:
    - schema_ref_missing_or_mismatched
    - stage_4_audit_package_ref_missing
    - validation_truth_unknown
    - changed_files_unknown
    - scope_evidence_missing
    - allowed_review_decisions_expanded
    - generator_output_contains_accept_recommendation
    - generator_output_contains_delivery_state_transition
    - generator_output_contains_review_decision_record
    - generator_output_hides_known_risks
```

---

## 7. Evidence Package Contract

```yaml id="evidence-package-contract"
evidence_package_contract:
  evidence_report_required: true
  evidence_report_must_include:
    - generator_input_inventory
    - generator_output_example
    - missing_input_behavior
    - forbidden_claim_check
    - reviewer_decision_boundary_check
    - commands_run
    - commands_not_run
    - remaining_risks
  evidence_report_must_not_claim:
    - reviewer_decision_created
    - gate_event_emitted
    - accepted_delivery_state
```

---

## 8. Manual Acceptance Criteria For This Version

```yaml id="manual-acceptance-criteria"
manual_acceptance_criteria:
  can_be_accepted_for_next_step_when:
    - generator fills v5_1 schema fields from bound inputs
    - generator fails closed when required evidence is missing
    - generator preserves allowed decisions without adding options
    - generator keeps ACCEPT as reviewer-selectable only
    - generator output remains separate from ReviewDecision and GateEvent
  must_return_to_draft_when:
    - generator recommends ACCEPT
    - generator converts validation pass into review acceptance
    - generator can mutate delivery state
    - generator hides missing evidence or risk
```

---

## 9. Next Version Handoff

```yaml id="next-version-handoff"
next_version_handoff:
  next_version: v5.3
  next_version_name: Alignment Questions V1
  handoff_condition: >
    v5.3 may define project-goal alignment questions only after v5.2 preserves
    the handoff package boundary.
  still_not_authorized:
    - implementation
    - executor_run
    - review_acceptance
    - delivery_state_transition
```

中文解释：v5.2 是“装包机器”，不是“审查官”。它只能把材料装完整，不能代替判断。
