# Version 中文任务书：Stage 2 / v2.3 阶段到主任务书绑定 V1

```yaml id="version-stage-02-v2-3-zh-cn-summary"
chinese_companion:
  source_document: docs/taskbooks/versions/stage-02/VERSION_STAGE_02_V2_3_STAGE_TO_MASTER_BINDING_V1.md
  source_sha256: 0699376b9162c0e4ef276996482820c26327e60f5d8371a7193860dbfce6594e
  translation_status: companion_draft
  authority_status: planning_reference_only
version_execution_taskbook:
  version_id: stage_02_v2_3_stage_to_master_binding_v1
  version: v2.3
  chinese_name: 阶段到主任务书绑定 V1
  status: discussion_draft
  execution_authorization_status: not_authorized
```

## 1. 这份任务书是什么

这是 Stage 2 的第三份 Version 任务书草稿。

`Stage-to-Master Binding V1` = 阶段到主任务书绑定 V1。

中文意思是：定义 Stage Taskbook 和 Stage registry 如何绑定同一份
`PROJECT_MASTER_TASKBOOK.md` hash，确保 Stage 不能自己改写 Master，也不能把
Master 的 `freeze_candidate` 状态变成执行授权。

它现在不是执行授权，不授权实现，不授权 executor，不授权 commit，不授权 push，
不授权 fetch/pull，也不授权 Master mutation、project final goal mutation 或
delivery state 变化。

## 2. 父级绑定

这份 Version 绑定到：

- Master Taskbook：`PROJECT_MASTER_TASKBOOK.md`
  - hash：`1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34`
- Stage 2 Taskbook：`docs/taskbooks/stages/STAGE_02_STAGE_TASKBOOK_MANAGEMENT.md`
  - hash：`b0e1a55121503df4116d9c49031eb07729858c483cc73e6c97730eca0a067876`
- previous version v2.2：
  - hash：`d43c791d76df839b0fa361955dc6208af9cce24a7594d045feb4062892f69050`
- Stage 1 Version set confirmation：
  - hash：`c4ef865c84ab634a7b3626cdc6924a4e51420a1d6d94bb274aeb9f13d354fce5`

中文解释：如果 Stage 和 Master 冲突，错的是 Stage 记录，不是 Master 被 Stage 重写。

## 3. 目标

本版本要定义最小 Stage-to-Master binding 规则：

- 每个 registered Stage Taskbook 必须带有精确 `master_taskbook_ref`；
- 必须保留 `project_final_goal_ref`；
- 必须说明 `supports_project_goal` 的理由；
- Master hash 缺失或不匹配时必须 fail closed；
- Stage 不能把 Master `freeze_candidate` 解释成 execution authority；
- Stage 不能声称 delivery_state accepted。

`project_final_goal_ref` = 项目最终目标引用。中文意思是：Stage 必须说明自己服务
哪个最终目标，但不能自己修改最终目标。

## 4. 不做什么

v2.3 不做：

- Master mutation；
- `project_final_goal` 编辑；
- Stage 自动生成；
- registry migration；
- executor dispatch；
- Delivery State Gate transition；
- accepted delivery state。

## 5. 候选写入范围

未来如果 Commander 单独授权执行，本版本候选写入范围最多包括：

- `runner/stage_to_master_binding.py`
- `tests/test_stage_to_master_binding.py`
- `docs/taskbooks/versions/stage-02/evidence/VERSION_STAGE_02_V2_3_STAGE_TO_MASTER_BINDING_REPORT.md`
- `docs/taskbooks/versions/stage-02/evidence/zh-CN/VERSION_STAGE_02_V2_3_STAGE_TO_MASTER_BINDING_REPORT.zh-CN.md`

这些现在只是候选路径，不是当前授权。

## 6. 绑定最小合约

Stage-to-Master binding 至少要检查：

- `master_taskbook_ref.path`；
- `master_taskbook_ref.raw_snapshot_sha256`；
- `master_taskbook_ref.review_status`；
- `project_final_goal_ref`；
- `supports_project_goal`；
- `support_rationale`；
- `source_stage_taskbook_ref`；
- `source_registry_record_ref`。

必须失败关闭的情况包括：

- 缺少 `master_taskbook_ref`；
- Master hash 不匹配；
- 缺少 `project_final_goal_ref`；
- `supports_project_goal` 为 false 或缺失；
- Stage 声称 Master mutation authority；
- Stage 声称 `freeze_candidate` 是 execution authority；
- Stage 声称 delivery_state accepted。

`support_rationale` = 支持理由。中文意思是：Stage 必须说明自己为什么服务项目最终
目标，不能只填一个布尔值。

## 7. 人工验收条件

审查者可以接受 v2.3 的条件包括：

- binding rule 要求精确 Master path 和 raw snapshot hash；
- binding rule 保留 `project_final_goal_ref`；
- binding rule 拒绝缺失或不匹配的 Master ref；
- binding rule 拒绝把 Master `freeze_candidate` 当成 execution authority；
- 证据报告区分 `commands_run` 和 `commands_not_run`。

不能接受的情况包括：

- Stage record 可以覆盖 `project_final_goal`；
- Stage record 可以修改 Master；
- 缺失 Master hash 仍被接受；
- binding result 声称 delivery_state accepted。

## 8. 下一版本交接

v2.3 交给 v2.4 的是：

- 精确 Master binding contract；
- `project_final_goal_ref` preservation；
- `freeze_candidate` 边界。

它不能把自己当成 Master mutation authorization、execution authorization 或
accepted delivery state。
