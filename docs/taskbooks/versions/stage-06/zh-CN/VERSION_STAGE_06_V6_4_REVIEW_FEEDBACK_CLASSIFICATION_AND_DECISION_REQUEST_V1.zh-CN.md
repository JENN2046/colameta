# Version 中文任务书：Stage 6 / v6.4 审查反馈分类与决策请求 V1

```yaml id="version-stage-06-v6-4-zh-cn-summary"
chinese_companion:
  source_document: docs/taskbooks/versions/stage-06/VERSION_STAGE_06_V6_4_REVIEW_FEEDBACK_CLASSIFICATION_AND_DECISION_REQUEST_V1.md
  source_sha256: 34fd4bdca1a6cb4c21ee03a8836de0d6c35e6c3c9376be543cb9742dcf4ddcd5
  translation_status: companion_draft
  authority_status: planning_reference_only
version_execution_taskbook:
  version_id: stage_06_v6_4_review_feedback_classification_and_decision_request_v1
  version: v6.4
  chinese_name: 审查反馈分类与决策请求 V1
  status: discussion_draft
  execution_authorization_status: not_authorized
```

## 1. 这份任务书是什么

`Review Feedback Classification And Decision Request V1` = 审查反馈分类与决策请求 V1。

中文意思是：把已验证反馈分类成 Commander 需要决定的请求；它只生成请求，不代替
Commander 授权，也不写 GateEvent。

它现在不授权实现，不授权 executor，不授权 Commander authorization，不授权
ReviewDecision creation，不授权 GateEvent emission，不授权 plan mutation，也不授权
delivery state transition。

## 2. 父级绑定

这份 Version 绑定到：

- Master Taskbook hash：`1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34`
- Stage 6 Taskbook hash：`c83c979d447a4ec645d380b6c1dc206730d12d5d644c08582b3cfd04f3e0009d`
- v6.3 hash：`008b99f4d6ec793f9aaf83868f2ae91da3c1ea0d6bfdaf8664e075021475f990`
- Stage 5 Version set confirmation hash：`ca23f567af50038469e3198b9a5600b1625e595c3381f20d262ab3aa81d61ea8`

## 3. 目标

v6.4 的目标是定义 classification 和 `CommanderDecisionRequest`：

- 把 validated ReviewFeedback 分类；
- 生成 Commander 需要判断的问题；
- 保留 reviewer handoff package ref；
- 保留 Version Taskbook ref；
- 保留 execution report ref；
- 保留 workspace snapshot ref；
- 保留 Master / Stage hash；
- 明确 requested action 不等于 authorized action。

`CommanderDecisionRequest` = 指挥官决策请求。

中文意思是：系统把“下一步该不该做、做哪种动作”整理成请求，等 Commander 授权；
它不是授权本身。

## 4. 决策映射

v6.4 的映射边界：

- `ACCEPT` -> ask whether to request Delivery State Gate review；
- `NEEDS_FIX` -> ask whether to prepare rework or gate return；
- `PLAN_ADJUST` -> ask whether to prepare plan adjustment draft；
- `ABORT` -> ask whether to prepare abort or supersede handling；
- `PASS` alias -> 必须有 policy ref，只映射到 accept review feedback。

禁止效果：

- `ACCEPT` 不能变成 delivery_state accepted；
- `NEEDS_FIX` 不能自动打开 rework route；
- `PLAN_ADJUST` 不能自动修改 plan；
- `ABORT` 不能自动 delete、revert 或 cancel runtime；
- `PASS` 不能变成 delivery_state passed 或 accepted。

## 5. 候选写入范围

未来如果 Commander 单独授权执行，本版本候选写入范围最多包括：

- `runner/review_feedback_classification.py`
- `runner/commander_decision_request.py`
- `tests/test_review_feedback_classification.py`
- `tests/test_commander_decision_request.py`
- `docs/taskbooks/versions/stage-06/evidence/VERSION_STAGE_06_V6_4_REVIEW_FEEDBACK_CLASSIFICATION_AND_DECISION_REQUEST_REPORT.md`
- `docs/taskbooks/versions/stage-06/evidence/zh-CN/VERSION_STAGE_06_V6_4_REVIEW_FEEDBACK_CLASSIFICATION_AND_DECISION_REQUEST_REPORT.zh-CN.md`

这些现在只是候选路径，不是当前授权。

## 6. 拒绝规则

v6.4 应拒绝：

- validation status not valid for preview；
- review decision value unmapped；
- PASS alias without policy ref；
- request 缺少 binding refs；
- request 声称 Commander authorization；
- request 声称 GateEvent emission；
- request 声称 delivery state transition；
- request 声称 plan mutation 或 executor continuation。

## 7. 人工验收条件

审查者可以接受 v6.4 的条件包括：

- 所有 allowed review decisions 都映射到 bounded CommanderDecisionRequest shape；
- request 包含 source feedback 和 binding refs；
- request 明确分离 requested action 与 authorized action；
- ACCEPT 绝不映射到 delivery_state accepted。

不能接受的情况包括：

- request 可以执行自己；
- request 可以 emit GateEvent；
- request 可以 mutate plan 或 route；
- 中文 companion 改弱 Commander authority boundary。

## 8. 下一步交接

v6.4 通过后，才能交给 v6.5 定义 `Review Decision Adapter V1`。

中文意思是：v6.4 可以“生成请求”，但请求不会自己执行。真正动作仍要 Commander 再授权。
