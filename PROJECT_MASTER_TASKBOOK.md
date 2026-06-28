# ColaMeta Project Master Taskbook v1

```yaml id="master-taskbook-canonical-summary"
master_taskbook:
  document_type: project_master_taskbook
  id: colameta_master_taskbook_v1
  canonical_name: Master Taskbook
  aliases:
    - Project Charter
    - 项目宪章
    - 项目总目标大任务书
  project: ColaMeta
  version: v1
  status: discussion_draft
  canonical_path: PROJECT_MASTER_TASKBOOK.md

  owner: Commander / Jenn
  planning_authority: ChatGPT / Commander
  execution_governance_layer: ColaMeta
  executor_authority: Codex / other bounded executors
  review_authority: ChatGPT Reviewer / Codex Commander / Human Commander

  draft_notice: >
    This is not the final frozen Master Taskbook. It is a reality-calibrated
    discussion draft stored in the project so future planning rounds have a
    shared anchor. It must not be treated as an active canonical hash anchor
    until Commander confirmation and the activation requirements are satisfied.

  project_final_goal:
    status: commander_confirmed_for_discussion_draft
    applies_to: current_design_draft
    goal: >
      Design and evolve ColaMeta into a goal-anchored AI delivery command layer
      that can preserve the Commander-confirmed project final goal across
      Master, Stage, and Version taskbooks; constrain local execution through
      machine-checkable envelopes; produce evidence-backed review handoffs; and
      request Commander-controlled next-state decisions without silent drift,
      hidden authority expansion, or unverifiable completion claims.
    mvp_proof_shape: >
      The MVP proof is the Stage 0-6 Thin Governed Loop: goal anchor, taskbook
      binding, version task import, bounded execution envelope, execution and
      validation receipts, reviewer handoff, and classified next-state Commander
      decision request.
    non_authorization: >
      This goal does not authorize implementation, freeze, commit, push,
      remote action, memory write, bridge activation, route transition, or
      automatic state promotion unless separately and explicitly approved.

  current_known_state:
    observed_at: "2026-06-28"
    development_repo: /home/jenn/src/colameta-dev
    stable_service_runtime: /home/jenn/tools/colameta
    local_branch: main
    local_head: 640a843
    origin_main: 1caa0b2
    local_ahead_origin_main: 2
    latest_remote_completed_implementation_version: v1.9
    v1_9_remote_sync: pushed_to_origin_main
    latest_local_plan_baseline_version: v1.10
    latest_local_completed_implementation_version: v1.10
    v1_10_name: Executor Session Head Mismatch Classification
    v1_10_plan_baseline_commit: 487541f
    v1_10_implementation_commit: 640a843
    v1_10_remote_sync: not_pushed_at_observation_time
    master_taskbook_worktree_state: untracked_discussion_draft
    route_correction: >
      Earlier drafts treated v1.10 as Master Taskbook Registry V1.
      The current project route inserts v1.10 as an execution-state
      clarification slice for executor-session HEAD mismatch. Master
      Taskbook Registry V1 is therefore deferred to v1.11 or a later
      explicitly approved version.
    current_delivery_state_control_reality:
      status: observed_current_implementation
      summary: >
        Current ColaMeta implementation uses distributed state advancement
        control: runner state, version status, state mutation gateway,
        acceptance rerun, checkpoint review, continue-next-version workflow,
        and executor-session safeguards are separate cooperating mechanisms.
      chinese_meaning: >
        当前 ColaMeta 不是一个统一的交付状态门对象，而是由状态记录、版本状态、
        状态变更网关、验收、审查、继续下一版本流程、executor 会话保护等机制
        分散协作来控制状态推进。
  delivery_state_gate_freeze_target:
    status: freeze_target_not_current_runtime
    summary: >
      The freeze target is to upgrade the distributed state advancement
      control reality into a unified Delivery State Gate governance contract.
    chinese_meaning: >
      冻结目标不是假装当前已经有完整状态门，而是把现有的分散式状态推进控制
      收束升级为统一的 Delivery State Gate / 交付状态门治理契约。

  state_authority_contract_decision:
    status: commander_confirmed_for_discussion_draft
    adopted_name: State Authority Contract
    chinese_name: 状态权责契约
    supersedes_discussion_label: State Ownership Contract
    supersedes_discussion_label_chinese: 状态归属契约
    summary: >
      State is separated into authority domains: taskbooks own intent and
      declarations, Runtime owns observed facts, Delivery State Gate owns
      acceptance and transition judgment, and the user-visible state is only
      a projection of accepted declarations, verified evidence, and gate
      decisions.
    chinese_meaning: >
      状态不是简单问归谁，而是拆成权责：任务书拥有意图和主张，Runtime
      拥有观测事实，Delivery State Gate 拥有接受裁决和状态转换判断，
      用户看到的状态只是已接受主张、已验证证据、门控裁决的投影。

  delivery_state_transition_model_decision:
    status: commander_confirmed_for_discussion_draft
    adopted_name: Minimal Delivery State Transition Model
    chinese_name: 最小交付状态转换模型
    summary: >
      Master freezes a small canonical delivery lifecycle:
      proposed, ready, in_delivery, submitted, accepted, cancelled.
      Blocked, returned, gate review, validation, approval, and delivery are
      conditions, transition outcomes, processes, or facets; they are not MVP
      top-level delivery states.
    chinese_meaning: >
      Master 冻结一条很小的交付生命周期主线：已提出、已就绪、
      交付中、已提交验收、已接受、已取消。受阻、退回、状态门审查、
      验证、批准、交付送达都不是 MVP 顶层交付状态，而是条件、转移结果、
      过程或分层字段。

  review_decision_mapping_decision:
    status: commander_confirmed_for_discussion_draft
    adopted_name: Review Decision Mapping
    chinese_name: 审查决策映射
    summary: >
      Reviewer decisions are review records first. Only some review records
      may request a delivery-state transition. The transition is applied only
      by Delivery State Gate through a GateEvent, using Commander or delegated
      Delivery Authority as authority basis when required.
    chinese_meaning: >
      审查决策首先是审查记录，不是状态按钮。只有当审查者或后续裁决者
      拥有足够权威依据时，部分审查记录才可以请求交付状态迁移；真正写入
      状态的仍然只能是 Delivery State Gate 产生的 GateEvent。

  taskbook_layer_responsibility_decision:
    status: commander_confirmed_for_discussion_draft
    adopted_name: Layer Responsibility Contract
    chinese_name: 三层任务书职责边界契约
    summary: >
      Master, Stage, and Version taskbooks define bounded claims and
      execution envelopes; they do not own state authority. Master owns
      project doctrine, the single project_final_goal, and responsibility
      boundaries. Stage owns repeatable governed delivery protocols.
      Version owns concrete delivery-attempt claims, evidence references,
      review references, and gate requests.
    chinese_meaning: >
      Master / Stage / Version 三层任务书不是三个状态权威，也不是三个互相
      复制的计划。Master 管项目最终目标和全局边界；Stage 管阶段交付契约；
      Version 管一次具体执行的声明和证据。正式是否接受，只能由
      Delivery State Gate 判断。

  goal_statement_policy:
    status: commander_confirmed_for_discussion_draft
    single_complete_goal_statement: project_final_goal
    no_separate_short_goal_phrase: true
    no_separate_north_star_goal: true
    user_promise: >
      ColaMeta lets users delegate project work to a controlled,
      reviewable, and correctable AI execution team.
    mechanism_summary: >
      ColaMeta binds goals, taskbooks, execution envelopes, executors, evidence,
      gates, review feedback, and project state so long-running AI delivery can
      move forward without silent drift or unauthorized expansion.

  product_identity_constraint_decision:
    status: commander_confirmed_for_discussion_draft
    chinese_name: 产品定位边界决策
    derived_from: project_final_goal
    no_separate_positioning_phrase: true
    canonical_user_promise: goal_statement_policy.user_promise
    wrong_positioning:
      - automatic_project_manager
      - automatic_planning_brain
      - automatic_product_owner
      - automatic_reviewer
      - automatic_release_system
      - unbounded_autonomous_agent_framework
      - executor_without_scope_limits
    chinese_meaning: >
      ColaMeta 的定位由项目最终目标约束。它不是自动项目经理、自动规划脑、
      自动产品负责人、自动审查者或自动发布系统，而是目标锚定的 AI 交付指挥层。

  minimum_irreplaceable_capability_set:
    status: commander_confirmed_for_discussion_draft
    decision_summary: >
      ColaMeta is irreplaceable only if it keeps AI delivery anchored to the
      agreed goal across taskbooks, execution envelopes, bounded execution,
      evidence, review, state advancement, and Commander-controlled stops.
    capabilities:
      - goal_and_taskbook_anchoring
      - three_level_taskbook_model_master_stage_version
      - execution_envelope
      - bounded_executor_dispatch
      - evidence_and_reviewer_handoff_package
      - delivery_state_machine
      - review_feedback_intake_and_next_state_decision_request
      - commander_gate_stop_boundary_and_observable_status_surface

  mvp_shape_decision:
    status: commander_confirmed_for_discussion_draft
    name: Stage 0-6 Thin Governed Loop
    meaning: >
      Stage 0 through Stage 6 define one thin governed proof loop, not seven
      full product layers and not a standing authorization to build every
      implied automation surface.
    downgraded_stage_scopes:
      stage_04: >
        Bounded execution means a machine-checkable execution envelope plus
        local execution evidence or an imported execution receipt. It does not
        require a new general executor-dispatch platform in MVP.
      stage_06: >
        Review feedback intake means structured classification and a
        next-state Commander decision request. It does not automatically mutate
        plans, advance delivery state, continue execution, or apply route
        changes.
    freeze_before_conditions:
      - machine_checkable_execution_envelope_contract
      - validation_receipt_semantics
      - finite_delivery_state_gate
      - gate_event_minimum_contract
      - commander_decision_request_minimum_contract
      - audit_event_minimum_contract
      - state_authority_contract
      - minimal_delivery_state_transition_model
      - review_decision_mapping
      - taskbook_layer_responsibility_contract
      - stage_0_6_readiness_contract
      - reviewer_handoff_minimum_template
      - codex_router_mvp_exclusion
      - discussion_draft_authority_boundary

  stage_0_6_readiness_contract_decision:
    status: commander_confirmed_for_discussion_draft
    adopted_name: Stage 0-6 Thin Governed Loop Readiness Contract
    chinese_name: 阶段 0-6 薄治理闭环就绪契约
    summary: >
      Stage 0 through Stage 6 are one static MVP readiness contract, not seven
      independent product layers and not a live project tracker. Each stage
      must state the minimum readiness claim, required evidence, gate question,
      and explicit non-goal needed for the next governed boundary decision.
    chinese_meaning: >
      Stage 0-6 是一条最小可审查闭环，不是七个大产品模块，也不是实时进度表。
      每个阶段只说明最低要证明什么、需要什么证据、Gate 或 Commander 要回答
      什么问题、以及这个阶段明确不做什么。
    static_contract_not_tracker: true
    required_static_fields:
      - stage
      - minimum_readiness_claim
      - required_evidence
      - gate_question
      - explicit_non_goal
    excluded_dynamic_tracker_fields:
      - dynamic_status
      - owner
      - due_date
      - priority
      - risk_score
      - dependency_graph
      - executor_dispatch_plan
      - workflow_history
    universal_stop_predicates:
      missing_authority: 缺少权威来源
      boundary_conflict: 越过授权边界
      state_conflict: 任务书声明和 Runtime 事实冲突
      acceptance_unknown: 证据不足以让 Gate 判断

  future_bridge_candidates:
    - id: codex_router_future_bridge_candidate
      status: future_bridge_candidate
      implementation_route: not_in_current_route
      runtime_status: non_runtime
      mvp_dependency: false
      upstream_layer: ColaMeta
      downstream_layer: codex-router
      boundary_summary: >
        ColaMeta may integrate with codex-router as a downstream local-first
        governance, routing, approval, execution-control, validation, and
        audit-evidence harness. The bridge boundary is TaskEnvelope in;
        RoutingDecision, preflight, approval, execution grant, validation, and
        audit evidence out.
      non_authorization: >
        This candidate does not authorize implementation, adapter work, schema
        work, runtime integration, shared state, executor dispatch, remote
        writes, or changes to the near-term implementation route.
    - id: goal_boundary_contract_future_bridge_candidate
      status: future_bridge_candidate
      implementation_route: not_in_current_route
      runtime_status: non_runtime
      mvp_dependency: false
      upstream_layer: ColaMeta
      downstream_layer: future bridge boundary contract
      boundary_summary: >
        Goal Boundary Contract is a downgraded, non-runtime future bridge
        concept for describing goal, scope, authority, pause and unknown zones,
        memory limits, executor permissions, and return-key conditions.
      non_authorization: >
        This candidate does not authorize implementation, schema work, adapter
        work, state-machine changes, runtime integration, executor dispatch,
        remote writes, or changes to the near-term implementation route.

  non_goals:
    - Do not automatically generate the full project master plan.
    - Do not replace ChatGPT / Commander route judgment.
    - Do not replace Reviewer final judgment.
    - Do not allow executors to silently expand task scope.
    - Do not allow ordinary version tasks to silently change the master goal.
    - Do not automatically run infinite repair loops.
    - Do not automatically commit, push, tag, release, or deploy.
    - Do not bypass preview / apply / review / audit boundaries.
    - Do not mix planning authority, execution authority, and review authority.

  governance_principles:
    - planning_authority_is_external
    - execution_authority_is_bounded
    - review_authority_is_separate
    - state_transition_requires_structured_decision
    - master_goal_changes_require_commander_hard_gate
    - every_stage_and_version_must_bind_to_master_taskbook
    - semantic_alignment_is_reviewed_not_auto_claimed

  required_bindings:
    - master_taskbook_ref
    - stage_taskbook_ref
    - version_taskbook_ref
    - executor_report_ref
    - review_feedback_ref

  mvp_boundary:
    included_stages:
      - stage_00_baseline_closeout
      - stage_01_master_taskbook_anchoring
      - stage_02_stage_taskbook_management
      - stage_03_external_taskbook_import
      - stage_04_bounded_execution_and_evidence
      - stage_05_reviewer_handoff_package
      - stage_06_review_feedback_intake
    post_mvp_stages:
      - stage_07_drift_evidence_and_correction
      - stage_08_plan_adjustment_control
      - stage_09_controlled_continue_and_long_run

  success_criteria:
    - A project master taskbook can be registered.
    - Stage taskbooks can be registered and bound to the master taskbook.
    - External version taskbooks can be imported and validated.
    - Taskbooks can be checked for binding to the project goal.
    - Codex can be dispatched under bounded taskbook constraints.
    - Execution reports are trustworthy and evidence-backed.
    - Reviewer Handoff Packages can be generated.
    - Structured Review Feedback can be ingested.
    - Feedback can be classified into a next-state Commander decision request.
    - Drift evidence can be recorded.
    - Long-running project work can be kept aligned with the original goal.
```

---

## 1. Project Goal

### 1.0 Project Final Goal

The project final goal for the current design draft is:

```yaml id="project-final-goal"
project_final_goal:
  status: commander_confirmed_for_discussion_draft
  applies_to: current_design_draft
  goal: >
    Design and evolve ColaMeta into a goal-anchored AI delivery command layer
    that can preserve the Commander-confirmed project final goal across Master,
    Stage, and Version taskbooks; constrain local execution through
    machine-checkable envelopes; produce evidence-backed review handoffs; and
    request Commander-controlled next-state decisions without silent drift,
    hidden authority expansion, or unverifiable completion claims.
  mvp_proof_shape: >
    Stage 0-6 Thin Governed Loop: goal anchor, taskbook binding, version task
    import, bounded execution envelope, execution and validation receipts,
    reviewer handoff, and classified next-state Commander decision request.
  non_authorization: >
    This goal is a design anchor. It does not authorize implementation, freeze,
    commit, push, remote action, memory write, bridge activation, route
    transition, or automatic state promotion without separate explicit approval.
```

This draft keeps one complete highest goal statement: `project_final_goal`.
It does not maintain a separate short goal phrase or a separate North Star goal.

ColaMeta lets users delegate project work to a controlled, reviewable, and
correctable AI execution team. It does not replace ChatGPT / Commander as the
source of project plans, and it does not replace Reviewer as the final judge.
ColaMeta's job is to register, freeze, validate, execute, report, review, and
track goals and taskbooks produced by external planning authorities so the
project does not drift during long-running development.

### 1.1 Minimum Irreplaceable Capability Set

Commander confirmed the following capability set for the discussion draft. This
decision defines the minimum shape ColaMeta must have to satisfy the
`project_final_goal` instead of becoming only an executor wrapper,
a document store, a generic router, or a project dashboard.

```yaml id="minimum-irreplaceable-capability-set"
minimum_irreplaceable_capability_set:
  status: commander_confirmed_for_discussion_draft
  core_claim: >
    ColaMeta is irreplaceable only if it can keep AI delivery anchored to the
    agreed goal: why the work exists, which taskbook boundary controls it,
    what evidence proves it, who reviews it, and what next state may be
    requested.
  capabilities:
    - id: goal_and_taskbook_anchoring
      meaning: Bind project work to the agreed goal and taskbook references.
    - id: three_level_taskbook_model_master_stage_version
      meaning: Manage Master, Stage, and Version taskbooks as distinct control layers.
    - id: execution_envelope
      meaning: Convert a Version Taskbook into a bounded local execution envelope.
    - id: bounded_executor_dispatch
      meaning: Dispatch executors only inside authorized scope and stop conditions.
    - id: evidence_and_reviewer_handoff_package
      meaning: Produce evidence that lets Reviewer judge delivery, not only code output.
    - id: delivery_state_machine
      meaning: Track delivery lifecycle states, not only process run states.
    - id: review_feedback_intake_and_next_state_decision_request
      meaning: Classify review feedback and prepare the next Commander decision request.
    - id: commander_gate_stop_boundary_and_observable_status_surface
      meaning: Preserve key gates, stop boundaries, and human-readable project status.
```

These capabilities are minimal, not maximal. They do not authorize
codex-router bridge implementation, remote actions, automatic commit or push,
automatic plan mutation, automatic route transition, or AGENTS OS Rights Plane
claims.

---

## 2. Why This Project Exists

AI coding already has strong roles:

```text id="project-context-roles"
ChatGPT can plan goals and tasks.
Codex can implement code.
Reviewer can review results.
Human Commander can make final decisions.
```

The hard problem in long-running AI development is:

```text id="project-problem"
Projects slowly drift.
```

Drift can come from:

