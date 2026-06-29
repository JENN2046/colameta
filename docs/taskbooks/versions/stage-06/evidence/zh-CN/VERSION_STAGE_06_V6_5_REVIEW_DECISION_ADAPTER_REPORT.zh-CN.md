# 证据报告：Stage 6 / v6.5 审查决策适配器 V1

```yaml id="companion-binding"
companion_binding:
  language: zh-CN
  companion_type: full_chinese_reading_companion
  authority_status: non_authoritative_companion
  source_report: docs/taskbooks/versions/stage-06/evidence/VERSION_STAGE_06_V6_5_REVIEW_DECISION_ADAPTER_REPORT.md
  source_sha256: 894417baa2f894744d2ebe111f8b086b3c0f7593b12bbb65fb91062a9a4413ad
```

## 范围

这份中文 companion 对应 Stage 6 / v6.5 `Review Decision Adapter V1` 的本地证据报告。

`Review Decision Adapter` = 审查决策适配器。中文意思是：把不同来源的审查词汇规整到
四个正式 ReviewDecision 值里，但它不创建 ReviewDecision 记录，也不写 GateEvent。

## 原生值映射用例

```yaml id="native-value-mapping-cases"
native_value_mapping_cases:
  ACCEPT:
    normalized_review_decision_value: ACCEPT
  NEEDS_FIX:
    normalized_review_decision_value: NEEDS_FIX
  PLAN_ADJUST:
    normalized_review_decision_value: PLAN_ADJUST
  ABORT:
    normalized_review_decision_value: ABORT
  authority_effects:
    review_decision_created: false
    gate_event_emitted: false
    delivery_state_transitioned: false
```

中文解释：四个原生值只会映射到自己，不会顺手生成审查记录或状态事件。

## PASS 别名政策用例

```yaml id="pass-alias-policy-case"
pass_alias_policy_case:
  original_value: PASS
  alias_policy_ref_when_used: legacy-pass-alias-policy-v1
  normalized_review_decision_value: ACCEPT
  alias_disclosure:
    alias_used: true
    must_surface_alias: true
    does_not_mean_runtime_PASSED: true
    does_not_mean_delivery_state_accepted: true
    does_not_mean_validation_passed_as_review_acceptance: true
```

中文解释：`PASS` 只能在带 policy ref 时映射成 `ACCEPT`。它不是 runtime `PASSED`，
也不是 delivery state `accepted`。

## 未知值拒绝用例

```yaml id="unknown-value-rejection-case"
unknown_value_rejection_case:
  original_value: AUTO_ACCEPT
  adapter_status: review_decision_adapter_failed_closed
  rejection_code: UNKNOWN_REVIEW_VALUE
```

## 运行态等价拒绝用例

```yaml id="runtime-state-equivalence-rejection-case"
runtime_state_equivalence_rejection_case:
  runtime_value: PASSED
  adapter_status: review_decision_adapter_failed_closed
  rejection_code: RUNTIME_STATE_EQUIVALENCE_FORBIDDEN
  forbidden_equivalence_claim_rejected: ACCEPT_equals_delivery_state_accepted
```

中文解释：`PASSED` 是运行态/验证态词，不是 ReviewDecision 值。`ACCEPT` 也不能等价成
delivery state accepted。

## 禁止输出检查

```yaml id="forbidden-output-check"
forbidden_output_check:
  review_decision_created: false
  gate_event_emitted: false
  delivery_state_transitioned: false
  runtime_state_transitioned: false
  commander_authorization_granted: false
```

## 已运行命令

```text id="commands-run"
.venv/bin/python -m compileall runner/review_decision_adapter.py
.venv/bin/python -m unittest tests.test_review_decision_adapter
git diff --check
sha256sum docs/taskbooks/versions/stage-06/VERSION_STAGE_06_V6_5_REVIEW_DECISION_ADAPTER_V1.md runner/commander_decision_request.py docs/taskbooks/versions/stage-06/evidence/VERSION_STAGE_06_V6_4_REVIEW_FEEDBACK_CLASSIFICATION_AND_DECISION_REQUEST_REPORT.md runner/review_decision_adapter.py tests/test_review_decision_adapter.py
.venv/bin/python -c "from runner.review_decision_adapter import adapt_review_decision_value, review_decision_adapter_inventory; r=adapt_review_decision_value('PASS', alias_policy_ref='legacy-pass-alias-policy-v1'); inv=review_decision_adapter_inventory(); print('adapter_status:', r['adapter_status']); print('normalized_review_decision_value:', r['normalized_review_decision_value']); print('native_values:', len(inv['accepted_native_values'])); print('review_decision_created:', str(r['review_decision_created']).lower()); print('gate_event_emitted:', str(r['gate_event_emitted']).lower()); print('delivery_state_transitioned:', str(r['delivery_state_transitioned']).lower())"
```

## 命令结果

```yaml id="command-results"
command_results:
  compileall: passed
  unittest:
    status: passed
    tests_run: 8
  git_diff_check: passed
  smoke:
    adapter_status: review_decision_value_adapted
    normalized_review_decision_value: ACCEPT
    native_values: 4
    review_decision_created: false
    gate_event_emitted: false
    delivery_state_transitioned: false
```

## 未运行命令

```yaml id="commands-not-run"
commands_not_run:
  review_decision_persistence: not_authorized
  review_acceptance: not_authorized
  gate_event_emission: not_authorized
  runtime_state_mapping: not_authorized
  delivery_state_transition: not_authorized
  executor_run: not_authorized
  route_transition: not_authorized
  push: not_authorized
```

## 剩余风险

```yaml id="remaining-risks"
remaining_risks:
  - risk: adapter_is_not_persistence
    note: v6.5 只规整值，不持久化 ReviewDecision 记录。
  - risk: thin_loop_needs_package_review
    note: Stage 6 v6.1-v6.5 仍需要包级审查，才能进入下一路线。
  - risk: evidence_is_not_authority
    note: 本报告只是本地证据，不授权 accepted 交付状态。
```
