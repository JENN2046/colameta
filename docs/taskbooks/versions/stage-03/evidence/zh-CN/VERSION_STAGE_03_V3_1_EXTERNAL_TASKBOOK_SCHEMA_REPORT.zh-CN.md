# 证据报告中文 companion：Stage 3 / v3.1 External Taskbook Schema V1

```yaml id="stage-03-v3-1-evidence-zh-cn-summary"
chinese_companion:
  companion_id: stage_03_v3_1_external_taskbook_schema_evidence_zh_cn
  source_report: docs/taskbooks/versions/stage-03/evidence/VERSION_STAGE_03_V3_1_EXTERNAL_TASKBOOK_SCHEMA_REPORT.md
  source_sha256: 02616de6a67c9551eb581d3fffdd2fd7bf6442571e194eb1573bbc9b6b3229f5
  language: zh-CN
  authority_status: non_authoritative_reading_companion
  review_acceptance: false
  delivery_state_accepted: false
```

这份文件是英文证据报告的中文阅读 companion，不是新的权威副本，也不产生审查接受、状态推进、导入采用或执行授权。

本轮 v3.1 的目标是建立 `External Taskbook Schema V1`：也就是把外部传入的 Version Execution Taskbook 先看成“有边界的声明”，而不是可信事实。它只定义外部 taskbook 被归一化接入前必须具备的最小字段、拒绝字段、归一化输出候选字段和权限边界。

换句话说：外部 taskbook 可以提交“我声称这些文件、这些命令、这些验收信息属于某个版本”的结构化内容，但 ColaMeta 不能因此直接相信它、不能让它改计划、不能让它扩大 allowed files、不能让它授权执行，也不能把人工确认误读成 delivery state accepted。

---

## 1. 本轮实现摘要

```yaml id="stage-03-v3-1-implementation-summary-zh-cn"
implementation_summary:
  source_version_taskbook: docs/taskbooks/versions/stage-03/VERSION_STAGE_03_V3_1_EXTERNAL_TASKBOOK_SCHEMA_V1.md
  source_version_taskbook_sha256: 0d92e1d7779db1d89253986cd40c045dc75b25c0b2f31dbb46143d3b5d1f3232
  implementation_authorization_head: 0dbd14462add847865e1a17a15fd11dcb0cabcc9
  master_taskbook_sha256: 1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34
  stage_03_taskbook_sha256: c5402734ef6990687a6a03ec6b17769f598ff0319b350b6a2371144985ece7ff
  stage_2_version_set_confirmation_sha256: 3de9f207f7a80ce1ec3f2cb374c1f10b4903014be18d0dbe6d2defa1224e8f58
  stage_2_gate_readiness_evidence_sha256: 2f660ddfe5dbc38d2d2a4531913945668fc4cdb556b1f5d0f155378c7fdbd392
  external_taskbook_schema_sha256: 3f40f58f6680644c9ff2feaf57860ebcc6e01d9abdf22646c7223ace55f09291
  external_taskbook_schema_helper_sha256: 2dfcf5aab88d31d6a95a45464d65abb699473f32a856dfb78c8721278970db82
  external_taskbook_schema_tests_sha256: 0bc08f8d9f4d73bf9c317057037356a609953502cb31a0c53d66c74a9b38e579
```

本轮新增了 5 个允许范围内的文件：

```yaml id="stage-03-v3-1-files-changed-zh-cn"
files_changed:
  created:
    - .colameta/taskbooks/external_taskbook_schema.json
    - runner/external_taskbook_schema.py
    - tests/test_external_taskbook_schema.py
    - docs/taskbooks/versions/stage-03/evidence/VERSION_STAGE_03_V3_1_EXTERNAL_TASKBOOK_SCHEMA_REPORT.md
    - docs/taskbooks/versions/stage-03/evidence/zh-CN/VERSION_STAGE_03_V3_1_EXTERNAL_TASKBOOK_SCHEMA_REPORT.zh-CN.md
  modified: []
  forbidden_files_touched: []
```