| Source | Example |
| --- | --- |
| Executor drift | Codex edits forbidden files, expands scope, or performs opportunistic refactors. |
| Planner drift | ChatGPT gradually decomposes tasks away from the original goal. |
| Reviewer drift | Reviewer checks code quality but forgets the project direction. |
| State drift | A stage is treated as done without credible evidence and review closure. |
| Plan drift | The task list grows, but the project moves away from its original purpose. |

ColaMeta exists to answer:

```text id="project-core-problem"
How can long-running AI project delivery remain controllable, reviewable, traceable, and correctable?
```

---

## 3. Product Identity Constraint

### 3.1 Derived Product Identity

ColaMeta's product identity is derived from `project_final_goal`.

This draft does not keep a separate positioning phrase, slogan, or North Star
goal. Reopening product identity means reopening the complete
`project_final_goal`, and requires Commander hard-gate review.

"Project delivery control plane" and similar phrases may be used only as
explanatory language for how ColaMeta constrains and tracks execution. They are
not canonical goal statements.

```text id="control-plane-position"
ChatGPT / Commander / Reviewer
        ↓
      ColaMeta
        ↓
Codex / Executor / Local Project
```

| Role | Responsibility |
| --- | --- |
| ChatGPT / Commander | Define master goals, stage goals, version taskbooks, and route decisions. |
| ColaMeta | Register goals, freeze tasks, constrain execution, collect evidence, route review, and advance state under rules. |
| Codex / Executor | Implement the current bounded taskbook. |
| Reviewer | Judge pass/fix/adjust/abort using the goal, taskbook, diff, evidence, and reports. |
| Human Commander | Handle hard gates, major route changes, and final approval. |

### 3.2 Wrong Positioning

ColaMeta must not become:

```text id="wrong-positioning"
automatic project manager
automatic planning brain
automatic product owner
automatic reviewer
automatic release system
unbounded autonomous agent framework
executor without scope limits
```

Its value is not doing all judgment for humans. Its value is making judgment bounded, evidenced, reviewable, and reversible.

### 3.3 Architecture Boundary: codex-router Future Bridge Candidate

```yaml id="codex-router-future-bridge-candidate"
future_bridge_candidate:
  id: codex_router_future_bridge_candidate
  status: future_bridge_candidate
  implementation_route: not_in_current_route
  runtime_status: non_runtime
  mvp_dependency: false
  canonical_binding: illustrative_only
  upstream_layer: ColaMeta
  downstream_layer: codex-router
  relationship: layered_bridge_not_merger
  contract_boundary:
    input_from_colameta:
      - TaskEnvelope
      - taskbook/version/run correlation ids
      - requested action
      - workspace and repo context
      - risk and validation expectations
    output_from_codex_router:
      - RoutingDecision
      - preflight result
      - approval requirement
      - execution grant or block reason
      - validation result
      - audit and evidence receipt
  non_authorization:
    - does_not_authorize_implementation
    - does_not_authorize_runtime_integration
    - does_not_authorize_adapter_or_schema_work
    - does_not_authorize_executor_dispatch
    - does_not_authorize_remote_actions
```

ColaMeta may later integrate with `codex-router` as a downstream local-first governance, routing, approval, execution-control, validation, and audit-evidence harness.

The boundary is deliberately layered:

```text id="codex-router-bridge-layering"
ColaMeta decides what should be done, why it belongs to the project plan,
and which master/stage/version taskbook it serves.

codex-router decides whether that execution is allowed, which execution
boundary applies, what approval is required, and what evidence proves the
boundary was respected.
```

This bridge candidate must not turn `codex-router` into a ColaMeta business workflow engine, and must not move ColaMeta taskbook semantics into `codex-router`. It also must not let ColaMeta bypass preflight, approval gates, workspace-write guards, validation arbiters, or audit evidence.

The first acceptable bridge, if later authorized, should be narrow and preferably preflight-only:

```text id="codex-router-minimum-future-bridge-shape"
Taskbook -> TaskEnvelope -> RoutingDecision / Preflight -> EvidenceReceipt
```

This shape is illustrative, not canonical implementation scope. This candidate
is recorded as an architecture boundary only. It is not part of the current
implementation route.

### 3.4 Semantics-to-Mechanics Translation Table

This section records which external governance semantics ColaMeta may borrow, and how each borrowed semantic is narrowed into concrete ColaMeta delivery mechanics.

Untranslated semantics are not implementation requirements. A phrase may inspire the project, but it cannot constrain execution, authorize work, or enter the frozen route unless it maps to an explicit control, evidence requirement, or rejection condition.

| semantic_source | borrowed_semantic | allowed_colameta_meaning | mechanical_control | runtime_status | authority_owner | required_evidence | forbidden_interpretation | freeze_binding |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| AGENTS OS / dream essay | Unknown may remain | Ambiguous intent, state, consent, or authority must not be forced into a fake conclusion. | `unknown`, `blocked`, or `needs_human` state must fail closed for scope-expanding or authority-crossing actions. | non_runtime_governance_rule | Commander / Reviewer / Human hard gate | blocked state, review note, taskbook issue, or approval request | ColaMeta may infer the missing answer from past behavior, delivery pressure, or system confidence. | canonical_v1 |
| AGENTS OS / dream essay | Silence is not consent | Lack of response cannot authorize continuation, escalation, remote action, or scope expansion. | Explicit authorization is required before boundary-crossing action. Timeouts degrade to pause or blocked state. | non_runtime_governance_rule | Commander / Human hard gate | approval receipt or explicit written authorization | No objection, timeout, or non-response means proceed. | canonical_v1 |
| AGENTS OS / dream essay | Fatigue is not authorization | User exhaustion, repeated prompting, or "you decide" language does not create open-ended authority. | Ambiguous or fatigue-like delegation must narrow to safe, reversible, local actions or pause before high-impact work. | non_runtime_governance_rule | Commander / Reviewer | taskbook scope, approval class, or blocked report | A tired user implicitly grants broad execution authority. | canonical_v1 |
| AGENTS OS / memory governance | Past memory cannot rule present | Memory and prior route history are advisory context only. Current instruction, repository reality, and observed evidence win. | State checks and repo observations override memory. Stale memory must be treated as advisory and revalidated. | non_runtime_governance_rule | ColaMeta / Reviewer / Commander | current status, git state, observed output, review note | Stored memory or old task state authorizes present action without current confirmation. | canonical_v1 |
| AGENTS OS / dream essay | Pause returns control | Pause, block, or stop is a valid delivery state, not a failure to hide. | Executor must stop, release scope, record reason, and wait for review or Commander input when authority becomes unclear. | non_runtime_governance_rule | ColaMeta / Executor / Reviewer | executor report, stop reason, receipt, review feedback | Delivery momentum justifies continuing through ambiguity. | canonical_v1 |
| AGENTS OS | Growth right and relationship right | These rights belong to resident Agents in AGENTS OS, not to ColaMeta executors. | Treat as forbidden for ColaMeta executor identity claims. Do not grant resident-Agent ontology to executor processes. | forbidden | Commander / Reviewer | boundary review note or rejected draft finding | ColaMeta executors have resident Agent growth rights, relationship rights, or life-governance status. | canonical_v1 |
| Goal Boundary Contract | Goal Boundary Contract | A future non-runtime contract concept that may describe goal, scope, authority, pause/unknown zones, memory limits, executor permissions, and return-key conditions. | Preview-only future bridge candidate. Does not authorize schema, adapter, state-machine, runtime, or executor changes. | future_bridge_candidate | Commander hard gate | separately approved future taskbook before any implementation | Goal Boundary Contract is an MVP dependency or current runtime architecture. | canonical_v1 |
| codex-router | Policy / routing / approval / execution-control bridge | A possible downstream future bridge for preflight, routing, approval, execution grants, validation, and audit evidence. | Architecture boundary only. No implementation until a separate approved bridge taskbook exists. | future_bridge_candidate | Commander hard gate / future bridge reviewer | separate future bridge taskbook only | Naming codex-router authorizes adapter work, schema work, runtime integration, executor dispatch, or remote actions. | canonical_boundary_only |
| ColaMeta governance | Semantic alignment | ColaMeta may surface alignment evidence and questions, but it must not self-certify final semantic alignment. | Reviewer or Commander must judge alignment before state advancement when alignment is disputed or unclear. | non_runtime_governance_rule | Reviewer / Commander | review feedback, alignment decision, state transition record | ColaMeta can judge semantic alignment by itself. | canonical_v1 |

### 3.5 Forbidden Claims / Boundary Law

These claims are forbidden in the Master Taskbook, derived stage taskbooks, version taskbooks, implementation prompts, product descriptions, and future bridge drafts unless a later Commander-approved taskbook explicitly supersedes this boundary.

```text id="forbidden-claims-boundary-law"
ColaMeta is not AGENTS OS.
ColaMeta does not govern resident Agent life, growth, intimacy, or relationship rights.
Growth right and relationship right apply only to resident Agents, not ColaMeta executors.

ColaMeta may borrow governance semantics from AGENTS OS only after translating them into explicit mechanical controls.
Untranslated semantics are not implementation requirements.

Treaty Layer is not an approved ColaMeta runtime layer.
The downgraded concept name is Goal Boundary Contract.
Goal Boundary Contract is a non-runtime future_bridge_candidate concept only.
It does not authorize schema work, adapter work, executor dispatch, state-machine changes, runtime integration, or implementation.

codex-router is not an immediate ColaMeta dependency.
codex-router is a future_bridge_candidate only.
No bridge implementation, adapter, schema, runtime integration, shared state, executor dispatch, or remote action is authorized by naming codex-router in this document.

Silence is not consent.
Fatigue is not authorization.
Past memory is not present authority.
Unknown state must fail closed.
Semantic alignment must be reviewed, not auto-claimed by ColaMeta.
ColaMeta must not replace Commander planning, Reviewer judgment, or human hard gates.
```

Draft rejection criteria:

- Any draft using `Treaty Layer` as a current ColaMeta runtime layer is rejected.
- Any draft implying `codex-router` is part of the MVP is rejected.
- Any draft applying AGENTS OS resident-Agent growth rights or relationship rights to ColaMeta executors is rejected.
- Any draft turning `Goal Boundary Contract` into runtime architecture before a separate approved taskbook is rejected.
- Any draft allowing ColaMeta to infer consent, continue from fatigue, or rely on stale memory over current state is rejected.
- Any draft claiming semantic alignment without Reviewer or Commander judgment is rejected.

---

## 4. Core Governance Principles

### 4.1 Separation Of Authority

```text id="separation-of-authority"
Planning authority != execution authority != review authority
```

| Authority | Owner |
| --- | --- |
| Planning | ChatGPT / Commander |
| Execution | Codex / Executor |
| Review | Reviewer / Commander |
| State advancement | ColaMeta under structured decisions |
| Master goal change | Commander hard gate |

ColaMeta does not replace these roles. It keeps them from collapsing into one uncontrolled surface.

### 4.2 Goal Anchoring

Every stage, task, execution, review, fix, and plan adjustment must bind back to the project master goal.

Every step must be able to answer:

```text id="alignment-question"
Does this step still serve the project master goal?
```

If the answer is unclear, the system must not proceed as if alignment is proven. It must enter review or plan adjustment.

### 4.3 Task Freezing

Each executable version task must freeze:

```text id="task-freeze-fields"
goal
allowed_files
forbidden_files
acceptance_commands
manual_acceptance
out_of_scope
delivery_evidence
review_requirements
```

Executors may complete the current taskbook. They may not rewrite the route.

### 4.4 Feedback Loop

```text id="feedback-loop"
taskbook registration
  ↓
executor execution
  ↓
ColaMeta evidence collection
  ↓
Reviewer Handoff Package
  ↓
Reviewer decision
  ↓
structured feedback intake
  ↓
continue / fix / plan adjust / abort
```

Long-running progress should not continue automatically without review feedback.

### 4.5 Preview First

These actions must be preview-first:

```text id="preview-first-actions"
register master taskbook
modify master taskbook
register stage taskbook
modify stage taskbook
insert version task
modify version task
adjust plan from review feedback
commit local Git changes
perform remote Git actions
```

ColaMeta must not skip preview and apply directly.

### 4.6 Semantic Drift Policy

ColaMeta may collect evidence and ask alignment questions, but it must not claim final semantic alignment by itself.

```yaml id="semantic-drift-policy"
semantic_drift_policy:
  cola_meta_may_collect_evidence: true
  cola_meta_may_require_reviewer_answers: true
  cola_meta_may_surface_alignment_questions: true
  cola_meta_must_not_claim_semantic_alignment_alone: true
  reviewer_or_commander_must_decide_semantic_alignment: true
```

---

## 5. Master Taskbook Activation

### 5.1 Status Definitions

```yaml id="activation-policy"
activation_policy:
  draft:
    meaning: Editable, not an execution anchor.
  discussion_draft:
    meaning: Stored in the project for planning discussion, not a frozen canonical anchor.
  active_candidate:
    meaning: Reviewable and hashable, but not yet a mandatory anchor.
  freeze_candidate:
    meaning: Revised after review, waiting for Commander freeze confirmation.
  active:
    meaning: Can be formally referenced by stage, version, and review records.
  superseded:
    meaning: Replaced by a newer version; old tasks may still reference the old hash.
  revoked:
    meaning: Revoked by Commander and unavailable for new tasks.
```

Current document status:

```yaml id="current-taskbook-review-status"
status: discussion_draft
recommended_review_decision: CONTINUE_DISCUSSION
```

### 5.2 Activation Requirements

```yaml id="activation-requires"
activation_requires:
  - Commander review completed for freeze-candidate use
  - canonical copy stored
  - canonical hash generated
  - no unresolved P0 review issues
  - all P1 review issues resolved, scoped out, or explicitly dispositioned as non-blocking
  - hash_policy accepted for review use
  - versioning_policy accepted for review use
  - freeze_candidate_preconditions satisfied
```

This file is intentionally not yet active. It is the shared baseline for further route discussion.

### 5.3 Freeze Candidate Preconditions

This draft must not move from `discussion_draft` to `freeze_candidate` until
the MVP is reviewable as a thin governed loop rather than a broad product
platform.

```yaml id="freeze-candidate-preconditions"
freeze_candidate_preconditions:
  status: required_before_freeze_candidate
  current_status: contract_patches_applied_pending_readiness_review
  status_note: >
    The hash/canonical authority, state authority, and minimum checkable object
    patches have been applied in discussion_draft. This does not promote the
    document to freeze_candidate; it only makes the draft ready for a
    non-authoritative readiness review.
  required_conditions:
    - id: stage_00_to_06_thin_governed_loop
      requirement: >
        Stage 0 through Stage 6 are defined as one governed proof loop, not
        seven full automation layers or standing permission for broad
        implementation.
    - id: stage_04_downgraded_scope
      requirement: >
        Stage 4 is limited to a machine-checkable execution envelope plus
        local execution evidence or imported execution receipt. A new general
        executor-dispatch platform is not an MVP prerequisite.
    - id: stage_06_downgraded_scope
      requirement: >
        Stage 6 is limited to structured feedback classification and a
        next-state Commander decision request. It must not apply plan changes,
        mutate delivery state, or continue execution by itself.
    - id: machine_checkable_execution_envelope_contract
      requirement: >
        The execution envelope has structured fields and fail-closed rejection
        rules for parent hashes, allowed paths, allowed actions, forbidden
        actions, stop conditions, evidence requirements, and validation
        commands.
    - id: validation_receipt_semantics
      requirement: >
        Execution and validation receipts distinguish validated, unvalidated,
        not_run, failed, and blocked results, including command, exit status,
        evidence location, and uncertainty where applicable.
    - id: finite_delivery_state_gate
      requirement: >
        The delivery state gate defines finite states, allowed transitions,
        required evidence for each transition, and forbidden auto-promotions.
    - id: gate_event_minimum_contract
      requirement: >
        GateEvent is defined as the append-only record emitted by Delivery
        State Gate for delivery_state transitions and item-level blocked
        changes, with authority basis, prior and resulting state versions,
        evidence refs, idempotency, and conflict checks.
    - id: commander_decision_request_minimum_contract
      requirement: >
        CommanderDecisionRequest is defined as a bounded request object for
        accept, rework, plan adjustment, cancellation, defer, or next-loop
        decisions. It must not mutate plan, state, Git, memory, route, bridge,
        or remote systems by itself.
    - id: audit_event_minimum_contract
      requirement: >
        AuditEvent is defined as a small append-only trace record binding
        actor, authority basis, envelope, receipt, evidence, GateEvent,
        CommanderDecisionRequest, redaction posture, and integrity digest
        without becoming delivery-state authority.
    - id: minimal_delivery_state_transition_model
      requirement: >
        The Master freezes proposed, ready, in_delivery, submitted, accepted,
        and cancelled as the top-level delivery states. Blocked, returned,
        gate review, validation, approval, and delivery are handled as flags,
        transition outcomes, processes, or facets, not as top-level states.
    - id: review_decision_mapping
      requirement: >
        Reviewer decisions are review records first. ACCEPT and NEEDS_FIX may
        produce delivery-state transitions only through Delivery State Gate
        authority. PLAN_ADJUST and ABORT do not directly mutate delivery_state;
        they create Commander decision requests and optional blocked flags.
    - id: taskbook_layer_responsibility_contract
      requirement: >
        Master, Stage, and Version taskbooks define bounded claims and
        execution envelopes, not state authority. Master owns project doctrine
        and responsibility boundaries. Stage owns stage-local delivery
        protocols and gate-readiness criteria. Version owns concrete
        delivery-attempt claims, evidence references, review references, and
        gate requests. Accepted state remains owned only by Delivery State Gate.
    - id: stage_0_6_readiness_contract
      requirement: >
        Stage 0 through Stage 6 are described as one static readiness contract,
        not seven product layers and not a live project tracker. Each stage
        must define a minimum readiness claim, required evidence, gate question,
        and explicit non-goal, with universal stop predicates for missing
        authority, boundary conflict, state conflict, and acceptance unknown.
    - id: reviewer_handoff_minimum_template
      requirement: >
        The reviewer handoff package has a minimum template covering goal,
        scope, changed files, validation, risks, unresolved items, and the
        requested next-state decision.
    - id: codex_router_mvp_exclusion
      requirement: >
        codex-router remains a future_bridge_candidate only and is not an MVP
        dependency, execution route, adapter requirement, or authorization path.
    - id: authority_boundary
      requirement: >
        discussion_draft status, hashes, validation results, and review
        packets are not treated as execution, freeze, canonicalization, commit,
        push, memory-write, or bridge-activation authority.
```

