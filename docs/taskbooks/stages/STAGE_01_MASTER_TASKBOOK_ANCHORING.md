# Stage 1 Taskbook: Master Taskbook Anchoring

```yaml id="stage-taskbook-summary"
stage_taskbook:
  document_type: stage_taskbook
  schema_version: stage_taskbook.discussion_draft.v1
  stage_id: stage_01_master_taskbook_anchoring
  stage_name: Master Taskbook Anchoring
  chinese_name: 主任务书锚定
  status: discussion_draft
  authority_status: planning_reference_only
  master_stage_status_ref: planned_after_stage_00_closeout
  mvp_scope: included
  mvp_loop_name: Stage 0-6 Thin Governed Loop
  target_repository: /home/jenn/src/colameta-dev
  created_from_head: c0ed30d
  created_from_head_meaning: historical_creation_baseline_not_current_freeze_snapshot
```

`Stage Taskbook` = 阶段任务书。它把 Master Taskbook 的总目标拆成一个
阶段目标，但它不是状态权威、不是执行授权、不是验收结论。

`master_stage_status_ref` = Master 里的阶段状态引用。中文意思是：Master 说
Stage 1 是 `planned_after_stage_00_closeout`，但这份 Stage Taskbook 文件本身
仍然只是 `discussion_draft` 草稿。

---

## 1. Master Binding

```yaml id="master-binding"
master_binding:
  master_taskbook_path: PROJECT_MASTER_TASKBOOK.md
  master_taskbook_raw_snapshot_sha256: 1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34
  review_packet_path: FREEZE_CANDIDATE_REVIEW_PACKET.md
  review_packet_sha256: 2dc1761a5596fc0b41a33da8ef90536aa429d73e0b3f947f05ad4354260531ba
  master_review_status: freeze_candidate_confirmed_for_exact_hash
  master_taskbook_ref:
    path: PROJECT_MASTER_TASKBOOK.md
    raw_snapshot_sha256: 1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34
    review_status: freeze_candidate_confirmed_for_exact_hash
  master_authority_boundary:
    - freeze_candidate is review status only
    - not active authority
    - not implementation authorization
    - not executor authorization
    - not route transition authorization
  project_final_goal_ref: master_taskbook.project_final_goal
  supports_project_goal: true
```

Plain Chinese meaning: this Stage binds to the exact Master snapshot already
confirmed for freeze-candidate review. It may use that Master as planning
reference, but it must not claim that the Master has become active execution
authority.

中文解释：这一节的意思是，Stage 1 只能引用这份已经确认 hash 的 Master
草稿作为路线依据，不能把它说成“已经授权实现”。

---

## 2. Stage Purpose

Stage 1 makes the Project Master Taskbook readable, referenceable,
validatable, hashable, and protected against silent modification.

It exists so every later Stage Taskbook, Version Execution Taskbook, execution
envelope, receipt, review package, and GateEvent can trace back to the same
`project_final_goal`.

`project_final_goal` = 项目最终目标。中文意思是：用户给到 ColaMeta 的最高
实现目标，后面所有阶段、版本和执行都要能回溯到它。

---

## 3. Why This Serves The Project Goal

ColaMeta is intended to become a goal-anchored AI delivery command layer. That
cannot work if the highest goal exists only as conversational memory, a loose
document, or a mutable planning note.

Stage 1 turns the Master Taskbook into a governed anchor:

```text id="stage-01-supports-project-goal"
single project_final_goal
        ↓
stable Master Taskbook reference
        ↓
bounded Stage Taskbooks
        ↓
bounded Version Execution Taskbooks
        ↓
evidence-backed delivery review
```

中文解释：Stage 1 的核心不是“多写一个文档”，而是把最高目标固定成后续
所有执行都必须引用的锚点。

---

## 4. Entry Criteria

```yaml id="entry-criteria"
entry_criteria:
  required:
    - local repository path is /home/jenn/src/colameta-dev
    - Master Taskbook exists at PROJECT_MASTER_TASKBOOK.md
    - Master Taskbook raw snapshot hash is known
    - freeze-candidate review confirmation is recorded in FREEZE_CANDIDATE_REVIEW_PACKET.md
    - Stage 0 baseline evidence records observed local and remote Git state
  explicitly_not_required:
    - active Master authority
    - P0 closure as an implementation gate
    - executor run
    - runtime route transition
    - codex-router bridge work
```

`Entry Criteria` = 进入条件。中文意思是：开始 Stage 1 草稿和后续版本设计前，
哪些事实必须已经成立。

---

## 5. Exit Criteria

```yaml id="exit-criteria"
exit_criteria:
  required:
    - Master Taskbook can be registered by path and hash
    - Master Taskbook can be read through a controlled local API or workflow
    - required Master fields can be validated
    - missing project_final_goal fails validation
    - canonical hash or raw snapshot hash can be produced deterministically
    - ordinary version tasks cannot silently modify PROJECT_MASTER_TASKBOOK.md
    - Master mutation requires Commander hard gate
    - Stage 2 can reference a stable master_taskbook_ref
  not_exit_criteria:
    - full taskbook management platform
    - Stage Taskbook registry implementation
    - version taskbook import implementation
    - executor dispatch implementation
    - delivery_state acceptance
```

