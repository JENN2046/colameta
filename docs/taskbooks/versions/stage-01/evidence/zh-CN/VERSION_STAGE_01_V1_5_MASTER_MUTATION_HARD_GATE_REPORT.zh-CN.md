# Stage 1 / v1.5 主任务书变更硬门 V1 证据报告中文 Companion

```yaml id="stage-01-v1-5-evidence-zh-cn-summary"
chinese_companion:
  source_document: docs/taskbooks/versions/stage-01/evidence/VERSION_STAGE_01_V1_5_MASTER_MUTATION_HARD_GATE_REPORT.md
  source_sha256: a8d134f8d75a63d7276cc0654b406611f51607d9ece3b5f887768b02528a43c0
  translation_status: companion_draft
  authority_status: evidence_reference_only
```

这份中文 companion 对应英文证据报告。它解释 Stage 1 / v1.5
`Master Mutation Hard Gate V1`，中文叫“主任务书变更硬门 V1”。它不授权 commit、
push、executor run、route transition、canonical receipt generation、review
acceptance 或 delivery state accepted。

---

## 1. 这次做了什么

这次实现的是 Master mutation hard gate，也就是“主任务书变更硬门”。

中文大白话：普通 Version 任务、executor、review packet、runtime 状态，都不能偷偷改
`PROJECT_MASTER_TASKBOOK.md` 或它的中文 companion。如果候选变更只是读取 Master、
计算 hash、检查状态，那可以作为证据通过；如果候选变更要修改 Master，就必须被挡住，
除非未来另有 Commander 通过精确 hash 和精确范围开一扇单独的 hard gate。

它明确不做：

- 不修改 `PROJECT_MASTER_TASKBOOK.md`；
- 不修改 `PROJECT_MASTER_TASKBOOK.zh-CN.md`；
- 不修改 `.colameta/taskbooks/master_taskbook_registry.json`；
- 不修改 reader、validator、hash binding；
- 不生成 Commander hard-gate token；
- 不生成 canonical receipt；
- 不最终化 canonical payload hash；
- 不创建 ReviewDecision；
- 不创建 GateEvent；
- 不写 delivery_state；
- 不声称 accepted。

`Hard Gate` = 硬门。中文意思是：这里不是普通提醒，而是默认阻断；要越过必须有更高层的明确授权。

`Master Mutation` = 主任务书变更。中文意思是：对 Master Taskbook 治理内容做写入、修改、删除、重命名、替换等动作。

`Evidence Only` = 仅作为证据。中文意思是：helper 的结果只能给 reviewer 或后续流程参考，不能自己宣布交付已接受。

---

## 2. 命令执行结果

关键验证结果：

```text
git status -sb
  结果：通过
  观察值：
    main 相对 origin/main 本地 ahead 52
    当前新增英文 evidence report
    当前新增中文 companion
    当前新增 runner/master_taskbook_mutation_gate.py
    当前新增 tests/test_master_taskbook_mutation_gate.py

git rev-parse HEAD
  结果：通过
  观察值：779f8dd9538036ea1ec4ecbb0fa1b8c57d8f0fd1

sha256sum PROJECT_MASTER_TASKBOOK.md
  结果：通过
  观察值：1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34

sha256sum .colameta/taskbooks/master_taskbook_registry.json
  结果：通过
  观察值：86baca398528b1cc5c635101e6fe25f0bf0e65d9363b5d5e1680e7c7bb753a3c

sha256sum runner/master_taskbook_reader.py
  结果：通过
  观察值：ad234e8f3ce7763d24048775f1f77dcd2828e5cc5922c6da5e19ea2a657e5382

sha256sum runner/master_taskbook_validator.py
  结果：通过
  观察值：b25206dfb143fe6fb24df5ae25bbcf0930fb20dfcea97e24b77290946a1a6b97

sha256sum runner/master_taskbook_hash_binding.py
  结果：通过
  观察值：36db40871105ffb4d41ad2778a44d14ea29ee1c37497a25a142d0db7ec42629d

sha256sum docs/taskbooks/versions/stage-01/VERSION_STAGE_01_V1_5_MASTER_MUTATION_HARD_GATE_V1.md
  结果：通过
  观察值：60732a6bef0d6add2382da353ad715ce88a35c0dbef33d451c1b1d128e12ed81

sha256sum runner/master_taskbook_mutation_gate.py
  结果：通过
  观察值：ac4c817559d14dc5b5d222e4a8c4323100e7ffe722654e8b8daf9527f6c2e294

sha256sum tests/test_master_taskbook_mutation_gate.py
  结果：通过
  观察值：53101b6229d8e8208262df47e841876a47fedd5791a4a411e80c3d1fa35b3d1e

.venv/bin/python -m compileall runner/master_taskbook_mutation_gate.py
  结果：通过

.venv/bin/python -m unittest tests.test_master_taskbook_mutation_gate
  结果：通过，12 个测试 OK

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
  - registry_mutation
  - reader_mutation
  - validator_mutation
  - hash_binding_mutation
  - master_taskbook_mutation
  - commander_hard_gate_token_generation
  - canonical_receipt_generation
  - canonical_payload_hash_finalization
  - review_acceptance
  - delivery_state_transition
```

