# 证据报告：Stage 6 / v6.4 审查反馈分类与决策请求 V1

```yaml id="companion-binding"
companion_binding:
  language: zh-CN
  companion_type: full_chinese_reading_companion
  authority_status: non_authoritative_companion
  source_report: docs/taskbooks/versions/stage-06/evidence/VERSION_STAGE_06_V6_4_REVIEW_FEEDBACK_CLASSIFICATION_AND_DECISION_REQUEST_REPORT.md
  source_sha256: d3f4f5fef7d19b91662f6433d8463a94f228953ae7581cf531f540926e9366f8
```

## 范围

这份中文 companion 对应 Stage 6 / v6.4
`Review Feedback Classification And Decision Request V1` 的本地证据报告。

`CommanderDecisionRequest` = 指挥官决策请求。中文意思是：系统把下一步问题整理成一个
请求，等 Commander 决定；它不是 Commander 已经授权。

## 分类映射清单

```yaml id="classification-mapping-inventory"
classification_mapping_inventory:
  classification_values:
    - accept_review_feedback
    - needs_fix_review_feedback
    - plan_adjust_review_feedback
    - abort_review_feedback
    - blocked_unclear_review_feedback
  decision_mapping:
    ACCEPT: accept_review_feedback
    NEEDS_FIX: needs_fix_review_feedback
    PLAN_ADJUST: plan_adjust_review_feedback
    ABORT: abort_review_feedback
  forbidden_classification_claims:
    - classification_is_review_acceptance
    - classification_is_delivery_state
    - classification_authorizes_route
    - classification_authorizes_executor
```

中文解释：分类只是把反馈归入候选路径，不是验收，不是交付状态，也不是路线授权。

## 指挥官决策请求字段清单

```yaml id="commander-decision-request-field-inventory"
commander_decision_request_field_inventory:
  request_schema_version: commander_decision_request.v1
  required_field_count: 14
  required_fields:
    - commander_decision_request_id
    - request_schema_version
    - source_review_feedback_ref
    - source_review_decision_value
    - normalized_classification
    - reviewer_handoff_package_ref
    - version_taskbook_ref
    - execution_report_ref
    - workspace_snapshot_ref
    - master_taskbook_hash
    - stage_taskbook_hash
    - requested_commander_action
    - allowed_commander_responses
    - non_authority_notice
  allowed_commander_responses:
    - AUTHORIZE_GATE_REVIEW_REQUEST
    - AUTHORIZE_REWORK_PLANNING
    - AUTHORIZE_PLAN_ADJUSTMENT_DRAFT
    - AUTHORIZE_ABORT_HANDLING_DRAFT
    - RETURN_FOR_CLARIFICATION
    - REJECT_REQUEST
```

中文解释：请求可以有 `commander_decision_request_id`，因为 v6.4 的目标就是生成请求；
但这个 id 不是授权 token，也不能自动执行请求动作。

## ACCEPT 请求用例

```yaml id="accept-request-case"
accept_request_case:
  normalized_classification: accept_review_feedback
  requested_commander_action: ask_whether_to_request_delivery_state_gate_review
  commander_authorization_granted: false
  delivery_state_transitioned: false
```

中文解释：`ACCEPT` 只会生成“是否请求 Delivery State Gate review”的问题，不会直接把
delivery state 改成 accepted。

## NEEDS_FIX 请求用例

```yaml id="needs-fix-request-case"
needs_fix_request_case:
  normalized_classification: needs_fix_review_feedback
  requested_commander_action: ask_whether_to_prepare_rework_or_gate_return
  execute_requested_action: false
  mutate_plan: false
```

## PLAN_ADJUST 请求用例

```yaml id="plan-adjust-request-case"
plan_adjust_request_case:
  normalized_classification: plan_adjust_review_feedback
  requested_commander_action: ask_whether_to_prepare_plan_adjustment_draft
  mutate_plan: false
```

## ABORT 请求用例