本轮没有修改 `PROJECT_MASTER_TASKBOOK.md`、中文 Master companion、Stage Taskbook、Version Taskbook、freeze packet、`.colameta/plan.json`、executor state、route state 或服务运行时。

---

## 2. Schema 的中文解释

`External Taskbook Schema V1` 可以理解成外部任务书进入 ColaMeta 之前的“申报表格式”。它不判断任务是否应该被采用，也不替 Commander、Reviewer、Gate 或 Runtime 做决定；它只判断外部输入有没有按最小结构把自己的声明说清楚。

它要求外部声明至少包含这些字段：

```yaml id="stage-03-v3-1-required-fields-zh-cn"
required_fields:
  - source
  - provenance
  - external_taskbook_hash
  - expected_hash_authority_ref
  - master_taskbook_ref
  - stage_taskbook_ref
  - allowed_files
  - forbidden_files
  - acceptance_commands
  - manual_acceptance
  - out_of_scope
  - supports_stage_and_master_goals
```

这些字段的意思是：

```yaml id="stage-03-v3-1-field-meaning-zh-cn"
field_meaning:
  source: 外部 taskbook 的来源描述。
  provenance: 来源链路和生成背景。
  external_taskbook_hash: 外部 taskbook 的原始 hash 声明。
  expected_hash_authority_ref: 外部 hash 应该由哪个权威材料来绑定。
  master_taskbook_ref: 它声称自己支持哪个 Master Taskbook。
  stage_taskbook_ref: 它声称自己支持哪个 Stage Taskbook。
  allowed_files: 它声称实现时允许触碰哪些文件。
  forbidden_files: 它明确不能触碰哪些文件。
  acceptance_commands: 它建议的验证命令。
  manual_acceptance: 它声称需要人工确认的部分。
  out_of_scope: 它明确不覆盖的范围。
  supports_stage_and_master_goals: 它如何支持 Stage 和 Master 的目标。
```

同时，schema 也明确了失败时要输出的拒绝信息：

```yaml id="stage-03-v3-1-rejection-fields-zh-cn"
rejection_fields:
  - rejected_fields
  - rejection_reasons
  - known_conflicts
```

以及通过 schema 后可以生成的“候选输出”，注意这里仍然只是候选，不是采用：

```yaml id="stage-03-v3-1-normalized-output-fields-zh-cn"
normalized_output_fields:
  - normalized_claims
  - normalized_output_candidate
  - version_candidate_mapping
```

---

## 3. 权限边界

本轮最重要的边界是：外部 taskbook 的 schema 检查通过，只代表“声明格式合格”，不代表它已经被 ColaMeta 信任或采用。

以下权威声明必须被拒绝：

```yaml id="stage-03-v3-1-forbidden-authority-claims-zh-cn"
forbidden_authority_claims:
  - external_taskbook_is_trusted_fact
  - external_taskbook_mutates_plan
  - external_taskbook_authorizes_execution
  - external_taskbook_expands_allowed_files
  - manual_acceptance_means_delivery_state_accepted
```

所有 schema 结果都必须保持下面的权限状态：

```yaml id="stage-03-v3-1-authority-boundary-zh-cn"
authority_boundary:
  schema_result_is_authority: false
  creates_review_decision: false
  emits_gate_event: false
  writes_delivery_state: false
```

中文大白话说：这一步只是在门口检查“表格填得像不像样”，不是让外部任务书进屋当主人。

---

## 4. 已运行验证

