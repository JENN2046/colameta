# Version 中文任务书：Stage 5 / v5.2 审查者交接生成器 V1

```yaml id="version-stage-05-v5-2-zh-cn-summary"
chinese_companion:
  source_document: docs/taskbooks/versions/stage-05/VERSION_STAGE_05_V5_2_REVIEWER_HANDOFF_GENERATOR_V1.md
  source_sha256: 5b47123fa34da5a9381d2747bbdd1ba23efbe2b992130d511065240f99c5547a
  translation_status: companion_draft
  authority_status: planning_reference_only
version_execution_taskbook:
  version_id: stage_05_v5_2_reviewer_handoff_generator_v1
  version: v5.2
  chinese_name: 审查者交接生成器 V1
  status: discussion_draft
  execution_authorization_status: not_authorized
```

## 1. 这份任务书是什么

`Reviewer Handoff Generator V1` = 审查者交接生成器 V1。

中文意思是：把已有的 Stage 4 audit/evidence package 转换成审查者可读的
handoff package，但只生成材料，不推荐结论，不写 ReviewDecision，也不改
Delivery State Gate。

它现在不授权实现，不授权代码修改，不授权 executor，不授权 commit，不授权 push，
不授权 fetch/pull，不授权 review acceptance，不授权 GateEvent，也不授权 accepted。

## 2. 父级绑定

这份 Version 绑定到：

- Master Taskbook hash：`1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34`
- Stage 5 Taskbook hash：`532d36ab5c99d37c1a88b094fbe9c37bdc342e17e572447468a0918afbdce43c`
- v5.1 hash：`7c1d5d95f02a1ff7b22712678d05e50a88fff00f5f43af0969d0292920d50e54`
- Stage 4 Version set confirmation hash：`b1da3ea7e105d48f5018c5be17bb59e0164779bfe06e8a36f8e7265b62031c6f`

## 3. 目标

v5.2 的目标是定义一个最小 generator：

- 读取 v5.1 schema；
- 读取 Stage 4 audit package；
- 输出完整 reviewer handoff package；
- 填入 claim summary、changed files、validation truth、scope evidence；
- 保留 known risks 和 known gaps；
- 加入 reviewer questions；
- 保留 allowed review decisions。

中文解释：v5.2 是“装包机器”，不是“审查官”。它只能把材料装完整，不能代替判断。

## 4. 生成器合约

生成器必须输入：

- reviewer handoff schema；
- Master / Stage / Version refs；
- Stage 4 audit package ref；
- validation truth source；
- changed files source；
- scope evidence source。

生成器必须输出：

- reviewer handoff package；
- generation summary；
- missing input report；
- forbidden claim check。

生成器必须做到：

- 保留固定 review decisions；
- 保留 known risks 和 known gaps；
- 不把 validation truth 改写成 acceptance；
- 缺证据时 fail closed；
- 询问 Reviewer 是否存在 drift。

生成器禁止：

- 推荐 `ACCEPT`；
- 推断 review decision；
- 创建 ReviewDecision record；
- 发出 GateEvent；
- 修改 delivery_state；
- 隐藏 validation failure。

## 5. 候选写入范围

未来如果 Commander 单独授权执行，本版本候选写入范围最多包括：

- `runner/reviewer_handoff_generator.py`
- `tests/test_reviewer_handoff_generator.py`
- `docs/taskbooks/versions/stage-05/evidence/VERSION_STAGE_05_V5_2_REVIEWER_HANDOFF_GENERATOR_REPORT.md`
- `docs/taskbooks/versions/stage-05/evidence/zh-CN/VERSION_STAGE_05_V5_2_REVIEWER_HANDOFF_GENERATOR_REPORT.zh-CN.md`

这些现在只是候选路径，不是当前授权。

## 6. 拒绝规则

v5.2 应拒绝这些情况：

- schema ref 缺失或不匹配；
- Stage 4 audit package 缺失；
- validation truth unknown；
- changed files unknown；
- scope evidence missing；
- allowed review decisions 被扩展；
- generator output 包含 `ACCEPT` 推荐；
- generator output 包含 delivery_state transition；
- generator output 包含 ReviewDecision record；
- generator output 隐藏 known risks。

## 7. 人工验收条件

审查者可以接受 v5.2 的条件包括：

- generator 按 v5.1 schema 填字段；
- 缺必需证据时 fail closed；
- 不增加决策选项；
- `ACCEPT` 只作为 Reviewer 可选项；
- 输出仍然独立于 ReviewDecision 和 GateEvent。

不能接受的情况包括：

- generator 推荐 `ACCEPT`；
- generator 把 validation pass 转成 review acceptance；
- generator 可以改 delivery state；
- generator 隐藏缺失证据或风险。

## 8. 下一步交接

v5.2 通过后，才能交给 v5.3 定义 `Alignment Questions V1`。

中文意思是：先保证“材料包”不越权，再问它和目标是否对齐。
