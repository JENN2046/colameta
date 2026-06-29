# Version 中文任务书：Stage 5 / v5.1 审查者交接模式 V1

```yaml id="version-stage-05-v5-1-zh-cn-summary"
chinese_companion:
  source_document: docs/taskbooks/versions/stage-05/VERSION_STAGE_05_V5_1_REVIEWER_HANDOFF_SCHEMA_V1.md
  source_sha256: 7c1d5d95f02a1ff7b22712678d05e50a88fff00f5f43af0969d0292920d50e54
  translation_status: companion_draft
  authority_status: planning_reference_only
version_execution_taskbook:
  version_id: stage_05_v5_1_reviewer_handoff_schema_v1
  version: v5.1
  chinese_name: 审查者交接模式 V1
  status: discussion_draft
  execution_authorization_status: not_authorized
```

## 1. 这份任务书是什么

这是 Stage 5 的第一份 Version 任务书草稿。

`Reviewer Handoff Schema V1` = 审查者交接模式 V1。

中文意思是：先把交给 Reviewer 的 package 字段边界定义清楚，让后续 generator 只能
填充材料，不能偷偷替 Reviewer 下结论。

它现在不授权实现，不授权代码修改，不授权 executor，不授权 commit，不授权 push，
不授权 fetch/pull，不授权 review acceptance，不授权 Delivery State Gate transition，
也不授权 accepted delivery state。

## 2. 父级绑定

这份 Version 绑定到：

- Master Taskbook：`PROJECT_MASTER_TASKBOOK.md`
  - hash：`1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34`
- Stage 5 Taskbook：`docs/taskbooks/stages/STAGE_05_REVIEWER_HANDOFF_PACKAGE.md`
  - hash：`532d36ab5c99d37c1a88b094fbe9c37bdc342e17e572447468a0918afbdce43c`
- Stage 4 Version set confirmation：
  - hash：`b1da3ea7e105d48f5018c5be17bb59e0164779bfe06e8a36f8e7265b62031c6f`

中文解释：Stage 4 把“证据从哪里来”定清楚；Stage 5 从“交给审查者的包长什么样”
开始。

## 3. 目标

v5.1 的目标是定义最小 `ReviewerHandoffPackage`：

- 绑定 Master / Stage / Version Taskbook；
- 绑定 Stage 4 的 audit/evidence package；
- 带上 changed files；
- 带上 validation truth；
- 带上 scope evidence；
- 带上 known risks 和 known gaps；
- 带上 reviewer questions；
- 带上 allowed review decision values。

`allowed_review_decisions` = 允许的审查决策选项。

中文意思是：Reviewer 可以从这些选项里做判断，但 generator 不能推荐 `ACCEPT`，
也不能把选项写成已经接受。

## 4. 最小合约

`ReviewerHandoffPackage` 至少需要：

- `handoff_package_id`
- `handoff_schema_version`
- `master_taskbook_ref`
- `stage_taskbook_ref`
- `version_taskbook_ref`
- `stage_4_audit_package_ref`
- `execution_receipt_refs`
- `claim_summary`
- `changed_files`
- `validation_truth`
- `scope_evidence`
- `known_risks`
- `known_gaps`
- `reviewer_questions`
- `allowed_review_decisions`
- `forbidden_generator_claims`
- `generated_at`

允许的审查决策只有：

- `ACCEPT`
- `NEEDS_FIX`
- `PLAN_ADJUST`
- `ABORT`

禁止 generator 声明：

- 推荐 `ACCEPT`；
- delivery_state 已 accepted；
- review acceptance 已记录；
- Commander 已授权下一条 route；
- 没有 Reviewer 判断就声明 scope aligned。

## 5. 候选写入范围

未来如果 Commander 单独授权执行，本版本候选写入范围最多包括：

- `runner/reviewer_handoff_schema.py`
- `tests/test_reviewer_handoff_schema.py`
- `docs/taskbooks/versions/stage-05/evidence/VERSION_STAGE_05_V5_1_REVIEWER_HANDOFF_SCHEMA_REPORT.md`
- `docs/taskbooks/versions/stage-05/evidence/zh-CN/VERSION_STAGE_05_V5_1_REVIEWER_HANDOFF_SCHEMA_REPORT.zh-CN.md`

这些现在只是候选路径，不是当前授权。

## 6. 拒绝规则

v5.1 应拒绝这些情况：

- 缺少 Master / Stage / Version 绑定；
- 缺少 Stage 4 audit package；
- 缺少 validation truth；
- 缺少 changed files；
- 缺少 scope evidence；
- 缺少 reviewer questions；
- decision options 被扩展；
- generator 推荐 `ACCEPT`；
- package 声明 delivery_state accepted；
- package 声明 review acceptance recorded。

## 7. 人工验收条件

审查者可以接受 v5.1 的条件包括：

- schema 要求 Master / Stage / Version / Stage 4 evidence 绑定；
- schema 要求 validation truth 和 scope evidence；
- allowed decisions 只保留 `ACCEPT / NEEDS_FIX / PLAN_ADJUST / ABORT`；
- schema 禁止 generator 推荐 `ACCEPT`；
- schema 清楚区分 handoff package、ReviewDecision、GateEvent。

不能接受的情况包括：

- package schema 可以被读成 review acceptance；
- package schema 可以改 delivery state；
- decision option 可以绕过 Commander review 扩展；
- 中文 companion 改弱了权威边界。

## 8. 下一步交接

v5.1 通过后，才能交给 v5.2 定义 `Reviewer Handoff Generator V1`。

中文意思是：先把“包的格式”锁住，再写“怎么生成这个包”。格式本身不等于审查通过。
