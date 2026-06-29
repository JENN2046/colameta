# ColaMeta 项目主任务书 v1 中文 Companion

```yaml
chinese_companion:
  source_document: PROJECT_MASTER_TASKBOOK.md
  source_sha256: 1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34
  translation_status: companion_draft
  authority_status: planning_reference_only
  translation_mode: full_semantic_chinese_mirror
```

`Project Master Taskbook` = 项目主任务书。中文意思是：这是 ColaMeta 项目的最高层
治理任务书，用来固定项目最终目标、产品定位、三层任务书结构、状态权责、MVP 边界、
冻结规则和后续 Stage 路线。

本中文文件是 `PROJECT_MASTER_TASKBOOK.md` 的中文 companion。它不替代英文源文件的
hash 权威，不修改 freeze-candidate 确认，不授权 implementation、commit、push、
executor run、route transition、remote action、memory write 或 bridge activation。

---

## 0. 元信息与当前草稿边界

英文源文件声明：

```yaml
document_type: project_master_taskbook
id: colameta_master_taskbook_v1
canonical_name: Master Taskbook
project: ColaMeta
version: v1
status: discussion_draft
canonical_path: PROJECT_MASTER_TASKBOOK.md
owner: Commander / Jenn
planning_authority: ChatGPT / Commander
execution_governance_layer: ColaMeta
executor_authority: Codex / other bounded executors
review_authority: ChatGPT Reviewer / Codex Commander / Human Commander
```

中文解释：

- `Master Taskbook` = 主任务书 / 项目宪章 / 项目总目标大任务书。
- 当前状态是 `discussion_draft`，即讨论草稿。
- 它不是已经生效的 active authority。
- 它必须经过 Commander 确认和 activation requirements，才可成为正式 anchor。

当前源文件中的 `current_known_state` 是文档被 hash 绑定时的记录，不等于每次阅读时的
实时仓库状态。实时状态要用 Git 和 Runner 当前输出另行校准。

---

## 1. Project Goal = 项目目标

### 1.0 Project Final Goal = 项目最终实现目标

`project_final_goal` 是当前设计稿唯一完整最高目标。项目不再另设短句版
`North Star Goal`。

完整中文表述：

> 将 ColaMeta 设计并演进为一个目标锚定的 AI 交付指挥层。它必须能在 Master、
> Stage、Version 三层任务书之间保留 Commander 确认的项目最终目标；通过机器可检查
> 的执行信封约束本地执行；生成有证据支撑的审查交接包；并在没有静默漂移、隐藏权威
> 扩张或不可验证完成声明的情况下，请求由 Commander 控制的下一状态决策。

`MVP proof shape` = MVP 证明形态：

Stage 0-6 Thin Governed Loop。中文意思是：目标锚点、任务书绑定、版本任务导入、
有边界的执行信封、执行与验证回执、审查者交接、分类后的下一状态 Commander 决策请求。

非授权边界：

- 项目目标只是设计锚点；
- 不授权 implementation；
- 不授权 freeze；
- 不授权 commit / push / remote action；
- 不授权 memory write；
- 不授权 bridge activation；
- 不授权 route transition；
- 不授权 automatic state promotion。

### 1.1 Minimum Irreplaceable Capability Set = 最小不可替代能力集

ColaMeta 只有在能持续把 AI 交付锚定到已同意的目标时，才是不可替代的。它必须回答：

- 为什么这项工作存在；
- 哪个 taskbook boundary 控制它；
- 什么证据证明它；
- 谁审查它；
- 下一状态可以请求什么。

最小能力包括：

1. `goal_and_taskbook_anchoring` = 目标与任务书锚定。
2. `three_level_taskbook_model_master_stage_version` = Master / Stage / Version 三层任务书模型。
3. `execution_envelope` = 执行信封，把 Version Taskbook 转成受控本地执行边界。
4. `bounded_executor_dispatch` = 只在授权 scope 和 stop conditions 内派发 executor。
5. `evidence_and_reviewer_handoff_package` = 生成可供 Reviewer 判断的证据包，而不只是代码输出。
6. `delivery_state_machine` = 跟踪交付生命周期状态，而不只是进程状态。
7. `review_feedback_intake_and_next_state_decision_request` = 摄入审查反馈并准备下一状态 Commander 决策请求。
8. `commander_gate_stop_boundary_and_observable_status_surface` = 保留关键门、停止边界和人可读状态面。

这些是最小能力，不是最大能力。它们不授权 codex-router bridge、remote action、自动 commit/push、
自动 plan mutation、自动 route transition 或 AGENTS OS Rights Plane claim。

---

## 2. Why This Project Exists = 项目为什么存在

AI 编码中已有强角色：

- ChatGPT 可以规划目标和任务；
- Codex 可以实现代码；
- Reviewer 可以审查结果；
- Human Commander 可以做最终决策。

长期 AI 项目最大的问题是：

> Projects slowly drift. 项目会慢慢漂移。

漂移来源：

- Executor drift：Codex 修改 forbidden files、扩 scope、顺手重构。
- Planner drift：ChatGPT 拆任务时逐渐偏离原目标。
- Reviewer drift：Reviewer 只看代码质量，忘记项目方向。
- State drift：没有可信证据和审查 closure，却把阶段当作完成。
- Plan drift：任务越来越多，但项目离原始目的越来越远。

ColaMeta 要回答的问题是：

> 长期 AI 项目交付怎样保持可控制、可审查、可追踪、可纠正？

---

## 3. Product Identity Constraint = 产品定位约束

### 3.1 Derived Product Identity = 派生产品身份

ColaMeta 的产品身份从 `project_final_goal` 派生。源文件不保留独立 slogan、positioning
phrase 或 North Star Goal。

如果要重开产品身份，就等于重开完整 `project_final_goal`，需要 Commander hard gate。

职责分层：

- ChatGPT / Commander：定义 master goals、stage goals、version taskbooks、route decisions。
- ColaMeta：登记目标、冻结任务、约束执行、收集证据、路由审查、按规则推进状态。
- Codex / Executor：实现当前 bounded taskbook。
- Reviewer：根据 goal、taskbook、diff、evidence、reports 判断 pass/fix/adjust/abort。
- Human Commander：处理 hard gates、重大路线变化、最终批准。

### 3.2 Wrong Positioning = 错误定位

ColaMeta 不能变成：

- 自动项目经理；
- 自动规划大脑；
- 自动产品负责人；
- 自动审查者；
- 自动发布系统；
- 无边界自主 agent 框架；
- 无 scope 限制的 executor。

它的价值不是替人类做所有判断，而是让判断有边界、有证据、可审查、可回退。

### 3.3 codex-router Future Bridge Candidate = codex-router 未来桥接候选

`codex-router` 当前只是 `future_bridge_candidate`：

- 不在当前实现路线；
- 非 runtime；
- 不是 MVP 依赖；
- 与 ColaMeta 是 layered bridge，不是 merger；
- 上游是 ColaMeta；
- 下游是 codex-router。

候选边界：

- ColaMeta 输入：`TaskEnvelope`、taskbook/version/run correlation ids、requested action、
  workspace/repo context、risk/validation expectations。
- codex-router 输出：`RoutingDecision`、preflight result、approval requirement、execution grant
  或 block reason、validation result、audit/evidence receipt。

中文解释：

ColaMeta 决定“应该做什么、为什么属于项目计划、服务哪个 Master/Stage/Version taskbook”。
codex-router 决定“这次执行是否允许、适用什么执行边界、需要什么批准、什么证据证明边界被遵守”。

第一种可接受桥接形状如果未来被授权，应是很窄的 preflight-only：

```text
Taskbook -> TaskEnvelope -> RoutingDecision / Preflight -> EvidenceReceipt
```

此形状只是说明，不是当前实现 scope。

### 3.4 Semantics-to-Mechanics Translation Table = 语义到机制转换表

Master 允许从 AGENTS OS、dream essay、memory governance、codex-router 等处借治理语义，
但必须翻译成 ColaMeta 的明确机械控制。未经翻译的语义不是实现要求。

重要语义与机制：

- `Unknown may remain` = 未知可以继续存在。含义：意图、状态、同意、权威不明确时不能强行假装清楚；
  必须进入 `unknown`、`blocked` 或 `needs_human`，对扩 scope 或跨权威动作 fail closed。
- `Silence is not consent` = 沉默不是同意。无回复、超时、没反对都不能授权继续、升级、remote action 或扩 scope。
- `Fatigue is not authorization` = 疲劳不是授权。用户累了、说“你决定吧”也不产生开放式权威。
- `Past memory cannot rule present` = 过去记忆不能统治当前。当前 instruction、repo reality、observed evidence 优先。
- `Pause returns control` = 暂停把控制权还给人。pause/block/stop 是合法交付状态，不是要隐藏的失败。
- `Growth right and relationship right` = 成长权和关系权只属于 AGENTS OS resident Agents，不属于 ColaMeta executors。
- `Goal Boundary Contract` = 目标边界契约只是未来非 runtime bridge concept，不是 MVP 依赖。
- `codex-router` = 未来可能作为 policy/routing/approval/execution-control bridge，但当前只是 architecture boundary。
- `Semantic alignment` = 语义对齐必须由 Reviewer 或 Commander 判断，ColaMeta 不能自证。

