# Version 中文任务书：Stage 5 / v5.4 漂移问题包 V1

```yaml id="version-stage-05-v5-4-zh-cn-summary"
chinese_companion:
  source_document: docs/taskbooks/versions/stage-05/VERSION_STAGE_05_V5_4_DRIFT_QUESTION_PACK_V1.md
  source_sha256: 7ba2f150461cc03cfcce3068c6e9a13925494eb1282036962324904335418c39
  translation_status: companion_draft
  authority_status: planning_reference_only
version_execution_taskbook:
  version_id: stage_05_v5_4_drift_question_pack_v1
  version: v5.4
  chinese_name: 漂移问题包 V1
  status: discussion_draft
  execution_authorization_status: not_authorized
```

## 1. 这份任务书是什么

`Drift Question Pack V1` = 漂移问题包 V1。

中文意思是：专门让 Reviewer 判断任务是否偏离目标、范围、授权、证据或用户意图。
它只提出漂移检查问题，不替 Reviewer 判定“有漂移”或“无漂移”。

它现在不授权实现，不授权 executor，不授权 review acceptance，不授权 PLAN_ADJUST，
不授权 NEEDS_FIX，也不授权 delivery_state transition。

## 2. 父级绑定

这份 Version 绑定到：

- Master Taskbook hash：`1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34`
- Stage 5 Taskbook hash：`532d36ab5c99d37c1a88b094fbe9c37bdc342e17e572447468a0918afbdce43c`
- v5.3 hash：`8e61482234cd2493463214649366b8b7d2455b2ea1d17777eea4bc4a1c04b98c`
- Stage 4 Version set confirmation hash：`b1da3ea7e105d48f5018c5be17bb59e0164779bfe06e8a36f8e7265b62031c6f`

## 3. 目标

v5.4 的目标是定义最小 drift question pack，让 Reviewer 可以看到并判断：

- project goal drift；
- scope drift；
- authority drift；
- evidence drift；
- validation drift；
- risk drift。

`authority_drift` = 权限漂移。

中文意思是：检查实际动作、文本或证据有没有越过授权边界，例如把 package 当成
commit、push、executor、review acceptance 或 accepted。

## 4. 漂移问题合约

漂移问题至少需要：

- `drift_question_id`
- `drift_type`
- `question_text`
- `expected_reference`
- `observed_evidence_refs`
- `reviewer_answer_options`
- `unresolved_followup_prompt`

Reviewer 的回答选项是：

- `NO_DRIFT_VISIBLE`
- `DRIFT_VISIBLE`
- `UNCLEAR`
- `NOT_APPLICABLE`

禁止的问题行为包括：

- generator 默认标记 no drift；
- generator 把 drift 结果转成 review decision；
- generator 隐藏 `UNCLEAR`；
- generator 删除 authority drift questions。

## 5. 必问问题

v5.4 至少要问：

- 工作是否偏离 project final goal？
- 是否只优化局部机制而丢失 Commander goal？
- 是否有 changed files 超出 declared allowed scope？
- 是否引入无关 refactor 或 metadata churn？
- 是否有 artifact 在未授权下声明 implementation authority？
- 是否有 artifact 在未授权下声明 commit / push / executor / route / review acceptance / delivery_state authority？
- claims 是否指向 evidence refs？
- known gaps 是否被保留而不是隐藏？
- validation truth 是否被报告为 observed truth，而不是 acceptance？
- failed 或 skipped validations 是否可见？
- unresolved risks 是否仍对 Reviewer 可见？
- package 是否指出哪里可能需要 Commander judgment？

## 6. 候选写入范围

未来如果 Commander 单独授权执行，本版本候选写入范围最多包括：

- `runner/reviewer_drift_questions.py`
- `tests/test_reviewer_drift_questions.py`
- `docs/taskbooks/versions/stage-05/evidence/VERSION_STAGE_05_V5_4_DRIFT_QUESTION_PACK_REPORT.md`
- `docs/taskbooks/versions/stage-05/evidence/zh-CN/VERSION_STAGE_05_V5_4_DRIFT_QUESTION_PACK_REPORT.zh-CN.md`

这些现在只是候选路径，不是当前授权。

## 7. 拒绝规则

v5.4 应拒绝这些情况：

- 缺少 project goal drift question；
- 缺少 authority drift question；
- 缺少 evidence refs；
- answer options 没有 `UNCLEAR`；
- generator 默认 no drift；
- drift answer 创建 ReviewDecision；
- drift answer 发出 GateEvent；
- package 声明 no drift as final。

## 8. 人工验收条件

审查者可以接受 v5.4 的条件包括：

- 所有 required drift groups 都出现；
- authority drift 覆盖 commit / push / executor / route / review / state claims；
- `UNCLEAR` 保持可见；
- drift answers 仍归 Reviewer 所有，不归 generator 所有。

不能接受的情况包括：

- generator 可以自证 no drift；
- drift questions 漏掉 authority drift；
- drift answers 暗示 acceptance；
- 中文 companion 改弱了 drift 边界。

## 9. 下一步交接

v5.4 通过后，才能交给 v5.5 定义 `Reviewer Package Report Surface V1`。

中文意思是：v5.4 是把“可能跑偏了吗”问出来，不是让系统自己宣布“没有跑偏”。
