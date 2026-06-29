# Version 中文任务书：Stage 3 / v3.4 任务书到版本候选映射 V1

```yaml id="version-stage-03-v3-4-zh-cn-summary"
chinese_companion:
  source_document: docs/taskbooks/versions/stage-03/VERSION_STAGE_03_V3_4_TASKBOOK_TO_VERSION_CANDIDATE_MAPPING_V1.md
  source_sha256: a1ef7d80d50655dc24b19c23d696cd69a16bbc0fbaa0aa35811b858c41e849b1
  translation_status: companion_draft
  authority_status: planning_reference_only
version_execution_taskbook:
  version_id: stage_03_v3_4_taskbook_to_version_candidate_mapping_v1
  version: v3.4
  chinese_name: 任务书到版本候选映射 V1
  status: discussion_draft
  execution_authorization_status: not_authorized
```

## 1. 这份任务书是什么

这是 Stage 3 的第四份 Version 任务书草稿。

`Taskbook-to-Version-Candidate Mapping V1` = 任务书到版本候选映射 V1。

中文意思是：把 v3.3 的只读导入预览翻译成 ColaMeta 内部 Version candidate 的结构化
候选对象。它仍然不是采用，不会写入 `.colameta/plan.json`。

它现在不授权实现，不授权 executor，不授权 commit，不授权 push，不授权 fetch/pull，
也不授权 import adoption、plan mutation、Delivery State Gate transition 或 accepted
delivery state。

## 2. 父级绑定

这份 Version 绑定到：

- Master Taskbook：`PROJECT_MASTER_TASKBOOK.md`
  - hash：`1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34`
- Stage 3 Taskbook：`docs/taskbooks/stages/STAGE_03_EXTERNAL_TASKBOOK_IMPORT.md`
  - hash：`c5402734ef6990687a6a03ec6b17769f598ff0319b350b6a2371144985ece7ff`
- previous version v3.3：
  - hash：`8443c5ac8b9927a308da382bd2fd3e39992636b27f059539f0de46f802c78768`
- Stage 2 Version set confirmation：
  - hash：`3de9f207f7a80ce1ec3f2cb374c1f10b4903014be18d0dbe6d2defa1224e8f58`

中文解释：映射是“把外部说法翻译成 ColaMeta 内部候选格式”，不是“已经采纳”。

## 3. 目标

本版本要定义从 import preview 到 Version candidate object 的映射：

- 保留 source taskbook hash；
- 保留 import preview hash；
- 保留 parent bindings；
- 保留 candidate version identity；
- 保留 candidate allowed_files；
- 保留 forbidden files；
- 保留 acceptance command candidates；
- 保留 manual acceptance requirements；
- 保留 evidence requirements；
- 保留 known gaps；
- 保留 required Commander decisions。

`version_candidate_id` = 版本候选 ID。

中文意思是：候选对象可以有内部编号，但这个编号不表示它已经进入计划。

## 4. 不做什么

v3.4 不做：

- import adoption；
- plan insertion；
- allowed_files expansion；
- executor dispatch；
- review acceptance；
- delivery state accepted。

## 5. 候选写入范围

未来如果 Commander 单独授权执行，本版本候选写入范围最多包括：

- `runner/taskbook_version_candidate_mapping.py`
- `tests/test_taskbook_version_candidate_mapping.py`
- `docs/taskbooks/versions/stage-03/evidence/VERSION_STAGE_03_V3_4_TASKBOOK_TO_VERSION_CANDIDATE_MAPPING_REPORT.md`
- `docs/taskbooks/versions/stage-03/evidence/zh-CN/VERSION_STAGE_03_V3_4_TASKBOOK_TO_VERSION_CANDIDATE_MAPPING_REPORT.zh-CN.md`

这些现在只是候选路径，不是当前授权。

## 6. 映射最小合约

映射输出至少要包括：

- `version_candidate_id`；
- `mapping_status`；
- `source_taskbook_ref`；
- `import_preview_ref`；
- `candidate_parent_refs`；
- `candidate_version_identity`；
- `candidate_allowed_files`；
- `candidate_forbidden_files`；
- `candidate_acceptance_commands`；
- `candidate_manual_acceptance`；
- `candidate_evidence_requirements`；
- `candidate_out_of_scope`；
- `adoption_blockers`；
- `required_commander_decisions`；
- `authority_boundary`。

允许的 mapping status 只有：

- `mapping_ready`；
- `mapping_blocked_preview_not_ready`；
- `mapping_blocked_scope_conflict`；
- `mapping_blocked_authority_confusion`。

禁止的输出声明包括：

- `plan_item_inserted`；
- `plan_mutation_authorized`；
- `allowed_files_expansion_authorized`；
- `executor_dispatch_authorized`；
- `delivery_state_accepted`。

## 7. 人工验收条件

审查者可以接受 v3.4 的条件包括：

- mapping 只消费 `preview_ready` 输入；
- mapping 保留 source hash 和 preview hash；
- mapping 输出明确是 candidate-only；
- mapping 拒绝 plan insertion 和 executor dispatch claim；
- 证据报告区分 `commands_run` 和 `commands_not_run`。

不能接受的情况包括：

- mapping 消费 blocked preview；
- mapping 丢掉 blockers 或 known gaps；
- mapping 写入 `.colameta/plan.json`；
- mapping 把 manual acceptance 映射成 delivery_state accepted。

## 8. 下一步交接

v3.4 通过后，才能交给 v3.5 做 `Taskbook Import Adoption Preview`。

中文意思是：把候选对象准备好后，最后再生成“如果要采纳，需要哪些精确授权”的预览。
这个交接仍然不是 adoption、不是 plan mutation、不是 execution。