### 3.5 Forbidden Claims / Boundary Law = 禁止主张 / 边界法

Master、Stage taskbooks、Version taskbooks、implementation prompts、product descriptions、
future bridge drafts 都禁止以下主张，除非未来 Commander-approved taskbook 明确 supersede：

- ColaMeta 不是 AGENTS OS。
- ColaMeta 不治理 resident Agent 的 life、growth、intimacy、relationship rights。
- Growth right 和 relationship right 只适用于 resident Agents，不适用于 ColaMeta executors。
- ColaMeta 可以借 AGENTS OS 治理语义，但必须翻译成明确机械控制。
- 未翻译语义不是实现要求。
- Treaty Layer 不是已批准的 ColaMeta runtime layer。
- 降级后的概念名是 Goal Boundary Contract。
- Goal Boundary Contract 只是 non-runtime future_bridge_candidate，不授权 schema、adapter、executor dispatch、
  state-machine、runtime integration 或 implementation。
- codex-router 不是即时依赖，只是 future_bridge_candidate。
- 命名 codex-router 不授权 bridge implementation、adapter、schema、runtime integration、shared state、
  executor dispatch 或 remote action。
- 沉默不是同意。
- 疲劳不是授权。
- 过去记忆不是当前权威。
- unknown state 必须 fail closed。
- semantic alignment 必须被审查，不能由 ColaMeta 自动声称。
- ColaMeta 不能替代 Commander planning、Reviewer judgment 或 human hard gates。

拒绝标准：

- 把 Treaty Layer 当当前 runtime layer 的草稿拒绝。
- 暗示 codex-router 是 MVP 的草稿拒绝。
- 把 AGENTS OS resident-Agent rights 应用到 ColaMeta executors 的草稿拒绝。
- 在单独批准 taskbook 前把 Goal Boundary Contract runtime 化的草稿拒绝。
- 允许 ColaMeta 推断 consent、从 fatigue 继续、用 stale memory 压过当前状态的草稿拒绝。
- 没有 Reviewer 或 Commander 判断就声称 semantic alignment 的草稿拒绝。

---

## 4. Core Governance Principles = 核心治理原则

### 4.1 Separation Of Authority = 权威分离

规划权、执行权、审查权不能混成一个面。

- Planning：ChatGPT / Commander。
- Execution：Codex / Executor。
- Review：Reviewer / Commander。
- State advancement：ColaMeta under structured decisions。
- Master goal change：Commander hard gate。

### 4.2 Goal Anchoring = 目标锚定

每个 stage、task、execution、review、fix、plan adjustment 都必须能回到项目 master goal。

每一步都要回答：

> 这一步还服务项目 master goal 吗？

如果不清楚，不能假装已经对齐，必须进入 review 或 plan adjustment。

### 4.3 Task Freezing = 任务冻结

每个可执行 version task 必须冻结：

- goal
- allowed_files
- forbidden_files
- acceptance_commands
- manual_acceptance
- out_of_scope
- delivery_evidence
- review_requirements

Executor 可以完成当前 taskbook，但不能重写路线。

### 4.4 Feedback Loop = 反馈闭环

标准闭环：

```text
taskbook registration
  -> executor execution
  -> ColaMeta evidence collection
  -> Reviewer Handoff Package
  -> Reviewer decision
  -> structured feedback intake
  -> continue / fix / plan adjust / abort
```

长期推进不应在缺少 review feedback 的情况下自动继续。

### 4.5 Preview First = 先预览

以下动作必须 preview-first：

- register / modify master taskbook；
- register / modify stage taskbook；
- insert / modify version task；
- adjust plan from review feedback；
- commit local Git changes；
- perform remote Git actions。

ColaMeta 不能跳过 preview 直接 apply。

### 4.6 Semantic Drift Policy = 语义漂移策略

ColaMeta 可以收集 evidence、要求 reviewer answer、提出 alignment questions，但不能独自声称
final semantic alignment。最终语义对齐要 Reviewer 或 Commander 判断。

---

## 5. Master Taskbook Activation = 主任务书激活

状态定义：

- `draft`：可编辑，不是执行锚点。
- `discussion_draft`：存入项目供讨论，不是 frozen canonical anchor。
- `active_candidate`：可审查、可 hash，但还不是 mandatory anchor。
- `freeze_candidate`：review 后修订，等待 Commander freeze confirmation。
- `active`：可被 Stage、Version、Review records 正式引用。
- `superseded`：被新版本替代，旧任务仍可引用旧 hash。
- `revoked`：被 Commander 撤销，新任务不可用。

当前源文件内部状态是 `discussion_draft`，推荐 review decision 是 `CONTINUE_DISCUSSION`。

激活要求：

- Commander review completed for freeze-candidate use；
- canonical copy stored；
- canonical hash generated；
- no unresolved P0 review issues；
- P1 已 resolved、scoped out 或明确 non-blocking disposition；
- hash_policy accepted for review use；
- versioning_policy accepted for review use；
- freeze_candidate_preconditions satisfied。

### 5.3 Freeze Candidate Preconditions = 冻结候选前置条件

Master 不能从 `discussion_draft` 进入 `freeze_candidate`，除非 MVP 能被审查为一个
thin governed loop，而不是广泛产品平台。

前置条件包括：

- Stage 0-6 是一个 governed proof loop，不是七个完整自动化层。
- Stage 4 降权为 machine-checkable execution envelope + local execution evidence 或 imported execution receipt。
- Stage 6 降权为 structured feedback classification + next-state Commander decision request。
- execution envelope 有结构化字段和 fail-closed rejection rules。
- validation receipt 能区分 validated、unvalidated、not_run、failed、blocked。
- delivery state gate 有有限状态、允许转换、每个转换所需证据、禁止 auto-promotion。
- GateEvent 是 Delivery State Gate 对状态转换和 item-level blocked 变化的 append-only 记录。
- CommanderDecisionRequest 是 request object，不是 mutation authority。
- AuditEvent 是 append-only trace record，不是 delivery-state authority。
- Master 顶层 delivery states 只冻结 proposed、ready、in_delivery、submitted、accepted、cancelled。
- Reviewer decisions 先是 review records，不能直接改 delivery_state。
- Master / Stage / Version taskbooks 定义主张和 execution envelopes，不拥有 state authority。
- Stage 0-6 是静态 readiness contract，不是 live tracker。
- reviewer handoff package 有最低模板。
- codex-router 仍是 future_bridge_candidate，不是 MVP dependency。
- discussion_draft、hash、validation results、review packets 不等于 execution/freeze/canonicalization/commit/push/memory-write/bridge authority。

---

## 6. Hash Boundary Policy = Hash 边界策略

Master 最终必须可 hash、可验证、可引用。canonical hash 应绑定治理字段，而不是格式或变化中的本地状态备注。

核心规则：

- `hash_policy.canonical_fields` 是单一真相源。
- derived payload views 只是审查视图，不能成为第二套权威。
- 如果 derived payload view、review packet 或 future canonicalizer mapping 与 `hash_policy.canonical_fields`
  冲突，canonicalizer 必须 fail closed。

Canonical field path style = 规范字段路径风格：

- 只允许机器可读真实来源路径；
- 允许前缀：`master_taskbook.`、`markdown_section.`、`yaml_block.`、`hash_policy.`；
- 允许 wildcard list selector；
- 禁止 bare concept name、ambiguous heading label、runtime status note。

Canonical scope decisions：

- `future_bridge_candidates`：绑定 future status、non-authorization、not MVP dependency、not current route；
  不绑定详细 bridge implementation、adapter fields、schema work、runtime integration details。
- `post_mvp_stages`：绑定 post-MVP route only、not authorized、not Stage 0-6 readiness；
  不绑定 detailed deliverables、implementation order、version allocation。
- `user_promise`：用户承诺“ColaMeta lets users delegate project work to a controlled,
  reviewable, and correctable AI execution team” 足以约束产品方向。

Canonical fields 包括：

- Master id、version、project_final_goal、goal_statement_policy、product_identity_constraint_decision；
- minimum_irreplaceable_capability_set、mvp_shape_decision、delivery_state_gate_freeze_target；
- state_authority_contract_decision、delivery_state_transition_model_decision、review_decision_mapping_decision；
- taskbook_layer_responsibility_decision、stage_0_6_readiness_contract_decision；
- future_bridge_candidates 的 id/status/route/runtime/mvp_dependency/non_authorization；
- non_goals、governance_principles、required_bindings、mvp_boundary、success_criteria；
- freeze-candidate preconditions；
- freeze process and canonicalization；
- minimum checkable schema contracts summary；
- semantics-to-mechanics table、forbidden claims boundary law、standard workflow、review feedback decision policy、
  taskbook hierarchy、MVP boundary、hard gates。

Excluded fields 包括：

- `master_taskbook.current_known_state`；
- codex-router bridge detailed implementation shape；
- Stage 7-9 detailed deliverables；
- stage summary status notes；
- review packet snapshot runtime values；
- formatting、heading numbering、examples/commentary unless promoted、generated_at、draft_notes、本地状态备注、
  runtime status notes、debate transcripts、raw logs、secrets、credentials。