---

## 6. Hash Boundary Policy

The Master Taskbook must eventually be hashable, verifiable, and referenceable. To avoid meaningless hash churn, the canonical hash should bind governance fields, not formatting or changing local status notes.

```yaml id="hash-policy"
hash_policy:
  canonical_payload_authority:
    chinese_name: 规范载荷单一权威
    single_source_of_truth: hash_policy.canonical_fields
    hash_input_manifest: hash_policy.canonical_fields
    derived_payload_views:
      - freeze_process_and_canonicalization.derived_hashable_payload_view
      - freeze_process_and_canonicalization.derived_excluded_payload_view
    conflict_rule: >
      If a derived payload view, review packet, or future canonicalizer mapping
      conflicts with hash_policy.canonical_fields, the canonicalizer must fail
      closed. The derived view must be corrected before any freeze_candidate
      request.
    chinese_meaning: >
      真正决定哈希输入的只有 hash_policy.canonical_fields。后面的
      hashable payload 只是方便人审查的派生视图，不能成为第二套权威清单。

  canonical_field_path_style:
    style: machine_readable_source_paths_only
    chinese_name: 机器可抓取真实来源路径
    allowed_prefixes:
      - master_taskbook.
      - markdown_section.
      - yaml_block.
      - hash_policy.
    wildcard_list_selectors_allowed: true
    forbidden_styles:
      - bare_concept_name
      - ambiguous_heading_label
      - runtime_status_note

  canonical_scope_decisions:
    future_bridge_candidates:
      chinese_name: 未来桥接候选
      bind:
        - future candidate status
        - non-authorization boundary
        - not MVP dependency
        - not current implementation route
      do_not_bind:
        - detailed bridge implementation shape
        - adapter fields
        - schema work
        - runtime integration details
    post_mvp_stages:
      chinese_name: 第 7 到第 9 阶段
      bind:
        - post-MVP route only
        - not authorized for current implementation
        - not part of Stage 0-6 MVP readiness
      do_not_bind:
        - detailed deliverables
        - implementation order
        - version allocation
    user_promise:
      chinese_name: 用户承诺
      bind_as_product_promise: true
      meaning: >
        The promise that ColaMeta lets users delegate project work to a
        controlled, reviewable, and correctable AI execution team is canonical
        enough to constrain product direction.
    canonical_field_path_rule:
      chinese_name: 规范字段路径规则
      rule: >
        canonical_fields must use machine-readable source paths. Real
        master_taskbook fields use master_taskbook.<field>. Markdown-only
        canonical sections use markdown_section.<stable_section_slug>. Hash
        policy rules use hash_policy.<field>. Bare concept names are not valid
        canonical field paths.

  canonical_fields:
    - master_taskbook.id
    - master_taskbook.version
    - master_taskbook.project_final_goal
    - master_taskbook.goal_statement_policy
    - master_taskbook.product_identity_constraint_decision
    - master_taskbook.minimum_irreplaceable_capability_set
    - master_taskbook.mvp_shape_decision
    - master_taskbook.delivery_state_gate_freeze_target
    - master_taskbook.state_authority_contract_decision
    - master_taskbook.delivery_state_transition_model_decision
    - master_taskbook.review_decision_mapping_decision
    - master_taskbook.taskbook_layer_responsibility_decision
    - master_taskbook.stage_0_6_readiness_contract_decision
    - master_taskbook.future_bridge_candidates[*].id
    - master_taskbook.future_bridge_candidates[*].status
    - master_taskbook.future_bridge_candidates[*].implementation_route
    - master_taskbook.future_bridge_candidates[*].runtime_status
    - master_taskbook.future_bridge_candidates[*].mvp_dependency
    - master_taskbook.future_bridge_candidates[*].non_authorization
    - master_taskbook.non_goals
    - master_taskbook.governance_principles
    - master_taskbook.required_bindings
    - master_taskbook.mvp_boundary
    - yaml_block.freeze-candidate-preconditions
    - yaml_block.freeze-process-and-canonicalization
    - yaml_block.minimum-checkable-schema-contracts-summary
    - master_taskbook.success_criteria
    - hash_policy.canonical_field_path_style
    - hash_policy.canonical_scope_decisions
    - markdown_section.semantics_to_mechanics_translation_table
    - markdown_section.forbidden_claims_boundary_law
    - markdown_section.standard_workflow
    - markdown_section.review_feedback_decision_policy
    - markdown_section.taskbook_hierarchy
    - markdown_section.mvp_boundary
    - markdown_section.hard_gates

  excluded_fields:
    machine_path_entries:
      - master_taskbook.current_known_state
      - yaml_block.codex-router-future-bridge-candidate.implementation_shape_fields
      - markdown_section.stage_07_detailed_deliverables
      - markdown_section.stage_08_detailed_deliverables
      - markdown_section.stage_09_detailed_deliverables
      - markdown_section.stage_summary_status_notes
      - markdown_section.review_packet_snapshot_runtime_values
    category_entries:
      - formatting
      - markdown_heading_numbering
      - examples_unless_promoted_to_canonical_claim
      - commentary_unless_promoted_to_canonical_claim
      - generated_at
      - draft_notes
      - local_status_notes
      - runtime_status_notes
      - debate_transcripts
      - raw_runtime_logs_full_text
      - secrets
      - credentials
    path_precision_rule: >
      Any excluded governance-bearing content must be named by machine-readable
      source path before freeze_candidate. Category entries are allowed only for
      non-governance presentation or transient runtime material.

  canonicalization:
    trim_surrounding_whitespace: true
    normalize_line_endings: lf
    sort_mapping_keys: true
    preserve_list_order: true
```

`current_known_state` is excluded because it records changing repository reality, such as local commits, remote sync state, and in-progress versions.

### 6.1 Freeze Process And Canonicalization

`Freeze Process And Canonicalization` = 冻结流程与规范化.

Plain Chinese meaning: `freeze_candidate` means the governance content is stable
enough to review. It is not accepted truth, active authority, implementation
approval, commit approval, push approval, deployment approval, remote-action
approval, or credential authority.

```text id="freeze-process-core-rule"
freeze_candidate is a reviewable governance candidate, not active authority.
Hash is identity, not truth or authorization.
Hashing a claim does not make it a fact.
Freeze approval is not implementation approval.
```

Chinese meaning:

```text id="freeze-process-core-rule-zh"
冻结候选是可审查的治理候选，不是已生效权威。
哈希是身份，不是真相或授权。
把主张哈希了，不会让主张变成事实。
冻结批准不是实施批准。
```

```yaml id="freeze-process-and-canonicalization"
freeze_process_and_canonicalization:
  chinese_name: 冻结流程与规范化
  status: commander_confirmed_for_discussion_draft

  freeze_candidate_meaning:
    means:
      - reviewable_governance_candidate
      - candidate_content_stable_enough_for_freeze_review
      - canonical_payload_can_be_hashed_and_compared
    does_not_mean:
      - accepted_truth
      - active_authority
      - implementation_approval
      - commit_approval
      - push_approval
      - deploy_approval
      - remote_action_approval
      - credential_or_secret_authority
      - user_visible_accepted_truth

  canonical_hash:
    name: freeze_content_hash
    algorithm: sha256
    input_rule: sha256("ColaMeta.freeze_candidate.v1\n" + canonical_json)
    canonicalization_rules:
      - use UTF-8
      - normalize line endings to LF
      - normalize unicode to NFC
      - sort mapping keys by byte order
      - omit undefined fields
      - preserve explicit null fields
      - sort set-like arrays by stable id
      - require explicit order fields for semantically ordered arrays
      - use repo-relative forward-slash paths
      - hash EvidencePackage digests or references, not raw long logs
      - never include secrets or credentials

  hash_input_authority:
    single_source_of_truth: hash_policy.canonical_fields
    derived_views_are_authoritative: false
    required_mapping_rule: >
      Every field in derived_hashable_payload_view must trace to one or more
      entries in hash_policy.canonical_fields. Any unmapped or ambiguously
      mapped field fails closed before freeze_candidate.
    chinese_meaning: >
      冻结哈希到底吃哪些内容，只看 hash_policy.canonical_fields。下面的字段
      只是审查用视图，必须能反查到真实来源路径，否则不能冻结。

  derived_hashable_payload_view:
    - schema_version
    - canonicalizer_version
    - taskbook_id
    - candidate_id
    - lifecycle.phase
    - authority_model
    - project_final_goal
    - scope
    - claims
    - assumptions
    - unknowns
    - acceptance_contract
    - evidence_index
    - blocked_policy
    - terminal_correction_supersede_policy
    - runtime_compatibility
    - user_visible_projection_contract
    - lineage.supersedes
    - excluded_fields_manifest
    - action_authority_flags

  derived_excluded_payload_view:
    - markdown_formatting
    - markdown_heading_numbering
    - discussion_notes
    - debate_transcripts
    - reviewer_freeform_comments_unless_promoted_to_disposition
    - generated_at
    - updated_at
    - local_absolute_paths
    - machine_name
    - username
    - pid
    - cwd
    - token_count
    - elapsed_time
    - raw_runtime_logs_full_text
    - secrets
    - credentials
    - hash_field_itself
    - non_normative_explanation_unless_promoted_to_claim

  hash_meaning:
    means:
      - the canonical freeze payload identity is bound to this digest
      - the reviewed governance candidate has not silently changed
      - Commander confirmation can refer to this exact candidate identity
    does_not_mean:
      - content_is_true
      - evidence_is_sufficient
      - Runtime facts are verified
      - Taskbook claims are accepted
      - Delivery State Gate accepted the candidate
      - Commander authorized implementation
      - commit_push_deploy_or_remote_action_is_authorized
      - user_visible_status_has_changed

  review_packet_minimum:
    - candidate_id
    - taskbook_id
    - status: freeze_candidate
    - canonicalizer_version
    - hash_algorithm
    - freeze_content_hash
    - included_fields_manifest
    - excluded_fields_manifest
    - canonical_payload_snapshot_or_digest
    - diff_summary
    - p0_p1_p2_disposition
    - EvidencePackage_index
    - conflict_review
    - runtime_compatibility_check
    - terminal_correction_supersede_check
    - user_visible_projection_preview_marked_preview_only
    - non_authority_notice
    - Commander_confirmation_text

  p0_p1_p2_rules:
    P0: any open P0 blocks freeze_candidate.
    P1: P1 blocks unless resolved, scoped out, or explicitly dispositioned as non-blocking.
    P2: P2 may remain tracked only when it does not weaken core governance claims.

  invalidation_rules:
    - any hashable field changes
    - schema_version or canonicalizer_version changes
    - EvidencePackage digest is missing, changed, superseded, or retracted
    - Runtime fact conflicts with frozen Taskbook claim
    - scope, boundary, or acceptance contract changes
    - blocked policy premise changes
    - terminal correction or supersede relation changes
    - user-visible projection cannot be mechanically derived
    - secret or unauthorized sensitive content is discovered
    - Commander confirmation hash, scope, or boundary does not match
    - a new open P0 is discovered
    - action authority flags change

  action_authority_flags:
    implementation_authority: none
    commit_authority: none
    push_authority: none
    deploy_authority: none
    remote_action_authority: none
    credential_authority: none
    external_api_authority: none

  commander_confirmation_template: >
    CONFIRM FREEZE_CANDIDATE taskbook_id=<TASKBOOK_ID>
    candidate_id=<CANDIDATE_ID> canonicalizer=ColaMeta.freeze_candidate.v1
    hash=sha256:<HASH> scope=<SCOPE_ID> boundary=<BOUNDARY_ID>
    review_only=true delivery_state_gate_required=true
    implementation_authority=none commit_authority=none push_authority=none
    deploy_authority=none remote_action_authority=none
    credential_authority=none external_api_authority=none
```

---

## 7. Versioning Policy

```yaml id="versioning-policy"
versioning_policy:
  minor_text_edits:
    allowed_without_new_master_version: true
    condition: They do not change canonical_fields.

  governance_change:
    requires_new_master_taskbook_version: true
    requires_commander_hard_gate: true

  project_final_goal_change:
    requires_new_master_taskbook_version: true
    requires_commander_hard_gate: true

  non_goals_change:
    requires_new_master_taskbook_version: true
    requires_commander_hard_gate: true

  active_versions_can_coexist: true
  old_tasks_keep_original_hash: true
  new_tasks_should_bind_latest_active_version: true
```

Ordinary version tasks must not silently modify the Master Taskbook.

---

## 8. Three-Level Taskbook Hierarchy

ColaMeta must manage three levels of taskbooks, without inventing them as an unbounded planning brain:

```text id="taskbook-hierarchy"
Project Master Taskbook
        ↓
Stage Taskbook
        ↓
Version Execution Taskbook
```

This hierarchy is a control structure, not an authorization ladder. Commander
authorizes explicitly named gates and bounded execution envelopes, not every
internal step.

### 8.0 Layer Responsibility Contract

`Layer Responsibility Contract` = 三层任务书职责边界契约.

Plain Chinese meaning: Taskbooks explain the goal, phase, delivery attempt,
and evidence trail. They are not the source of final state truth.

```text id="taskbook-layer-core-rule"
Taskbooks define bounded claims and execution envelopes; they do not own state authority.
Runtime owns facts.
Taskbooks own claims.
Delivery State Gate owns acceptance.
Delivery State Gate writes delivery_state only through GateEvent.
Commander owns boundary authority.
The User sees accepted truth only.
```

Layer ownership:

```yaml id="taskbook-layer-ownership"
taskbook_layer_ownership:
  master_taskbook:
    owns:
      - project_final_goal
      - global doctrine
      - non_goals
      - Stage 0-6 Thin Governed Loop
      - authority boundaries
      - responsibility boundaries
      - freeze_candidate preconditions
    may_enable:
      - safe_execution_envelope_rules
      - commander_escalation_rules
      - stage_decomposition
    must_not_own:
      - Runtime facts
      - accepted delivery state
      - Version implementation truth
      - EvidencePackage sufficiency
      - ReviewDecision outcome authority
      - GateEvent outcome authority

  stage_taskbook:
    owns:
      - stage purpose
      - stage entry criteria
      - stage exit criteria
      - required artifacts
      - required evidence shape
      - stage-local review expectations
      - gate-readiness criteria
    may_enable:
      - autonomous executor work inside stage-local rules
      - version task directions
      - candidate handoff to Delivery State Gate
    must_not_own:
      - project_final_goal mutation
      - global authority rules
      - accepted delivery state
      - cross-stage policy exceptions
      - Version-specific runtime truth
      - codex-router activation authority

  version_taskbook:
    owns:
      - one concrete delivery attempt
      - scoped implementation claims
      - allowed files and mutations
      - validation commands
      - evidence references
      - review references
      - requested gate actions
      - open risks
    may_enable:
      - local implementation
      - local validation
      - narrow fixes inside the authorized envelope
      - EvidencePackage assembly
      - review and gate request preparation
    must_not_own:
      - acceptance
      - Runtime facts
      - stage policy
      - Master doctrine
      - user-visible accepted truth
      - state transitions
```

Executor autonomy rule:

```text id="taskbook-layer-executor-autonomy-rule"
Within an authorized Stage and Version envelope, executors may continue
automatically on reversible, local, scope-aligned work that gathers runtime
facts, improves evidence, fixes defects, runs validation, updates candidate
claims, or prepares a review or gate request.

Commander approval is not required for ordinary execution steps inside that
envelope. Escalation is required before any action changes project_final_goal,
changes scope boundaries or non-goals, bypasses required Stage 0-6 controls,
declares accepted state, mutates delivery_state, resolves conflicts between
Runtime facts and taskbook claims, performs irreversible or external actions,
overwrites unresolved user work, or promotes codex-router beyond
future_bridge_candidate.
```

Status vocabulary rule:

```text id="taskbook-layer-status-vocabulary-rule"
Taskbooks may record claims, evidence, and requested transitions only.
They must not declare accepted delivery state.

"Ready for Gate" means only: executor claims required evidence is present.
"Complete" means only: listed executor-local tasks are claimed complete inside
this Version.
"Frozen" means only: no further edits inside the named draft or candidate
without the applicable unfreeze or supersede rule.
"Accepted" is valid only when backed by an authoritative Delivery State
GateEvent.

If a status word appears without its authority source, it is non-authoritative
taskbook text.
```

### 8.1 Project Master Taskbook

Suggested file:

```text id="master-taskbook-path"
PROJECT_MASTER_TASKBOOK.md
```

Purpose:

```text id="master-taskbook-purpose"
freeze project master goal
define positioning
define non-goals
define long-term route
define stage decomposition principles
define review principles
define drift judgment standards
define plan adjustment rules
define layer responsibility boundaries
```

ColaMeta responsibilities:

```text id="master-taskbook-colameta-duty"
register
read
hash
validate
reference
prevent silent modification
require hard gate for major changes
```

### 8.2 Stage Taskbook

Suggested path:

```text id="stage-taskbook-path"
docs/taskbooks/stages/STAGE_XX_*.md
```

Purpose:

```text id="stage-taskbook-purpose"
decompose the master goal into a stage goal
explain why the stage supports the master goal
declare what the stage will not do
list version-task directions
define gate-readiness criteria
define stage review requirements
```

ColaMeta responsibilities:

```text id="stage-taskbook-colameta-duty"
register
validate master_taskbook_ref
compute stage_taskbook_hash
bind future version tasks
surface to Reviewer
```

### 8.3 Version Execution Taskbook

Suggested path:

```text id="version-taskbook-path"
.colameta/prompts/vX.Y.md
```

Required fields:

```yaml id="version-taskbook-required-fields"
version:
name:
master_taskbook_ref:
stage_taskbook_ref:
task_goal:
supports_project_goal:
allowed_files:
forbidden_files:
allowed_mutations:
acceptance_commands:
manual_acceptance:
stop_conditions:
out_of_scope:
reporting_destination:
acceptance_and_evidence_contract:
forbidden_authority_claims:
reviewer_packet_requirements:
```

ColaMeta responsibilities:

```text id="version-taskbook-colameta-duty"
validate format
insert plan version
dispatch authorized executor
run acceptance
check scope
generate report
enter review flow
```

### 8.4 Execution Envelope Principle

Version Execution Taskbooks define execution envelopes. When explicitly
authorized by Commander, an execution envelope authorizes only explicitly named
local work against exact parent hashes and explicit file paths or globs.

```yaml id="execution-envelope-required-fields"
execution_envelope:
  parent_hashes:
    master_taskbook_hash:
    stage_taskbook_hash:
  task_goal:
  definition_of_good:
  allowed_files_or_globs:
  allowed_mutations:
  forbidden_actions:
  exact_local_validation_commands:
  manual_checks:
  stop_conditions:
  reporting_destination:
  acceptance_and_evidence_contract:
  forbidden_authority_claims:
```