中文解释：这次只做 v1.5 本地实现和 focused test。完整测试套件没有跑，因为这次授权是窄授权。

---

## 4. 改了哪些文件

创建了这些文件：

```yaml
files_changed:
  created:
    - runner/master_taskbook_mutation_gate.py
    - tests/test_master_taskbook_mutation_gate.py
    - docs/taskbooks/versions/stage-01/evidence/VERSION_STAGE_01_V1_5_MASTER_MUTATION_HARD_GATE_REPORT.md
    - docs/taskbooks/versions/stage-01/evidence/zh-CN/VERSION_STAGE_01_V1_5_MASTER_MUTATION_HARD_GATE_REPORT.zh-CN.md
  modified: []
  forbidden_files_touched: []
```

`PROJECT_MASTER_TASKBOOK.md`、`PROJECT_MASTER_TASKBOOK.zh-CN.md`、registry、
reader、validator 和 hash binding 都保持只读。

---

## 5. Mutation Gate Contract Summary = 变更门禁合约摘要

英文报告里的核心结论是：

```yaml
mutation_gate_contract_summary:
  helper: runner/master_taskbook_mutation_gate.py
  input_contract:
    - candidate_changes
    - commander_authorization_or_none
    - protected_paths
    - observed_git_head
    - source_version_taskbook_ref
  protected_paths:
    - PROJECT_MASTER_TASKBOOK.md
    - PROJECT_MASTER_TASKBOOK.zh-CN.md
    - FREEZE_CANDIDATE_REVIEW_PACKET.md
    - FREEZE_CANDIDATE_REVIEW_PACKET.zh-CN.md
  mutation_attempt_classes:
    - no_master_mutation
    - read_only_master_access
    - unauthorized_master_mutation_attempt
    - commander_authorized_master_mutation_candidate
    - unknown_master_mutation_risk
  gate_result_values:
    - allow_read_only
    - block_unauthorized_mutation
    - require_commander_hard_gate
    - known_unknown
  missing_or_ambiguous_change_evidence_fails_closed: true
  unauthorized_master_mutation_fails_closed: true
  commander_authorization_token_echo: redacted_not_returned
  source_version_taskbook_ref_filtering: allowlisted_string_fields_only
  mutation_gate_result_is_authority: false
  creates_review_decision: false
  emits_gate_event: false
  writes_delivery_state: false
```

中文解释：这个 helper 的职责是看候选变更有没有碰受保护的 Master 路径。它只输出门禁证据，
不能把任何东西变成 accepted。

---

## 6. Protected Path Check = 受保护路径检查

默认受保护路径：

```yaml
protected_paths:
  - PROJECT_MASTER_TASKBOOK.md
  - PROJECT_MASTER_TASKBOOK.zh-CN.md
  - FREEZE_CANDIDATE_REVIEW_PACKET.md
  - FREEZE_CANDIDATE_REVIEW_PACKET.zh-CN.md
```

路径归一化规则：

- 去掉 `/home/jenn/src/colameta-dev/` 这个项目根路径前缀；
- 去掉开头的 `./`；
- 把 Windows 风格反斜杠转成普通斜杠；
- 折叠 `..` 路径段，比如 `docs/../PROJECT_MASTER_TASKBOOK.md` 会变成 `PROJECT_MASTER_TASKBOOK.md`；
- 因此绝对路径 `/home/jenn/src/colameta-dev/PROJECT_MASTER_TASKBOOK.md` 会被识别成受保护路径。

`Protected Path` = 受保护路径。中文意思是：这些文件不是普通实现文件，普通任务不能静默修改。

---

## 7. Mutation Attempt Classification = 变更尝试分类

