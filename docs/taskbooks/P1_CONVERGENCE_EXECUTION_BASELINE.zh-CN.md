# P1 收敛执行基线

```yaml id="p1-convergence-execution-baseline-zh-cn-metadata"
p1_convergence_execution_baseline_zh_cn:
  document_type: chinese_companion
  source_document_ref: docs/taskbooks/P1_CONVERGENCE_EXECUTION_BASELINE.md
  source_sha256: 0ca6da39880c7da6692dbf8831866108f8bf8fbb3b64238c45fb24723069c558
  source_schema_version: colameta.p1_convergence_execution_baseline.v2
  translation_status: companion_draft
  authority_status: planning_reference_only
  source_authority_boundary: english_source_remains_authoritative
  revision: 9
  created_at: 2026-07-24
  reconciled_at: 2026-07-25
  source_status: p1_e_implementation_verified_fresh_development_acceptance_pending
  known_translation_gaps: []
```

## 决定

P1 是一次大刀阔斧的收敛计划，不是一串缓慢的表面修补。公开 Commander 契约固定为
**九个工具**：原来的七个，加上 `review_manifest` 与 `read_result_artifact`。本 v2
基线只在“已经实现的 typed-read 扩展”这一点上取代旧的七工具冻结；P1 期间不增加
第十个公开工具。

计划按顺序解决四件事：过大的 MCP 组合根、没有统一生成的当前事实产物、彼此割裂的
Stage 7--9 preview，以及 ChatGPT 与本地 Codex 体验过度相似的问题。旧路由暂时保留
是为了兼容，不是为了拖延。

## 不可谈判的执行规则

1. 每个批次要么交付完整垂直切片，要么不交付；不能留下长期半拆模块、双重 authority
   或伪装为兼容性的重复实现。
2. `mcp_server.py` 只保留 HTTP/JSON-RPC transport、认证与 policy 选择、tool registry、
   response envelope 组合和明确的 legacy routing。领域行为必须进入 `runner/mcp_*.py`。
3. P1 内公开九工具契约冻结。新能力优先进入已有 typed tool、`run_mcp_workflow` 兼容层，
   或 loopback advanced/local-Codex 表面。
4. runtime facts 是生成的 snapshot，绝不静默改写历史。历史 receipt、受保护 taskbook 和
   stable-replacement evidence 始终只是不可变输入。
5. Stage 7--9 只读/preview。缺少 hash、context、authority 或 observation evidence 时，
   必须硬阻断，不能猜。
6. 本地测试绿不等于 release。stable replacement、Connector cutover、OAuth、tunnel、DNS、
   push、tag、publish 和公开提交始终是单独明确的决定。

## 已经获得的基础

- public workflow、validation 与 Git 表面的 context-bound mutation/confirmation 检查；
- 区分 historical/current/freshness 的 canonical state projection；
- 明确“不要启动/运行 executor”的路由与回归覆盖；
- manifest-bound 独立读取；以及
- typed、只读的大结果分页续读，已在真实 ChatGPT development Connector 中验收，
  且不依赖 `resources/read`。

这些是地基，不是继续拖延剩余工作的理由。

## P1-A —— 打碎 MCP 单体并收窄公开 Workflow

### 目标

把 `runner/mcp_server.py` 从约 17.6k 行降至 **不超过 9k 行**。它只拥有 transport、
registry、policy 和 compatibility composition；已抽出的 family 不得仍在其中保留直接的
领域实现。

### 必做工作

1. 先生成并提交 `P1-A0` migration map：把当前每个 `run_mcp_workflow.workflow` 值分类为
   `public-typed`、`public-compatibility`、`local-advanced` 或 `retired-with-handoff`。每项都
   必须写明 owner module、精确输入/输出契约、authority scope 和回归测试。
2. 把 workflow registration/schema、response shaping、Commander projection、manifest/artifact
   reads 和 workflow-family dispatch 抽到聚焦的 `runner/mcp_*.py` 模块。已有模块必须复用，
   不能再包一层重复实现。
