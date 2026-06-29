# Version Taskbook: Stage 5 / v5.5 Reviewer Package Report Surface V1

```text id="version-stage-05-v5-5-boundary-banner"
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
  version_id: stage_05_v5_5_reviewer_package_report_surface_v1
  version: v5.5
  name: Reviewer Package Report Surface V1
  chinese_name: 审查包报告展示面 V1
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

`Reviewer Package Report Surface V1` = 审查包报告展示面 V1。中文意思是：把 Stage 5
生成的审查材料整理成 Reviewer 能读、能判断、能选择决策选项的报告表面；它不是
Reviewer 的决定本身。

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
    path: docs/taskbooks/versions/stage-05/VERSION_STAGE_05_V5_4_DRIFT_QUESTION_PACK_V1.md
    raw_snapshot_sha256: 7ba2f150461cc03cfcce3068c6e9a13925494eb1282036962324904335418c39
    version_id: stage_05_v5_4_drift_question_pack_v1
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
    Define the minimum reviewer-facing report surface for the Stage 5 handoff
    package, including summary, evidence inventory, validation truth, changed
    files, alignment questions, drift questions, known risks, known gaps, and
    allowed review decision options.
  minimum_readiness_claim: >
    ColaMeta can present a self-contained review package to a Reviewer without
    converting presentation into review acceptance.
  gate_question: >
    Can a Reviewer understand the task, evidence, risks, and allowed decisions
    without reconstructing the whole thread?
  explicit_non_goal: >
    This version is not review UI finalization, not review decision submission,
    not GateEvent emission, not release, and not accepted delivery state.
```

---

## 3. Report Surface Contract

```yaml id="reviewer-package-report-surface-contract"
reviewer_package_report_surface_contract:
  required_sections:
    - package_identity
    - binding_summary
    - task_goal_summary
    - claim_summary
    - changed_files
    - validation_truth
    - scope_evidence
    - alignment_questions
    - drift_questions
    - known_risks
    - known_gaps
    - allowed_review_decisions
    - non_authority_notice
  allowed_review_decisions:
    - ACCEPT
    - NEEDS_FIX
    - PLAN_ADJUST
    - ABORT
  required_non_authority_notice:
    - report_surface_is_not_review_decision
    - report_surface_is_not_delivery_state_transition
    - report_surface_is_not_commander_authorization
    - report_surface_is_not_executor_authorization
  forbidden_presentation_patterns:
    - highlighted_accept_as_recommended
    - hidden_needs_fix_or_plan_adjust
    - validation_pass_labelled_as_accepted
    - no_risk_summary_when_risks_exist
```

`Report Surface` = 报告展示面。中文意思是：审查者看到的报告结构和字段顺序，不是
审查系统的权力来源。

---

## 4. Minimum Report Layout

```yaml id="minimum-report-layout"
minimum_report_layout:
  package_identity:
    must_show:
      - handoff_package_id
      - generated_at
      - source_refs
  binding_summary:
    must_show:
      - master_taskbook_ref
      - stage_taskbook_ref
      - version_taskbook_ref
      - stage_4_audit_package_ref
  review_body:
    must_show:
      - claim_summary
      - evidence_inventory
      - changed_files
      - validation_truth
      - scope_evidence
      - known_risks
      - known_gaps
  reviewer_prompts:
    must_show:
      - alignment_questions
      - drift_questions
      - allowed_review_decisions
  boundary_footer:
    must_show:
      - not_review_decision
      - not_delivery_state_transition
      - not_commit_or_push_authorization
      - not_executor_authorization
```

---

## 5. Stage 5 Set Handoff

```yaml id="stage-5-set-handoff"
stage_5_set_handoff:
  stage_set_readiness_claim: >
    v5.1-v5.5 define the minimum reviewer handoff package protocol from schema,
    generator, alignment questions, drift questions, and reviewer-facing report
    surface.
  package_review_requires:
    - all previous_version_ref hashes resolved
    - all Chinese companion source hashes resolved
    - no generator ACCEPT recommendation wording
    - no ReviewDecision creation authority wording
    - no GateEvent emission authority wording
    - no delivery_state accepted wording
  must_not_handoff_as:
    - review_acceptance
    - reviewer_decision_record
    - delivery_state_accepted
    - next_route_authorization
```

