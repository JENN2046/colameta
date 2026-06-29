# Stage 6 Taskbook: Review Feedback Intake

```yaml id="stage-taskbook-summary"
stage_taskbook:
  document_type: stage_taskbook
  schema_version: stage_taskbook.discussion_draft.v1
  stage_id: stage_06_review_feedback_intake
  stage_name: Review Feedback Intake
  chinese_name: 审查反馈接入
  status: discussion_draft
  authority_status: planning_reference_only
  master_stage_status_ref: planned
  mvp_scope: included
  mvp_loop_name: Stage 0-6 Thin Governed Loop
  mvp_implementation_mode: thin_by_default
  target_repository: /home/jenn/src/colameta-dev
  created_from_head: c0ed30d
```

`Review Feedback Intake` = 审查反馈接入。中文意思是：把审查者的反馈结构化，
变成下一步 Commander 决策请求，而不是自动改计划、自动验收或自动继续执行。

`master_stage_status_ref` = Master 里的阶段状态引用。中文意思是：Master 说
Stage 6 是 `planned`，但这份 Stage Taskbook 文件本身仍然只是
`discussion_draft` 草稿。

---

## 1. Binding

```yaml id="binding"
binding:
  master_taskbook_path: PROJECT_MASTER_TASKBOOK.md
  master_taskbook_raw_snapshot_sha256: 1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34
  requires_master_taskbook_ref: true
  requires_stage_taskbook_ref: true
  requires_version_taskbook_ref: true
  requires_reviewer_handoff_package_ref: true
  requires_execution_report_ref: true
  requires_workspace_snapshot_ref: true
```

`ReviewDecision` = 审查决策记录。中文意思是：审查者说出的判断记录，但它本身
不是 Delivery State Gate 的状态写入。

---

## 2. Stage Purpose

Stage 6 turns structured review feedback into a classified next-state
Commander decision request. It preserves the boundary between Reviewer opinion,
Commander authority, and Delivery State Gate state transitions.

---

## 3. Entry Criteria

```yaml id="entry-criteria"
entry_criteria:
  required:
    - reviewer handoff package exists
    - review feedback is bound to an execution report
    - workspace snapshot reference is known
    - master and stage hashes are known
  explicitly_not_required:
    - plan mutation
    - delivery_state promotion
    - executor continuation
```

---

## 4. Exit Criteria

```yaml id="exit-criteria"
exit_criteria:
  required:
    - ACCEPT, NEEDS_FIX, PLAN_ADJUST, and ABORT are recognized
    - PASS is handled only as a policy-mapped legacy alias for ReviewDecision.ACCEPT
    - PASS alias policy id is recorded
    - ReviewDecision.ACCEPT never means delivery_state accepted
    - feedback binds reviewer_handoff_package_ref
    - feedback binds version_taskbook_ref
    - feedback binds execution_report_ref
    - feedback binds workspace_snapshot_ref
    - feedback binds master_taskbook_hash
    - feedback binds stage_taskbook_hash
    - binding mismatch fails closed
    - output is a CommanderDecisionRequest, not a state transition
  not_exit_criteria:
    - automatic plan modification
    - automatic state transition
    - automatic executor continuation
    - commit or push
```

`CommanderDecisionRequest` = 指挥官决策请求。中文意思是：系统把“下一步需要
你授权什么”整理出来，请 Commander 决定，而不是替 Commander 决定。

---

## 5. Deliverables

```yaml id="deliverables"
deliverables:
  minimum:
    - review_feedback_schema
    - review_feedback_validator
    - review_feedback_preview
    - review_feedback_classification
    - commander_decision_request
    - review_decision_mapping
    - feedback_audit_record
  optional_after_minimum:
    - feedback_import_receipt
    - decision_request_status_surface
```

---

## 6. Version Directions

```yaml id="version-directions"
version_directions:
  preferred_sequence:
    - Review Feedback Schema V1
    - Review Feedback Validator V1
    - Review Feedback Preview V1
    - Review Feedback Classification And Decision Request V1
    - Review Decision Adapter V1
```

`Version Directions` = 版本方向。中文意思是：Stage 6 后续可以拆成这些更小的
Version Execution Taskbook；它们只生成 Commander 决策请求，不写状态。

---

## 7. Gate-Readiness Criteria

```yaml id="gate-readiness-criteria"
gate_readiness_criteria:
  - only ACCEPT, NEEDS_FIX, PLAN_ADJUST, and ABORT are recognized review decision values
  - PASS is a legacy alias for ReviewDecision.ACCEPT only when explicitly mapped by policy id
  - ReviewDecision.ACCEPT never means delivery_state accepted
  - feedback must bind reviewer_handoff_package_ref
  - feedback must bind version_taskbook_ref
  - feedback must bind execution_report_ref
  - feedback must bind workspace_snapshot_ref
  - feedback must bind master_taskbook_hash
  - feedback must bind stage_taskbook_hash
  - feedback must contain charter_alignment, task_completion, and scope_assessment
  - binding mismatch fails closed
  - ACCEPT creates a CommanderDecisionRequest asking whether to request Delivery State Gate review; only GateEvent may record accepted
  - NEEDS_FIX creates a CommanderDecisionRequest asking whether to request Delivery State Gate review; only GateEvent may record returned work
  - ACCEPT, NEEDS_FIX, and PASS alias handling never open a gate route automatically
  - PLAN_ADJUST creates a Commander decision request; it never mutates the plan by itself
  - ABORT creates a Commander decision request; it never cancels, deletes, or reverts by itself
  - PASS alias is disabled unless explicit authorized pass_alias_policy_ref is present
  - feedback classification never mutates plan, route, delivery state, Git state, memory, executor continuation, commit, or push by itself
```

`GateEvent` = 状态门事件。中文意思是：真正写入交付状态变化的事件记录，不是
审查反馈本身。

---

## 8. Minimum Evidence Package

```yaml id="minimum-evidence-package"
minimum_evidence_package:
  required_fields:
    - review_feedback_ref
    - reviewer_identity_or_source
    - reviewer_authority_scope
    - reviewer_attestation
    - reviewer_handoff_package_ref
    - version_taskbook_ref
    - execution_report_ref
    - workspace_snapshot_ref
    - master_taskbook_hash
    - stage_taskbook_hash
    - review_decision_value
    - pass_alias_policy_id_when_used
    - charter_alignment
    - task_completion
    - scope_assessment
    - requested_commander_decision
  must_not_include_as_authority:
    - automatic delivery_state transition
    - plan mutation
    - route transition
    - executor continuation
```

---

## 9. Non-Goals

```yaml id="non-goals"
non_goals:
  - no automatic review conclusion inference
  - no vague feedback intake
  - no unbound report feedback
  - no automatic plan modification
  - no automatic state transition
  - no automatic executor continuation
  - no automatic commit
```

---

## 10. Next Recommended Step

```text id="next-recommended-step"
After Stage 5 can generate a review handoff package, define the smallest
feedback schema that turns a review decision into a CommanderDecisionRequest.
```

中文解释：Stage 6 第一刀是“把反馈变成下一步请求”，不是让反馈直接开动机器。