3. 公开 `run_mcp_workflow` 变成紧凑的 compatibility/orchestration tool。新的 ChatGPT 指引
   先用 typed tools；legacy workflow 要么走唯一有边界的兼容路径，要么返回可复制的
   local-Codex handoff，不能藏第二个实现。
4. 公开九工具保持精确不变：Git 在 `manage_git`，validation 在 `manage_validation_run`，
   independent review 在 `review_manifest`，大结果恢复在 `read_result_artifact`。

### 退出闸口

- `mcp_server.py` 不超过 9k 行；
- 每个迁移 workflow 只有一个权威实现和一个 migration map entry；
- 旧入口/公开 typed 入口的等价性与拒绝路径都有目标测试；
- public schema、scope、preview/apply binding 和 context binding 均不扩大；
- full pytest、self-hosting smoke、受影响 Python 的 compileall、Ruff 与 `git diff --check`
  全部通过。

### 已采用的 P1-A 组合边界

- `runner/mcp_tool_catalog.py` 负责声明式 MCP 输入/输出 schema、tool annotations，以及
  Stage-parallel/context-binding 的 schema 片段。
- `runner/mcp_server.py` 只组合该 catalog、追加既有 Work Item definitions，并应用冻结的
  exposure-profile 检查；它不再重新实现 catalog 数据。
- `runner/commander_widget.html` 是由 `runner/commander_widget.py` 加载的 packaged
  application data；原有 `ui://colameta/commander/v1.html` URI 与 widget response bytes
  保持稳定。
- `runner/mcp_commander_app.py` 负责 Commander/ChatGPT 的 product domain：manifest、
  readiness/product-console projection、submission-evidence view 与 client-flow 组装。
  `MCPPlanningBridgeServer` 通过继承使用该 domain，同时保留 transport、registry、policy
  和明确的 compatibility composition。原有 server-module dependency-injection seam 被刻意
  保留并有测试，ownership 移动不改变既有 focused integration behavior。

这只是内部 ownership 拆分；不改变九个公开工具、scope、authorization boundary、connector
configuration 或 release authority。

## P1-B —— 把当前事实做成真正的产品产物

### 目标

`canonical_project_state` 是 current-facts artifact 的唯一组合输入。Git、Runner、runtime
和 connector collector 仍拥有各自观察来源；canonical projection 不能冒充这些来源。

### 必做工作

1. 在 `.colameta/reports/current-facts/` 生成脱敏、版本化的 Markdown/JSON snapshot。每份
   snapshot 都记录 `observed_at`、每个 source 的 observation state、freshness conclusion、
   canonical-state digest，以及它不授予 authority 的声明。
2. 通过已有只读 typed result/artifact 路径返回 snapshot，不增加公开工具。对 tracked docs
   的更新只能走明确的 docs preview/apply，且绝不能覆盖历史 receipt 或受保护 taskbook。
3. 为 fresh、stale、partial、not-observed 及冲突的 Git/Runner/runtime/connector evidence
   增加确定性 fixture。验证 projection 不携带 secret-like 字段或 ignored raw runtime 内容。

### 退出闸口

- 相同 fixture 输入产出字节完全一致的 current-facts artifact；
- 每份 artifact 有 source observation timestamps、canonical digest 和明确 freshness/authority
  boundary；
- stale 或缺失的 external evidence 只能得到 `freshness_required` 或 `partial`，绝不能生成
  healthy/release conclusion；
- artifact generation 未经独立确认的 docs preview/apply 不得写入 tracked documentation。

### 已采用的 P1-B current-facts 边界

- `runner/mcp_current_facts.py` 负责既有 `run_mcp_workflow` compatibility surface 背后的有界
  `current_facts` state machine：`inspect`、`preview` 和 context-bound `apply`。公开九工具保持不变。
