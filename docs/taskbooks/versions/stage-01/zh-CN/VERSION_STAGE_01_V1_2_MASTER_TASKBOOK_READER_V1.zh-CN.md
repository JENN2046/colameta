# Version 中文任务书：Stage 1 / v1.2 主任务书读取器 V1

```yaml id="version-stage-01-v1-2-zh-cn-summary"
chinese_companion:
  source_document: docs/taskbooks/versions/stage-01/VERSION_STAGE_01_V1_2_MASTER_TASKBOOK_READER_V1.md
  source_sha256: 2f95e2a6d695f4426b8e4eadb6bc184d56382c2120db9970a0cee79483425103
  translation_status: companion_draft
  authority_status: planning_reference_only
version_execution_taskbook:
  version_id: stage_01_v1_2_master_taskbook_reader_v1
  version: v1.2
  chinese_name: 主任务书读取器 V1
  status: discussion_draft
  created_from_head_meaning: historical_creation_baseline_not_execution_or_freeze_snapshot
  execution_authorization_status: not_authorized
```

## 1. 这份任务书是什么

这是 Stage 1 的第二份 Version 任务书草稿。

`Master Taskbook Reader V1` = 主任务书读取器 V1。中文意思是：按 v1.1 定义的
registry 合约，只读地找到并读取 `PROJECT_MASTER_TASKBOOK.md`，返回读取结果和基础
元数据。

它现在不是执行授权，不授权实现，不授权 executor，不授权 commit，不授权 push，
不授权 fetch/pull，也不授权任何 delivery state 变化。

## 2. 和 v1.1 的关系

v1.1 是 `Master Taskbook Registry V1`，中文意思是“主任务书登记表 V1”。它定义
Master 应该如何登记。

v1.2 是 reader，中文意思是“读取器”。它只能读取 registry 和 Master，不能创建或
修改 registry，也不能判断 Master 字段是否合格。

中文解释：先有登记表，再有读取器；读取器不能反过来改登记表。

## 3. 目标

v1.2 的目标是：

- 从 registry 读取 Master path；
- 确认路径仍在 `/home/jenn/src/colameta-dev` 仓库内；
- 只读读取 Master 内容；
- 记录 raw content hash；
- 记录文件大小和当前 Git HEAD；
- 记录 read status；
- 在 registry 缺失、路径越界或读取失败时 fail closed；
- 保留 `freeze_candidate` 只是审查状态的边界。

`raw_content_sha256` = 原始内容 hash。中文意思是：对 reader 实际读到的 Master
内容算 hash。

`path_within_repository` = 路径在仓库内。中文意思是：reader 不允许顺着 registry
读到仓库外面的文件。

## 4. 不做什么

v1.2 不做：

- registry 创建；
- registry 修改；
- `project_final_goal` 语义校验；
- canonical hash；
- mutation hard gate；
- CLI / Web status surface；
- executor dispatch；
- delivery_state accepted。

这些会留给后续 v1.3、v1.4、v1.5 或更晚版本。

## 5. 允许和禁止的文件

未来如果 Commander 单独授权执行，本版本候选写入范围最多包括：

- `runner/master_taskbook_reader.py`
- `tests/test_master_taskbook_reader.py`
- `docs/taskbooks/versions/stage-01/evidence/VERSION_STAGE_01_V1_2_MASTER_TASKBOOK_READER_REPORT.md`
- `docs/taskbooks/versions/stage-01/evidence/zh-CN/VERSION_STAGE_01_V1_2_MASTER_TASKBOOK_READER_REPORT.zh-CN.md`

它可以只读查看：

- `PROJECT_MASTER_TASKBOOK.md`
- `.colameta/taskbooks/master_taskbook_registry.json`
- v1.1 任务书；
- Stage 1 任务书；
- runner 和 tests。

禁止修改：

- `/home/jenn/tools/colameta/**`
- `PROJECT_MASTER_TASKBOOK.md`
- `.colameta/taskbooks/master_taskbook_registry.json`
- `docs/taskbooks/stages/**`
- `docs/taskbooks/versions/stage-00/**`
- `.colameta/state.json`
- `.colameta/runtime/**`
- `.git/**`
- `.env`、secret、credential 相关文件。

中文解释：v1.2 的 registry 是只读输入，不是写入目标。

## 6. Reader Result 最小合约

`Reader Result` = 读取结果。中文意思是：reader 返回它读到了什么和怎么读的。

最少字段包括：

- `registry_record_id`
- `master_taskbook_path`
- `resolved_master_taskbook_path`
- `path_within_repository`
- `raw_content_sha256`
- `observed_file_size_bytes`
- `observed_git_head`
- `registry_review_status_boundary`
- `read_status`
- `failure_reason_or_none`

读取结果不能把这些字段当作权威：

- `delivery_state`
- `accepted`
- `executor_authorization`
- `active_master_authority`
- `review_decision_outcome`

中文解释：reader result 不是验收结论，只是读取证据。

## 7. 候选验收命令

英文任务书列出的候选命令包括：

- `git status --short --branch`
- `git rev-parse HEAD`
- `sha256sum PROJECT_MASTER_TASKBOOK.md .colameta/taskbooks/master_taskbook_registry.json || true`
- `python -m unittest tests.test_master_taskbook_reader`
- `python -m compileall runner/master_taskbook_reader.py`
- `git diff --check` 针对未来证据报告文件
- `rg -n` 检查未来证据报告字段

这些命令现在只是候选命令，不代表已经执行，也不代表已经授权执行。

如果 registry 文件不存在，报告必须写 `known_unknown` 或 `registry_missing`，不能在
v1.2 里顺手创建或修复 registry。

## 8. 证据包

v1.2 的证据包至少要包括：

- reader contract summary；
- registry read result or known unknown；
- Master path resolution check；
- raw content hash check；
- read-only boundary check；
- fail-closed path escape check；
- 中文 reader report companion；
- not_validated；
- remaining_risks。

这些证据只证明 reader 的读操作和边界，不证明 Master 内容已经合格。

## 9. 人工验收

审查者可以接受的条件：

- reader 只读 registry 和 Master；
- reader 拒绝仓库外路径；
- reader 报告 `raw_content_sha256`；
- reader 报告 `failure_reason_or_none`；
- reader 不修改 `PROJECT_MASTER_TASKBOOK.md`；
- reader 不创建或更新 registry；
- 证据报告区分 commands_run 和 commands_not_run；
- 中文报告 companion 用中文解释技术术语。

不能接受的情况：

- reader 校验 `project_final_goal` 语义；
- reader 声称 Master 已经是 active authority；
- reader 把 read success 映射成 accepted delivery_state；
- reader 顺手创建 registry；
- 证据只来自 chat memory 或 stale runtime labels。

## 10. 停止条件

遇到以下情况必须停：

- 当前仓库不是 `/home/jenn/src/colameta-dev`；
- 实现会修改 `PROJECT_MASTER_TASKBOOK.md`；
- 实现会创建或修改 registry record；
- 实现需要修改 `/home/jenn/tools/colameta`；
- 实现需要 fetch、pull、push 或远端写入；
- reader result 会声称 active Master authority；
- reader result 会声称 delivery_state accepted；
- 测试需要 executor run 或服务重启。

## 11. 交接

v1.2 成功后，下一步候选是：

```text
stage_01_v1_3_master_taskbook_required_field_validator_v1
```

中文解释：v1.3 才能拿 reader result 去做字段校验。reader result 本身不是 authority。

## 12. 非授权边界

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

真正要实现 Master reader，还需要 Commander 以后按精确 hash 和范围单独授权。
