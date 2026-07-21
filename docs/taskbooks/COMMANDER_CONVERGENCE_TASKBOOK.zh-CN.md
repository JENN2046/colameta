# Commander 收敛任务书中文 Companion

```yaml id="commander-convergence-taskbook-zh-cn-metadata"
commander_convergence_taskbook_chinese_companion:
  schema_version: commander_convergence_taskbook.zh-CN.v1
  document_type: product_and_engineering_taskbook_chinese_companion
  status: companion_review_ready
  authority_status: planning_reference_only
  source_document: docs/taskbooks/COMMANDER_CONVERGENCE_TASKBOOK.md
  source_sha256: 1b84312561d690181be81e0e5d959cd72f0a129a950ecf3b1d3fa0379d3b161b
  source_hash_status: bound_to_current_source_draft
  generated_at: 2026-07-21
  workspace: /home/jenn/src/colameta-dev
  branch_at_draft: main
  head_at_draft: 31a46757943de575d086002174c5a0e2059df17a
  implementation_authority: false
  commit_authority: false
  push_authority: false
  release_authority: false
  stable_replacement_authority: false
```

## 1. 指挥官快速结论

ColaMeta 私人 App 的七工具治理边界已经在真实非破坏性使用中证明可靠。下一个产品里程碑
不是增加第八个工具，也不是扩大权限，而是完成一次“收敛”：让现有七个工具使用同一套
决策语言，并给项目负责人一个更小、更清楚的默认界面。

本任务书把 Commander 收敛为一个契约闸口和六项工作：

1. CC-0 先把冲突场景冻结成 red→green 契约测试；
2. CC-1 让执行器续接只保留一个权威决策；
3. CC-2 明确区分已观测、草案、模拟和占位证据；
4. CC-3 把项目、运行时、Apps 可达性、外部连接器证据和任务就绪度拆开表达；
5. CC-4 让只读意图直接走状态检查，不再绕进执行包；
6. CC-5 让 Commander 默认只显示结论、关注项、下一步和操作影响；
7. CC-6 统一仓库概览中的缓存和生成文件排除规则。

这是一份规划草案。它不授权实现、执行器运行、验证运行、提交、推送、发布、部署、稳定
服务替换、服务重启、ReviewDecision、GateEvent 或 Delivery State 修改。

## 2. 用户证据与问题定义

真实私人 App 会话完整调用了七个公开工具，并且没有执行破坏性操作：

| 环节 | 工具 | 实际结果 |
| --- | --- | --- |
| 项目发现 | `list_registered_projects` | 可以找到已登记项目。 |
| 项目分析 | `analyze_project_state` | Git、计划、Runner 和执行器事实有用。 |
| Commander | `render_commander_app` | 面板成功渲染，但默认信息过多。 |
| 连接器检查 | `get_apps_connector_smoke_packet` | Apps 调用已证明可达，但外部 closeout 证据仍不完整。 |
| 治理工作流 | `run_mcp_workflow` | 生成了只读 thin-loop 草案，但普通只读意图仍被带入执行型契约。 |
| 验证管理 | `manage_validation_run` | 三条命令被固定在需要确认的 `preview_id` 后。 |
| Git 评审 | `manage_git` | 评审信息足够，但缓存文件污染仓库概览。 |

本轮没有发生执行器运行、验证运行、文件修改、ReviewDecision、GateEvent、Delivery State 修改、
commit 或 push。验证流程正确停在 `can_run=true`、`requires_confirmation=true` 的确认边界。

核心产品结论是：

> 治理和防误操作已经可信，但决策语义和信息架构还没有收敛成轻量 Commander。

这份会话报告属于用户提供的第一手产品证据。下列当前源码锚点独立支持任务书识别出的实现风险，
但它们不等于已经复现了线上 ChatGPT 会话：

| 问题 | 当前源码锚点 |
| --- | --- |
| continuation 推荐在多个位置重复推导 | `runner/executor_session.py` 的 `classify_executor_session_head_mismatch`、`get_continuation_decision`，以及 `runner/core_orchestrator.py` 的 `_thin_loop_executor_session_guidance` |
| Draft 对象可能出现形似真实执行的模拟值 | `runner/core_orchestrator.py` 的 `_thin_loop_reset_draft_task_evidence`、`_thin_loop_apply_draft_seed` |
| Connector closeout 被压缩为 `ready` 或 `needs_attention` | `runner/runtime_observability.py` 的 `build_apps_connector_closeout_packet` |
| Commander 顶部状态和首次 payload 聚合了过多维度 | `runner/mcp_server.py` 的 Commander manifest 构造逻辑 |
| 仓库概览缺少其他模块已经使用的部分缓存排除规则 | `runner/source_review_bridge.py`、`runner/file_policy_rules.py` 和 `runner/work_item_governance/source_binding.py` |