Once an execution envelope is explicitly authorized, ColaMeta and bounded
executors may iterate autonomously inside the envelope across local
read/edit/validate/narrow-fix/report cycles until local validation passes, a
gate request is ready, or a stop condition is reached. Commander does not
approve every internal step.

Narrow fixes may be repeated if they preserve the envelope. They must stay
inside allowed scope and must not introduce new files, dependencies, APIs,
route changes, policy changes, scope expansion, authority claims, credential
changes, runtime changes, destructive actions, or remote writes.

Hash validity must be checked before execution starts and before review
submission. If a referenced parent hash does not exactly match, or parent
status changes, the envelope is suspended immediately.

Reporting is local or review-packet reporting only, to explicitly named
destinations. It does not authorize GitHub comments, PR updates, issues, Slack
posts, remote records, memory writes, route-state updates, canonical status
updates, or external writes unless separately authorized.

The Acceptance & Evidence Contract requires evidence of what changed, what
validation ran, what passed or failed, what remains uncertain, and how the work
supports the Master / Stage / Version goal.

The Forbidden Authority Claims block must state that the envelope does not
authorize status promotion, route transition, canonical freeze, P0 closure, git
action, remote write, runtime promotion, bridge activation, dependency change,
credential action, destructive action, or policy adoption unless separately
named by Commander.

---

## 9. Minimum Checkable Schema Contracts

`Minimum Checkable Schema Contracts` = 最小可检查结构契约.

Plain Chinese meaning: Master freezes only the minimum field shapes needed to
check scope, authority, evidence, validation, and state movement. It does not
freeze executor internals, commands, tools, logs, UI, or implementation routes.
Master defines governance data contracts, not runner APIs.

Plain Chinese meaning: Master 定义治理数据契约，不定义执行器 API.

Current implementation reality:

`distributed_state_advancement_control` = 分散式状态推进控制.

ColaMeta currently controls state movement through separate cooperating
mechanisms: runner state, version status, state mutation gateway, acceptance
rerun, checkpoint review, continue-next-version workflow, and executor-session
safeguards. This is the observed current implementation reality, not a unified
`Delivery State Gate` object.

Freeze target:

`unified_delivery_state_gate_contract` = 统一的交付状态门契约.

The freeze target is to upgrade that distributed state advancement control into
a unified `Delivery State Gate` governance contract. This target clarifies the
contract boundary; it does not authorize runtime implementation, migration,
state-machine rewrite, executor dispatch changes, commit, push, or freeze by
itself.

The four contracts compose as:

```text id="minimum-contract-composition"
Envelope controls permission.
Receipt controls truth.
Reviewer handoff and decision controls judgment.
Delivery state gate controls movement.
```

Chinese meaning:

```text id="minimum-contract-composition-zh"
执行边界管权限。
执行与验证回执管事实。
审查交接与决策管判断。
交付状态门管状态移动。
```

```yaml id="minimum-checkable-schema-contracts-summary"
minimum_checkable_schema_contracts:
  status: commander_confirmed_for_discussion_draft
  chinese_name: 最小可检查结构契约
  contract_kind: governance_data_contracts_not_runner_api
  representation: YAML / JSON / Python dataclass are all valid implementation forms
  refs_are_opaque: true
  implementation_details_are_non_authoritative: true
  required_minimum_objects:
    ExecutionEnvelope:
      chinese_name: 执行信封
      purpose: pre-dispatch boundary and permission check
    Receipt:
      chinese_name: 执行与验证回执
      purpose: observed or imported execution truth evidence
    GateEvent:
      chinese_name: 状态门事件
      purpose: append-only delivery_state and blocked projection event
    CommanderDecisionRequest:
      chinese_name: 指挥官决策请求
      purpose: bounded request for Commander decision, not mutation authority
    AuditEvent:
      chinese_name: 审计事件
      purpose: append-only trace record, not state authority
  master_freezes:
    - field names
    - required fields
    - allowed enums
    - reference relationships
    - fail-closed rules
    - authority boundaries
    - state authority domains
    - minimum evidence slots
  stage_or_version_owns:
    - concrete commands
    - executor choice
    - implementation steps
    - runner internals
    - retry policy
    - log format
    - evidence attachment format
    - stage-specific acceptance details
```

### 9.1 State Authority Contract

`State Authority Contract` = 状态权责契约.

Earlier discussion used `State Ownership Contract` = 状态归属契约. The adopted
name is `State Authority Contract` because the decision is not only about who
owns a state field. It separates who may define intent, who may declare a state
claim, who may produce evidence, who may judge a transition, and what the user
is allowed to see as trusted status.

Plain Chinese meaning: 状态不是一坨东西归某一层。ColaMeta 要把状态拆成
意图、主张、证据、裁决、用户可见状态，每一种都有自己的权责边界。

```yaml id="state-authority-contract"
state_authority_contract:
  status: commander_confirmed_for_discussion_draft
  chinese_name: 状态权责契约
  supersedes_discussion_label:
    english: State Ownership Contract
    chinese: 状态归属契约

  authority_domains:
    intent_authority:
      chinese_name: 意图权
      owner: Master Taskbook
      chinese_owner: 总任务书
      owns:
        - project_final_goal
        - global_delivery_semantics
        - mvp_scope
        - final_acceptance_meaning
      does_not_own:
        - runtime_logs
        - command_results
        - version_execution_details

    declaration_authority:
      chinese_name: 声明权
      owner: relevant_taskbook_layer
      chinese_owner: 对应任务书层
      owns:
        - Master declares project-level state claims.
        - Stage declares stage-level state claims.
        - Version declares version-level state claims.
      does_not_own:
        - evidence_truth
        - gate_acceptance
        - automatic_upper_layer_promotion

    evidence_authority:
      chinese_name: 证据权
      owner: ColaMeta Runtime or equivalent verification source
      chinese_owner: ColaMeta 运行时或等价验证来源
      owns:
        - observed_execution_facts
        - commands
        - logs
        - validation_results
        - failures
        - artifacts
        - execution_traces
        - scope_guard_results
      does_not_own:
        - delivery_acceptance
        - stage_completion
        - project_goal_satisfaction
        - remote_or_irreversible_permission

    transition_authority:
      chinese_name: 转换裁决权
      owner: Delivery State Gate
      chinese_owner: 交付状态门
      owns:
        - transition_judgment
        - gate_acceptance
        - block_reason
        - conflict_exposure
      does_not_own:
        - invented_state
        - fabricated_evidence
        - commander_permission
        - hidden_upper_layer_promotion

    permission_authority:
      chinese_name: 授权权
      owner: Commander / Human hard gate
      chinese_owner: 指挥官 / 人类硬门
      owns:
        - boundary_crossing_permission
        - freeze_permission
        - commit_push_release_permission
        - remote_or_irreversible_action_permission
      does_not_own:
        - evidence_facts
        - validation_results
        - silent_state_promotion

  user_visible_truth:
    chinese_name: 用户可见真相
    definition: >
      User-visible state is a published projection of accepted declarations,
      verified evidence, and Delivery State Gate decisions. It is not authored
      independently by Master, Stage, Version, Runtime, Reviewer, Commander, or
      Gate alone.
    required_projection_fields:
      - project_final_goal_ref
      - current_stage_ref
      - current_version_ref
      - gate_status
      - evidence_status
      - next_safe_action_or_blocker

  adopted_rule: >
    Runtime owns facts. Taskbooks own claims. Delivery State Gate owns
    acceptance. User sees accepted truth.
  adopted_rule_chinese: >
    运行时拥有事实。任务书拥有主张。交付状态门拥有接受裁决。用户看到的是
    被接受后的真相。
```

Hard rules:

```text id="state-authority-contract-hard-rules"
No Runtime observation may directly become delivery state.
No Taskbook declaration may become accepted state without evidence and Gate judgment.
No Delivery State Gate may invent state not declared by an owning layer or supported by evidence.
No user-visible truth may omit source ownership, evidence status, and gate result.
Automation may advance execution state only within predeclared transitions accepted by the Gate and within Commander authorization.
Runtime may auto-write facts only; every promotion to truth, authority, or user-visible completion requires Gate or Commander ownership.
If ownership, evidence, or state consistency is unclear, fail closed.
```

Chinese meaning:

```text id="state-authority-contract-hard-rules-zh"
Runtime 的观测事实不能直接变成交付状态。
任务书的状态主张必须有证据和交付状态门裁决，才能变成被接受状态。
交付状态门不能发明上游没有声明、证据没有支持的状态。
用户可见状态必须带来源、证据状态和门控结果。
自动化只能在已声明、已授权、已被门控接受的边界内推进执行状态。
Runtime 只能自动写事实；任何升级成真相、授权或用户可见完成，都必须经过交付状态门或指挥官权责。
如果归属、证据或状态一致性不清楚，就默认阻断。
```

### 9.2 Global Contract Rules

`Global Contract Rules` = 全局契约规则.

Plain Chinese meaning: these rules apply to every minimum contract below.

```text id="minimum-contract-global-rules"
Missing required fields fail closed.
Empty required fields fail closed.
TBD, unknown, or ambiguous authority fields fail closed.
Refs are opaque references, not commitments to a storage backend, runner, UI, CI, or router.
Implementation details are non-authoritative unless a Stage or Version Taskbook separately binds them.
Review findings are evidence, not execution permission.
Hashes identify observed content; hashes do not authorize action.
Validation evidence reports readiness; validation does not authorize state promotion.
Remote, destructive, credential, production, freeze, commit, push, memory-write, or bridge actions require separate explicit Commander authorization.
```

Master must freeze these enum families:

```yaml id="minimum-contract-enums"
minimum_contract_enums:
  risk_level:
    chinese_name: 风险等级
    values:
      - low
      - medium
      - high
      - critical

  validation_status:
    chinese_name: 验证状态
    values:
      - validated
      - unvalidated
      - not_run
      - failed
      - blocked

  execution_status:
    chinese_name: 执行状态
    values:
      - executed
      - partial
      - not_run
      - blocked

  execution_result:
    chinese_name: 执行结果
    values:
      - completed_validated
      - completed_unvalidated
      - partial
      - blocked
      - failed

  review_decision:
    chinese_name: 审查决策
    values:
      - ACCEPT
      - NEEDS_FIX
      - PLAN_ADJUST
      - ABORT

  delivery_state:
    chinese_name: 交付状态
    state_family: top_level_delivery_lifecycle_state
    values:
      - proposed
      - ready
      - in_delivery
      - submitted
      - accepted
      - cancelled
    terminal_states:
      - accepted
      - cancelled
    flags_not_states:
      - blocked
      - at_risk
      - on_hold
      - waiting
    transition_outcomes_not_states:
      - returned_for_revision
    terminal_record_events_not_states:
      - administrative_correction
      - supersede_record
    facets_not_states:
      validation:
        - untested
        - passed
        - failed
        - partial
        - not_required
      approval:
        - none
        - approved
        - denied
        - not_required
      delivery:
        - not_delivered
        - delivered
        - delivery_failed
        - not_required
```

### 9.3 Delivery State Transition Model

`Delivery State Transition Model` = 交付状态转换模型.

Plain Chinese meaning: Master freezes only the main lifecycle of a delivery
item. It does not turn every condition, review action, validation fact, or
external delivery detail into a top-level state.

The adopted model is `small, strict, and boring` = 小、严、朴素.

```yaml id="delivery-state-transition-model"
delivery_state_transition_model:
  status: commander_confirmed_for_discussion_draft
  chinese_name: 交付状态转换模型
  model_type: minimal_canonical_delivery_lifecycle
  transition_application_rule:
    state_writer: Delivery State Gate via GateEvent
    authority_basis_not_state_writer: >
      Commander, delegated Delivery Authority, delivery owner, DRI, reviewer,
      Runtime, and Taskbook records may supply authority basis or evidence, but
      none of them directly writes delivery_state.
    chinese_meaning: >
      指挥官、被委派交付权责、负责人、审查者、Runtime、任务书都可以提供
      权威依据或证据，但不能直接写 delivery_state。状态只能由
      Delivery State Gate 通过 GateEvent 写入。

  canonical_states:
    proposed:
      chinese_name: 已提出
      meaning: A delivery item exists, but is not yet committed for delivery.
      terminal: false
    ready:
      chinese_name: 已就绪
      meaning: Scope, owner, acceptance criteria, priority, and required inputs are known.
      terminal: false
    in_delivery:
      chinese_name: 交付中
      meaning: Work is actively being produced or revised.
      terminal: false
    submitted:
      chinese_name: 已提交验收
      meaning: The owner claims the deliverable is complete and has submitted output or evidence for acceptance review.
      terminal: false
    accepted:
      chinese_name: 已接受
      meaning: Delivery State Gate has accepted the submitted delivery through a GateEvent, using the required acceptance authority basis.
      terminal: true
    cancelled:
      chinese_name: 已取消
      meaning: The item has been intentionally stopped and will not be delivered under this record.
      terminal: true

  condition_flags_not_states:
    blocked: 受阻
    at_risk: 有风险
    on_hold: 暂停
    waiting: 等待中

  facets_not_states:
    validation: 验证维度
    approval: 批准维度
    delivery: 交付送达维度

  transition_outcomes_not_states:
    returned_for_revision: 退回修改

  terminal_record_events_not_states:
    administrative_correction: 行政纠错
    supersede_record: 替代记录
```

Chinese meaning:

```text id="delivery-state-transition-model-zh"
Proposed / 已提出：有交付项，但还没承诺执行。
Ready / 已就绪：范围、负责人、验收标准和优先级清楚了，可以开始。
In Delivery / 交付中：正在做或正在返工。
Submitted / 已提交验收：负责人提交产物和证据，请求验收。
Accepted / 已接受：交付状态门基于必要的验收权威依据，通过 GateEvent 接受，成为用户可见完成。
Cancelled / 已取消：明确停止，此记录不再交付。

Blocked / 受阻不是主状态，而是挂在某个主状态上的条件。
Returned / 已退回不是主状态，而是 Submitted -> In Delivery 的退回修改结果。
Gate review / 状态门审查不是主状态，而是 Submitted 阶段里的审核过程。
Validated / 已验证、Approved / 已批准、Delivered / 已送达不是主状态，而是分层字段。
```

Allowed transitions:

```yaml id="delivery-state-allowed-transitions"
allowed_delivery_state_transitions:
  - from: proposed
    to: ready
    authority_basis: delivery_authority_or_project_lead
    requires:
      - owner
      - scope
      - acceptance_criteria
      - priority
      - required_inputs
  - from: proposed
    to: cancelled
    authority_basis: delivery_authority_or_requester
    requires:
      - cancellation_reason
      - cancellation_authority
  - from: ready
    to: in_delivery
    authority_basis: delivery_owner_or_dri
    requires:
      - start_record
      - known_risks
  - from: ready
    to: cancelled
    authority_basis: delivery_authority_or_project_lead
    requires:
      - cancellation_reason
      - partial_work_disposition_if_any
  - from: in_delivery
    to: submitted
    authority_basis: delivery_owner_or_dri
    requires:
      - output_ref
      - completion_notes
      - evidence_against_acceptance_criteria
      - known_gaps_if_any
  - from: in_delivery
    to: cancelled
    authority_basis: delivery_authority_or_project_lead
    requires:
      - cancellation_reason
      - partial_work_disposition
  - from: submitted
    to: accepted
    authority_basis: acceptance_authority_or_commander_delegation
    requires:
      - accepted_output_ref
      - acceptance_criteria_checked
      - evidence_refs
      - acceptance_timestamp
      - acceptance_authority_ref
  - from: submitted
    to: in_delivery
    transition_outcome: returned_for_revision
    authority_basis: reviewer_or_acceptance_authority_basis
    requires:
      - revision_reason
      - failed_acceptance_criteria_or_change_request
      - required_changes
      - scope_change_status
  - from: submitted
    to: cancelled
    exceptional: true
    authority_basis: commander_or_delegated_cancellation_authority
    requires:
      - cancellation_reason
      - why_submission_no_longer_needed
      - partial_work_disposition
```

Forbidden transitions:

```text id="delivery-state-forbidden-transitions"
proposed -> in_delivery
proposed -> submitted
proposed -> accepted
ready -> submitted
ready -> accepted
in_delivery -> accepted
submitted -> ready
submitted -> proposed
accepted -> proposed
accepted -> ready
accepted -> in_delivery
accepted -> submitted
accepted -> cancelled
cancelled -> proposed
cancelled -> ready
cancelled -> in_delivery
cancelled -> submitted
cancelled -> accepted
any state -> proposed
administrative_correction is not a delivery_state transition
any state -> accepted without submitted output and evidence
```

Terminal state rule:

```text id="delivery-terminal-state-rule"
Accepted and cancelled are terminal states.
Accepted work must not be reopened as a normal transition.
Post-acceptance record errors require administrative correction.
Post-acceptance invalid acceptance basis requires a supersede record.
Post-acceptance new scope or new work requires a new item or change request.
```

Terminal correction, supersede, and new-item rule:

