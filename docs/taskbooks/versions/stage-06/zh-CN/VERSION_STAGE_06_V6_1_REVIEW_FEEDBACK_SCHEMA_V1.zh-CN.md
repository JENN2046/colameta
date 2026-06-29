# Version 中文任务书：Stage 6 / v6.1 审查反馈模式 V1

```yaml id="version-stage-06-v6-1-zh-cn-summary"
chinese_companion:
  source_document: docs/taskbooks/versions/stage-06/VERSION_STAGE_06_V6_1_REVIEW_FEEDBACK_SCHEMA_V1.md
  source_sha256: 70ec9d9aa6e34299f3c3f0def67fdc0a8ec066cedbc934868dca98542b38ddf7
  translation_status: companion_draft
  authority_status: planning_reference_only
version_execution_taskbook:
  version_id: stage_06_v6_1_review_feedback_schema_v1
  version: v6.1
  chinese_name: 审查反馈模式 V1
  status: discussion_draft
  execution_authorization_status: not_authorized
```

## 1. 这份任务书是什么

`Review Feedback Schema V1` = 审查反馈模式 V1。

中文意思是：先定义 Reviewer 反馈必须携带哪些绑定、证据和判断字段，让反馈不能脱离
handoff package、执行报告和 workspace snapshot 漂进系统。

它现在不授权实现，不授权 executor，不授权 commit，不授权 push，不授权 plan mutation，
不授权 ReviewDecision creation，不授权 GateEvent emission，也不授权 delivery state
accepted。

## 2. 父级绑定

这份 Version 绑定到：

- Master Taskbook hash：`1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34`
- Stage 6 Taskbook hash：`c83c979d447a4ec645d380b6c1dc206730d12d5d644c08582b3cfd04f3e0009d`
- Stage 5 Version set confirmation hash：`ca23f567af50038469e3198b9a5600b1625e595c3381f20d262ab3aa81d61ea8`

中文解释：先规定“什么样的反馈算可接入”，再谈如何验证和分类。

## 3. 目标

v6.1 的目标是定义最小 `ReviewFeedback` schema，要求反馈绑定：

- Reviewer identity or source；
- Reviewer authority scope；
- Reviewer attestation；
- reviewer handoff package；
- Version Taskbook；
- execution report；
- workspace snapshot；
- Master hash；
- Stage hash；
- review decision value。

`ReviewFeedback` = 审查反馈。

中文意思是：Reviewer 给出的结构化反馈输入；它不是 ReviewDecision 的最终权威写入，
也不是 Delivery State Gate 事件。

## 4. 最小合约

`ReviewFeedback` 至少需要：

- `review_feedback_id`
- `review_feedback_schema_version`
- `reviewer_identity_or_source`
- `reviewer_authority_scope`
- `reviewer_attestation`
- `reviewer_handoff_package_ref`
- `version_taskbook_ref`
- `execution_report_ref`
- `workspace_snapshot_ref`
- `master_taskbook_hash`
- `stage_taskbook_hash`
- `review_decision_value`
- `pass_alias_policy_id_when_used`
- `charter_alignment`
- `task_completion`
- `scope_assessment`
- `reviewer_notes`
- `submitted_at`

原生允许的 review decision value 只有：

- `ACCEPT`
- `NEEDS_FIX`
- `PLAN_ADJUST`
- `ABORT`

`PASS` 只允许作为 legacy alias，并且必须有 policy ref。它只能映射到
`ReviewDecision.ACCEPT`，不能代表 delivery_state accepted。

## 5. 候选写入范围

未来如果 Commander 单独授权执行，本版本候选写入范围最多包括：

- `runner/review_feedback_schema.py`
- `tests/test_review_feedback_schema.py`
- `docs/taskbooks/versions/stage-06/evidence/VERSION_STAGE_06_V6_1_REVIEW_FEEDBACK_SCHEMA_REPORT.md`
- `docs/taskbooks/versions/stage-06/evidence/zh-CN/VERSION_STAGE_06_V6_1_REVIEW_FEEDBACK_SCHEMA_REPORT.zh-CN.md`

这些现在只是候选路径，不是当前授权。

## 6. 拒绝规则

v6.1 应拒绝这些情况：

- 缺少 reviewer handoff package ref；
- 缺少 version taskbook ref；
- 缺少 execution report ref；
- 缺少 workspace snapshot ref；
- 缺少 Master 或 Stage hash；
- review decision value unknown；
- 使用 PASS alias 但没有 policy ref；
- feedback 声明 delivery state transition；
- feedback 声明 plan mutation；
- feedback 声明 executor continuation。

## 7. 人工验收条件

审查者可以接受 v6.1 的条件包括：

- schema 要求所有反馈绑定 refs；
- schema 只允许 `ACCEPT / NEEDS_FIX / PLAN_ADJUST / ABORT`；
- PASS alias 没有 explicit policy ref 时禁用；
- schema 拒绝声称 plan、route、executor 或 state authority 的反馈。

不能接受的情况包括：

- feedback 可以无绑定 refs 被接受；
- PASS 可以表示 delivery_state accepted；
- schema 可以直接创建 ReviewDecision、GateEvent 或 route transition；
- 中文 companion 改弱 non-authority boundary。

## 8. 下一步交接

v6.1 通过后，才能交给 v6.2 定义 `Review Feedback Validator V1`。

中文意思是：v6.1 是“反馈输入的形状”，不是“收到反馈就自动往前走”。
