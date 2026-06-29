# Version Taskbook: Stage 5 / v5.4 Drift Question Pack V1

```text id="version-stage-05-v5-4-boundary-banner"
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
  version_id: stage_05_v5_4_drift_question_pack_v1
  version: v5.4
  name: Drift Question Pack V1
  chinese_name: 漂移问题包 V1
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

`Drift Question Pack V1` = 漂移问题包 V1。中文意思是：专门让 Reviewer 判断任务是否
偏离目标、范围、授权、证据或用户意图。它只提出漂移检查问题，不替 Reviewer 判定
“有漂移”或“无漂移”。

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
    path: docs/taskbooks/versions/stage-05/VERSION_STAGE_05_V5_3_ALIGNMENT_QUESTIONS_V1.md
    raw_snapshot_sha256: 8e61482234cd2493463214649366b8b7d2455b2ea1d17777eea4bc4a1c04b98c
    version_id: stage_05_v5_3_alignment_questions_v1
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
    Define the minimum drift question pack that a reviewer handoff package must
    include so the Reviewer can detect project-goal drift, scope drift,
    authority drift, evidence drift, validation drift, and implementation-risk
    drift.
  minimum_readiness_claim: >
    ColaMeta can surface drift risks for review without self-certifying that no
    drift exists.
  gate_question: >
    Can drift be made visible enough for Reviewer judgment without becoming an
    automatic review decision?
  explicit_non_goal: >
    This version is not drift verdict automation, not automatic PLAN_ADJUST,
    not automatic NEEDS_FIX, not review acceptance, and not state transition.
```

---

## 3. Drift Question Contract

```yaml id="drift-question-contract"
drift_question_contract:
  required_drift_groups:
    - project_goal_drift
    - scope_drift
    - authority_drift
    - evidence_drift
    - validation_drift
    - risk_drift
  required_question_fields:
    - drift_question_id
    - drift_type
    - question_text
    - expected_reference
    - observed_evidence_refs
    - reviewer_answer_options
    - unresolved_followup_prompt
  reviewer_answer_options:
    - NO_DRIFT_VISIBLE
    - DRIFT_VISIBLE
    - UNCLEAR
    - NOT_APPLICABLE
  forbidden_question_behavior:
    - generator_marks_no_drift_by_default
    - generator_converts_drift_to_review_decision
    - generator_hides_unclear
    - generator_drops_authority_drift_questions
```

`authority_drift` = 权限漂移。中文意思是：检查实际动作、文本或证据有没有越过授权
边界，例如把 package 当成 commit、push、executor、review acceptance 或 accepted。

---

## 4. Required Drift Questions

```yaml id="required-drift-questions"
required_drift_questions:
  project_goal_drift:
    - Did the work move away from the project final goal?
    - Did the work optimize a local mechanism while losing the Commander goal?
  scope_drift:
    - Were any changed files outside the declared allowed scope?
    - Were unrelated refactors or metadata churn introduced?
  authority_drift:
    - Did any artifact claim implementation authority without authorization?
    - Did any artifact claim commit push executor route review acceptance or
      delivery_state authority without authorization?
  evidence_drift:
    - Do claims point to the evidence they depend on?
    - Are known gaps carried forward rather than hidden?
  validation_drift:
    - Is validation truth reported as observed truth rather than acceptance?
    - Are failed or skipped validations visible?
  risk_drift:
    - Are unresolved risks still visible to Reviewer?
    - Does the package identify where Commander judgment may be needed?
```

---

## 5. Candidate Execution Envelope