`current_known_state` 被排除，是因为它记录变化中的仓库现实，例如 local commits、remote sync state、
in-progress versions。

### 6.1 Freeze Process And Canonicalization = 冻结流程与规范化

核心规则：

- `freeze_candidate` 是可审查治理候选，不是 active authority。
- Hash 是 identity，不是真相或授权。
- 把主张 hash 了，不会让主张变成事实。
- Freeze approval 不是 implementation approval。

`freeze_candidate` 意味着：

- 内容足够稳定，可以进入 freeze review；
- canonical payload 可以被 hash 和比较。

它不意味着：

- accepted truth；
- active authority；
- implementation / commit / push / deploy / remote action approval；
- credential authority；
- user-visible accepted truth。

Canonical hash：

- 名称：`freeze_content_hash`；
- 算法：sha256；
- 输入规则：`sha256("ColaMeta.freeze_candidate.v1\n" + canonical_json)`；
- 规则：UTF-8、LF、NFC、mapping keys 排序、保留 explicit null、set-like arrays 按 stable id 排序、
  semantically ordered arrays 需要 explicit order fields、repo-relative paths、hash evidence digests/refs、
  永不包含 secrets/credentials。

Review packet minimum 包括：

- candidate_id、taskbook_id、status、canonicalizer_version、hash_algorithm、freeze_content_hash；
- included/excluded fields manifest；
- canonical payload snapshot or digest；
- diff_summary；
- P0/P1/P2 disposition；
- EvidencePackage index；
- conflict review；
- runtime compatibility check；
- terminal correction / supersede check；
- preview-only user-visible projection；
- non-authority notice；
- Commander confirmation text。

P0/P1/P2 规则：

- P0：任何 open P0 都阻止 freeze_candidate。
- P1：除非 resolved、scoped out 或明确 dispositioned as non-blocking，否则阻止。
- P2：只要不削弱核心治理主张，可留作 tracked。

失效规则包括：任何 hashable field 变化、schema/canonicalizer version 变化、evidence digest 缺失或变化、
Runtime fact 与 Taskbook claim 冲突、scope/boundary/acceptance contract 变化、blocked policy premise 变化、
terminal correction/supersede 变化、projection 不能机械导出、发现 secret、Commander confirmation 不匹配、
新 P0、action authority flags 变化。

Action authority flags 全部为 none：

- implementation_authority
- commit_authority
- push_authority
- deploy_authority
- remote_action_authority
- credential_authority
- external_api_authority

---

## 7. Versioning Policy = 版本策略

规则：

- 不改变 canonical_fields 的小文本编辑，不要求新 Master version。
- governance change 需要新 Master Taskbook version 和 Commander hard gate。
- project_final_goal change 需要新 Master Taskbook version 和 Commander hard gate。
- non_goals change 需要新 Master Taskbook version 和 Commander hard gate。
- active versions 可以共存。
- old tasks 保留 original hash。
- new tasks 应绑定 latest active version。

普通 version task 不能静默修改 Master Taskbook。

---

## 8. Three-Level Taskbook Hierarchy = 三层任务书架构

结构：

```text
Project Master Taskbook
        ↓
Stage Taskbook
        ↓
Version Execution Taskbook
```

这是一套控制结构，不是授权阶梯。Commander 授权的是明确命名的 gates 和 bounded execution
envelopes，不是每个内部步骤。

### 8.0 Layer Responsibility Contract = 三层任务书职责边界契约

核心规则：

- Taskbooks 定义 bounded claims 和 execution envelopes；
- Taskbooks 不拥有 state authority；
- Runtime owns facts；
- Taskbooks own claims；
- Delivery State Gate owns acceptance；
- Delivery State Gate 只能通过 GateEvent 写 delivery_state；
- Commander owns boundary authority；
- 用户只看到 accepted truth。

Master Taskbook 拥有：

- project_final_goal；
- global doctrine；
- non_goals；
- Stage 0-6 Thin Governed Loop；
- authority boundaries；
- responsibility boundaries；
- freeze_candidate preconditions。

Master 不拥有：

- Runtime facts；
- accepted delivery state；
- Version implementation truth；
- EvidencePackage sufficiency；
- ReviewDecision outcome authority；
- GateEvent outcome authority。

Stage Taskbook 拥有：

- stage purpose；
- entry/exit criteria；
- required artifacts；
- required evidence shape；
- stage-local review expectations；
- gate-readiness criteria。

Stage 不拥有 project_final_goal mutation、global authority rules、accepted delivery state、cross-stage exceptions、
Version runtime truth、codex-router activation authority。

Version Taskbook 拥有：

- 一次具体 delivery attempt；
- scoped implementation claims；
- allowed files/mutations；
- validation commands；
- evidence refs；
- review refs；
- requested gate actions；
- open risks。

Version 不拥有 acceptance、Runtime facts、stage policy、Master doctrine、user-visible accepted truth、
state transitions。

Executor autonomy rule：

在已授权 Stage 和 Version envelope 内，executor 可以自动继续本地、可逆、scope-aligned 工作：
收集 runtime facts、改善 evidence、修 defects、跑 validation、更新 candidate claims、准备 review/gate request。

Commander 不需要批准 envelope 内每个普通执行步骤。但以下情况必须升级：

- 改 `project_final_goal`；
- 改 scope boundary 或 non-goals；
- 绕过 Stage 0-6 controls；
- 宣称 accepted state；
- mutate delivery_state；
- 解决 Runtime facts 与 taskbook claims 的冲突；
- 做不可逆或外部动作；
- 覆盖 unresolved user work；
- 把 codex-router 提升出 future_bridge_candidate。

状态词规则：

- Taskbook 只能记录 claims、evidence、requested transitions。
- Taskbook 不能声明 accepted delivery state。
- `Ready for Gate` 只表示 executor 声称 evidence 已具备。
- `Complete` 只表示 Version 内 executor-local tasks 声称完成。
- `Frozen` 只表示 named draft/candidate 未经适用规则不可再编辑。
- `Accepted` 只有在有 authoritative Delivery State GateEvent 支撑时才有效。
- 没有 authority source 的 status word 都只是 non-authoritative taskbook text。

### 8.1 Project Master Taskbook = 项目主任务书

路径：`PROJECT_MASTER_TASKBOOK.md`

用途：冻结 project master goal、定义 positioning/non-goals/long-term route/stage decomposition principles、
review principles、drift judgment standards、plan adjustment rules、layer responsibility boundaries。

ColaMeta duty：register、read、hash、validate、reference、防止 silent modification、major changes 需要 hard gate。

### 8.2 Stage Taskbook = 阶段任务书

路径：`docs/taskbooks/stages/STAGE_XX_*.md`

用途：把 master goal 拆成 stage goal，说明为什么支持 master goal，声明 out_of_scope，
列 version-task directions，定义 gate-readiness criteria 和 stage review requirements。

ColaMeta duty：register、validate master_taskbook_ref、compute stage_taskbook_hash、
bind future version tasks、surface to Reviewer。

### 8.3 Version Execution Taskbook = 版本执行任务书

路径：`.colameta/prompts/vX.Y.md`

必需字段：

- version、name；
- master_taskbook_ref、stage_taskbook_ref；
- task_goal、supports_project_goal；
- allowed_files、forbidden_files、allowed_mutations；
- acceptance_commands、manual_acceptance、stop_conditions、out_of_scope；
- reporting_destination、acceptance_and_evidence_contract、forbidden_authority_claims、
  reviewer_packet_requirements。

### 8.4 Execution Envelope Principle = 执行信封原则

Version Taskbook 定义 execution envelope。Commander 明确授权后，envelope 只授权 exact parent hashes
和明确 paths/globs 上的本地命名工作。

执行信封必需字段：

- parent_hashes；
- task_goal；
- definition_of_good；
- allowed_files_or_globs；
- allowed_mutations；
- forbidden_actions；
- exact_local_validation_commands；
- manual_checks；
- stop_conditions；
- reporting_destination；
- acceptance_and_evidence_contract；
- forbidden_authority_claims。

授权后，ColaMeta 和 bounded executors 可以在 envelope 内自动迭代：local read/edit/validate/
narrow-fix/report，直到 local validation passes、gate request ready 或 stop condition reached。

Narrow fixes 可重复，但必须保持 envelope，不得增加新文件、dependency、API、route change、policy change、
scope expansion、authority claim、credential change、runtime change、destructive action 或 remote write。

Hash validity 必须在 execution start 和 review submission 前检查。parent hash 不匹配或 parent status 变化，
envelope 立即 suspended。

Reporting 只到本地或 review-packet 明确 destination，不授权 GitHub comments、PR updates、issues、Slack、
remote records、memory writes、route-state updates、canonical status updates 或 external writes。

---

## 9. Minimum Checkable Schema Contracts = 最小可检查结构契约

Master 只冻结检查 scope、authority、evidence、validation、state movement 所需的最小字段形状。
它不冻结 executor internals、commands、tools、logs、UI 或 implementation routes。

当前实现现实：

- `distributed_state_advancement_control` = 分散式状态推进控制。
- 当前 ColaMeta 通过 runner state、version status、state mutation gateway、acceptance rerun、
  checkpoint review、continue-next-version workflow、executor-session safeguards 等机制协作控制状态推进。
