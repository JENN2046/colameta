# Stage 3 中文任务书：外部任务书导入协议

```yaml id="stage-03-zh-cn-summary"
chinese_companion:
  source_document: docs/taskbooks/stages/STAGE_03_EXTERNAL_TASKBOOK_IMPORT.md
  source_sha256: c5402734ef6990687a6a03ec6b17769f598ff0319b350b6a2371144985ece7ff
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

英文源文件里的 `created_from_head` 是历史创建基线，不是当前 freeze snapshot HEAD。

## 2. 绑定要求

外部任务书必须绑定：

- `master_taskbook_ref`；
- `stage_taskbook_ref`；
- `project_final_goal_ref`。

这保证版本任务不是直接挂在总目标下面乱跑。

本阶段显式绑定 `master_taskbook_ref`，并声明 `supports_project_goal=true`。

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
- acceptance_commands 和 manual_acceptance 明确；
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
- acceptance_commands；
- manual_acceptance；
- out_of_scope；
- supports_stage_and_master_goals。

拒绝信息需要 rejected_fields、rejection_reasons、known_conflicts。

规范化输出需要 normalized_claims、normalized_output_candidate、
version_candidate_mapping。

## 7. 关键词解释

- `acceptance_commands` = 验收命令。用于验证候选任务，不是交付状态验收授权。
- `manual_acceptance` = 人工验收要求。说明 Reviewer 要看什么，不等于
  `delivery_state: accepted`。
- `expected_hash_authority_ref` = 预期 hash 权威引用。说明期望 hash 应由哪份授权
  材料或回执提供。
- `provenance` = 来源证明。说明任务书从哪里来、什么时候来、由谁交给 ColaMeta。

## 7.1 Stage 0-6 就绪契约

```yaml id="stage-0-6-readiness-contract-zh-cn"
stage_0_6_readiness_contract:
  stage_id: stage_03_external_taskbook_import
  minimum_readiness_claim: 外部任务书只作为声明进入。
  required_evidence:
    - 来源
    - 来源证明
    - 导入回执
    - 规范化声明
    - 冲突记录
  gate_question: 导入声明能否被审查，而不直接变成事实？
  explicit_non_goal: 不做可信状态导入或通用 ingestion。
```

## 8. 最小证据包

最小证据包需要 source、provenance、imported_taskbook_hash、
expected_hash_authority_ref、master_taskbook_ref、stage_taskbook_ref、
validation_result、rejected_fields、rejection_reasons、normalized_claims、
normalized_output_candidate、known_conflicts。

不能把 source reputation、user silence、previous memory、runtime status labels 当作权威。

## 9. 非目标

Stage 3 不自动扩展 goal、不自动补危险 scope、不自动扩 allowed_files、不自动派发
executor、不自动 commit/push。