- `runner/current_facts_artifact.py` 只接收 `canonical_project_state`，拒绝 secret/path-like key，并渲染
  一对脱敏 JSON/Markdown 文件，包含精确 canonical、semantic 与 snapshot SHA-256。它构建 artifact 时
  不读取 raw runtime state、项目源码、receipt 或 taskbook 内容。
- `inspect` 与 `preview` 通过既有 typed `read_result_artifact` recovery contract 打包 snapshot。preview
  只存在于短期进程内，不创建 archive directory，也不会把 checkout 弄脏。
- `apply` 写入前重新观察 semantic state，并且只写入完全一致的 preview 文件对。状态变化返回
  `CURRENT_FACTS_PREVIEW_STALE`；没有 Git-ignore coverage 返回
  `CURRENT_FACTS_ARCHIVE_NOT_IGNORED`。固定 archive 是
  `.colameta/reports/current-facts/`，不是调用方指定路径，也不是 tracked docs path。
- 确定性 fixture 覆盖 fresh、stale、partial、not-observed 和 Git/Runner conflict projection。即使本地
  archive 写入已被明确确认，artifact 仍然只是 observation-only。

## P1-C —— 把 Stage 7--9 变成一条 fail-closed preview journey

### P1-C0 实施闸口

开始代码前，先建立一个精确的 Stage 7--9 integration manifest：allowed files、当前
schema/hash bindings、input fixtures、public entry point 和 negative cases。manifest 必须
把工作绑定到既有 Stage taskbook，但不能宣称 taskbook 自身已经授予实施权限。

### 已采用的 P1-C0 集成绑定

`docs/taskbooks/P1_C_STAGE_7_9_INTEGRATION_MANIFEST.md` 现在是这个切片的精确
implementation-binding manifest（baseline commit `eb35e8e`，SHA-256
`bb16181ae45abedbf06ee4e68799a13e4adeb9c9142cf1b6063bd9d575e33519`）。它冻结当前
Master/Stage 7/Stage 8/Stage 9 的路径与 hash，把 public entry 限定为
`run_mcp_workflow workflow=stage_7_9_preview`，只支持 `mcp:read` 下的 `inspect` 和
`preview`，并指定一个不在 `mcp_server.py` 中的聚焦 domain owner。它要求 inspect 签发且重新核对的
journey context、精确的三段 input object、cross-stage pack-ID/taskbook-hash continuity、
whitelist-only public projection 和具名 negative test。

规范的 PLAN_ADJUST 路径在 Stage 9 必须保持 blocked，直到人工解决 Stage 8：
`PLAN_ADJUST_BLOCKS_CONTINUE` 是正确的安全 readiness conclusion，不是绕过 adjustment 的邀请。manifest
不增加公开工具，也不向其中 taskbook input 授予 implementation authority。

### 目标

复用已有 read/preview capability，提供一条有边界的 journey：

```text
Stage 7 drift evidence
  -> Stage 8 PLAN_ADJUST preview
  -> Stage 9 continue-readiness report
```

公开入口保持在九工具契约之内；必要时使用紧凑的 `run_mcp_workflow`
compatibility/orchestration 表面。rich diagnostics 留在 local-Codex/advanced-only。journey 的
任何部分都不能 apply plan、continue version、运行 executor、创建 ReviewDecision、修改
Delivery State、commit 或 push。

### 退出闸口

- 一套 fixture matrix 证明有效与无效的 Stage 7 -> 8 -> 9 handoff；
- 所有 context/hash/authority 缺失都返回具名 fail-closed blocker；
- 所有 side-effect path 都被测试为 denied；
- public projection 能指出下一项人工决定，但不泄露 private runtime data，也不把 semantic
  drift verdict 表述成事实。

### 已采用的 P1-C 实现收口

- `runner/mcp_stage_7_9_preview.py` 是唯一的组合 owner。它调用既有的 Stage 7 builder、
  Stage 8 preview 与 Stage 9 readiness report；不复制它们的 domain logic，也不把行为塞回
  `mcp_server.py`。