- 这不是统一 `Delivery State Gate` object。

冻结目标：

- `unified_delivery_state_gate_contract` = 统一交付状态门契约。
- 目标是把分散式状态推进控制升级为统一 governance contract。
- 这不授权 runtime implementation、migration、state-machine rewrite、executor dispatch changes、
  commit、push 或 freeze。

四个契约组合：

```text
Envelope controls permission.        执行边界管权限。
Receipt controls truth.              执行与验证回执管事实。
Reviewer handoff and decision controls judgment. 审查交接与决策管判断。
Delivery state gate controls movement.           交付状态门管状态移动。
```

最小对象：

- `ExecutionEnvelope` = 执行信封，用于 dispatch 前边界和权限检查。
- `Receipt` = 执行与验证回执，用于 observed/imported execution truth evidence。
- `GateEvent` = 状态门事件，用于 append-only delivery_state 和 blocked projection event。
- `CommanderDecisionRequest` = 指挥官决策请求，是 request，不是 mutation authority。
- `AuditEvent` = 审计事件，是 append-only trace record，不是 state authority。

### 9.1 State Authority Contract = 状态权责契约

状态不是一坨东西归某层。ColaMeta 把状态拆成 intent、claim、evidence、judgment、
user-visible truth，每种都有权责边界。

权责域：

- `intent_authority` = 意图权，owner 是 Master Taskbook，拥有 project_final_goal、global semantics、
  MVP scope、final acceptance meaning。
- `declaration_authority` = 声明权，owner 是对应 taskbook layer，Master/Stage/Version 各自声明本层状态主张。
- `evidence_authority` = 证据权，owner 是 ColaMeta Runtime 或等价验证来源，拥有 execution facts、commands、
  logs、validation results、failures、artifacts、traces、scope guard results。
- `transition_authority` = 转换裁决权，owner 是 Delivery State Gate，拥有 transition judgment、
  gate acceptance、block reason、conflict exposure。
- `permission_authority` = 授权权，owner 是 Commander / Human hard gate，拥有 boundary-crossing、
  freeze、commit/push/release、remote/irreversible action permission。

采用规则：

> Runtime owns facts. Taskbooks own claims. Delivery State Gate owns acceptance. User sees accepted truth.

中文：

> 运行时拥有事实。任务书拥有主张。交付状态门拥有接受裁决。用户看到的是被接受后的真相。

硬规则：

- Runtime observation 不能直接变成 delivery state。
- Taskbook declaration 没有 evidence 和 Gate judgment 不能变 accepted state。
- Gate 不能发明没有声明或证据支撑的 state。
- User-visible truth 必须带 source ownership、evidence status、gate result。
- Automation 只能在预声明 transition、Gate accepted、Commander authorization 内推进 execution state。
- Runtime 只能自动写 facts；promotion to truth/authority/user-visible completion 需要 Gate 或 Commander。
- ownership/evidence/state consistency 不清楚时 fail closed。

### 9.2 Global Contract Rules = 全局契约规则

- 缺 required fields fail closed。
- 空 required fields fail closed。
- TBD、unknown 或 ambiguous authority fields fail closed。
- Refs 是 opaque references，不承诺 storage backend、runner、UI、CI 或 router。
- Implementation details 非权威，除非 Stage/Version Taskbook 另行绑定。
- Review findings 是 evidence，不是 execution permission。
- Hashes identify observed content，不授权 action。
- Validation evidence reports readiness，不授权 state promotion。
- Remote、destructive、credential、production、freeze、commit、push、memory-write、bridge actions 都需要单独 Commander authorization。

必须冻结的 enum families：

- `risk_level`: low、medium、high、critical。
- `validation_status`: validated、unvalidated、not_run、failed、blocked。
- `execution_status`: executed、partial、not_run、blocked。
- `execution_result`: completed_validated、completed_unvalidated、partial、blocked、failed。
- `review_decision`: ACCEPT、NEEDS_FIX、PLAN_ADJUST、ABORT。
- `delivery_state`: proposed、ready、in_delivery、submitted、accepted、cancelled。
- terminal states：accepted、cancelled。
- flags not states：blocked、at_risk、on_hold、waiting。
- transition outcomes not states：returned_for_revision。
- terminal record events not states：administrative_correction、supersede_record。

### 9.3 Delivery State Transition Model = 交付状态转换模型

采用模型：small, strict, and boring = 小、严、朴素。

顶层 delivery states：

- `proposed` = 已提出：有交付项，但还未承诺交付。
- `ready` = 已就绪：scope、owner、acceptance criteria、priority、required inputs 已知。
- `in_delivery` = 交付中：正在生产或修订。
- `submitted` = 已提交验收：owner 声称完成并提交产物或证据供验收。
- `accepted` = 已接受：Delivery State Gate 通过 GateEvent 接受提交项，terminal。
- `cancelled` = 已取消：此记录下有意停止，不再交付，terminal。

非顶层状态：

- blocked、at_risk、on_hold、waiting 是 condition flags。
- validation、approval、delivery 是 facets。
- returned_for_revision 是 submitted -> in_delivery 的 transition outcome。
- administrative_correction、supersede_record 是 terminal record events，不是 states。

允许转换：

- proposed -> ready；
- proposed -> cancelled；
- ready -> in_delivery；
- ready -> cancelled；
- in_delivery -> submitted；
- in_delivery -> cancelled；
- submitted -> accepted；
- submitted -> in_delivery，outcome 为 returned_for_revision；
- submitted -> cancelled，exceptional，需要 Commander 或 delegated cancellation authority。

禁止转换：

- proposed -> in_delivery/submitted/accepted；
- ready -> submitted/accepted；
- in_delivery -> accepted；
- submitted -> ready/proposed；
- accepted -> proposed/ready/in_delivery/submitted/cancelled；
- cancelled -> proposed/ready/in_delivery/submitted/accepted；
- any state -> proposed；
- administrative_correction 不是 delivery_state transition；
- 没有 submitted output 和 evidence 时任何 state -> accepted。

Terminal rule：

- accepted 和 cancelled 是 terminal states。
- accepted work 不用普通 transition 重开。
- 接受后记录错误用 administrative correction。
- 接受依据无效用 supersede record。
- 接受后新增 scope/work 用 new item 或 change request。

Administrative correction = 行政纠错：

- 只能修账本，不能改判决。
- 适用于 evidence link、hash transcription、timestamp、attachment id、file name、version label、
  display label 等记录错误。
- 不得改变 delivery subject、accepted artifact、acceptance scope、review decision、gate authority、
  evidence content hash 或 delivery_state。

Supersede record = 替代记录：

- 保留旧历史，但声明后续以新记录为准。
- 用于原 evidence 不支持 acceptance、accepted artifact 错误、reviewer/Gate authority 无效、
  ReviewDecision 记录实质错误、acceptance scope/requirements 用错、evidence forged/polluted/unverifiable、
  旧 terminal conclusion 不再可作为当前有效结论。
- supersede 不重开旧 terminal item，不删除旧记录；replacement item 必须有自己的 EvidencePackage、
  ReviewDecision、Gate transition。

New item = 新交付项：

- 用于 new requirement、新 acceptance standard、follow-on improvement、新环境/集成问题、原 accepted scope 外 defect、
  第二版或 continuation work。
- 原 accepted item 保持 accepted。

Blocked flag policy = 受阻标记策略：

- blocked 不是 state，是 condition flag。
- Executor owns run-level truth。
- Gate owns item-level blocked truth。
- Review can proceed while blocked。
- Acceptance cannot finalize while active blockers remain。
- `delivery_item.blocked` 不能直接写，只能由 active `ItemBlocker` 经 Gate 派生。
- Executor 可以写自己的 `executor_run.blocked`，创建 blocker_report EvidencePackage，
  发 BlockerReported/BlockerResolved evidence，请求 Gate set/clear blocked。
- Executor 不能写或清 `delivery_item.blocked`，不能写 delivery_state，不能把 EvidencePackage 当 approval。
- `submitted + blocked=true` 可以进入 review，但不能 finalize as accepted，除非同一 transaction 中所有 active ItemBlockers
  被 cleared/waived/invalidated。
- accepted 和 cancelled 不能带 active blocked=true。

ItemBlocker minimum fields：

- item_blocker_id、item_id、blocker_category、blocker_summary、blocker_owner、status、
  source_actor、source_authority_domain、affected_delivery_state、impact、evidence_refs、
  authority_required、unblock_condition、created_at、last_reviewed_at。

Status values：active、cleared、waived、invalidated。

### 9.4 Runtime State Compatibility Mapping = 运行态兼容映射

旧 runtime states 是当前执行机器的 evidence signals。它们可以支持 EvidencePackage、
ReviewDecision input 或 Gate request，但不拥有 delivery lifecycle、item-level blocked truth、
terminal state、taskbook scope 或 Commander authority。

Legacy states：

- `RUNNING_ACCEPTANCE` = 正在跑验收。只是 runtime execution fact；不能表示 submitted、accepted、rejected、cancelled。
- `VERSION_PASSED` = 版本检查通过。只是 validation receipt fact；不能表示 accepted、gate approved、implementation authorized。
- `PASSED` = 检查通过。只是 validation fact；不能表示 accepted、automatic Gate transition、Commander authorization。
- `COMPLETED` = 执行完成。只是 execution completion fact；不能表示 submitted、accepted、ReviewDecision recorded。
- `BLOCKED` = 运行阻塞。可贡献 executor_run.blocked 和 blocker evidence；不能直接写 delivery_item.blocked、
  顶层 delivery_state、cancelled 或 plan change。
