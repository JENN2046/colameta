# 证据报告：Stage 6 / v6.3 审查反馈预览 V1

```yaml id="companion-binding"
companion_binding:
  language: zh-CN
  companion_type: full_chinese_reading_companion
  authority_status: non_authoritative_companion
  source_report: docs/taskbooks/versions/stage-06/evidence/VERSION_STAGE_06_V6_3_REVIEW_FEEDBACK_PREVIEW_REPORT.md
  source_sha256: 1deb452cb63dc5d78ec7216648fc2b1a76c7449a7cd8b19a711ffda736fd9fc3
```

## 范围

这份中文 companion 对应 Stage 6 / v6.3 `Review Feedback Preview V1` 的本地证据报告。

`Review Feedback Preview` = 审查反馈预览。中文意思是：反馈通过验证后，先展示“可能会往
哪个下一步走、将来可能需要向 Commander 问什么”，但不真正创建请求、不写状态。

## 预览映射清单

```yaml id="preview-mapping-inventory"
preview_mapping_inventory:
  candidate_classification_values:
    - candidate_accept_path
    - candidate_needs_fix_path
    - candidate_plan_adjust_path
    - candidate_abort_path
    - candidate_blocked_unclear_feedback
  decision_mapping:
    ACCEPT: candidate_accept_path
    NEEDS_FIX: candidate_needs_fix_path
    PLAN_ADJUST: candidate_plan_adjust_path
    ABORT: candidate_abort_path
  forbidden_outputs:
    - commander_decision_request_id
    - review_decision_record
    - gate_event
    - delivery_state_transition
    - plan_mutation
    - executor_continuation
```

中文解释：preview 可以说“候选路径是什么”，但不能生成真正的
`CommanderDecisionRequest id`。

## ACCEPT 预览用例

```yaml id="accept-preview-case"
accept_preview_case:
  candidate_classification: candidate_accept_path
  preview_question: Ask Commander whether to request Delivery State Gate review.
  commander_decision_request_created: false
  delivery_state_transitioned: false
```

中文解释：`ACCEPT` 预览只表示可能要问 Commander 是否进入 Delivery State Gate 审查，
不是直接把状态改成 accepted。

## NEEDS_FIX 预览用例

```yaml id="needs-fix-preview-case"
needs_fix_preview_case:
  candidate_classification: candidate_needs_fix_path
  preview_question_includes_rework: true
  commander_decision_request_created: false
  plan_mutation: false
```

## PLAN_ADJUST 预览用例

```yaml id="plan-adjust-preview-case"
plan_adjust_preview_case:
  candidate_classification: candidate_plan_adjust_path
  boundary_notice:
    preview_is_not_plan_mutation: true
  commander_decision_request_created: false
```

## ABORT 预览用例

```yaml id="abort-preview-case"
abort_preview_case:
  candidate_classification: candidate_abort_path
  commander_decision_request_id_created: false
  runtime_cancelled: false
```

## PASS 别名预览用例

```yaml id="pass-alias-preview-case"
pass_alias_preview_case:
  review_decision_value: PASS
  candidate_classification: candidate_accept_path
  alias_mapping_notice:
    pass_alias_used: true
    maps_to: ACCEPT
    does_not_mean_delivery_state_accepted: true
```

中文解释：`PASS` 可以预览成 `ACCEPT` 路径，但必须保留别名说明，不能偷换成
Delivery State accepted。

## 边界声明检查

```yaml id="boundary-notice-check"
boundary_notice_check:
  required_notices:
    - preview_is_not_commander_decision_request
    - preview_is_not_review_decision
    - preview_is_not_gate_event
    - preview_is_not_delivery_state_transition
    - preview_is_not_plan_mutation
    - preview_is_not_executor_continuation
  actionable_request_id_result: rejected_by_contract
  missing_boundary_notice_result: rejected_by_contract
```

## 已运行命令

```text id="commands-run"
.venv/bin/python -m compileall runner/review_feedback_preview.py
.venv/bin/python -m unittest tests.test_review_feedback_preview
git diff --check
sha256sum docs/taskbooks/versions/stage-06/VERSION_STAGE_06_V6_3_REVIEW_FEEDBACK_PREVIEW_V1.md runner/review_feedback_validator.py docs/taskbooks/versions/stage-06/evidence/VERSION_STAGE_06_V6_2_REVIEW_FEEDBACK_VALIDATOR_REPORT.md runner/review_feedback_preview.py tests/test_review_feedback_preview.py
.venv/bin/python -c "from runner.review_feedback_preview import build_review_feedback_preview, preview_mapping_inventory; from runner.review_feedback_validator import example_valid_feedback_for_preview, example_validation_context, validate_review_feedback_for_preview; f=example_valid_feedback_for_preview(); v=validate_review_feedback_for_preview(f, example_validation_context()); p=build_review_feedback_preview(f, v); inv=preview_mapping_inventory(); print('preview_status:', p['preview_status']); print('candidate_classification:', p['candidate_classification']); print('candidate_paths:', len(inv['candidate_classification_values'])); print('commander_decision_request_created:', str(p['commander_decision_request_created']).lower()); print('gate_event_emitted:', str(p['gate_event_emitted']).lower()); print('delivery_state_transitioned:', str(p['delivery_state_transitioned']).lower())"
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
    preview_status: review_feedback_preview_available
    candidate_classification: candidate_needs_fix_path
    candidate_paths: 5
    commander_decision_request_created: false
    gate_event_emitted: false
    delivery_state_transitioned: false
```

## 未运行命令

```yaml id="commands-not-run"
commands_not_run:
  commander_decision_request_creation: not_authorized
  review_decision_creation: not_authorized
  gate_event_emission: not_authorized
  plan_mutation: not_authorized
  executor_continuation: not_authorized
  delivery_state_transition: not_authorized
  remote_write: not_authorized
```

## 剩余风险

```yaml id="remaining-risks"
remaining_risks:
  - risk: preview_is_not_classification_finalization
    note: v6.4 必须单独定义分类和决策请求处理。
  - risk: candidate_shape_is_not_actionable
    note: preview 故意不创建可执行的 CommanderDecisionRequest id。
  - risk: evidence_is_not_authority
    note: 本报告只是本地证据，不授权路线或状态移动。
```
