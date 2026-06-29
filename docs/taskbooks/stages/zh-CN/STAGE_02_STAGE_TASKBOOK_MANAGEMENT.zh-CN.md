# Stage 2 中文任务书：阶段任务书管理

```yaml id="stage-02-zh-cn-summary"
chinese_companion:
  source_document: docs/taskbooks/stages/STAGE_02_STAGE_TASKBOOK_MANAGEMENT.md
  source_sha256: b0e1a55121503df4116d9c49031eb07729858c483cc73e6c97730eca0a067876
  translation_status: companion_draft
  authority_status: planning_reference_only
stage:
  stage_id: stage_02_stage_taskbook_management
  chinese_name: 阶段任务书管理
  status: discussion_draft
```

## 1. 阶段定位

Stage 2 让 Stage Taskbook 成为可登记、可校验、可引用、并且必须绑定 Master 的
治理规划文档。

阶段任务书可以描述阶段目的、边界、证据期望和状态门就绪条件，但不能声明
accepted delivery state。

英文源文件里的 `created_from_head` 是历史创建基线，不是当前 freeze snapshot HEAD。

## 2. Master 绑定

Stage 2 要求每个 Stage Taskbook 都有 `master_taskbook_ref`。中文意思是：每个
阶段必须说明自己绑定的是哪一份 Master，而不是凭聊天记忆继续。

本阶段显式绑定 `master_taskbook_ref`，并声明 `supports_project_goal=true`。

## 3. 进入条件

进入 Stage 2 需要：

- Stage 1 产生稳定 `master_taskbook_ref`；
- Stage Taskbook 路径约定已知；
- Stage Taskbook 必填字段已定义。

不需要完整 workflow platform、executor dispatch、Web UI 或 codex-router bridge。

## 4. 退出条件

Stage 2 完成时需要：

- Stage Taskbook schema 存在；
- Stage Taskbook validator 存在；
- registry 可记录 stage id、path、hash、master ref；
- 缺少 `master_taskbook_ref` 时 fail closed；
- stage purpose 和 non-goals 必填；
- gate-readiness criteria 必填；
- version task 只能引用 registered 且 gate-ready 的 `stage_taskbook_ref`。

## 5. 启动登记模式

`bootstrap_registration_mode` = 启动登记模式。它只用于首次把 Stage 0-6 讨论草稿
纳入登记或迁移。

它必须满足：

- 另有 Version Execution Taskbook 和 Commander authorization；
- 只适用于初始 Stage 0-6 discussion drafts；
- one-time only；
- hash-bound；
- receipt-required；
- 初次迁移后不可重复；
- 不能成为未来 schema waiver；
- 不授权执行、不授权 delivery state、不授权 route、不授权 registry mutation、
  不授权 Git、不授权 memory write。

## 6. 必填字段矩阵

严格模式下，Stage Taskbook 必须包括：

- stage_id；
- stage_name；
- chinese_name；
- status；
- authority_status；
- master_taskbook_ref；
- supports_project_goal；
- stage_purpose；
- entry_criteria；
- exit_criteria；
- deliverables；
- gate_readiness_criteria；
- minimum_evidence_package；
- non_goals。

还需要 readiness contract 字段：minimum_readiness_claim、required_evidence、
gate_question、explicit_non_goal。

## 6.1 Stage 0-6 就绪契约

```yaml id="stage-0-6-readiness-contract-zh-cn"
stage_0_6_readiness_contract:
  stage_id: stage_02_stage_taskbook_management
  minimum_readiness_claim: Stage Taskbook 能表达有边界的阶段声明。
  required_evidence:
    - 阶段目标
    - 阶段边界
    - 证据期望
    - 状态门就绪条件
  gate_question: 阶段声明是否与 accepted state 保持区分？
  explicit_non_goal: 不做状态权威或 workflow platform。
```

## 7. 版本方向

Stage 2 后续版本方向：

- Stage Taskbook Schema + Validator V1；
- Stage Taskbook Registry V1；
- Stage-to-Master Binding V1；
- Stage Taskbook Gate-Readiness Contract V1。

## 8. 最小证据包

最小证据包需要：

- stage_taskbook_path；
- stage_taskbook_hash；
- master_taskbook_ref；
- supports_project_goal_summary；
- non_goals；
- gate_readiness_criteria；
- validation_result。

不能把 reviewer acceptance、delivery_state、runtime status labels 当作权威。

## 9. 非目标

Stage 2 不做 stage execution、不自动生成 stage-goal、不自动调整 master-goal、
不要求 dashboard、不授权 commit/push。

## 10. 下一步建议

Stage 1 建立 Master registration 后，再单独起草 Version Execution Taskbook，实现
最小 Stage Taskbook schema 与 validation path。