- `run_mcp_workflow workflow=stage_7_9_preview` 只公开 `inspect` 与 `preview`，scope 为
  `mcp:read`。非法的副作用 phase 会有意到达 typed read-only handler，并返回
  `STAGE_7_9_PHASE_NOT_SUPPORTED`，而不是误导性的通用 policy 拒绝。
- `inspect` 返回精确的 `stage_7_9_context`，包括 source-only Runner facts 中有意义的 null。
  公共 projection 会保留这份闭合合同，使 ChatGPT 的原样后续调用可以被复核。
- `preview` 会核对冻结 taskbook path/hash、三个有界 input object、生成的 Stage 7 到 Stage 8
  pack 连续性、生成的 Stage 8 到 Stage 9 preview 连续性，以及每个底层 Stage result 的
  false side-effect claim。它唯一成功的 PLAN_ADJUST 结论是被阻断、需要人工决定的 Stage 9 状态。
- focused tests 覆盖有效路线、公开结果脱敏、clean checkout、缺失/变化 context、taskbook/input/hash
  mismatch、Stage 7/8/9 fail-closed，以及所有已声明的副作用 phase。

## P1-D —— 明确区分客户端体验，并设立硬 release gate

### 客户端契约

ChatGPT 得到紧凑的九工具 Commander 契约、typed read/preview continuation、短 next action
和可恢复 result handle。本地 Codex 和 loopback advanced endpoint 保留 rich executor packet、
深度 diagnostics 和 migration handoff。两种表面共享 canonical state、scope、context 和
authority semantics；默认不共享 oversized payload。

### 开发验收

每个变更后的 public contract 必须在新鲜 ChatGPT development Connector 会话中验收：

1. 精确发现九个工具；
2. 故意触发 `CONTEXT_BINDING_MISMATCH` 的负向覆盖；
3. manifest inspect/read/verify 与已声明 subject 的 hash continuity；
4. packaged-result artifact 全页恢复和稳定 SHA/expiry；以及
5. 证明 ChatGPT 不依赖不可用的 `resources/read`。

### 硬 release blockers

以下任何一项不成立，release decision packet 必须是 `blocked`：

- 所有必需本地验证为绿；
- public endpoint runtime provenance 明确验证目标 commit，而不是 `unverified` 或
  `reload_needed_for_verification`；
- 有不暴露凭据的新鲜 connector/OAuth reachability evidence 和精确九工具 discovery；
- current-facts artifact 新鲜且没有未解决 critical blocker；
- 上述 fresh ChatGPT 验收通过；
- decision packet 写明另行授权的 stable-replacement target。

准备该 packet 不改变服务。执行 stable replacement 仍需要新的明确指令。

### 已采用的 P1-D 本地实现收口

- `runner/chatgpt_development_acceptance.py` 现在会在临时 fixture 中对精确九工具 Commander
  surface 做 in-process 合同演练：故意的 context-binding 负向路径、全页 hash-bound manifest
  review、全页 typed result-artifact recovery、clean checkout，以及不依赖 `resources/read`。
- 演练被明确标成 `local_contract_rehearsal`；它绝不声称 live ChatGPT session、Connector/OAuth
  可达、runtime provenance、stable replacement 或 release 已被授权。
- Commander 现在会在 initial current-facts packaged response 以及 typed pages 中都保留完整安全的
  artifact descriptor，包括 `expires_at`；client 不再需要猜 expiry。
- advanced consumer contract 现在显式展示客户端体验分层：字面量九工具 Commander tuple 和 typed
  reads，对比 normal Local Codex advanced capability examples；没有增加公开工具。
- `p1_client_release_gate` 会出现在 submission-readiness output 中，但它是独立命名的 release
  decision。独立验证的 live evidence 未到齐前它必须保持 `blocked`，调用方声明不能把它推进。
  `P1_D_CLIENT_RELEASE_GATE_MANIFEST.md` 记录精确的本地演练与外部证据边界。

