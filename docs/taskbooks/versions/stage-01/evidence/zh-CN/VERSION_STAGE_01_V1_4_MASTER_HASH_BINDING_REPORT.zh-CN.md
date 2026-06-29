# Stage 1 / v1.4 主任务书哈希绑定 V1 证据报告中文 Companion

```yaml id="stage-01-v1-4-evidence-zh-cn-summary"
chinese_companion:
  source_document: docs/taskbooks/versions/stage-01/evidence/VERSION_STAGE_01_V1_4_MASTER_HASH_BINDING_REPORT.md
  source_sha256: ff9f35315970b68b949b9ebf78b4df1e4b1551a03f89958d533ace46fb34bd3b
  translation_status: companion_draft
  authority_status: evidence_reference_only
```

这份中文 companion 对应英文证据报告。它解释 Stage 1 / v1.4
`Master Hash Binding V1`，中文叫“主任务书哈希绑定 V1”。它不授权 commit、push、
executor run、route transition、canonical receipt generation、review acceptance
或 delivery state accepted。

---

## 1. 这次做了什么

这次实现的是 hash binding，也就是“哈希绑定”。

中文大白话：v1.1 registry 里有一份 Master hash；v1.2 reader 实际读到一份
Master hash；v1.3 validator 使用 reader result 时也看到一份 Master hash。v1.4
把这三份 hash 放在一起核对，看它们是不是指向同一份 `PROJECT_MASTER_TASKBOOK.md`
原始快照。

它明确不做：

- 不修改 `PROJECT_MASTER_TASKBOOK.md`；
- 不修改 `PROJECT_MASTER_TASKBOOK.zh-CN.md`；
- 不修改 `.colameta/taskbooks/master_taskbook_registry.json`；
- 不修改 reader output；
- 不修改 validator output；
- 不生成 canonical receipt；
- 不最终化 canonical payload hash；
- 不创建 ReviewDecision；
- 不创建 GateEvent；
- 不写 delivery_state；
- 不声称 accepted。

`Hash Binding` = 哈希绑定。中文意思是：多个来源都说自己指向同一份内容，就用 hash
核对它们到底是不是同一份。

`canonical receipt` = 规范收据。中文意思是：按规范字段抽取、排序、序列化以后生成
的正式 hash 收据。v1.4 不做这个。

---

## 2. 命令执行结果

关键验证结果：

```text
git status -sb
  结果：通过
  观察值：
    main 相对 origin/main 本地 ahead 51
    当前新增英文 evidence report
    当前新增中文 companion
    当前新增 runner/master_taskbook_hash_binding.py
    当前新增 tests/test_master_taskbook_hash_binding.py

git rev-parse HEAD
  结果：通过
  观察值：df2d42f3110d2d5c77e3d8b16c878920ee6c8dac

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

.venv/bin/python -m compileall runner/master_taskbook_hash_binding.py
  结果：通过

.venv/bin/python -m unittest tests.test_master_taskbook_hash_binding
  结果：通过，8 个测试 OK

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
  - registry_creation_or_repair
  - reader_mutation
  - validator_mutation
  - master_taskbook_mutation
  - canonical_receipt_generation
  - canonical_payload_hash_finalization
  - review_acceptance
  - delivery_state_transition
```

中文解释：这次只做 v1.4 本地实现和 focused test。完整测试套件没有跑，因为这次授权是窄授权。

---

## 4. 改了哪些文件

创建了这些文件：

```yaml
files_changed:
  created:
    - runner/master_taskbook_hash_binding.py
    - tests/test_master_taskbook_hash_binding.py
    - docs/taskbooks/versions/stage-01/evidence/VERSION_STAGE_01_V1_4_MASTER_HASH_BINDING_REPORT.md
    - docs/taskbooks/versions/stage-01/evidence/zh-CN/VERSION_STAGE_01_V1_4_MASTER_HASH_BINDING_REPORT.zh-CN.md
  modified: []
  forbidden_files_touched: []
```

`PROJECT_MASTER_TASKBOOK.md`、`PROJECT_MASTER_TASKBOOK.zh-CN.md`、registry、
reader 和 validator 都保持只读。

---

## 5. Hash Binding Contract Summary = 哈希绑定合约摘要

英文报告里的核心结论是：

```yaml
hash_binding_contract_summary:
  helper: runner/master_taskbook_hash_binding.py
  input_contract:
    - registry_master_raw_snapshot_sha256
    - reader_raw_content_sha256
    - validator_input_raw_content_sha256
  binding_mode: input_hash_comparison_only
  result_values:
    - match
    - mismatch
    - missing_input
    - known_unknown
  mismatch_fails_closed: true
  missing_input_fails_closed: true
  canonical_receipt_generation: deferred_not_generated
  canonical_payload_hash_finalization: deferred_not_finalized
  binding_result_is_authority: false
  creates_review_decision: false
  emits_gate_event: false
  writes_delivery_state: false
```

中文解释：这个 helper 只比较 hash。它的结果是证据，不是权威；它不会把任务变成 accepted。

---

## 6. Hash Inputs = 哈希输入

当前三边输入都是同一个 Master raw snapshot hash：

```yaml
hash_inputs:
  registry_master_raw_snapshot_sha256:
    source: .colameta/taskbooks/master_taskbook_registry.json
    value: 1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34
  reader_raw_content_sha256:
    source: runner.master_taskbook_reader.read_master_taskbook result
    value: 1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34
  validator_input_raw_content_sha256:
    source: runner.master_taskbook_validator.validate_master_taskbook_required_fields result reader_result_input.raw_content_sha256
    value: 1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34
```

---

## 7. Hash Binding Result = 哈希绑定结果

```yaml
hash_binding_result:
  result: match
  fail_closed_result: pass
  missing_inputs: []
  known_unknown_inputs: []
  failure_reason_or_none: null
  observed_git_head: df2d42f3110d2d5c77e3d8b16c878920ee6c8dac
  canonical_receipt_generation: deferred_not_generated
  canonical_payload_hash_finalization: deferred_not_finalized
  binding_result_is_authority: false
  forbidden_authority_claims_present: []
```

`match` = 匹配。中文意思是：registry、reader、validator 三边 hash 一致。

`mismatch` = 不匹配。中文意思是：至少有一边 hash 和其他边不一致，必须 fail closed。

`missing_input` = 缺输入。中文意思是：必要 hash 缺失或格式不对，必须 fail closed。

`known_unknown` = 已知未知。中文意思是：上游明确说自己不能可靠判断，不能假装通过。

---

## 8. Not Validated = 没有验证的事项

```yaml
not_validated:
  - live_remote_status_not_validated: true
  - no_fetch_pull_or_remote_probe_was_authorized_or_run
  - full_unittest_discovery_not_authorized_for_this_slice
  - canonical_payload_hash_finalization_not_performed
  - canonical_receipt_generation_not_performed
  - review_acceptance_not_performed
  - delivery_state_gate_transition_not_performed
```

中文解释：v1.4 只证明三边 raw hash 一致。它不是规范收据，不是审查决策，不是状态门事件。

---

## 9. Remaining Risks = 剩余风险

```yaml
remaining_risks:
  - Hash binding 只证明 registry、reader、validator 指向同一个 Master raw snapshot hash。
  - 本切片不最终化 canonical payload hash，也不生成 canonical receipt。
  - 后续 v1.5 可以消费 hash binding evidence，但 hash binding result 本身不是 Master mutation authority。
```

中文总结：v1.4 把“这些上游组件到底是不是锚在同一份 Master 内容”这件事做成了机器可检查结果。
但它仍然只是证据层，不是验收层，不是状态门，也不是规范收据。
