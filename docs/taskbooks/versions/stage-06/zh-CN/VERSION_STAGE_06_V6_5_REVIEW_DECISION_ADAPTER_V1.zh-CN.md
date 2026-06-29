# Version 中文任务书：Stage 6 / v6.5 审查决策适配器 V1

```yaml id="version-stage-06-v6-5-zh-cn-summary"
chinese_companion:
  source_document: docs/taskbooks/versions/stage-06/VERSION_STAGE_06_V6_5_REVIEW_DECISION_ADAPTER_V1.md
  source_sha256: 0313e9dd493566bcf9a38a48a19be0eec3e1cecf52fc1454cfad30b2e4e622d9
  translation_status: companion_draft
  authority_status: planning_reference_only
version_execution_taskbook:
  version_id: stage_06_v6_5_review_decision_adapter_v1
  version: v6.5
  chinese_name: 审查决策适配器 V1
  status: discussion_draft
  execution_authorization_status: not_authorized
```

## 1. 这份任务书是什么

`Review Decision Adapter V1` = 审查决策适配器 V1。

中文意思是：把不同来源或旧口径的审查反馈值规整到 Stage 6 的四个 ReviewDecision 值，
但不创建 ReviewDecision 记录，也不写 GateEvent。

它现在不授权实现，不授权 executor，不授权 review acceptance，不授权 GateEvent，不授权
runtime state mapping，也不授权 delivery state transition。

## 2. 父级绑定

这份 Version 绑定到：

- Master Taskbook hash：`1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34`
- Stage 6 Taskbook hash：`c83c979d447a4ec645d380b6c1dc206730d12d5d644c08582b3cfd04f3e0009d`
- v6.4 hash：`34fd4bdca1a6cb4c21ee03a8836de0d6c35e6c3c9376be543cb9742dcf4ddcd5`
- Stage 5 Version set confirmation hash：`ca23f567af50038469e3198b9a5600b1625e595c3381f20d262ab3aa81d61ea8`

## 3. 目标

v6.5 的目标是定义 bounded adapter：

- 接受 native review values；
- 处理 legacy alias；
- 保留 original value；
- 输出 normalized value；
- 暴露 alias policy ref；
- 检查 forbidden meanings；
- 不创建 ReviewDecision；
- 不创建 GateEvent。

`PASS alias` = PASS 别名。

中文意思是：为了兼容旧表述，`PASS` 可以在有明确 policy ref 时映射成
`ReviewDecision.ACCEPT`，但绝不等于 runtime `PASSED` 或 delivery state `accepted`。

## 4. 运行态兼容边界

v6.5 必须区分：

- `ReviewDecision.ACCEPT`
- legacy `PASS` alias；
- runtime `VERSION_PASSED`；
- runtime `PASSED`；
- delivery_state `accepted`。

禁止等价关系：

- PASS 等于 delivery_state accepted；
- ACCEPT 等于 delivery_state accepted；
- runtime PASSED 等于 review acceptance；
- validation passed 等于 review acceptance。

必须披露：

- PASS 使用时的 alias policy ref；
- normalized value；
- original value；
- no delivery state transition notice。

## 5. Stage 6 集合交接

v6.1-v6.5 合起来定义 Stage 6 最小 review feedback intake protocol：

- schema；
- validation；
- preview；
- classification；
- CommanderDecisionRequest generation；
- ReviewDecision adapter boundary。

Stage 6 集合审查时必须确认：

- previous_version_ref hashes 都能解析；
- 中文 companion source hashes 都匹配；
- 没有 ReviewDecision creation authority wording；
- 没有 GateEvent emission authority wording；
- 没有 plan mutation authority wording；
- 没有 route transition authority wording；
- 没有 delivery_state accepted wording；
- PASS alias 需要 explicit policy ref。

## 6. 候选写入范围

未来如果 Commander 单独授权执行，本版本候选写入范围最多包括：

- `runner/review_decision_adapter.py`
- `tests/test_review_decision_adapter.py`
- `docs/taskbooks/versions/stage-06/evidence/VERSION_STAGE_06_V6_5_REVIEW_DECISION_ADAPTER_REPORT.md`
- `docs/taskbooks/versions/stage-06/evidence/zh-CN/VERSION_STAGE_06_V6_5_REVIEW_DECISION_ADAPTER_REPORT.zh-CN.md`

这些现在只是候选路径，不是当前授权。

## 7. 拒绝规则

v6.5 应拒绝：

- unknown review value；
- PASS alias without policy ref；
- alias policy ref missing or untrusted；
- adapter output claims ReviewDecision record；
- adapter output claims GateEvent；
- adapter output claims delivery state transition；
- adapter equates runtime PASSED with review acceptance。

## 8. 人工验收条件

审查者可以接受 v6.5 的条件包括：

- adapter 保留 original value、normalized value 和 policy ref；
- PASS alias 需要 explicit policy ref；
- runtime PASSED 和 delivery_state accepted 保持分离；
- adapter output 不能创建 ReviewDecision、GateEvent 或 state transition。

不能接受的情况包括：

- PASS 可以暗示 accepted delivery state；
- ACCEPT 可以暗示 accepted delivery state；
- adapter 隐藏 alias use；
- 中文 companion 改弱 runtime compatibility boundary。

## 9. Thin Governed Loop 交接

Stage 0 到 Stage 6 现在有了 Version Taskbook candidate sets，定义了从 baseline
reality 到 reviewer feedback intake 的最小 thin governed loop。

中文解释：v6.5 把旧审查词和运行态词分开，防止 `PASS / PASSED / ACCEPT / accepted`
混成一团。Stage 0-6 到这里完成的是“最小治理闭环的计划骨架”，不是实现闭环。
