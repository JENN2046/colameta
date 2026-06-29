# Version 中文任务书：Stage 2 / v2.1 阶段任务书模式与校验器 V1

```yaml id="version-stage-02-v2-1-zh-cn-summary"
chinese_companion:
  source_document: docs/taskbooks/versions/stage-02/VERSION_STAGE_02_V2_1_STAGE_TASKBOOK_SCHEMA_VALIDATOR_V1.md
  source_sha256: 76c3c12c191609f94c16d292e40217db08c8020792157639011b046cb977c429
  translation_status: companion_draft
  authority_status: planning_reference_only
version_execution_taskbook:
  version_id: stage_02_v2_1_stage_taskbook_schema_validator_v1
  version: v2.1
  chinese_name: 阶段任务书模式与校验器 V1
  status: discussion_draft
  created_from_head_meaning: historical_creation_baseline_not_execution_or_freeze_snapshot
  execution_authorization_status: not_authorized
```

## 1. 这份任务书是什么

这是 Stage 2 的第一份 Version 任务书草稿。

`Version Execution Taskbook` = 版本执行任务书。中文意思是：把一个 Stage 下面的一次
小交付拆成明确边界，说明目标、能读什么、能写什么、怎么验收、什么时候停止、需要
哪些证据。

本版本叫：

```text
Stage Taskbook Schema And Validator V1
```

中文意思是：

```text
阶段任务书模式与校验器 V1
```

它的核心任务是：定义 Stage Taskbook 必须有哪些字段，并定义一个最小校验器，让
缺少 Master 绑定、阶段目标、非目标、状态门就绪条件或证据包的 Stage Taskbook
默认不通过。

它现在不是执行授权，不授权实现，不授权 executor，不授权 commit，不授权 push，
不授权 fetch/pull，也不授权任何 delivery state 变化。

## 2. 父级绑定

这份 Version 绑定到：

- Master Taskbook：`PROJECT_MASTER_TASKBOOK.md`
  - hash：`1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34`
  - 状态：`freeze_candidate_confirmed_for_exact_hash`
- Stage 2 Taskbook：`docs/taskbooks/stages/STAGE_02_STAGE_TASKBOOK_MANAGEMENT.md`
  - hash：`b0e1a55121503df4116d9c49031eb07729858c483cc73e6c97730eca0a067876`
- Stage 0-6 freeze packet：`docs/taskbooks/stages/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_0_6.md`
  - hash：`94ea9101a120e0935e834533ed0315a6fe3e77e3d4ecb48db37fa6851e75b5ce`
- Stage 0 Version set confirmation record：
  - path：`docs/taskbooks/versions/stage-00/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_00_VERSIONS.md`
  - hash：`b3d838f5229a94e88dbaa405a0f65ae76f5208660ab000c1eecd777090897acc`
- Stage 1 Version set confirmation record：
  - path：`docs/taskbooks/versions/stage-01/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_01_VERSIONS.md`
  - hash：`c4ef865c84ab634a7b3626cdc6924a4e51420a1d6d94bb274aeb9f13d354fce5`

中文解释：它只能服务 Stage 2 的“阶段任务书管理”，不能反过来修改 Master、Stage 2
或 Stage 0/1 的确认记录。

## 3. 目标

本版本的目标是定义 Stage 2 的第一刀实现边界：

- 定义 Stage Taskbook 必填字段；
- 定义 `master_taskbook_ref` 校验；
- 校验 Stage Taskbook 是否说明自己支持 `project_final_goal`；
- 校验 stage purpose、non-goals、gate-readiness criteria；
- 校验 minimum evidence package；
- 明确 Stage Taskbook 声明不等于 accepted delivery state；
- 为后续 Stage Taskbook registry 提供前置校验合约。

`master_taskbook_ref` = 主任务书引用。中文意思是：Stage Taskbook 必须说清楚自己
绑定哪一份 Master，而不是靠聊天上下文继续。

`gate-readiness criteria` = 状态门就绪条件。中文意思是：Stage Taskbook 只能说
“到什么程度可以拿去审查”，不能自己宣布 accepted。

## 4. 不做什么

v2.1 不做：

- Stage Taskbook registry；
- 启动迁移引擎；
- 自动生成 Stage；
- executor dispatch；
- review acceptance；
- Delivery State Gate transition；
- codex-router bridge；
- Stage Taskbook 源文件修改；
- Master 内容修改。

中文解释：这一刀只做“模式与校验”。不要把 Stage 2 的所有能力塞进第一版。

## 5. 执行信封是什么意思

`Execution Envelope` = 执行信封。

中文意思是：真正执行前必须有一封边界信，明确：

- 可以读哪些文件；
- 可以写哪些文件；
- 不能碰哪些文件；
- 可以运行哪些命令；
- 什么时候必须停下；
- 最后报告到哪里。

英文任务书里已经写了一个候选执行信封，但它现在还没有被授权。

## 6. 允许和禁止的文件

未来如果 Commander 单独授权执行，本版本候选写入范围最多包括：

