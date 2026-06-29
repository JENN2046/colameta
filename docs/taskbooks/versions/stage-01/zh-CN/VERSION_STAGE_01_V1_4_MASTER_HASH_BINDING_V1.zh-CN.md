# Version 中文任务书：Stage 1 / v1.4 主任务书哈希绑定 V1

```yaml id="version-stage-01-v1-4-zh-cn-summary"
chinese_companion:
  source_document: docs/taskbooks/versions/stage-01/VERSION_STAGE_01_V1_4_MASTER_HASH_BINDING_V1.md
  source_sha256: c8e7f2d41ad1094495f687f4e7b10b012f415823174d1fe988b2d05f83bcb0ff
  translation_status: companion_draft
  authority_status: planning_reference_only
version_execution_taskbook:
  version_id: stage_01_v1_4_master_hash_binding_v1
  version: v1.4
  chinese_name: 主任务书哈希绑定 V1
  status: discussion_draft
  created_from_head_meaning: historical_creation_baseline_not_execution_or_freeze_snapshot
  execution_authorization_status: not_authorized
```

## 1. 这份任务书是什么

这是 Stage 1 的第四份 Version 任务书草稿。

`Master Hash Binding V1` = 主任务书哈希绑定 V1。中文意思是：把 registry 声明的
Master hash、reader 实际读到的 Master hash、validator 使用的输入 hash 放到一起
核对，确认它们是否指向同一份 Master 内容。

它现在不是执行授权，不授权实现，不授权 executor，不授权 commit，不授权 push，
不授权 fetch/pull，不授权 canonical receipt finalization，也不授权任何 delivery
state 变化。

## 2. 和前面版本的关系

- v1.1 定义 registry；
- v1.2 定义 reader；
- v1.3 定义 validator；
- v1.4 定义 hash binding。

中文解释：v1.4 只比较这些上游结果里的 hash，不重新实现 registry、reader 或
validator。

## 3. 目标

v1.4 的目标是：

- 比较 `registry_master_raw_snapshot_sha256`；
- 比较 `reader_raw_content_sha256`；
- 比较 `validator_input_raw_content_sha256`；
- 产出 `hash_binding_result`；
- 区分 `match`、`mismatch`、`missing_input`、`known_unknown`；
- 对 mismatch 和 missing input fail closed；
- 明确 canonical payload hash finalization 暂缓；
- 不写 delivery_state；
- 不修改 Master、registry、reader output 或 validator output。

`Hash Binding` = 哈希绑定。中文意思是：多个来源都说自己指向同一份文件，就用 hash
核对它们到底是不是同一份。

## 4. 什么是暂缓 canonical receipt

`canonical receipt` = 规范收据。中文意思是：按规范字段抽取、排序、序列化以后生成
的正式 hash 收据。

v1.4 不做最终 canonical receipt，只做 raw snapshot hash 绑定。这样可以避免把
Stage 1 的哈希检查膨胀成完整规范化系统。

## 5. 允许和禁止的文件

未来如果 Commander 单独授权执行，本版本候选写入范围最多包括：

- `runner/master_taskbook_hash_binding.py`
- `tests/test_master_taskbook_hash_binding.py`
- `docs/taskbooks/versions/stage-01/evidence/VERSION_STAGE_01_V1_4_MASTER_HASH_BINDING_REPORT.md`
- `docs/taskbooks/versions/stage-01/evidence/zh-CN/VERSION_STAGE_01_V1_4_MASTER_HASH_BINDING_REPORT.zh-CN.md`

禁止修改：

- `/home/jenn/tools/colameta/**`
- `PROJECT_MASTER_TASKBOOK.md`
- `PROJECT_MASTER_TASKBOOK.zh-CN.md`
- `.colameta/taskbooks/master_taskbook_registry.json`
- `docs/taskbooks/stages/**`
- `docs/taskbooks/versions/stage-00/**`
- `FREEZE_CANDIDATE_REVIEW_PACKET.md`
- `.colameta/state.json`
- `.colameta/runtime/**`
- `.git/**`
- `.env`、secret、credential 相关文件。

