# 证据报告中文 companion：Stage 3 / v3.2 External Taskbook Validator V1

```yaml id="stage-03-v3-2-evidence-zh-cn-summary"
chinese_companion:
  companion_id: stage_03_v3_2_external_taskbook_validator_evidence_zh_cn
  source_report: docs/taskbooks/versions/stage-03/evidence/VERSION_STAGE_03_V3_2_EXTERNAL_TASKBOOK_VALIDATOR_REPORT.md
  source_sha256: 75d1bdfdecd8c621275111aa96a1fb2218b4550909e0edba254d64ca2bac4420
  language: zh-CN
  authority_status: non_authoritative_reading_companion
  review_acceptance: false
  delivery_state_accepted: false
```

这份文件是 v3.2 英文证据报告的中文阅读 companion。它不是新的权威副本，不产生导入采用、计划修改、执行授权、审查接受、GateEvent 或 delivery state accepted。

v3.2 的目标是实现 `External Taskbook Validator V1`，中文是“外部任务书校验器 V1”。它在 v3.1 schema 的基础上，再检查外部 taskbook claim 是否绑定到正确的 Master / Stage、是否带有 hash 权威引用、allowed_files / forbidden_files 是否越界、acceptance_commands 是否包含远程或 executor 动作，以及它是否支持 Stage 和 Master 的目标。

最重要的一点：校验通过只表示“这份外部声明可以进入下一步 preview”，不表示“已经采用”，也不表示“可以执行”。

---

## 1. 本轮实现摘要

```yaml id="stage-03-v3-2-implementation-summary-zh-cn"
implementation_summary:
  source_version_taskbook: docs/taskbooks/versions/stage-03/VERSION_STAGE_03_V3_2_EXTERNAL_TASKBOOK_VALIDATOR_V1.md
  source_version_taskbook_sha256: 7bdf06889b25439f9ca8ed70a2e93962f1ab6bec9566fe7b752aa47ad9ebb927
  implementation_authorization_head: c259bcfaf434f310d703e724a75abe8c5e0e5db0
  master_taskbook_sha256: 1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34
  stage_03_taskbook_sha256: c5402734ef6990687a6a03ec6b17769f598ff0319b350b6a2371144985ece7ff
  v3_1_schema_file_sha256: 3f40f58f6680644c9ff2feaf57860ebcc6e01d9abdf22646c7223ace55f09291
  v3_1_schema_helper_sha256: 2dfcf5aab88d31d6a95a45464d65abb699473f32a856dfb78c8721278970db82
  v3_1_schema_evidence_sha256: 02616de6a67c9551eb581d3fffdd2fd7bf6442571e194eb1573bbc9b6b3229f5
  external_taskbook_validator_helper_sha256: 42e9bc43b2942cba72e3ee802b80be80fa284975250253a18fc2a68cda4dc44f
  external_taskbook_validator_tests_sha256: 16e49d75dcdd8029eacc72e8fcf8c503c05f16cca3207f9a715e1d16d2126164
```

本轮新增 4 个允许范围内的文件：

```yaml id="stage-03-v3-2-files-changed-zh-cn"
files_changed:
  created:
    - runner/external_taskbook_validator.py
    - tests/test_external_taskbook_validator.py
    - docs/taskbooks/versions/stage-03/evidence/VERSION_STAGE_03_V3_2_EXTERNAL_TASKBOOK_VALIDATOR_REPORT.md
    - docs/taskbooks/versions/stage-03/evidence/zh-CN/VERSION_STAGE_03_V3_2_EXTERNAL_TASKBOOK_VALIDATOR_REPORT.zh-CN.md
  modified: []
  forbidden_files_touched: []
```

本轮没有修改 Master、中文 Master companion、Stage Taskbook、Version Taskbook、freeze packet、`.colameta/plan.json`、executor state、route state 或服务运行时。

---

## 2. 校验器做什么

v3.1 的 schema 只回答：“外部任务书 claim 的结构有没有基本形状？”

v3.2 的 validator 继续回答：“这个 claim 是否真的绑定到了当前预期的 Master、Stage 和 hash 权威边界？它有没有偷偷夹带计划修改、执行授权、扩大 allowed files、或者把人工确认冒充成 delivery state accepted？”

它的核心输出是：

```yaml id="stage-03-v3-2-validator-output-zh-cn"
validator_outputs:
  - validation_result
  - recognized_fields
  - rejected_fields
  - rejection_reasons
  - known_conflicts
  - normalized_claims_candidate
```

字段中文解释：

```yaml id="stage-03-v3-2-output-meaning-zh-cn"
output_meaning:
  validation_result: 校验结果，只能是 validation_passed 或 validation_failed_closed。
  recognized_fields: 校验器识别到的字段。
  rejected_fields: 被拒绝的字段。
  rejection_reasons: 拒绝原因列表。
  known_conflicts: 已知冲突列表。
  normalized_claims_candidate: 只有通过校验时才给出的归一化声明候选。
```

---

## 3. 通过案例

```yaml id="stage-03-v3-2-positive-case-zh-cn"
positive_case_result:
  validation_result: validation_passed
  fail_closed_result: pass
  recognized_fields_count: 12
  rejected_fields: []
  known_conflicts: []
  version_candidate_mapping_status: schema_claim_shape_only_not_adopted
  authority_boundary:
    validator_result_is_authority: false
    external_taskbook_is_trusted_fact: false
    external_taskbook_mutates_plan: false
    external_taskbook_authorizes_execution: false
    external_taskbook_expands_allowed_files: false
    manual_acceptance_means_delivery_state_accepted: false
    creates_review_decision: false
    emits_gate_event: false
    writes_delivery_state: false
```