```yaml id="delivery-terminal-correction-supersede-rule"
terminal_correction_supersede_rule:
  chinese_name: 终态纠错、替代记录与新交付项规则
  product_principle: Accepted is not reopened; it is corrected, superseded, or followed by a new item.
  product_principle_chinese: 已接受项不重开普通生命周期；只能行政纠错、追加替代记录，或创建新交付项。

  administrative_correction:
    chinese_name: 行政纠错
    use_when: record_error_without_changed_acceptance_result
    plain_chinese_meaning: 行政纠错只能修账本，不能改判决。
    allowed_examples:
      - wrong evidence link
      - wrong hash transcription while underlying content is unchanged
      - wrong timestamp, attachment id, file name, version label, or display label
      - correct evidence existed at acceptance time but was linked incorrectly or omitted from the record
      - traceability metadata needs correction while the original acceptance still stands
    required_conditions:
      - does_not_change_delivery_subject
      - does_not_change_accepted_artifact
      - does_not_change_acceptance_scope
      - does_not_change_review_decision
      - does_not_change_gate_authority
      - does_not_change_evidence_content_hash
      - acceptance_still_valid
      - append_only
    required_fields:
      - correction_id
      - target_record_ref
      - correction_type
      - corrected_fields
      - old_values
      - new_values
      - reason
      - actor
      - authority_basis
      - evidence_refs
      - created_at
      - impact_assessment
      - preserves_delivery_state: true
      - append_only: true
    gate_invariant: administrative_correction may annotate terminal records, but must not change terminal authority, acceptance basis, artifact identity, evidence content hash, delivery scope, or delivery_state.

  supersede_record:
    chinese_name: 替代记录
    use_when: accepted_or_cancelled_history_remains_but_current_authoritative_interpretation_must_be_replaced
    plain_chinese_meaning: 替代记录保留旧历史，但声明后续以新记录为准。
    required_when:
      - evidence proves a different item, artifact, version, or scope
      - original evidence did not support acceptance
      - accepted artifact was wrong
      - reviewer or Gate authority was invalid
      - ReviewDecision was not actually made or was recorded incorrectly in a substantive way
      - acceptance scope or requirements were misapplied
      - evidence was forged, polluted, unverifiable, or mismatched to the delivery item
      - the old terminal conclusion must no longer be treated as the current valid conclusion
    required_fields:
      - supersede_id
      - original_item_ref
      - replacement_item_ref
      - supersede_reason
      - supersede_authority_ref
      - relationship
      - carry_forward_evidence_refs
      - invalidated_or_replaced_basis_refs
      - created_at
    invariants:
      - supersede does not reopen the original terminal item.
      - supersede does not delete or rewrite the old record.
      - the original item keeps its terminal delivery_state.
      - the replacement item must use its own EvidencePackage, ReviewDecision, and Gate transition before acceptance.

  new_item:
    chinese_name: 新交付项
    use_when: new_scope_or_new_work_is_required
    required_when:
      - new requirement
      - new acceptance standard
      - follow-on improvement
      - new environment or integration issue
      - defect outside the original accepted scope
      - second version or continuation work
      - one accepted issue splits into multiple follow-on tasks
    invariants:
      - the original accepted item remains accepted.
      - the new item carries the new lifecycle.
      - the new item may reference the original item as background, not as reopened work.

  forbidden_interpretations:
    - accepted -> in_delivery
    - accepted -> submitted
    - accepted -> cancelled
    - cancelled -> accepted
    - administrative_correction changes acceptance result
    - administrative_correction replaces evidence content in place
    - administrative_correction changes delivery_state
    - supersede deletes old record
    - supersede silently rewrites history
    - new evidence silently repairs old approval
    - hash reuse across changed content
```

Blocked flag policy:

```yaml id="delivery-blocked-condition-rule"
blocked_flag_policy:
  chinese_name: 受阻标记策略
  blocked_is_state: false
  blocked_is_condition_flag: true
  core_rule:
    - Executor owns run-level truth.
    - Gate owns item-level blocked truth.
    - Review can proceed while blocked.
    - Acceptance cannot finalize while blocked remains active.
  applies_to_states:
    - proposed
    - ready
    - in_delivery
    - submitted
  forbidden_active_on_terminal_states:
    - accepted
    - cancelled
  delivery_item_blocked_model:
    delivery_item_blocked_is_directly_writable: false
    delivery_item_blocked_is_gate_derived: true
    derived_from: active ItemBlocker records
    meaning: delivery_item.blocked is true when at least one active ItemBlocker exists for the item.

  executor_permissions:
    may:
      - set executor_run.blocked for its own run
      - clear executor_run.blocked for its own run
      - create EvidencePackage with type blocker_report
      - emit BlockerReported evidence
      - emit BlockerResolved evidence
      - request Gate to set delivery_item.blocked
      - request Gate to clear delivery_item.blocked
    must_not:
      - write delivery_item.blocked
      - clear delivery_item.blocked
      - write delivery_item.delivery_state
      - treat EvidencePackage as approval
      - treat ReviewDecision as a state transition

  review_while_blocked:
    submitted_blocked_review_allowed: true
    submitted_blocked_acceptance_finalization_allowed: false
    allowed_acceptance_path:
      - Gate reviews submitted item and active blockers.
      - Gate clears, waives, or invalidates all active ItemBlockers in the same transaction.
      - Gate applies accepted only when the resulting blocked flag is false.
    invalid_states:
      - accepted + blocked=true
      - cancelled + blocked=true

  required_fields_when_blocked:
    - blocker_id
    - blocker_category
    - blocker_summary
    - blocker_owner
    - blocked_since
    - source_actor
    - source_authority_domain
    - affected_delivery_state
    - impact
    - evidence_refs
    - authority_required
    - unblock_condition
    - next_review_date_or_unblock_condition
    - allowed_next_actions
    - forbidden_next_actions

  item_blocker_minimum:
    chinese_name: 交付项阻塞记录最小字段
    required_fields:
      - item_blocker_id
      - item_id
      - blocker_category
      - blocker_summary
      - blocker_owner
      - status
      - source_actor
      - source_authority_domain
      - affected_delivery_state
      - impact
      - evidence_refs
      - authority_required
      - unblock_condition
      - created_at
      - last_reviewed_at
    status_values:
      - active
      - cleared
      - waived
      - invalidated
    closure_required_fields:
      - closure_reason
      - closure_actor
      - closure_authority
      - closure_evidence_refs
      - closed_at

  required_invariants:
    - delivery_item.blocked can change only through GateBlockerApplied, GateBlockerCleared, GateBlockerWaived, or GateBlockerInvalidated.
    - Clearing blocked never advances delivery_state.
    - A separate allowed transition record is always required for lifecycle movement.
    - submitted + blocked=true may enter review, but cannot finalize as accepted while any active ItemBlocker remains.
    - accepted implies blocked=false.
    - cancelled implies blocked=false, or blocker history is closed into the cancellation reason.
```

Transition record rule:

```yaml id="delivery-transition-record-rule"
delivery_transition_record:
  required_for_every_transition:
    - gate_event_id
    - item_id
    - prior_state_version
    - resulting_state_version
    - from_state
    - to_state
    - actor
    - authority_basis
    - timestamp
    - reason
    - evidence_refs_where_applicable
  invariants:
    - delivery_transition_record is a view of an applied GateEvent, not a separate state writer.
    - gate_event_id must bind to the append-only GateEvent that applied the transition.
  accepted_requires:
    - accepted_output_ref
    - accepted_version_or_package_ref
    - acceptance_authority_ref
    - acceptance_notes
  cancelled_requires:
    - cancellation_reason
    - cancellation_authority_ref
    - replacement_item_ref_if_any
    - partial_work_disposition
```

### 9.4 Runtime State Compatibility Mapping

`runtime_state_compatibility_mapping` = 运行态兼容映射.

Plain Chinese meaning: legacy runtime states are evidence signals from current
execution machinery. They may support evidence, review, or Gate requests, but
they do not own delivery lifecycle, item-level blocked truth, terminal state,
taskbook scope, or Commander authority.

```text id="runtime-state-compatibility-core-rule"
Legacy runtime states may contribute facts.
They do not own delivery lifecycle.
```

Chinese meaning:

```text id="runtime-state-compatibility-core-rule-zh"
旧运行态可以贡献事实。
旧运行态不拥有交付生命周期。
```

```yaml id="runtime-state-compatibility-mapping"
runtime_state_compatibility_mapping:
  chinese_name: 运行态兼容映射
  status: commander_confirmed_for_discussion_draft

  core_invariants:
    - Runtime states are evidentiary signals, not delivery lifecycle states.
    - Runtime states may create or support EvidencePackage entries, ReviewDecision inputs, or Gate review requests.
    - Runtime states must not directly mutate delivery_state.
    - Runtime states must not directly mutate delivery_item.blocked.
    - Runtime states must not reopen terminal states.
    - Runtime states must not mutate taskbook scope or Commander authority.

  legacy_states:
    RUNNING_ACCEPTANCE:
      chinese_name: 正在跑验收
      correct_domain: runtime_execution_fact
      may_contribute:
        - evidence_status: pending
        - acceptance_runner_started_fact
        - review_or_gate_pending_signal
      must_not_mean:
        - submitted
        - accepted
        - rejected
        - cancelled

    VERSION_PASSED:
      chinese_name: 版本检查通过
      correct_domain: validation_receipt_fact
      may_contribute:
        - version_validation_passed_evidence
        - compatibility_check_receipt
      must_not_mean:
        - accepted
        - gate_approved
        - implementation_authorized

    PASSED:
      chinese_name: 检查通过
      correct_domain: validation_receipt_fact
      may_contribute:
        - positive_check_entry_in_EvidencePackage
        - validation_status_passed_for_declared_scope
      must_not_mean:
        - accepted
        - automatic_Gate_transition
        - Commander_authorization

    COMPLETED:
      chinese_name: 执行完成
      correct_domain: execution_completion_fact
      may_contribute:
        - run_finished_fact
        - support_for_submission_request_when_EvidencePackage_is_complete
      must_not_mean:
        - submitted
        - accepted
        - review_decision_recorded

    BLOCKED:
      chinese_name: 运行阻塞
      correct_domain: blocker_evidence_fact
      may_contribute:
        - executor_run.blocked: true
        - BlockerReported evidence
        - request Gate to create ItemBlocker
      must_not_mean:
        - delivery_item.blocked authoritative write
        - top_level_delivery_state
        - cancelled
        - plan_change

    FAILED_BLOCKED:
      chinese_name: 失败且阻塞
      correct_domain: failure_and_blocker_evidence_fact
      may_contribute:
        - failed_validation_record
        - blocker_evidence
        - request Gate to create ItemBlocker
        - ReviewDecision input for NEEDS_FIX, PLAN_ADJUST, or ABORT
      must_not_mean:
        - cancelled
        - NEEDS_FIX by itself
        - top_level_delivery_state
        - automatic_scope_change

  forbidden_interpretations:
    - PASSED -> accepted
    - VERSION_PASSED -> accepted
    - COMPLETED -> submitted
    - COMPLETED -> accepted
    - BLOCKED -> delivery_item.blocked without Gate
    - FAILED_BLOCKED -> cancelled
    - RUNNING_ACCEPTANCE -> submitted
    - RUNNING_ACCEPTANCE -> accepted
    - runtime_state -> user_visible_accepted_truth without Gate projection
```

### 9.5 User Visible Status Projection

`User Visible Status Projection` = 用户可见状态投影.

Plain Chinese meaning: the user-visible status is a read-only projection for
humans. It may summarize evidence and review context, but only GateEvent may
project `delivery_state` and `blocked`.

```text id="user-visible-status-projection-core-rule"
User Visible Status is a read-only projection, not an authority source.
User Visible Status may summarize evidence and review context, but only GateEvent may project delivery_state and blocked.
```

Chinese meaning:

```text id="user-visible-status-projection-core-rule-zh"
用户可见状态是只读投影，不是新的权威来源。
用户可见状态可以摘要展示证据和审查上下文，但只有 GateEvent 可以投影交付状态和受阻标记。
```

```yaml id="user-visible-status-projection"
user_visible_status_projection:
  chinese_name: 用户可见状态投影
  status: commander_confirmed_for_discussion_draft
  projection_type: read_only_view

  authority_boundary:
    - Runtime facts are evidence, not user-visible accepted truth.
    - Taskbook claims are claims, not user-visible accepted truth.
    - EvidencePackage is evidence, not user-visible accepted truth.
    - ReviewDecision is a review record, not user-visible accepted truth.
    - Legacy runtime states are evidentiary signals, not user-visible accepted truth.
    - GateEvent is the only source that may project delivery_state and blocked into the user-visible status.

  minimum_fields:
    status:
      chinese_name: 交付状态
      source: GateEvent-applied delivery_state
      values:
        - proposed
        - ready
        - in_delivery
        - submitted
        - accepted
        - cancelled
    blocked:
      chinese_name: 是否受阻
      source: Gate-derived active ItemBlocker
      values:
        - true
        - false
    status_text:
      chinese_name: 人话状态摘要
      source: safe projection text
      examples:
        - 已提交，等待验收
        - 交付中，但等待 Commander 授权
        - 已接受
    evidence_status:
      chinese_name: 证据状态
      source: EvidencePackage plus runtime facts and claim alignment
      authority: context_only_not_delivery_state
      values:
        - missing
        - partial
        - present
        - contested
        - sufficient_for_review
    review_status:
      chinese_name: 审查状态
      source: ReviewDecision
      authority: context_only_not_delivery_state
      values:
        - not_reviewed
        - under_review
        - acceptance_recommended
        - changes_requested
        - rejected
        - superseded
    next_visible_action:
      chinese_name: 下一步可见动作
      examples:
        - wait_for_review
        - provide_evidence
        - continue_delivery
        - wait_for_authorization
        - no_action

  optional_fields:
    - owner
    - last_gate_result
    - updated_at
    - known_gaps

  projection_rules:
    - delivery_state must come from GateEvent-applied state.
    - blocked must come from Gate-derived active ItemBlocker.
    - evidence_status may summarize evidence context, but must not become delivery_state.
    - review_status may summarize ReviewDecision context, but acceptance_recommended must not become accepted without GateEvent.
    - updated_at must prefer GateEvent timestamp for status and blocked changes.
    - known_gaps must be short, actionable, and safe for user display.

  runtime_projection_limits:
    PASSED: evidence_status or summary only; never accepted.
    VERSION_PASSED: evidence_status or summary only; never accepted.
    COMPLETED: evidence_status or summary only; never submitted or accepted.
    BLOCKED: blocker evidence only; never delivery_item.blocked without Gate.
    FAILED_BLOCKED: failure and blocker evidence only; never cancelled or NEEDS_FIX by itself.
    RUNNING_ACCEPTANCE: pending evidence only; never submitted or accepted.

  hidden_or_degraded_details:
    - raw stdout or stderr
    - raw runtime states
    - EvidencePackage raw internals
    - local filesystem paths not needed for review
    - environment variables
    - secrets or credentials
    - ReviewDecision internal reasoning or disagreement
    - GateEvent replay internals
    - Commander authorization tokens or private policy reasoning
    - draft Taskbook claim disputes
    - ungated runtime facts or conclusions

  forbidden_interpretations:
    - Runtime PASSED -> status accepted
    - Runtime COMPLETED -> status accepted
    - Runtime BLOCKED -> blocked true without active ItemBlocker
    - ReviewDecision acceptance_recommended -> status accepted without GateEvent
    - Taskbook claim accepted -> status accepted
    - EvidencePackage complete -> status accepted
    - latest runtime signal -> user-visible truth
```

### 9.6 Execution Envelope Minimum Contract

`execution_envelope_minimum_contract` = 执行边界最小契约.

Plain Chinese meaning: before execution starts, the system must know the goal,
stage, scope, allowed actions, forbidden actions, risk, approval requirement,
and stop conditions.

```yaml id="execution-envelope-minimum-contract"
execution_envelope_minimum_contract:
  chinese_name: 执行边界最小契约
  required_fields:
    - envelope_id
    - schema_version
    - task_id
    - stage_id
    - parent_refs
    - actor_role
    - intent
    - scope
    - allowed_paths
    - forbidden_paths
    - allowed_actions
    - forbidden_actions
    - risk_level
    - inputs
    - target_artifacts
    - validation_commands
    - evidence_requirements
    - stop_conditions
    - approval_required
    - authority_limits
    - reporting_destination
    - expected_receipt_contract

  parent_refs_required_fields:
    - master_taskbook_ref
    - stage_taskbook_ref
    - version_taskbook_ref
    - workspace_head_ref

  allowed_action_taxonomy:
    allowed_without_new_commander_gate_when_inside_envelope:
      - read
      - inspect
      - narrow_edit
      - run_listed_validation
      - generate_receipt
    requires_commander_hard_gate:
      - dependency_upgrade
      - lockfile_rewrite
      - credential_change
      - remote_action
      - broad_formatting
      - destructive_file_operation
      - core_state_machine_semantic_change
    forbidden_in_envelope:
      - commit
      - push
      - release
      - deploy
      - force_reset
      - secret_printing
      - delivery_state_write

  required_invariants:
    - task_id must be stable and traceable.
    - stage_id must bind to a Stage Taskbook or explicit stage.
    - parent_refs must match observed workspace reality before dispatch.
    - intent must describe purpose, not implementation steps.
    - scope must define what may be touched.
    - allowed_paths and forbidden_paths must be checkable before dispatch.
    - allowed_actions and forbidden_actions must be checkable.
    - validation_commands must be explicit or explicitly not_required with reason.
    - evidence_requirements must be explicit, even when minimal.
    - high or critical risk must require explicit Commander approval.
    - approval_required must not be inferred from natural language.
    - missing or mismatched parent references fail closed.
    - any path, action, command, stop condition, or evidence mismatch fails closed before dispatch.

  deferred_to_stage_or_version:
    - executor name
    - working directory
    - environment
    - timeout
    - retry policy
    - tool choice
    - script path
    - implementation steps
```

### 9.7 Execution And Validation Receipt Minimum Contract

`execution_validation_receipt_minimum_contract` = 执行与验证回执最小契约.

Plain Chinese meaning: after work runs, the system must know what happened,
what changed, what validation ran, what did not run, what failed, and where the
evidence is.

```yaml id="execution-validation-receipt-minimum-contract"
execution_validation_receipt_minimum_contract:
  chinese_name: 执行与验证回执最小契约
  required_fields:
    - receipt_id
    - schema_version
    - envelope_id
    - task_id
    - stage_id
    - actor_role
    - receipt_source
    - produced_by
    - workspace_ref_before
    - workspace_ref_after
    - head_ref_before
    - head_ref_after
    - started_at
    - completed_at
    - actions_taken
    - artifacts_changed
    - validation
    - result
    - deviations
    - blocked_reason
    - command_transcript_digest
    - envelope_compatibility
    - integrity_digest
    - evidence_refs

  receipt_source_values:
    - runtime_observed
    - imported_from_executor
    - imported_from_external_review
    - manually_attested_by_commander

  envelope_compatibility_required_fields:
    - parent_refs_match
    - allowed_paths_respected
    - forbidden_paths_untouched
    - allowed_actions_respected
    - validation_commands_status
    - stop_conditions_respected

  validation_required_fields:
    - status
    - checks_run
    - checks_not_run
    - failures
    - uncertainty

  required_invariants:
    - receipt_id must be unique.
    - envelope_id or task_id must bind back to the execution envelope.
    - receipt_source must distinguish runtime-observed evidence from imported evidence.
    - produced_by must identify the actor or system that produced the receipt.
    - workspace_ref_before and workspace_ref_after must be explicit for mutable workspaces.
    - head_ref_before and head_ref_after must be explicit when Git state is relevant.
    - actions_taken must describe observed facts, not plans.
    - artifacts_changed must be explicit, even when empty.
    - checks_run and checks_not_run must be separated.
    - completed_unvalidated must never be reported as completed_validated.
    - deviations must be explicit, even when empty.
    - blocked_reason is required when result is blocked or failed.
    - command_transcript_digest may bind summarized logs without including raw long logs.
    - imported receipts must declare provenance and envelope compatibility before they can be used as evidence.
    - integrity_digest binds the receipt record identity, not truth or authorization.
    - evidence_refs must point to reviewable evidence, not vague claims.

  deferred_to_stage_or_version:
    - concrete validation commands
    - framework-specific report format
    - raw logs
    - screenshot paths
    - coverage metrics
    - benchmark numbers
    - detailed failure excerpts
```