```yaml id="abort-request-case"
abort_request_case:
  normalized_classification: abort_review_feedback
  requested_commander_action: ask_whether_to_prepare_abort_or_supersede_handling
  execute_requested_action: false
```

## PASS 别名请求用例

```yaml id="pass-alias-request-case"
pass_alias_request_case:
  source_review_decision_value: PASS
  normalized_classification: accept_review_feedback
  delivery_state_transitioned: false
  commander_authorization_granted: false
```

## 禁止效果检查

```yaml id="forbidden-effect-check"
forbidden_effect_check:
  commander_authorization_granted: false
  execute_requested_action: false
  mutate_plan: false
  emit_gate_event: false
  continue_executor: false
  commit_or_push: false
  review_decision_created: false
  gate_event_emitted: false
  delivery_state_transitioned: false
```

## 已运行命令

```text id="commands-run"
.venv/bin/python -m compileall runner/review_feedback_classification.py runner/commander_decision_request.py
.venv/bin/python -m unittest tests.test_review_feedback_classification tests.test_commander_decision_request
git diff --check
sha256sum docs/taskbooks/versions/stage-06/VERSION_STAGE_06_V6_4_REVIEW_FEEDBACK_CLASSIFICATION_AND_DECISION_REQUEST_V1.md runner/review_feedback_preview.py docs/taskbooks/versions/stage-06/evidence/VERSION_STAGE_06_V6_3_REVIEW_FEEDBACK_PREVIEW_REPORT.md runner/review_feedback_classification.py runner/commander_decision_request.py tests/test_review_feedback_classification.py tests/test_commander_decision_request.py
.venv/bin/python -c "from runner.review_feedback_validator import example_valid_feedback_for_preview, example_validation_context, validate_review_feedback_for_preview; from runner.review_feedback_preview import build_review_feedback_preview; from runner.review_feedback_classification import classify_review_feedback; from runner.commander_decision_request import build_commander_decision_request, commander_decision_request_field_inventory; f=example_valid_feedback_for_preview(); v=validate_review_feedback_for_preview(f, example_validation_context()); p=build_review_feedback_preview(f, v); c=classify_review_feedback(f, v, p, {'mapping_policy_id':'stage-06-v6-4-decision-mapping'}); r=build_commander_decision_request(c, f); inv=commander_decision_request_field_inventory(); print('classification_status:', c['classification_status']); print('request_status:', r['request_status']); print('required_fields:', len(inv['required_fields'])); print('commander_authorization_granted:', str(r['commander_authorization_granted']).lower()); print('gate_event_emitted:', str(r['gate_event_emitted']).lower()); print('delivery_state_transitioned:', str(r['delivery_state_transitioned']).lower())"
```

## 命令结果

```yaml id="command-results"
command_results:
  compileall: passed
  unittest:
    status: passed
    tests_run: 13
  git_diff_check: passed
  smoke:
    classification_status: review_feedback_classification_ready
    request_status: commander_decision_request_available
    required_fields: 14
    commander_authorization_granted: false
    gate_event_emitted: false
    delivery_state_transitioned: false
```

## 未运行命令

```yaml id="commands-not-run"
commands_not_run:
  commander_authorization_grant: not_authorized
  review_decision_creation: not_authorized
  gate_event_emission: not_authorized
  plan_mutation: not_authorized
  executor_continuation: not_authorized
  commit_or_push_from_request: not_authorized
  delivery_state_transition: not_authorized
  remote_write: not_authorized
```

## 剩余风险

```yaml id="remaining-risks"
remaining_risks:
  - risk: request_is_not_authorization
    note: CommanderDecisionRequest 仍需要 Commander 后续明确回应才可执行。
  - risk: adapter_not_implemented_here
    note: v6.5 必须单独定义 ReviewDecision adapter 边界。
  - risk: evidence_is_not_authority
    note: 本报告只是本地证据，不批准 review acceptance。
```