- `FAILED_BLOCKED` = 失败且阻塞。可贡献 failed validation record、blocker evidence 和 review input；
  不能表示 cancelled、NEEDS_FIX by itself、top-level state 或 automatic scope change。

禁止映射：

- PASSED / VERSION_PASSED -> accepted；
- COMPLETED -> submitted / accepted；
- BLOCKED -> delivery_item.blocked without Gate；
- FAILED_BLOCKED -> cancelled；
- RUNNING_ACCEPTANCE -> submitted / accepted；
- runtime_state -> user_visible_accepted_truth without Gate projection。

### 9.5 User Visible Status Projection = 用户可见状态投影

用户可见状态是 read-only projection，不是 authority source。它可以摘要 evidence 和 review context，
但只有 GateEvent 可以把 delivery_state 和 blocked 投影给用户。

最小字段：

- `status`：来自 GateEvent-applied delivery_state，值为 proposed/ready/in_delivery/submitted/accepted/cancelled。
- `blocked`：来自 Gate-derived active ItemBlocker，true/false。
- `status_text`：人话状态摘要，例如“已提交，等待验收”“交付中，但等待 Commander 授权”“已接受”。
- `evidence_status`：来自 EvidencePackage + runtime facts + claim alignment，只做 context。
- `review_status`：来自 ReviewDecision，只做 context。
- `next_visible_action`：wait_for_review、provide_evidence、continue_delivery、wait_for_authorization、no_action。

Projection rules：

- delivery_state 必须来自 GateEvent。
- blocked 必须来自 Gate-derived active ItemBlocker。
- evidence_status 不能变 delivery_state。
- review_status 中的 acceptance_recommended 不能在无 GateEvent 时变 accepted。
- updated_at 对 status/blocked 改变优先用 GateEvent timestamp。

Hidden/degraded details：

- raw stdout/stderr；
- raw runtime states；
- EvidencePackage raw internals；
- 不必要本地路径；
- environment variables；
- secrets/credentials；
- ReviewDecision internal reasoning；
- GateEvent replay internals；
- Commander authorization tokens；
- draft Taskbook claim disputes。

### 9.6 Execution Envelope Minimum Contract = 执行边界最小契约

执行开始前，系统必须知道 goal、stage、scope、allowed actions、forbidden actions、risk、
approval requirement、stop conditions。

Required fields：

- envelope_id、schema_version、task_id、stage_id、parent_refs、actor_role、intent、scope；
- allowed_paths、forbidden_paths、allowed_actions、forbidden_actions；
- risk_level、inputs、target_artifacts、validation_commands、evidence_requirements；
- stop_conditions、approval_required、authority_limits、reporting_destination、expected_receipt_contract。

Parent refs 必须包括 master_taskbook_ref、stage_taskbook_ref、version_taskbook_ref、workspace_head_ref。

Allowed actions within envelope：read、inspect、narrow_edit、run_listed_validation、generate_receipt。

需要 Commander hard gate：dependency_upgrade、lockfile_rewrite、credential_change、remote_action、
broad_formatting、destructive_file_operation、core_state_machine_semantic_change。

Envelope 内禁止：commit、push、release、deploy、force_reset、secret_printing、delivery_state_write。

### 9.7 Execution And Validation Receipt Minimum Contract = 执行与验证回执最小契约

工作运行后，系统必须知道发生了什么、改了什么、跑了什么验证、没跑什么、失败什么、证据在哪里。

Required fields：

- receipt_id、schema_version、envelope_id、task_id、stage_id、actor_role、receipt_source、produced_by；
- workspace_ref_before/after、head_ref_before/after；
- started_at、completed_at、actions_taken、artifacts_changed、validation、result、deviations；
- blocked_reason、command_transcript_digest、envelope_compatibility、integrity_digest、evidence_refs。

Receipt source values：

- runtime_observed；
- imported_from_executor；
- imported_from_external_review；
- manually_attested_by_commander。

不变量：

- completed_unvalidated 绝不能报成 completed_validated；
- checks_run 和 checks_not_run 必须分开；
- result 为 blocked/failed 时 blocked_reason 必填；
- imported receipts 必须声明 provenance 和 envelope compatibility；
- integrity_digest 绑定 record identity，不是真相或授权；
- evidence_refs 必须指向可审查证据，而不是模糊主张。

### 9.8 Delivery State Gate Minimum Contract = 交付状态门最小契约

任务只有在 required receipts、validation status、risks、reviewer requirement、decision record
允许时，才能从一个 state 移到另一个 state。

Required fields：

- gate_id、task_id、stage_id、from_state、to_state；
- required_receipts、required_artifacts、required_validation_status；
- open_risks、reviewer_required、decision_status、decision_ref；
- resulting_gate_event_ref、blocking_conditions。

不变量：

- reviewer_required=true 阻止 automatic pass；
- decision_status 不能自己创建 implementation task；
- decision_ref 必须绑定 review 或 Commander decision evidence；
- 有 transition 或 blocked projection 时需要 resulting_gate_event_ref；
- to_state 必须属于 frozen delivery_state enum；
- accepted/cancelled 是 terminal；
- blocked 是 condition flag；
- returned_for_revision 是 submitted -> in_delivery outcome；
- 缺 decision evidence fail closed。

GateEvent = 状态门事件：

- Delivery State Gate 应用或拒绝 delivery_state transition / item-level blocked change 时产生的 append-only record。
- 它是 accepted、cancelled、returned_for_revision、blocked change 进入用户可见状态的唯一账本事件。
- event_type 包括 transition_applied、transition_rejected、blocker_applied、blocker_cleared、blocker_waived、
  blocker_invalidated、correction_recorded、supersede_recorded。
- GateEvent 是唯一能写 delivery_state 和 delivery_item.blocked 的记录。
- accepted 只能在 blocker_changes 后 blocked=false 时应用。
- rejected GateEvent 不 mutate delivery_state。

### 9.9 Evidence Package Minimum Contract = 证据包最小契约

Evidence Package 是最小 review input，让 Delivery State Gate 知道提交了什么、检查了什么、没检查什么、
还有什么风险、请求什么 decision。它是 evidence，不是 approval，不能 mutate delivery_state。

Required fields：

- evidence_package_id、schema_version、task_ref、submission、state_context、artifacts、checks、
  not_validated、remaining_risks、authority_required。

Task ref：taskbook_id、task_id、scope_ref。

Submission：submitted_by、submitted_at、submitted_summary、requested_gate_action。

requested_gate_action 只是 request，不是 ReviewDecision，也不 apply state transition。取值：

- request_acceptance_review；
- request_revision_review；
- request_blocking_review；
- request_cancellation_review。

State context：delivery_state_seen、condition_flags_seen、state_version_seen。它只是 context，不授予 state-transition authority。

不变量：

- EvidencePackage 是 evidence，不是 approval。
- Hash 是 identity，不是 approval。
- Validation 是 evidence，不是 authorization。
- Runtime outcome 是 signal，不是 delivery_state。
- delivery_state_seen 是 observed context，不是 requested/resulting state。
- blocked 只能在 condition_flags_seen 或 remaining_risks 中出现，不能作为 top-level delivery_state。
- PASSED、COMPLETED、BLOCKED runtime outcomes 不能复制或映射为 delivery_state。
- not_validated 和 remaining_risks 即使为空也要明确。
- ReviewDecision 和 GateEvent 必须绑定 EvidencePackage，不能藏在 EvidencePackage 里面。

### 9.10 Reviewer Handoff And Decision Minimum Contract = 审查交接与决策最小契约

Reviewer 必须收到足够绑定证据，才能决定 ACCEPT、NEEDS_FIX、PLAN_ADJUST、ABORT，而不必重跑整个任务。

Required fields：

- handoff_id、task_id、stage_id、bound_inputs、goal_context、scope_reviewed、changed_artifacts；
- receipts、validation_summary、known_risks、unresolved_questions、review_axes、reviewer_focus；
- decision_needed、next_state_request_shape。

Bound inputs：master_taskbook_ref、stage_taskbook_ref、version_taskbook_ref、execution_report_ref、
workspace_snapshot_ref。

Review axes：charter_alignment、task_completion、scope_assessment、validation_truth、evidence_sufficiency、
residual_risk、unresolved_items。

不变量：

- decision_needed 必须是 ACCEPT / NEEDS_FIX / PLAN_ADJUST / ABORT。
- changed_artifacts 来自 receipts。
- validation_summary 必须区分 validated、unvalidated、not_run、failed、blocked。
- review decisions 首先是 review records。
- lifecycle transitions 需要 separate authority validation。
- reviewer decision 不自动 mutate plan/state/Git/memory/route/remote。
- delivery_state 和 item-level blocked 变化需要 Delivery State Gate GateEvent。

### 9.11 Review Decision Mapping = 审查决策映射

Reviewer output 先成为 review record。它可以请求 state transition，但 delivery_state 只在
Delivery State Gate 用所需 authority basis 产生 GateEvent 时改变。

