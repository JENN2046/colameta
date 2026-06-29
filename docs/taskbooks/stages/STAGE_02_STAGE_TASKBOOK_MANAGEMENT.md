# Stage 2 Taskbook: Stage Taskbook Management

```yaml id="stage-taskbook-summary"
stage_taskbook:
  document_type: stage_taskbook
  schema_version: stage_taskbook.discussion_draft.v1
  stage_id: stage_02_stage_taskbook_management
  stage_name: Stage Taskbook Management
  chinese_name: 阶段任务书管理
  status: discussion_draft
  authority_status: planning_reference_only
  master_stage_status_ref: planned
  mvp_scope: included
  mvp_loop_name: Stage 0-6 Thin Governed Loop
  target_repository: /home/jenn/src/colameta-dev
  created_from_head: c0ed30d
```

`Stage Taskbook Management` = 阶段任务书管理。中文意思是：让每个阶段任务书
能被登记、校验、引用，并且必须绑定到 Master Taskbook。

`master_stage_status_ref` = Master 里的阶段状态引用。中文意思是：Master 说
Stage 2 是 `planned`，但这份 Stage Taskbook 文件本身仍然只是
`discussion_draft` 草稿。

---

## 1. Master Binding

```yaml id="master-binding"
master_binding:
  master_taskbook_path: PROJECT_MASTER_TASKBOOK.md
  master_taskbook_raw_snapshot_sha256: 1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34
  stage_requires_master_ref: true
  project_final_goal_ref: master_taskbook.project_final_goal
```

Stage 2 depends on Stage 1 producing a stable `master_taskbook_ref`.

`master_taskbook_ref` = 主任务书引用。中文意思是：下游阶段和版本必须明确自己
绑定的是哪一份 Master，而不是凭聊天记忆继续。

---

## 2. Stage Purpose

Stage 2 makes Stage Taskbooks first-class governed planning artifacts. A Stage
Taskbook may describe stage purpose, bounds, evidence expectations, and
gate-readiness criteria, but it must not claim accepted delivery state.

---

## 3. Entry Criteria

```yaml id="entry-criteria"
entry_criteria:
  required:
    - Stage 1 exposes a stable master_taskbook_ref
    - Stage Taskbook path convention is known
    - Stage Taskbook required fields are defined
  explicitly_not_required:
    - complete workflow platform
    - executor dispatch
    - Web UI
    - codex-router bridge
```

---

## 4. Exit Criteria

```yaml id="exit-criteria"
exit_criteria:
  required:
    - Stage Taskbook schema exists
    - Stage Taskbook validator exists
    - Stage Taskbook registry can record stage id, path, hash, and master ref
    - missing master_taskbook_ref fails closed
    - stage purpose and non-goals are required
    - gate-readiness criteria are required
    - version tasks can reference only registered, gate-ready stage_taskbook_ref values
  not_exit_criteria:
    - state authority
    - execution authorization
    - automatic stage generation
    - automatic acceptance
```

---

## 5. Deliverables

```yaml id="deliverables"
deliverables:
  minimum:
    - stage_taskbook_schema
    - stage_taskbook_validator
    - stage_taskbook_registry
    - stage_to_master_binding_check
    - stage_gate_readiness_contract
  optional_after_minimum:
    - stage_taskbook_status_surface
    - stage_taskbook_hash_report
```

---

## 6. Version Directions

```yaml id="version-directions"
version_directions:
  preferred_sequence:
    - Stage Taskbook Schema + Validator V1
    - Stage Taskbook Registry V1
    - Stage-to-Master Binding V1
    - Stage Taskbook Gate-Readiness Contract V1
```

`Version Directions` = 版本方向。中文意思是：Stage 2 后续可以拆成这些更小的
Version Execution Taskbook，但这里不授权执行。

---

## 7. Required Field Matrix

```yaml id="required-field-matrix"
required_field_matrix:
  bootstrap_registration_mode:
    purpose: >
      Allow the initial Stage 0-6 discussion drafts to be registered or
      migrated before the full Stage Taskbook schema is enforced.
    authorization_required: separate_version_execution_taskbook_and_commander_authorization
    allowed_scope:
      - initial Stage 0-6 discussion drafts only
    one_time_only: true
    hash_bound: true
    receipt_required: true
    non_repeatable_after_initial_migration: true
    no_future_schema_waiver: true
    allowed_missing_or_aliasable_fields:
      - master_taskbook_ref can be derived from the known Master binding during bootstrap.
      - supports_project_goal can be derived from the stage purpose and Master reference during bootstrap.
      - readiness_contract_fields can be mapped from existing gate-readiness criteria during bootstrap.
    boundary: >
      Bootstrap mode is for a separately authorized migration preview or
      migration only. It must not grant execution authority, delivery-state
      authority, route authority, registry mutation authority, Git authority,
      memory-write authority, or future schema bypass authority.
  static_required_fields:
    - stage_id
    - stage_name
    - chinese_name
    - status
    - authority_status
    - master_taskbook_ref
    - supports_project_goal
    - stage_purpose
    - entry_criteria
    - exit_criteria
    - deliverables
    - gate_readiness_criteria
    - minimum_evidence_package
    - non_goals
  readiness_contract_fields:
    - minimum_readiness_claim
    - required_evidence
    - gate_question
    - explicit_non_goal
  boundary_fields:
    - state_authority_boundary
    - execution_authorization_boundary
    - mutation_boundary
```

`Required Field Matrix` = 必填字段矩阵。中文意思是：后续写 Stage Taskbook
schema 时，不能只说“字段要完整”，要明确哪些字段必须存在。

`bootstrap_registration_mode` = 启动登记模式。中文意思是：第一次把 Stage 0-6
草稿纳入登记时，可以用受控迁移规则补齐引用字段；但它必须另有授权、绑定 hash、
留下回执，只能用一次，迁移完成后再执行严格 schema。

---

## 8. Gate-Readiness Criteria

```yaml id="gate-readiness-criteria"
gate_readiness_criteria:
  - Stage Taskbook must reference master_taskbook_ref.
  - Stage Taskbook must explain supports_project_goal.
  - Stage Taskbook must declare non_goals or out_of_scope.
  - Stage Taskbook must define gate-readiness criteria.
  - Stage Taskbook hash can be referenced by version tasks only after registration and gate-readiness checks.
  - Stage Taskbook claims are distinct from accepted delivery state.
```

`supports_project_goal` = 支持项目最终目标。中文意思是：阶段任务书必须说明自己
为什么服务于 `project_final_goal`。

---

## 9. Minimum Evidence Package

```yaml id="minimum-evidence-package"
minimum_evidence_package:
  required_fields:
    - stage_taskbook_path
    - stage_taskbook_hash
    - master_taskbook_ref
    - supports_project_goal_summary
    - non_goals
    - gate_readiness_criteria
    - validation_result
  must_not_include_as_authority:
    - reviewer acceptance
    - delivery_state
    - runtime status labels
```

---

## 10. Non-Goals

```yaml id="non-goals"
non_goals:
  - no stage execution
  - no automatic stage-goal generation
  - no automatic master-goal adjustment
  - no dashboard requirement
  - no commit or push authorization
```

---

## 11. Next Recommended Step

```text id="next-recommended-step"
After Stage 1 establishes Master registration, draft a separate Version
Execution Taskbook for the smallest Stage Taskbook schema and validation path
that can register these Stage 0-6 drafts.
Use bootstrap registration mode only for the first controlled migration, then
require the strict field matrix for later Stage Taskbooks.
```

中文解释：Stage 2 的第一刀应该是“能登记并校验阶段任务书”，不是做完整平台。