```yaml
mutation_attempt_classification:
  no_master_mutation:
    中文: 没有碰 Master 受保护路径
    gate_result: allow_read_only
    fail_closed_result: pass
  read_only_master_access:
    中文: 只是读取、检查、计算 hash
    gate_result: allow_read_only
    fail_closed_result: pass
  unauthorized_master_mutation_attempt:
    中文: 未授权修改 Master
    gate_result: block_unauthorized_mutation
    fail_closed_result: fail_closed
  commander_authorized_master_mutation_candidate:
    中文: 输入里带有 Commander hard-gate 授权证据，但 helper 仍不自己执行或批准变更
    gate_result: require_commander_hard_gate
    fail_closed_result: fail_closed
  unknown_master_mutation_risk:
    中文: 证据不足，无法判断是否会改 Master
    gate_result: known_unknown
    fail_closed_result: fail_closed
```

`Fail Closed` = 失败时关闭。中文意思是：只要证据不清楚，就按不通过处理，而不是默认放行。

---

## 8. Commander Hard Gate Requirement Check = 指挥官硬门要求检查

helper 可以读取未来传进来的 Commander 授权证据字段：

```yaml
commander_authorization_input_fields:
  - authorization_status
  - authorization_token
  - authorization_scope_hash
  - authorized_paths
  - authorized_actions
```

但是这次 v1.5 helper 不生成 token，也不回显 token 本体，更不把 token 当成交付接受。
即使输入里带有匹配的 Commander hard-gate 授权，它也只是把候选变更分类为
`commander_authorized_master_mutation_candidate`，并返回
`require_commander_hard_gate`。

中文大白话：它能认出“这看起来像已经走到 Commander 硬门门口了”，但它不能自己开门。

---

## 9. Gate Result = 门禁结果

当前 repo smoke case 是：

```yaml
current_repo_smoke_gate_result:
  candidate_changes:
    - protected_path: PROJECT_MASTER_TASKBOOK.md
      attempted_action: sha256sum
      detected_from: current_repo_smoke
    - protected_path: runner/master_taskbook_mutation_gate.py
      attempted_action: create
      detected_from: current_repo_smoke
  result:
    mutation_attempt_class: read_only_master_access
    gate_result: allow_read_only
    fail_closed_result: pass
  observed_git_head: 779f8dd9538036ea1ec4ecbb0fa1b8c57d8f0fd1
```

中文解释：这次实际只读了 Master hash，并创建了授权范围内的 v1.5 helper，所以当前 smoke case
通过。它没有修改 Master。

---

## 10. Blocked Attempt Or None = 阻断尝试记录

如果看到未授权 Master 修改，helper 会给出阻断记录：

```yaml
blocked_attempt_or_none:
  unauthorized_master_mutation_attempt:
    example:
      protected_path: PROJECT_MASTER_TASKBOOK.md
      attempted_action: modify
      detected_from: git_diff_name_status
    gate_result: block_unauthorized_mutation
  current_repo_smoke:
    blocked_attempt_or_none: null
```

中文解释：真正有问题时，它会明确告诉你“哪个受保护文件、什么动作、从哪里检测到”。当前这次没有阻断项。

---

## 11. Validation Results = 验证结果

```yaml
validation_results:
  focused_compile:
    command: .venv/bin/python -m compileall runner/master_taskbook_mutation_gate.py
    status: PASS
  focused_tests:
    command: .venv/bin/python -m unittest tests.test_master_taskbook_mutation_gate
    status: PASS
    tests: 12
  report_validation:
    command: git diff --check
    status: PASS
```

---

## 12. Not Validated = 没有验证的部分

```yaml
not_validated:
  - live_remote_status_not_validated: true
  - no_fetch_pull_or_remote_probe_was_authorized_or_run
  - no_executor_run_was_authorized_or_run
  - no_service_restart_was_authorized_or_run
  - no_canonical_receipt_generation_was_authorized_or_run
```

中文解释：没有 fetch/pull，所以不能证明远端这一刻没变化；没有 executor run，也没有服务重启。

---

## 13. Remaining Risks = 剩余风险

```yaml
remaining_risks:
  - future_real_master_mutation_flow_still_requires_separate_commander_hard_gate
  - future_integration_must_define_how_candidate_changes_are_collected
  - remote_state_may_have_changed_because_fetch_pull_was_not_authorized
```

中文解释：v1.5 已经把“Master 不能被普通任务偷偷改”这个最小门禁立住了。但未来真的要修改
Master 时，还要单独设计并授权 Commander hard gate 的实际流程。