`Exit Criteria` = 退出条件。中文意思是：Stage 1 做到什么程度，才算能把
“Master 锚定”这件事交给 Stage 2 继续使用。

---

## 6. Deliverables

```yaml id="deliverables"
deliverables:
  minimum:
    - master_taskbook_reference_contract
    - master_taskbook_local_reader
    - master_taskbook_required_field_validator
    - master_taskbook_hash_or_snapshot_digest
    - master_taskbook_registry_record
    - master_taskbook_mutation_hard_gate_policy
  optional_after_minimum:
    - canonical payload extraction preview
    - review packet cross-check
    - CLI status surface
```

`Deliverables` = 交付物。中文意思是：Stage 1 至少要产出哪些可以被代码、
测试或审查引用的东西。

---

## 7. Version Directions

```yaml id="version-directions"
version_directions:
  preferred_sequence:
    - version_name: Master Taskbook Registry V1
      likely_version: v1.11_or_later
      purpose: Register PROJECT_MASTER_TASKBOOK.md by path, hash, and status boundary.
    - version_name: Master Taskbook Reader V1
      likely_version: later_explicit_version
      purpose: Read the registered Master without mutating it.
    - version_name: Master Taskbook Validator V1
      likely_version: later_explicit_version
      purpose: Validate required fields and fail closed on missing goal anchors.
    - version_name: Master Hash Binding V1
      likely_version: later_explicit_version
      purpose: Produce deterministic digest evidence for registered Master references.
    - version_name: Master Mutation Hard Gate V1
      likely_version: later_explicit_version
      purpose: Prevent ordinary version tasks from silently changing Master governance content.
```

`Version Directions` = 版本方向。中文意思是：Stage 1 下面可能拆出来的具体
版本任务，不代表现在已经授权执行。

---

## 8. Gate-Readiness Criteria

```yaml id="gate-readiness-criteria"
gate_readiness_criteria:
  master_reference:
    - PROJECT_MASTER_TASKBOOK.md path is explicit
    - current observed hash is recorded
    - review status is distinguished from active authority
  validation:
    - project_final_goal must be present
    - MVP boundary must be present
    - authority boundaries must be present
    - forbidden usage must be present
    - missing required field fails closed
  mutation_control:
    - version taskbooks may not silently modify Master
    - ordinary executor actions may not mutate Master
    - Commander hard gate is required for Master governance changes
  handoff_to_stage_2:
    - Stage 2 can bind to master_taskbook_ref
    - Stage 2 can distinguish Master claims from accepted delivery state
```

`Gate-Readiness Criteria` = 状态门就绪条件。中文意思是：这些不是验收通过，
而是进入状态门审查前必须准备好的判断材料。

### 8.1 Stage 0-6 Readiness Contract

```yaml id="stage-0-6-readiness-contract"
stage_0_6_readiness_contract:
  stage_id: stage_01_master_taskbook_anchoring
  minimum_readiness_claim: Work is anchored to project_final_goal.
  required_evidence:
    - Master Taskbook goal
    - MVP scope
    - authority rules
    - stage list
  gate_question: Does every downstream claim trace to the single final goal?
  explicit_non_goal: Not multi-goal portfolio planning.
```

---

## 9. Minimum Evidence Package

```yaml id="minimum-evidence-package"
minimum_evidence_package:
  required_fields:
    - master_taskbook_path
    - observed_master_hash
    - observed_git_head
    - observed_origin_sync_state
    - validation_command_or_manual_check
    - required_fields_check_result
    - mutation_boundary_check_result
    - known_gaps
  must_not_include_as_authority:
    - chat memory
    - stale executor session state
    - unaccepted review packet claims
    - runtime PASSED or COMPLETED labels
```

`Minimum Evidence Package` = 最小证据包。中文意思是：只收足够判断 Stage 1
是否可继续的证据，不做庞大审计系统。

---

## 10. State And Authority Boundaries

```yaml id="state-authority-boundaries"
state_authority_boundaries:
  stage_taskbook_owns:
    - stage purpose
    - stage entry criteria
    - stage exit criteria
    - stage deliverables
    - version directions
    - gate-readiness criteria
    - non-goals
  stage_taskbook_must_not_own:
    - runtime facts
    - accepted delivery state
    - ReviewDecision outcome authority
    - GateEvent outcome authority
    - Commander authorization
    - executor dispatch authority
  accepted_state_rule:
    only_delivery_state_gate_via_gate_event_may_write_delivery_state: true
```

中文解释：Stage Taskbook 只能定义“这个阶段要证明什么”，不能自己宣布
accepted，也不能替 Commander 授权。

---

## 11. Non-Goals

