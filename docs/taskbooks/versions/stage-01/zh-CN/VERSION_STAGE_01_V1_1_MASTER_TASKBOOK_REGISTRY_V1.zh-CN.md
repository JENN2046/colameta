# Version 中文任务书：Stage 1 / v1.1 主任务书登记表 V1

```yaml id="version-stage-01-v1-1-zh-cn-summary"
chinese_companion:
  source_document: docs/taskbooks/versions/stage-01/VERSION_STAGE_01_V1_1_MASTER_TASKBOOK_REGISTRY_V1.md
  source_sha256: 503af0ff7cdac71c55b9fa3d47a09d3fc484c851daffb244a52385ac0dd2b896
  translation_status: companion_draft
  authority_status: planning_reference_only
version_execution_taskbook:
  version_id: stage_01_v1_1_master_taskbook_registry_v1
  version: v1.1
  chinese_name: 主任务书登记表 V1
  status: discussion_draft
  created_from_head_meaning: historical_creation_baseline_not_execution_or_freeze_snapshot
  execution_authorization_status: not_authorized
```

## 1. 这份任务书是什么

这是 Stage 1 的第一份 Version 任务书草稿。

`Version Execution Taskbook` = 版本执行任务书。中文意思是：把一个 Stage 下面的一次
小交付拆成明确边界，说明目标、能读什么、能写什么、怎么验收、什么时候停止、需要
哪些证据。

本版本叫：

```text
Master Taskbook Registry V1
```

中文意思是：

```text
主任务书登记表 V1
```

它的核心任务是：先定义一条最小机器可读登记记录，让 ColaMeta 知道当前项目使用
哪一份 `PROJECT_MASTER_TASKBOOK.md`、它的 hash 是什么、它处于什么审查状态、它
不能被当成什么权威。

它现在不是执行授权，不授权实现，不授权 executor，不授权 commit，不授权 push，
不授权 fetch/pull，也不授权任何 delivery state 变化。

## 2. 父级绑定

这份 Version 绑定到：

- Master Taskbook：`PROJECT_MASTER_TASKBOOK.md`
  - hash：`1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34`
  - 状态：`freeze_candidate_confirmed_for_exact_hash`
- Stage 1 Taskbook：`docs/taskbooks/stages/STAGE_01_MASTER_TASKBOOK_ANCHORING.md`
  - hash：`f880585ed8d37639d215c9f440b37750defa9201f265b2fb7bd63cfdacf6c326`
- Stage 0-6 freeze packet：`docs/taskbooks/stages/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_0_6.md`
  - hash：`94ea9101a120e0935e834533ed0315a6fe3e77e3d4ecb48db37fa6851e75b5ce`
- Stage 0 Version set confirmation record：
  - path：`docs/taskbooks/versions/stage-00/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_00_VERSIONS.md`
  - hash：`b3d838f5229a94e88dbaa405a0f65ae76f5208660ab000c1eecd777090897acc`

中文解释：它只能服务 Stage 1 的“主任务书锚定”，不能反过来修改 Master、Stage 1
或 Stage 0 的确认记录。

## 3. 目标

本版本的目标是定义 Stage 1 的第一刀实现边界：

- 登记 Master 文件路径；
- 登记 Master raw snapshot hash；
- 登记 Master review status；
- 明确 `freeze_candidate` 不是 active authority；
- 登记当前观察到的 Git HEAD；
- 登记本地 `origin/main` tracking ref 状态；
- 写清楚 Master mutation boundary，也就是 Master 变更边界；
- 给后续 reader、validator、hash binding、mutation gate 提供同一个锚点。

`raw snapshot hash` = 原始快照 hash。中文意思是：直接对文件当前内容算出来的
hash，不先做 canonical 化。

`review status` = 审查状态。中文意思是：例如 `freeze_candidate` 表示进入冻结候选
审查，不等于 active authority，也不等于 accepted。

## 4. 不做什么

v1.1 不做：

- 完整任务书平台；
- Master reader；
- Master validator；
- canonical hash engine；
- CLI status surface；
- executor dispatch；
- delivery-state acceptance；
- codex-router bridge；
- Master 自动生成；
- Master 内容修改。

中文解释：这一刀只做“登记合约”。不要把 Stage 1 的所有能力塞进第一版。

## 5. 执行信封是什么意思

`Execution Envelope` = 执行信封。

中文意思是：真正执行前必须有一封边界信，明确：

- 可以读哪些文件；
- 可以写哪些文件；
- 不能碰哪些文件；
- 可以运行哪些命令；
- 什么时候必须停下；
- 最后报告到哪里。

英文任务书里已经写了一个候选执行信封，但它现在还没有被授权。

## 6. 允许和禁止的文件

未来如果 Commander 单独授权执行，本版本候选写入范围最多包括：

- `.colameta/taskbooks/master_taskbook_registry.json`
- `runner/master_taskbook_registry.py`
- `tests/test_master_taskbook_registry.py`
- `docs/taskbooks/versions/stage-01/evidence/VERSION_STAGE_01_V1_1_MASTER_TASKBOOK_REGISTRY_REPORT.md`
- `docs/taskbooks/versions/stage-01/evidence/zh-CN/VERSION_STAGE_01_V1_1_MASTER_TASKBOOK_REGISTRY_REPORT.zh-CN.md`

这些现在只是候选路径，不是当前授权。

禁止修改：

