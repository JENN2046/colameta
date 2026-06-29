# 证据报告中文 companion：Stage 3 / v3.3 Taskbook Import Preview V1

```yaml id="stage-03-v3-3-evidence-zh-cn-summary"
chinese_companion:
  companion_id: stage_03_v3_3_taskbook_import_preview_evidence_zh_cn
  source_report: docs/taskbooks/versions/stage-03/evidence/VERSION_STAGE_03_V3_3_TASKBOOK_IMPORT_PREVIEW_REPORT.md
  source_sha256: b6b3c999155f89b301ed42a4b8f7f65a7d6d8aa8f4159f89f551c200355c4285
  language: zh-CN
  authority_status: non_authoritative_reading_companion
  review_acceptance: false
  delivery_state_accepted: false
```

这份文件是 v3.3 英文证据报告的中文阅读 companion。它不是新的权威副本，不产生外部任务书采用、计划修改、allowed_files 扩展、执行授权、审查接受、GateEvent 或 delivery state accepted。

v3.3 的目标是实现 `Taskbook Import Preview V1`，中文是“任务书导入预览 V1”。它接收 v3.2 的校验结果，把外部任务书 claim 变成只读预览，让 Commander 和 reviewer 能看清：这份外部任务书想影响什么、候选文件范围是什么、候选验证命令是什么、还需要哪些 Commander 决策。

最关键的边界：预览只是“给你看”，不是“已经采用”，也不是“允许执行”。

---

## 1. 本轮实现摘要

```yaml id="stage-03-v3-3-implementation-summary-zh-cn"
implementation_summary:
  source_version_taskbook: docs/taskbooks/versions/stage-03/VERSION_STAGE_03_V3_3_TASKBOOK_IMPORT_PREVIEW_V1.md
  source_version_taskbook_sha256: 8443c5ac8b9927a308da382bd2fd3e39992636b27f059539f0de46f802c78768
  implementation_authorization_head: 2bf635704cb311120368865ac8a0a994d91d4124
  master_taskbook_sha256: 1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34
  stage_03_taskbook_sha256: c5402734ef6990687a6a03ec6b17769f598ff0319b350b6a2371144985ece7ff
  v3_2_validator_helper_sha256: 42e9bc43b2942cba72e3ee802b80be80fa284975250253a18fc2a68cda4dc44f
  v3_2_validator_evidence_sha256: 75d1bdfdecd8c621275111aa96a1fb2218b4550909e0edba254d64ca2bac4420
  taskbook_import_preview_helper_sha256: 5717d7da4cfc0143484c6bfbb8ce66a712a05e880af0cee6726d296375aecca7
  taskbook_import_preview_tests_sha256: 6b22a81443d46810ba4df41b38269e9754bf25cb1e27a52023bd36dabaa09c55
```

本轮新增 4 个允许范围内的文件：

```yaml id="stage-03-v3-3-files-changed-zh-cn"
files_changed:
  created:
    - runner/taskbook_import_preview.py
    - tests/test_taskbook_import_preview.py
    - docs/taskbooks/versions/stage-03/evidence/VERSION_STAGE_03_V3_3_TASKBOOK_IMPORT_PREVIEW_REPORT.md
    - docs/taskbooks/versions/stage-03/evidence/zh-CN/VERSION_STAGE_03_V3_3_TASKBOOK_IMPORT_PREVIEW_REPORT.zh-CN.md
  modified: []
  forbidden_files_touched: []
```

本轮没有修改 Master、中文 Master companion、Stage Taskbook、Version Taskbook、freeze packet、`.colameta/plan.json`、executor state、route state 或服务运行时。

---

## 2. Preview Contract 中文解释

`preview` 在这里的意思是“导入预览”：把通过 v3.2 校验的外部任务书 claim 展示成一个候选影响清单。

它必须输出：