```yaml id="non-goals"
non_goals:
  - no automatic master-plan generator
  - no ColaMeta-authored project goals
  - no Web UI requirement
  - no state-machine rewrite
  - no automatic review
  - no automatic delivery_state promotion
  - no executor run authorization
  - no commit or push authorization
  - no codex-router integration
```

`Non-Goals` = 非目标。中文意思是：Stage 1 明确不做这些事，防止范围膨胀。

---

## 12. Open Questions

```yaml id="open-questions"
open_questions:
  - Should Stage 1 registry use a new docs/taskbooks registry file or reuse existing runner state storage?
  - Should the first implementation slice be registry-only, reader-only, or registry-plus-reader?
  - Should raw snapshot hash be sufficient for Stage 1 MVP, with canonical hash binding deferred?
  - Which command should become the first read-only status surface for Master registration?
```

These questions are discussion inputs only. They do not block this Stage
Taskbook draft from existing as a planning artifact.

### 12.1 Non-Normative Implementation Sketches

These sketches are non-authorizing discussion inputs for a later Stage 1
Version Execution Taskbook. They are not baseline authority, route authority,
implementation authorization, allowed files, an execution envelope, command
authorization, commit authorization, push authorization, or route-transition
authorization.

```yaml id="non-normative-implementation-sketches"
non_normative_implementation_sketches:
  registry_storage:
    decision: use_repo_tracked_colameta_registry_file
    proposed_path: .colameta/taskbooks/master_taskbook_registry.json
    authorization_boundary: requires_separate_version_execution_taskbook
    reason: >
      Master registration is governance metadata. It should be versioned with
      the project, while runtime mirrors under .colameta/runtime remain
      non-authoritative.
  first_slice:
    decision: registry_only_first
    authorization_boundary: requires_separate_version_execution_taskbook
    reason: >
      The first Version Execution Taskbook should register path, hash, review
      status boundary, and observed HEAD. Reader, validator, and canonical hash
      binding can follow as smaller slices.
  hash_policy_for_mvp:
    decision: raw_snapshot_hash_is_sufficient_for_first_registry_mvp
    reason: >
      The confirmed Master already has a raw snapshot hash. Canonical payload
      binding is valuable but should not be required before the registry can
      safely record the Master reference.
  first_read_only_status_surface:
    decision: add_cli_master_taskbook_status_after_registry_exists
    proposed_command_shape: colameta master-taskbook-status /path/to/project
    authorization_boundary: requires_separate_version_execution_taskbook
    reason: >
      A read-only CLI status surface matches current ColaMeta operational
      habits and can later be mirrored into MCP or Web Console without changing
      the registry contract.
```

These sketches do not allow this Stage Taskbook to create `.colameta/taskbooks`,
add a CLI command, mutate registry files, run commands, or claim Master active
authority. Candidate paths and command shapes are examples for later debate,
not `allowed_files`, not `acceptance_commands`, and not executable authority.

### 12.2 First Version Slice Draft

```yaml id="first-version-slice-draft"
first_version_slice_draft:
  candidate_name: Master Taskbook Registry V1
  status: draft_input_only
  allowed_file_candidates:
    - .colameta/taskbooks/master_taskbook_registry.json
    - runner/master_taskbook_registry.py
    - tests/test_master_taskbook_registry.py
  validation_command_candidates:
    - python -m unittest tests.test_master_taskbook_registry
  expected_receipt_fields:
    - master_taskbook_path
    - raw_snapshot_sha256
    - review_status_boundary
    - observed_git_head
    - observed_origin_sync_state
    - created_by_version_taskbook_ref
  authorization_boundary: >
    This is a draft slice description only. It requires a separate Version
    Execution Taskbook before any file edit, command execution, commit, push,
    route transition, registry mutation, or Master Taskbook mutation.
```

中文解释：

- `non_normative_implementation_sketches` = 非规范实现草图。中文意思是：只是给后续 Version Taskbook 讨论用，不是现在的路线授权。
- `registry_storage` = 登记存储位置。这里只是候选草图，不是允许创建文件。
- `first_slice` = 第一刀实现范围。建议先只做 registry，不把 reader、validator、canonicalizer 混在同一刀。
- `hash_policy_for_mvp` = MVP 哈希策略。第一步先用 raw snapshot hash，canonical hash 后面再接。
- `first_read_only_status_surface` = 第一条只读状态入口。建议以后做 `colameta master-taskbook-status /path/to/project`。
- `first_version_slice_draft` = 第一版任务切片草案。中文意思是：只是为后面写 Version Taskbook 准备材料，不是现在开工。

---

## 13. Next Recommended Step

```text id="next-recommended-step"
Review this Stage 1 Taskbook draft for scope, authority, and sequencing.
Then decide the first Version Execution Taskbook under Stage 1.
The likely first version is Master Taskbook Registry V1.
```

中文解释：下一步不是直接实现整套 Stage 1，而是先确认这个阶段任务书的边界，
然后只挑第一个 Version 任务，例如 Master Taskbook Registry V1。