## 3. 产品目标

收敛完成后，项目负责人在 Commander 首次响应中，不需要理解内部治理术语，就能回答四个问题：

1. 项目健康吗？
2. 具体哪一项需要关注或阻断了进度？
3. 推荐下一步是什么？
4. 这个动作是读取、预览、运行、写入、提交、推送，还是会改变外部系统？

详细治理对象仍然保留，供展开诊断和审计，但不能继续占据默认决策界面的主体。

## 4. 非目标

- 不增加第八个 Commander 公开工具。
- 不削弱 preview ID、确认门、权限检查、private-auth 检查、Work Item Gate、Git gate 或稳定
  替换规则。
- 不把项目健康、本地运行时、Apps 可达性、外部连接器 closeout、验证就绪和交付就绪重新
  压成一个布尔值。
- 本轮不重做整套视觉语言，也不替换现有 widget 技术。
- 不引入新的工作流引擎、状态库、任务书平台或外部服务。
- 不把草案或模拟证据当成执行证明。
- 本任务书本身不允许修改稳定服务、外部连接器配置、OAuth、tunnel、DNS 或 provider 配置。
- 本任务书本身不允许发布、打 tag、release 或 deploy。

## 5. 目标产品契约

### 5.1 Commander 紧凑摘要

每个公开 Commander 流程都应提供一个小型决策投影，形状类似：

```json
{
  "project_health": "healthy",
  "primary_attention": {
    "domain": "external_connector_evidence",
    "status": "unverified",
    "blocks_current_task": false
  },
  "recommended_next_action": {
    "label": "检查项目状态",
    "tool": "analyze_project_state",
    "effect": "read"
  },
  "authority": {
    "state": "not_required_for_read",
    "authorized": true,
    "authorization_source": "read_only_tool_contract"
  },
  "details_available": true
}
```

实现审查时可以调整精确字段名，但“回答四个用户问题”和“不丢失各维度事实”是硬验收要求。

### 5.2 操作影响词汇

私人 App 暴露的推荐动作必须使用一套统一的用户可见词汇：

```text
read = 读取
preview = 预览
run = 运行
write = 写入
commit = 提交
push = 推送
external_change = 外部状态变化
```

`requires_confirmation` 继续作为独立事实存在。只读动作不能写成“运行/写入”，预览也不能
描述成已经完成的执行。

授权状态也必须是首屏一等字段，不能藏进诊断详情。`requires_confirmation` 不等于动作已经获得
授权。当前动作级授权缺失时，任何 mutation effect（`run`、`write`、`commit`、`push` 或
`external_change`）只能推荐只读/预览步骤或把请求交回 Operator 授权，不能把可复制的写操作
调用描述成当前已获准的下一步。

### 5.3 证据来源词汇

凡是可能被误认为执行或审查证据的对象，都必须带上：

```text
evidence_kind = observed | draft | simulated | placeholder
evidence_subject = execution | validation | review | hash_binding | read_only_observation
subject_requires_execution = true | false
subject_operation_completed = true | false
execution_performed = true | false
eligible_for_acceptance = true | false
```

中文含义：

- `observed`：实际观测到的事实；
- `draft`：尚未执行的草案；
- `simulated`：为了演示结构而模拟的结果；
- `placeholder`：等待填写的占位内容。

只有具有真实完成操作依据的 `observed` 才能设置 `execution_performed=true`。Draft 模式不能
生成看起来像真实观测结果的无限定 `executed`、`passed` 或退出码为 0 的主张。

Fail-closed 真值表如下：

