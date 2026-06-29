# Version 中文任务书：Stage 1 / v1.5 主任务书变更硬门 V1

```yaml id="version-stage-01-v1-5-zh-cn-summary"
chinese_companion:
  source_document: docs/taskbooks/versions/stage-01/VERSION_STAGE_01_V1_5_MASTER_MUTATION_HARD_GATE_V1.md
  source_sha256: 60732a6bef0d6add2382da353ad715ce88a35c0dbef33d451c1b1d128e12ed81
  translation_status: companion_draft
  authority_status: planning_reference_only
version_execution_taskbook:
  version_id: stage_01_v1_5_master_mutation_hard_gate_v1
  version: v1.5
  chinese_name: 主任务书变更硬门 V1
  status: discussion_draft
  created_from_head_meaning: historical_creation_baseline_not_execution_or_freeze_snapshot
  execution_authorization_status: not_authorized
```

## 1. 这份任务书是什么

这是 Stage 1 的第五份 Version 任务书草稿。

`Master Mutation Hard Gate V1` = 主任务书变更硬门 V1。中文意思是：定义一个硬边界，
防止普通 Version 任务、executor、runtime state、review packet 静默修改
`PROJECT_MASTER_TASKBOOK.md`。

它现在不是执行授权，不授权实现，不授权 executor，不授权 commit，不授权 push，
不授权 fetch/pull，不授权 Master Taskbook mutation，也不授权任何 delivery state
变化。

## 2. 和前面版本的关系

- v1.1 定义 registry；
- v1.2 定义 reader；
- v1.3 定义 validator；
- v1.4 定义 hash binding；
- v1.5 定义 mutation hard gate。

中文解释：v1.5 是 Stage 1 的收束门，目标是让 Stage 2 可以放心引用
`master_taskbook_ref`。

## 3. 目标

v1.5 的目标是：

- 明确受保护路径；
- 区分只读访问和修改尝试；
- 阻断未授权 Master mutation；
- 要求 Master governance 变更必须有 Commander hard gate；
- 说明 runtime state 不能授权 Master mutation；
- 说明 review packet 不能授权 Master mutation；
- 说明 executor session state 不能授权 Master mutation；
- 记录 blocked attempt，但不写 delivery_state；
- 不修改 `PROJECT_MASTER_TASKBOOK.md`。

`Commander hard gate` = 指挥官硬门。中文意思是：只有 Commander 用精确范围、精确
hash、明确 token 单独授权，Master governance 内容才可以改。

## 4. 受保护路径

`protected_paths` = 受保护路径。

最少包括：

- `PROJECT_MASTER_TASKBOOK.md`
- `PROJECT_MASTER_TASKBOOK.zh-CN.md`
- `FREEZE_CANDIDATE_REVIEW_PACKET.md`
- `FREEZE_CANDIDATE_REVIEW_PACKET.zh-CN.md`

中文解释：这些文件承载 Master 治理内容，普通任务不能静默修改。

## 5. Mutation Attempt 分类

`mutation_attempt_classes` = 变更尝试分类。

候选分类包括：

- `no_master_mutation`：没有 Master 变更；
- `read_only_master_access`：只读访问 Master；
- `unauthorized_master_mutation_attempt`：未授权 Master 变更尝试；
- `commander_authorized_master_mutation_candidate`：有 Commander 授权的候选变更；
- `unknown_master_mutation_risk`：证据不足，存在未知风险。

`gate_result` = 门禁结果。

候选结果包括：

- `allow_read_only`
- `block_unauthorized_mutation`
- `require_commander_hard_gate`
- `known_unknown`

中文解释：证据不足时不能默认放行，应该 known unknown 或 require hard gate。

## 6. 允许和禁止的文件

未来如果 Commander 单独授权执行，本版本候选写入范围最多包括：

