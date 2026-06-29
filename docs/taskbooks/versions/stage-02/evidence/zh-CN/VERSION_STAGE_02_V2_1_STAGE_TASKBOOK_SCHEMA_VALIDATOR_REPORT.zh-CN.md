# Stage 2 / v2.1 阶段任务书模式与校验器 V1 证据报告中文 Companion

```yaml id="stage-02-v2-1-evidence-zh-cn-summary"
chinese_companion:
  source_document: docs/taskbooks/versions/stage-02/evidence/VERSION_STAGE_02_V2_1_STAGE_TASKBOOK_SCHEMA_VALIDATOR_REPORT.md
  source_sha256: 4f4c85fc8eb3f76e59bf28406dce0edde36d15161012fc7bbe56f2a254d9e7f6
  translation_status: companion_draft
  authority_status: evidence_reference_only
```

这份中文 companion 对应英文证据报告。它解释 Stage 2 / v2.1
`Stage Taskbook Schema And Validator V1`，中文叫“阶段任务书模式与校验器 V1”。
它不授权 commit、push、executor run、route transition、review acceptance 或
delivery state accepted。

---

## 1. 这次做了什么

这次实现的是 Stage Taskbook schema 和 validator，也就是“阶段任务书模式”和
“阶段任务书校验器”。

中文大白话：Stage Taskbook 以后不能只是普通文档。它必须说明自己是谁、绑定哪份
Master、为什么支持项目最终目标、哪些事情不做、什么时候算 gate-ready、证据包最少
要有哪些字段。v2.1 的 validator 会检查这些最小字段，缺关键字段就 fail closed。

它明确不做：

- 不修改 `PROJECT_MASTER_TASKBOOK.md`；
- 不修改 `PROJECT_MASTER_TASKBOOK.zh-CN.md`；
- 不修改任何 Stage Taskbook 源文件；
- 不修改 Stage 0 / Stage 1 Version 文件；
- 不创建 Stage Taskbook registry；
- 不运行 executor；
- 不创建 ReviewDecision；
- 不创建 GateEvent；
- 不写 delivery_state；
- 不声称 accepted。

`Schema` = 模式。中文意思是：规定一类文档至少应该有哪些字段、哪些边界、哪些检查项。

`Validator` = 校验器。中文意思是：读取文档后检查它是不是满足 schema，输出证据结果。

`Fail Closed` = 失败时关闭。中文意思是：如果证据缺失或不清楚，就按不通过处理，不能默认放行。

---

## 2. 命令执行结果

关键验证结果：

```text
git status -sb
  结果：通过
  观察值：
    main 相对 origin/main 本地 ahead 53
    当前新增 .colameta/taskbooks/stage_taskbook_schema.json
    当前新增英文 evidence report
    当前新增中文 companion
    当前新增 runner/stage_taskbook_validator.py
    当前新增 tests/test_stage_taskbook_validator.py

git rev-parse HEAD
  结果：通过
  观察值：3efcdc1d81d40619f35caab9cfe4018e232336ff

git rev-parse origin/main
  结果：通过
  观察值：018ff63b76872504407c537cd46e1e8a2ee5c22e

git rev-list --count origin/main..HEAD
  结果：通过
  观察值：53

sha256sum PROJECT_MASTER_TASKBOOK.md
  结果：通过
  观察值：1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34

sha256sum docs/taskbooks/stages/STAGE_02_STAGE_TASKBOOK_MANAGEMENT.md
  结果：通过
  观察值：b0e1a55121503df4116d9c49031eb07729858c483cc73e6c97730eca0a067876

sha256sum docs/taskbooks/versions/stage-02/VERSION_STAGE_02_V2_1_STAGE_TASKBOOK_SCHEMA_VALIDATOR_V1.md
  结果：通过
  观察值：76c3c12c191609f94c16d292e40217db08c8020792157639011b046cb977c429

sha256sum .colameta/taskbooks/stage_taskbook_schema.json
  结果：通过
  观察值：ded29cfaf8e98dedf57f307d8032e01d4865a7e0d6b673ef47497b62c55b404d

sha256sum runner/stage_taskbook_validator.py
  结果：通过
  观察值：df0ab74eb4b36833912ee62436829e3c06c324bedf382844551938d8be486ae6

sha256sum tests/test_stage_taskbook_validator.py
  结果：通过
  观察值：5369b24514a77435ec50aab982b9c523560384d65b0404e6125b5b6a5b79b7ed

.venv/bin/python -m compileall runner/stage_taskbook_validator.py
  结果：通过

.venv/bin/python -m unittest tests.test_stage_taskbook_validator
  结果：通过，19 个测试 OK

git diff --check
  结果：通过
```

---

## 3. 没有执行的命令

明确没有执行：

```yaml
commands_not_run:
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
  - git_add_or_staging
  - commit
  - credential_read_or_write
  - master_taskbook_mutation
  - stage_taskbook_source_mutation
  - stage_taskbook_registry_creation
  - review_acceptance
  - delivery_state_transition
```

中文解释：这次只做 v2.1 本地实现和 focused test。完整测试套件没有跑，因为这次授权是窄授权。

---

## 4. 改了哪些文件

创建了这些文件：

```yaml
files_changed:
  created:
    - .colameta/taskbooks/stage_taskbook_schema.json
    - runner/stage_taskbook_validator.py
    - tests/test_stage_taskbook_validator.py
    - docs/taskbooks/versions/stage-02/evidence/VERSION_STAGE_02_V2_1_STAGE_TASKBOOK_SCHEMA_VALIDATOR_REPORT.md
    - docs/taskbooks/versions/stage-02/evidence/zh-CN/VERSION_STAGE_02_V2_1_STAGE_TASKBOOK_SCHEMA_VALIDATOR_REPORT.zh-CN.md
  modified: []
  forbidden_files_touched: []
```

