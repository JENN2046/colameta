# Version 中文任务书：Stage 2 / v2.2 阶段任务书登记表 V1

```yaml id="version-stage-02-v2-2-zh-cn-summary"
chinese_companion:
  source_document: docs/taskbooks/versions/stage-02/VERSION_STAGE_02_V2_2_STAGE_TASKBOOK_REGISTRY_V1.md
  source_sha256: d43c791d76df839b0fa361955dc6208af9cce24a7594d045feb4062892f69050
  translation_status: companion_draft
  authority_status: planning_reference_only
version_execution_taskbook:
  version_id: stage_02_v2_2_stage_taskbook_registry_v1
  version: v2.2
  chinese_name: 阶段任务书登记表 V1
  status: discussion_draft
  execution_authorization_status: not_authorized
```

## 1. 这份任务书是什么

这是 Stage 2 的第二份 Version 任务书草稿。

`Stage Taskbook Registry V1` = 阶段任务书登记表 V1。

中文意思是：定义一份机器可读的登记表，用来记录每个 Stage Taskbook 的 ID、路径、
hash、Master 绑定、v2.1 校验结果和 gate-readiness 摘要。

它现在不是执行授权，不授权实现，不授权 executor，不授权 commit，不授权 push，
不授权 fetch/pull，也不授权 registry mutation 或 delivery state 变化。

## 2. 父级绑定

这份 Version 绑定到：

- Master Taskbook：`PROJECT_MASTER_TASKBOOK.md`
  - hash：`1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34`
- Stage 2 Taskbook：`docs/taskbooks/stages/STAGE_02_STAGE_TASKBOOK_MANAGEMENT.md`
  - hash：`b0e1a55121503df4116d9c49031eb07729858c483cc73e6c97730eca0a067876`
- previous version v2.1：
  - hash：`76c3c12c191609f94c16d292e40217db08c8020792157639011b046cb977c429`
- Stage 1 Version set confirmation：
  - hash：`c4ef865c84ab634a7b3626cdc6924a4e51420a1d6d94bb274aeb9f13d354fce5`

中文解释：v2.2 必须消费 v2.1 的 schema/validator 合约，不能绕过校验直接登记。

## 3. 目标

本版本的目标是定义 Stage Taskbook registry 的最小字段：

- `stage_id`；
- `stage_name`；
- `stage_taskbook_path`；
- `stage_taskbook_raw_snapshot_sha256`；
- `master_taskbook_ref`；
- `supports_project_goal`；
- `validator_result`；
- `gate_readiness_summary`；
- `non_goals_summary`；
- `authority_boundary`；
- `source_version_taskbook_ref`；
- `observed_git_head`；
- `created_at`。

`validator_result` = 校验结果。中文意思是：Stage Taskbook 先经过 v2.1 校验器，再
被登记；登记表不能把未校验文档当成已就绪。

## 4. 不做什么

v2.2 不做：

- bootstrap migration；
- 自动生成 Stage；
- registry mutation authorization；
- executor dispatch；
- Delivery State Gate transition；
- accepted delivery state；
- Master 或 Stage Taskbook 内容修改。

## 5. 候选写入范围

未来如果 Commander 单独授权执行，本版本候选写入范围最多包括：

- `.colameta/taskbooks/stage_taskbook_registry.json`
- `runner/stage_taskbook_registry.py`
- `tests/test_stage_taskbook_registry.py`
- `docs/taskbooks/versions/stage-02/evidence/VERSION_STAGE_02_V2_2_STAGE_TASKBOOK_REGISTRY_REPORT.md`
- `docs/taskbooks/versions/stage-02/evidence/zh-CN/VERSION_STAGE_02_V2_2_STAGE_TASKBOOK_REGISTRY_REPORT.zh-CN.md`

这些现在只是候选路径，不是当前授权。

## 6. 登记表不能声称什么

Stage Taskbook registry 不能声称：

- registered stage 已经是 accepted delivery state；
- registered stage 自动授权 execution；
- registry 可以修改 Stage Taskbook；
- registry 可以覆盖 Delivery State Gate。

## 7. 候选验收命令

英文任务书列出的候选命令包括：

- `git status --short --branch`
- `git rev-parse HEAD`
- `sha256sum docs/taskbooks/stages/STAGE_02_STAGE_TASKBOOK_MANAGEMENT.md docs/taskbooks/versions/stage-02/VERSION_STAGE_02_V2_1_STAGE_TASKBOOK_SCHEMA_VALIDATOR_V1.md`
- `python -m unittest tests.test_stage_taskbook_registry`
- `python -m compileall runner/stage_taskbook_registry.py`

这些命令是未来执行授权后的候选命令，不是当前已经授权运行。

## 8. 人工验收条件

审查者可以接受 v2.2 的条件包括：

- registry record 包含 Stage Taskbook path 和 hash；
- registry record 绑定精确 `master_taskbook_ref`；
- registry record 消费 `validator_result`，不绕过校验；
- registry record 区分 gate-readiness 与 delivery_state accepted；
- 证据报告区分 `commands_run` 和 `commands_not_run`。

不能接受的情况包括：

- registry 可以标记 Stage accepted；
- registry 可以授权 execution；
- registry 修改 Stage Taskbook 源文件；
- registry 接受缺失的 `validator_result`。

## 9. 下一版本交接

v2.2 交给 v2.3 的是：

- registry 可以记录精确 `master_taskbook_ref`；
- registry 可以记录 `validator_result`；
- registry 保留 authority boundary。

它不能把自己当作 execution authorization 或 accepted delivery state。
