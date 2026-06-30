# Stage 7 Taskbook: Drift Evidence And Correction

```yaml id="stage-taskbook-summary"
stage_taskbook:
  document_type: stage_taskbook
  schema_version: stage_taskbook.discussion_draft.v1
  stage_id: stage_07_drift_evidence_and_correction
  stage_name: Drift Evidence And Correction
  chinese_name: 漂移证据与纠偏
  status: discussion_draft
  authority_status: planning_reference_only
  master_stage_status_ref: post_mvp_planned
  mvp_scope: excluded
  post_mvp_scope: included
  target_repository: /home/jenn/src/colameta-dev
  created_from_head: 8367a7d
  created_from_head_meaning: local_stage_7_9_preparation_baseline
```

`Drift Evidence And Correction` = 漂移证据与纠偏。中文意思是：ColaMeta
收集项目是否偏离 master goal 的证据和问题，让 Reviewer 判断是否需要纠偏。

This taskbook does not authorize ColaMeta to declare semantic alignment or
rewrite any taskbook by itself.

---

## 1. Reality Snapshot

```yaml id="reality-snapshot"
reality_snapshot:
  captured_at: 2026-07-01T01:02:18+08:00
  dev_head: 8367a7d39cef0c70237625c4e50f0d6127cde3a6
  origin_main: 8367a7d39cef0c70237625c4e50f0d6127cde3a6
  stable_head: 8367a7d39cef0c70237625c4e50f0d6127cde3a6
  stable_service_health: mcp_and_web_ok
  runner_status: COMPLETED
  current_version: v1.11
  current_version_status: PASSED
  stage_0_6_status: thin_governed_loop_available
  stage_7_9_status_before_this_file: master_roadmap_notes_only
```

Current reality: Stage 0-6 can already provide bounded execution evidence,
reviewer handoff, and review feedback classification. Stage 7 needs to reuse
that evidence instead of inventing a new authority path.

---

## 2. Binding

```yaml id="binding"
binding:
  master_taskbook_path: PROJECT_MASTER_TASKBOOK.md
  master_taskbook_raw_snapshot_sha256: 1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34
  master_taskbook_stage_section: "21. Stage 7: Drift Evidence And Correction"
  upstream_stage_dependency:
    - stage_05_reviewer_handoff_package
    - stage_06_review_feedback_intake
  downstream_stage_dependency:
    - stage_08_plan_adjustment_control
  requires_master_taskbook_ref: true
  requires_stage_taskbook_ref: true
  requires_version_taskbook_ref: true
  requires_reviewer_handoff_package_ref: true
  requires_execution_report_or_receipt_ref: true
  supports_project_goal: true
```

---

## 3. Stage Purpose

Stage 7 organizes drift evidence so a Reviewer can answer whether the work is
still serving the master goal.

The stage must separate:

- observed evidence;
- questions for the Reviewer;
- possible correction routes;
- Commander authorization boundaries.

It must not turn evidence into an automatic semantic judgment.

---

## 4. Entry Criteria

```yaml id="entry-criteria"
entry_criteria:
  required:
    - master_taskbook_ref is known
    - stage_taskbook_ref is known
    - version_taskbook_ref is known
    - execution evidence or receipt exists
    - reviewer handoff package can be generated or read
    - changed files or touched artifacts are known
  explicitly_not_required:
    - reviewer drift decision
    - plan adjustment preview
    - route transition
    - executor continuation
```

---

## 5. Exit Criteria

```yaml id="exit-criteria"
exit_criteria:
  required:
    - drift evidence pack can be generated from bounded evidence
    - executor drift evidence is separated from task drift evidence
    - task drift evidence is separated from stage drift evidence
    - master goal alignment questions are produced
    - reviewer drift checklist is produced
    - plan adjustment trigger conditions are explicit
    - PLAN_ADJUST is routed to Stage 8 preview flow only
    - no automatic semantic alignment claim is emitted
  not_exit_criteria:
    - taskbook rewrite
    - master goal change
    - stage scope expansion
    - Delivery State accepted
```

---

## 6. Deliverables

```yaml id="deliverables"
deliverables:
  minimum:
    - drift_evidence_schema
    - drift_evidence_pack_builder
    - executor_drift_evidence
    - task_drift_evidence
    - stage_drift_evidence
    - master_goal_alignment_questions
    - reviewer_drift_checklist
    - plan_adjustment_trigger_conditions
  optional_after_minimum:
    - drift_evidence_report_surface
    - drift_question_pack_templates
```

---

## 7. Version Directions

```yaml id="version-directions"
version_directions:
  preferred_sequence:
    - Drift Evidence Schema V1
    - Drift Evidence Pack Builder V1
    - Master Goal Alignment Questions V1
    - Reviewer Drift Checklist V1
    - PLAN_ADJUST Trigger Conditions V1
```

These versions should be source-only or preview-only until the Stage 8
controlled preview behavior exists.

---

## 8. Gate-Readiness Criteria

```yaml id="gate-readiness-criteria"
gate_readiness_criteria:
  - drift evidence binds master_taskbook_hash
  - drift evidence binds stage_taskbook_hash
  - drift evidence binds version_taskbook_ref
  - drift evidence binds execution evidence or receipt
  - forbidden_files, out_of_scope, validation, and diff evidence are preserved
  - Reviewer receives explicit alignment questions
  - Reviewer receives limited drift answer options
  - ColaMeta never declares semantic alignment by itself
  - PLAN_ADJUST creates only a request for Stage 8 controlled preview
```

---

## 9. Minimum Evidence Package

```yaml id="minimum-evidence-package"
minimum_evidence_package:
  required_fields:
    - drift_evidence_pack_id
    - master_taskbook_ref
    - stage_taskbook_ref
    - version_taskbook_ref
    - execution_evidence_ref
    - changed_files
    - validation_truth
    - scope_evidence
    - forbidden_files_evidence
    - out_of_scope_evidence
    - master_goal_alignment_questions
    - reviewer_drift_checklist
    - plan_adjustment_trigger_conditions
  must_not_include_as_authority:
    - semantic_alignment_pass
    - plan_mutation
    - master_goal_change
    - stage_scope_expansion
```

---

## 10. Non-Goals

```yaml id="non-goals"
non_goals:
  - no ColaMeta-only semantic drift judgment
  - no automatic taskbook rewrite
  - no automatic master-goal change
  - no automatic stage-scope expansion
  - no Delivery State Gate transition
  - no executor continuation
  - no commit or push
```

---

## 11. Prepared Next Action

```yaml id="prepared-next-action"
prepared_next_action:
  recommended_first_version: Drift Evidence Schema V1
  recommended_tooling_mode: source_only_preview_first
  required_before_implementation:
    - create version prompt for v1.12 or a new stage-07 version series
    - bind allowed files narrowly
    - keep Stage 8 and Stage 9 actions forbidden until their preview/gate behavior is implemented and authorized
```
