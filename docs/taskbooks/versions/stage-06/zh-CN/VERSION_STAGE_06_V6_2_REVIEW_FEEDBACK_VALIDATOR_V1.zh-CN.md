# Version 中文任务书：Stage 6 / v6.2 审查反馈验证器 V1

```yaml id="version-stage-06-v6-2-zh-cn-summary"
chinese_companion:
  source_document: docs/taskbooks/versions/stage-06/VERSION_STAGE_06_V6_2_REVIEW_FEEDBACK_VALIDATOR_V1.md
  source_sha256: 679f462641f49ebd5bce077c1a387fda2977f5d3ce5707560aacffff3fd8d4f6
  translation_status: companion_draft
  authority_status: planning_reference_only
version_execution_taskbook:
  version_id: stage_06_v6_2_review_feedback_validator_v1
  version: v6.2
  chinese_name: 审查反馈验证器 V1
  status: discussion_draft
  execution_authorization_status: not_authorized
```

## 1. 这份任务书是什么

`Review Feedback Validator V1` = 审查反馈验证器 V1。

中文意思是：检查反馈是否符合 v6.1 schema、hash 是否匹配、绑定是否完整、PASS 是否有
policy ref。验证失败只能返回错误，不生成 CommanderDecisionRequest。

它现在不授权实现，不授权 executor，不授权 commit，不授权 push，不授权 review decision
creation，不授权 GateEvent emission，也不授权 delivery state transition。

## 2. 父级绑定

这份 Version 绑定到：

- Master Taskbook hash：`1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34`
- Stage 6 Taskbook hash：`c83c979d447a4ec645d380b6c1dc206730d12d5d644c08582b3cfd04f3e0009d`
- v6.1 hash：`70ec9d9aa6e34299f3c3f0def67fdc0a8ec066cedbc934868dca98542b38ddf7`
- Stage 5 Version set confirmation hash：`ca23f567af50038469e3198b9a5600b1625e595c3381f20d262ab3aa81d61ea8`

## 3. 目标

v6.2 的目标是定义 fail-closed validator：

- 检查 required fields；
- 检查 allowed decision values；
- 检查 PASS alias policy；
- 检查 binding hashes；
- 检查 handoff package refs；
- 检查 execution report refs；
- 检查 forbidden authority claims。

`valid_for_preview` = 可进入预览。

中文意思是：反馈只通过“可以预览下一步请求”的门，不代表已经接受、已经分类完成或
可以改状态。

## 4. 验证器合约

验证器必须输入：

- review feedback candidate；
- review feedback schema ref；
- expected Master hash；
- expected Stage hash；
- expected Version Taskbook ref；
- expected reviewer handoff package ref；
- expected workspace snapshot ref。

验证器必须输出：

- validation status；
- validation errors；
- normalized review decision value；
- PASS alias policy check；
- binding check；
- forbidden claim check。

禁止输出：

- CommanderDecisionRequest；
- ReviewDecision record；
- GateEvent；
- delivery state transition。

## 5. 拒绝规则

v6.2 应拒绝：

- required field missing；
- binding mismatch；
- unknown review decision value；
- PASS alias policy missing；
- forbidden authority claim present；
- validation output claims next-state authority。

## 6. 候选写入范围

未来如果 Commander 单独授权执行，本版本候选写入范围最多包括：

- `runner/review_feedback_validator.py`
- `tests/test_review_feedback_validator.py`
- `docs/taskbooks/versions/stage-06/evidence/VERSION_STAGE_06_V6_2_REVIEW_FEEDBACK_VALIDATOR_REPORT.md`
- `docs/taskbooks/versions/stage-06/evidence/zh-CN/VERSION_STAGE_06_V6_2_REVIEW_FEEDBACK_VALIDATOR_REPORT.zh-CN.md`

这些现在只是候选路径，不是当前授权。

## 7. 人工验收条件

审查者可以接受 v6.2 的条件包括：

- validator 检查所有必需反馈绑定；
- validator 拒绝没有 policy ref 的 PASS；
- validator 拒绝包含 state 或 route authority claims 的反馈；
- validator output 只有 validation status。

不能接受的情况包括：

- validator 可以生成 CommanderDecisionRequest；
- validator 可以创建 ReviewDecision 或 GateEvent；
- validator 把 ACCEPT 当成 delivery_state accepted；
- 中文 companion 改弱 fail-closed behavior。

## 8. 下一步交接

v6.2 通过后，才能交给 v6.3 定义 `Review Feedback Preview V1`。

中文意思是：v6.2 是“看这份反馈能不能进入预览”，不是“看完就进入下一状态”。