```yaml id="stage-03-v3-3-preview-contract-zh-cn"
preview_contract_summary:
  helper: runner.taskbook_import_preview.render_taskbook_import_preview
  accepted_input:
    - v3_2_validator_result
  preview_statuses:
    - preview_ready
    - preview_blocked_invalid_validator_result
    - preview_blocked_authority_confusion
    - preview_blocked_missing_required_claim
  required_output_fields:
    - preview_id
    - preview_status
    - source_claim_ref
    - validator_result_ref
    - recognized_claims_summary
    - rejected_claims_summary
    - proposed_version_candidate_identity
    - proposed_scope_summary
    - proposed_allowed_files_candidate_delta
    - proposed_forbidden_files_summary
    - proposed_acceptance_commands_summary
    - proposed_manual_acceptance_summary
    - required_commander_decisions
    - blockers
    - authority_boundary
```

中文解释：

```yaml id="stage-03-v3-3-field-meaning-zh-cn"
field_meaning:
  preview_id: 本次预览的本地标识。
  preview_status: 预览状态。
  source_claim_ref: 外部 claim 来源摘要。
  validator_result_ref: v3.2 校验结果摘要。
  recognized_claims_summary: 已识别声明摘要。
  rejected_claims_summary: 被拒声明摘要。
  proposed_version_candidate_identity: 候选 Version 身份预览，不是 mapping。
  proposed_scope_summary: 候选范围摘要。
  proposed_allowed_files_candidate_delta: 候选 allowed_files 变化，不是授权变化。
  proposed_forbidden_files_summary: 候选 forbidden_files 摘要。
  proposed_acceptance_commands_summary: 候选验证命令摘要，不是命令执行授权。
  proposed_manual_acceptance_summary: 候选人工确认摘要，不是状态接受。
  required_commander_decisions: 继续之前需要 Commander 再决定的事项。
  blockers: 阻塞原因。
  authority_boundary: 权限边界。
```

---

## 3. 有效预览示例

```yaml id="stage-03-v3-3-valid-preview-zh-cn"
valid_preview_example:
  preview_status: preview_ready
  blockers: []
  proposed_version_candidate_identity:
    candidate_only: true
    authorized_for_mapping: false
    identity_status: candidate_identity_preview_only_not_mapped
  proposed_allowed_files_candidate_delta:
    candidate_only: true
    authorized_delta: false
  proposed_acceptance_commands_summary:
    candidate_only: true
    authorized_to_run: false
  proposed_manual_acceptance_summary:
    candidate_only: true
    manual_acceptance_is_delivery_state_accepted: false
  required_commander_decisions:
    - decide_whether_to_consider_mapping
    - hash_specific_adoption_decision
    - execution_authorization
```

中文解释：就算 preview_ready，也只是“预览准备好了”。后面仍需要 Commander 决定是否进入 mapping、是否有 hash-specific adoption 决策、是否有执行授权。

---

## 4. 无效校验结果示例

```yaml id="stage-03-v3-3-invalid-validator-result-zh-cn"
invalid_validator_result_example:
  preview_status: preview_blocked_invalid_validator_result
  blocker_code: validator_result_not_passed
  authorized_delta: false
  adoption_authorized: false
  delivery_state_accepted: false
```

中文解释：如果 v3.2 validator 没有通过，v3.3 不会继续装作可以预览；它会把 preview 阻塞住。

---

## 5. 权限边界

```yaml id="stage-03-v3-3-authority-boundary-zh-cn"
authority_boundary_check:
  preview_result_is_authority: false
  preview_authorizes_adoption: false
  preview_mutates_plan: false
  preview_expands_allowed_files: false
  preview_authorizes_executor_dispatch: false
  preview_writes_delivery_state: false
  creates_review_decision: false
  emits_gate_event: false
  adoption_authorized: false
  plan_mutation_authorized: false
  allowed_files_expansion_authorized: false
  executor_dispatch_authorized: false
  delivery_state_accepted: false
```

