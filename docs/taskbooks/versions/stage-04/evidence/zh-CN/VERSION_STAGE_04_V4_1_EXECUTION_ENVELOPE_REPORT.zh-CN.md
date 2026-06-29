# 证据报告中文 companion：Stage 4 / v4.1 Machine-checkable Execution Envelope V1

```yaml id="stage-04-v4-1-evidence-zh-cn-summary"
chinese_companion:
  companion_id: stage_04_v4_1_execution_envelope_evidence_zh_cn
  source_report: docs/taskbooks/versions/stage-04/evidence/VERSION_STAGE_04_V4_1_EXECUTION_ENVELOPE_REPORT.md
  source_sha256: f8e6a0d674c0d41e03e1b03f114e64c2579346827876f6f9e61a367ee372d020
  language: zh-CN
  authority_status: non_authoritative_reading_companion
  review_acceptance: false
  delivery_state_accepted: false
```

这份文件是 v4.1 英文证据报告的中文阅读 companion。它不是新的权威副本，不产生 executor dispatch、计划修改、allowed_files 扩展、commit、push、审查接受、GateEvent 或 delivery state accepted。

v4.1 的目标是实现 `Machine-checkable Execution Envelope V1`，中文是“机器可检查执行信封 V1”。它把候选执行的边界做成机器可检查对象：绑定哪个 Master、Stage、Version Taskbook，是什么 `authority_mode`，允许哪些文件和命令，禁止哪些文件，验证命令是什么，超时、网络、密钥、破坏性操作、重试和停止条件是什么。

最关键的边界：ExecutionEnvelope 存在或通过校验，不等于可以 dispatch executor。

---

## 1. 本轮实现摘要

```yaml id="stage-04-v4-1-implementation-summary-zh-cn"
implementation_summary:
  source_version_taskbook: docs/taskbooks/versions/stage-04/VERSION_STAGE_04_V4_1_MACHINE_CHECKABLE_EXECUTION_ENVELOPE_V1.md
  source_version_taskbook_sha256: 22e99e01a854c6d8fe1fc4f0ceba38f5d2b1ce28d796596f80f4292459071dfa
  implementation_authorization_head: 0992385679cc06f6ab317d872fab95f18c58b8ef
  master_taskbook_sha256: 1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34
  stage_04_taskbook_sha256: 05e6114a666942c0641c635905c2295feaa62b98bd9e7b5166babd662e015a41
  stage_3_version_set_confirmation_sha256: 8695cf9f9b29608011dfc4691fd12df5a4f21f879e025e999c8bba5ae929e313
  execution_envelope_helper_sha256: e2c0c616408ff15f24d3353103686ce004d08c22ab43f3e6938aeed80efe381f
  execution_envelope_tests_sha256: c1a814ad4343a88724e7e909e8e5dd39f1e7cfbd57f79bb1d431c4aeccae9244
```

本轮新增 4 个允许范围内的文件：

```yaml id="stage-04-v4-1-files-changed-zh-cn"
files_changed:
  created:
    - runner/execution_envelope.py
    - tests/test_execution_envelope.py
    - docs/taskbooks/versions/stage-04/evidence/VERSION_STAGE_04_V4_1_EXECUTION_ENVELOPE_REPORT.md
    - docs/taskbooks/versions/stage-04/evidence/zh-CN/VERSION_STAGE_04_V4_1_EXECUTION_ENVELOPE_REPORT.zh-CN.md
  modified: []
  forbidden_files_touched: []
```

本轮没有修改 Master、中文 Master companion、Stage Taskbook、Version Taskbook、freeze packet、`.colameta/plan.json`、executor state、route state 或服务运行时。

---

## 2. ExecutionEnvelope Contract 中文解释

`ExecutionEnvelope` 可以理解成“执行前必须装好的安全信封”。它不负责执行，只负责让系统能检查：这个执行请求有没有边界、有没有授权引用、有没有命令范围、有没有停止条件。

最小字段如下：

