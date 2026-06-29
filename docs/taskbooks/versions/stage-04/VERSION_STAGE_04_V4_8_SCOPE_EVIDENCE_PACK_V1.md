# Version Taskbook: Stage 4 / v4.8 Scope Evidence Pack V1

```text id="version-stage-04-v4-8-boundary-banner"
VERSION TASKBOOK DRAFT ONLY.
This document defines a candidate Version Execution Taskbook for Stage 4. It
does not authorize execution, executor dispatch, code edits, commit, push,
fetch, pull, route transition, plan mutation, review acceptance, Delivery State
Gate transition, or accepted delivery state.
```

```yaml id="version-taskbook-summary"
version_execution_taskbook:
  document_type: version_execution_taskbook
  schema_version: version_execution_taskbook.discussion_draft.v1
  version_id: stage_04_v4_8_scope_evidence_pack_v1
  version: v4.8
  name: Scope Evidence Pack V1
  chinese_name: 范围证据包 V1
  parent_stage_id: stage_04_bounded_execution_and_evidence
  parent_stage_name: Bounded Execution And Evidence
  status: discussion_draft
  authority_status: planning_reference_only
  execution_authorization_status: not_authorized
  dispatch_status: not_authorized
  executor_run_authorized: false
  created_from_head: 6194279
  created_from_head_full: 619427962eee7c5415d1893be9a5b07c5a7cb285
  created_from_head_meaning: historical_creation_baseline_not_execution_or_freeze_snapshot
  created_from_head_subject: "docs: add stage 4 execution receipt taskbooks"
  origin_main_observed_local_tracking_ref: 018ff63
  local_tracking_ref_sync_status_at_creation: local_ahead_remote_tracking_ref
  local_ahead_origin_main_at_creation: 32
```

`Scope Evidence Pack V1` = 范围证据包 V1。中文意思是：把 allowed_files、forbidden_files、
实际 touched files、scope violation 和 known gaps 打包成范围证据，方便审查是否越界。

---

## 1. Parent Binding

```yaml id="parent-binding"
parent_binding:
  master_taskbook_ref:
    path: PROJECT_MASTER_TASKBOOK.md
    raw_snapshot_sha256: 1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34
    review_status: freeze_candidate_confirmed_for_exact_hash
  stage_taskbook_ref:
    path: docs/taskbooks/stages/STAGE_04_BOUNDED_EXECUTION_AND_EVIDENCE.md
    raw_snapshot_sha256: 05e6114a666942c0641c635905c2295feaa62b98bd9e7b5166babd662e015a41
    stage_id: stage_04_bounded_execution_and_evidence
  previous_version_ref:
    path: docs/taskbooks/versions/stage-04/VERSION_STAGE_04_V4_7_VALIDATION_TRUTH_INTEGRATION_V1.md
    raw_snapshot_sha256: 755b33635c24eb450162de4bad1e0c8e17c38cf8a4eb83887cda985cf6dea8e5
    version_id: stage_04_v4_7_validation_truth_integration_v1
  stage_3_version_set_confirmation_ref:
    path: docs/taskbooks/versions/stage-03/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_03_VERSIONS.md
    raw_snapshot_sha256: 8695cf9f9b29608011dfc4691fd12df5a4f21f879e025e999c8bba5ae929e313
    review_status: hash_specific_freeze_candidate_confirmation_recorded
  supports_project_goal: true
```

---

## 2. Task Goal

```yaml id="task-goal"
task_goal:
  primary_goal: >
    Define a scope evidence pack that compares allowed files, forbidden files,
    observed touched files, observed mutations, ignored runtime files, generated
    files, and scope violations for a taskbook-bound execution.
  minimum_readiness_claim: >
    ColaMeta can show whether execution stayed inside its authorized file and
    command boundaries.
  gate_question: >
    Can scope compliance be reviewed from evidence instead of executor summary?
  explicit_non_goal: >
    This version is not executor dispatch, not plan mutation, not review
    acceptance, and not delivery state accepted.
```

---

## 3. Scope Evidence Contract

```yaml id="scope-evidence-contract"
scope_evidence_pack_contract:
  required_fields:
    - scope_pack_id
    - version_taskbook_ref
    - execution_envelope_ref
    - allowed_files
    - forbidden_files
    - observed_touched_files
    - observed_mutations
    - generated_files
    - ignored_runtime_files
    - scope_violations
    - known_gaps
    - remaining_risks
    - authority_boundary
  valid_scope_results:
    - in_scope
    - out_of_scope
    - unknown_needs_review
  forbidden_claims:
    - out_of_scope_summarized_as_in_scope
    - unknown_summarized_as_in_scope
    - scope_pass_implies_review_acceptance
    - delivery_state_accepted
```

---

## 4. Candidate Execution Envelope

```yaml id="candidate-execution-envelope"
execution_envelope_candidate:
  authorization_status: not_authorized
  parent_hashes:
    master_taskbook_hash: 1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34
    stage_taskbook_hash: 05e6114a666942c0641c635905c2295feaa62b98bd9e7b5166babd662e015a41
    previous_version_hash: 755b33635c24eb450162de4bad1e0c8e17c38cf8a4eb83887cda985cf6dea8e5
    stage_3_version_set_confirmation_hash: 8695cf9f9b29608011dfc4691fd12df5a4f21f879e025e999c8bba5ae929e313
  task_goal_ref: task_goal.primary_goal
  definition_of_good:
    - scope pack compares allowed forbidden and touched files
    - scope pack records violations explicitly
    - scope pack preserves unknowns and known gaps
    - scope pack cannot claim review acceptance
```

---

## 5. Allowed Files And Mutations

```yaml id="allowed-files-and-mutations"
allowed_files:
  read_only:
    - PROJECT_MASTER_TASKBOOK.md
    - docs/taskbooks/stages/STAGE_04_BOUNDED_EXECUTION_AND_EVIDENCE.md
    - docs/taskbooks/versions/stage-04/VERSION_STAGE_04_V4_7_VALIDATION_TRUTH_INTEGRATION_V1.md
    - runner/**
    - tests/**
  writable_after_separate_execution_authorization:
    - runner/scope_evidence_pack.py
    - tests/test_scope_evidence_pack.py
    - docs/taskbooks/versions/stage-04/evidence/VERSION_STAGE_04_V4_8_SCOPE_EVIDENCE_PACK_REPORT.md
    - docs/taskbooks/versions/stage-04/evidence/zh-CN/VERSION_STAGE_04_V4_8_SCOPE_EVIDENCE_PACK_REPORT.zh-CN.md
forbidden_files:
  mutation_targets:
    - /home/jenn/tools/colameta/**
    - PROJECT_MASTER_TASKBOOK.md
    - docs/taskbooks/stages/**
    - docs/taskbooks/versions/stage-00/**
    - docs/taskbooks/versions/stage-01/**
    - docs/taskbooks/versions/stage-02/**
    - docs/taskbooks/versions/stage-03/**
    - .colameta/plan.json
    - .colameta/state.json
    - .git/**
```

---

## 6. Next Version Handoff

```yaml id="next-version-handoff"
next_version_handoff:
  next_version: v4.9 Audit Package Taskbook Binding V1
  handoff_requires:
    - scope pack records observed touched files
    - violations and unknowns are explicit
    - scope result does not imply review acceptance
  must_not_handoff_as:
    - review_acceptance
    - delivery_state_accepted
```