Master、Stage Taskbook 源文件、Stage 0/1 Version 文件和 freeze packets 都保持只读。

---

## 5. Schema Contract Summary = 模式合约摘要

```yaml
schema_contract_summary:
  schema_file: .colameta/taskbooks/stage_taskbook_schema.json
  schema_version: stage_taskbook_schema.v1
  required_field_groups:
    static_required_fields:
      - stage_id
      - stage_name
      - chinese_name
      - status
      - authority_status
      - master_taskbook_ref
      - supports_project_goal
      - stage_purpose
      - entry_criteria
      - exit_criteria
      - deliverables
      - gate_readiness_criteria
      - minimum_evidence_package
      - non_goals
    readiness_contract_fields:
      - minimum_readiness_claim
      - required_evidence
      - gate_question
      - explicit_non_goal
    boundary_fields:
      - state_authority_boundary
      - execution_authorization_boundary
      - mutation_boundary
```

中文解释：schema 先把 Stage Taskbook 必须具备的字段钉住。后续 v2.2 registry 不能绕过这些检查。

---

## 6. Validator Behavior Summary = 校验器行为摘要

```yaml
validator_behavior_summary:
  helper: runner/stage_taskbook_validator.py
  parser_mode: bounded_markdown_and_yaml_block_text_checks
  no_external_yaml_dependency: true
  fail_closed_when:
    - schema_or_stage_content_is_unavailable
    - missing_master_taskbook_ref
    - master_binding_hash_without_path
    - master_hash_mismatch
    - supports_project_goal_is_missing_or_not_true
    - missing_stage_purpose
    - missing_non_goals
    - non_goals_heading_without_machine_checkable_field
    - missing_gate_readiness_criteria
    - gate_readiness_heading_without_machine_checkable_field
    - missing_minimum_evidence_package
    - minimum_evidence_package_field_mentions_outside_required_fields
    - stage_claims_delivery_state_accepted
    - delivery_state_accepted_phrase_from_schema_pattern
    - review_acceptance_true_claim
    - stage_claims_execution_authority
  machine_checkable_fail_closed_fields_do_not_pass_on_anchor_only: true
  anchor_fallback_allowed_fields:
    - stage_purpose
  master_binding_path_required: true
  minimum_evidence_package_required_fields_section_only: true
  forbidden_claim_detection_uses_schema_patterns: true
  review_acceptance_true_fails_closed: true
  mutates_stage_taskbook_sources: false
  mutates_master_taskbook: false
  validator_result_is_authority: false
```

中文解释：validator 使用轻量 markdown/YAML block 文本检查，不引入 PyYAML 依赖。它的结果只是证据，
不是状态权威。收紧后的规则还明确要求：fail-closed 关键字段不能只靠标题通过，只有
`stage_purpose` 保留标题正文兜底；Master 绑定必须写出路径；最小证据包字段必须位于
`minimum_evidence_package.required_fields` 下面；禁用权威声明要读取 schema 里的 pattern，
包括 `review_acceptance: true`。

---

## 7. 当前 Stage 2 校验结果

```yaml
current_stage_2_required_field_check_table:
  validation_result: passed
  fail_closed_result: pass
  stage_id: stage_02_stage_taskbook_management
  stage_taskbook_hash: b0e1a55121503df4116d9c49031eb07729858c483cc73e6c97730eca0a067876
  yaml_block_count: 11
  fail_closed_violations: []
  required_field_violations: []
```

中文解释：当前 Stage 2 Taskbook 满足 v2.1 最小 schema 检查。

---

## 8. Master Binding Check = 主任务书绑定检查

```yaml
master_binding_check:
  current_stage_2_result: present
  master_taskbook_ref:
    path: PROJECT_MASTER_TASKBOOK.md
    raw_snapshot_sha256: 1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34
  expected_master_taskbook_hash: 1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34
  mismatch_fails_closed: true
```

中文解释：Stage 2 明确绑定到当前 freeze_candidate Master raw snapshot hash。hash 不一致会 fail closed。

---

## 9. Fail-Closed Negative Case Results = 失败时关闭负例结果

```yaml
fail_closed_negative_case_results:
  covered_by_focused_tests:
    - missing_master_taskbook_ref
    - master_binding_hash_without_path
    - master_hash_mismatch
    - supports_project_goal_false
    - missing_non_goals
    - non_goals_heading_without_machine_checkable_field
    - missing_gate_readiness_criteria
    - gate_readiness_heading_without_machine_checkable_field
    - missing_minimum_evidence_package
    - minimum_evidence_package_field_mentions_outside_required_fields
    - accepted_true_claim
    - delivery_state_accepted_phrase_from_schema_pattern
    - review_acceptance_true_claim
    - execution_authority_granted_claim
    - missing_stage_taskbook_content_known_unknown
  current_stage_2_forbidden_claims: []
```

中文解释：测试覆盖了最容易出界的负例：缺 Master 绑定、hash 不一致、缺 non-goals、
缺 gate-readiness、缺 evidence package、乱声称 accepted、乱声称 execution authority。

---

## 10. Known Gaps = 已知缺口

```yaml
known_gaps:
  - validator_does_not_perform_full_semantic_review
  - validator_does_not_create_or_mutate_stage_taskbook_registry
  - validator_does_not_authorize_bootstrap_registration_mode
  - validator_does_not_probe_live_remote_state
```

---

## 11. Remaining Risks = 剩余风险

```yaml
remaining_risks:
  - future_v2_2_registry_must_consume_validator_result_instead_of_bypassing_it
  - future_stage_taskbook_registration_requires_separate_authorization
  - remote_state_may_have_changed_because_fetch_pull_was_not_authorized
```