```yaml id="stage-04-v4-1-envelope-contract-zh-cn"
envelope_contract_summary:
  helper: runner.execution_envelope.validate_execution_envelope
  envelope_schema_version: execution_envelope.v1
  required_fields:
    - envelope_id
    - envelope_schema_version
    - version_taskbook_ref
    - master_taskbook_ref
    - stage_taskbook_ref
    - authority_mode
    - local_execution_authorization_ref
    - imported_receipt_authorization_ref
    - allowed_files
    - forbidden_files
    - allowed_commands
    - validation_commands
    - timeout_limits
    - network_policy
    - secrets_policy
    - destructive_operation_policy
    - retry_policy
    - stop_conditions
  valid_authority_modes:
    - local_execution
    - imported_receipt
    - validation_only
```

字段中文解释：

```yaml id="stage-04-v4-1-field-meaning-zh-cn"
field_meaning:
  envelope_id: 信封 ID。
  envelope_schema_version: 信封 schema 版本。
  version_taskbook_ref: 绑定的 Version Taskbook。
  master_taskbook_ref: 绑定的 Master Taskbook。
  stage_taskbook_ref: 绑定的 Stage Taskbook。
  authority_mode: 权限模式。
  local_execution_authorization_ref: 本地执行授权引用。
  imported_receipt_authorization_ref: 外部回执导入授权引用。
  allowed_files: 候选执行允许触碰的文件。
  forbidden_files: 候选执行禁止触碰的文件。
  allowed_commands: 候选允许命令。
  validation_commands: 验证命令。
  timeout_limits: 超时限制。
  network_policy: 网络策略。
  secrets_policy: 密钥策略。
  destructive_operation_policy: 破坏性操作策略。
  retry_policy: 重试策略。
  stop_conditions: 停止条件。
```

---

## 3. 有效信封示例

```yaml id="stage-04-v4-1-valid-envelope-zh-cn"
valid_envelope_example:
  envelope_check_result: envelope_check_passed
  validation_result: passed
  authority_mode: validation_only
  rejected_fields: []
  dispatch_authorized_by_envelope_existence: false
  executor_dispatch_authorized: false
  plan_mutation_authorized: false
  allowed_files_expansion_authorized: false
  commit_authorized: false
  push_authorized: false
  delivery_state_accepted: false
```

中文解释：`envelope_check_passed` 只表示信封结构合格，不表示 executor 可以跑。

---

## 4. 拒绝案例

```yaml id="stage-04-v4-1-rejected-examples-zh-cn"
rejected_envelope_examples:
  local_execution_without_local_execution_authorization_ref:
    envelope_check_result: envelope_check_failed_closed
    rejected_field: local_execution_authorization_ref
    rejection_code: LOCAL_EXECUTION_AUTHORIZATION_REF_REQUIRED
  imported_receipt_without_imported_receipt_authorization_ref:
    envelope_check_result: envelope_check_failed_closed
    rejected_field: imported_receipt_authorization_ref
  missing_version_taskbook_ref:
    envelope_check_result: envelope_check_failed_closed
    rejected_field: version_taskbook_ref
  master_or_stage_reference_mismatch:
    envelope_check_result: envelope_check_failed_closed
    rejection_code: REFERENCE_MISMATCH
  unknown_authority_mode:
    envelope_check_result: envelope_check_failed_closed
    rejected_field: authority_mode
  empty_allowed_files_or_validation_commands:
    envelope_check_result: envelope_check_failed_closed
  forbidden_authority_claim:
    envelope_check_result: envelope_check_failed_closed
    rejection_code: FORBIDDEN_ENVELOPE_AUTHORITY_CLAIM
```

中文解释：缺授权引用、缺绑定、缺文件范围、缺验证命令、权限模式不认识、或者信封自己声称能授权 dispatch，都会 fail closed。

---

## 5. Authority Mode Check = 权限模式检查

```yaml id="stage-04-v4-1-authority-mode-check-zh-cn"
authority_mode_check:
  validation_only:
    local_execution_authorization_ref_required: false
    imported_receipt_authorization_ref_required: false
    dispatch_authorized: false
  local_execution:
    local_execution_authorization_ref_required: true
    imported_receipt_authorization_ref_grants_dispatch: false
    dispatch_authorized_by_envelope: false
  imported_receipt:
    imported_receipt_authorization_ref_required: true
    local_execution_authorization_ref_grants_receipt_adoption: false
    dispatch_authorized_by_envelope: false
```