| `evidence_kind` | Subject 规则 | `execution_performed` | `eligible_for_acceptance` | 规则 |
| --- | --- | --- | --- | --- |
| `draft` | 任意 subject | `false` | `false` | 永远没有执行，也不能用于验收。 |
| `simulated` | 任意 subject | `false` | `false` | 预期/示例结果永远不是执行证明。 |
| `placeholder` | 任意 subject | `false` | `false` | 缺失或等待 Operator 填写的内容永远不能验收。 |
| `observed` | 要求 execution，但尚未完成 | `false` | `false` | 不能证明要求的执行。 |
| `observed` | 非执行 subject 已完成 | `false` | 可以为 `true` | 只允许已完成的 review、hash binding 或只读观测，并要求全部适用的来源、task/version、digest/binding、完整性、新鲜度及权威 validator 通过。 |
| `observed` | Execution 已完成，但证明不完整/冲突 | `true` | `false` | 任一适用检查缺失或冲突时仍不可验收。 |
| `observed` | Execution 已完成且证明完整 | `true` | 可以为 `true` | 只有全部绑定和现有权威 validator 通过时才允许；eligible 仍不等于已经 accepted。 |

`evidence_subject`、`subject_requires_execution` 和 `subject_operation_completed` 必须由 validator
推导，不能信任调用方自报。输入 envelope 可以携带 `claimed_*` 值用于比对，但权威 validator
必须根据绑定对象/path、schema 和权威 operation/binding record 得出返回值。固定 v1 映射是：
`execution`、`validation` 必须要求 execution；`review`、`hash_binding`、
`read_only_observation` 不要求 execution。Operation 是否完成必须来自绑定证据，不能来自请求中的
布尔值。未知 subject、path/schema mismatch、subject downgrade、把执行对象伪装成非执行，或
completion mismatch，都必须设置 `eligible_for_acceptance=false` 并让 acceptance-aware 路径
fail closed。

未知 kind、新契约要求但缺失的 provenance，以及彼此冲突的 provenance 都必须 fail closed。现有
legacy provided-mode 对象可以为兼容而继续读取和解析，但必须报告
`provenance_status=legacy_unclassified`、`eligible_for_acceptance=false`，并且不能创建新的
acceptance、ReviewDecision、GateEvent 或 Delivery State mutation。Legacy 对象要进入新的
acceptance-aware 路径，必须先通过版本化 provenance envelope 重新绑定并由当前 validator 验证。

## 6. 工作项

### CC-0 — 契约 Fixture 冻结

优先级：`P1 前置闸口`

问题：在 CC-1 和 CC-2 修改行为前，必须只用一套共享事实把当前相互冲突的推荐和草案证据歧义
冻结下来。

要求：

- 建立不读取 ignored runtime/private state 的确定性 fixture。
- 同一个 continuation fixture 应按需复用到 session decision、Web/status、analyze-state、
  invocation-preview 和 thin-loop 断言。
- 同一个 provenance fixture 应按需复用到 draft generation 以及权威 receipt、validation-truth、
  review-feedback validator。
- 实施过程中可以记录修复前的红灯，但最终工作区和 closeout 不能留下失败测试。
- CC-1 和 CC-2 完成后，必须让同一批 fixture 全部转绿。

强制 fixture：

| Fixture | 事实 | 最终必须结果 |
| --- | --- | --- |
| `CONT-01` | HEAD 相同、provider/identity 匹配、resume support 已验证、无阻断 | 可以推荐 `resume`。 |
| `CONT-02` | 历史会话已完成且 idle，当前 HEAD 已前进，工作区干净 | `start_new`，禁止 resume。 |
| `CONT-03` | HEAD mismatch 且操作正在或可能正在运行 | `human_review`，resume/start 都禁止。 |
| `CONT-04` | HEAD mismatch 且 operation/job/run/Runner/worktree 事实不完整 | `inspect_evidence`，resume/start 都禁止。 |
| `CONT-05` | 没有 session、provider mismatch、identity 缺失或 resume unsupported | 带精确原因的 `start_new`，不能假装可 resume。 |
| `PROV-01` | Draft seed 包含 allowed files 和 validation commands | Packet 可以为未来工作 ready，但 receipt 必须仍是 not-run、不可验收。 |
| `PROV-02` | Draft 含默认 review/hash placeholder | 占位内容必须明确标记且不可验收。 |
| `PROV-03` | simulated/placeholder evidence 进入 acceptance-aware 路径 | Fail closed，不能当作 observed evidence。 |
| `PROV-04` | 已完成且完整绑定的 observed review/hash/read-only evidence | `execution_performed=false`；可以 eligible，但不能自动推出 acceptance。 |
| `PROV-05` | 已完成且完整绑定的 observed execution/validation evidence | `execution_performed=true`；可以 eligible，但不能自动推出 acceptance。 |
| `PROV-06` | 调用方把 execution/validation 降级成 non-execution、修改 subject/path 或自报未证明的 completion | Fail closed，`eligible_for_acceptance=false`。 |

