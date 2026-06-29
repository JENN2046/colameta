# Version 中文任务书：Stage 3 / v3.2 外部任务书校验器 V1

```yaml id="version-stage-03-v3-2-zh-cn-summary"
chinese_companion:
  source_document: docs/taskbooks/versions/stage-03/VERSION_STAGE_03_V3_2_EXTERNAL_TASKBOOK_VALIDATOR_V1.md
  source_sha256: 7bdf06889b25439f9ca8ed70a2e93962f1ab6bec9566fe7b752aa47ad9ebb927
  translation_status: companion_draft
  authority_status: planning_reference_only
version_execution_taskbook:
  version_id: stage_03_v3_2_external_taskbook_validator_v1
  version: v3.2
  chinese_name: 外部任务书校验器 V1
  status: discussion_draft
  execution_authorization_status: not_authorized
```

## 1. 这份任务书是什么

这是 Stage 3 的第二份 Version 任务书草稿。

`External Taskbook Validator V1` = 外部任务书校验器 V1。

中文意思是：读取外部任务书 claim，检查最小字段、hash 权威引用、Master/Stage
绑定、allowed/forbidden 文件、acceptance commands 和越权声明；不通过就 fail closed。

它现在不是执行授权，不授权实现，不授权 executor，不授权 commit，不授权 push，
不授权 fetch/pull，也不授权 plan mutation、import adoption 或 delivery state 变化。

## 2. 父级绑定

这份 Version 绑定到：

- Master Taskbook：`PROJECT_MASTER_TASKBOOK.md`
  - hash：`1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34`
- Stage 3 Taskbook：`docs/taskbooks/stages/STAGE_03_EXTERNAL_TASKBOOK_IMPORT.md`
  - hash：`c5402734ef6990687a6a03ec6b17769f598ff0319b350b6a2371144985ece7ff`
- previous version v3.1：
  - hash：`0d92e1d7779db1d89253986cd40c045dc75b25c0b2f31dbb46143d3b5d1f3232`
- Stage 2 Version set confirmation：
  - hash：`3de9f207f7a80ce1ec3f2cb374c1f10b4903014be18d0dbe6d2defa1224e8f58`

中文解释：校验器只能判断“这份外部任务书 claim 是否合格”，不能替用户补授权。

## 3. 目标

本版本要定义 fail-closed validator：

- 检查必填字段；
- 检查 provenance；
- 检查 hash authority；
- 检查 Master 和 Stage 引用；
- 检查 allowed_files 和 forbidden_files；
- 检查 acceptance_commands 和 manual_acceptance；
- 检查 out_of_scope；
- 拒绝 plan mutation authority；
- 拒绝 executor dispatch authority；
- 拒绝 delivery_state accepted。

`fail closed` = 失败时关闭。中文意思是：不清楚、不完整、不匹配时按“不通过”处理，
不能默认放行。

## 4. 不做什么

v3.2 不做：

- import preview；
- taskbook mapping；
- adoption；
- plan mutation；
- executor dispatch；
- review acceptance；
- Delivery State Gate transition。

## 5. 候选写入范围

未来如果 Commander 单独授权执行，本版本候选写入范围最多包括：

- `runner/external_taskbook_validator.py`
- `tests/test_external_taskbook_validator.py`
- `docs/taskbooks/versions/stage-03/evidence/VERSION_STAGE_03_V3_2_EXTERNAL_TASKBOOK_VALIDATOR_REPORT.md`
- `docs/taskbooks/versions/stage-03/evidence/zh-CN/VERSION_STAGE_03_V3_2_EXTERNAL_TASKBOOK_VALIDATOR_REPORT.zh-CN.md`

这些现在只是候选路径，不是当前授权。

## 6. 校验器输出

校验器至少要输出：

- `validation_result`；
- `recognized_fields`；
- `rejected_fields`；
- `rejection_reasons`；
- `known_conflicts`；
- `normalized_claims_candidate`。

`recognized_fields` = 已识别字段。中文意思是：校验器能看懂哪些字段要列出来。

`rejected_fields` = 被拒字段。中文意思是：不能采信或越权的字段也要列出来。

## 7. 人工验收条件

审查者可以接受 v3.2 的条件包括：

- validator 对缺少必填字段 fail closed；
- validator 对缺少 `expected_hash_authority_ref` fail closed；
- validator 拒绝 plan mutation 和 executor dispatch claims；
- validator 输出 rejected_fields 和 rejection_reasons；
- 证据报告区分 `commands_run` 和 `commands_not_run`。

不能接受的情况包括：

- validator 默默补齐缺失授权；
- validator 把外部任务书当成可信事实；
- validator 接受自动 allowed_files expansion；
- validator 把 manual_acceptance 映射成 delivery_state accepted。

## 8. 下一版本交接

v3.2 交给 v3.3 的是：

- recognized_fields；
- rejected_fields；
- rejection_reasons；
- claim-only boundary。

它不能把自己当成 import adoption authorization、plan mutation authorization 或
execution authorization。
