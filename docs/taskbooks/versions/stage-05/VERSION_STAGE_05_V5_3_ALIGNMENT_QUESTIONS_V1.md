# Version Taskbook: Stage 5 / v5.3 Alignment Questions V1

```text id="version-stage-05-v5-3-boundary-banner"
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
  version_id: stage_05_v5_3_alignment_questions_v1
  version: v5.3
  name: Alignment Questions V1
  chinese_name: 对齐问题 V1
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

`Alignment Questions V1` = 对齐问题 V1。中文意思是：把 Reviewer 必须判断的
“是否贴合最终目标、阶段目标、版本目标”转成固定问题清单，但答案仍由 Reviewer
给出，不由 generator 代答。

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
    path: docs/taskbooks/versions/stage-05/VERSION_STAGE_05_V5_2_REVIEWER_HANDOFF_GENERATOR_V1.md
    raw_snapshot_sha256: 5b47123fa34da5a9381d2747bbdd1ba23efbe2b992130d511065240f99c5547a
    version_id: stage_05_v5_2_reviewer_handoff_generator_v1
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
    Define the minimum alignment question set that a reviewer handoff package
    must present so a Reviewer can judge whether the evidence supports the
    project final goal, the parent Stage goal, and the specific Version task
    goal.
  minimum_readiness_claim: >
    ColaMeta can ask the right goal-alignment questions without claiming that
    the work is aligned.
  gate_question: >
    Can the handoff package separate evidence presentation from Reviewer
    alignment judgment?
  explicit_non_goal: >
    This version is not semantic acceptance, not drift classification by the
    generator, not ReviewDecision creation, and not delivery state transition.
```

---

## 3. Alignment Question Contract

```yaml id="alignment-question-contract"
alignment_question_contract:
  required_question_groups:
    - project_final_goal_alignment
    - stage_goal_alignment
    - version_task_goal_alignment
    - scope_alignment
    - evidence_alignment
    - risk_alignment
  required_question_fields:
    - question_id
    - question_text
    - target_ref
    - evidence_refs
    - reviewer_answer_options
    - unanswered_state
  reviewer_answer_options:
    - YES
    - NO
    - UNCLEAR
    - NOT_APPLICABLE
  forbidden_question_behavior:
    - prefilled_yes_answer
    - accept_recommendation
    - hidden_unclear_option
    - generator_scored_alignment_as_final
```

`project_final_goal_alignment` = 项目最终目标对齐。中文意思是：Reviewer 要判断当前
证据是否真的服务于用户最终要实现的东西，而不是只看任务列表有没有打勾。

---

## 4. Required Questions

```yaml id="required-questions"
required_questions:
  project_final_goal_alignment:
    - Does the evidence support the project final goal rather than only local
      task completion?
    - Did the work avoid changing the project final goal without Commander
      authorization?
  stage_goal_alignment:
    - Does the evidence support the Stage 5 goal of reviewer handoff rather than
      review replacement?
    - Are the Stage 5 non-goals preserved?
  version_task_goal_alignment:
    - Does the package satisfy the exact Version task goal?
    - Are missing fields or risks surfaced instead of hidden?
  scope_alignment:
    - Were changed files and touched artifacts within declared scope?
    - Are out-of-scope changes named clearly if they exist?
  evidence_alignment:
    - Does each claim have a supporting evidence reference?
    - Are validation truth and scope evidence kept separate from acceptance?
  risk_alignment:
    - Are known risks and known gaps visible enough for review?
    - Is the Reviewer asked to judge unresolved drift?
```

---

## 5. Candidate Execution Envelope

```yaml id="candidate-execution-envelope"
execution_envelope_candidate:
  authorization_status: not_authorized
  parent_hashes:
    master_taskbook_hash: 1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34
    stage_taskbook_hash: 532d36ab5c99d37c1a88b094fbe9c37bdc342e17e572447468a0918afbdce43c
    previous_version_hash: 5b47123fa34da5a9381d2747bbdd1ba23efbe2b992130d511065240f99c5547a
    stage_4_version_set_confirmation_hash: b1da3ea7e105d48f5018c5be17bb59e0164779bfe06e8a36f8e7265b62031c6f
  task_goal_ref: task_goal.primary_goal
  definition_of_good:
    - alignment questions bind to evidence refs
    - unanswered or unclear answers remain visible
    - generator never pre-fills acceptance or alignment pass
    - project final goal is asked directly
    - Stage and Version goals are asked separately
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
    - docs/taskbooks/versions/stage-04/**
    - runner/**
    - tests/**
  writable_after_separate_execution_authorization:
    - runner/reviewer_alignment_questions.py
    - tests/test_reviewer_alignment_questions.py
    - docs/taskbooks/versions/stage-05/evidence/VERSION_STAGE_05_V5_3_ALIGNMENT_QUESTIONS_REPORT.md
    - docs/taskbooks/versions/stage-05/evidence/zh-CN/VERSION_STAGE_05_V5_3_ALIGNMENT_QUESTIONS_REPORT.zh-CN.md
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
    - project_final_goal_question_missing
    - stage_goal_question_missing
    - version_task_goal_question_missing
    - scope_alignment_question_missing
    - evidence_ref_missing_for_claim
    - reviewer_answer_options_missing_unclear
    - generator_prefills_yes_or_accept
    - alignment_question_claims_final_alignment
```

---

## 8. Evidence Package Contract

```yaml id="evidence-package-contract"
evidence_package_contract:
  evidence_report_required: true
  evidence_report_must_include:
    - question_inventory
    - target_ref_inventory
    - evidence_ref_inventory
    - unanswered_state_examples
    - forbidden_prefill_check
    - commands_run
    - commands_not_run
    - remaining_risks
  evidence_report_must_not_claim:
    - alignment_confirmed
    - reviewer_acceptance
    - delivery_state_accepted
```

---

## 9. Manual Acceptance Criteria For This Version

```yaml id="manual-acceptance-criteria"
manual_acceptance_criteria:
  can_be_accepted_for_next_step_when:
    - project Stage and Version alignment are asked separately
    - question answers include UNCLEAR
    - every claim question can carry evidence refs
    - generator cannot answer alignment on behalf of Reviewer
  must_return_to_draft_when:
    - question wording pressures Reviewer toward ACCEPT
    - question set omits project final goal
    - alignment result can be treated as delivery state
    - Chinese companion weakens the alignment boundary
```

---

## 10. Next Version Handoff

```yaml id="next-version-handoff"
next_version_handoff:
  next_version: v5.4
  next_version_name: Drift Question Pack V1
  handoff_condition: >
    v5.4 may define drift-specific review questions after v5.3 separates
    alignment questions from alignment judgment.
  still_not_authorized:
    - implementation
    - executor_run
    - review_acceptance
    - delivery_state_transition
```

中文解释：v5.3 要做的是“问准问题”，不是“替审查者说已经对齐”。