Red→green 规则：初始红灯只属于实施过程证据。任何强制 fixture 或既有回归测试仍失败时，首刀
都不能 closeout、commit 或晋升。

### CC-1 — 统一执行器续接决策

优先级：`P1`

问题：执行器 session 分析已经存在 HEAD mismatch 分类器，但不同工具仍各自推导推荐动作，
导致同一个旧会话既可能得到 `resume`，又可能得到 `start_new`。

要求：

- 在 `runner/executor_session.py` 定义唯一的纯 continuation-decision builder；其他 surface 只能
  消费，不能重新推导。
- 接受一个明确 fact bundle，包含 session/current HEAD、operation-running、job、latest run/claim、
  Runner/version、worktree、provider、identity 和 resume-support 事实。
- HEAD mismatch 分类器和 fact bundle 必须成为权威输入。
- 对象至少包含 `classification`、`resume_allowed`、`start_new_allowed`、
  `recommended_action`、`reason`、`severity` 和 `decision_source`。
- Web/status、`analyze_project_state`、thin-loop packet、executor invocation preview 和 Commander
  摘要只能投影同一个对象，不能在各自收集不同事实后再次自行判断。
- 证据不完整或可能存在活动操作时，必须保留更严格的结论。

Canonical v1 枚举：

```text
classification = no_session | resume_eligible |
  completed_idle_stale_session | active_operation_head_mismatch |
  head_evidence_incomplete | provider_or_identity_mismatch | resume_unsupported
recommended_action = resume | start_new | inspect_evidence | human_review
```

任何 surface 都不能用 `null`、自由同义词或第二个 recommendation 字段覆盖
`recommended_action`。冲突优先级必须 fail closed：

1. active 或可能 active 的 mismatch -> `human_review`；
2. 对比/运行证据不完整 -> `inspect_evidence`；
3. completed stale、无 session、provider/identity mismatch 或 resume unsupported -> 带精确原因的
   `start_new`；
4. 只有完整验证的同一会话事实 -> `resume`。

验收样例：

| 情况 | 必须得到的决策 |
| --- | --- |
| HEAD 相同、provider 和身份匹配、无阻断 | 可以推荐 resume。 |
| 历史会话已完成且 idle，当前 HEAD 已前进，工作区干净 | 必须 start new，不允许自动 resume。 |
| HEAD 不一致且操作可能仍在运行 | 自动 resume 和自动 start 都阻断，要求人工判断。 |
| HEAD 对比证据不完整 | 不猜测，明确返回证据阻断。 |

### CC-2 — 证据分型与草案真实性

优先级：`P1`

问题：thin-loop draft 外层说明“没有执行”，但内部可能出现模拟的 `executed`、`passed` 和
`exit_code=0`。外层边界虽然正确，内部语义仍容易被用户、模型或后续代码误读。

要求：

- 对执行 receipt、验证结果、review feedback 草案、hash 和占位字段加入证据来源标记。
- 契约必须绑定 `runner/local_execution_receipt.py`、`runner/validation_truth.py` 和
  `runner/review_feedback_schema.py` 的当前权威 validator；只加展示标签不算完成。
- Subject、execution requirement 和 completion 必须从绑定对象/path/schema 及权威记录推导，
  不能信任 caller flag。
- Draft 输入生成必须明确保持“未执行、未验证”。
- 如果示例需要展示预期结果，必须放进单独命名的 `simulated_expectation` 或 schema example，
  并明确不能用于 acceptance。
- `NEEDS_FIX` 等默认 review 内容必须标成示例，或从已观测摘要中移除。
- 公开投影必须把已观测事实和草案对象分区。

