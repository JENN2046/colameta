# Version 中文任务书：Stage 2 / v2.4 阶段任务书状态门就绪契约 V1

```yaml id="version-stage-02-v2-4-zh-cn-summary"
chinese_companion:
  source_document: docs/taskbooks/versions/stage-02/VERSION_STAGE_02_V2_4_STAGE_TASKBOOK_GATE_READINESS_CONTRACT_V1.md
  source_sha256: b014845d275d4e240ace857561923e48314d176750949b7ed556ca5a9e876578
  translation_status: companion_draft
  authority_status: planning_reference_only
version_execution_taskbook:
  version_id: stage_02_v2_4_stage_taskbook_gate_readiness_contract_v1
  version: v2.4
  chinese_name: 阶段任务书状态门就绪契约 V1
  status: discussion_draft
  execution_authorization_status: not_authorized
```

## 1. 这份任务书是什么

这是 Stage 2 的第四份 Version 任务书草稿，也是 Stage 2 Version set 的收束版本。

`Stage Taskbook Gate-Readiness Contract V1` = 阶段任务书状态门就绪契约 V1。

中文意思是：定义一个 Stage Taskbook 到什么程度才可以被后续 Version 当作
`stage_taskbook_ref` 引用。

它现在不是执行授权，不授权实现，不授权 executor，不授权 commit，不授权 push，
不授权 fetch/pull，也不授权 review acceptance、Delivery State Gate transition 或
accepted delivery state。

## 2. 父级绑定

这份 Version 绑定到：

- Master Taskbook：`PROJECT_MASTER_TASKBOOK.md`
  - hash：`1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34`
- Stage 2 Taskbook：`docs/taskbooks/stages/STAGE_02_STAGE_TASKBOOK_MANAGEMENT.md`
  - hash：`b0e1a55121503df4116d9c49031eb07729858c483cc73e6c97730eca0a067876`
- previous version v2.3：
  - hash：`0699376b9162c0e4ef276996482820c26327e60f5d8371a7193860dbfce6594e`
- Stage 1 Version set confirmation：
  - hash：`c4ef865c84ab634a7b3626cdc6924a4e51420a1d6d94bb274aeb9f13d354fce5`

中文解释：v2.4 要消费 v2.1-v2.3 的结果，不能把 gate-ready 说成 accepted。

## 3. 目标

本版本要定义最小 gate-readiness contract：

- schema validation passed；
- registry record exists；
- exact Master binding passed；
- minimum evidence package present；
- non-goals explicit；
- authority boundary explicit；
- result distinct from accepted delivery state。

`gate_ready` = 状态门就绪。中文意思是：资料够完整，可以被后续 Version 引用或拿去
审查；它不是 accepted，也不是执行授权。

## 4. 不做什么

v2.4 不做：

- review acceptance；
- Delivery State Gate transition；
- executor dispatch；
- workflow automation；
- automatic Stage generation；
- accepted delivery state。

## 5. 候选写入范围

未来如果 Commander 单独授权执行，本版本候选写入范围最多包括：

- `runner/stage_taskbook_gate_readiness.py`
- `tests/test_stage_taskbook_gate_readiness.py`
- `docs/taskbooks/versions/stage-02/evidence/VERSION_STAGE_02_V2_4_STAGE_TASKBOOK_GATE_READINESS_REPORT.md`
- `docs/taskbooks/versions/stage-02/evidence/zh-CN/VERSION_STAGE_02_V2_4_STAGE_TASKBOOK_GATE_READINESS_REPORT.zh-CN.md`

这些现在只是候选路径，不是当前授权。

## 6. 状态门就绪最小合约

Gate-readiness 至少需要这些输入：

- `stage_taskbook_ref`；
- `stage_taskbook_raw_snapshot_sha256`；
- `validator_result`；
- `registry_record_ref`；
- `master_binding_result`；
- `minimum_evidence_package`；
- `non_goals_summary`。

允许的 readiness result 只有：

- `gate_ready`；
- `not_gate_ready`；
- `blocked_needs_review`。

禁止的结果声明包括：

- `accepted_delivery_state`；
- `execution_authorized`；
- `executor_dispatch_authorized`；
- `route_transition_authorized`；
- `registry_mutation_authorized`。

## 7. stage_taskbook_ref 消费规则

后续 Version 只有在这些条件满足时，才能引用一个 `stage_taskbook_ref`：

- readiness result 是 `gate_ready`；
- Stage Taskbook hash 与 registry 匹配；
- Master ref 与 binding result 匹配；
- evidence package 存在，或 known_unknown 已记录；
- authority boundary 明确。

后续 Version 必须拒绝：

- unregistered `stage_taskbook_ref`；
- validator result failed 或 missing；
- Master binding failed 或 missing；
- evidence package missing 且没有 known_unknown；
- readiness result 声称 accepted 或 execution authority。

## 8. 人工验收条件

审查者可以接受 v2.4 的条件包括：

- gate-readiness 要求 validator_result pass；
- gate-readiness 要求 registry record；
- gate-readiness 要求精确 Master binding pass；
- 后续 Version 必须拒绝 unregistered 或 unvalidated `stage_taskbook_ref`；
- `gate_ready` 明确不是 accepted delivery state；
- 证据报告区分 `commands_run` 和 `commands_not_run`。

不能接受的情况包括：

- `gate_ready` 授权 execution；
- `gate_ready` 映射到 accepted delivery state；
- unregistered `stage_taskbook_ref` 可以被消费；
- failed validator_result 仍然可以 gate_ready。

## 9. Stage 2 收束就绪

v2.1 到 v2.4 草稿齐全后，Stage 2 具备做包级审查的基础：

- v2.1：schema + validator；
- v2.2：registry；
- v2.3：Stage-to-Master binding；
- v2.4：gate-readiness contract。

这些仍然只是 Version Taskbook 草稿，不授权实现、commit、push、executor、route 或
delivery state accepted。