---

## 6. Candidate Execution Envelope

```yaml id="candidate-execution-envelope"
execution_envelope_candidate:
  authorization_status: not_authorized
  parent_hashes:
    master_taskbook_hash: 1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34
    stage_taskbook_hash: 532d36ab5c99d37c1a88b094fbe9c37bdc342e17e572447468a0918afbdce43c
    previous_version_hash: 7ba2f150461cc03cfcce3068c6e9a13925494eb1282036962324904335418c39
    stage_4_version_set_confirmation_hash: b1da3ea7e105d48f5018c5be17bb59e0164779bfe06e8a36f8e7265b62031c6f
  task_goal_ref: task_goal.primary_goal
  definition_of_good:
    - report surface shows bindings evidence validation risk and questions
    - report surface keeps all decision options visible
    - report surface does not recommend ACCEPT
    - report surface includes explicit non-authority notice
    - report surface prepares Stage 6 feedback intake without starting it
```

---

## 7. Allowed Files And Mutations

```yaml id="allowed-files-and-mutations"
allowed_files:
  read_only:
    - PROJECT_MASTER_TASKBOOK.md
    - docs/taskbooks/stages/STAGE_05_REVIEWER_HANDOFF_PACKAGE.md
    - docs/taskbooks/versions/stage-05/**
    - docs/taskbooks/versions/stage-04/**
    - runner/**
    - tests/**
  writable_after_separate_execution_authorization:
    - runner/reviewer_package_report_surface.py
    - tests/test_reviewer_package_report_surface.py
    - docs/taskbooks/versions/stage-05/evidence/VERSION_STAGE_05_V5_5_REVIEWER_PACKAGE_REPORT_SURFACE_REPORT.md
    - docs/taskbooks/versions/stage-05/evidence/zh-CN/VERSION_STAGE_05_V5_5_REVIEWER_PACKAGE_REPORT_SURFACE_REPORT.zh-CN.md
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

## 8. Rejection Rules

```yaml id="rejection-rules"
rejection_rules:
  reject_when:
    - report_surface_missing_binding_summary
    - report_surface_missing_validation_truth
    - report_surface_missing_scope_evidence
    - report_surface_missing_alignment_or_drift_questions
    - report_surface_recommends_accept
    - report_surface_hides_needs_fix_or_plan_adjust
    - report_surface_claims_review_decision_recorded
    - report_surface_claims_delivery_state_transition
```

---

## 9. Evidence Package Contract

```yaml id="evidence-package-contract"
evidence_package_contract:
  evidence_report_required: true
  evidence_report_must_include:
    - report_section_inventory
    - decision_option_visibility_check
    - non_authority_notice_check
    - validation_truth_rendering_check
    - risk_and_gap_rendering_check
    - commands_run
    - commands_not_run
    - remaining_risks
  evidence_report_must_not_claim:
    - reviewer_decision_created
    - gate_event_emitted
    - delivery_state_accepted
```

---

## 10. Manual Acceptance Criteria For This Version

```yaml id="manual-acceptance-criteria"
manual_acceptance_criteria:
  can_be_accepted_for_next_step_when:
    - report surface is self-contained enough for Reviewer judgment
    - report surface keeps all four review decisions visible and equal
    - report surface names risks gaps and unclear items
    - report surface clearly states it is not ReviewDecision or GateEvent
  must_return_to_draft_when:
    - report makes ACCEPT look recommended
    - report hides risks or gaps
    - report turns validation pass into accepted state
    - Chinese companion changes the non-authority boundary
```

---

## 11. Next Stage Handoff

```yaml id="next-stage-handoff"
next_stage_handoff:
  next_stage: Stage 6
  next_stage_name: Review Feedback Intake
  handoff_condition: >
    Stage 6 may intake Reviewer feedback only after Stage 5 can present a
    self-contained handoff package without claiming review acceptance.
  still_not_authorized:
    - implementation
    - executor_run
    - review_acceptance
    - delivery_state_transition
    - route_transition
```

中文解释：v5.5 是“把审查材料摆到桌上”，不是“替审查者盖章”。Stage 6 只能在这个
边界清楚之后，接收真正的审查反馈。
