# Version 中文任务书：Stage 4 / v4.6 执行证据回执 V1

```yaml id="version-stage-04-v4-6-zh-cn-summary"
chinese_companion:
  source_document: docs/taskbooks/versions/stage-04/VERSION_STAGE_04_V4_6_EXECUTION_EVIDENCE_RECEIPT_V1.md
  source_sha256: 320366232e7ad5b436d73178a60452766d3ce526c1fdf963a7a6e9395a62c8a4
  translation_status: companion_draft
  authority_status: planning_reference_only
version_execution_taskbook:
  version_id: stage_04_v4_6_execution_evidence_receipt_v1
  version: v4.6
  chinese_name: 执行证据回执 V1
  status: discussion_draft
  execution_authorization_status: not_authorized
```

## 1. 这份任务书是什么

`Execution Evidence Receipt V1` = 执行证据回执 V1。

中文意思是：把执行报告、回执和关键证据打成一个可引用的 evidence receipt，但它仍然
不是 review decision。

它不授权 executor、commit、push、review acceptance 或 delivery state accepted。

## 2. 父级绑定

- Master Taskbook hash：`1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34`
- Stage 4 Taskbook hash：`05e6114a666942c0641c635905c2295feaa62b98bd9e7b5166babd662e015a41`
- previous version v4.5 hash：`55bf66619ecf07ea0aa71a39a9795018f7f45d03b9788301eaf4846ae9582b2f`
- Stage 3 Version set confirmation hash：`8695cf9f9b29608011dfc4691fd12df5a4f21f879e025e999c8bba5ae929e313`

## 3. 目标

本版本要定义 evidence receipt：

- 绑定 executor report refs；
- 绑定 execution receipt refs；
- 绑定 changed files summary；
- 绑定 validation truth summary；
- 绑定 scope summary；
- 记录 evidence hashes；
- 保留 known gaps 和 remaining risks；
- 不声称 review acceptance 或 delivery_state accepted。

## 4. 候选写入范围

未来如果 Commander 单独授权执行，本版本候选写入范围最多包括：

- `runner/execution_evidence_receipt.py`
- `tests/test_execution_evidence_receipt.py`
- `docs/taskbooks/versions/stage-04/evidence/VERSION_STAGE_04_V4_6_EXECUTION_EVIDENCE_RECEIPT_REPORT.md`
- `docs/taskbooks/versions/stage-04/evidence/zh-CN/VERSION_STAGE_04_V4_6_EXECUTION_EVIDENCE_RECEIPT_REPORT.zh-CN.md`

这些现在只是候选路径，不是当前授权。

## 5. 人工验收条件

审查者可以接受 v4.6 的条件包括：

- evidence receipt 绑定 executor report refs；
- evidence receipt 绑定 execution receipt refs；
- evidence receipt 保留 evidence hashes；
- evidence receipt 保留 known gaps 和 remaining risks。

不能接受的情况包括：

- evidence receipt 声称 review acceptance；
- evidence receipt 声称 delivery_state accepted；
- evidence receipt 丢掉 validation truth summary；
- evidence receipt 隐藏 scope summary。