为保持兼容，首刀使用版本化的 transport-level sibling `evidence_provenance` envelope，不替换现有
v1 对象字段，也不改变标量 hash 字段的形状。Envelope entry 指向具体对象或 JSON field path，
记录 evidence subject、该 subject 是否要求 execution、subject operation 是否完成、evidence
kind、execution fact、eligibility fact 和已验证绑定状态。Review hash 继续保持 SHA-256 字符串；
它的 provenance 是 sibling entry，不改成 hash object。缺少 envelope 的现有 legacy
provided-mode input 标记为 `legacy_unclassified`；它们可以继续读取/解析，但重新绑定并验证前
不能产生新的 acceptance 或状态修改。

### CC-3 — 多维健康与就绪状态

优先级：`P1`

问题：`needs_attention` 对 connector closeout 来说可能是正确结论，但放到 Commander 顶部后，
看起来像项目或本地运行时发生故障。

要求：

- 分别保留这些状态：
  - 项目健康；
  - 本地运行时健康与代码新鲜度；
  - Apps 工具调用可达性；
  - 外部 connector/tunnel 证据；
  - 当前任务就绪度；
  - 在相关场景中的交付/发布就绪度。
- 缺少外部 closeout receipt 不能静默降低项目健康状态。
- 顶部摘要必须指出受影响的具体维度，以及它是否阻断当前任务。
- `ready`、`needs_attention`、`blocked` 可以继续作为维度状态，但单一总状态不能抹掉健康的
  component 事实。

必须覆盖的矩阵包括：项目/运行时健康但外部证据未验证、本地运行时 degraded、Apps 调用不可达、
以及与 connector closeout 无关的任务级阻断。

### CC-4 — 只读意图路由

优先级：`P1`

问题：普通用户可能用空执行数组或不支持的 review value 表达“我只想看看”。系统虽然安全地
拒绝执行，但已经先生成了一大包执行型对象。

要求：

- 在构建 thin-loop 执行包之前识别明确的 inspect/status/review-only 意图。
- 将它路由到现有 project-status 或 source-observation 路径。
- 对不寻求执行的任务，不生成 execution receipt、Codex execution packet、allowed-file blocker
  或 validation-command blocker。
- 收到不兼容字段时，返回简短解释和可直接复制的安全请求形状。
- 执行意图继续保持严格：可运行 packet 仍必须具备有界文件、命令、验证、task tier 和适用权限门。

### CC-5 — Commander 默认紧凑、详情后置

优先级：`P2`

问题：Commander 默认结果携带很多有用但次要的 section，导致当前决策不突出。

要求：

- 私人 App 默认使用紧凑摘要。
- 默认界面聚焦项目健康、主要关注项、推荐下一步、操作影响和是否需要确认。
- stable cadence、submission readiness、domain projection、profile 详情、并行 Stage 控制、fallback
  transport 和 authority diagnostics 放到展开区或单独详情读取。只有详细 authority diagnostics
  可以后置；强制 authority summary 必须继续留在默认首屏。
- 用户下一次调用需要的 `preview_id`、`run_id` 等 continuation ID 必须保留。
- 定义并测试有界公开 payload，不能截断需要复制的确认绑定请求。
- 公开工具数量继续严格保持七个。

### CC-6 — 统一仓库概览排除规则

优先级：`P2`

问题：source review、execution overlay 和 repo overview 没有完整复用同一套缓存/生成文件排除
规则，缓存文件会消耗有限的文件树名额。

要求：

- 建立可复用的缓存/生成文件排除策略。
- 仓库概览和其他语义相同的用户可见文件清单共同使用它。
- 至少覆盖 `.ruff_cache`、`.pytest_cache`、`__pycache__`、`.mypy_cache`、虚拟环境、
  build/dist、egg-info、coverage 以及其他已经在仓库规则中拒绝的语言/vendor cache。
- 在诊断中区分“安全敏感拒绝”和“低价值缓存排除”，但默认文件树必须同时排除两者。
- 被排除的文件不能消耗 `max_files`。

## 7. 实施顺序与第一刀

```text
CC-0 建立当前问题的契约测试
  -> CC-1 统一续接决策
  -> CC-2 证据分型
  -> CC-3 多维状态
  -> CC-4 只读意图路由
  -> CC-5 紧凑优先投影
  -> CC-6 统一排除规则与文档收口
```

CC-0 是可以独立审计的 red→green 契约闸口，不是交付失败测试的许可。CC-1 至 CC-3 是语义
基础；CC-4 和 CC-5 消费这些统一语义；CC-6 在基线 fixture 存在后可以相对独立实施。

### 7.1 第一实施刀 — `CC-S01`