决策映射：

- `ACCEPT` = 接受。请求效果：submitted -> accepted。只有 Delivery State Gate 可应用。
  如果 actor 缺少 required authority，结果是 gate_review_required，record_outcome 是 acceptance_recommended。
  禁止 automatic push/release/deploy/remote close。
- `NEEDS_FIX` = 需要修复。请求效果：submitted -> in_delivery，outcome 是 returned_for_revision。
  只有 Delivery State Gate 可应用。禁止创建顶层 needs_fix/returned/rejected state，禁止 automatic scope expansion
  和 automatic plan change。
- `PLAN_ADJUST` = 计划调整。无直接 delivery_state change。记录 plan_adjustment_required，
  创建 Commander decision request。可请求 ItemBlocker，但不能直接 set blocked。
- `ABORT` = 中止。无直接 delivery_state change。记录 cancellation_recommended，
  创建 Commander decision request。可请求 ItemBlocker，但不能直接 set blocked；没有 cancellation authority
  时不能变 cancelled。

Compact rule：

- ACCEPT：submitted -> accepted，仅 Gate。
- NEEDS_FIX：submitted -> in_delivery，outcome returned_for_revision，仅 Gate。
- PLAN_ADJUST：不直接改 delivery_state，请求 Commander decision，可请求 ItemBlocker。
- ABORT：不直接改 delivery_state，请求 Commander decision，可请求 ItemBlocker。

Review decision record required fields：

- review_decision_id、item_id、submission_id、delivery_state_at_review；
- taskbook_id、taskbook_version、reviewer_id、reviewer_role、reviewer_authority_scope；
- decision、decision_reason、evidence_refs、created_at、resulting_action、resulting_action_id。

Forbidden shortcuts：

- reviewer_ACCEPT_without_gate -> accepted；
- validation_passed -> accepted；
- approval_recorded -> accepted；
- delivery_complete -> accepted；
- taskbook_claim_satisfied -> accepted；
- runtime_fact_update -> delivery_state_change；
- taskbook_claim_update -> delivery_state_change；
- review_decision / PLAN_ADJUST / ABORT -> delivery_item.blocked without GateEvent；
- blocked=false -> ready/submitted/accepted；
- PLAN_ADJUST -> accepted/in_delivery/ready/cancelled；
- ABORT -> cancelled without explicit Commander or delegated Delivery Authority confirmation；
- submitted artifact in-place change without new submission_id or revision record。

### 9.12 Commander Decision Request Minimum Contract = 指挥官决策请求最小契约

这是向 Commander 请求有边界决策的对象，不是决策本身，也不能 mutate plan、state、Git、memory、
route、bridge 或 remote systems。

Required fields：

- commander_decision_request_id、schema_version、task_id、stage_id；
- source_review_decision_ref、source_evidence_package_ref；
- requested_decision_type、requested_action、scope_ref、authority_needed；
- options、recommended_option、risk_summary、blocked_context、non_mutation_notice、created_at。

Requested decision type：

- accept_via_gate_review；
- return_for_revision_via_gate_review；
- adjust_plan；
- cancel_item；
- defer_decision；
- continue_next_loop。

不变量：

- request only；
- 不 mutate delivery_state；
- 不 mutate plan、Taskbook、Git、memory、route、bridge、remote；
- 从 review feedback 创建时必须绑定 ReviewDecision 和 EvidencePackage；
- 必须说明 executors 是否可在无 Commander input 时继续；
- recommended_option 和 authorized_action 必须分开；
- authority_needed 缺失 fail closed。

### 9.13 Audit Event Minimum Contract = 审计事件最小契约

AuditEvent 是小型 append-only trace record，用来绑定 actor、authority basis、envelope、receipt、
evidence、redaction posture。它不是大型 audit platform，也不是 state authority。

Required fields：

- audit_event_id、schema_version、event_type、actor、authority_basis；
- envelope_ref、receipt_ref、evidence_refs、gate_event_refs、commander_decision_request_refs；
- workspace_ref、created_at、redaction_status、secrets_checked、mutation_allowed、integrity_digest。

Event types：

- envelope_created / envelope_rejected；
- execution_started；
- receipt_recorded；
- evidence_package_created；
- review_decision_recorded；
- gate_event_recorded；
- commander_decision_requested；
- administrative_correction_recorded；
- supersede_recorded。

不变量：

- append-only；
- trace evidence，不是 delivery_state authority；
- `mutation_allowed` 默认 false，除非单独 envelope 或 GateEvent 授权；
- external reporting 前 secrets_checked 必须明确；
- redaction_status 区分 redacted、not_needed、pending_review；
- integrity_digest 绑定事件身份，不是真相或授权；
- 不得包含 secrets、credentials 或 raw chain-of-thought。

---

## 10. Standard Reference Objects = 标准引用对象

### 10.1 Master Taskbook Reference

```yaml
master_taskbook_ref:
  id: colameta_master_taskbook_v1
  path: PROJECT_MASTER_TASKBOOK.md
  hash: sha256:...
```

用途：证明当前任务仍绑定同一 project goal，防止 planner/reviewer drift。

### 10.2 Stage Taskbook Reference

```yaml
stage_taskbook_ref:
  id: stage_01_master_taskbook_anchoring
  path: docs/taskbooks/stages/STAGE_01_MASTER_TASKBOOK_ANCHORING.md
  hash: sha256:...
```

用途：证明 version 属于某个具体 stage，防止 version tasks 偏离 stage goals。

### 10.3 Review Feedback Record

Review feedback record 包含 review_id、version、decision、bound inputs、charter_alignment、
task_completion、scope_assessment 和 required_action。

Decision 值只允许 ACCEPT、NEEDS_FIX、PLAN_ADJUST、ABORT。

Required action 类型包括 CONTINUE_PREVIEW、FIX_PREVIEW、PLAN_ADJUST_PREVIEW、
CANCELLATION_DECISION_REQUEST。

---

## 11. Standard Workflow = 标准流程

### 11.1 Master Taskbook Registration

流程：

```text
ChatGPT / Commander drafts PROJECT_MASTER_TASKBOOK.md
  -> ColaMeta previews registration
  -> required fields are validated
  -> master_taskbook_hash is calculated
  -> Commander confirms apply
  -> future stage and version tasks must reference that hash
```

Readiness criteria：Master 可读、hash 稳定、缺 master goal fail validation、普通 version tasks
不能静默修改 Master、Master 修改需要 hard gate。

### 11.2 Stage Taskbook Registration

流程：

```text
ChatGPT creates Stage Taskbook from Master
  -> ColaMeta validates master_taskbook_ref
  -> stage_taskbook_hash is calculated
  -> Stage Taskbook registered
  -> version tasks under that stage must reference it
```

Readiness criteria：Stage 必须说明为什么服务 master goal，声明 out_of_scope，定义 gate-readiness，
缺 master_taskbook_ref 被拒。

### 11.3 Version Taskbook Execution

流程：

```text
ChatGPT creates version execution taskbook
  -> ColaMeta validates master/stage refs
  -> ColaMeta validates allowed/forbidden files and acceptance commands
  -> ColaMeta inserts plan version
  -> Codex executes
  -> ColaMeta collects diff / validation / scope / audit
  -> ColaMeta generates Reviewer Handoff Package
  -> Reviewer feedback required before long-run continuation
```

### 11.4 Review Feedback Intake

流程：

```text
Reviewer reads handoff package
  -> Reviewer checks master/stage/version taskbooks and evidence
  -> Reviewer emits structured review_feedback
  -> ColaMeta previews feedback intake
  -> version/report/workspace/taskbook hashes validated
  -> apply records classified feedback and prepares next-state Commander decision request
```

---

## 12. Review Feedback Decision Policy = 审查反馈决策策略

只识别四个 decision：

- `ACCEPT`：Reviewer 记录接受当前 scope；accepted delivery state 仍需要 Delivery State Gate GateEvent。
  ColaMeta action 是 record_accept_review 并请求 submitted -> accepted Gate review。
- `NEEDS_FIX`：当前 version 需要 bounded fix。ColaMeta 记录 fix_required，并请求 submitted -> in_delivery
  with returned_for_revision Gate review。不得扩 scope 或无权改 plan。
- `PLAN_ADJUST`：当前 plan 需要调整。ColaMeta 记录 plan_adjustment_required 并创建 Commander decision request。
  不得直接 mutate delivery_state 或 apply plan change。
- `ABORT`：当前 version 或 stage 应停止。ColaMeta 记录 cancellation_recommended 并创建 Commander decision request。
  没有 explicit authority 不能把 state 改 cancelled。

重要说明：

- ACCEPT 不是 automatic continue。
- ACCEPT 只记录 acceptance recommendation 并请求 Delivery State Gate review。
- PASS 只是 legacy alias，只有 migration/compatibility policy 显式映射时才等于 ACCEPT。
- `continue_next_version` 仍是 controlled action。

---

## 13. Long-Term Roadmap = 长期路线

完整 ColaMeta 路线分成 10 个 stages。

Master 定义 stage goals 和 taskbook granularity，不定义详细 implementation steps。
详细实现交给 Stage Taskbooks 和 Version Execution Taskbooks。

