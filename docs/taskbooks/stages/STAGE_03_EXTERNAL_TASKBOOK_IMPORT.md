# Stage 3 Taskbook: External Taskbook Import Protocol

```yaml id="stage-taskbook-summary"
stage_taskbook:
  document_type: stage_taskbook
  schema_version: stage_taskbook.discussion_draft.v1
  stage_id: stage_03_external_taskbook_import
  stage_name: External Taskbook Import Protocol
  chinese_name: 外部任务书导入协议
  status: discussion_draft
  authority_status: planning_reference_only
  master_stage_status_ref: planned
  mvp_scope: included
  mvp_loop_name: Stage 0-6 Thin Governed Loop
  mvp_implementation_mode: thin_by_default
  target_repository: /home/jenn/src/colameta-dev
  created_from_head: c0ed30d
  created_from_head_meaning: historical_creation_baseline_not_current_freeze_snapshot
```

`External Taskbook Import Protocol` = 外部任务书导入协议。中文意思是：ChatGPT
或 Commander 写出来的版本任务书，进入 ColaMeta 时只能先作为待校验的 claim，
不能直接变成事实、计划修改或执行命令。

`master_stage_status_ref` = Master 里的阶段状态引用。中文意思是：Master 说
Stage 3 是 `planned`，但这份 Stage Taskbook 文件本身仍然只是
`discussion_draft` 草稿。

---

## 1. Master And Stage Binding

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
  project_final_goal_ref: master_taskbook.project_final_goal
  supports_project_goal: true
```

`stage_taskbook_ref` = 阶段任务书引用。中文意思是：版本任务书必须说明自己属于
哪个阶段，而不是直接挂在总目标下面乱跑。

---

## 2. Stage Purpose

Stage 3 defines the smallest safe path for externally authored Version
Execution Taskbooks to enter ColaMeta through validation, preview, and bounded
mapping.

It keeps external taskbooks as claims until separately adopted through an
approved import gate.

---

## 3. Entry Criteria

```yaml id="entry-criteria"
entry_criteria:
  required:
    - Master Taskbook can be referenced
    - Stage Taskbook can be referenced
    - minimum external taskbook fields are known
  explicitly_not_required:
    - executor dispatch
    - automatic task acceptance
    - general document ingestion
    - codex-router bridge
```

---

## 4. Exit Criteria

```yaml id="exit-criteria"
exit_criteria:
  required:
    - external taskbook schema exists
    - external taskbook validator exists
    - import preview can show recognized and rejected fields
    - invalid format is rejected
    - hash mismatch fails closed
    - allowed_files and forbidden_files are required
    - acceptance_commands and manual_acceptance are explicit
    - imported taskbook maps to a bounded version task candidate
  not_exit_criteria:
    - automatic plan mutation
    - automatic allowed_files expansion
    - automatic executor dispatch
    - automatic commit
```

---

## 5. Deliverables

```yaml id="deliverables"
deliverables:
  minimum:
    - external_taskbook_schema
    - external_taskbook_validator
    - taskbook_import_preview
    - taskbook_to_version_candidate_mapping
    - taskbook_rejection_reasons
  optional_after_minimum:
    - import_adoption_preview_after_hard_gate
    - normalized_taskbook_receipt
```

---

## 6. Version Directions

```yaml id="version-directions"
version_directions:
  preferred_sequence:
    - External Taskbook Schema V1
    - External Taskbook Validator V1
    - Taskbook Import Preview V1
    - Taskbook-to-Version-Candidate Mapping V1
    - Taskbook Import Adoption Preview V1
  apply_boundary: import_adoption_requires_separate_commander_hard_gate
  mutation_boundary: import_preview_and_mapping_must_not_mutate_plan
```

`Version Directions` = 版本方向。中文意思是：Stage 3 后续可以拆成这些更小的
Version Execution Taskbook；其中 `Import Adoption` 必须单独过 Commander
硬授权，而且 preview/mapping 不能自动改 plan。

---

## 7. Gate-Readiness Criteria

```yaml id="gate-readiness-criteria"
gate_readiness_criteria:
  - Taskbook must contain master_taskbook_ref.
  - Taskbook must contain stage_taskbook_ref.
  - Taskbook must contain allowed_files and forbidden_files.
  - Taskbook must contain acceptance_commands.
  - Taskbook must contain manual_acceptance.
  - Taskbook must contain out_of_scope.
  - Taskbook must explain how it supports stage and master goals.
  - Invalid format is rejected.
  - Hash mismatch fails closed.
```

### 7.1 Minimum External Taskbook Fields

```yaml id="minimum-external-taskbook-fields"
minimum_external_taskbook_fields:
  required_fields:
    - source
    - provenance
    - external_taskbook_hash
    - expected_hash_authority_ref
    - master_taskbook_ref
    - stage_taskbook_ref
    - allowed_files
    - forbidden_files
    - acceptance_commands
    - manual_acceptance
    - out_of_scope
    - supports_stage_and_master_goals
  rejection_fields:
    - rejected_fields
    - rejection_reasons
    - known_conflicts
  normalized_output_fields:
    - normalized_claims
    - normalized_output_candidate
    - version_candidate_mapping
  boundary: >
    This field list supports import preview and validation only. It does not
    authorize plan mutation, task adoption, execution, commit, push, or route
    transition.
```

`expected_hash_authority_ref` = 预期哈希权威引用。中文意思是：说明外部任务书的
期望 hash 应该由哪份授权材料或回执来提供，不能凭空声称 hash 正确。

`acceptance_commands` = 验收命令。中文意思是：这些命令用于验证候选任务，
不是交付状态验收授权。

`manual_acceptance` = 人工验收要求。中文意思是：说明后续需要人工或 Reviewer
看什么，不等于 `delivery_state: accepted`。

### 7.2 Stage 0-6 Readiness Contract

```yaml id="stage-0-6-readiness-contract"
stage_0_6_readiness_contract:
  stage_id: stage_03_external_taskbook_import
  minimum_readiness_claim: External taskbooks enter only as claims.
  required_evidence:
    - source
    - provenance
    - import receipt
    - normalized claims
    - conflicts
  gate_question: Can imported claims be reviewed without becoming facts?
  explicit_non_goal: Not trusted state import or general ingestion.
```

---

## 8. Minimum Evidence Package

```yaml id="minimum-evidence-package"
minimum_evidence_package:
  required_fields:
    - source
    - provenance
    - imported_taskbook_hash
    - expected_hash_authority_ref
    - master_taskbook_ref
    - stage_taskbook_ref
    - validation_result
    - rejected_fields
    - rejection_reasons
    - normalized_claims
    - normalized_output_candidate
    - known_conflicts
  must_not_include_as_authority:
    - source reputation alone
    - user silence
    - previous memory
    - runtime status labels
```

`provenance` = 来源证明。中文意思是：说明这份外部任务书从哪里来、什么时候来、
由谁交给 ColaMeta。

---

## 9. Non-Goals

```yaml id="non-goals"
non_goals:
  - no automatic goal expansion
  - no automatic dangerous-scope completion
  - no automatic allowed_files expansion
  - no automatic executor dispatch
  - no automatic commit or push
```

---

## 10. Next Recommended Step

```text id="next-recommended-step"
After Stage 2 can register Stage Taskbooks, define the smallest Version
Execution Taskbook import schema and rejection preview.
```

中文解释：Stage 3 的第一刀是“导入前先看懂、先拒错”，不是接上执行器就跑。
