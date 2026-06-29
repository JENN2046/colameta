# 证据报告：Stage 6 / v6.1 审查反馈模式 V1

```yaml id="companion-binding"
companion_binding:
  language: zh-CN
  companion_type: full_chinese_reading_companion
  authority_status: non_authoritative_companion
  source_report: docs/taskbooks/versions/stage-06/evidence/VERSION_STAGE_06_V6_1_REVIEW_FEEDBACK_SCHEMA_REPORT.md
  source_sha256: e5dc93173b3304a3290a1076d809dbf9a9aabb8bfad8ca056f5b83b18e30cfd1
```

## 范围

这份中文 companion 对应 Stage 6 / v6.1 `Review Feedback Schema V1` 的本地证据报告。

`ReviewFeedback` = 审查反馈。中文意思是：Reviewer 给出的结构化反馈输入。它还不是
最终 `ReviewDecision`，不是 `GateEvent`，也不能直接推动 Delivery State Gate。

## 模式字段清单

```yaml id="schema-field-inventory"
schema_field_inventory:
  schema_version: review_feedback.v1
  required_field_count: 18
  required_fields:
    - review_feedback_id
    - review_feedback_schema_version
    - reviewer_identity_or_source
    - reviewer_authority_scope
    - reviewer_attestation
    - reviewer_handoff_package_ref
    - version_taskbook_ref
    - execution_report_ref
    - workspace_snapshot_ref
    - master_taskbook_hash
    - stage_taskbook_hash
    - review_decision_value
    - pass_alias_policy_id_when_used
    - charter_alignment
    - task_completion
    - scope_assessment
    - reviewer_notes
    - submitted_at
  allowed_review_decision_values:
    - ACCEPT
    - NEEDS_FIX
    - PLAN_ADJUST
    - ABORT
```

中文解释：v6.1 先规定“反馈必须长什么样”。反馈必须绑定 handoff package、Version
Taskbook、执行报告、workspace snapshot、Master hash 和 Stage hash，不能只写一句
“看起来可以”。

## 有效反馈样例

```yaml id="valid-feedback-example"
valid_feedback_example:
  review_feedback_schema_check_result: review_feedback_schema_check_passed
  normalized_review_decision_value: NEEDS_FIX
  review_decision_created: false
  gate_event_emitted: false
  delivery_state_transitioned: false
```

中文解释：样例能通过 schema 检查，但通过检查不等于产生审查决策，也不等于进入
accepted 状态。

## 拒绝样例

```yaml id="rejection-case-examples"
rejection_case_examples:
  missing_reviewer_handoff_package_ref:
    result: failed_closed
    rejected_field: reviewer_handoff_package_ref
  invalid_master_taskbook_hash:
    result: failed_closed
    rejected_field: master_taskbook_hash
  unknown_review_decision_value:
    result: failed_closed
    rejected_field: review_decision_value
  pass_alias_without_policy_ref:
    result: failed_closed
    normalized_review_decision_value: null
  forbidden_delivery_state_claim:
    result: failed_closed
    rejection_code: FORBIDDEN_REVIEW_FEEDBACK_AUTHORITY_CLAIM
```

中文解释：缺绑定、hash 不像 hash、决策值未知、`PASS` 没有别名政策、或者反馈声称能写入
交付状态，都会 fail closed。

## PASS 别名策略样例

```yaml id="pass-alias-policy-example"
pass_alias_policy_example:
  alias: PASS
  maps_to: ACCEPT
  requires_policy_ref: true
  policy_scope: legacy_alias_only_not_delivery_state_accepted
  with_policy_ref_result: review_feedback_schema_check_passed
  without_policy_ref_result: review_feedback_schema_check_failed_closed
  delivery_state_transitioned: false
```

中文解释：`PASS` 只能作为旧口径别名映射到 `ACCEPT`，而且必须带政策引用。它不能表示
Delivery State 已经 accepted。

## 禁止状态权威检查

```yaml id="forbidden-state-claim-check"
forbidden_state_claim_check:
  review_feedback_writes_delivery_state: forbidden
  review_feedback_mutates_plan: forbidden
  review_feedback_authorizes_executor_continuation: forbidden
  accept_means_delivery_state_accepted: forbidden
  review_decision_created: false
  gate_event_emitted: false
  delivery_state_transitioned: false
```

中文解释：审查反馈只是输入，不是状态权威。它不能写 plan，不能授权 executor 继续，也不能
把 `ACCEPT` 偷换成交付状态已 accepted。

## 已运行命令

```text id="commands-run"
.venv/bin/python -m compileall runner/review_feedback_schema.py
.venv/bin/python -m unittest tests.test_review_feedback_schema
git diff --check
sha256sum docs/taskbooks/versions/stage-06/VERSION_STAGE_06_V6_1_REVIEW_FEEDBACK_SCHEMA_V1.md docs/taskbooks/stages/STAGE_06_REVIEW_FEEDBACK_INTAKE.md docs/taskbooks/versions/stage-05/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_05_VERSIONS.md docs/taskbooks/versions/stage-05/evidence/VERSION_STAGE_05_V5_5_REVIEWER_PACKAGE_REPORT_SURFACE_REPORT.md runner/review_feedback_schema.py tests/test_review_feedback_schema.py
.venv/bin/python -c "from runner.review_feedback_schema import validate_review_feedback_schema, example_review_feedback, review_feedback_field_inventory; r=validate_review_feedback_schema(example_review_feedback()); inv=review_feedback_field_inventory(); print('review_feedback_schema_check_result:', r['review_feedback_schema_check_result']); print('fields:', len(inv['required_fields'])); print('allowed_decisions:', ','.join(inv['allowed_review_decision_values'])); print('review_decision_created:', str(r['review_decision_created']).lower()); print('gate_event_emitted:', str(r['gate_event_emitted']).lower()); print('delivery_state_transitioned:', str(r['delivery_state_transitioned']).lower())"
```

## 命令结果

```yaml id="command-results"
command_results:
  compileall: passed
  unittest:
    status: passed
    tests_run: 10
  git_diff_check: passed
  smoke:
    review_feedback_schema_check_result: review_feedback_schema_check_passed
    fields: 18
    allowed_decisions:
      - ACCEPT
      - NEEDS_FIX
      - PLAN_ADJUST
      - ABORT
    review_decision_created: false
    gate_event_emitted: false
    delivery_state_transitioned: false
```

## 未运行命令

```yaml id="commands-not-run"
commands_not_run:
  executor_run: not_authorized
  route_transition: not_authorized
  plan_mutation: not_authorized
  review_decision_creation: not_authorized
  gate_event_emission: not_authorized
  delivery_state_transition: not_authorized
  remote_write: not_authorized
```

## 剩余风险

```yaml id="remaining-risks"
remaining_risks:
  - risk: schema_only_not_feedback_intake
    note: v6.1 只定义输入形状；v6.2 仍要单独验证反馈实例。
  - risk: stage_5_packet_hash_observed_differs_from_historical_taskbook_binding
    note: 证据如实记录当前观察到的 Stage 5 packet hash，没有修改 Stage 或 Version taskbook。
  - risk: evidence_is_not_authority
    note: 本报告只是本地证据，不创建 ReviewDecision、GateEvent 或 accepted 状态。
```
