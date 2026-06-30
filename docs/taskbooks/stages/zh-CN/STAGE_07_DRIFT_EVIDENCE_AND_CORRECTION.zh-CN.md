# Stage 7 中文任务书：漂移证据与纠偏

```yaml id="stage-07-zh-cn-summary"
chinese_companion:
  source_document: docs/taskbooks/stages/STAGE_07_DRIFT_EVIDENCE_AND_CORRECTION.md
  source_sha256: 24cec5e48435254731cce4bb2e72c8810df3d041f57c142d5674d82a632cb142
  translation_status: companion_draft
  authority_status: planning_reference_only
stage:
  stage_id: stage_07_drift_evidence_and_correction
  chinese_name: 漂移证据与纠偏
  status: discussion_draft
```

## 1. 阶段定位

Stage 7 负责把项目是否偏离 master goal 的证据整理出来，让 Reviewer 判断是否
需要纠偏。

它不让 ColaMeta 自己宣布复杂语义对齐，也不自动改 taskbook、改 master goal、
扩大 stage scope、推进 Delivery State，或继续 executor。

英文源文件里的 `created_from_head=8367a7d` 是本次 Stage 7-9 准备基线。

## 2. 当前现实

当前 repo 与稳定服务都在 `8367a7d39cef0c70237625c4e50f0d6127cde3a6`。稳定
Web/MCP 服务健康，Runner 状态为 `COMPLETED`，当前版本是 `v1.11 PASSED`。

Stage 0-6 已经能提供有边界执行证据、reviewer handoff、review feedback
classification。Stage 7 应复用这些证据，不另开新的权威路径。

## 3. 绑定要求

Stage 7 drift evidence 必须绑定：

- `master_taskbook_ref`；
- `stage_taskbook_ref`；
- `version_taskbook_ref`；
- execution evidence 或 receipt；
- reviewer handoff package；
- changed files 或 touched artifacts。

本阶段显式绑定 Master Taskbook 的 Stage 7 roadmap section，并声明
`supports_project_goal=true`。

## 4. 退出条件

Stage 7 完成时需要：

- 能生成 drift evidence pack；
- executor、task、stage 三层漂移证据分开；
- 生成 master goal alignment questions；
- 生成 reviewer drift checklist；
- 明确 PLAN_ADJUST 触发条件；
- PLAN_ADJUST 只进入 Stage 8 preview flow；
- 不输出自动 semantic alignment claim。

## 5. 最小证据包

最小证据包需要：

- `drift_evidence_pack_id`；
- `master_taskbook_ref`；
- `stage_taskbook_ref`；
- `version_taskbook_ref`；
- `execution_evidence_ref`；
- changed files；
- validation truth；
- scope evidence；
- forbidden files evidence；
- out-of-scope evidence；
- master goal alignment questions；
- reviewer drift checklist；
- plan adjustment trigger conditions。

不能把 `semantic_alignment_pass`、plan mutation、master goal change、stage scope
expansion 当成权威。

## 6. 首个实现方向

建议先做 `Drift Evidence Schema V1`，并保持 source-only 或 preview-only。

在 Stage 8 controlled preview behavior 实现前，Stage 7 只负责整理证据和问题，
不负责执行 plan adjustment。

## 7. 非目标

Stage 7 不做 ColaMeta-only semantic drift judgment、不自动 rewrite taskbook、不
自动修改 master goal、不自动扩大 stage scope、不触发 Delivery State Gate、不继续
executor、不 commit、不 push。