中文解释：`local_execution`、`imported_receipt`、`validation_only` 三种模式不能混用授权。尤其是本地执行授权不能拿来采纳外部回执，外部回执授权也不能拿来启动本地执行。

---

## 6. 边界非授权检查

```yaml id="stage-04-v4-1-boundary-check-zh-cn"
boundary_non_authorization_check:
  envelope_result_is_authority: false
  envelope_existence_authorizes_dispatch: false
  envelope_authorizes_allowed_files_expansion: false
  envelope_authorizes_plan_mutation: false
  envelope_authorizes_commit: false
  envelope_authorizes_push: false
  envelope_writes_delivery_state: false
  creates_review_decision: false
  emits_gate_event: false
  dispatch_authorized_by_envelope_existence: false
  executor_dispatch_authorized: false
  allowed_files_expansion_authorized: false
  plan_mutation_authorized: false
  commit_authorized: false
  push_authorized: false
  delivery_state_accepted: false
```

中文大白话：信封只是边界检查对象，不是授权令牌。

---

## 7. 已运行验证

```text id="stage-04-v4-1-validation-zh-cn"
git status -sb
  result: PASS
  observed_after_stage_3_closeout_before_reports:
    ## main...origin/main [ahead 62]
    ?? runner/execution_envelope.py
    ?? tests/test_execution_envelope.py

git rev-parse HEAD
  result: PASS
  observed: 0992385679cc06f6ab317d872fab95f18c58b8ef

git rev-list --count origin/main..HEAD
  result: PASS
  observed: 62

sha256sum PROJECT_MASTER_TASKBOOK.md docs/taskbooks/stages/STAGE_04_BOUNDED_EXECUTION_AND_EVIDENCE.md docs/taskbooks/versions/stage-04/VERSION_STAGE_04_V4_1_MACHINE_CHECKABLE_EXECUTION_ENVELOPE_V1.md docs/taskbooks/versions/stage-03/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_03_VERSIONS.md runner/execution_envelope.py tests/test_execution_envelope.py
  result: PASS

.venv/bin/python -m compileall runner/execution_envelope.py
  result: PASS

.venv/bin/python -m unittest tests.test_execution_envelope
  result: PASS
  observed: Ran 14 tests ... OK

git diff --check
  result: PASS

read-only envelope smoke
  result: PASS
  observed:
    envelope_check_result: envelope_check_passed
    authority_mode: validation_only
    rejected_fields: []
    dispatch_authorized_by_envelope_existence: false
    executor_dispatch_authorized: false
    delivery_state_accepted: false
```

---

## 8. 没有运行或没有授权的动作

```yaml id="stage-04-v4-1-not-authorized-zh-cn"
not_authorized_and_not_run:
  - fetch
  - pull
  - push
  - force_push
  - executor_run
  - executor_dispatch
  - route_transition
  - service_restart
  - release
  - deploy
  - remote_write
  - full_unittest_discovery
  - plan_mutation
  - allowed_files_expansion
  - commit_authorization_by_envelope
  - review_acceptance
  - review_decision_creation
  - gate_event_emission
  - delivery_state_transition
  - modifying_/home/jenn/tools/colameta
```

---

## 9. 已知缺口和剩余风险

```yaml id="stage-04-v4-1-known-gaps-zh-cn"
known_gaps:
  - envelope helper 校验结构化 dictionary，不解析任意 taskbook Markdown。
  - envelope validation 不 dispatch executor，也不运行命令。
  - envelope validation 不创建 receipt、ReviewDecision、GateEvent 或 delivery state transition。
  - 本轮只运行了 v4.1 focused unittest module。
remaining_risks:
  - v4.2 必须继续区分 envelope-valid 和 executor-run-authorized。
  - 未来 executor dispatch 代码必须要求单独的 hash-specific authorization，而不是只看 envelope existence。
  - 未来展示层不能把 envelope_check_passed 显示成 accepted delivery state。
```

结论：v4.1 已经把 Stage 4 的执行边界信封立起来了。它能在 dispatch 前拒绝缺范围、缺授权引用或越权的候选执行请求，但它自己不授权执行。