```yaml id="commander-convergence-first-slice-zh-cn"
first_implementation_slice:
  slice_id: CC-S01
  status: reviewed_scope_ready_for_authorization
  includes:
    - CC-0_contract_fixture_freeze
    - CC-1_canonical_executor_continuation_decision
    - CC-2_evidence_provenance_and_draft_truthfulness
  defers:
    - CC-3_multi_axis_health_and_readiness
    - CC-4_read_only_intent_router
    - CC-5_compact_first_commander_information_architecture
    - CC-6_shared_repository_overview_exclusion_policy
  implementation_authority: false
  validation_run_authority: false
  commit_authority: false
  push_authority: false
  stable_replacement_authority: false
```

首刀结果：

- 在共享决策源消除 resume/start-new 冲突；
- 通过权威验证语义让 draft/simulated/placeholder 明确保持未执行、不可验收；
- CC-0 全部 fixture 和既有回归测试最终转绿。

首刀明确不改顶层 `needs_attention` 模型、只读意图路由、Commander 信息架构、缓存过滤、工具
数量、稳定运行时、连接器配置或视觉设计。首刀唯一允许的 Commander projection 变化，是为了
证明 CC-1/CC-2 而透传 canonical decision、provenance 和 authority 字段。

供未来精确实施闸口审查的主要候选文件面：

```text
runner/executor_session.py
runner/web_console.py
runner/core_orchestrator.py
runner/thin_governed_loop.py
runner/local_execution_receipt.py
runner/validation_truth.py
runner/review_feedback_schema.py
runner/mcp_server.py
runner/commander_projections.py
tests/test_executor_session_head_mismatch.py
tests/test_thin_governed_loop.py
tests/test_local_execution_receipt.py
tests/test_validation_truth.py
tests/test_review_feedback_schema.py
tests/test_mcp_runtime_observability.py
tests/test_mcp_commander_exposure_profile.py
```

这只是经过审查的候选面，不是当前写入授权。如果实现证明必须执行持久化 schema migration，
或触碰候选面之外的任何文件，必须停下重新审查并绑定范围，不能自动扩权。

首刀专用验收门：

| 闸口 | 必须证明的结果 |
| --- | --- |
| CC-0 红灯记录 | 可以证明修复前冲突被捕获，但最终树中不能保留故意失败测试。 |
| CC-1 跨 surface 一致 | `CONT-01` 至 `CONT-05` 在 session、Web/status、analyze、invocation、thin-loop 和 Commander 中得到同一个 canonical decision。 |
| CC-1 fail-closed 优先级 | active/uncertain 证据不能被 cache preference、provider preference 或后续 projection 降级。 |
| CC-2 provenance envelope | Sibling envelope 已版本化、绑定路径、不改变标量 hash 形状，并按需通过 Commander projection。 |
| CC-2 acceptance 负向 | draft、simulated、placeholder、unknown、conflicting、stale、绑定不完整、subject downgrade、path mismatch 或 completion mismatch 证据始终不可验收。 |
| CC-2 非执行正向 | 完整验证且已完成的 review/hash/read-only evidence 可以在 `execution_performed=false` 时 eligible；execution/validation subject 不能走这条分支。 |
| CC-2 兼容性 | 现有 v1 对象保持可读/可解析，不会被静默重标为 provenance-verified，重新绑定前不能创建新的 acceptance 或状态修改。 |
| 完整回归 | Targeted modules、Commander 七工具契约、compileall、完整 pytest、self-hosting smoke 和 `git diff --check` 通过。 |

只有上表全部转绿、公开工具数仍为七、CC-3 至 CC-6 没有被夹带进范围，并且 closeout 同时记录
新语义和兼容性结果，`CC-S01` 才能判为本地完成。本地完成仍不授权 commit、push、稳定替换、
重启或真实私人 App 写操作。

## 8. 预计实现范围

下列路径预计与实现有关，但仍需未来单独授权和实现前源码检查：

