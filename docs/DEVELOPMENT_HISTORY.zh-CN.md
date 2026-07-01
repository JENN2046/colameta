# ColaMeta 开发历程总览

```yaml
document_type: development_history_overview
language: zh-CN
status: living_overview
recorded_at: 2026-07-01
project: colameta-self-dev
dev_repo: /home/jenn/src/colameta-dev
stable_runtime_dir: /home/jenn/tools/colameta
authority_status: evidence_index_only
```

这份文档是 ColaMeta 开发过程的中文总览。它把分散在 taskbook、evidence report、
stable replacement receipt、connector closeout receipt、`.colameta` 运行痕迹和 Git
历史里的事实串成一条可阅读的路线。

它不是新的授权，不创建 `ReviewDecision`，不发出 `GateEvent`，不写
`Delivery State accepted`，不替代任何具体 receipt，也不授权 executor run、push、
stable replacement、deploy、release 或 package publish。

## 当前一眼看懂

```yaml
current_baseline:
  observed_at: 2026-07-01T23:51:00+08:00
  observation_scope: development_history_snapshot
  validated_by:
    - git rev-parse HEAD origin/main
    - git -C /home/jenn/tools/colameta rev-parse HEAD
    - stable MCP get_runtime_version_status
    - stable MCP get_connector_runtime_health_status
  dev_head: a3a1bbca2394b71fef1f8255c186b02a3d32eab3
  origin_main: a3a1bbca2394b71fef1f8255c186b02a3d32eab3
  stable_head: a3a1bbca2394b71fef1f8255c186b02a3d32eab3
  stable_web: http://127.0.0.1:8801
  stable_mcp: http://127.0.0.1:8766/mcp
  stable_service_status: healthy
  runtime_provenance: installed_package_matches_project_checkout
  executor_profile: codex + gpt-5.5 + xhigh
  external_connector_status: unverified
  operator_closeout: local_runtime_ready_external_connector_unverified
```

大白话：ColaMeta 现在已经不是一堆文档草案。它有稳定 Web/MCP 服务，有受控
preview/apply 思路，有 taskbook 证据链，有稳定服务替换记录，也已经能作为本地 agent
和 Web GPT 的指挥入口使用。剩余最明显的运营缺口是 external connector/tunnel 的真实
可用性仍需要持续用 approved sanitized evidence 收口。

## 怎么读这条证据链

推荐阅读顺序：

1. 先读本文件，理解路线。
2. 再读 [docs/USAGE.zh-CN.md](USAGE.zh-CN.md)，知道怎么使用稳定服务。
3. 要看 Stage 0-6 的收口事实，读
   [docs/taskbooks/STAGE_0_6_IMPLEMENTATION_CLOSEOUT_READINESS_PACKET.zh-CN.md](taskbooks/STAGE_0_6_IMPLEMENTATION_CLOSEOUT_READINESS_PACKET.zh-CN.md)。
4. 要看每个阶段的任务边界，读 [docs/taskbooks/stages](taskbooks/stages)。
5. 要看每个版本的实现证据，读 [docs/taskbooks/versions](taskbooks/versions)。
6. 要看稳定服务替换证据，读
   [docs/stable-replacement-receipts](stable-replacement-receipts)。
7. 要看 connector/tunnel closeout，读
   [docs/connector-tunnel-closeout-receipts](connector-tunnel-closeout-receipts)。

## 早期目标：让 ColaMeta 先能讲清现实

最开始的工作不是直接让 agent 自动跑很远，而是先解决一个更基础的问题：项目现实要能被
看清楚。

Stage 0 做的是 baseline closeout：把 repo、runtime、validation、local/remote 状态等
现实事实收束出来，避免在不清楚当前状态时继续叠加治理话术。

对应入口：

- [docs/taskbooks/stages/STAGE_00_BASELINE_CLOSEOUT.md](taskbooks/stages/STAGE_00_BASELINE_CLOSEOUT.md)
- [docs/taskbooks/versions/stage-00](taskbooks/versions/stage-00)

## Stage 1-6：薄治理闭环成型

Stage 1-6 是 ColaMeta 的第一条核心能力链。它的目标不是“自动做一切”，而是让每次执行都
能被任务书绑定、被证据约束、被 reviewer 接住、被反馈重新路由。

### Stage 1：Master Taskbook Anchoring

Stage 1 让 Master Taskbook 变成可引用、可校验、受保护的上游锚点。实现内容包括
registry、reader、validator、hash binding 和 mutation hard gate。

证据入口：

- [docs/taskbooks/stages/STAGE_01_MASTER_TASKBOOK_ANCHORING.md](taskbooks/stages/STAGE_01_MASTER_TASKBOOK_ANCHORING.md)
- [docs/taskbooks/versions/stage-01](taskbooks/versions/stage-01)

### Stage 2：Stage Taskbook Management

