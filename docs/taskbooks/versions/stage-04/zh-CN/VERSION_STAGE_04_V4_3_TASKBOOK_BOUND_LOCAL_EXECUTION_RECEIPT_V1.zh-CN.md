# Version 中文任务书：Stage 4 / v4.3 任务书绑定本地执行回执 V1

```yaml id="version-stage-04-v4-3-zh-cn-summary"
chinese_companion:
  source_document: docs/taskbooks/versions/stage-04/VERSION_STAGE_04_V4_3_TASKBOOK_BOUND_LOCAL_EXECUTION_RECEIPT_V1.md
  source_sha256: d1ff43bf57a3279ed801a6440d7a8ead382d23873035878d560c74bf277d1342
  translation_status: companion_draft
  authority_status: planning_reference_only
version_execution_taskbook:
  version_id: stage_04_v4_3_taskbook_bound_local_execution_receipt_v1
  version: v4.3
  chinese_name: 任务书绑定本地执行回执 V1
  status: discussion_draft
  execution_authorization_status: not_authorized
```

## 1. 这份任务书是什么

这是 Stage 4 的第三份 Version 任务书草稿。

`Taskbook-bound Local Execution Receipt V1` = 任务书绑定本地执行回执 V1。

中文意思是：定义本地执行已经发生之后必须留下什么证据。它不授权执行，只约束回执
格式和真实性。

它现在不授权实现，不授权 executor，不授权 commit，不授权 push，不授权 fetch/pull，
也不授权 plan mutation、review acceptance、Delivery State Gate transition 或
accepted delivery state。

## 2. 父级绑定

这份 Version 绑定到：

- Master Taskbook：`PROJECT_MASTER_TASKBOOK.md`
  - hash：`1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34`
- Stage 4 Taskbook：`docs/taskbooks/stages/STAGE_04_BOUNDED_EXECUTION_AND_EVIDENCE.md`
  - hash：`05e6114a666942c0641c635905c2295feaa62b98bd9e7b5166babd662e015a41`
- previous version v4.2：
  - hash：`e4f02abe34af18ea0b1ef8cc94006dc5dddf04e0e80f0ca65f9f393ae8b617a2`
- Stage 3 Version set confirmation：
  - hash：`8695cf9f9b29608011dfc4691fd12df5a4f21f879e025e999c8bba5ae929e313`

中文解释：回执是“实际发生了什么”的证据，不是“审查已经通过”的判决。

## 3. 目标

本版本要定义本地执行回执：

- 绑定 `local_execution_authorization_ref`；
- 绑定 `execution_envelope_ref`；
- 绑定 `run_preview_ref`；
- 记录 command attempts；
- 记录 touched files；
- 记录 observed mutations；
- 记录 validation commands 和 validation results；
- 记录 blocked 或 failed reasons；
- 记录 known gaps 和 remaining risks。

## 4. 不做什么

v4.3 不做：

- executor dispatch；
- imported receipt adoption；
- executor report aggregation；
- plan mutation；
- review acceptance；
- delivery state accepted。

## 5. 候选写入范围

未来如果 Commander 单独授权执行，本版本候选写入范围最多包括：

- `runner/local_execution_receipt.py`
- `tests/test_local_execution_receipt.py`
- `docs/taskbooks/versions/stage-04/evidence/VERSION_STAGE_04_V4_3_LOCAL_EXECUTION_RECEIPT_REPORT.md`
- `docs/taskbooks/versions/stage-04/evidence/zh-CN/VERSION_STAGE_04_V4_3_LOCAL_EXECUTION_RECEIPT_REPORT.zh-CN.md`

这些现在只是候选路径，不是当前授权。

## 6. 本地执行回执最小合约

本地执行回执至少需要：

- `receipt_id`；
- `receipt_kind`；
- `local_execution_authorization_ref`；
- `execution_envelope_ref`；
- `run_preview_ref`；
- `version_taskbook_ref`；
- `master_taskbook_hash`；
- `stage_taskbook_hash`；
- `started_at`；
- `completed_at`；
- `command_attempts`；
- `touched_files`；
- `observed_mutations`；
- `validation_commands`；
- `validation_results`；
- `scope_check_result`；
- `blocked_or_failed_reasons`；
- `known_gaps`；
- `remaining_risks`。

它必须区分：

- executed；
- validated；
- reviewed；
- accepted。

## 7. 人工验收条件

审查者可以接受 v4.3 的条件包括：

- receipt 绑定 `local_execution_authorization_ref`；
- receipt 绑定 `execution_envelope_ref` 和 `run_preview_ref`；
- receipt 区分 executed 和 validated；
- receipt 记录 touched files 和 observed mutations；
- 证据报告区分 `commands_run` 和 `commands_not_run`。

不能接受的情况包括：

- receipt 声称 review acceptance；
- receipt 声称 delivery_state accepted；
- receipt 隐藏 validation failure；
- receipt 把 runtime PASSED label alone 当作 proof。

## 8. 下一步交接

v4.3 通过后，才能交给 v4.4 做 `Imported Execution Receipt`。

中文意思是：本地执行回执和外部导入回执必须分开定义，不能把一种授权偷换成另一种。
