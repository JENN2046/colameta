# Stage 4 Taskbook: Bounded Execution And Evidence

```yaml id="stage-taskbook-summary"
stage_taskbook:
  document_type: stage_taskbook
  schema_version: stage_taskbook.discussion_draft.v1
  stage_id: stage_04_bounded_execution_and_evidence
  stage_name: Bounded Execution And Evidence
  chinese_name: 有边界执行与证据
  status: discussion_draft
  authority_status: planning_reference_only
  master_stage_status_ref: planned
  mvp_scope: included
  mvp_loop_name: Stage 0-6 Thin Governed Loop
  mvp_implementation_mode: thin_governed_loop
  target_repository: /home/jenn/src/colameta-dev
  created_from_head: c0ed30d
```

`Bounded Execution And Evidence` = 有边界执行与证据。中文意思是：执行必须被
明确的 envelope 限住，并且产出能被审查的 evidence/receipt。

`master_stage_status_ref` = Master 里的阶段状态引用。中文意思是：Master 说
Stage 4 是 `planned`，但这份 Stage Taskbook 文件本身仍然只是
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
```

`ExecutionEnvelope` = 执行信封。中文意思是：把一次执行允许做什么、不能做
什么、用什么命令验证、哪些文件可改，全部包在一个机器可检查的边界里。

---

## 2. Stage Purpose

Stage 4 prepares a bounded, machine-checkable execution envelope from a
separately authorized version task candidate. Dispatch, local execution, and
imported receipt adoption each require their own explicit authority basis.

It does not create a general executor-dispatch platform.

---

## 3. Entry Criteria

```yaml id="entry-criteria"
entry_criteria:
  required:
    - version taskbook has valid master_taskbook_ref
    - version taskbook has valid stage_taskbook_ref
    - local_execution_authorization_ref is explicit when local dispatch is requested
    - imported_receipt_authorization_ref is explicit when imported receipt adoption is requested
    - allowed_files and forbidden_files are explicit
    - validation commands are explicit
  explicitly_not_required:
    - multi-provider dispatch
    - automatic repair
    - automatic review
    - automatic commit
```

---

## 4. Exit Criteria

```yaml id="exit-criteria"
exit_criteria:
  required:
    - execution envelope is machine-checkable
    - invalid envelope fails closed before dispatch
    - envelope schema, run preview, local execution receipt, and imported receipt are distinguishable records
    - execution or imported receipt report binds to version taskbook
    - execution or imported receipt report records master_taskbook_hash and stage_taskbook_hash
    - receipt distinguishes executed, imported, and validated
    - validation failure cannot be summarized as passed
    - scope violation is explicit
    - executor cannot automatically promote delivery_state
    - envelope existence cannot authorize dispatch by itself
  not_exit_criteria:
    - general executor-dispatch platform
    - automatic next-version continuation
    - acceptance review
    - commit or push
```

---

## 5. Deliverables

```yaml id="deliverables"
deliverables:
  minimum:
    - execution_envelope_contract
    - envelope_rejection_rules
    - executor_run_preview
    - local_execution_receipt_contract
    - imported_execution_receipt_contract
    - changed_files_report
    - validation_truth_report
    - scope_check_report
    - taskbook_bound_audit_package
  optional_after_minimum:
    - receipt_hash
    - evidence_package_preview
```

---

## 6. Version Directions

```yaml id="version-directions"
version_directions:
  preferred_sequence:
    - Machine-checkable Execution Envelope V1
    - Taskbook-bound Executor Run Preview V1
    - Taskbook-bound Local Execution Receipt V1
    - Imported Execution Receipt V1
    - Taskbook-bound Executor Report V1
    - Execution Evidence Receipt V1
    - Validation Truth Integration V1
    - Scope Evidence Pack V1
    - Audit Package Taskbook Binding V1
```

`Version Directions` = 版本方向。中文意思是：Stage 4 后续可以拆成这些更小的
Version Execution Taskbook；它们仍不自动授权 executor 运行。

---

## 7. Gate-Readiness Criteria

```yaml id="gate-readiness-criteria"
gate_readiness_criteria:
  - execution envelope must be machine-checkable
  - invalid envelope must fail closed before dispatch
  - envelope existence never authorizes dispatch by itself
  - local dispatch requires local_execution_authorization_ref
  - imported receipt adoption requires imported_receipt_authorization_ref
  - local_execution_authorization_ref cannot authorize imported receipt adoption
  - imported_receipt_authorization_ref cannot authorize local dispatch
  - bounded in-envelope retry, fix, or validation loops may run only when explicitly authorized by the same Version Execution Taskbook and envelope
  - bounded in-envelope retry, fix, or validation loops cannot expand allowed files, commands, network, secrets, destructive operations, timeout, route, or delivery state
  - executor run must bind to a version taskbook
  - execution report must include master_taskbook_hash
  - execution report must include stage_taskbook_hash
  - execution receipt must distinguish executed from validated
  - validation receipt must distinguish validated, unvalidated, not_run, failed, and blocked
  - validation failure cannot be summarized as passed
  - scope violation must be explicit
  - executor cannot automatically commit
  - executor cannot automatically continue across versions
  - executor cannot automatically promote delivery state
```

---

## 8. Minimum Evidence Package

```yaml id="minimum-evidence-package"
minimum_evidence_package:
  required_fields:
    - execution_envelope_ref
    - authority_mode
    - local_execution_authorization_ref
    - imported_receipt_authorization_ref
    - matching_authority_ref_for_authority_mode
    - version_taskbook_ref
    - master_taskbook_hash
    - stage_taskbook_hash
    - allowed_scope
    - observed_mutations
    - validation_command
    - validation_result
    - uncertainty_or_known_gaps
  must_not_include_as_authority:
    - executor self-acceptance
    - validation summary without command evidence
    - runtime PASSED label alone
```

`Receipt` = 回执。中文意思是：记录一次执行或验证实际发生了什么，而不是替它
宣布已经通过。

`authority_mode` = 权限模式。中文意思是：明确这份证据来自本地执行授权还是
外部回执导入授权，二者不能混成一个模糊字段。

---

## 9. Non-Goals

```yaml id="non-goals"
non_goals:
  - no general executor-dispatch platform
  - no multi-provider dispatcher requirement
  - no router integration
  - no automatic repair
  - no automatic review
  - no automatic cross-version continue
  - no automatic commit
  - no automatic push
```

---

## 10. Next Recommended Step

```text id="next-recommended-step"
After Stage 3 can import valid Version Execution Taskbooks, define the smallest
ExecutionEnvelope and Receipt records that can prove bounded local execution.
```

中文解释：Stage 4 第一刀是让“能跑”变成“有边界地跑，并留下证据”。