Stage 2 把总目标拆成阶段任务书，并建立 stage schema、registry、Stage-to-Master binding
和 gate-readiness helper。

证据入口：

- [docs/taskbooks/stages/STAGE_02_STAGE_TASKBOOK_MANAGEMENT.md](taskbooks/stages/STAGE_02_STAGE_TASKBOOK_MANAGEMENT.md)
- [docs/taskbooks/versions/stage-02](taskbooks/versions/stage-02)

### Stage 3：External Taskbook Import

Stage 3 解决外部任务书导入问题：外部输入先被当成 claim，而不是自动当成事实。它提供
schema、validator、import preview、version candidate mapping 和 adoption preview。

证据入口：

- [docs/taskbooks/stages/STAGE_03_EXTERNAL_TASKBOOK_IMPORT.md](taskbooks/stages/STAGE_03_EXTERNAL_TASKBOOK_IMPORT.md)
- [docs/taskbooks/versions/stage-03](taskbooks/versions/stage-03)

### Stage 4：Bounded Execution And Evidence

Stage 4 是“可控执行”的核心。它把执行 envelope、executor preview、local/imported
execution receipt、validation truth、scope evidence 和 audit package binding 串起来。

大白话：执行不是一句“跑了”。它要说清楚按什么任务跑、允许碰哪里、实际碰了哪里、怎么验
证、哪些证据能给 reviewer 看。

证据入口：

- [docs/taskbooks/stages/STAGE_04_BOUNDED_EXECUTION_AND_EVIDENCE.md](taskbooks/stages/STAGE_04_BOUNDED_EXECUTION_AND_EVIDENCE.md)
- [docs/taskbooks/versions/stage-04](taskbooks/versions/stage-04)

### Stage 5：Reviewer Handoff Package

Stage 5 让 reviewer 能接住执行结果。它提供 handoff schema、handoff generator、alignment
questions、drift questions 和 report surface。

证据入口：

- [docs/taskbooks/stages/STAGE_05_REVIEWER_HANDOFF_PACKAGE.md](taskbooks/stages/STAGE_05_REVIEWER_HANDOFF_PACKAGE.md)
- [docs/taskbooks/versions/stage-05](taskbooks/versions/stage-05)

### Stage 6：Review Feedback Intake

Stage 6 把 review feedback 转成下一步请求，而不是让反馈直接变成状态跃迁。它实现 feedback
schema、validator、preview、classification、CommanderDecisionRequest 和
ReviewDecision adapter boundary。

证据入口：

- [docs/taskbooks/stages/STAGE_06_REVIEW_FEEDBACK_INTAKE.md](taskbooks/stages/STAGE_06_REVIEW_FEEDBACK_INTAKE.md)
- [docs/taskbooks/versions/stage-06](taskbooks/versions/stage-06)

### Stage 0-6 收口状态

Stage 0-6 已有完整 closeout readiness packet：

- [docs/taskbooks/STAGE_0_6_IMPLEMENTATION_CLOSEOUT_READINESS_PACKET.zh-CN.md](taskbooks/STAGE_0_6_IMPLEMENTATION_CLOSEOUT_READINESS_PACKET.zh-CN.md)

这份 packet 记录了 Stage 1-6 的实现产物 manifest、测试结果、边界和 push 决策前提。它是
Stage 0-6 最重要的总证据包。

## Stage 7-9：从“闭环可跑”走向“长期项目可控”

Stage 7-9 起初是 post-MVP preparation draft，后来已经推进了部分实现 slice。

### Stage 7：Drift Evidence And Correction

Stage 7 的问题是：项目跑着跑着，怎么知道有没有偏离 master goal？

已推进内容：

- `885eee6 feat(stage7): add drift evidence schema`
- `ac64f07 feat(stage7): build drift evidence packs`

大白话：ColaMeta 可以组织 drift evidence，生成 reviewer 问题和检查项，但不能自己宣称
“没有漂移”或“语义对齐通过”。

### Stage 8：Plan Adjustment Control

Stage 8 的问题是：如果 reviewer 认为计划要调整，怎么避免 agent 直接改 plan？

已推进内容：

- `9448b4e feat(stage8): add plan adjustment preview`
- `44ba425 fix(stage8-stage9): fail closed gated previews`
- `c923618 fix(stage8-stage9): tighten acceptance blockers`

大白话：PLAN_ADJUST 只能先生成 preview。真正改 plan、taskbook 或 master goal 仍需要明确
Commander gate。

### Stage 9：Controlled Continue And Long-Run Trace

Stage 9 的问题是：一个长期项目怎么继续下一步，而不是无限自动跑？

已推进内容：

- `3d53588 feat(stage9): add continue readiness report`
- `8ee3b34 feat(workflow): add final version closeout control`

