# Stage 9 Taskbook: Controlled Continue And Long-Run Trace

```yaml id="stage-taskbook-summary"
stage_taskbook:
  document_type: stage_taskbook
  schema_version: stage_taskbook.discussion_draft.v1
  stage_id: stage_09_controlled_continue_and_long_run
  stage_name: Controlled Continue And Long-Run Trace
  chinese_name: 受控继续与长期追踪
  status: discussion_draft
  authority_status: planning_reference_only
  master_stage_status_ref: post_mvp_planned
  mvp_scope: excluded
  post_mvp_scope: included
  target_repository: /home/jenn/src/colameta-dev
  created_from_head: 8367a7d
  created_from_head_meaning: local_stage_7_9_preparation_baseline
```

`Controlled Continue And Long-Run Trace` = 受控继续与长期追踪。中文意思是：
在 review 给出 eligible decision 后，ColaMeta 才能通过单独 gate 进入下一
version 或 stage，并留下长期项目轨迹。

This taskbook does not authorize infinite loops, skipped review, or automatic
commit/push.

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
  has_pending_versions: false
  stage_9_status_before_this_file: master_roadmap_notes_only
```

Current reality: ColaMeta can finish a bounded loop and can record controlled
final-version closeout. Stage 9 is the missing long-run continuation layer.

---

## 2. Binding

```yaml id="binding"
binding:
  master_taskbook_path: PROJECT_MASTER_TASKBOOK.md
  master_taskbook_raw_snapshot_sha256: 1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34
  master_taskbook_stage_section: "23. Stage 9: Controlled Continue And Long-Run Trace"
  upstream_stage_dependency:
    - stage_06_review_feedback_intake
    - stage_07_drift_evidence_and_correction
    - stage_08_plan_adjustment_control
  requires_review_decision_ref: true
  requires_continue_gate: true
  requires_taskbook_hash_checks: true
  supports_project_goal: true
```

---

## 3. Stage Purpose

Stage 9 allows ColaMeta to continue a long-running project only after review
and gate requirements are satisfied.

It must explain:

- why the next action is allowed;
- which review decision enabled it;
- which hashes were checked;
- which stage or version boundary is being entered;
- which side effects remain forbidden.

---

## 4. Entry Criteria

```yaml id="entry-criteria"
entry_criteria:
  required:
    - eligible ReviewDecision or CommanderDecisionRequest exists
    - separate continue gate is requested
    - master taskbook hash is known
    - stage taskbook hash is known
    - version taskbook hash or next-version preview is known
    - no blocking review comments remain
  explicitly_not_required:
    - automatic executor run
    - automatic commit
    - automatic push
    - production deployment
```

---

## 5. Exit Criteria

```yaml id="exit-criteria"
exit_criteria:
  required:
    - controlled continue gate exists
    - review-decision-required policy exists
    - next-version readiness report can be generated
    - stage closeout review can be generated at stage end
    - long-run trace records why each step happened
    - continue action fails closed without ACCEPT and separate gate
    - taskbook hashes are checked before continuation
  not_exit_criteria:
    - infinite execution loop
    - skipped review
    - automatic commit or push
    - unauthorized stage entry
```

---

## 6. Deliverables

```yaml id="deliverables"
deliverables:
  minimum:
    - controlled_continue_gate
    - review_decision_required_policy
    - next_version_readiness_report
    - stage_closeout_review
    - long_run_project_trace
  optional_after_minimum:
    - continue_preview_status_surface
    - long_run_trace_reader
```

---

## 7. Version Directions

```yaml id="version-directions"
version_directions:
  preferred_sequence:
    - Review Decision Required Policy V1
    - Controlled Continue Gate V1
    - Next Version Readiness Report V1
    - Stage Closeout Review V1
    - Long Run Project Trace V1
```

---

## 8. Gate-Readiness Criteria

```yaml id="gate-readiness-criteria"
gate_readiness_criteria:
  - continue_next_version cannot run automatically without ACCEPT and separate continue gate
  - continue action checks master taskbook hash
  - continue action checks stage taskbook hash
  - continue action checks version taskbook hash or preview binding
  - stage end generates stage closeout review
  - long-run trace explains why every step happened
  - no infinite loop path exists
  - no commit or push is performed by continue gate
```

---

## 9. Minimum Evidence Package

```yaml id="minimum-evidence-package"
minimum_evidence_package:
  required_fields:
    - continue_gate_id
    - review_decision_ref
    - commander_authorization_ref
    - master_taskbook_hash
    - stage_taskbook_hash
    - version_taskbook_hash_or_preview_ref
    - current_state_summary
    - next_version_readiness_report
    - forbidden_side_effects
    - long_run_trace_entry
  must_not_include_as_authority:
    - skipped_review
    - automatic_executor_loop
    - automatic_commit
    - automatic_push
    - production_deploy
```

---

## 10. Non-Goals

```yaml id="non-goals"
non_goals:
  - no infinite execution loop
  - no skipped review
  - no automatic commit or push
  - no unauthorized stage entry
  - no production deployment
  - no package publish
```

---

## 11. Prepared Next Action

```yaml id="prepared-next-action"
prepared_next_action:
  recommended_first_version: Review Decision Required Policy V1
  recommended_tooling_mode: policy_and_readiness_report_first
  required_before_implementation:
    - Stage 8 adjustment preview behavior is clear
    - ACCEPT semantics remain separated from Delivery State accepted
    - continue gate cannot invoke executor directly in first slice
```