- `/home/jenn/tools/colameta/**`
- `PROJECT_MASTER_TASKBOOK.md`
- `PROJECT_MASTER_TASKBOOK.zh-CN.md`
- `FREEZE_CANDIDATE_REVIEW_PACKET.md`
- `docs/taskbooks/stages/**`
- `docs/taskbooks/versions/stage-00/**`
- `.colameta/state.json`
- `.colameta/runtime/**`
- `.git/**`
- `.env`、secret、credential 相关文件。

中文解释：v1.1 可以定义未来 registry 怎么写，但不能现在就修改 Master，也不能碰
稳定服务目录。

## 7. 主任务书登记表最小合约

`Master Registry Minimum Contract` = 主任务书登记表最小合约。

中文意思是：未来 registry 至少要记录这些字段：

- `project`：项目名；
- `workspace`：项目目录；
- `master_taskbook_path`：Master 文件路径；
- `master_raw_snapshot_sha256`：Master 原始文件 hash；
- `master_review_status`：Master 审查状态；
- `master_authority_boundary`：Master 权威边界；
- `project_final_goal_ref`：项目最终目标引用；
- `source_stage_taskbook_ref`：来源 Stage 任务书引用；
- `source_version_taskbook_ref`：来源 Version 任务书引用；
- `observed_git_head`：观察到的 Git HEAD；
- `observed_origin_main_local_tracking_ref`：观察到的本地 `origin/main` tracking ref；
- `ahead_behind_from_local_refs`：基于本地引用算出的 ahead/behind；
- `live_remote_status_not_validated`：没有验证 live remote 最新状态；
- `mutation_boundary`：变更边界；
- `created_at`：创建时间。

registry 绝对不能声称：

- Master 已经是 active execution authority；
- Master 已经是 accepted delivery state；
- `freeze_candidate` 自动授权 executor；
- registry 记录可以修改 Master；
- registry 记录可以覆盖 Delivery State Gate。

## 8. 候选验收命令

英文任务书列出的候选命令包括：

- `git status --short --branch`
- `git rev-parse HEAD`
- `git rev-parse origin/main || true`
- `git rev-list --left-right --count origin/main...HEAD || true`
- `sha256sum PROJECT_MASTER_TASKBOOK.md docs/taskbooks/stages/STAGE_01_MASTER_TASKBOOK_ANCHORING.md`
- `python -m unittest tests.test_master_taskbook_registry`
- `python -m compileall runner/master_taskbook_registry.py`
- `git diff --check` 针对未来证据报告文件
- `rg -n` 检查未来证据报告字段

这些命令现在只是候选命令，不代表已经执行，也不代表已经授权执行。

如果本地 `origin/main` tracking ref 不可用，报告必须写成 `known_unknown`，不能自动
`fetch` 或联系远端。

## 9. 证据包是什么意思

`Evidence Package` = 证据包。

中文意思是：把“做了什么、看到了什么、哪些命令跑了、哪些没跑、还有什么风险”
收起来给审查者看。证据包不是批准，不会改变 delivery state。

v1.1 的证据包至少要包括：

- registry contract summary；
- registry file or known unknown；
- Master hash check；
- observed Git HEAD check；
- local tracking ref check；
- mutation boundary check；
- fail-closed validation check；
- 中文 registry report companion；
- not_validated；
- remaining_risks。

不能把 chat memory、stale executor session state、runtime PASSED/COMPLETED labels、
未接受的 review packet claims、未经授权探测的 live remote state 当成权威。

## 10. 人工验收

审查者可以接受的条件：

- registry 记录存在，或明确写出 known unknown；
- registry 按精确 raw snapshot hash 绑定 `PROJECT_MASTER_TASKBOOK.md`；
- registry 区分 `freeze_candidate` 审查状态和 active authority；
- registry 保留 `project_final_goal_ref`；
- registry 包含 Master governance 内容的 mutation boundary；
- registry helper 在缺少必填字段时 fail closed；
- 证据报告区分 commands_run 和 commands_not_run；
- 中文报告 companion 用中文解释技术术语。

不能接受的情况：

- registry 声称 Master 已经是 active execution authority；
- registry 修改 `PROJECT_MASTER_TASKBOOK.md`；
- registry 把 `freeze_candidate` 映射成 accepted delivery_state；
- 证据只来自 chat memory 或 stale runtime labels；
- 测试或报告校验失败却没有 documented known_unknowns。

## 11. 停止条件

遇到以下情况必须停：

- 当前仓库不是 `/home/jenn/src/colameta-dev`；
- 实现会修改 `PROJECT_MASTER_TASKBOOK.md`；
- 实现需要修改 `/home/jenn/tools/colameta`；
- 实现需要 fetch、pull、push 或远端写入；
- registry 记录会声称 Master 是 active authority；
- registry 记录会声称 delivery_state accepted；
- 必需 hash 和父级声明不匹配；
- 测试需要 executor run 或服务重启。

## 12. 交接

v1.1 成功后，下一步候选是：

- `stage_01_v1_2_master_taskbook_reader_v1`
- `stage_01_v1_3_master_taskbook_required_field_validator_v1`
- `stage_01_v1_4_master_hash_binding_v1`
- `stage_01_v1_5_master_mutation_hard_gate_v1`

中文解释：不要直接跳到完整 taskbook platform、外部导入、executor dispatch 或
delivery_state acceptance。

## 13. 非授权边界

这份任务书不授权：

- implementation；
- code changes；
- registry mutation；
- Master Taskbook mutation；
- commit；
- push；
- fetch；
- pull；
- executor run；
- service restart；
- route transition；
- remote write；
- release；
- deploy；
- delivery_state transition。

真正要实现 Master registry，还需要 Commander 以后按精确 hash 和范围单独授权。
