# Stage 8 Taskbook: Plan Adjustment Control Plane

```yaml id="stage-taskbook-summary"
stage_taskbook:
  document_type: stage_taskbook
  schema_version: stage_taskbook.discussion_draft.v1
  stage_id: stage_08_plan_adjustment_control
  stage_name: Plan Adjustment Control Plane
  chinese_name: 计划调整控制面
  status: discussion_draft
  authority_status: planning_reference_only
  master_stage_status_ref: post_mvp_planned
  mvp_scope: excluded
  post_mvp_scope: included
  target_repository: /home/jenn/src/colameta-dev
  created_from_head: 8367a7d
  created_from_head_meaning: local_stage_7_9_preparation_baseline
```

`Plan Adjustment Control Plane` = 计划调整控制面。中文意思是：Reviewer 判断需要
调整计划时，ColaMeta 生成可审查的 adjustment preview，而不是直接改 plan。

This taskbook does not authorize any automatic plan mutation.

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
  stage_8_status_before_this_file: master_roadmap_notes_only
```

Current reality: Stage 6 can classify `PLAN_ADJUST` as a Commander decision
request. Stage 8 is the missing controlled surface that turns such a request
into a bounded preview.

---

## 2. Binding

```yaml id="binding"
binding:
  master_taskbook_path: PROJECT_MASTER_TASKBOOK.md
  master_taskbook_raw_snapshot_sha256: 1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34
  master_taskbook_stage_section: "22. Stage 8: Plan Adjustment Control Plane"
  upstream_stage_dependency:
    - stage_06_review_feedback_intake
    - stage_07_drift_evidence_and_correction
  downstream_stage_dependency:
    - stage_09_controlled_continue_and_long_run
  requires_commander_authorization_for_apply: true
  requires_master_taskbook_ref: true
  requires_stage_taskbook_ref: true
  requires_version_taskbook_ref: true
  supports_project_goal: true
```

---

## 3. Stage Purpose

Stage 8 creates a controlled plan adjustment preview when review evidence says
the current plan should change.

It must preserve the difference between:

- a requested adjustment;
- a previewed adjustment;
- Commander authorization;
- actual plan or taskbook mutation.

---

## 4. Entry Criteria

```yaml id="entry-criteria"
entry_criteria:
  required:
    - ReviewDecision or CommanderDecisionRequest indicates PLAN_ADJUST
    - drift evidence pack or review feedback is bound
    - master_taskbook_hash is known
    - affected stage or version taskbook refs are known
    - requested adjustment explains why it still serves the master goal
  explicitly_not_required:
    - automatic apply authority
    - next-stage entry
    - executor continuation
```

---

## 5. Exit Criteria

```yaml id="exit-criteria"
exit_criteria:
  required:
    - plan adjustment request schema exists
    - plan adjustment preview can be generated
    - stage taskbook adjustment preview can be generated when needed
    - version taskbook adjustment preview can be generated when needed
    - master taskbook hard gate policy is explicit
    - adjustment audit record is generated
    - preview explains continued service to master goal
    - apply remains blocked without Commander hard gate
  not_exit_criteria:
    - automatic plan apply
    - automatic master taskbook mutation
    - automatic task-scope expansion
    - Reviewer bypass
```

---

## 6. Deliverables

```yaml id="deliverables"
deliverables:
  minimum:
    - plan_adjustment_request_schema
    - plan_adjustment_preview
    - stage_taskbook_adjustment_preview
    - version_taskbook_adjustment_preview
    - master_taskbook_hard_gate_policy
    - adjustment_audit_record
  optional_after_minimum:
    - adjustment_diff_renderer
    - adjustment_preview_status_surface
```

---

## 7. Version Directions

```yaml id="version-directions"
version_directions:
  preferred_sequence:
    - Plan Adjustment Request Schema V1
    - Plan Adjustment Preview V1
    - Taskbook Adjustment Preview V1
    - Master Hard Gate Policy V1
    - Adjustment Audit Record V1
```

---

## 8. Gate-Readiness Criteria

```yaml id="gate-readiness-criteria"
gate_readiness_criteria:
  - PLAN_ADJUST can only produce preview
  - plan adjustment cannot directly apply
  - adjustment explains why it still serves the master goal
  - master taskbook modifications require Commander hard gate
  - stage taskbook modifications reference master hash
  - version taskbook modifications reference stage hash
  - all adjustments are auditable
  - apply path fails closed without preview id and Commander authorization
```

---

## 9. Minimum Evidence Package

```yaml id="minimum-evidence-package"
minimum_evidence_package:
  required_fields:
    - adjustment_request_id
    - request_source
    - review_decision_ref
    - drift_evidence_ref
    - master_taskbook_ref
    - affected_stage_taskbook_refs
    - affected_version_taskbook_refs
    - proposed_change_summary
    - proposed_diff_or_patch_preview
    - continued_master_goal_service_explanation
    - forbidden_side_effects
    - audit_record_ref
  must_not_include_as_authority:
    - automatic_apply
    - Reviewer_bypass
    - master_goal_change_without_hard_gate
    - next_stage_entry
```

---

## 10. Non-Goals

```yaml id="non-goals"
non_goals:
  - no automatic master-goal change
  - no automatic task-scope expansion
  - no Reviewer bypass
  - no automatic next-stage entry
  - no executor continuation
  - no commit or push
```

---

## 11. Prepared Next Action

```yaml id="prepared-next-action"
prepared_next_action:
  recommended_first_version: Plan Adjustment Request Schema V1
  recommended_tooling_mode: schema_and_preview_only
  required_before_implementation:
    - Stage 7 PLAN_ADJUST trigger evidence shape is known
    - Commander hard gate policy wording is approved
    - apply route remains out of scope until preview behavior is proven
```