中文解释：v1.4 可以定义未来 hash-binding helper，但不能改 Master、registry 或
任何 freeze/confirmation packet。

## 6. Hash Binding 最小合约

最少输入包括：

- `registry_master_raw_snapshot_sha256`
- `reader_raw_content_sha256`
- `validator_input_raw_content_sha256`
- `observed_git_head`
- `source_version_taskbook_refs`

结果值包括：

- `match`
- `mismatch`
- `missing_input`
- `known_unknown`

其中 `mismatch` 和 `missing_input` 必须 fail closed。

## 7. 候选验收命令

英文任务书列出的候选命令包括：

- `git status --short --branch`
- `git rev-parse HEAD`
- `sha256sum PROJECT_MASTER_TASKBOOK.md docs/taskbooks/versions/stage-01/VERSION_STAGE_01_V1_3_MASTER_TASKBOOK_REQUIRED_FIELD_VALIDATOR_V1.md`
- `python -m unittest tests.test_master_taskbook_hash_binding`
- `python -m compileall runner/master_taskbook_hash_binding.py`
- `git diff --check` 针对未来证据报告文件
- `rg -n` 检查未来证据报告字段

这些命令现在只是候选命令，不代表已经执行，也不代表已经授权执行。

如果任何输入不可用，binding result 必须是 `missing_input` 或 `known_unknown`，
不能用 chat memory、runtime labels 或猜测 hash 替代。

## 8. 证据包

v1.4 的证据包至少要包括：

- hash binding contract summary；
- registry hash input or known unknown；
- reader hash input or known unknown；
- validator hash input or known unknown；
- hash binding result；
- fail-closed result；
- 中文 hash binding report companion；
- not_validated；
- remaining_risks。

不能把 chat memory、stale executor session state、runtime PASSED/COMPLETED labels、
未由本版本生成的 canonical receipt claims 或 delivery_state accepted 当作权威。

## 9. 人工验收

审查者可以接受的条件：

- binding 使用 registry、reader result、validator result；
- binding 确定性比较 raw hash；
- mismatch 或 missing input 时 fail closed；
- 明确暂缓 canonical receipt generation；
- 不修改 `PROJECT_MASTER_TASKBOOK.md`；
- 不写 delivery_state；
- 证据报告区分 commands_run 和 commands_not_run；
- 中文报告 companion 用中文解释技术术语。

不能接受的情况：

- binding 猜测缺失 hash；
- binding 声称 canonical payload hash 已最终化；
- binding 声称 active Master authority；
- binding 声称 accepted delivery_state；
- binding 重写 registry、reader output 或 validator output。

## 10. 停止条件

遇到以下情况必须停：

- 当前仓库不是 `/home/jenn/src/colameta-dev`；
- 实现会修改 `PROJECT_MASTER_TASKBOOK.md`；
- 实现会创建或修改 registry record；
- 实现会最终化 canonical receipt；
- 实现需要修改 `/home/jenn/tools/colameta`；
- 实现需要 fetch、pull、push 或远端写入；
- binding result 会声称 delivery_state accepted；
- 测试需要 executor run 或服务重启。

## 11. 交接

v1.4 成功后，下一步候选是：

```text
stage_01_v1_5_master_mutation_hard_gate_v1
```

中文解释：v1.5 可以使用 hash binding result 作为证据输入，但不能把它当成 accepted。

## 12. 非授权边界

这份任务书不授权：

- implementation；
- code changes；
- registry mutation；
- reader mutation；
- validator mutation；
- Master Taskbook mutation；
- canonical receipt generation；
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

真正要实现 Master hash binding，还需要 Commander 以后按精确 hash 和范围单独授权。