```yaml id="candidate-execution-envelope"
execution_envelope_candidate:
  authorization_status: not_authorized
  parent_hashes:
    master_taskbook_hash: 1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34
    stage_taskbook_hash: 532d36ab5c99d37c1a88b094fbe9c37bdc342e17e572447468a0918afbdce43c
    previous_version_hash: 8e61482234cd2493463214649366b8b7d2455b2ea1d17777eea4bc4a1c04b98c
    stage_4_version_set_confirmation_hash: b1da3ea7e105d48f5018c5be17bb59e0164779bfe06e8a36f8e7265b62031c6f
  task_goal_ref: task_goal.primary_goal
  definition_of_good:
    - drift groups cover project scope authority evidence validation and risk
    - drift questions require evidence refs
    - UNCLEAR remains an allowed answer
    - generator never defaults to no drift
    - drift answers do not mutate ReviewDecision or GateEvent
```

---

## 6. Allowed Files And Mutations

```yaml id="allowed-files-and-mutations"
allowed_files:
  read_only:
    - PROJECT_MASTER_TASKBOOK.md
    - docs/taskbooks/stages/STAGE_05_REVIEWER_HANDOFF_PACKAGE.md
    - docs/taskbooks/versions/stage-05/VERSION_STAGE_05_V5_1_REVIEWER_HANDOFF_SCHEMA_V1.md
    - docs/taskbooks/versions/stage-05/VERSION_STAGE_05_V5_2_REVIEWER_HANDOFF_GENERATOR_V1.md
    - docs/taskbooks/versions/stage-05/VERSION_STAGE_05_V5_3_ALIGNMENT_QUESTIONS_V1.md
    - docs/taskbooks/versions/stage-04/**
    - runner/**
    - tests/**
  writable_after_separate_execution_authorization:
    - runner/reviewer_drift_questions.py
    - tests/test_reviewer_drift_questions.py
    - docs/taskbooks/versions/stage-05/evidence/VERSION_STAGE_05_V5_4_DRIFT_QUESTION_PACK_REPORT.md
    - docs/taskbooks/versions/stage-05/evidence/zh-CN/VERSION_STAGE_05_V5_4_DRIFT_QUESTION_PACK_REPORT.zh-CN.md
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

## 7. Rejection Rules

```yaml id="rejection-rules"
rejection_rules:
  reject_when:
    - project_goal_drift_question_missing
    - authority_drift_question_missing
    - evidence_refs_missing
    - reviewer_answer_options_missing_unclear
    - generator_defaults_to_no_drift
    - drift_answer_creates_review_decision
    - drift_answer_emits_gate_event
    - package_claims_no_drift_as_final
```

---

## 8. Evidence Package Contract

```yaml id="evidence-package-contract"
evidence_package_contract:
  evidence_report_required: true
  evidence_report_must_include:
    - drift_question_inventory
    - drift_type_coverage
    - evidence_ref_examples
    - unclear_answer_behavior
    - forbidden_default_no_drift_check
    - commands_run
    - commands_not_run
    - remaining_risks
  evidence_report_must_not_claim:
    - no_drift_confirmed
    - review_decision_created
    - delivery_state_transitioned
```

---

## 9. Manual Acceptance Criteria For This Version

```yaml id="manual-acceptance-criteria"
manual_acceptance_criteria:
  can_be_accepted_for_next_step_when:
    - all required drift groups are represented
    - authority drift explicitly covers commit push executor route review and state claims
    - unclear remains visible
    - drift answers remain Reviewer-owned records outside the generator
  must_return_to_draft_when:
    - generator can self-certify no drift
    - drift questions omit authority drift
    - drift answers imply acceptance
    - Chinese companion weakens the drift boundary
```

---

## 10. Next Version Handoff

```yaml id="next-version-handoff"
next_version_handoff:
  next_version: v5.5
  next_version_name: Reviewer Package Report Surface V1
  handoff_condition: >
    v5.5 may define the reviewer-facing report surface after v5.4 makes drift
    questions explicit and non-authoritative.
  still_not_authorized:
    - implementation
    - executor_run
    - review_acceptance
    - delivery_state_transition
```

中文解释：v5.4 是把“可能跑偏了吗”问出来，不是让系统自己宣布“没有跑偏”。