- `runner/master_taskbook_mutation_gate.py`
- `tests/test_master_taskbook_mutation_gate.py`
- `docs/taskbooks/versions/stage-01/evidence/VERSION_STAGE_01_V1_5_MASTER_MUTATION_HARD_GATE_REPORT.md`
- `docs/taskbooks/versions/stage-01/evidence/zh-CN/VERSION_STAGE_01_V1_5_MASTER_MUTATION_HARD_GATE_REPORT.zh-CN.md`

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

中文解释：hard gate 可以定义未来的 gate helper，但不能自己去改 Master。

## 7. 候选验收命令

英文任务书列出的候选命令包括：

- `git status --short --branch`
- `git rev-parse HEAD`
- `sha256sum PROJECT_MASTER_TASKBOOK.md docs/taskbooks/versions/stage-01/VERSION_STAGE_01_V1_4_MASTER_HASH_BINDING_V1.md`
- `python -m unittest tests.test_master_taskbook_mutation_gate`
- `python -m compileall runner/master_taskbook_mutation_gate.py`
- `git diff --check` 针对未来证据报告文件
- `rg -n` 检查未来证据报告字段

这些命令现在只是候选命令，不代表已经执行，也不代表已经授权执行。

如果 change set 不能检查，gate result 必须是 `known_unknown` 或
`require_commander_hard_gate`，不能静默允许 Master mutation。

## 8. 证据包

v1.5 的证据包至少要包括：

- mutation gate contract summary；
- protected path check；
- mutation attempt classification；
- Commander hard gate requirement check；
- gate result；
- blocked attempt or none；
- 中文 mutation gate report companion；
- not_validated；
- remaining_risks。

不能把 chat memory、stale executor session state、runtime PASSED/COMPLETED labels、
未接受的 review packet claims 或 delivery_state accepted 当作权威。

## 9. 人工验收

审查者可以接受的条件：

- protected paths 明确；
- 只读访问和修改尝试明确区分；
- 未授权 Master mutation 被阻断；
- Commander hard gate 要求明确；
- runtime state 不能授权 Master mutation；
- review packet 不能授权 Master mutation；
- executor session state 不能授权 Master mutation；
- 证据报告区分 commands_run 和 commands_not_run；
- 中文报告 companion 用中文解释技术术语。

不能接受的情况：

- 普通 Version 任务可以静默修改 Master；
- runtime PASSED 或 COMPLETED labels 可以授权 Master mutation；
- gate 写 delivery_state；
- gate 修改 `PROJECT_MASTER_TASKBOOK.md`；
- gate 把缺失证据当成 allow。

## 10. 停止条件

遇到以下情况必须停：

- 当前仓库不是 `/home/jenn/src/colameta-dev`；
- 实现会修改 `PROJECT_MASTER_TASKBOOK.md`；
- 实现需要修改 `/home/jenn/tools/colameta`；
- 实现需要 fetch、pull、push 或远端写入；
- gate 会把 runtime state 当成 Master mutation authority；
- gate 会把 review packet 当成 Master mutation authority；
- gate 会声称 delivery_state accepted；
- 测试需要 executor run 或服务重启。

## 11. Stage 1 收束就绪

v1.1 到 v1.5 草稿齐全后，Stage 1 具备做包级审查的基础：

- registry contract defined；
- reader contract defined；
- validator contract defined；
- hash binding contract defined；
- mutation hard gate contract defined。

下一步候选是：

```text
stage_01_version_set_freeze_candidate_review_packet_draft
```

中文解释：这只是进入包级审查和 freeze packet 草稿的条件，不授权实现、executor、
push 或 delivery_state accepted。

## 12. 非授权边界

这份任务书不授权：

- implementation；
- code changes；
- registry mutation；
- reader mutation；
- validator mutation；
- hash binding mutation；
- Master Taskbook mutation；
- Commander hard gate token generation；
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

真正要实现 Master mutation hard gate，还需要 Commander 以后按精确 hash 和范围
单独授权。