### 9.8 Delivery State Gate Minimum Contract

`delivery_state_gate_minimum_contract` = 交付状态门最小契约.

Plain Chinese meaning: a task can move from one state to another only when the
required receipts, validation status, risks, reviewer requirement, and decision
record allow the movement.

```yaml id="delivery-state-gate-minimum-contract"
delivery_state_gate_minimum_contract:
  chinese_name: 交付状态门最小契约
  required_fields:
    - gate_id
    - task_id
    - stage_id
    - from_state
    - to_state
    - required_receipts
    - required_artifacts
    - required_validation_status
    - open_risks
    - reviewer_required
    - decision_status
    - decision_ref
    - resulting_gate_event_ref
    - blocking_conditions

  required_invariants:
    - gate_id must be unique.
    - required_receipts must exist and be traceable.
    - required_artifacts must align with target_artifacts from the envelope.
    - open_risks must be explicit, even when empty.
    - reviewer_required true prevents automatic pass.
    - decision_status must not create a new implementation task by itself.
    - decision_ref must bind to review or Commander decision evidence.
    - resulting_gate_event_ref is required when a transition or blocked projection is applied.
    - to_state must be allowed by the frozen delivery_state enum.
    - accepted and cancelled are terminal states.
    - blocked is a condition flag, not a top-level delivery_state.
    - returned_for_revision is a transition outcome from submitted to in_delivery, not a top-level delivery_state.
    - missing decision evidence fails closed.

  deferred_to_stage_or_version:
    - stage-specific gate count
    - stage-specific thresholds
    - detailed review checklist
    - release channel
    - deployment target
    - notification route
    - QA matrix
```

GateEvent minimum record:

```yaml id="gate-event-minimum-contract"
gate_event_minimum_contract:
  chinese_name: 状态门事件最小契约
  meaning: >
    GateEvent is the append-only record emitted by Delivery State Gate when it
    applies or rejects a delivery_state transition or item-level blocked change.
  chinese_meaning: >
    GateEvent / 状态门事件，是 Delivery State Gate 作出的可追溯状态裁决记录。
    它是 accepted、cancelled、returned_for_revision、blocked 变化进入用户可见状态的
    唯一账本事件。

  required_fields:
    - gate_event_id
    - schema_version
    - gate_id
    - task_id
    - stage_id
    - event_type
    - authority_basis
    - prior_state_version
    - resulting_state_version
    - from_state
    - to_state
    - transition_outcome
    - blocker_changes
    - evidence_refs
    - review_decision_refs
    - receipt_refs
    - actor
    - created_at
    - idempotency_key
    - conflict_check

  event_type_values:
    - transition_applied
    - transition_rejected
    - blocker_applied
    - blocker_cleared
    - blocker_waived
    - blocker_invalidated
    - correction_recorded
    - supersede_recorded

  required_invariants:
    - GateEvent is append-only.
    - GateEvent is the only record that may write delivery_state.
    - GateEvent is the only record that may change delivery_item.blocked.
    - authority_basis must identify Commander, delegated Delivery Authority, reviewer, policy, or runtime evidence used by the Gate.
    - prior_state_version must match before the event is applied.
    - resulting_state_version must be unique and monotonic for the delivery item.
    - idempotency_key prevents duplicate application.
    - conflict_check must fail closed on stale parent refs, stale state version, missing evidence, or active blockers that prevent acceptance.
    - accepted may be applied only when blocked is false after blocker_changes.
    - rejected GateEvent does not mutate delivery_state.
```

### 9.9 Evidence Package Minimum Contract

`evidence_package_minimum_contract` = 证据包最小契约.

Plain Chinese meaning: the evidence package is the smallest review input that
lets the Delivery State Gate understand what was submitted, what was checked,
what was not checked, what risks remain, and what decision is being requested.
It is evidence, not approval, and it cannot mutate `delivery_state`.

```yaml id="evidence-package-minimum-contract"
evidence_package_minimum_contract:
  chinese_name: 证据包最小契约
  purpose:
    - record the submitted delivery evidence
    - bind checks and artifacts to an explicit scope
    - expose unvalidated items and remaining risks
    - request a Gate decision without applying that decision

  required_fields:
    - evidence_package_id
    - schema_version
    - task_ref
    - submission
    - state_context
    - artifacts
    - checks
    - not_validated
    - remaining_risks
    - authority_required

  task_ref:
    required_fields:
      - taskbook_id
      - task_id
      - scope_ref
    meaning: The exact taskbook, task or delivery unit, and acceptance scope this evidence package covers.

  submission:
    required_fields:
      - submitted_by
      - submitted_at
      - submitted_summary
      - requested_gate_action
    requested_gate_action:
      meaning: Request only. This is not a ReviewDecision and does not apply any state transition.
      values:
        - request_acceptance_review
        - request_revision_review
        - request_blocking_review
        - request_cancellation_review

  state_context:
    required_fields:
      - delivery_state_seen
      - condition_flags_seen
      - state_version_seen
    meaning: The state observed before review. It is context only and does not grant state-transition authority.

  artifacts:
    item_required_fields:
      - artifact_id
      - kind
      - uri
      - immutable_ref_or_digest

  checks:
    item_required_fields:
      - check_id
      - kind
      - outcome
      - evidence_ref
      - checked_at
      - limitations

  required_invariants:
    - EvidencePackage is evidence, not approval.
    - EvidencePackage cannot mutate delivery_state.
    - Hash is identity, not approval.
    - Validation is evidence, not authorization.
    - Runtime outcome is signal, not delivery_state.
    - delivery_state_seen is observed context, not a requested or resulting state.
    - blocked may appear only in condition_flags_seen or remaining_risks, not as a top-level delivery_state.
    - PASSED, COMPLETED, and BLOCKED runtime outcomes must not be copied or mapped into delivery_state.
    - not_validated must be explicit, even when empty.
    - remaining_risks must be explicit, even when empty.
    - authority_required must identify the Gate or authority required before any state transition can be applied.
    - requested_gate_action is only a request for Gate attention, not a ReviewDecision.
    - ReviewDecision and GateEvent must bind to EvidencePackage, not be hidden inside it.

  excluded_from_minimum:
    - full runtime logs
    - full conversation records
    - chain-of-thought
    - complex risk scoring
    - coverage trends
    - multi-party approval matrix
    - dependency graph
    - dashboard analytics
    - delivery_state_after
    - acceptance_rationale
    - gate_event
```

### 9.10 Reviewer Handoff And Decision Minimum Contract

`reviewer_handoff_decision_minimum_contract` = 审查交接与决策最小契约.

Plain Chinese meaning: Reviewer must receive enough bound evidence to decide
ACCEPT, NEEDS_FIX, PLAN_ADJUST, or ABORT without rerunning the whole task.

```yaml id="reviewer-handoff-decision-minimum-contract"
reviewer_handoff_decision_minimum_contract:
  chinese_name: 审查交接与决策最小契约
  required_fields:
    - handoff_id
    - task_id
    - stage_id
    - bound_inputs
    - goal_context
    - scope_reviewed
    - changed_artifacts
    - receipts
    - validation_summary
    - known_risks
    - unresolved_questions
    - review_axes
    - reviewer_focus
    - decision_needed
    - next_state_request_shape

  bound_inputs_required_fields:
    - master_taskbook_ref
    - stage_taskbook_ref
    - version_taskbook_ref
    - execution_report_ref
    - workspace_snapshot_ref

  review_axes_required_fields:
    - charter_alignment
    - task_completion
    - scope_assessment
    - validation_truth
    - evidence_sufficiency
    - residual_risk
    - unresolved_items

  required_invariants:
    - decision_needed must use ACCEPT, NEEDS_FIX, PLAN_ADJUST, or ABORT.
    - changed_artifacts must be derived from receipts.
    - validation_summary must distinguish validated, unvalidated, not_run, failed, and blocked.
    - known_risks and unresolved_questions must be explicit, even when empty.
    - reviewer_focus may guide review but must not limit findings.
    - review decisions are review records first.
    - authorized lifecycle transitions require separate authority validation.
    - reviewer decision must not automatically mutate plan, state, Git, memory, route, or remote systems.
    - delivery_state and item-level blocked changes require Delivery State Gate GateEvent.
    - Commander or delegated Delivery Authority may provide authority basis for follow-on changes, not direct state mutation.

  deferred_to_stage_or_version:
    - handoff prose template
    - stage-specific review questions
    - domain-specific evidence attachments
    - diff display format
    - screenshot requirements
    - benchmark requirements
    - role-specific checklist wording
```

### 9.11 Review Decision Mapping

`Review Decision Mapping` = 审查决策映射.

Plain Chinese meaning: Reviewer output first becomes a review record. It may
request a state transition, but delivery_state changes only when Delivery State
Gate applies a GateEvent using the required authority basis.

```text id="review-decision-mapping-core-rule"
Reviewers may identify outcomes.
Only Delivery State Gate applies delivery_state changes through GateEvent.
Commander or delegated Delivery Authority may provide authority basis, not a direct state write.
```

Chinese meaning:

```text id="review-decision-mapping-core-rule-zh"
Reviewer 可以指出结果。
只有 Delivery State Gate 可以通过 GateEvent 应用交付状态变化。
Commander 或被委派交付权责可以提供权威依据，但不是直接写状态。
```

```yaml id="review-decision-mapping"
review_decision_mapping:
  status: commander_confirmed_for_discussion_draft
  chinese_name: 审查决策映射
  decisions:
    ACCEPT:
      chinese_name: 接受
      requested_delivery_state_effect: submitted -> accepted
      transition_outcome: accepted_by_gate
      required_authority: Delivery State Gate
      if_actor_lacks_required_authority:
        resulting_action: gate_review_required
        record_outcome: acceptance_recommended
      forbidden:
        - automatic_push
        - automatic_release
        - automatic_deploy
        - automatic_remote_close

    NEEDS_FIX:
      chinese_name: 需要修复
      requested_delivery_state_effect: submitted -> in_delivery
      transition_outcome: returned_for_revision
      required_authority: Delivery State Gate
      meaning: >
        The item was submitted and reviewed against the current taskbook or
        acceptance criteria, but the submitted work did not satisfy the criteria
        while remaining deliverable through rework.
      forbidden:
        - create_top_level_needs_fix_state
        - create_top_level_returned_state
        - create_top_level_rejected_state
        - automatic_scope_expansion
        - automatic_plan_change

    PLAN_ADJUST:
      chinese_name: 计划调整
      requested_delivery_state_effect: none
      record_outcome: plan_adjustment_required
      resulting_action: commander_decision_requested
      required_authority_for_follow_on_change: Commander or delegated Delivery Authority
      allowed_gate_request:
        request_item_blocker: true when no further delivery work should proceed before Commander decision
        suggested_blocker_reason: pending_plan_adjustment_decision
        note: Request only. GateEvent must apply, waive, clear, or invalidate the ItemBlocker.
      forbidden:
        - PLAN_ADJUST -> accepted
        - PLAN_ADJUST -> in_delivery
        - PLAN_ADJUST -> ready
        - PLAN_ADJUST -> cancelled
        - automatic_taskbook_mutation
        - automatic_scope_change
        - automatic_acceptance_criteria_change

    ABORT:
      chinese_name: 中止
      requested_delivery_state_effect: none
      record_outcome: cancellation_recommended
      resulting_action: commander_decision_requested
      required_authority_for_follow_on_cancellation: Commander or delegated Delivery Authority
      allowed_gate_request:
        request_item_blocker: true when continuing delivery is unsafe before cancellation decision
        suggested_blocker_reason: pending_cancellation_decision
        note: Request only. GateEvent must apply, waive, clear, or invalidate the ItemBlocker.
      forbidden:
        - ABORT -> cancelled without explicit cancellation authority
        - automatic_delete
        - automatic_revert
        - automatic_remote_close
        - automatic_cleanup
```

Compact rule set:

```text id="review-decision-compact-rule-set"
ACCEPT:
  submitted -> accepted
  only by Delivery State Gate

NEEDS_FIX:
  submitted -> in_delivery
  outcome = returned_for_revision
  only by Delivery State Gate

PLAN_ADJUST:
  no direct delivery_state change
  record plan_adjustment_required
  request Commander decision
  may request ItemBlocker, but cannot set delivery_item.blocked directly

ABORT:
  no direct delivery_state change
  record cancellation_recommended
  request Commander decision
  may request ItemBlocker, but cannot set delivery_item.blocked directly
```

Minimum review decision record:

```yaml id="review-decision-record-minimum"
review_decision_record:
  required_fields:
    - review_decision_id
    - item_id
    - submission_id
    - delivery_state_at_review
    - taskbook_id
    - taskbook_version
    - reviewer_id
    - reviewer_role
    - reviewer_authority_scope
    - decision
    - decision_reason
    - evidence_refs
    - created_at
    - resulting_action
    - resulting_action_id

  decision_values:
    - ACCEPT
    - NEEDS_FIX
    - PLAN_ADJUST
    - ABORT

  resulting_action_values:
    - state_transition_applied
    - gate_review_required
    - commander_decision_requested
    - no_action
```

Decision-specific minimum fields:

```yaml id="review-decision-specific-fields"
review_decision_specific_fields:
  ACCEPT:
    - accepted_criteria_refs
    - runtime_fact_refs
    - gate_actor_id
    - transition_id
    - from_state: submitted
    - to_state: accepted
    - transition_outcome: accepted_by_gate

  NEEDS_FIX:
    - failed_criteria_refs
    - required_fix_summary
    - runtime_fact_refs
    - gate_actor_id
    - transition_id
    - from_state: submitted
    - to_state: in_delivery
    - transition_outcome: returned_for_revision

  PLAN_ADJUST:
    - plan_issue_summary
    - affected_taskbook_sections
    - requested_commander_decision_id
    - plan_adjustment_required: true
    - blocked_flag_change_if_any
    - no_delivery_state_transition_embedded: true

  ABORT:
    - abort_reason
    - risk_or_boundary_issue_summary
    - requested_commander_decision_id
    - cancellation_recommended: true
    - blocked_flag_change_if_any
    - no_cancellation_transition_embedded: true
```

Forbidden shortcuts:

```text id="review-decision-forbidden-shortcuts"
reviewer_ACCEPT_without_gate -> accepted
validation_passed -> accepted
approval_recorded -> accepted
delivery_complete -> accepted
taskbook_claim_satisfied -> accepted
runtime_fact_update -> delivery_state_change
taskbook_claim_update -> delivery_state_change
review_decision -> delivery_item.blocked without GateEvent
PLAN_ADJUST -> delivery_item.blocked without GateEvent
ABORT -> delivery_item.blocked without GateEvent
blocked = false -> ready
blocked = false -> submitted
blocked = false -> accepted
PLAN_ADJUST -> accepted
PLAN_ADJUST -> in_delivery
PLAN_ADJUST -> ready
PLAN_ADJUST -> cancelled
ABORT -> cancelled without explicit Commander or delegated Delivery Authority confirmation
submitted artifact changes in place without new submission_id or revision record
```

Authority boundary:

```text id="review-decision-authority-boundary"
Runtime owns facts.
Taskbooks own claims.
Delivery State Gate owns accepted.
Commander owns plan and cancellation boundary changes.
User sees only accepted truth.
```

### 9.12 Commander Decision Request Minimum Contract

`commander_decision_request_minimum_contract` = 指挥官决策请求最小契约.

Plain Chinese meaning: this object asks the Commander for a bounded decision.
It is not the decision itself, and it cannot mutate plan, state, Git, memory,
route, bridge, or remote systems.

```yaml id="commander-decision-request-minimum-contract"
commander_decision_request_minimum_contract:
  chinese_name: 指挥官决策请求最小契约
  required_fields:
    - commander_decision_request_id
    - schema_version
    - task_id
    - stage_id
    - source_review_decision_ref
    - source_evidence_package_ref
    - requested_decision_type
    - requested_action
    - scope_ref
    - authority_needed
    - options
    - recommended_option
    - risk_summary
    - blocked_context
    - non_mutation_notice
    - created_at

  requested_decision_type_values:
    - accept_via_gate_review
    - return_for_revision_via_gate_review
    - adjust_plan
    - cancel_item
    - defer_decision
    - continue_next_loop

  requested_action_values:
    accept_via_gate_review:
      chinese_name: 请求状态门验收
      effect_if_authorized: Delivery State Gate may emit GateEvent if evidence is sufficient.
    return_for_revision_via_gate_review:
      chinese_name: 请求状态门退回修改
      effect_if_authorized: Delivery State Gate may emit returned_for_revision GateEvent.
    adjust_plan:
      chinese_name: 请求调整计划
      effect_if_authorized: Commander may authorize a future plan change task or taskbook patch.
    cancel_item:
      chinese_name: 请求取消交付项
      effect_if_authorized: Commander may provide cancellation authority basis for a GateEvent.
    defer_decision:
      chinese_name: 请求延后决策
      effect_if_authorized: No state transition; item remains in current state with explicit unresolved reason.
    continue_next_loop:
      chinese_name: 请求进入下一轮
      effect_if_authorized: Creates or authorizes a future bounded envelope; does not auto-dispatch by itself.

  required_invariants:
    - CommanderDecisionRequest is request only.
    - It must not mutate delivery_state.
    - It must not mutate plan, Taskbook, Git, memory, route, bridge, or remote systems.
    - It must bind to ReviewDecision and EvidencePackage when created from review feedback.
    - It must state whether executors may continue without Commander input.
    - It must separate recommended_option from authorized_action.
    - Missing authority_needed fails closed.
```

### 9.13 Audit Event Minimum Contract

`audit_event_minimum_contract` = 审计事件最小契约.

Plain Chinese meaning: this is the small append-only trace record that ties
actor, authority basis, envelope, receipt, evidence, and redaction posture
together without becoming a large audit platform.

