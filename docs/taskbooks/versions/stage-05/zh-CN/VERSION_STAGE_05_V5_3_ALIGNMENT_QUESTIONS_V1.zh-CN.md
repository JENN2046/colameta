# Version 中文任务书：Stage 5 / v5.3 对齐问题 V1

```yaml id="version-stage-05-v5-3-zh-cn-summary"
chinese_companion:
  source_document: docs/taskbooks/versions/stage-05/VERSION_STAGE_05_V5_3_ALIGNMENT_QUESTIONS_V1.md
  source_sha256: 8e61482234cd2493463214649366b8b7d2455b2ea1d17777eea4bc4a1c04b98c
  translation_status: companion_draft
  authority_status: planning_reference_only
version_execution_taskbook:
  version_id: stage_05_v5_3_alignment_questions_v1
  version: v5.3
  chinese_name: 对齐问题 V1
  status: discussion_draft
  execution_authorization_status: not_authorized
```

## 1. 这份任务书是什么

`Alignment Questions V1` = 对齐问题 V1。

中文意思是：把 Reviewer 必须判断的“是否贴合最终目标、阶段目标、版本目标”
转成固定问题清单，但答案仍由 Reviewer 给出，不由 generator 代答。

它现在不授权实现，不授权 executor，不授权 review acceptance，不授权 alignment
confirmed，也不授权 delivery_state accepted。

## 2. 父级绑定

这份 Version 绑定到：

- Master Taskbook hash：`1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34`
- Stage 5 Taskbook hash：`532d36ab5c99d37c1a88b094fbe9c37bdc342e17e572447468a0918afbdce43c`
- v5.2 hash：`5b47123fa34da5a9381d2747bbdd1ba23efbe2b992130d511065240f99c5547a`
- Stage 4 Version set confirmation hash：`b1da3ea7e105d48f5018c5be17bb59e0164779bfe06e8a36f8e7265b62031c6f`

## 3. 目标

v5.3 的目标是定义最小对齐问题集，让 Reviewer 判断证据是否支持：

- 项目最终目标；
- 父 Stage 目标；
- 当前 Version 任务目标；
- scope；
- evidence；
- risk。

`project_final_goal_alignment` = 项目最终目标对齐。

中文意思是：Reviewer 要判断当前证据是否真的服务于用户最终要实现的东西，而不是
只看任务列表有没有打勾。

## 4. 问题合约

对齐问题必须覆盖：

- project final goal alignment；
- stage goal alignment；
- version task goal alignment；
- scope alignment；
- evidence alignment；
- risk alignment。

每个问题至少需要：

- `question_id`
- `question_text`
- `target_ref`
- `evidence_refs`
- `reviewer_answer_options`
- `unanswered_state`

Reviewer 的回答选项是：

- `YES`
- `NO`
- `UNCLEAR`
- `NOT_APPLICABLE`

禁止的问题行为包括：

- 预填 `YES`；
- 推荐 `ACCEPT`；
- 隐藏 `UNCLEAR`；
- generator 把 alignment 分数当成最终判断。

## 5. 必问问题

v5.3 至少要问：

- 证据是否支持 project final goal，而不只是局部任务完成？
- 是否未经 Commander 授权修改了 project final goal？
- 证据是否支持 Stage 5 的 reviewer handoff，而不是 reviewer replacement？
- Stage 5 non-goals 是否保留？
- package 是否满足当前 Version task goal？
- 缺失字段或风险是否被暴露而不是隐藏？
- changed files 是否在 declared scope 内？
- 每个 claim 是否有 evidence ref？
- validation truth 和 scope evidence 是否没有被写成 acceptance？
- known risks 和 known gaps 是否足够可见？
- Reviewer 是否被要求判断 unresolved drift？

## 6. 候选写入范围

未来如果 Commander 单独授权执行，本版本候选写入范围最多包括：

- `runner/reviewer_alignment_questions.py`
- `tests/test_reviewer_alignment_questions.py`
- `docs/taskbooks/versions/stage-05/evidence/VERSION_STAGE_05_V5_3_ALIGNMENT_QUESTIONS_REPORT.md`
- `docs/taskbooks/versions/stage-05/evidence/zh-CN/VERSION_STAGE_05_V5_3_ALIGNMENT_QUESTIONS_REPORT.zh-CN.md`

这些现在只是候选路径，不是当前授权。

## 7. 拒绝规则

v5.3 应拒绝这些情况：

- 缺少 project final goal question；
- 缺少 stage goal question；
- 缺少 version task goal question；
- 缺少 scope alignment question；
- claim 没有 evidence ref；
- answer options 没有 `UNCLEAR`；
- generator 预填 `YES` 或 `ACCEPT`；
- alignment question 声明 final alignment。

## 8. 人工验收条件

审查者可以接受 v5.3 的条件包括：

- project / Stage / Version alignment 分开询问；
- answer options 包含 `UNCLEAR`；
- 每个 claim question 可以携带 evidence refs；
- generator 不能代替 Reviewer 回答 alignment。

不能接受的情况包括：

- 问题措辞诱导 Reviewer 选 `ACCEPT`；
- 问题集漏掉 project final goal；
- alignment result 可以被当成 delivery state；
- 中文 companion 改弱了 alignment 边界。

## 9. 下一步交接

v5.3 通过后，才能交给 v5.4 定义 `Drift Question Pack V1`。

中文意思是：v5.3 要做的是“问准问题”，不是“替审查者说已经对齐”。