中文大白话：preview 只能把候选影响摊开给你看，不能替你点同意，不能替你改计划，不能替你开执行。

---

## 6. Candidate Delta 标记检查

```yaml id="stage-03-v3-3-candidate-delta-labeling-zh-cn"
candidate_delta_labeling_check:
  proposed_version_candidate_identity:
    candidate_only: true
    authorized_for_mapping: false
  proposed_scope_summary:
    candidate_only: true
  proposed_allowed_files_candidate_delta:
    candidate_only: true
    authorized_delta: false
  proposed_forbidden_files_summary:
    candidate_only: true
  proposed_acceptance_commands_summary:
    candidate_only: true
    authorized_to_run: false
  proposed_manual_acceptance_summary:
    candidate_only: true
    manual_acceptance_is_delivery_state_accepted: false
```

这里每个 `proposed_*` 都要明确是候选，不是授权。尤其是 `proposed_allowed_files_candidate_delta`，它只是说明外部任务书“想让 allowed_files 怎么变”，不是 ColaMeta 已经允许它变。

---

## 7. 已运行验证

```text id="stage-03-v3-3-validation-zh-cn"
git status -sb
  result: PASS
  observed_after_v3_2_commit_before_reports:
    ## main...origin/main [ahead 59]
    ?? runner/taskbook_import_preview.py
    ?? tests/test_taskbook_import_preview.py

git rev-parse HEAD
  result: PASS
  observed: 2bf635704cb311120368865ac8a0a994d91d4124

git rev-list --count origin/main..HEAD
  result: PASS
  observed: 59

sha256sum PROJECT_MASTER_TASKBOOK.md docs/taskbooks/stages/STAGE_03_EXTERNAL_TASKBOOK_IMPORT.md docs/taskbooks/versions/stage-03/VERSION_STAGE_03_V3_3_TASKBOOK_IMPORT_PREVIEW_V1.md runner/external_taskbook_validator.py runner/taskbook_import_preview.py tests/test_taskbook_import_preview.py docs/taskbooks/versions/stage-03/evidence/VERSION_STAGE_03_V3_2_EXTERNAL_TASKBOOK_VALIDATOR_REPORT.md
  result: PASS

.venv/bin/python -m compileall runner/taskbook_import_preview.py
  result: PASS

.venv/bin/python -m unittest tests.test_taskbook_import_preview
  result: PASS
  observed: Ran 11 tests ... OK

git diff --check
  result: PASS

read-only preview smoke
  result: PASS
  observed:
    preview_status: preview_ready
    blockers: []
    candidate_only: true
    authorized_delta: false
    adoption_authorized: false
    delivery_state_accepted: false
```

---

## 8. 没有运行或没有授权的动作

```yaml id="stage-03-v3-3-not-authorized-zh-cn"
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
  - review_decision_creation
  - gate_event_emission
  - delivery_state_transition
  - acceptance_command_execution
  - modifying_/home/jenn/tools/colameta
```

---

## 9. 已知缺口和剩余风险

```yaml id="stage-03-v3-3-known-gaps-zh-cn"
known_gaps:
  - preview 消费结构化 validator result，不解析任意外部 Markdown taskbook。
  - preview 不把外部 taskbook 映射成 Version candidate；v3.4 负责 mapping。
  - preview 不采用外部 taskbook、不改 plan、不扩 allowed_files。
  - 本轮只运行了 v3.3 focused unittest module。
remaining_risks:
  - v3.4 必须继续区分 preview 和 Version candidate mapping。
  - v3.5 必须保持 adoption preview，除非有单独 hard gate，否则不得实际采用。
  - 后续 UI 或报告层不能把 candidate delta 折叠成 authorized delta。
```

结论：v3.3 已经把外部任务书导入前的只读预览层立起来了。它把“外部任务书想要什么”讲清楚，但不替 Commander 做任何采用、执行或状态推进决定。
