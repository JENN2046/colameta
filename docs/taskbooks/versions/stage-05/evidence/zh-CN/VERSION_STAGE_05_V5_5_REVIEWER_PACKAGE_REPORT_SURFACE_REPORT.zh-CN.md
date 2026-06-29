# 证据报告：Stage 5 / v5.5 审查包报告展示面 V1

```yaml id="companion-binding"
companion_binding:
  language: zh-CN
  companion_type: full_chinese_reading_companion
  authority_status: non_authoritative_companion
  source_report: docs/taskbooks/versions/stage-05/evidence/VERSION_STAGE_05_V5_5_REVIEWER_PACKAGE_REPORT_SURFACE_REPORT.md
  source_sha256: 87dd10d8219257a4bcbb644787e72893bf3ca09470633e89eb82fb883ec56635
```

## 范围

这份中文 companion 对应 Stage 5 / v5.5 `Reviewer Package Report Surface V1`
的本地证据报告。

`Reviewer Package Report Surface` = 审查包报告展示面。中文意思是：把审查材料整理成
Reviewer 能读、能判断、能选择的报告结构。它只是展示面，不是 Reviewer 的决定，
也不是状态门事件，更不是 accepted 交付状态。

## 报告章节清单

```yaml id="report-section-inventory"
report_section_inventory:
  required_sections:
    - package_identity
    - binding_summary
    - task_goal_summary
    - claim_summary
    - changed_files
    - validation_truth
    - scope_evidence
    - alignment_questions
    - drift_questions
    - known_risks
    - known_gaps
    - allowed_review_decisions
    - non_authority_notice
  example_surface_sections_observed: 13
  known_gaps_empty_allowed_when_section_present: true
```

中文解释：报告必须把“这是什么包、绑定到什么任务书、做了什么、改了哪些文件、验证
事实是什么、风险和空缺是什么、Reviewer 可以选哪些决策”都摆出来。`known_gaps`
可以为空，但这个章节本身必须出现，避免把“没有写”误看成“没有缺口”。

## 决策选项可见性检查

```yaml id="decision-option-visibility-check"
decision_option_visibility_check:
  allowed_review_decisions:
    - ACCEPT
    - NEEDS_FIX
    - PLAN_ADJUST
    - ABORT
  equality_rule: exact_list_required
  hidden_needs_fix_or_plan_adjust_result: failed_closed
  highlighted_accept_as_recommended_result: failed_closed
```

中文解释：四个审查选项必须平等显示。报告不能把 `ACCEPT` 做成推荐项，也不能隐藏
`NEEDS_FIX` 或 `PLAN_ADJUST`，否则就会变成诱导审查。

## 非权威声明检查

```yaml id="non-authority-notice-check"
non_authority_notice_check:
  required_notices:
    - report_surface_is_not_review_decision
    - report_surface_is_not_delivery_state_transition
    - report_surface_is_not_commander_authorization
    - report_surface_is_not_executor_authorization
  missing_notice_result: failed_closed
  forbidden_authority_claim_result: failed_closed
```

中文解释：报告展示面必须明说自己不是 `ReviewDecision`，不是 `GateEvent`，不是
Commander 授权，也不是 Executor 授权。少了这些声明就 fail closed。

## 验证事实展示检查

```yaml id="validation-truth-rendering-check"
validation_truth_rendering_check:
  validation_truth_section_required: true
  validation_pass_labelled_as_accepted: forbidden
  reviewer_decision_created: false
  gate_event_emitted: false
  delivery_state_accepted: false
```

中文解释：验证通过只能说明验证通过，不能写成“已接受”。本轮没有创建审查决策记录，
没有发出状态门事件，也没有把交付状态设置成 accepted。

## 风险与缺口展示检查

```yaml id="risk-and-gap-rendering-check"
risk_and_gap_rendering_check:
  known_risks_required: true
  known_gaps_section_required: true
  known_gaps_empty_allowed_when_explicitly_present: true
  no_risk_summary_when_risks_exist: forbidden_by_taskbook
```

中文解释：报告必须给 Reviewer 看到风险和缺口。即使当前没有具体缺口，也要明确出现
`known_gaps`，这样审查者不用猜“是没有缺口，还是没写”。

## 已运行命令

```text id="commands-run"
.venv/bin/python -m compileall runner/reviewer_package_report_surface.py
.venv/bin/python -m unittest tests.test_reviewer_package_report_surface
git diff --check
sha256sum docs/taskbooks/versions/stage-05/VERSION_STAGE_05_V5_5_REVIEWER_PACKAGE_REPORT_SURFACE_V1.md runner/reviewer_package_report_surface.py tests/test_reviewer_package_report_surface.py docs/taskbooks/versions/stage-05/evidence/VERSION_STAGE_05_V5_4_DRIFT_QUESTION_PACK_REPORT.md
.venv/bin/python -c "from runner.reviewer_package_report_surface import validate_reviewer_package_report_surface, example_report_surface; r=validate_reviewer_package_report_surface(example_report_surface()); print('report_surface_check_result:', r['report_surface_check_result']); print('sections:', len(r['section_inventory'])); print('reviewer_decision_created:', str(r['reviewer_decision_created']).lower()); print('delivery_state_accepted:', str(r['delivery_state_accepted']).lower())"
```

## 命令结果

```yaml id="command-results"
command_results:
  compileall: passed
  unittest:
    status: passed
    tests_run: 6
  git_diff_check: passed
  smoke:
    report_surface_check_result: reviewer_package_report_surface_check_passed
    sections: 13
    reviewer_decision_created: false
    delivery_state_accepted: false
```

## 未运行命令

```yaml id="commands-not-run"
commands_not_run:
  executor_run: not_authorized
  route_transition: not_authorized
  service_restart: not_authorized
  remote_write: not_authorized
  review_acceptance: not_authorized
  delivery_state_transition: not_authorized
```

## 剩余风险

```yaml id="remaining-risks"
remaining_risks:
  - risk: reviewer_report_surface_is_schema_level_only
    note: Stage 5 v5.5 只校验最低报告结构，不是最终 UI。
  - risk: downstream_feedback_intake_not_started
    note: Stage 6 仍需要定义反馈接收和决策请求边界。
  - risk: evidence_is_not_authority
    note: 本报告只是本地证据，不批准交付状态。
```