大白话：ColaMeta 可以说明“现在能不能继续、为什么不能继续、缺什么 gate 或 evidence”，
但不会因为 runner completed 或 tests passed 就自动等同于 review accepted。

Stage 7-9 的计划入口：

- [docs/taskbooks/stages/STAGE_07_DRIFT_EVIDENCE_AND_CORRECTION.md](taskbooks/stages/STAGE_07_DRIFT_EVIDENCE_AND_CORRECTION.md)
- [docs/taskbooks/stages/STAGE_08_PLAN_ADJUSTMENT_CONTROL.md](taskbooks/stages/STAGE_08_PLAN_ADJUSTMENT_CONTROL.md)
- [docs/taskbooks/stages/STAGE_09_CONTROLLED_CONTINUE_AND_LONG_RUN_TRACE.md](taskbooks/stages/STAGE_09_CONTROLLED_CONTINUE_AND_LONG_RUN_TRACE.md)

## v1.11-v1.17：从实现闭环走向可运营服务

Stage 能力成型之后，开发重点转向“ColaMeta 作为日常指挥入口是否好用”。

### v1.11：connector/runtime health observability

目标：把本地 Web/MCP 服务健康、运行时代码新鲜度、外部 connector/tunnel 可用性拆开看。

代表提交：

- `fa9c388 feat(runtime): add connector health observability`
- `ef017a2 fix(cli): discover running serve status without metadata`
- `8b92e98 feat(runtime): verify installed package provenance`

结果：`colameta status`、runtime version status 和 connector health surfaces 开始能说明
PID/port、runtime provenance、local service 和 external connector 的差异。

### v1.12-v1.15：Stage 7-9 最小实现

目标：让 drift evidence、plan adjustment preview、continue readiness 这些 post-MVP 能力先
以 fail-closed / read-only / preview-only 的方式落地。

代表提交：

- `885eee6 feat(stage7): add drift evidence schema`
- `ac64f07 feat(stage7): build drift evidence packs`
- `9448b4e feat(stage8): add plan adjustment preview`
- `3d53588 feat(stage9): add continue readiness report`

结果：Stage 7-9 不再只是 roadmap 文字，已经有部分 runtime/helper 能力，但 apply、continue
和 delivery accepted 仍保持受控边界。

### v1.16：Connector Runtime Health MCP Closeout Tool

目标：提供 `get_connector_runtime_health_status`，用只读 MCP 工具把 local runtime health 和
external connector/tunnel evidence 分开。

代表提交：

- `380a9e3 feat(runtime): add connector closeout guidance`
- `27e7625 feat(connector): add tunnel health closeout loop`
- `5403363 fix(connector): probe web api healthz`

结果：有 sanitized evidence 时可以得到 `connector_closeout_ready`；证据缺失时保持 blocked 或
unverified，不从缺失信息推断成功。

### v1.17：Connector Tunnel Evidence Receipt And Closeout Packet

目标：把 connector/tunnel 真实可用性的证据写成可审查 receipt，不读 token、cookie、
provider raw response、proxy config 或 tunnel-client config。

代表证据：

- [docs/connector-tunnel-closeout-receipts/connector-tunnel-closeout-27e7625-20260701.md](connector-tunnel-closeout-receipts/connector-tunnel-closeout-27e7625-20260701.md)
- [docs/connector-tunnel-closeout-receipts/connector-tunnel-closeout-5403363-20260701.md](connector-tunnel-closeout-receipts/connector-tunnel-closeout-5403363-20260701.md)
- [docs/connector-tunnel-closeout-receipts/connector-tunnel-closeout-prealignment-20260701.md](connector-tunnel-closeout-receipts/connector-tunnel-closeout-prealignment-20260701.md)

结果：connector closeout 的证据格式已经存在；当前 stable 服务仍把 external connector 标为
`unverified`，因为最新运行面没有持续提供完整 approved tunnel-client/control-plane evidence。

## 稳定服务路线

ColaMeta 有两个重要位置：

```yaml
service_layout:
  dev_repo: /home/jenn/src/colameta-dev
  stable_runtime_dir: /home/jenn/tools/colameta
  stable_cli: /home/jenn/tools/colameta/.venv/bin/colameta
  stable_web: http://127.0.0.1:8801
  stable_mcp: http://127.0.0.1:8766/mcp
```

稳定服务替换不是普通文档编辑。每次替换都应该有：

- exact commit authorization；
- CI success；
- stable backup；
- package reinstall；
- service restart evidence；
- Web/MCP smoke；
- runtime provenance；
- residual caveat。

已有 stable replacement receipt：

