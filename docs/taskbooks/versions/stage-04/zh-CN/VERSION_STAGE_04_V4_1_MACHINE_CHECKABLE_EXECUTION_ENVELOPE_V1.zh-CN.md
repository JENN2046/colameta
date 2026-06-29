# Version 中文任务书：Stage 4 / v4.1 机器可检查执行信封 V1

```yaml id="version-stage-04-v4-1-zh-cn-summary"
chinese_companion:
  source_document: docs/taskbooks/versions/stage-04/VERSION_STAGE_04_V4_1_MACHINE_CHECKABLE_EXECUTION_ENVELOPE_V1.md
  source_sha256: 22e99e01a854c6d8fe1fc4f0ceba38f5d2b1ce28d796596f80f4292459071dfa
  translation_status: companion_draft
  authority_status: planning_reference_only
version_execution_taskbook:
  version_id: stage_04_v4_1_machine_checkable_execution_envelope_v1
  version: v4.1
  chinese_name: 机器可检查执行信封 V1
  status: discussion_draft
  execution_authorization_status: not_authorized
```

## 1. 这份任务书是什么

这是 Stage 4 的第一份 Version 任务书草稿。

`Machine-checkable Execution Envelope V1` = 机器可检查执行信封 V1。

中文意思是：把一次候选执行允许做什么、禁止做什么、绑定哪个 Version Taskbook、
用什么命令验证，全部变成机器可检查的边界对象。它本身不授权 dispatch。

它现在不授权实现，不授权 executor，不授权 commit，不授权 push，不授权 fetch/pull，
也不授权 plan mutation、import adoption、Delivery State Gate transition 或 accepted
delivery state。

## 2. 父级绑定

这份 Version 绑定到：

- Master Taskbook：`PROJECT_MASTER_TASKBOOK.md`
  - hash：`1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34`
- Stage 4 Taskbook：`docs/taskbooks/stages/STAGE_04_BOUNDED_EXECUTION_AND_EVIDENCE.md`
  - hash：`05e6114a666942c0641c635905c2295feaa62b98bd9e7b5166babd662e015a41`
- Stage 3 Version set confirmation：
  - hash：`8695cf9f9b29608011dfc4691fd12df5a4f21f879e025e999c8bba5ae929e313`

中文解释：先把执行边界做成“信封”，再谈能不能跑；信封存在不等于可以跑。

## 3. 目标

本版本要定义最小 `ExecutionEnvelope`：

- 绑定 Master / Stage / Version Taskbook；
- 声明 `authority_mode`；
- 声明本地执行授权或外部回执导入授权；
- 声明 allowed_files 和 forbidden_files；
- 声明 allowed_commands 和 validation_commands；
- 声明 timeout、network、secrets、destructive operation、retry 和 stop conditions。

`authority_mode` = 权限模式。

中文意思是：说明这个信封是为本地执行、外部回执还是只验证而准备；不同模式不能
混用授权。

## 4. 不做什么

v4.1 不做：

- executor dispatch；
- run preview；
- local execution；
- imported receipt adoption；
- plan mutation；
- review acceptance；
- delivery state accepted。

## 5. 候选写入范围

未来如果 Commander 单独授权执行，本版本候选写入范围最多包括：

- `runner/execution_envelope.py`
- `tests/test_execution_envelope.py`
- `docs/taskbooks/versions/stage-04/evidence/VERSION_STAGE_04_V4_1_EXECUTION_ENVELOPE_REPORT.md`
- `docs/taskbooks/versions/stage-04/evidence/zh-CN/VERSION_STAGE_04_V4_1_EXECUTION_ENVELOPE_REPORT.zh-CN.md`

这些现在只是候选路径，不是当前授权。

## 6. 执行信封最小合约

`ExecutionEnvelope` 至少需要：

- `envelope_id`；
- `version_taskbook_ref`；
- `master_taskbook_ref`；
- `stage_taskbook_ref`；
- `authority_mode`；
- `local_execution_authorization_ref`；
- `imported_receipt_authorization_ref`；
- `allowed_files`；
- `forbidden_files`；
- `allowed_commands`；
- `validation_commands`；
- `timeout_limits`；
- `network_policy`；
- `secrets_policy`；
- `destructive_operation_policy`；
- `retry_policy`；
- `stop_conditions`。

禁止的声明包括：

- envelope 存在就授权 dispatch；
- allowed_files expansion authorized；
- plan mutation authorized；
- commit authorized；
- push authorized；
- delivery_state accepted。

## 7. 人工验收条件

审查者可以接受 v4.1 的条件包括：

- envelope 要求 `version_taskbook_ref`；
- envelope 要求 `authority_mode`；
- envelope 拒绝缺少 allowed_files 或 validation_commands；
- envelope 拒绝 dispatch authority claims；
- 证据报告区分 `commands_run` 和 `commands_not_run`。

不能接受的情况包括：

- envelope 存在就授权 dispatch；
- local execution 授权被拿去授权 imported receipt adoption；
- imported receipt 授权被拿去授权 local dispatch；
- validation summary 被映射成 delivery_state accepted。

## 8. 下一步交接

v4.1 通过后，才能交给 v4.2 做 `Taskbook-bound Executor Run Preview`。

中文意思是：先证明信封边界能检查，再生成“如果要跑会跑什么”的只读预览。这个交接
仍然不是 executor run authorization。
