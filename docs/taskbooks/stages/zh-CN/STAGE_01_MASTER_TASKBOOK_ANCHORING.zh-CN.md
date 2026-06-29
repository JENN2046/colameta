# Stage 1 中文任务书：主任务书锚定

```yaml id="stage-01-zh-cn-summary"
chinese_companion:
  source_document: docs/taskbooks/stages/STAGE_01_MASTER_TASKBOOK_ANCHORING.md
  source_sha256: 94fe88c20c9593ea814d8ca76fe5cab6635b70f933819da8108c40320c8e0cce
  translation_status: companion_draft
  authority_status: planning_reference_only
stage:
  stage_id: stage_01_master_taskbook_anchoring
  chinese_name: 主任务书锚定
  status: discussion_draft
```

## 1. 阶段定位

Stage 1 让 Project Master Taskbook 可以被登记、读取、校验、hash、引用，并防止
普通任务静默修改 Master。

它的目的不是生成 Master，也不是让 ColaMeta 自己发明项目目标，而是让所有后续
Stage Taskbook、Version Taskbook、receipt、review package、GateEvent 都能回溯到
同一个 `project_final_goal`。

## 2. Master 绑定

本阶段绑定：

- Master 文件：`PROJECT_MASTER_TASKBOOK.md`
- Master raw snapshot hash：`1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34`
- Review packet：`FREEZE_CANDIDATE_REVIEW_PACKET.md`
- Review packet hash：`2dc1761a5596fc0b41a33da8ef90536aa429d73e0b3f947f05ad4354260531ba`
- Master 当前 review status：`freeze_candidate_confirmed_for_exact_hash`

`freeze_candidate` 只是审查状态，不是 active authority，不授权实现、不授权
executor、不授权 route transition。

## 3. 进入条件

进入 Stage 1 草稿讨论需要：

- 本地仓库路径明确；
- Master 文件存在；
- Master raw snapshot hash 已知；
- freeze-candidate review confirmation 已记录；
- Stage 0 baseline evidence 已记录本地/远端 Git 状态。

不需要 active Master authority、P0 closure 作为实现门、executor run、runtime route
transition 或 codex-router bridge。

## 4. 退出条件

Stage 1 可交给 Stage 2 使用时，需要：

- Master Taskbook 可以按路径和 hash 登记；
- Master 可通过受控本地 API 或 workflow 读取；
- 必填 Master 字段可校验；
- 缺少 `project_final_goal` 时 fail closed；
- raw snapshot hash 或 canonical hash 可确定产生；
- 普通版本任务不能静默修改 Master；
- Master governance 变更必须 Commander hard gate；
- Stage 2 可以引用稳定 `master_taskbook_ref`。

## 5. 交付物

最小交付物方向包括：

- master_taskbook_reference_contract；
- master_taskbook_local_reader；
- master_taskbook_required_field_validator；
- master_taskbook_hash_or_snapshot_digest；
- master_taskbook_registry_record；
- master_taskbook_mutation_hard_gate_policy。

这些都只是 Stage 1 方向，不是当前执行授权。

## 6. 版本方向

优先版本方向：

- Master Taskbook Registry V1；
- Master Taskbook Reader V1；
- Master Taskbook Validator V1；
- Master Hash Binding V1；
- Master Mutation Hard Gate V1。

## 7. 非规范实现草图

英文源文件中列出的 registry path、CLI command shape、candidate files、validation
command 都只是 `Non-Normative Implementation Sketches`，中文意思是“非规范实现草图”。

它们不是：

- allowed files；
- execution envelope；
- command authorization；
- commit authorization；
- push authorization；
- route transition authorization；
- registry mutation authorization；
- Master mutation authorization。

## 8. 状态和权威边界

Stage Taskbook 只拥有阶段目的、进入条件、退出条件、交付物、版本方向、gate
readiness、non-goals。它不拥有 runtime facts、accepted delivery state、
ReviewDecision outcome authority、GateEvent outcome authority、Commander
authorization 或 executor dispatch authority。

只有 Delivery State Gate 通过 GateEvent 才能写 delivery_state。

## 9. 最小证据包

Stage 1 最小证据包需要：

- master_taskbook_path；
- observed_master_hash；
- observed_git_head；
- observed_origin_sync_state；
- validation_command_or_manual_check；
- required_fields_check_result；
- mutation_boundary_check_result；
- known_gaps。

不能把 chat memory、stale executor session state、unaccepted review packet claims、
runtime PASSED/COMPLETED labels 当作权威。

## 10. 非目标

Stage 1 不做自动 Master plan generator、不让 ColaMeta 自己写项目目标、不要求 Web
UI、不重写 state machine、不自动 review、不提升 delivery_state、不授权 executor、
不授权 commit/push、不集成 codex-router。

## 11. 下一步建议

先审查 Stage 1 的范围、权威和顺序，再决定第一份 Version Execution Taskbook。
最可能的第一刀是 Master Taskbook Registry V1，但仍需单独授权。