```yaml id="audit-event-minimum-contract"
audit_event_minimum_contract:
  chinese_name: 审计事件最小契约
  required_fields:
    - audit_event_id
    - schema_version
    - event_type
    - actor
    - authority_basis
    - envelope_ref
    - receipt_ref
    - evidence_refs
    - gate_event_refs
    - commander_decision_request_refs
    - workspace_ref
    - created_at
    - redaction_status
    - secrets_checked
    - mutation_allowed
    - integrity_digest

  event_type_values:
    - envelope_created
    - envelope_rejected
    - execution_started
    - receipt_recorded
    - evidence_package_created
    - review_decision_recorded
    - gate_event_recorded
    - commander_decision_requested
    - administrative_correction_recorded
    - supersede_recorded

  required_invariants:
    - AuditEvent is append-only.
    - AuditEvent is trace evidence, not delivery_state authority.
    - mutation_allowed must be false unless a separate authorized envelope or GateEvent allows mutation.
    - secrets_checked must be explicit before external reporting.
    - redaction_status must distinguish redacted, not_needed, and pending_review.
    - integrity_digest binds the audit event identity, not truth or authorization.
    - AuditEvent must not include secrets, credentials, or raw chain-of-thought.
```

---

## 10. Standard Reference Objects

### 10.1 Master Taskbook Reference

```yaml id="master-taskbook-ref"
master_taskbook_ref:
  id: colameta_master_taskbook_v1
  path: PROJECT_MASTER_TASKBOOK.md
  hash: sha256:...
```

Purpose:

```text id="master-taskbook-ref-purpose"
prove the current task is still bound to the same project goal
prevent planner and reviewer drift over time
```

### 10.2 Stage Taskbook Reference

```yaml id="stage-taskbook-ref"
stage_taskbook_ref:
  id: stage_01_master_taskbook_anchoring
  path: docs/taskbooks/stages/STAGE_01_MASTER_TASKBOOK_ANCHORING.md
  hash: sha256:...
```

Purpose:

```text id="stage-taskbook-ref-purpose"
prove the version belongs to a specific stage
prevent version tasks from drifting away from stage goals
```

### 10.3 Review Feedback Record

```yaml id="review-feedback-record"
review_feedback:
  review_id: review_v1_10_001
  version: v1.10
  decision: ACCEPT | NEEDS_FIX | PLAN_ADJUST | ABORT

  bound_inputs:
    master_taskbook_hash: sha256:...
    stage_taskbook_hash: sha256:...
    execution_report_ref: report_...
    workspace_snapshot_ref: ...

  charter_alignment:
    status: aligned | drift_detected | unclear
    evidence:
      - ...

  task_completion:
    status: complete | incomplete | unclear
    evidence:
      - ...

  scope_assessment:
    status: clean | violation | unclear
    evidence:
      - ...

  required_action:
    type: CONTINUE_PREVIEW | FIX_PREVIEW | PLAN_ADJUST_PREVIEW | CANCELLATION_DECISION_REQUEST
    instructions:
      - ...
```

---

## 11. Standard Workflow

### 11.1 Master Taskbook Registration

```text id="master-taskbook-registration-flow"
ChatGPT / Commander drafts PROJECT_MASTER_TASKBOOK.md
        ↓
ColaMeta previews registration
        ↓
required fields are validated
        ↓
master_taskbook_hash is calculated
        ↓
Commander confirms apply
        ↓
future stage and version tasks must reference that hash
```

Registration Readiness Criteria:

```text id="master-taskbook-registration-readiness-criteria"
Master Taskbook can be read.
Hash is stable.
Missing master goal fails validation.
Ordinary version tasks cannot silently modify the Master Taskbook.
Master Taskbook modifications require a hard gate.
```

### 11.2 Stage Taskbook Registration

```text id="stage-taskbook-registration-flow"
ChatGPT creates a Stage Taskbook from the Master Taskbook
        ↓
ColaMeta validates master_taskbook_ref
        ↓
stage_taskbook_hash is calculated
        ↓
Stage Taskbook is registered
        ↓
version tasks under that stage must reference it
```

Registration Readiness Criteria:

```text id="stage-taskbook-registration-readiness-criteria"
Stage Taskbook explains why it serves the master goal.
Stage Taskbook declares out_of_scope.
Stage Taskbook defines gate-readiness criteria.
Missing master_taskbook_ref is rejected.
```

### 11.3 Version Taskbook Execution

```text id="version-taskbook-execution-flow"
ChatGPT creates version execution taskbook
        ↓
ColaMeta validates master_taskbook_ref / stage_taskbook_ref
        ↓
ColaMeta validates allowed_files / forbidden_files / acceptance_commands
        ↓
ColaMeta inserts plan version
        ↓
Codex executes
        ↓
ColaMeta collects diff / validation / scope / audit
        ↓
ColaMeta generates Reviewer Handoff Package
        ↓
Reviewer feedback is required before long-run continuation
```

### 11.4 Review Feedback Intake

```text id="review-feedback-flow"
Reviewer reads handoff package
        ↓
Reviewer checks master taskbook, stage taskbook, version taskbook, and evidence
        ↓
Reviewer emits structured review_feedback
        ↓
ColaMeta previews feedback intake
        ↓
version / execution_report_ref / workspace_snapshot_ref / taskbook_hash are validated
        ↓
apply records classified feedback and prepares the corresponding next-state Commander decision request
```

---

## 12. Review Feedback Decision Policy

Only four review decision values are recognized:

```yaml id="review-feedback-decision-policy"
review_feedback_decision_policy:
  ACCEPT:
    meaning: Reviewer recorded ACCEPT for the requested scope; accepted delivery state still requires Delivery State Gate GateEvent.
    cola_meta_action: >
      record_accept_review; request Delivery State Gate review for submitted -> accepted.
      Only a GateEvent may record the accepted transition.
    must_not: auto_continue_push_release_or_deploy

  NEEDS_FIX:
    meaning: Current version needs a bounded fix.
    cola_meta_action: >
      record_fix_required; request Delivery State Gate review for submitted -> in_delivery
      with returned_for_revision. Only a GateEvent may record the returned-for-revision transition.
    must_not: expand_scope_or_mutate_plan_without_authority

  PLAN_ADJUST:
    meaning: Current plan needs adjustment.
    cola_meta_action: >
      record_plan_adjustment_required and create Commander decision request.
    must_not: mutate_delivery_state_or_apply_plan_change_directly

  ABORT:
    meaning: Current version or stage should stop.
    cola_meta_action: >
      record_cancellation_recommended and create Commander decision request.
    must_not: mutate_delivery_state_to_cancelled_without_explicit_authority
```

Important note:

```text id="review-feedback-safety-note"
ACCEPT is not automatic continue.
ACCEPT records acceptance recommendation and requests Delivery State Gate review; only GateEvent may record the submitted -> accepted transition.
PASS is a legacy alias for ACCEPT only when a migration or compatibility policy explicitly maps it.
continue_next_version remains a controlled action.
```

---

## 13. Long-Term Roadmap

The complete ColaMeta route is divided into ten stages.

```text id="roadmap-scope-note"
This Master Taskbook defines stage goals and taskbook granularity.
It does not define detailed implementation steps.
Detailed implementation is delegated to Stage Taskbooks and Version Execution Taskbooks.
```

---

## 14. Stage 0: Baseline Closeout And Execution-State Clarity

```yaml id="stage-00-summary"
stage_id: stage_00_baseline_closeout
status: active_closeout
current_note: >
  v1.9 has been completed and is present on origin/main.
  v1.10 has been inserted as an execution-state clarity slice for
  executor-session HEAD mismatch. This supersedes earlier drafts that
  expected v1.10 to be Master Taskbook Registry V1.
```

### 14.1 Stage Goal

Converge the ColaMeta self-development chain so executor reports, validation state, runtime status, and workspace status are trustworthy and explainable.

### 14.2 Why It Serves The Master Goal

Goal anchoring is impossible if the system cannot reliably explain what ran, what changed, what passed, what is stale, and whether an executor session represents current work or historical metadata.

### 14.3 Deliverables

```text id="stage-00-deliverables"
validation truth-source hardening
trusted executor report
trusted audit package
read-only runtime version observability
loaded-code verification
executor-session head mismatch classification
explainable local/remote baseline
```

### 14.4 Stage Taskbook

```text id="stage-00-taskbook"
STAGE_00_BASELINE_CLOSEOUT.md
```

### 14.5 Gate-Readiness Criteria

```text id="stage-00-gate-readiness-criteria"
validation failure cannot be summarized as passed
validation_inconsistent can be identified
audit packages expose truth-source evidence
runtime loaded-code freshness is explainable
executor-session HEAD mismatch is classified without mutation
local commit and remote sync state are separately recorded
```

### 14.6 Non-Goals

```text id="stage-00-non-goals"
no new product governance capabilities beyond baseline clarity
no expanded executor authority
no review feedback system
no dashboard
no automatic runtime cleanup
```

---

## 15. Stage 1: Master Taskbook Anchoring

```yaml id="stage-01-summary"
stage_id: stage_01_master_taskbook_anchoring
status: planned_after_stage_00_closeout
current_note: >
  Stage 1 remains the next governance capability stage, but the version
  numbering has shifted. v1.10 is now reserved for executor-session HEAD
  mismatch classification. Master Taskbook Registry V1 is deferred to
  v1.11 or a later explicitly approved version.
```

### 15.1 Stage Goal

Allow ColaMeta to register, freeze, validate, hash, and reference the Project Master Taskbook.

This is the root of ColaMeta's anti-drift capability.

### 15.2 Why It Serves The Master Goal

Without a master goal anchor, stage taskbooks, version taskbooks, and review feedback have no highest reference. Over time, planners and executors can drift away from the original direction.

### 15.3 Deliverables

```text id="stage-01-deliverables"
PROJECT_MASTER_TASKBOOK.md format
master_taskbook schema
master_taskbook validator
master_taskbook hash
master_taskbook registry
master_taskbook change hard-gate policy
```

### 15.4 Stage Taskbook

```text id="stage-01-taskbook"
STAGE_01_MASTER_TASKBOOK_ANCHORING.md
```

### 15.5 Version Directions

```text id="stage-01-version-directions"
v1.10 Executor Session Head Mismatch Classification
v1.11 Master Taskbook Registry V1
v1.12 Master Taskbook Schema + Validator V1
v1.13 Master Taskbook Hash Binding V1
v1.14 Master Taskbook Change Policy V1
```

Version numbering remains subject to future Commander route decisions. The important route correction is that Master Taskbook Registry V1 no longer owns v1.10.

### 15.6 Gate-Readiness Criteria

```text id="stage-01-gate-readiness-criteria"
Project Master Taskbook can be registered.
Project Master Taskbook can be read.
Stable hash can be generated.
Missing core fields fail validation.
Ordinary tasks cannot silently modify the Master Taskbook.
Master Taskbook modifications require Commander hard gate.
```

### 15.7 Non-Goals

```text id="stage-01-non-goals"
no automatic master-plan generator
no ColaMeta-authored project goals
no Web UI requirement
no state-machine rewrite
no automatic review
```

---

## 16. Stage 2: Stage Taskbook Management

```yaml id="stage-02-summary"
stage_id: stage_02_stage_taskbook_management
status: planned
mvp_scope: included
```

### 16.1 Stage Goal

Allow ColaMeta to register Stage Taskbooks and require each Stage Taskbook to bind to the Project Master Taskbook.

### 16.2 Why It Serves The Master Goal

The master goal is too large to feed directly into every execution task. Stage Taskbooks turn it into bounded stage goals while preserving binding to the master.

### 16.3 Deliverables

```text id="stage-02-deliverables"
stage_taskbook schema
stage_taskbook validator
stage_taskbook registry
stage_taskbook hash
stage-to-master binding
stage gate-readiness contract
```

### 16.4 Stage Taskbook

```text id="stage-02-taskbook"
STAGE_02_STAGE_TASKBOOK_MANAGEMENT.md
```

### 16.5 Version Directions

```text id="stage-02-version-directions"
Stage Taskbook Schema + Validator V1
Stage Taskbook Registry V1
Stage-to-Master Binding V1
Stage Taskbook Gate-Readiness Contract V1
```

### 16.6 Gate-Readiness Criteria

```text id="stage-02-gate-readiness-criteria"
Stage Taskbook must reference master_taskbook_ref.
Stage Taskbook must explain supports_project_goal.
Stage Taskbook must declare non_goals / out_of_scope.
Stage Taskbook must define gate-readiness criteria.
Stage Taskbook hash can be referenced by version tasks.
```

### 16.7 Non-Goals

```text id="stage-02-non-goals"
no stage execution
no automatic stage-goal generation
no automatic master-goal adjustment
no dashboard
```

---

## 17. Stage 3: External Taskbook Import Protocol

```yaml id="stage-03-summary"
stage_id: stage_03_external_taskbook_import
status: planned
mvp_scope: included
mvp_implementation_mode: thin_by_default
mvp_limit: minimal canonical import path, not a general ingestion system
```

### 17.1 Stage Goal

Define how version execution taskbooks authored by ChatGPT / Commander enter ColaMeta.

ColaMeta does not generate these taskbooks as an autonomous planning brain, but it must strictly validate them.

### 17.2 Why It Serves The Master Goal

The real workflow is:

```text id="stage-03-real-workflow"
ChatGPT authors a taskbook.
ColaMeta validates, records, and prepares the taskbook for separately authorized freezing or adoption.
Codex executes the bounded task.
Reviewer checks whether the result drifted.
```

Without an import protocol, ColaMeta cannot reliably accept and execute externally planned work.

### 17.3 Deliverables

```text id="stage-03-deliverables"
external_taskbook schema
external_taskbook validator
taskbook import preview
taskbook import apply
taskbook-to-plan mapping
taskbook rejection reasons
```

### 17.4 Stage Taskbook

```text id="stage-03-taskbook"
STAGE_03_EXTERNAL_TASKBOOK_IMPORT.md
```

### 17.5 Version Directions

```text id="stage-03-version-directions"
External Taskbook Schema V1
External Taskbook Validator V1
Taskbook Import Preview V1
Taskbook-to-Plan Version Mapping V1
Taskbook Import Apply V1
```

### 17.6 Gate-Readiness Criteria

```text id="stage-03-gate-readiness-criteria"
Taskbook must contain master_taskbook_ref.
Taskbook must contain stage_taskbook_ref.
Taskbook must contain allowed_files / forbidden_files.
Taskbook must contain acceptance_commands.
Taskbook must contain manual_acceptance.
Taskbook must contain out_of_scope.
Taskbook must explain how it supports stage and master goals.
Invalid format is rejected.
Hash mismatch fails closed.
```

### 17.7 Non-Goals

```text id="stage-03-non-goals"
no automatic goal expansion
no automatic dangerous-scope completion
no automatic allowed_files expansion
no automatic executor dispatch
no automatic commit
```

---

## 18. Stage 4: Bounded Execution And Evidence

```yaml id="stage-04-summary"
stage_id: stage_04_bounded_execution_and_evidence
status: planned
mvp_scope: included
mvp_implementation_mode: thin_governed_loop
mvp_limit: machine-checkable envelope plus evidence or receipt, not a general executor-dispatch platform
```

### 18.1 Stage Goal

Allow ColaMeta to convert registered version taskbooks into bounded,
machine-checkable execution envelopes and record trustworthy local execution
evidence or imported execution receipts.

### 18.2 Why It Serves The Master Goal

Delivery cannot mean only "code changed." It must answer:

```text id="stage-04-core-questions"
Was the taskbook followed?
Was scope respected?
Did validation pass?
Is the work still goal-bound?
Can a reviewer judge it?
```

### 18.3 Deliverables

```text id="stage-04-deliverables"
execution envelope contract
execution envelope rejection rules
executor run preview
bounded local executor run or imported execution receipt
changed files report
execution evidence receipt
validation truth report
scope check report
audit package
taskbook binding in report
```

### 18.4 Stage Taskbook

```text id="stage-04-taskbook"
STAGE_04_BOUNDED_EXECUTION_AND_EVIDENCE.md
```

### 18.5 Version Directions

```text id="stage-04-version-directions"
Machine-checkable Execution Envelope V1
Taskbook-bound Executor Run Preview V1
Taskbook-bound Executor Report V1
Execution Evidence Receipt V1
Validation Truth Integration V1
Scope Evidence Pack V1
Audit Package Taskbook Binding V1
```

### 18.6 Gate-Readiness Criteria

```text id="stage-04-gate-readiness-criteria"
execution envelope must be machine-checkable
invalid envelope must fail closed before dispatch
executor run must bind to a version taskbook
execution report must include master_taskbook_hash
execution report must include stage_taskbook_hash
execution receipt must distinguish executed from validated
validation receipt must distinguish validated / unvalidated / not_run / failed / blocked
validation failure cannot be summarized as passed
scope violation must be explicit
evidence receipt must record allowed scope, observed mutations, validation command, result, and uncertainty
executor cannot automatically commit
executor cannot automatically continue next version
executor cannot automatically promote delivery state
```

### 18.7 Non-Goals

```text id="stage-04-non-goals"
no general executor-dispatch platform
no multi-provider dispatcher requirement
no router integration
no automatic repair
no automatic review
no automatic continue
no automatic commit
no automatic push
```

---

## 19. Stage 5: Reviewer Handoff Package

```yaml id="stage-05-summary"
stage_id: stage_05_reviewer_handoff_package
status: planned
mvp_scope: included
```

### 19.1 Stage Goal

After a version execution completes, ColaMeta must generate a review package for ChatGPT / Codex Commander / Reviewer.

### 19.2 Why It Serves The Master Goal

Reviewers cannot judge only final code. They need goal, taskbook, diff, validation, risk, and drift evidence.

### 19.3 Deliverables

```text id="stage-05-deliverables"
reviewer handoff package schema
reviewer handoff package generator
alignment questions
drift questions
recommended decision options
report excerpt
diff summary
validation truth summary
```

### 19.4 Stage Taskbook

```text id="stage-05-taskbook"
STAGE_05_REVIEWER_HANDOFF_PACKAGE.md
```

### 19.5 Version Directions

```text id="stage-05-version-directions"
Reviewer Handoff Schema V1
Reviewer Handoff Generator V1
Alignment Questions V1
Drift Question Pack V1
Reviewer Package Report Surface V1
```

### 19.6 Gate-Readiness Criteria

```text id="stage-05-gate-readiness-criteria"
handoff package includes master-goal summary
handoff package includes stage-goal summary
handoff package includes version-task summary
handoff package includes changed_files
handoff package includes validation truth
handoff package includes scope evidence
handoff package asks Reviewer to judge drift
handoff package offers limited decision options
```

### 19.7 Non-Goals

```text id="stage-05-non-goals"
no final Reviewer replacement
no automatic aligned claim
no automatic next-version release
no treating handoff package as acceptance pass
```

