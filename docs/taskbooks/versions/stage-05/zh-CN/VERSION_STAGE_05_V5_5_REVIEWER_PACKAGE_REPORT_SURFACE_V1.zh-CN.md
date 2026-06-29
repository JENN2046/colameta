# Version 中文任务书：Stage 5 / v5.5 审查包报告展示面 V1

```yaml id="version-stage-05-v5-5-zh-cn-summary"
chinese_companion:
  source_document: docs/taskbooks/versions/stage-05/VERSION_STAGE_05_V5_5_REVIEWER_PACKAGE_REPORT_SURFACE_V1.md
  source_sha256: 99f187020e9908ff1d4532ffc656f4f660b14592369fe5006c2decd28d96f0c5
  translation_status: companion_draft
  authority_status: planning_reference_only
version_execution_taskbook:
  version_id: stage_05_v5_5_reviewer_package_report_surface_v1
  version: v5.5
  chinese_name: 审查包报告展示面 V1
  status: discussion_draft
  execution_authorization_status: not_authorized
```

## 1. 这份任务书是什么

`Reviewer Package Report Surface V1` = 审查包报告展示面 V1。

中文意思是：把 Stage 5 生成的审查材料整理成 Reviewer 能读、能判断、能选择决策
选项的报告表面；它不是 Reviewer 的决定本身。

它现在不授权实现，不授权 executor，不授权 review decision submission，不授权
GateEvent，不授权 release，也不授权 accepted delivery state。

## 2. 父级绑定

这份 Version 绑定到：

- Master Taskbook hash：`1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34`
- Stage 5 Taskbook hash：`532d36ab5c99d37c1a88b094fbe9c37bdc342e17e572447468a0918afbdce43c`
- v5.4 hash：`7ba2f150461cc03cfcce3068c6e9a13925494eb1282036962324904335418c39`
- Stage 4 Version set confirmation hash：`b1da3ea7e105d48f5018c5be17bb59e0164779bfe06e8a36f8e7265b62031c6f`

## 3. 目标

v5.5 的目标是定义最小 reviewer-facing report surface，包括：

- package identity；
- binding summary；
- task goal summary；
- claim summary；
- changed files；
- validation truth；
- scope evidence；
- alignment questions；
- drift questions；
- known risks；
- known gaps；
- allowed review decisions；
- non-authority notice。

`Report Surface` = 报告展示面。

中文意思是：审查者看到的报告结构和字段顺序，不是审查系统的权力来源。

## 4. 展示面合约

报告必须展示：

- package identity；
- binding summary；
- task goal summary；
- claim summary；
- changed files；
- validation truth；
- scope evidence；
- alignment questions；
- drift questions；
- known risks；
- known gaps；
- allowed review decisions；
- non-authority notice。

四个决策选项必须同时可见：

- `ACCEPT`
- `NEEDS_FIX`
- `PLAN_ADJUST`
- `ABORT`

报告必须明确说明：

- report surface 不是 review decision；
- report surface 不是 delivery state transition；
- report surface 不是 Commander authorization；
- report surface 不是 executor authorization。

禁止的展示模式包括：

- 高亮 `ACCEPT` 作为推荐；
- 隐藏 `NEEDS_FIX` 或 `PLAN_ADJUST`；
- 把 validation pass 标成 accepted；
- 已知有风险时不展示 risk summary。

## 5. 最小报告结构

报告至少分为：

- package identity；
- binding summary；
- review body；
- reviewer prompts；
- boundary footer。

其中 review body 必须展示：

- claim summary；
- evidence inventory；
- changed files；
- validation truth；
- scope evidence；
- known risks；
- known gaps。

boundary footer 必须展示：

- 这不是 ReviewDecision；
- 这不是 Delivery State Gate transition；
- 这不是 commit / push authorization；
- 这不是 executor authorization。

## 6. Stage 5 集合交接

v5.1-v5.5 合起来定义 Stage 5 最小 reviewer handoff package protocol：

- schema；
- generator；
- alignment questions；
- drift questions；
- reviewer-facing report surface。

Stage 5 集合审查时必须确认：

- previous version hashes 都能解析；
- 中文 companion source hashes 都匹配；
- 没有 generator 推荐 `ACCEPT` 的措辞；
- 没有 ReviewDecision creation authority；
- 没有 GateEvent emission authority；
- 没有 delivery_state accepted wording。

## 7. 候选写入范围

未来如果 Commander 单独授权执行，本版本候选写入范围最多包括：

- `runner/reviewer_package_report_surface.py`
- `tests/test_reviewer_package_report_surface.py`
- `docs/taskbooks/versions/stage-05/evidence/VERSION_STAGE_05_V5_5_REVIEWER_PACKAGE_REPORT_SURFACE_REPORT.md`
- `docs/taskbooks/versions/stage-05/evidence/zh-CN/VERSION_STAGE_05_V5_5_REVIEWER_PACKAGE_REPORT_SURFACE_REPORT.zh-CN.md`

这些现在只是候选路径，不是当前授权。

## 8. 拒绝规则

v5.5 应拒绝这些情况：

- report surface 缺少 binding summary；
- report surface 缺少 validation truth；
- report surface 缺少 scope evidence；
- report surface 缺少 alignment 或 drift questions；
- report surface 推荐 `ACCEPT`；
- report surface 隐藏 `NEEDS_FIX` 或 `PLAN_ADJUST`；
- report surface 声明 ReviewDecision recorded；
- report surface 声明 delivery_state transition。

## 9. 人工验收条件

审查者可以接受 v5.5 的条件包括：

- report surface 足够自包含，Reviewer 不需要重建整个线程；
- 四个 review decisions 同等可见；
- risks、gaps、unclear items 都被展示；
- report surface 明确声明自己不是 ReviewDecision 或 GateEvent。

不能接受的情况包括：

- report 让 `ACCEPT` 看起来像推荐；
- report 隐藏风险或缺口；
- report 把 validation pass 变成 accepted state；
- 中文 companion 改弱了 non-authority boundary。

## 10. 下一阶段交接

v5.5 通过后，才能交给 Stage 6 的 `Review Feedback Intake`。

中文意思是：v5.5 是“把审查材料摆到桌上”，不是“替审查者盖章”。Stage 6 只能在
这个边界清楚之后，接收真正的审查反馈。
