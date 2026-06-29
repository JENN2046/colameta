# Stage 3 中文任务书：外部任务书导入协议

```yaml id="stage-03-zh-cn-summary"
chinese_companion:
  source_document: docs/taskbooks/stages/STAGE_03_EXTERNAL_TASKBOOK_IMPORT.md
  source_sha256: b09560907bdf0610dcd53281c82b5314647ece996bc3c1b4b3114f118bfe8028
  translation_status: companion_draft
  authority_status: planning_reference_only
stage:
  stage_id: stage_03_external_taskbook_import
  chinese_name: 外部任务书导入协议
  status: discussion_draft
```

## 1. 阶段定位

Stage 3 定义 ChatGPT 或 Commander 写出的外部 Version Execution Taskbook 如何进入
ColaMeta。

外部任务书进入时只能先作为 claim，中文意思是“待审查声明”，不能直接变成事实、
计划修改或执行命令。

## 2. 绑定要求

外部任务书必须绑定：

- `master_taskbook_ref`；
- `stage_taskbook_ref`；
- `project_final_goal_ref`。

这保证版本任务不是直接挂在总目标下面乱跑。

## 3. 进入条件

进入 Stage 3 需要：

- Master Taskbook 可引用；
- Stage Taskbook 可引用；
- 最小外部任务书字段已知。

不需要 executor dispatch、automatic task acceptance、general document ingestion 或
codex-router bridge。

## 4. 退出条件

Stage 3 完成时需要：

- external taskbook schema 存在；
- validator 存在；
- import preview 可显示 recognized 和 rejected 字段；
- invalid format 被拒绝；
- hash mismatch fail closed；
- allowed_files 和 forbidden_files 必填；
- validation_commands 和 manual_review_requirements 明确；
- imported taskbook 映射为 bounded version task candidate。

## 5. 版本方向

Stage 3 后续版本方向：

- External Taskbook Schema V1；
- External Taskbook Validator V1；
- Taskbook Import Preview V1；
- Taskbook-to-Version-Candidate Mapping V1；
- Taskbook Import Adoption Preview V1。

Import Adoption 必须另有 Commander hard gate。Preview 和 mapping 不能自动修改 plan。

## 6. 最小外部任务书字段

外部任务书最小字段包括：

- source；
- provenance；
- external_taskbook_hash；
- expected_hash_authority_ref；
- master_taskbook_ref；
- stage_taskbook_ref；
- allowed_files；
- forbidden_files；
- validation_commands；
- manual_review_requirements；
- out_of_scope；
- supports_stage_and_master_goals。

拒绝信息需要 rejected_fields、rejection_reasons、known_conflicts。

规范化输出需要 normalized_claims、normalized_output_candidate、
version_candidate_mapping。

## 7. 关键词解释

- `validation_commands` = 验证命令。用于验证候选任务，不是交付状态验收授权。
- `manual_review_requirements` = 人工审查要求。说明 Reviewer 要看什么，不等于
  `delivery_state: accepted`。
- `expected_hash_authority_ref` = 预期 hash 权威引用。说明期望 hash 应由哪份授权
  材料或回执提供。
- `provenance` = 来源证明。说明任务书从哪里来、什么时候来、由谁交给 ColaMeta。

## 8. 最小证据包

最小证据包需要 source、provenance、imported_taskbook_hash、
expected_hash_authority_ref、master_taskbook_ref、stage_taskbook_ref、
validation_result、rejected_fields、rejection_reasons、normalized_claims、
normalized_output_candidate、known_conflicts。

不能把 source reputation、user silence、previous memory、runtime status labels 当作权威。

## 9. 非目标

Stage 3 不自动扩展 goal、不自动补危险 scope、不自动扩 allowed_files、不自动派发
executor、不自动 commit/push。