- `.colameta/taskbooks/stage_taskbook_schema.json`
- `runner/stage_taskbook_validator.py`
- `tests/test_stage_taskbook_validator.py`
- `docs/taskbooks/versions/stage-02/evidence/VERSION_STAGE_02_V2_1_STAGE_TASKBOOK_SCHEMA_VALIDATOR_REPORT.md`
- `docs/taskbooks/versions/stage-02/evidence/zh-CN/VERSION_STAGE_02_V2_1_STAGE_TASKBOOK_SCHEMA_VALIDATOR_REPORT.zh-CN.md`

这些现在只是候选路径，不是当前授权。

禁止修改：

- `/home/jenn/tools/colameta/**`
- `PROJECT_MASTER_TASKBOOK.md`
- `PROJECT_MASTER_TASKBOOK.zh-CN.md`
- `docs/taskbooks/stages/**`
- `docs/taskbooks/versions/stage-00/**`
- `docs/taskbooks/versions/stage-01/**`
- `.colameta/state.json`
- `.colameta/runtime/**`
- `.git/**`
- `.env`、secret、credential 相关文件。

中文解释：v2.1 可以定义未来 schema 和 validator 怎么写，但不能现在就修改 Stage
Taskbook，也不能碰稳定服务目录。

## 7. 阶段任务书模式最小合约

`Stage Taskbook Schema Minimum Contract` = 阶段任务书模式最小合约。

中文意思是：未来 Stage Taskbook 至少要包括这些字段：

- `stage_id`：阶段 ID；
- `stage_name`：阶段英文名；
- `chinese_name`：阶段中文名；
- `status`：草稿或审查状态；
- `authority_status`：权威状态；
- `master_taskbook_ref`：主任务书引用；
- `supports_project_goal`：是否支持项目最终目标；
- `stage_purpose`：阶段目的；
- `entry_criteria`：进入条件；
- `exit_criteria`：退出条件；
- `deliverables`：交付物；
- `gate_readiness_criteria`：状态门就绪条件；
- `minimum_evidence_package`：最小证据包；
- `non_goals`：非目标。

还需要 readiness contract 字段：`minimum_readiness_claim`、`required_evidence`、
`gate_question`、`explicit_non_goal`。

## 8. 校验器行为

`Validator` = 校验器。中文意思是：它读取 Stage Taskbook，检查字段和边界是否完整。

校验器必须在这些情况下失败关闭：

- 缺少 `master_taskbook_ref`；
- Master hash 不匹配；
- 缺少 stage purpose；
- 缺少 non-goals；
- 缺少 gate-readiness criteria；
- 缺少 minimum evidence package；
- Stage Taskbook 声称 delivery state accepted；
- Stage Taskbook 声称 execution authority。

`fail closed` = 失败时关闭。中文意思是：校验不清楚时按“不通过”处理，不能默认放行。

## 9. 候选验收命令

英文任务书列出的候选命令包括：

- `git status --short --branch`
- `git rev-parse HEAD`
- `git rev-parse origin/main || true`
- `git rev-list --left-right --count origin/main...HEAD || true`
- `sha256sum PROJECT_MASTER_TASKBOOK.md docs/taskbooks/stages/STAGE_02_STAGE_TASKBOOK_MANAGEMENT.md`
- `python -m unittest tests.test_stage_taskbook_validator`
- `python -m compileall runner/stage_taskbook_validator.py`

这些是未来执行时的候选验收命令。现在写在任务书里，不代表已经执行，也不代表已经
授权执行。

## 10. 人工验收条件

审查者可以接受 v2.1 的条件包括：

- schema 必填字段匹配 Stage 2 的 Required Field Matrix；
- validator 拒绝缺少 `master_taskbook_ref`；
- validator 拒绝缺少 non-goals 和 gate-readiness criteria；
- validator 拒绝任何把 Stage Taskbook 说成 accepted delivery state 的声明；
- 证据报告区分 `commands_run` 和 `commands_not_run`；
- 中文报告 companion 用中文解释技术术语。

审查者不能接受的情况包括：

- validator 只把缺失字段当 warning；
- schema 允许 Stage Taskbook 声称状态权威；
- 实现修改 Stage Taskbook 源文件；
- 证据只来自聊天记忆或陈旧 runtime label；
- 测试或报告校验失败且没有记录 known_unknown。

## 11. 停止条件

出现以下情况必须停止：

- 仓库不是 `/home/jenn/src/colameta-dev`；
- 实现会修改 `PROJECT_MASTER_TASKBOOK.md`；
- 实现会修改 Stage Taskbook 源文件；
- 实现需要改 `/home/jenn/tools/colameta`；
- 实现需要 fetch、pull、push 或远端写入；
- validator 会声称 delivery_state accepted；
- validator 会授予 execution authority；
- 当前文件 hash 与父级绑定不匹配；
- 测试需要 executor run 或服务重启。

## 12. 下一版本交接

v2.1 交给 v2.2 的是：

- schema minimum contract；
- validator behavior contract；
- fail-closed 校验边界。

它不能把自己当作 execution authorization、registry mutation authorization 或
delivery state acceptance。