---

## 14. Stage 0: Baseline Closeout And Execution-State Clarity

Stage 0 = 基线收束与执行状态清晰化。

目标：让 executor reports、validation state、runtime status、workspace status 可信且可解释。

服务 Master 目标的原因：如果系统不能可靠解释“跑了什么、改了什么、什么过了、什么陈旧、
executor session 是当前工作还是历史 metadata”，就无法目标锚定。

Deliverables：

- validation truth-source hardening；
- trusted executor report；
- trusted audit package；
- read-only runtime version observability；
- loaded-code verification；
- executor-session head mismatch classification；
- explainable local/remote baseline。

Gate-readiness：

- validation failure 不能总结为 passed；
- validation_inconsistent 可识别；
- audit packages 暴露 truth-source evidence；
- runtime loaded-code freshness 可解释；
- executor-session HEAD mismatch 无 mutation 分类；
- local commit 和 remote sync state 分开记录。

Non-goals：不增加新产品治理能力、不扩 executor authority、不做 review feedback system、
不做 dashboard、不做 automatic runtime cleanup。

---

## 15. Stage 1: Master Taskbook Anchoring

Stage 1 = 主任务书锚定。

目标：允许 ColaMeta register、freeze、validate、hash、reference Project Master Taskbook。

原因：没有 master goal anchor，stage taskbooks、version taskbooks、review feedback 没有最高引用，
planner/executor 会随时间漂移。

Deliverables：

- `PROJECT_MASTER_TASKBOOK.md` format；
- master_taskbook schema / validator / hash / registry；
- master_taskbook change hard-gate policy。

Version directions：

- v1.10 Executor Session Head Mismatch Classification；
- v1.11 Master Taskbook Registry V1；
- v1.12 Master Taskbook Schema + Validator V1；
- v1.13 Master Taskbook Hash Binding V1；
- v1.14 Master Taskbook Change Policy V1。

Gate-readiness：Master 可注册、可读、可 hash、缺 core fields fail、普通 tasks 不可静默修改、
Master 修改需要 Commander hard gate。

Non-goals：不做 automatic master-plan generator、ColaMeta-authored project goals、Web UI requirement、
state-machine rewrite、automatic review。

---

## 16. Stage 2: Stage Taskbook Management

目标：允许 ColaMeta register Stage Taskbooks，并要求每份 Stage Taskbook 绑定 Project Master Taskbook。

原因：Master goal 太大，不能直接塞进每个执行任务。Stage Taskbooks 把它转成有边界的阶段目标。

Deliverables：

- stage_taskbook schema / validator / registry / hash；
- stage-to-master binding；
- stage gate-readiness contract。

Gate-readiness：

- Stage Taskbook 必须 reference master_taskbook_ref；
- 必须说明 supports_project_goal；
- 必须声明 non_goals / out_of_scope；
- 必须定义 gate-readiness criteria；
- hash 可被 version tasks 引用。

Non-goals：no stage execution、no automatic stage-goal generation、no automatic master-goal adjustment、no dashboard。

---

## 17. Stage 3: External Taskbook Import Protocol

目标：定义 ChatGPT / Commander 写出的 version execution taskbooks 如何进入 ColaMeta。

ColaMeta 不作为 autonomous planning brain 自动生成这些 taskbooks，但必须严格 validate。

实际 workflow：

```text
ChatGPT authors taskbook
  -> ColaMeta validates, records, prepares for separately authorized freezing/adoption
  -> Codex executes bounded task
  -> Reviewer checks drift
```

Deliverables：

- external_taskbook schema / validator；
- taskbook import preview / apply；
- taskbook-to-plan mapping；
- taskbook rejection reasons。

Gate-readiness：taskbook 必须包含 master_taskbook_ref、stage_taskbook_ref、allowed/forbidden files、
acceptance_commands、manual_acceptance、out_of_scope、supports stage/master goals；invalid format 或 hash mismatch fail closed。

Non-goals：no automatic goal expansion、dangerous-scope completion、allowed_files expansion、executor dispatch、commit。

---

## 18. Stage 4: Bounded Execution And Evidence

目标：把 registered version taskbooks 转成 bounded machine-checkable execution envelopes，并记录可信本地
execution evidence 或 imported execution receipts。

核心问题：

- taskbook 是否被遵守？
- scope 是否被遵守？
- validation 是否通过？
- work 是否仍 goal-bound？
- reviewer 是否能判断？

Deliverables：

- execution envelope contract；
- rejection rules；
- executor run preview；
- bounded local executor run 或 imported receipt；
- changed files report；
- execution evidence receipt；
- validation truth report；
- scope check report；
- audit package；
- taskbook binding in report。

Gate-readiness：envelope machine-checkable；invalid envelope dispatch 前 fail closed；run 绑定 version taskbook；
report 包含 master/stage hashes；receipt 区分 executed 与 validated；validation receipt 区分 validated/
unvalidated/not_run/failed/blocked；失败不能总结为 passed；scope violation explicit；executor 不 auto commit、
不 auto continue next version、不 auto promote delivery state。

Non-goals：不是 general executor-dispatch platform，不要求 multi-provider dispatcher、router integration、
automatic repair/review/continue/commit/push。

---

## 19. Stage 5: Reviewer Handoff Package

目标：version execution 完成后，ColaMeta 为 Reviewer 生成 review package。

Reviewer 不能只看最终代码；需要 goal、taskbook、diff、validation、risk、drift evidence。

Deliverables：

- reviewer handoff package schema / generator；
- alignment questions；
- drift questions；
- recommended decision options；
- report excerpt；
- diff summary；
- validation truth summary。

Gate-readiness：handoff 包含 master-goal、stage-goal、version-task summary、changed_files、
validation truth、scope evidence；要求 Reviewer 判断 drift；提供 limited decision options。

Non-goals：不替代最终 Reviewer，不自动声称 aligned，不自动 release next-version，不把 handoff package 当 acceptance pass。

---

## 20. Stage 6: Review Feedback Intake

目标：把 Reviewer decisions 作为 structured feedback 回到 ColaMeta，并分类成 next-state Commander decision request。

原因：如果 review results 只是自由聊天，ColaMeta 无法可靠请求下一受控决策。Feedback 必须绑定 version、
report、Git HEAD、taskbook hashes，但不能自动 state transition 或 execution command。

Deliverables：

- review_feedback schema / validator / preview；
- review_feedback classification；
- next_state Commander decision request；
- review decision mapping；
- feedback audit record。

Gate-readiness：

- 只识别 ACCEPT / NEEDS_FIX / PLAN_ADJUST / ABORT；
- PASS 只有显式 policy 映射时才是 ACCEPT alias；
- feedback 必须绑定 execution_report_ref、workspace_snapshot_ref、master_taskbook_hash、stage_taskbook_hash；
- 必须包含 charter_alignment / task_completion / scope_assessment；
- binding mismatch fail closed；
- ACCEPT 只记录 acceptance recommendation 并请求 Gate review；
- NEEDS_FIX 只记录 returned_for_revision recommendation 并请求 Gate review；
- PLAN_ADJUST 创建 Commander decision request，不自己 mutate plan；
- ABORT 创建 Commander decision request，不自己 cancel/delete/revert；
- feedback classification 不自己 mutate plan、route、delivery state、Git state 或 memory。

Non-goals：no automatic review conclusion inference、vague feedback intake、unbound feedback、automatic plan modification、
automatic state transition、automatic executor continuation、automatic commit。

---

## 21. Stage 7: Drift Evidence And Correction

Post-MVP，MVP excluded。

目标：收集并组织 drift evidence，让 Reviewer 判断项目是否偏离 master goal。ColaMeta 不能独自声称复杂语义对齐。

Deliverables：drift evidence pack、executor/task/stage drift evidence、master goal alignment questions、
reviewer drift checklist、plan adjustment trigger conditions。

Post-MVP readiness：review packages 包含 drift questions；Reviewer 必须回答 work 是否仍服务 master goal；
ColaMeta 不自动声明 semantic alignment；PLAN_ADJUST 进入 plan adjustment flow。

Non-goals：no ColaMeta-only semantic drift judgment、automatic taskbook rewrite、automatic master-goal change、
automatic stage-scope expansion。

---

## 22. Stage 8: Plan Adjustment Control Plane

Post-MVP，MVP excluded。

目标：Reviewer 判断 plan 需要调整时，ColaMeta 生成 controlled plan adjustment preview，而不是直接修改 plan。

Deliverables：plan adjustment request schema、plan adjustment preview、stage/version taskbook adjustment preview、
master taskbook hard gate policy、adjustment audit record。

Post-MVP readiness：PLAN_ADJUST 只能生成 preview；plan adjustment 不能直接 apply；调整必须解释为什么仍服务 master goal；
Master 修改需要 Commander hard gate；Stage 修改要 reference master hash；Version 修改要 reference stage hash；
所有 adjustment auditable。

Non-goals：no automatic master-goal change、task-scope expansion、Reviewer bypass、automatic next-stage entry。

---

## 23. Stage 9: Controlled Continue And Long-Run Trace

Post-MVP，MVP excluded。

目标：review 产生 eligible decision 后，允许 ColaMeta 在受控 gates 下进入下一 version 或 stage。

