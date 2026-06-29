# Version 中文任务书：Stage 3 / v3.5 任务书导入采纳预览 V1

```yaml id="version-stage-03-v3-5-zh-cn-summary"
chinese_companion:
  source_document: docs/taskbooks/versions/stage-03/VERSION_STAGE_03_V3_5_TASKBOOK_IMPORT_ADOPTION_PREVIEW_V1.md
  source_sha256: fc14101c9369d483281e16c4df98ed36258a00b6a1d256db234d03f6d2c619e4
  translation_status: companion_draft
  authority_status: planning_reference_only
version_execution_taskbook:
  version_id: stage_03_v3_5_taskbook_import_adoption_preview_v1
  version: v3.5
  chinese_name: 任务书导入采纳预览 V1
  status: discussion_draft
  execution_authorization_status: not_authorized
```

## 1. 这份任务书是什么

这是 Stage 3 的第五份 Version 任务书草稿，也是 Stage 3 Version set 的收束版本。

`Taskbook Import Adoption Preview V1` = 任务书导入采纳预览 V1。

中文意思是：在真正采纳外部任务书之前，生成一份窄授权请求草稿，列出精确 hash、候选
diff、风险、阻塞项和 Commander 必须确认的事项。它自己不执行采纳。

它现在不授权实现，不授权 executor，不授权 commit，不授权 push，不授权 fetch/pull，
也不授权 plan mutation、route transition、Delivery State Gate transition 或 accepted
delivery state。

## 2. 父级绑定

这份 Version 绑定到：

- Master Taskbook：`PROJECT_MASTER_TASKBOOK.md`
  - hash：`1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34`
- Stage 3 Taskbook：`docs/taskbooks/stages/STAGE_03_EXTERNAL_TASKBOOK_IMPORT.md`
  - hash：`c5402734ef6990687a6a03ec6b17769f598ff0319b350b6a2371144985ece7ff`
- previous version v3.4：
  - hash：`a1ef7d80d50655dc24b19c23d696cd69a16bbc0fbaa0aa35811b858c41e849b1`
- Stage 2 Version set confirmation：
  - hash：`3de9f207f7a80ce1ec3f2cb374c1f10b4903014be18d0dbe6d2defa1224e8f58`

中文解释：v3.5 是 Stage 3 的收束门，只回答“如果要采纳，必须精确授权什么”。

## 3. 目标

本版本要定义 adoption preview：

- 绑定 source taskbook hash；
- 绑定 import preview hash；
- 绑定 mapping hash；
- 标出 target plan path；
- 展示 candidate plan diff summary；
- 展示 candidate allowed_files delta；
- 展示 blockers；
- 展示 risks；
- 生成 Commander decision request。

`commander_decision_request` = 指挥官决策请求。

中文意思是：它只是把 Commander 需要确认的话术和 hash 列出来，不代表 Commander 已经
确认。

## 4. 不做什么

v3.5 不做：

- adoption execution；
- plan mutation；
- allowed_files expansion；
- executor dispatch；
- route transition；
- review acceptance；
- delivery state accepted。

## 5. 候选写入范围

未来如果 Commander 单独授权执行，本版本候选写入范围最多包括：

- `runner/taskbook_import_adoption_preview.py`
- `tests/test_taskbook_import_adoption_preview.py`
- `docs/taskbooks/versions/stage-03/evidence/VERSION_STAGE_03_V3_5_TASKBOOK_IMPORT_ADOPTION_PREVIEW_REPORT.md`
- `docs/taskbooks/versions/stage-03/evidence/zh-CN/VERSION_STAGE_03_V3_5_TASKBOOK_IMPORT_ADOPTION_PREVIEW_REPORT.zh-CN.md`

这些现在只是候选路径，不是当前授权。

## 6. 采纳预览最小合约

采纳预览至少要输出：

- `adoption_preview_id`；
- `adoption_preview_status`；
- `source_taskbook_ref`；
- `import_preview_ref`；
- `mapping_ref`；
- `target_plan_path`；
- `candidate_plan_diff_summary`；
- `candidate_allowed_files_delta`；
- `candidate_forbidden_files_summary`；
- `candidate_acceptance_commands_summary`；
- `candidate_manual_acceptance_summary`；
- `required_exact_hash_authorization`；
- `commander_decision_request`；
- `blockers`；
- `risks`；
- `authority_boundary`。

允许的 adoption preview status 只有：

- `adoption_preview_ready`；
- `adoption_preview_blocked_mapping_not_ready`；
- `adoption_preview_blocked_plan_scope_conflict`；
- `adoption_preview_blocked_authority_confusion`。

禁止的输出声明包括：

- `adoption_executed`；
- `plan_mutation_authorized`；
- `allowed_files_expansion_authorized`；
- `executor_dispatch_authorized`；
- `delivery_state_accepted`。

## 7. 人工验收条件

审查者可以接受 v3.5 的条件包括：

- adoption preview 只消费 `mapping_ready` 输入；
- adoption preview 绑定 source taskbook、import preview 和 mapping hash；
- Commander decision request 明确列出 authorized 和 unauthorized actions；
- plan diff 和 allowed_files delta 都标成 candidate-only；
- 证据报告区分 `commands_run` 和 `commands_not_run`。

不能接受的情况包括：

- adoption preview 修改 `.colameta/plan.json`；
- adoption preview 捆绑 implementation 或 executor dispatch authority；
- adoption preview 把 Commander decision request 当成确认；
- adoption preview 把 manual acceptance 映射成 delivery_state accepted。

## 8. Stage 3 收束就绪

v3.1 到 v3.5 草稿齐全后，Stage 3 具备做包级审查的基础：

- v3.1：外部任务书 schema；
- v3.2：外部任务书 validator；
- v3.3：只读 import preview；
- v3.4：Version candidate mapping；
- v3.5：adoption preview 和 Commander decision request。

这些仍然只是 Version Taskbook 草稿，不授权实现、commit、push、executor、route 或
delivery state accepted。
