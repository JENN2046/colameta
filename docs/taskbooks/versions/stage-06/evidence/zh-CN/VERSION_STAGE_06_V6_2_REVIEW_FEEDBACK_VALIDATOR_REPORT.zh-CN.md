# 证据报告：Stage 6 / v6.2 审查反馈验证器 V1

```yaml id="companion-binding"
companion_binding:
  language: zh-CN
  companion_type: full_chinese_reading_companion
  authority_status: non_authoritative_companion
  source_report: docs/taskbooks/versions/stage-06/evidence/VERSION_STAGE_06_V6_2_REVIEW_FEEDBACK_VALIDATOR_REPORT.md
  source_sha256: 70b4bd7badd2c35cea752cbb7a50b25c022d8d8c8794d5786c207e727f431414
```

## 范围

这份中文 companion 对应 Stage 6 / v6.2 `Review Feedback Validator V1` 的本地证据报告。

`Review Feedback Validator` = 审查反馈验证器。中文意思是：检查反馈是否完整、是否绑定
正确、是否有非法权威声明。它只能判断“可不可以进入预览”，不能生成真正的下一步决策。

## 验证器规则清单

```yaml id="validator-rule-inventory"
validator_rule_inventory:
  required_inputs:
    - review_feedback_candidate
    - review_feedback_schema_ref
    - expected_master_taskbook_hash
    - expected_stage_taskbook_hash
    - expected_version_taskbook_ref
    - expected_reviewer_handoff_package_ref
    - expected_workspace_snapshot_ref
  valid_validation_statuses:
    - valid_for_preview
    - invalid_missing_required_field
    - invalid_binding_mismatch
    - invalid_unknown_review_decision
    - invalid_pass_alias_policy_missing
    - invalid_forbidden_authority_claim
  forbidden_outputs:
    - commander_decision_request
    - review_decision_record
    - gate_event
    - delivery_state_transition
```

中文解释：`valid_for_preview` = 可进入预览。它只表示“下一层可以生成预览对象”，不是
已经验收、已经进入 accepted，也不是可以继续执行。

## 有效反馈用例

```yaml id="valid-feedback-case"
valid_feedback_case:
  validation_status: valid_for_preview
  normalized_review_decision_value: NEEDS_FIX
  commander_decision_request_created: false
  review_decision_created: false
  gate_event_emitted: false
  delivery_state_transitioned: false
```

## 绑定不匹配用例

```yaml id="binding-mismatch-case"
binding_mismatch_case:
  validation_status: invalid_binding_mismatch
  binding_check_status: failed_closed
  example_mismatch_field: workspace_snapshot_ref
```

中文解释：反馈必须绑定到预期 workspace snapshot、Version Taskbook、handoff package 和
hash。绑定不对，就不能进入预览。

## 未知决策值用例

```yaml id="unknown-decision-case"
unknown_decision_case:
  review_decision_value: AUTO_ACCEPT
  validation_status: invalid_unknown_review_decision
  normalized_review_decision_value: null
```

## PASS 缺少政策引用用例

```yaml id="pass-alias-missing-policy-case"
pass_alias_missing_policy_case:
  review_decision_value: PASS
  pass_alias_policy_check:
    status: failed_closed
    policy_ref_required: true
    policy_ref_present: false
  validation_status: invalid_pass_alias_policy_missing
```

中文解释：`PASS` 不是新的正式决策值。它只是旧口径别名，必须带 policy ref，且只能映射到
`ACCEPT`，不能映射到 Delivery State accepted。

## 禁止权威声明用例

```yaml id="forbidden-claim-case"
forbidden_claim_case:
  forbidden_claim: review_feedback_authorizes_executor_continuation
  validation_status: invalid_forbidden_authority_claim
  forbidden_claim_check_status: failed_closed
```

中文解释：反馈不能声称自己能授权 executor 继续，也不能声称能改 plan、发 GateEvent 或推进
交付状态。

## 已运行命令

```text id="commands-run"
.venv/bin/python -m compileall runner/review_feedback_validator.py
.venv/bin/python -m unittest tests.test_review_feedback_validator
git diff --check
sha256sum docs/taskbooks/versions/stage-06/VERSION_STAGE_06_V6_2_REVIEW_FEEDBACK_VALIDATOR_V1.md runner/review_feedback_schema.py docs/taskbooks/versions/stage-06/evidence/VERSION_STAGE_06_V6_1_REVIEW_FEEDBACK_SCHEMA_REPORT.md runner/review_feedback_validator.py tests/test_review_feedback_validator.py
.venv/bin/python -c "from runner.review_feedback_validator import validate_review_feedback_for_preview, example_valid_feedback_for_preview, example_validation_context, validator_rule_inventory; r=validate_review_feedback_for_preview(example_valid_feedback_for_preview(), example_validation_context()); inv=validator_rule_inventory(); print('validation_status:', r['validation_status']); print('rule_statuses:', len(inv['valid_validation_statuses'])); print('normalized_review_decision_value:', r['normalized_review_decision_value']); print('commander_decision_request_created:', str(r['commander_decision_request_created']).lower()); print('gate_event_emitted:', str(r['gate_event_emitted']).lower()); print('delivery_state_transitioned:', str(r['delivery_state_transitioned']).lower())"
```

## 命令结果

```yaml id="command-results"
command_results:
  compileall: passed
  unittest:
    status: passed
    tests_run: 9
  git_diff_check: passed
  smoke:
    validation_status: valid_for_preview
    rule_statuses: 6
    normalized_review_decision_value: NEEDS_FIX
    commander_decision_request_created: false
    gate_event_emitted: false
    delivery_state_transitioned: false
```

## 未运行命令

```yaml id="commands-not-run"
commands_not_run:
  commander_decision_request_generation: not_authorized
  review_decision_creation: not_authorized
  gate_event_emission: not_authorized
  delivery_state_transition: not_authorized
  executor_run: not_authorized
  route_transition: not_authorized
  remote_write: not_authorized
```

## 剩余风险

```yaml id="remaining-risks"
remaining_risks:
  - risk: validation_status_is_not_authority
    note: valid_for_preview 只允许下一层预览检查反馈。
  - risk: preview_not_implemented_here
    note: v6.3 必须单独构造预览对象，不能在本层创建决策请求。
  - risk: evidence_is_not_authority
    note: 本报告只是本地证据，不批准 review acceptance。
```
