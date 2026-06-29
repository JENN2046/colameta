# Stage 5 Taskbook: Reviewer Handoff Package

```yaml id="stage-taskbook-summary"
stage_taskbook:
  document_type: stage_taskbook
  schema_version: stage_taskbook.discussion_draft.v1
  stage_id: stage_05_reviewer_handoff_package
  stage_name: Reviewer Handoff Package
  chinese_name: 审查者交接包
  status: discussion_draft
  authority_status: planning_reference_only
  master_stage_status_ref: planned
  mvp_scope: included
  mvp_loop_name: Stage 0-6 Thin Governed Loop
  target_repository: /home/jenn/src/colameta-dev
  created_from_head: c0ed30d
  created_from_head_meaning: historical_creation_baseline_not_current_freeze_snapshot
```

`Reviewer Handoff Package` = 审查者交接包。中文意思是：把目标、任务、改动、
验证、风险、漂移问题打包给审查者，但不替审查者做最终判断。

`master_stage_status_ref` = Master 里的阶段状态引用。中文意思是：Master 说
Stage 5 是 `planned`，但这份 Stage Taskbook 文件本身仍然只是
`discussion_draft` 草稿。

---

## 1. Binding

```yaml id="binding"
binding:
  master_taskbook_path: PROJECT_MASTER_TASKBOOK.md
  master_taskbook_raw_snapshot_sha256: 1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34
  master_taskbook_ref:
    path: PROJECT_MASTER_TASKBOOK.md
    raw_snapshot_sha256: 1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34
    review_status: freeze_candidate_confirmed_for_exact_hash
  requires_master_taskbook_ref: true
  requires_stage_taskbook_ref: true
  requires_version_taskbook_ref: true
  requires_execution_receipt_ref: true
  supports_project_goal: true
```

---

## 2. Stage Purpose

Stage 5 generates a self-contained review package after bounded execution or
receipt intake. The package helps a Reviewer judge task completion, scope,
validation, risk, and goal alignment without reconstructing the whole thread.

It is not acceptance itself.

---

## 3. Entry Criteria

```yaml id="entry-criteria"
entry_criteria:
  required:
    - execution receipt or imported receipt exists
    - validation truth status is known
    - changed files or touched artifacts are known
    - taskbook bindings are known
  explicitly_not_required:
    - Reviewer decision
    - delivery_state promotion
    - automatic semantic alignment claim
```

---

## 4. Exit Criteria

```yaml id="exit-criteria"
exit_criteria:
  required:
    - handoff package includes master-goal summary
    - handoff package includes stage-goal summary
    - handoff package includes version-task summary
    - handoff package includes changed_files
    - handoff package includes validation truth
    - handoff package includes scope evidence
    - handoff package asks Reviewer to judge drift
    - handoff package offers limited decision options
    - handoff package decision options are exactly ACCEPT, NEEDS_FIX, PLAN_ADJUST, and ABORT
    - ACCEPT is presented only as a reviewer-selectable ReviewDecision value, never as a generator recommendation or delivery_state accepted
  not_exit_criteria:
    - acceptance
    - automatic aligned claim
    - automatic next-version release
```

---

## 5. Deliverables

```yaml id="deliverables"
deliverables:
  minimum:
    - reviewer_handoff_package_schema
    - reviewer_handoff_package_generator
    - alignment_questions
    - drift_questions
    - allowed_review_decision_options
    - minimum_handoff_template
    - diff_summary
    - validation_truth_summary
  optional_after_minimum:
    - report_excerpt
    - markdown_review_packet
```

---

## 6. Version Directions

```yaml id="version-directions"
version_directions:
  preferred_sequence:
    - Reviewer Handoff Schema V1
    - Reviewer Handoff Generator V1
    - Alignment Questions V1
    - Drift Question Pack V1
    - Reviewer Package Report Surface V1
```

`Version Directions` = 版本方向。中文意思是：Stage 5 后续可以拆成这些更小的
Version Execution Taskbook；它们只生成审查材料，不替审查者决策。

---

## 7. Gate-Readiness Criteria

```yaml id="gate-readiness-criteria"
gate_readiness_criteria:
  - handoff package includes master-goal summary
  - handoff package includes stage-goal summary
  - handoff package includes version-task summary
  - handoff package includes changed_files
  - handoff package includes validation truth
  - handoff package includes scope evidence
  - handoff package asks Reviewer to judge drift
  - handoff package offers only ACCEPT, NEEDS_FIX, PLAN_ADJUST, and ABORT
  - ACCEPT is ReviewDecision.ACCEPT only, never delivery_state accepted
```

### 7.1 Stage 0-6 Readiness Contract

```yaml id="stage-0-6-readiness-contract"
stage_0_6_readiness_contract:
  stage_id: stage_05_reviewer_handoff_package
  minimum_readiness_claim: Reviewer handoff is self-contained.
  required_evidence:
    - claim-to-evidence package
    - validation status
    - risks
    - known gaps
  gate_question: Can a reviewer decide without reconstructing context?
  explicit_non_goal: Not acceptance itself.
```

`Reviewer` = 审查者。中文意思是：负责判断执行结果是否满足任务、是否跑偏、
是否需要返工的人或智能体角色。

### 7.1 Minimum Handoff Template

```yaml id="minimum-handoff-template"
minimum_handoff_template:
  required_keys:
    - handoff_package_id
    - master_taskbook_ref
    - stage_taskbook_ref
    - version_taskbook_ref
    - execution_receipt_ref
    - claim_summary
    - changed_files
    - validation_truth
    - scope_evidence
    - known_risks
    - reviewer_questions
    - allowed_review_decisions
  allowed_review_decisions:
    - ACCEPT
    - NEEDS_FIX
    - PLAN_ADJUST
    - ABORT
  decision_boundary: >
    Reviewer decisions are review records selected by the Reviewer. The handoff
    generator must not recommend ACCEPT. Review records do not write
    delivery_state and do not replace Delivery State Gate review.
```

---

## 8. Minimum Evidence Package

```yaml id="minimum-evidence-package"
minimum_evidence_package:
  required_fields:
    - review_package_id
    - master_goal_summary
    - stage_goal_summary
    - version_task_summary
    - execution_receipt_ref
    - changed_files
    - validation_truth_summary
    - scope_evidence
    - known_risks
    - reviewer_questions
  must_not_include_as_authority:
    - acceptance claim
    - delivery_state transition
    - Commander authorization
```

---

## 9. Non-Goals

```yaml id="non-goals"
non_goals:
  - no final Reviewer replacement
  - no automatic aligned claim
  - no automatic next-version release
  - no treating handoff package as acceptance pass
  - no commit or push authorization
```

---

## 10. Next Recommended Step

```text id="next-recommended-step"
After Stage 4 can produce execution evidence, define the smallest review
package that lets a Reviewer answer ACCEPT, NEEDS_FIX, PLAN_ADJUST, or ABORT.
```

中文解释：Stage 5 第一刀是把审查材料交清楚，不是替审查者点头。