```text
runner/executor_session.py
runner/web_console.py
runner/core_orchestrator.py
runner/thin_governed_loop.py
runner/local_execution_receipt.py
runner/validation_truth.py
runner/review_feedback_schema.py
runner/runtime_observability.py
runner/commander_projections.py
runner/mcp_server.py
runner/source_review_bridge.py
runner/file_policy_rules.py
tests/test_executor_session_head_mismatch.py
tests/test_thin_governed_loop.py
tests/test_local_execution_receipt.py
tests/test_validation_truth.py
tests/test_review_feedback_schema.py
tests/test_runtime_observability.py
tests/test_mcp_runtime_observability.py
tests/test_mcp_commander_exposure_profile.py
docs/commander-public-response-minimization.md
docs/web-gpt-service-entrypoint.zh-CN.md
docs/ONBOARDING.md
docs/ONBOARDING.zh-CN.md
```

这只是预计影响面，不是 allowed-file 写入清单。真正实施前必须审查并绑定精确文件范围。

## 9. 验收矩阵

| 闸口 | 必须证明的结果 |
| --- | --- |
| 续接一致性 | 同一 fixture 在 session、Web/status、analyze、thin-loop、invocation preview 和 Commander 中得到相同推荐和权限。 |
| 活动 mismatch 安全 | 活动中或证据不确定的 HEAD mismatch 永远不会自动 resume 或自动 start。 |
| 草案真实性 | Draft 不包含已观测执行/通过主张，也不能满足 acceptance evidence。 |
| Provenance schema 权威 | Receipt、validation-truth 和 review-feedback validator 执行真值表；只加 projection 标签不能让证据 eligible。 |
| 只读路由 | 明确 inspect/review-only 的任务返回 project-status 路径，不生成 execution packet。 |
| 严格执行契约 | 可运行 packet 仍拒绝空文件、缺少验证、无效 tier 和不足权限。 |
| 状态分离 | 项目/运行时健康但外部证据缺失时，健康维度仍显示健康，证据缺口单独表达。 |
| 紧凑投影 | Commander 默认输出回答四个用户问题，始终保留强制 authority summary，拒绝把未授权 mutation 作为可立即调用的下一步，并移除次要诊断清单。 |
| 续接标识保留 | `preview_id`、`run_id` 和确认绑定 payload 在最小化后仍完整。 |
| 文件树卫生 | 缓存/生成路径不出现，也不占用 `max_files`。 |
| 七工具不变量 | 私人 Commander profile 继续只暴露现有七个工具。 |
| 私人服务与认证 | 现有 service-mode/private-auth 正向与反向路径继续有覆盖。 |
| 完整回归 | targeted tests、compileall、完整 pytest、self-hosting smoke 和 `git diff --check` 通过。 |

## 10. 完成定义

只有同时满足以下条件，本地 Commander 收敛实现才能判为 ready：

- CC-0 和六个收敛工作项全部通过各自验收；
- 相同事实在任何 surface 都不会产生互相冲突的 session 建议；
- 草案/模拟对象不会被误认为已观测执行证据；
- 顶层展示明确指出状态维度及其对当前任务的影响；
- 明确只读任务不会构建执行包；
- Commander 默认响应已经紧凑，但下一步所需 ID 和可复制请求仍完整；
- 仓库概览排除低价值缓存和生成文件；
- 公开工具数继续为七；
- 在批准的本地环境中通过 targeted 和完整回归验证；
- 用户与运维文档已经更新到最终契约。

本地 ready 不等于稳定服务 ready。稳定替换和真实私人 App 复验需要另行绑定精确提交并授权。

## 11. 风险与控制

| 风险 | 控制措施 |
| --- | --- |
| 做减法时意外削弱治理 | 只改投影和路由，不放松 authority gate；保留负向测试。 |
| 新总状态再次掩盖 component 事实 | 保留类型化维度状态和当前任务影响字段。 |
| 旧 consumer 依赖大型 payload | 紧凑优先只应用于 Commander 投影；advanced/maintainer 详情除非另行审查，否则保留。 |
| 证据分型破坏旧 fixture | 使用版本化 schema/投影，并增加兼容性测试。 |
| session 修复改变执行行为 | 广泛回归前覆盖同 HEAD、历史 stale、活动 mismatch、证据不全和 provider mismatch。 |
| payload 最小化丢失 continuation ID | 使用明确 operational-field allowlist 和边界测试。 |
| 本地修好后被误认为 stable 已修好 | 分开报告本地与 stable runtime；要求精确提交替换证据。 |

## 12. 交付与授权边界

这份任务书不授权任何实现或交付动作。未来可以单独授权“有界本地实现和测试”。commit、push、
PR、merge、稳定替换、服务重启、release、deploy 和真实私人 App 验证仍然是互相独立的授权步骤。

