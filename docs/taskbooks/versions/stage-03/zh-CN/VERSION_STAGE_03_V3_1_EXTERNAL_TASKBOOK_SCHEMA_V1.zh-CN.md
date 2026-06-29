# Version 中文任务书：Stage 3 / v3.1 外部任务书模式 V1

```yaml id="version-stage-03-v3-1-zh-cn-summary"
chinese_companion:
  source_document: docs/taskbooks/versions/stage-03/VERSION_STAGE_03_V3_1_EXTERNAL_TASKBOOK_SCHEMA_V1.md
  source_sha256: 0d92e1d7779db1d89253986cd40c045dc75b25c0b2f31dbb46143d3b5d1f3232
  translation_status: companion_draft
  authority_status: planning_reference_only
version_execution_taskbook:
  version_id: stage_03_v3_1_external_taskbook_schema_v1
  version: v3.1
  chinese_name: 外部任务书模式 V1
  status: discussion_draft
  execution_authorization_status: not_authorized
```

## 1. 这份任务书是什么

这是 Stage 3 的第一份 Version 任务书草稿。

`External Taskbook Schema V1` = 外部任务书模式 V1。

中文意思是：先定义一份外部 Version Execution Taskbook 进入 ColaMeta 前必须携带的
字段。外部任务书进入时只是 claim，也就是“待审查声明”，不是事实、计划修改或执行
命令。

它现在不是执行授权，不授权实现，不授权 executor，不授权 commit，不授权 push，
不授权 fetch/pull，也不授权 plan mutation、import adoption 或 delivery state 变化。

## 2. 父级绑定

这份 Version 绑定到：

- Master Taskbook：`PROJECT_MASTER_TASKBOOK.md`
  - hash：`1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34`
- Stage 3 Taskbook：`docs/taskbooks/stages/STAGE_03_EXTERNAL_TASKBOOK_IMPORT.md`
  - hash：`c5402734ef6990687a6a03ec6b17769f598ff0319b350b6a2371144985ece7ff`
- Stage 2 Version set confirmation：
  - hash：`3de9f207f7a80ce1ec3f2cb374c1f10b4903014be18d0dbe6d2defa1224e8f58`

中文解释：v3.1 只能服务“外部任务书导入协议”。它不能把外部任务书直接变成内部计划。

## 3. 目标

本版本要定义外部任务书最小字段：

- `source`：来源；
- `provenance`：来源证明；
- `external_taskbook_hash`：外部任务书 hash；
- `expected_hash_authority_ref`：预期哈希权威引用；
- `master_taskbook_ref`：主任务书引用；
- `stage_taskbook_ref`：阶段任务书引用；
- `allowed_files`：允许文件；
- `forbidden_files`：禁止文件；
- `acceptance_commands`：验收命令；
- `manual_acceptance`：人工验收要求；
- `out_of_scope`：范围外事项；
- `supports_stage_and_master_goals`：如何支持 Stage 和 Master 目标。

`expected_hash_authority_ref` = 预期哈希权威引用。中文意思是：说明外部任务书的
期望 hash 应该由哪份授权材料或回执来提供，不能凭空声称 hash 正确。

## 4. 不做什么

v3.1 不做：

- import validator；
- import preview renderer；
- plan mutation；
- allowed_files 自动扩展；
- executor dispatch；
- import adoption；
- Delivery State Gate transition；
- accepted delivery state。

## 5. 候选写入范围

未来如果 Commander 单独授权执行，本版本候选写入范围最多包括：

- `.colameta/taskbooks/external_taskbook_schema.json`
- `runner/external_taskbook_schema.py`
- `tests/test_external_taskbook_schema.py`
- `docs/taskbooks/versions/stage-03/evidence/VERSION_STAGE_03_V3_1_EXTERNAL_TASKBOOK_SCHEMA_REPORT.md`
- `docs/taskbooks/versions/stage-03/evidence/zh-CN/VERSION_STAGE_03_V3_1_EXTERNAL_TASKBOOK_SCHEMA_REPORT.zh-CN.md`

这些现在只是候选路径，不是当前授权。

## 6. 模式不能声称什么

外部任务书模式不能声称：

- external taskbook 已经是可信事实；
- external taskbook 可以修改 plan；
- external taskbook 可以授权 execution；
- external taskbook 可以扩展 allowed_files；
- manual_acceptance 等于 delivery_state accepted。

## 7. 人工验收条件

审查者可以接受 v3.1 的条件包括：

- schema 包含 Stage 3 最小外部任务书字段；
- schema 要求 allowed_files 和 forbidden_files；
- schema 要求 acceptance_commands 和 manual_acceptance；
- schema 拒绝 plan mutation 和 execution authority claims；
- 证据报告区分 `commands_run` 和 `commands_not_run`。

不能接受的情况包括：

- schema 把外部任务书当成可信事实；
- schema 允许自动 plan mutation；
- schema 允许自动扩展 allowed_files；
- schema 把 manual_acceptance 映射成 delivery_state accepted。

## 8. 下一版本交接

v3.1 交给 v3.2 的是：

- external taskbook schema minimum contract；
- forbidden authority claims；
- external taskbook as claims only 的边界。

它不能把自己当成 import adoption authorization、plan mutation authorization 或
execution authorization。