Deliverables：controlled continue gate、review-decision-required policy、stage closeout review、
next-version readiness report、long-run project trace。

Post-MVP readiness：没有 ACCEPT 和 separate continue gate，`continue_next_version` 不能自动运行；
继续前必须检查 taskbook hashes；stage end 生成 stage closeout；long-run trace 解释每一步为什么发生。

Non-goals：no infinite execution loop、skipped review、automatic commit/push、unauthorized stage entry。

---

## 24. MVP Boundary = MVP 边界

MVP 包括 Stage 0-6，称为 Stage 0-6 Thin Governed Loop。Stage 7-9 是 post-MVP。

MVP 是最小可用治理交付闭环，不是完整 long-run automation system。

MVP 形态：

```text
Master Taskbook registered
  -> Stage Taskbook bound to Master
  -> Version Taskbook imported
  -> Machine-checkable execution envelope authorized
  -> Bounded local execution or execution receipt recorded
  -> Reviewer Handoff Package generated
  -> Review Feedback classified into next-state request
```

MVP proof loop：

```text
baseline reality
  -> Master Taskbook anchor
  -> Stage Taskbook binding
  -> Version Execution Taskbook / authorized envelope
  -> bounded local execution or imported receipt
  -> validation receipt and execution evidence
  -> evidence-backed Reviewer Handoff Package
  -> classified next-state Commander decision request
```

Included stages：

- Stage 0 Baseline closeout and execution-state clarity；
- Stage 1 Master Taskbook anchoring；
- Stage 2 Stage Taskbook management；
- Stage 3 External taskbook import；
- Stage 4 Bounded envelope, execution evidence, and receipt；
- Stage 5 Reviewer Handoff Package；
- Stage 6 Review feedback classification and next-state decision request。

MVP implementation mode：minimal governance primitives，不是 full automation layers。

Stage 7-9 hooks 在 MVP 中只能是 route-integrity blockers 和 evidence fields，不授权 drift correction、
plan mutation、route transition、execution continuation、scope expansion、P0 closure 或 remote action。

### 24.1 Stage 0-6 Thin Governed Loop Readiness Contract

它定义 MVP 每一阶段最低必须证明什么。它是 static contract，不是 live progress tracker、dashboard、
approval queue、runtime state table 或 executor dispatch plan。

Allowed Master-level fields：

- Stage；
- Minimum readiness claim；
- Required evidence；
- Gate question；
- Explicit non-goal。

Excluded tracker fields：

- dynamic status、owner、due date、priority、risk score、dependency graph、executor dispatch plan、workflow history。

各阶段最小 readiness：

- Stage 0：baseline state 已知到足以开始 governed claims。证据是 baseline snapshot、known unknowns、
  local/runtime note。问题：后续 claims 是否从 declared baseline 开始。非目标：full audit/cleanup/dashboard。
- Stage 1：work 锚定到 `project_final_goal`。证据是 Master goal、MVP scope、authority rules、stage list。
  问题：下游 claim 是否追溯到 single final goal。非目标：multi-goal portfolio planning。
- Stage 2：Stage Taskbooks 表达 bounded stage claims。证据是 stage objective、bounds、evidence expectation、
  gate-readiness criteria。问题：stage claims 是否区别于 accepted state。非目标：state authority/workflow platform。
- Stage 3：External taskbooks 只作为 claims 进入。证据是 source、provenance、import receipt、
  normalized claims、conflicts。问题：claims 能否被审查而不变成 facts。非目标：trusted state import/general ingestion。
- Stage 4：execution bounded 且 evidence-backed。证据是 envelope、runtime actions、touched artifacts、
  validation receipt、risks。问题：是否能从 evidence 判断 acceptance，而不是 taskbook claims。非目标：general dispatch platform。
- Stage 5：reviewer handoff self-contained。证据是 claim-to-evidence package、validation status、risks、known gaps。
  问题：Reviewer 是否能不重建上下文就判断。非目标：acceptance itself。
- Stage 6：feedback 变成 Commander next-state request。证据是 feedback receipt、classification、
  requested next-state decision。问题：Commander 能否授权 stop/rework/defer/accept/next loop。非目标：
  plan mutation、state promotion、execution continuation。

Universal stop predicates：

- `missing_authority` = 缺少权威来源。
- `boundary_conflict` = 越过授权边界。
- `state_conflict` = Taskbook claim 与 Runtime facts 或 workspace reality 冲突。
- `acceptance_unknown` = 证据不足以让 Gate 或 Commander 判断 accept/rework/defer/stop/next loop。

MVP excluded：

- full long-run health report、dashboard、automatic drift scoring、automatic plan-adjust apply、automatic continue loop、
  required Web UI、remote release system；
- codex-router bridge implementation/adapter/schema/runtime/shared state/executor dispatch/remote action；
- Goal Boundary Contract implementation/schema/adapter/state-machine/runtime/executor dispatch；
- general executor-dispatch platform；
- automatic delivery-state promotion；
- review feedback 自己 apply plan/route changes。

### 24.2 Thin Loop Freeze Readiness

freeze-candidate 前必须满足：

- Stage 0-6 被描述为一个 governed proof loop；
- Stage 4 限于 machine-checkable envelope + evidence/receipt；
- Stage 6 限于 feedback classification + next-state Commander decision request；
- envelope dispatch 前拒绝 invalid parent hashes、paths、actions、stop conditions、evidence requirements；
- receipt semantics 区分 validated、unvalidated、not_run、failed、blocked；
- Delivery State Gate 定义 finite states、allowed transitions、evidence per transition、forbidden auto-promotions；
- GateEvent 是唯一能写 delivery_state 或 item-level blocked projection 的 append-only event；
- CommanderDecisionRequest request-only，不能 mutate plan/state/Git/memory/route/bridge/remote；
- AuditEvent 是 append-only trace evidence，不是 delivery_state authority；
- Reviewer handoff package 足够支持 accept/needs_fix/plan_adjust/abort；
- codex-router 保持 future_bridge_candidate，位于 MVP execution path 外；
- discussion_draft、observed hashes、review packets 不可被当作 freeze/canonicalization/commit/push/memory-write/
  bridge/remote authority。

---

## 25. Hard Gates = 硬门

以下动作需要 Commander hard gate：

- 修改 Project Master Taskbook canonical fields；
- 改 ColaMeta product positioning；
- 允许 ColaMeta auto-generate master plans；
- 允许 ColaMeta auto-review；
- 允许 ColaMeta auto-commit；
- 允许 ColaMeta git push / release / deploy；
- 扩 executor authority；
- 改 preview/apply safety model；
- 修改 core state machine；
- 增加 remote mutation surface；
- 修改 Master canonical hash policy；
- 激活 codex-router bridge work；
- 把 Goal Boundary Contract 提升为 runtime architecture；
- 把 AGENTS OS resident-Agent rights 引入 ColaMeta executors；
- 改 Semantics-to-Mechanics canonical rows；
- 改 Forbidden Claims / Boundary Law。

---

## 26. Near-Term Priorities = 近期优先级

Priority 0：保护当前 baseline reality。保持 v1.9 remote baseline 和 v1.10 local plan baseline 清楚记录。

Readiness：v1.9 在 origin/main 已知；v1.10 plan/prompt baseline 是 local ahead-of-origin work；
新 executor run 或 commit 前 current worktree 可解释；不存在 stale draft 说 v1.10 是 Master Taskbook Registry。

Priority 1：保留已完成本地 v1.10 Executor Session Head Mismatch Classification。

此安全修正已在本地 implementation commit `640a843` 完成，用于防 route confusion。但它不授权 remote sync
或新 execution route。

Priority 2：审查并迭代此 Master Taskbook draft。

Priority 3：进入 Master Taskbook Registry V1。之前草稿叫 v1.10；修正路线推迟到 v1.11 或以后。

Priority 4：建立 Stage Taskbook Binding。

Priority 5：建立 External Taskbook Import。

Priority 6：建立 Review Handoff And Feedback Intake。

---

## 27. How To Use This Draft = 如何使用此草稿

允许用途：

- planning discussion baseline；
- route review reference；
- stage taskbook drafting input；
- version taskbook alignment context；
- reviewer orientation；
- future canonicalization candidate。

禁止用途：

- 不可当作 active canonical hash anchor；
- 不可直接交给 Codex 做 one-shot implementation；
- 不可替代 Stage Taskbooks；
- 不可替代 Version Execution Taskbooks；
- 不可替代 Review Feedback；
- 不可作为 push/release/deploy automatic authorization。

---

## 28. Next Step = 下一步

下一步不是重启整条路线。路线是：

1. 保持本地 v1.10 plan 和 implementation baseline 与 Master Taskbook draft 分开。
2. 任何后续 executor run、commit、push 或 route transition 前，先对账 v1.10 local status。
3. 继续讨论 `PROJECT_MASTER_TASKBOOK.md` 草稿。
4. 只有在单独 hash-specific Commander authorization 且全部 activation requirements 满足后，才考虑从
   `discussion_draft` 进入 `active_candidate` 或 `freeze_candidate`。
5. 之后才生成 Stage 1 taskbook 和 Master Taskbook Registry V1 version taskbook。

Remote push 仍是单独 remote mutation，不被本文档授权。