当前规划结论：

```yaml id="commander-convergence-planning-outcome-zh-cn"
planning_outcome:
  taskbook_status: reviewed_first_slice_scoped
  recommended_next_gate: CC-S01_bounded_local_implementation_authorization_review
  may_implement_from_this_document_alone: false
  may_commit_from_this_document_alone: false
  may_replace_stable_from_this_document_alone: false
```

任务书独立审查收口：

```yaml id="commander-convergence-taskbook-review-closeout-zh-cn"
review_closeout:
  safety_and_authority_review: pass
  technical_implementability_review: pass
  usability_and_slice_clarity_review: pass
  remaining_blocker_high_medium_findings: 0
  first_slice: CC-S01
  first_slice_scope_confirmed:
    - CC-0
    - CC-1
    - CC-2
  implementation_authorized_by_review: false
```

## 13. 技术词汇表

| 英文术语 | 中文解释 |
| --- | --- |
| Commander convergence | Commander 收敛：不增加能力面，统一状态、决策和默认展示。 |
| continuation decision | 执行器会话是恢复旧会话还是启动新会话的统一决策。 |
| projection | 投影：从完整工程数据中提取给某类用户看的有界视图。 |
| evidence provenance | 证据来源：说明对象是实际观测、草案、模拟还是占位。 |
| intent router | 意图路由：先判断用户要查看还是执行，再选择正确工作流。 |
| closeout | 收口验收：证明某一明确范围的证据已经闭合。 |
| acceptance | 验收接受；不能由草案或模拟结果自动推出。 |

## 14. 已知翻译边界

- 本中文文件是英文源任务书的完整中文伴随版本，不替代未来可能绑定的英文源文件 hash 权威。
- 字段名、状态值和工具名保留英文，以避免实现时产生语义漂移。
- 如果后续英文源文件修改，中文 companion 必须同步更新并重新检查；冲突时状态应标记为
  `translation_conflict`，不能靠中文版本静默扩大范围或授权。

## 15. 本地实施授权、审查修复与 A2 收口

任务书本身仍不构成实施授权。Jenn 后续分别对 `CC-S01`、`CC-S01-A1` 和
`CC-S01-A2` 发出了明确的有界本地实施授权。这些授权只覆盖本地实现与验证，不授权 commit、
push、PR、merge、稳定替换、重启、发布或部署。

`CC-S01-A2` 为每次请求增加了一份 provider-aware continuation snapshot，以及项目级 POSIX
共享/独占 operation lease。Web v2、Analyze、Thin-loop、Commander、agent dispatch、MCP
executor status、run-once、bounded execution、Codex 和 OpenCode 现在消费同一份已捕获的
continuation facts，不再各自重新推导续接建议。Lease 直接持有既有 canonical project-root
目录描述符，因此只读 snapshot 采集不会在项目内创建文件。

第一次 CC-S01/A1/A2 合并收口审查随后发现四项使初始 ready 声明失效的问题：provider projection
可能放宽已经捕获的 resume capability 事实、中文 companion hash 已漂移、非字符串
`evidence_kind` 可能抛异常而不是 fail closed，以及版本化 provenance envelope 可以遗漏
validator-owned subjects。本次有界本地修复已经保留显式 false capability、拒绝畸形 evidence
kind、要求 provenance subject 完整覆盖，让 CONT-01 到 CONT-05 依次通过 Session、Analyze、
Thin-loop、Web、Invocation 和 Commander 投影矩阵，并在用户和运维文档中说明 snapshot/lease
行为。最终顺序验证和独立复审现已通过，构成下面 ready 状态的证据。

本地收口证据：

```yaml id="commander-convergence-cc-s01-a2-local-closeout-zh-cn"
cc_s01_a2_local_closeout:
  status: ready
  independent_reviews:
    technical: pass
    safety: pass
    usability_and_test_evidence: pass
  remaining_p0_p1_p2_findings: 0
  targeted_regression: 244_passed_84_subtests
  full_pytest: 1915_passed_2_skipped_139_subtests
  self_hosting_smoke: passed
  compileall: passed
  ruff_check: passed
  diff_check: passed
  final_project_and_venv_bytecode_count: 0
  commit_authorized: false
  push_authorized: false
  stable_replacement_authorized: false
```
