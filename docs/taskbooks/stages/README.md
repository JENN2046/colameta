# ColaMeta Stage Taskbooks

```yaml id="stage-taskbook-index-summary"
stage_taskbook_index:
  document_type: stage_taskbook_index
  schema_version: stage_taskbook_index.discussion_draft.v1
  status: discussion_draft
  authority_status: planning_reference_only
  master_taskbook_path: PROJECT_MASTER_TASKBOOK.md
  master_taskbook_raw_snapshot_sha256: 1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34
  review_packet_path: FREEZE_CANDIDATE_REVIEW_PACKET.md
  master_review_status: freeze_candidate_confirmed_for_exact_hash
```

`Stage Taskbook` = 阶段任务书。中文意思是：它把 Master Taskbook 的最高目标
拆成一个阶段内可审查、可引用、可继续细分的交付边界。

This directory contains discussion-draft Stage Taskbooks for the Stage 0-6
Thin Governed Loop. They are planning artifacts only. They do not authorize
implementation, executor runs, commits, pushes, route transitions, or delivery
state promotion.

## MVP Stage Drafts

| Stage | File | Chinese Meaning | MVP Role |
| --- | --- | --- | --- |
| Stage 0 | `STAGE_00_BASELINE_CLOSEOUT.md` | 基线收束与执行状态清晰化 | Make reality explainable before governance claims continue. |
| Stage 1 | `STAGE_01_MASTER_TASKBOOK_ANCHORING.md` | 主任务书锚定 | Make the Master Taskbook referenceable and protected. |
| Stage 2 | `STAGE_02_STAGE_TASKBOOK_MANAGEMENT.md` | 阶段任务书管理 | Make Stage Taskbooks bounded and bound to Master. |
| Stage 3 | `STAGE_03_EXTERNAL_TASKBOOK_IMPORT.md` | 外部任务书导入协议 | Import external version taskbooks as claims, not facts. |
| Stage 4 | `STAGE_04_BOUNDED_EXECUTION_AND_EVIDENCE.md` | 有边界执行与证据 | Bind execution to envelope and evidence. |
| Stage 5 | `STAGE_05_REVIEWER_HANDOFF_PACKAGE.md` | 审查者交接包 | Give reviewers enough context to decide. |
| Stage 6 | `STAGE_06_REVIEW_FEEDBACK_INTAKE.md` | 审查反馈接入 | Convert review feedback into next-state requests. |

## Common Boundary

```text id="stage-taskbook-common-boundary"
Stage Taskbooks own bounded stage claims.
They do not own runtime facts.
They do not own accepted delivery state.
They do not replace Version Execution Taskbooks.
They do not authorize executor dispatch.
They do not mutate the Master Taskbook.
```

中文解释：这里的 Stage 文件只是把路线拆清楚，不是命令 Codex 开始实现，也不是
宣布任何交付已经通过。