---

## 20. Stage 6: Review Feedback Intake

```yaml id="stage-06-summary"
stage_id: stage_06_review_feedback_intake
status: planned
mvp_scope: included
mvp_implementation_mode: thin_by_default
mvp_limit: feedback classification and next-state Commander decision request, not plan mutation, state promotion, or execution continuation
```

### 20.1 Stage Goal

Allow Reviewer decisions to return to ColaMeta as structured feedback that is
classified into a next-state Commander decision request.

### 20.2 Why It Serves The Master Goal

If review results remain free-form chat, ColaMeta cannot reliably ask for the
next controlled decision. Feedback must be structured and bound to version,
report, Git HEAD, and taskbook hashes, but it must not become an automatic
state transition or execution command.

### 20.3 Deliverables

```text id="stage-06-deliverables"
review_feedback schema
review_feedback validator
review_feedback preview
review_feedback classification
next_state Commander decision request
review decision mapping
feedback audit record
```

### 20.4 Stage Taskbook

```text id="stage-06-taskbook"
STAGE_06_REVIEW_FEEDBACK_INTAKE.md
```

### 20.5 Version Directions

```text id="stage-06-version-directions"
Review Feedback Schema V1
Review Feedback Validator V1
Review Feedback Preview V1
Review Feedback Classification And Decision Request V1
Review Decision Adapter V1
```

### 20.6 Gate-Readiness Criteria

```text id="stage-06-gate-readiness-criteria"
only ACCEPT / NEEDS_FIX / PLAN_ADJUST / ABORT are recognized review decision values
PASS is a legacy alias for ACCEPT only when explicitly mapped by policy
feedback must bind execution_report_ref
feedback must bind workspace_snapshot_ref
feedback must bind master_taskbook_hash
feedback must bind stage_taskbook_hash
feedback must contain charter_alignment / task_completion / scope_assessment
binding mismatch fails closed
ACCEPT records acceptance recommendation and requests Delivery State Gate review; only GateEvent may record the submitted -> accepted transition
NEEDS_FIX records returned_for_revision recommendation and requests Delivery State Gate review; only GateEvent may record the submitted -> in_delivery transition
PLAN_ADJUST records plan_adjustment_required and creates a Commander decision request; it never mutates the plan by itself
ABORT records cancellation_recommended and creates a Commander decision request; it never cancels, deletes, or reverts by itself
feedback classification never mutates plan, route, delivery state, Git state, or memory by itself
```

### 20.7 Non-Goals

```text id="stage-06-non-goals"
no automatic review conclusion inference
no vague feedback intake
no unbound report feedback
no automatic plan modification
no automatic state transition
no automatic executor continuation
no automatic commit
```

---

## 21. Stage 7: Drift Evidence And Correction

```yaml id="stage-07-summary"
stage_id: stage_07_drift_evidence_and_correction
status: post_mvp_planned
mvp_scope: excluded
```

Stage 7 through Stage 9 details are post-MVP roadmap notes only. They are not
MVP requirements, current implementation authorization, or freeze-candidate
readiness requirements.

### 21.1 Stage Goal

Allow ColaMeta to collect and organize drift evidence so Reviewer can decide whether the project is moving away from the master goal.

ColaMeta must not independently claim complex semantic alignment.

### 21.2 Deliverables

```text id="stage-07-deliverables"
drift evidence pack
executor drift evidence
task drift evidence
stage drift evidence
master goal alignment questions
reviewer drift checklist
plan adjustment trigger conditions
```

### 21.3 Post-MVP Readiness Notes

```text id="stage-07-post-mvp-readiness-notes"
review packages include drift questions
Reviewer must answer whether work still serves the master goal
ColaMeta does not automatically declare semantic alignment
ColaMeta exposes forbidden_files / out_of_scope / validation / diff evidence
PLAN_ADJUST enters plan adjustment flow
```

### 21.4 Non-Goals

```text id="stage-07-non-goals"
no ColaMeta-only semantic drift judgment
no automatic taskbook rewrite
no automatic master-goal change
no automatic stage-scope expansion
```

---

## 22. Stage 8: Plan Adjustment Control Plane

```yaml id="stage-08-summary"
stage_id: stage_08_plan_adjustment_control
status: post_mvp_planned
mvp_scope: excluded
```

### 22.1 Stage Goal

When Reviewer decides the plan needs adjustment, ColaMeta must generate a controlled plan adjustment preview instead of directly modifying the plan.

### 22.2 Deliverables

```text id="stage-08-deliverables"
plan adjustment request schema
plan adjustment preview
stage taskbook adjustment preview
version taskbook adjustment preview
master taskbook hard gate policy
adjustment audit record
```

### 22.3 Post-MVP Readiness Notes

```text id="stage-08-post-mvp-readiness-notes"
PLAN_ADJUST can only generate preview
plan adjustment cannot directly apply
adjustment must explain why it still serves the master goal
master taskbook modifications require Commander hard gate
stage taskbook modifications must reference master hash
version taskbook modifications must reference stage hash
all adjustments are auditable
```

### 22.4 Non-Goals

```text id="stage-08-non-goals"
no automatic master-goal change
no automatic task-scope expansion
no Reviewer bypass
no automatic next-stage entry
```

---

## 23. Stage 9: Controlled Continue And Long-Run Trace

```yaml id="stage-09-summary"
stage_id: stage_09_controlled_continue_and_long_run
status: post_mvp_planned
mvp_scope: excluded
```

### 23.1 Stage Goal

After review produces an eligible decision, allow ColaMeta to proceed to the next version or stage under controlled gates.

### 23.2 Deliverables

```text id="stage-09-deliverables"
controlled continue gate
review-decision-required policy
stage closeout review
next-version readiness report
long-run project trace
```

### 23.3 Post-MVP Readiness Notes

```text id="stage-09-post-mvp-readiness-notes"
without ACCEPT and a separate continue gate, continue_next_version cannot run automatically
before continuing, taskbook hashes must be checked
stage closeout is generated at stage end
long-run trace explains why each step happened
```

### 23.4 Non-Goals

```text id="stage-09-non-goals"
no infinite execution loop
no skipped review
no automatic commit or push
no unauthorized stage entry
```

---

## 24. MVP Boundary

MVP includes Stage 0 through Stage 6 as the Stage 0-6 Thin Governed Loop.
Stage 7 through Stage 9 remain post-MVP.

MVP is the smallest usable governed delivery loop, not the full long-run
automation system.

```text id="mvp-definition"
Master Taskbook registered
        ↓
Stage Taskbook bound to Master
        ↓
Version Taskbook imported
        ↓
Machine-checkable execution envelope authorized
        ↓
Bounded local execution or execution receipt recorded
        ↓
Reviewer Handoff Package generated
        ↓
Review Feedback classified into next-state request
```

MVP success is proven by one complete governed loop:

```text id="mvp-proof-loop"
baseline reality
        ↓
Master Taskbook anchor
        ↓
Stage Taskbook binding
        ↓
Version Execution Taskbook / authorized execution envelope
        ↓
bounded local execution or imported execution receipt
        ↓
validation receipt and execution evidence
        ↓
evidence-backed Reviewer Handoff Package
        ↓
classified next-state Commander decision request
```

Included:

```text id="mvp-included"
Stage 0: Baseline closeout and execution-state clarity
Stage 1: Master Taskbook anchoring
Stage 2: Stage Taskbook management
Stage 3: External taskbook import
Stage 4: Bounded envelope, execution evidence, and receipt
Stage 5: Reviewer Handoff Package
Stage 6: Review feedback classification and next-state decision request
```

MVP interpretation:

```yaml id="mvp-interpretation"
mvp_boundary:
  mvp_name: Stage 0-6 Thin Governed Loop
  included_stages: stage_00_to_stage_06
  post_mvp_stages: stage_07_to_stage_09
  implementation_mode: minimal_governance_primitives_not_full_automation_layers
  stage_03_scope: thin_canonical_import_not_general_ingestion
  stage_04_scope: bounded_envelope_execution_evidence_and_receipt_not_general_dispatch_platform
  stage_06_scope: feedback_classification_and_next_state_decision_request_not_plan_state_or_execution_mutation
  freeze_candidate_requires:
    - machine_checkable_execution_envelope_contract
    - validation_receipt_semantics
    - finite_delivery_state_gate
    - gate_event_minimum_contract
    - commander_decision_request_minimum_contract
    - audit_event_minimum_contract
    - minimal_delivery_state_transition_model
    - state_authority_contract
    - review_decision_mapping
    - taskbook_layer_responsibility_contract
    - stage_0_6_readiness_contract
    - reviewer_handoff_minimum_template
    - codex_router_mvp_exclusion
    - discussion_draft_authority_boundary
  route_integrity_blockers_required_in_mvp:
    - drift_verdict_or_drift_note
    - continue_gate_receipt
    - feedback_authority_classifier
    - parent_staleness_blocker
    - scope_expansion_blocker
    - evidence_sufficiency_verdict
  stage_07_to_09_hook_scope: evidence_and_request_fields_only
```

### 24.1 Stage 0-6 Thin Governed Loop Readiness Contract

`Stage 0-6 Thin Governed Loop Readiness Contract` = 阶段 0-6 薄治理闭环就绪契约.

Plain Chinese meaning: this section says the minimum each MVP stage must prove
before the loop can be reviewed. It is a static contract, not a live progress
tracker, dashboard, approval queue, runtime state table, or executor dispatch
plan.

```text id="stage-0-6-readiness-contract-core"
Stage 0-6 MVP is one thin governed proof loop, not seven independent product layers.
A stage is MVP-ready when it can produce or consume the minimum claim, evidence,
and decision needed for the next stage to proceed without ambiguity.
```

Allowed Master-level fields:

```text id="stage-0-6-readiness-contract-fields"
Stage
Minimum readiness claim
Required evidence
Gate question
Explicit non-goal
```

Excluded Master-level tracker fields:

```text id="stage-0-6-readiness-contract-excluded-fields"
dynamic status
owner
due date
priority
risk score
dependency graph
executor dispatch plan
workflow history
```

| Stage | Minimum Readiness Claim | Required Evidence | Gate Question | Explicit Non-Goal |
| --- | --- | --- | --- | --- |
| Stage 0: Baseline Closeout And Execution-State Clarity | Baseline state is known enough to start governed claims. | Baseline snapshot, known unknowns, local/runtime state note. | Do later claims start from a declared baseline? | Not full audit, cleanup, or dashboard. |
| Stage 1: Master Taskbook Anchoring | Work is anchored to `project_final_goal`. | Master Taskbook goal, MVP scope, authority rules, stage list. | Does every downstream claim trace to the single final goal? | Not multi-goal portfolio planning. |
| Stage 2: Stage Taskbook Management | Stage Taskbooks express bounded stage claims. | Stage objective, bounds, evidence expectation, gate-readiness criteria. | Are stage claims distinct from accepted state? | Not state authority or workflow platform. |
| Stage 3: External Taskbook Import Protocol | External taskbooks enter only as claims. | Source, provenance, import receipt, normalized claims, conflicts. | Can imported claims be reviewed without becoming facts? | Not trusted state import or general ingestion. |
| Stage 4: Bounded Execution And Evidence | Execution is bounded and evidence-backed. | Execution envelope, runtime actions, touched artifacts, validation receipt, risks. | Can acceptance be judged from evidence, not taskbook claims? | Not general executor dispatch platform. |
| Stage 5: Reviewer Handoff Package | Reviewer handoff is self-contained. | Claim-to-evidence package, validation status, risks, known gaps. | Can a reviewer decide without reconstructing context? | Not acceptance itself. |
| Stage 6: Review Feedback Intake | Feedback becomes a Commander next-state request. | Feedback receipt, classification, requested next-state decision. | Can Commander authorize stop, rework, defer, accept, or next loop? | Not plan mutation, state promotion, or execution continuation. |

Universal stop predicates:

```yaml id="stage-0-6-universal-stop-predicates"
stage_0_6_universal_stop_predicates:
  missing_authority:
    chinese_name: 缺少权威来源
    meaning: Required Commander, Gate, Runtime, ReviewDecision, or imported receipt authority is absent.
  boundary_conflict:
    chinese_name: 越过授权边界
    meaning: Requested action exceeds the authorized Stage, Version, file, mutation, route, or bridge boundary.
  state_conflict:
    chinese_name: 任务书声明和 Runtime 事实冲突
    meaning: Taskbook claim conflicts with observed Runtime facts or workspace reality.
  acceptance_unknown:
    chinese_name: 证据不足以让 Gate 判断
    meaning: Evidence is insufficient for Delivery State Gate or Commander to decide accept, rework, defer, stop, or next loop.
```

Stage 7 through Stage 9 hooks in MVP are route-integrity blockers and evidence
fields only. They do not authorize drift correction, plan mutation, route
transition, execution continuation, scope expansion, P0 closure, or remote
action.

Excluded:

```text id="mvp-excluded"
full long-run health report
dashboard
automatic drift scoring
automatic plan-adjust apply
automatic continue loop
Web UI as a required MVP feature
remote release system
codex-router bridge implementation, adapter work, schema work, runtime integration, shared state, executor dispatch, or remote action
Goal Boundary Contract implementation, schema work, adapter work, state-machine changes, runtime integration, or executor dispatch
general executor-dispatch platform
automatic delivery-state promotion
review feedback applying plan or route changes by itself
```

### 24.2 Thin Loop Freeze Readiness

The MVP boundary is not freeze-ready until the thin loop can be reviewed as a
bounded proof mechanism. The following conditions are required before any
freeze-candidate request:

```text id="thin-loop-freeze-readiness"
Stage 0-6 must be described as one governed proof loop, not seven product layers.
Stage 4 must be limited to machine-checkable envelope plus execution evidence or receipt.
Stage 6 must be limited to feedback classification plus next-state Commander decision request.
Execution envelope must reject invalid parent hashes, paths, actions, stop conditions, and evidence requirements before dispatch.
Receipt semantics must distinguish validated, unvalidated, not_run, failed, and blocked.
Delivery state gate must define finite states, allowed transitions, evidence per transition, and forbidden auto-promotions.
GateEvent must be defined as the only append-only event that can write delivery_state or item-level blocked projection.
CommanderDecisionRequest must be defined as request-only and unable to mutate plan, state, Git, memory, route, bridge, or remote systems.
AuditEvent must be defined as append-only trace evidence, not delivery_state authority.
Reviewer handoff package must have a minimum template sufficient for accept / needs_fix / plan_adjust / abort decisions.
codex-router must remain future_bridge_candidate only and outside the MVP execution path.
discussion_draft, observed hashes, and review packets must not be treated as freeze, canonicalization, commit, push, memory-write, bridge, or remote authority.
```

---

## 25. Hard Gates

These actions require Commander hard gate:

```text id="hard-gates"
modify Project Master Taskbook canonical fields
change ColaMeta product positioning
allow ColaMeta to auto-generate master plans
allow ColaMeta to auto-review
allow ColaMeta to auto-commit
allow ColaMeta to perform git push / release / deploy
expand executor authority
change preview/apply safety model
modify core state machine
add remote mutation surface
modify Master Taskbook canonical hash policy
activate codex-router bridge work
promote Goal Boundary Contract to runtime architecture
import AGENTS OS resident-Agent rights into ColaMeta executors
change Semantics-to-Mechanics canonical rows
change Forbidden Claims / Boundary Law
```

---

## 26. Near-Term Priorities

### Priority 0: Protect Current Baseline Reality

```text id="priority-0"
Goal: Keep the current v1.9 remote baseline and v1.10 local plan baseline clearly recorded.
```

Readiness Criteria:

```text id="priority-0-readiness-criteria"
v1.9 is known to exist on origin/main
v1.10 plan/prompt baseline is known as local ahead-of-origin work
current worktree state is explainable before any new executor run or commit
no stale draft claims that v1.10 is Master Taskbook Registry
```

### Priority 1: Preserve Completed v1.10 Executor Session Head Mismatch Classification

```text id="priority-1"
Goal: Keep the completed local v1.10 executor-session HEAD mismatch
classification baseline recorded as local ahead-of-origin work, without
treating it as remote-synced or authorizing any executor run, commit, push, or
route transition.
```

This priority is an execution-state safety correction completed locally at
implementation commit 640a843. It prevents route confusion before deeper
governance features are added, but it does not authorize remote sync or a new
execution route.

### Priority 2: Review And Iterate This Master Taskbook Draft

```text id="priority-2"
Goal: Continue discussion on this PROJECT_MASTER_TASKBOOK.md draft until it is
ready for active_candidate or freeze_candidate status.
```

This draft is intentionally stored before finalization so future planning rounds can edit the same project artifact.

### Priority 3: Enter Master Taskbook Registry V1

```text id="priority-3"
Goal: Add controlled registration and read support for the Master Taskbook.
```

Previous drafts labeled this as v1.10. The corrected route defers it to v1.11 or later.

### Priority 4: Establish Stage Taskbook Binding

```text id="priority-4"
Goal: Require Stage Taskbooks to bind to the Project Master Taskbook.
```

### Priority 5: Establish External Taskbook Import

```text id="priority-5"
Goal: Allow ChatGPT-authored version taskbooks to enter ColaMeta through validation.
```

### Priority 6: Establish Review Handoff And Feedback Intake

```text id="priority-6"
Goal: Generate review packages and ingest structured review feedback.
```

---

## 27. How To Use This Draft

Allowed usage:

```text id="allowed-usage"
planning discussion baseline
route review reference
stage taskbook drafting input
version taskbook alignment context
reviewer orientation
future canonicalization candidate
```

Forbidden usage:

```text id="forbidden-usage"
do not treat as active canonical hash anchor yet
do not hand to Codex for one-shot implementation
do not use as a substitute for Stage Taskbooks
do not use as a substitute for Version Execution Taskbooks
do not use as a substitute for Review Feedback
do not use as automatic authorization for push / release / deploy
```

---

## 28. Next Step

The next step is not to restart the whole route. The route is:

```text id="next-step"
1. Keep the local v1.10 plan and implementation baseline separate from this Master Taskbook draft.
2. Reconcile v1.10 local status before any later executor run, commit, push, or route transition.
3. Continue discussing this PROJECT_MASTER_TASKBOOK.md draft.
4. Only after separate hash-specific Commander authorization and all activation requirements are satisfied, consider moving this file from discussion_draft to active_candidate or freeze_candidate.
5. Only then generate the Stage 1 taskbook and the Master Taskbook Registry V1 version taskbook.
```

Remote push remains a separate remote mutation and is not authorized by this document.
