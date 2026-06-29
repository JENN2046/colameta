# Version 中文任务书：Stage 4 / v4.2 任务书绑定执行器运行预览 V1

```yaml id="version-stage-04-v4-2-zh-cn-summary"
chinese_companion:
  source_document: docs/taskbooks/versions/stage-04/VERSION_STAGE_04_V4_2_TASKBOOK_BOUND_EXECUTOR_RUN_PREVIEW_V1.md
  source_sha256: e4f02abe34af18ea0b1ef8cc94006dc5dddf04e0e80f0ca65f9f393ae8b617a2
  translation_status: companion_draft
  authority_status: planning_reference_only
version_execution_taskbook:
  version_id: stage_04_v4_2_taskbook_bound_executor_run_preview_v1
  version: v4.2
  chinese_name: 任务书绑定执行器运行预览 V1
  status: discussion_draft
  execution_authorization_status: not_authorized
```

## 1. 这份任务书是什么

这是 Stage 4 的第二份 Version 任务书草稿。

`Taskbook-bound Executor Run Preview V1` = 任务书绑定执行器运行预览 V1。

中文意思是：把一个有效 ExecutionEnvelope 渲染成只读 run preview，让 Commander
看到 executor 如果被授权会做什么。预览本身不授权运行。

它现在不授权实现，不授权 executor，不授权 commit，不授权 push，不授权 fetch/pull，
也不授权 plan mutation、Delivery State Gate transition 或 accepted delivery state。

## 2. 父级绑定

这份 Version 绑定到：

- Master Taskbook：`PROJECT_MASTER_TASKBOOK.md`
  - hash：`1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34`
- Stage 4 Taskbook：`docs/taskbooks/stages/STAGE_04_BOUNDED_EXECUTION_AND_EVIDENCE.md`
  - hash：`05e6114a666942c0641c635905c2295feaa62b98bd9e7b5166babd662e015a41`
- previous version v4.1：
  - hash：`22e99e01a854c6d8fe1fc4f0ceba38f5d2b1ce28d796596f80f4292459071dfa`
- Stage 3 Version set confirmation：
  - hash：`8695cf9f9b29608011dfc4691fd12df5a4f21f879e025e999c8bba5ae929e313`

中文解释：run preview 是“先看会跑什么”，不是“现在开始跑”。

## 3. 目标

本版本要定义只读 executor run preview：

- 渲染 proposed commands；
- 渲染 proposed writable paths；
- 渲染 validation commands；
- 渲染 timeout limits；
- 渲染 network 和 secrets policy；
- 渲染 stop conditions；
- 明确 required local execution authorization。

`proposed_writable_paths` = 候选可写路径。

中文意思是：这些路径只是预览里列出来的候选范围，不等于已经授权修改。

## 4. 不做什么

v4.2 不做：

- executor dispatch；
- local execution receipt；
- imported receipt adoption；
- plan mutation；
- review acceptance；
- delivery state accepted。

## 5. 候选写入范围

未来如果 Commander 单独授权执行，本版本候选写入范围最多包括：

- `runner/executor_run_preview.py`
- `tests/test_executor_run_preview.py`
- `docs/taskbooks/versions/stage-04/evidence/VERSION_STAGE_04_V4_2_EXECUTOR_RUN_PREVIEW_REPORT.md`
- `docs/taskbooks/versions/stage-04/evidence/zh-CN/VERSION_STAGE_04_V4_2_EXECUTOR_RUN_PREVIEW_REPORT.zh-CN.md`

这些现在只是候选路径，不是当前授权。

## 6. 运行预览最小合约

run preview 至少要输出：

- `run_preview_id`；
- `preview_status`；
- `execution_envelope_ref`；
- `version_taskbook_ref`；
- `authority_mode`；
- `required_local_execution_authorization_ref`；
- `proposed_commands`；
- `proposed_writable_paths`；
- `validation_commands`；
- `timeout_limits`；
- `network_policy`；
- `secrets_policy`；
- `destructive_operation_policy`；
- `stop_conditions`；
- `authority_boundary`。

禁止的输出声明包括：

- `executor_run_authorized`；
- `dispatch_started`；
- `code_changes_authorized`；
- `commit_authorized`；
- `push_authorized`；
- `delivery_state_accepted`。

## 7. 人工验收条件

审查者可以接受 v4.2 的条件包括：

- preview 只消费有效 envelope；
- preview 列出 proposed commands 和 writable paths；
- preview 把 mutations 标成 proposed only；
- preview 不启动 dispatch；
- 证据报告区分 `commands_run` 和 `commands_not_run`。

不能接受的情况包括：

- preview 授权 executor run；
- preview 把 proposed writable paths 当作已经授权的修改；
- preview 隐藏缺失的 local execution authorization；
- preview 把 validation summary 映射成 delivery_state accepted。

## 8. 下一步交接

v4.2 通过后，才能交给 v4.3 做 `Taskbook-bound Local Execution Receipt`。

中文意思是：先有只读运行预览，再定义真正执行后该怎样留下回执。这个交接仍然不是
executor run authorization。
