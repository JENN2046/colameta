# Version 中文任务书：Stage 3 / v3.3 任务书导入预览 V1

```yaml id="version-stage-03-v3-3-zh-cn-summary"
chinese_companion:
  source_document: docs/taskbooks/versions/stage-03/VERSION_STAGE_03_V3_3_TASKBOOK_IMPORT_PREVIEW_V1.md
  source_sha256: 8443c5ac8b9927a308da382bd2fd3e39992636b27f059539f0de46f802c78768
  translation_status: companion_draft
  authority_status: planning_reference_only
version_execution_taskbook:
  version_id: stage_03_v3_3_taskbook_import_preview_v1
  version: v3.3
  chinese_name: 任务书导入预览 V1
  status: discussion_draft
  execution_authorization_status: not_authorized
```

## 1. 这份任务书是什么

这是 Stage 3 的第三份 Version 任务书草稿。

`Taskbook Import Preview V1` = 任务书导入预览 V1。

中文意思是：外部任务书 claim 通过 v3.2 校验后，先生成一份只读预览，告诉我们它
想导入什么、会影响哪些范围、需要 Commander 做哪些关键决定。它不是采用，不是计划
修改，也不是执行授权。

它现在不授权实现，不授权 executor，不授权 commit，不授权 push，不授权 fetch/pull，
也不授权 allowed_files expansion、import adoption、Delivery State Gate transition 或
accepted delivery state。

## 2. 父级绑定

这份 Version 绑定到：

- Master Taskbook：`PROJECT_MASTER_TASKBOOK.md`
  - hash：`1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34`
- Stage 3 Taskbook：`docs/taskbooks/stages/STAGE_03_EXTERNAL_TASKBOOK_IMPORT.md`
  - hash：`c5402734ef6990687a6a03ec6b17769f598ff0319b350b6a2371144985ece7ff`
- previous version v3.2：
  - hash：`7bdf06889b25439f9ca8ed70a2e93962f1ab6bec9566fe7b752aa47ad9ebb927`
- Stage 2 Version set confirmation：
  - hash：`3de9f207f7a80ce1ec3f2cb374c1f10b4903014be18d0dbe6d2defa1224e8f58`

中文解释：预览只是“先给你看会发生什么”，不是“已经同意这么做”。

## 3. 目标

本版本要定义一份 read-only import preview：

- 展示 recognized claims；
- 展示 rejected claims；
- 展示 proposed Version candidate identity；
- 展示 scope impact；
- 展示 allowed_files candidate delta；
- 展示 acceptance command candidates；
- 展示 manual acceptance requirements；
- 展示 blockers；
- 展示 adoption 前需要 Commander 明确决定的事项。

`proposed_allowed_files_candidate_delta` = 候选 allowed_files 变化。

中文意思是：外部任务书想改的范围可以展示出来，但这不等于已经允许它改。

## 4. 不做什么

v3.3 不做：

- taskbook-to-version mapping；
- import adoption；
- plan mutation；
- allowed_files expansion；
- executor dispatch；
- review acceptance；
- delivery state accepted。

## 5. 候选写入范围

未来如果 Commander 单独授权执行，本版本候选写入范围最多包括：

- `runner/taskbook_import_preview.py`
- `tests/test_taskbook_import_preview.py`
- `docs/taskbooks/versions/stage-03/evidence/VERSION_STAGE_03_V3_3_TASKBOOK_IMPORT_PREVIEW_REPORT.md`
- `docs/taskbooks/versions/stage-03/evidence/zh-CN/VERSION_STAGE_03_V3_3_TASKBOOK_IMPORT_PREVIEW_REPORT.zh-CN.md`

这些现在只是候选路径，不是当前授权。

## 6. 导入预览最小合约

导入预览至少要输出：

- `preview_id`；
- `preview_status`；
- `source_claim_ref`；
- `validator_result_ref`；
- `recognized_claims_summary`；
- `rejected_claims_summary`；
- `proposed_version_candidate_identity`；
- `proposed_scope_summary`；
- `proposed_allowed_files_candidate_delta`；
- `proposed_acceptance_commands_summary`；
- `required_commander_decisions`；
- `blockers`；
- `authority_boundary`。

允许的 preview status 只有：

- `preview_ready`；
- `preview_blocked_invalid_validator_result`；
- `preview_blocked_authority_confusion`；
- `preview_blocked_missing_required_claim`。

禁止的输出声明包括：

- `adoption_authorized`；
- `plan_mutation_authorized`；
- `allowed_files_expansion_authorized`；
- `executor_dispatch_authorized`；
- `delivery_state_accepted`。

## 7. 人工验收条件

审查者可以接受 v3.3 的条件包括：

- preview 拒绝非 pass 的 validator result；
- preview 把所有 delta 都标成 candidate-only；
- preview 列出 adoption 前需要 Commander 决定的事项；
- preview 不修改 plan 或 allowed_files；
- 证据报告区分 `commands_run` 和 `commands_not_run`。

不能接受的情况包括：

- preview 把外部任务书 claim 当成可信事实；
- preview 授权 adoption；
- preview 扩大 allowed_files；
- preview 把 manual acceptance 映射成 delivery_state accepted。

## 8. 下一步交接

v3.3 通过后，才能交给 v3.4 做 `Taskbook-to-Version-Candidate Mapping`。

中文意思是：先看清外部任务书要什么，再讨论能不能映射成 ColaMeta 内部 Version
candidate。这个交接仍然不是 adoption、不是 plan mutation、不是 execution。
