# Version 中文任务书：Stage 6 / v6.3 审查反馈预览 V1

```yaml id="version-stage-06-v6-3-zh-cn-summary"
chinese_companion:
  source_document: docs/taskbooks/versions/stage-06/VERSION_STAGE_06_V6_3_REVIEW_FEEDBACK_PREVIEW_V1.md
  source_sha256: 008b99f4d6ec793f9aaf83868f2ae91da3c1ea0d6bfdaf8664e075021475f990
  translation_status: companion_draft
  authority_status: planning_reference_only
version_execution_taskbook:
  version_id: stage_06_v6_3_review_feedback_preview_v1
  version: v6.3
  chinese_name: 审查反馈预览 V1
  status: discussion_draft
  execution_authorization_status: not_authorized
```

## 1. 这份任务书是什么

`Review Feedback Preview V1` = 审查反馈预览 V1。

中文意思是：在反馈通过验证后，展示它将如何被分类、可能生成什么
CommanderDecisionRequest，但不真正创建请求、不写状态、不改计划。

它现在不授权实现，不授权 executor，不授权 request creation，不授权 review decision
creation，不授权 GateEvent，也不授权 delivery state transition。

## 2. 父级绑定

这份 Version 绑定到：

- Master Taskbook hash：`1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34`
- Stage 6 Taskbook hash：`c83c979d447a4ec645d380b6c1dc206730d12d5d644c08582b3cfd04f3e0009d`
- v6.2 hash：`679f462641f49ebd5bce077c1a387fda2977f5d3ce5707560aacffff3fd8d4f6`
- Stage 5 Version set confirmation hash：`ca23f567af50038469e3198b9a5600b1625e595c3381f20d262ab3aa81d61ea8`

## 3. 目标

v6.3 的目标是定义 non-authoritative preview：

- 展示 validated ReviewFeedback 将如何分类；
- 展示 candidate CommanderDecisionRequest shape；
- 保留 missing information；
- 保留 boundary notice；
- 不创建 request id；
- 不写状态。

`candidate_commander_decision_request_shape` = 候选指挥官决策请求形状。

中文意思是：只展示将来可能向 Commander 请求什么字段，不创建真正的请求编号或授权对象。

## 4. 预览映射

预览映射包括：

- `ACCEPT`：预览为“是否请求 Delivery State Gate review”；
- `NEEDS_FIX`：预览为“是否准备返工或 gate return”；
- `PLAN_ADJUST`：预览为“是否准备 plan adjustment draft”；
- `ABORT`：预览为“是否准备 abort 或 supersede handling”；
- `PASS` alias：必须有 policy ref，并只映射到 accept preview path。

这些预览都不能：

- 标记 delivery_state accepted；
- 发出 GateEvent；
- 继续 executor；
- 自动打开 route；
- 自动改 plan；
- 删除、回滚或取消 runtime。

## 5. 候选写入范围

未来如果 Commander 单独授权执行，本版本候选写入范围最多包括：

- `runner/review_feedback_preview.py`
- `tests/test_review_feedback_preview.py`
- `docs/taskbooks/versions/stage-06/evidence/VERSION_STAGE_06_V6_3_REVIEW_FEEDBACK_PREVIEW_REPORT.md`
- `docs/taskbooks/versions/stage-06/evidence/zh-CN/VERSION_STAGE_06_V6_3_REVIEW_FEEDBACK_PREVIEW_REPORT.zh-CN.md`

这些现在只是候选路径，不是当前授权。

## 6. 拒绝规则

v6.3 应拒绝：

- validation status 不是 `valid_for_preview`；
- candidate request shape 缺少 boundary notice；
- preview 创建 request id；
- preview 声称 ReviewDecision recorded；
- preview 声称 GateEvent emitted；
- preview 声称 delivery state transition；
- preview 隐藏 unclear 或 missing information。

## 7. 人工验收条件

审查者可以接受 v6.3 的条件包括：

- preview 映射所有 decision values 到 candidate paths；
- preview 不创建 actionable request id；
- preview 保留 missing information；
- preview 保持 ACCEPT 与 delivery_state accepted 分离。

不能接受的情况包括：

- preview 可以授权 next route；
- preview 可以创建 CommanderDecisionRequest；
- preview 可以 emit GateEvent；
- 中文 companion 改弱 preview-only boundary。

## 8. 下一步交接

v6.3 通过后，才能交给 v6.4 定义 `Review Feedback Classification And Decision Request V1`。

中文意思是：v6.3 是“先给 Commander 看将会问什么”，不是“已经问了也不是已经批准了”。