```text id="stage-03-v3-1-validation-zh-cn"
git status -sb
  result: PASS
  observed_after_implementation_before_reports:
    ## main...origin/main [ahead 57]
    ?? .colameta/taskbooks/external_taskbook_schema.json
    ?? runner/external_taskbook_schema.py
    ?? tests/test_external_taskbook_schema.py

git rev-parse HEAD
  result: PASS
  observed: 0dbd14462add847865e1a17a15fd11dcb0cabcc9

git rev-parse origin/main
  result: PASS
  observed: 018ff63b76872504407c537cd46e1e8a2ee5c22e

git rev-list --count origin/main..HEAD
  result: PASS
  observed: 57

sha256sum PROJECT_MASTER_TASKBOOK.md docs/taskbooks/stages/STAGE_03_EXTERNAL_TASKBOOK_IMPORT.md docs/taskbooks/versions/stage-03/VERSION_STAGE_03_V3_1_EXTERNAL_TASKBOOK_SCHEMA_V1.md docs/taskbooks/versions/stage-02/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_02_VERSIONS.md docs/taskbooks/versions/stage-02/evidence/VERSION_STAGE_02_V2_4_STAGE_TASKBOOK_GATE_READINESS_REPORT.md .colameta/taskbooks/external_taskbook_schema.json runner/external_taskbook_schema.py tests/test_external_taskbook_schema.py
  result: PASS

.venv/bin/python -m compileall runner/external_taskbook_schema.py
  result: PASS

.venv/bin/python -m unittest tests.test_external_taskbook_schema
  result: PASS
  observed: Ran 13 tests ... OK

git diff --check
  result: PASS

read-only helper smoke
  result: PASS
  observed:
    schema_contract_status: valid
    schema_check_result: schema_check_passed
    schema_result_is_authority: false
    writes_delivery_state: false
```

---

## 5. 没有运行或没有授权的动作

```yaml id="stage-03-v3-1-not-authorized-zh-cn"
not_authorized_and_not_run:
  - fetch
  - pull
  - push
  - force_push
  - executor_run
  - route_transition
  - service_restart
  - release
  - deploy
  - remote_write
  - full_unittest_discovery
  - plan_mutation
  - allowed_files_expansion
  - import_adoption
  - review_acceptance
  - delivery_state_transition
  - modifying_/home/jenn/tools/colameta
```

完整 unittest discovery 没有运行，因为 v3.1 授权范围收窄到 focused External Taskbook schema 测试。

---

## 6. 通过示例和拒绝示例

一个合格的外部声明形状会得到：

```yaml id="stage-03-v3-1-valid-claim-example-zh-cn"
valid_claim_example:
  schema_check_result: schema_check_passed
  version_candidate_mapping:
    mapping_status: schema_claim_shape_only_not_adopted
  authority_boundary:
    external_taskbook_is_trusted_fact: false
    external_taskbook_mutates_plan: false
    external_taskbook_authorizes_execution: false
    external_taskbook_expands_allowed_files: false
    manual_acceptance_means_delivery_state_accepted: false
```

不合格或越权的外部声明会 fail closed：

```yaml id="stage-03-v3-1-rejected-claim-example-zh-cn"
rejected_claim_examples:
  missing_required_field:
    result: schema_check_failed_closed
    observed_reason: REQUIRED_FIELD_MISSING
  invalid_external_taskbook_hash:
    result: schema_check_failed_closed
    observed_reason: FIELD_TYPE_INVALID
  missing_expected_hash_authority_document:
    result: schema_check_failed_closed
    observed_reason: EXPECTED_HASH_AUTHORITY_REF_INVALID
  forbidden_authority_claim:
    result: schema_check_failed_closed
    observed_reason: FORBIDDEN_AUTHORITY_CLAIM
```

---

## 7. 已知缺口和剩余风险

```yaml id="stage-03-v3-1-known-gaps-zh-cn"
known_gaps:
  - 这个 helper 只检查 schema contract 和示例 claim shape；完整导入验证由 v3.2 负责。
  - 这个 schema 不解析任意 Markdown taskbook 文本；它定义的是归一化 JSON claim shape。
  - 本轮只运行了 v3.1 的 focused unittest module。
remaining_risks:
  - v3.2 必须消费这个 schema，但不能把 schema_check_passed 误当成 import adoption。
  - 未来外部 taskbook 格式可能需要更多字段类型或更强的 provenance 规则。
```

结论：v3.1 已经把“外部任务书先作为有边界声明进入系统”的最低结构立住了。它为 v3.2 的完整外部 taskbook validator 铺路，但自己不做导入采用、不做状态推进、不做执行授权。
