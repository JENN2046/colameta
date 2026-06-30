# Stage 8 中文任务书：计划调整控制面

```yaml id="stage-08-zh-cn-summary"
chinese_companion:
  source_document: docs/taskbooks/stages/STAGE_08_PLAN_ADJUSTMENT_CONTROL.md
  source_sha256: 60421ba765b238b9671f1f9baf878cf716c6e6e5cd05524bfa746610fd9a3755
  translation_status: companion_draft
  authority_status: planning_reference_only
stage:
  stage_id: stage_08_plan_adjustment_control
  chinese_name: 计划调整控制面
  status: discussion_draft
```

## 1. 阶段定位

Stage 8 在 Reviewer 判断需要 `PLAN_ADJUST` 时，生成可审查的 adjustment preview，
而不是直接改 plan。

它保留 requested adjustment、previewed adjustment、Commander authorization、
actual mutation 之间的边界。

英文源文件里的 `created_from_head=8367a7d` 是本次 Stage 7-9 准备基线。

## 2. 当前现实

Stage 6 已经能把 `PLAN_ADJUST` 分类成 Commander decision request。Stage 8 是
缺失的 controlled surface：把请求变成有边界的 preview。

当前 repo 与稳定服务都在 `8367a7d39cef0c70237625c4e50f0d6127cde3a6`，稳定服务
Web/MCP 健康，`v1.11` 已 `PASSED`。

## 3. 进入条件

进入 Stage 8 需要：

- ReviewDecision 或 CommanderDecisionRequest 指向 `PLAN_ADJUST`；
- drift evidence pack 或 review feedback 已绑定；
- master taskbook hash 已知；
- affected stage/version taskbook refs 已知；
- requested adjustment 说明为什么仍服务 master goal。

不需要 automatic apply authority、next-stage entry 或 executor continuation。

## 4. 退出条件

Stage 8 完成时需要：

- plan adjustment request schema 存在；
- plan adjustment preview 可生成；
- stage taskbook adjustment preview 可生成；
- version taskbook adjustment preview 可生成；
- master taskbook hard gate policy 明确；
- adjustment audit record 可生成；
- preview 解释为什么仍服务 master goal；
- 没有 Commander hard gate 时 apply fail closed。

## 5. 最小证据包

最小证据包需要：

- `adjustment_request_id`；
- request source；
- review decision ref；
- drift evidence ref；
- master taskbook ref；
- affected stage/version taskbook refs；
- proposed change summary；
- proposed diff or patch preview；
- continued master goal service explanation；
- forbidden side effects；
- audit record ref。

不能把 automatic apply、Reviewer bypass、未过 hard gate 的 master goal change、next
stage entry 当成权威。

## 6. 首个实现方向

建议先做 `Plan Adjustment Request Schema V1`，实现 schema 和 preview-only 路径。

apply route 在 preview 行为被证明、Commander hard gate wording 被确认前保持
out of scope。

## 7. 非目标

Stage 8 不自动修改 master goal、不自动扩大 task scope、不绕过 Reviewer、不自动
进入下一阶段、不继续 executor、不 commit、不 push。
