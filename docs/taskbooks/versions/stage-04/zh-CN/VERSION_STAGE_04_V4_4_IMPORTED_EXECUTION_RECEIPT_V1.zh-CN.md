# Version 中文任务书：Stage 4 / v4.4 导入执行回执 V1

```yaml id="version-stage-04-v4-4-zh-cn-summary"
chinese_companion:
  source_document: docs/taskbooks/versions/stage-04/VERSION_STAGE_04_V4_4_IMPORTED_EXECUTION_RECEIPT_V1.md
  source_sha256: 24adc55f8176e41280ab2b7281d556f727cf714d86e7435124f66a6ed9c7ebc8
  translation_status: companion_draft
  authority_status: planning_reference_only
version_execution_taskbook:
  version_id: stage_04_v4_4_imported_execution_receipt_v1
  version: v4.4
  chinese_name: 导入执行回执 V1
  status: discussion_draft
  execution_authorization_status: not_authorized
```

## 1. 这份任务书是什么

`Imported Execution Receipt V1` = 导入执行回执 V1。

中文意思是：定义外部或人工提供的执行回执如何被登记为 claim-only evidence。它不是
本地执行，也不会自动采纳为事实。

它不授权实现、executor、commit、push、fetch/pull、imported receipt adoption、
review acceptance 或 delivery state accepted。

## 2. 父级绑定

- Master Taskbook hash：`1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34`
- Stage 4 Taskbook hash：`05e6114a666942c0641c635905c2295feaa62b98bd9e7b5166babd662e015a41`
- previous version v4.3 hash：`d1ff43bf57a3279ed801a6440d7a8ead382d23873035878d560c74bf277d1342`
- Stage 3 Version set confirmation hash：`8695cf9f9b29608011dfc4691fd12df5a4f21f879e025e999c8bba5ae929e313`

## 3. 目标

本版本要定义 imported receipt claim：

- 需要 `imported_receipt_authorization_ref`；
- 记录 provenance；
- 记录 source receipt hash；
- 把 commands、touched files、mutations、validation results 都标成 claimed；
- 记录 confidence level、known gaps 和 adoption blockers；
- 不把 imported receipt 当成本地执行或 accepted。

## 4. 候选写入范围

未来如果 Commander 单独授权执行，本版本候选写入范围最多包括：

- `runner/imported_execution_receipt.py`
- `tests/test_imported_execution_receipt.py`
- `docs/taskbooks/versions/stage-04/evidence/VERSION_STAGE_04_V4_4_IMPORTED_EXECUTION_RECEIPT_REPORT.md`
- `docs/taskbooks/versions/stage-04/evidence/zh-CN/VERSION_STAGE_04_V4_4_IMPORTED_EXECUTION_RECEIPT_REPORT.zh-CN.md`

这些现在只是候选路径，不是当前授权。

## 5. 人工验收条件

审查者可以接受 v4.4 的条件包括：

- imported receipt 要求 `imported_receipt_authorization_ref`；
- imported receipt 记录 provenance 和 source hash；
- imported commands 和 mutations 标成 claimed；
- imported receipt 不能授权 local dispatch；
- 证据报告区分 `commands_run` 和 `commands_not_run`。

不能接受的情况包括：

- imported receipt 声称 local execution occurred；
- imported receipt 在没有单独 adoption authority 时被采纳为事实；
- imported receipt 声称 review acceptance；
- imported receipt 声称 delivery_state accepted。
