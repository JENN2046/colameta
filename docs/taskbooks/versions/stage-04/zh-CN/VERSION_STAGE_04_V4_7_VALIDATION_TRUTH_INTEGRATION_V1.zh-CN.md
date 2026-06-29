# Version 中文任务书：Stage 4 / v4.7 验证真相集成 V1

```yaml id="version-stage-04-v4-7-zh-cn-summary"
chinese_companion:
  source_document: docs/taskbooks/versions/stage-04/VERSION_STAGE_04_V4_7_VALIDATION_TRUTH_INTEGRATION_V1.md
  source_sha256: 755b33635c24eb450162de4bad1e0c8e17c38cf8a4eb83887cda985cf6dea8e5
  translation_status: companion_draft
  authority_status: planning_reference_only
version_execution_taskbook:
  version_id: stage_04_v4_7_validation_truth_integration_v1
  version: v4.7
  chinese_name: 验证真相集成 V1
  status: discussion_draft
  execution_authorization_status: not_authorized
```

## 1. 这份任务书是什么

`Validation Truth Integration V1` = 验证真相集成 V1。

中文意思是：把 validation commands、实际结果、失败原因和未运行状态统一成可审查的
真相字段，防止把失败或未运行包装成 passed。

它不授权执行验证命令，不授权 review acceptance，也不授权 delivery state accepted。

## 2. 父级绑定

- Master Taskbook hash：`1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34`
- Stage 4 Taskbook hash：`05e6114a666942c0641c635905c2295feaa62b98bd9e7b5166babd662e015a41`
- previous version v4.6 hash：`320366232e7ad5b436d73178a60452766d3ce526c1fdf963a7a6e9395a62c8a4`
- Stage 3 Version set confirmation hash：`8695cf9f9b29608011dfc4691fd12df5a4f21f879e025e999c8bba5ae929e313`

## 3. 验证真相最小合约

至少记录：

- `validation_command`；
- `command_source_ref`；
- `execution_status`；
- `exit_code`；
- `output_summary`；
- `evidence_ref`；
- `failure_reason`；
- `blocker_reason`；
- `known_gaps`；
- `authority_boundary`。

允许的状态只有：`passed`、`failed`、`blocked`、`not_run`、`unvalidated`。

不能接受：failed/not_run/unvalidated 被总结成 passed，或只靠 runtime label 当真相。