中文解释：通过案例说明 validator 可以识别一个合格 claim，但它仍然明确保持“不是权威、不是采用、不是执行授权、不是状态推进”。

---

## 4. 失败案例

```yaml id="stage-03-v3-2-negative-cases-zh-cn"
negative_case_results:
  missing_required_field:
    validation_result: validation_failed_closed
    rejected_field: expected_hash_authority_ref
  missing_authority_hash:
    validation_result: validation_failed_closed
    rejection_code: EXPECTED_HASH_AUTHORITY_HASH_INVALID
  master_reference_mismatch:
    validation_result: validation_failed_closed
    rejected_field: master_taskbook_ref
    rejection_code: REFERENCE_MISMATCH
  stage_reference_mismatch:
    validation_result: validation_failed_closed
    rejected_field: stage_taskbook_ref
  allowed_forbidden_overlap:
    validation_result: validation_failed_closed
    rejection_code: ALLOWED_FORBIDDEN_FILES_OVERLAP
  hard_forbidden_allowed_file:
    validation_result: validation_failed_closed
    rejected_field: allowed_files
  forbidden_acceptance_command:
    validation_result: validation_failed_closed
    rejection_code: ACCEPTANCE_COMMAND_FORBIDDEN
  goal_support_false_or_missing_rationale:
    validation_result: validation_failed_closed
    rejected_field: supports_stage_and_master_goals
  plan_mutation_or_delivery_state_authority_claim:
    validation_result: validation_failed_closed
    rejection_code: FORBIDDEN_AUTHORITY_CLAIM
```

中文解释：这些失败案例证明 validator 是 fail closed 的。缺字段不会自动补，hash 权威缺失不会自动猜，Master / Stage 绑定不一致不会放行，allowed_files 越界不会放行，远程命令或 executor 动作也不会放行。

---

## 5. 被拒字段表

```yaml id="stage-03-v3-2-rejected-fields-table-zh-cn"
rejected_fields_table:
  schema_layer:
    - missing required field
    - malformed sha256
    - empty required list
    - forbidden authority claim
  validator_layer:
    - expected_hash_authority_ref without valid authority_hash or authority_sha256
    - master_taskbook_ref mismatch
    - stage_taskbook_ref mismatch
    - allowed_files and forbidden_files overlap
    - hard-forbidden path inside allowed_files
    - remote or executor command inside acceptance_commands
    - supports_stage_and_master_goals missing true Stage or Master support
```

这里的 `schema_layer` 是 v3.1 schema 层已经能拒绝的形状问题。`validator_layer` 是 v3.2 新增的绑定、边界和目标支持问题。

---

## 6. 已运行验证

```text id="stage-03-v3-2-validation-zh-cn"
git status -sb
  result: PASS
  observed_after_v3_1_commit_before_reports:
    ## main...origin/main [ahead 58]
    ?? runner/external_taskbook_validator.py
    ?? tests/test_external_taskbook_validator.py

git rev-parse HEAD
  result: PASS
  observed: c259bcfaf434f310d703e724a75abe8c5e0e5db0

git rev-list --count origin/main..HEAD
  result: PASS
  observed: 58

sha256sum PROJECT_MASTER_TASKBOOK.md docs/taskbooks/stages/STAGE_03_EXTERNAL_TASKBOOK_IMPORT.md docs/taskbooks/versions/stage-03/VERSION_STAGE_03_V3_2_EXTERNAL_TASKBOOK_VALIDATOR_V1.md .colameta/taskbooks/external_taskbook_schema.json runner/external_taskbook_schema.py runner/external_taskbook_validator.py tests/test_external_taskbook_validator.py docs/taskbooks/versions/stage-03/evidence/VERSION_STAGE_03_V3_1_EXTERNAL_TASKBOOK_SCHEMA_REPORT.md
  result: PASS

.venv/bin/python -m compileall runner/external_taskbook_validator.py
  result: PASS

.venv/bin/python -m unittest tests.test_external_taskbook_validator
  result: PASS
  observed: Ran 15 tests ... OK

git diff --check
  result: PASS

read-only validator smoke
  result: PASS
  observed:
    validation_result: validation_passed
    fail_closed_result: pass
    recognized_fields: 12
    rejected_fields: []
    known_conflicts: []
    validator_result_is_authority: false
    writes_delivery_state: false
```

---

## 7. 没有运行或没有授权的动作

```yaml id="stage-03-v3-2-not-authorized-zh-cn"
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
  - gate_event_emission
  - delivery_state_transition
  - modifying_/home/jenn/tools/colameta
```

完整 unittest discovery 没有运行，因为本轮是 v3.2 的 focused implementation slice。

---

## 8. 已知缺口和剩余风险

```yaml id="stage-03-v3-2-known-gaps-zh-cn"
known_gaps:
  - validator 消费结构化 claim dictionary，不解析任意 Markdown taskbook 文本。
  - validator 只把外部 taskbook 当作有边界声明来检查；v3.3 才负责 import preview。
  - validator 不把 claim 采用进 plan 或 Version candidates。
  - 本轮只运行了 v3.2 focused unittest module。
remaining_risks:
  - v3.3 必须继续区分 validation_passed 和 import preview。
  - v3.4 必须继续区分 import preview 和 Version candidate mapping。
  - v3.5 必须保持 adoption preview，不得在没有单独 hard gate 的情况下实际采用外部 taskbook。
```

结论：v3.2 已经把外部任务书的 fail-closed 校验层立起来了。它可以让不合格、越权、hash 混乱或目标不支持的外部 claim 止步于 preview 之前，但它本身仍然只是证据层，不是采用层。
