# Stage 9 中文任务书：受控继续与长期追踪

```yaml id="stage-09-zh-cn-summary"
chinese_companion:
  source_document: docs/taskbooks/stages/STAGE_09_CONTROLLED_CONTINUE_AND_LONG_RUN_TRACE.md
  source_sha256: 5bfe6e4632748bd33f5a763963bc54b5e546bd3349ad536ec5b693522c7d696d
  translation_status: companion_draft
  authority_status: planning_reference_only
stage:
  stage_id: stage_09_controlled_continue_and_long_run
  chinese_name: 受控继续与长期追踪
  status: discussion_draft
```

## 1. 阶段定位

Stage 9 负责在 review 给出 eligible decision 后，通过单独 continue gate 进入下一
个 version 或 stage，并留下长期项目轨迹。

它不授权无限循环、不跳过 review、不自动 commit/push、不做 production deploy。

英文源文件里的 `created_from_head=8367a7d` 是本次 Stage 7-9 准备基线。

## 2. 当前现实

ColaMeta 已经能完成有边界闭环，也能记录 final-version closeout。Stage 9 是缺失的
long-run continuation layer。

当前 repo 与稳定服务都在 `8367a7d39cef0c70237625c4e50f0d6127cde3a6`，Runner
状态为 `COMPLETED`，当前版本 `v1.11 PASSED`，没有 pending versions。

## 3. 进入条件

进入 Stage 9 需要：

- eligible ReviewDecision 或 CommanderDecisionRequest；
- 单独 continue gate；
- master taskbook hash；
- stage taskbook hash；
- version taskbook hash 或 next-version preview；
- 没有 blocking review comments。

不需要 automatic executor run、automatic commit、automatic push 或 production
deployment。

## 4. 退出条件

Stage 9 完成时需要：

- controlled continue gate 存在；
- review-decision-required policy 存在；
- next-version readiness report 可生成；
- stage closeout review 可生成；
- long-run trace 记录每一步为什么发生；
- 没有 ACCEPT 和单独 gate 时 continue fail closed；
- continuation 前检查 taskbook hashes。

## 5. 最小证据包

最小证据包需要：

- `continue_gate_id`；
- review decision ref；
- commander authorization ref；
- master taskbook hash；
- stage taskbook hash；
- version taskbook hash 或 preview ref；
- current state summary；
- next-version readiness report；
- forbidden side effects；
- long-run trace entry。

不能把 skipped review、automatic executor loop、automatic commit、automatic push、
production deploy 当成权威。

## 6. 首个实现方向

建议先做 `Review Decision Required Policy V1`，然后再做 controlled continue gate。

第一段实现应保持 policy 和 readiness report 优先，不直接调用 executor。

## 7. 非目标

Stage 9 不做无限执行循环、不跳过 review、不自动 commit 或 push、不未授权进入新
阶段、不 production deploy、不 package publish。