当 shared validation ladder 通过时，本地 P1-D implementation gate 才算完成。新的真实 ChatGPT
development-connector 验收，以及任何 stable-replacement 决策，仍然有意留作外部、另行授权的后续事项。

### P1-E 受控 release-evidence 收口

- `manage_p1_release_evidence` 是仅 normal/loopback 可见的 typed workflow。它通过
  `preview -> apply` 接收 closed、脱敏的 evidence shape，把五组 P1 evidence 全部绑定到同一精确
  candidate HEAD，并且只有 explicit operator confirmation 后才写入本地 ignored runtime receipt。
- `p1_client_release_gate` 现在会评估该 receipt，而不是固定返回一组泛化 blocker。每个非 stable
  check 都会显示 passed、stale 或 blocked。外部 ChatGPT/connector 观察始终标为 operator-attested，
  绝不伪装为服务器自行观察。
- 公开 Commander 仍严格是九工具。P1-E 没有增加公开工具，不改变 Connector/Auth0/tunnel 设置，也不能
  替换 stable。
- 即使五组 evidence check 均通过，gate 仍保持 `blocked`，并给出
  `EXPLICIT_STABLE_REPLACEMENT_AUTHORIZATION_REQUIRED`，直到 Jenn 通过 stable-promotion boundary
  单独授权一个精确 target。

### 2026-07-25 治理对账

本次文档对账开始前观察到的本地实现 HEAD 为
`05575ad90cd40f44819aed31dda185ec7aa5c1f8`，实现历史已经走到 P1-E：

- typed-read 与 runtime-convergence 基础：`25a9585` 至 `20ecb3b`；
- P1-A 组合根拆分：`4aef920` 至 `34a0382`；
- P1-B current-facts artifact workflow：`eb35e8e`；
- P1-C Stage 7--9 manifest 与 preview journey：`ddd2bea` 至 `7e18f29`；
- P1-D 客户端 release gate 与 continuity 修复：`29b2bd4` 至 `5dd354a`；
- P1-E release-evidence 评估：`05575ad`。

这是实现历史对账，不是 exact-candidate 验收结论。本次文档提交位于上述实现 HEAD
之后，因此仍须在干净、精确的候选提交上重新运行完整 validation ladder。新鲜的 public
runtime provenance、脱敏的 Connector/OAuth 可达性证据和新的 ChatGPT development-connector
验收仍待完成。本节不授予 P0 closure、stable replacement、外部配置、push、release 或
deployment 权力。

## 交付节奏

P1-A、P1-B、P1-C、P1-D 是顺序产品 gate；每批内部则直冲退出闸口，不等待无关清理。
每一批都有精确文件列表、acceptance commands、negative tests、docs update，并且仅在完整
垂直切片为绿后做一次 local commit。发现 scope expansion 时，建立新的有边界 subtask，不能
偷偷塞进当前批次。

只有四个退出闸口全部通过、公开九工具契约稳定、legacy routing 已明确保留边界或有经过
测试的退役路径，并且 P1-D decision packet ready，P1 才算完成。这个 ready 绝不等于未获
明确授权就进行 stable replacement。

## 术语说明

| 术语 | 中文含义 |
| --- | --- |
| typed tool / typed contract | 参数、权限和行为边界固定且可机器检查的专用入口或契约。 |
| migration map | 将旧 workflow 映射到唯一权威新实现、兼容路径或 retirement handoff 的清单。 |
| canonical project state | 统一组合历史验证、当前观察和新鲜度的项目状态投影。 |
| current-facts artifact | 从 canonical state 生成、带观察时间和 authority boundary 的脱敏当前事实快照。 |
| fail closed | 证据不足或不一致时拒绝推进，不猜测也不放宽权限。 |
| release gate | 判断是否满足发布前提的受控检查；它本身不会发布或替换 stable。 |