- [stable-replacement-80d849b-20260701.md](stable-replacement-receipts/stable-replacement-80d849b-20260701.md)
- [stable-replacement-04c0f91-20260701.md](stable-replacement-receipts/stable-replacement-04c0f91-20260701.md)
- [stable-replacement-5403363-20260701.md](stable-replacement-receipts/stable-replacement-5403363-20260701.md)
- [stable-replacement-814568f-20260701.md](stable-replacement-receipts/stable-replacement-814568f-20260701.md)
- [stable-replacement-7d45c30-20260701.md](stable-replacement-receipts/stable-replacement-7d45c30-20260701.md)

当前 stable 已替换到 `a3a1bbca2394b71fef1f8255c186b02a3d32eab3`，并通过 Web/MCP smoke。
这份开发历程文档记录该事实，但不替代专门的
`stable-replacement-a3a1bbc-20260701.md` receipt。

## 使用手感与交付化推进

近期文档和 UX 优化的主线是：让 ColaMeta 不只“能被开发者调通”，也能被 Web GPT、本地
Codex、planner、reviewer 和新手使用。

代表提交：

- `6afaab7 docs(usage): add Chinese operator manual`
- `41f5f19 docs(usage): add operator quick paths`
- `d25a124 docs(usage): clarify stable service version drift`
- `3e0f38b docs(onboarding): add project onboarding and closeout preflight`
- `814568f docs(connector): generalize prealignment closeout evidence`

对应文档：

- [docs/USAGE.zh-CN.md](USAGE.zh-CN.md)
- [docs/ONBOARDING.zh-CN.md](ONBOARDING.zh-CN.md)
- [docs/agent-consumer-contract.zh-CN.md](agent-consumer-contract.zh-CN.md)
- [docs/web-gpt-service-entrypoint.zh-CN.md](web-gpt-service-entrypoint.zh-CN.md)

## Executor 模型控制

ColaMeta 的 executor 配置已经推进到显式模型和 reasoning effort：

```yaml
executor_profile:
  provider: codex
  model: gpt-5.5
  reasoning_effort: xhigh
```

代表提交：

- `7d45c30 feat(executor): pass Codex reasoning effort`

替换到 `7d45c30` 后，stable package command path 已验证会构造包含
`--model gpt-5.5` 和 `model_reasoning_effort="xhigh"` 的 Codex CLI command。该验证不复制
provider raw response。

## 留痕在哪里

当前主要留痕位置：

```yaml
evidence_locations:
  stage_taskbooks: docs/taskbooks/stages
  version_taskbooks: docs/taskbooks/versions
  stage_0_6_closeout: docs/taskbooks/STAGE_0_6_IMPLEMENTATION_CLOSEOUT_READINESS_PACKET.zh-CN.md
  stable_replacement_receipts: docs/stable-replacement-receipts
  connector_closeout_receipts: docs/connector-tunnel-closeout-receipts
  colameta_plan: .colameta/plan.zh-CN.md
  colameta_audits: .colameta/audits
  colameta_reports: .colameta/reports
  colameta_runtime: .colameta/runtime
  github_ci: .github/workflows
  git_history: git log
```

这些留痕的角色不同：

- taskbook 说明“应该做什么”和“边界是什么”；
- evidence report 说明“某个 slice 做成了什么、怎么验证”；
- stable replacement receipt 说明“稳定服务何时替换到哪个 commit”；
- connector closeout receipt 说明“connector/tunnel 真实可用性证据是否足够”；
- `.colameta/runtime` 和 `.colameta/audits` 保存运行过程中的 preview、audit、report；
- Git 和 CI 提供提交和自动验证事实。

## 当前剩余缺口

```yaml
known_gaps:
  latest_stable_replacement_receipt:
    status: pending
    target_commit: a3a1bbca2394b71fef1f8255c186b02a3d32eab3
  external_connector_tunnel:
    status: unverified_in_current_stable_health_surface
    required_for_closeout:
      - approved sanitized tunnel_client evidence
      - approved sanitized control_plane evidence
  stage_7_9:
    status: partially_implemented
    remaining_focus:
      - fuller reviewer-facing drift evidence workflow
      - controlled plan adjustment apply boundary
      - long-run trace reader and stage closeout review polish
  productization:
    status: ongoing
    remaining_focus:
      - clearer first-use paths
      - fewer ambiguous health/status terms
      - consistent receipt generation after stable replacement
```

## 结论

ColaMeta 的开发历程已经有证据链：不是口头推进，也不是只靠聊天记录。它现在的状态可以概括为：

- Stage 0-6 薄治理闭环已经实现并有收口证据；
- Stage 7-9 已经从规划进入部分实现，但仍保持 preview/read-only/fail-closed 边界；
- 稳定服务已经能作为本地 Web/MCP 指挥入口使用；
- executor 模型路径已经显式到 `codex + gpt-5.5 + xhigh`；
- connector/tunnel 的证据模型已经建立，但当前外部可用性仍需要持续 closeout；
- 下一步产品化重点是让每次稳定替换、connector closeout 和新项目 onboarding 都更自动、更可读、更一致。
