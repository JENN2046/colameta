# Version 中文任务书：Stage 1 / v1.3 主任务书必填字段校验器 V1

```yaml id="version-stage-01-v1-3-zh-cn-summary"
chinese_companion:
  source_document: docs/taskbooks/versions/stage-01/VERSION_STAGE_01_V1_3_MASTER_TASKBOOK_REQUIRED_FIELD_VALIDATOR_V1.md
  source_sha256: 450d35760130672b2d3e145e821a9b9bc58ba3e1369d6021f7d01e991a6f9d07
  translation_status: companion_draft
  authority_status: planning_reference_only
version_execution_taskbook:
  version_id: stage_01_v1_3_master_taskbook_required_field_validator_v1
  version: v1.3
  chinese_name: 主任务书必填字段校验器 V1
  status: discussion_draft
  created_from_head_meaning: historical_creation_baseline_not_execution_or_freeze_snapshot
  execution_authorization_status: not_authorized
```

## 1. 这份任务书是什么

这是 Stage 1 的第三份 Version 任务书草稿。

`Master Taskbook Required Field Validator V1` = 主任务书必填字段校验器 V1。
中文意思是：在 v1.2 reader 能只读拿到 Master 内容之后，检查 Master 是否具备
Stage 0-6 最小治理循环必需的字段。

它现在不是执行授权，不授权实现，不授权 executor，不授权 commit，不授权 push，
不授权 fetch/pull，也不授权任何 delivery state 变化。

## 2. 和 v1.1 / v1.2 的关系

- v1.1 定义 registry，也就是 Master 如何登记；
- v1.2 定义 reader，也就是如何只读拿到 Master 内容；
- v1.3 定义 validator，也就是拿 reader result 检查必填字段。

中文解释：validator 只吃 reader result，不重新实现 reader，也不修改 registry。

## 3. 目标

v1.3 的目标是：

- 检查 Master 最小必填字段是否存在；
- 区分 `present`、`missing`、`empty`、`malformed`、`known_unknown`；
- 对 `project_final_goal` 缺失 fail closed；
- 对 `authority_boundaries` 缺失 fail closed；
- 对 `delivery_state_gate_boundary` 缺失 fail closed；
- 产出 validation result；
- 不写 delivery_state；
- 不修改 `PROJECT_MASTER_TASKBOOK.md`。

`fail closed` = 失败时关闭。中文意思是：缺关键字段时必须明确失败，不能猜测通过。

`validation_result` = 校验结果。中文意思是：说明字段检查结果，不是 accepted。

## 4. 必填字段最小合约

`Required Field Minimum Contract` = 必填字段最小合约。

最少字段包括：

- `project_final_goal`：项目最终目标；
- `mvp_stage_scope`：MVP 阶段范围；
- `master_stage_taskbook_architecture`：Master / Stage / Version 三层任务书架构；
- `authority_boundaries`：权威边界；
- `delivery_state_gate_boundary`：交付状态门边界；
- `review_decision_mapping_boundary`：审查决策映射边界；
- `evidence_package_minimum`：最小证据包；
- `stage_0_6_thin_governed_loop`：Stage 0-6 最小治理循环；
- `forbidden_claims_or_boundary_law`：禁止声明 / 边界法；
- `versioning_policy`：版本策略。

`authority_boundaries` = 权威边界。中文意思是：说明谁能决定什么，谁不能越权。

## 5. 允许和禁止的文件

未来如果 Commander 单独授权执行，本版本候选写入范围最多包括：

- `runner/master_taskbook_validator.py`
- `tests/test_master_taskbook_validator.py`
- `docs/taskbooks/versions/stage-01/evidence/VERSION_STAGE_01_V1_3_MASTER_TASKBOOK_REQUIRED_FIELD_VALIDATOR_REPORT.md`
- `docs/taskbooks/versions/stage-01/evidence/zh-CN/VERSION_STAGE_01_V1_3_MASTER_TASKBOOK_REQUIRED_FIELD_VALIDATOR_REPORT.zh-CN.md`

禁止修改：

- `/home/jenn/tools/colameta/**`
- `PROJECT_MASTER_TASKBOOK.md`
- `PROJECT_MASTER_TASKBOOK.zh-CN.md`
- `.colameta/taskbooks/master_taskbook_registry.json`
- `docs/taskbooks/stages/**`
- `docs/taskbooks/versions/stage-00/**`
- `.colameta/state.json`
- `.colameta/runtime/**`
- `.git/**`
- `.env`、secret、credential 相关文件。

中文解释：validator 可以写自己的 helper 和测试，但不能动 Master、registry、
Stage 文件或稳定服务目录。

## 6. 候选验收命令

英文任务书列出的候选命令包括：

- `git status --short --branch`
- `git rev-parse HEAD`
- `sha256sum PROJECT_MASTER_TASKBOOK.md docs/taskbooks/versions/stage-01/VERSION_STAGE_01_V1_2_MASTER_TASKBOOK_READER_V1.md`
- `python -m unittest tests.test_master_taskbook_validator`
- `python -m compileall runner/master_taskbook_validator.py`
- `git diff --check` 针对未来证据报告文件
- `rg -n` 检查未来证据报告字段

这些命令现在只是候选命令，不代表已经执行，也不代表已经授权执行。

如果 reader output 不可用，报告必须写 `reader_result_missing` 或 `known_unknown`，
不能在 v1.3 里重写 reader。

## 7. 证据包

v1.3 的证据包至少要包括：

- validator contract summary；
- reader result input or known unknown；
- required field check table；
- fail-closed result；
- validation result；
- 中文 validator report companion；
- not_validated；
- remaining_risks。

不能把 chat memory、stale executor session state、runtime PASSED/COMPLETED labels
或 delivery_state accepted 当作权威。

## 8. 人工验收

审查者可以接受的条件：

- validator 使用 reader result 作为输入；
- validator 检查最小合约中的每个必填字段；
- 缺少 `project_final_goal` 时 fail closed；
- validator 报告 missing、empty、malformed、present 或 known_unknown；
- validator 不修改 `PROJECT_MASTER_TASKBOOK.md`；
- validator 不写 delivery_state；
- 证据报告区分 commands_run 和 commands_not_run；
- 中文报告 companion 用中文解释技术术语。

不能接受的情况：

- validator 修改 Master 内容；
- validator 把 runtime labels 当成验证权威；
- validator 声称 accepted delivery_state；
- validator 静默忽略 fail-closed 字段缺失；
- validator 重写 registry 或 reader output。

## 9. 停止条件

遇到以下情况必须停：

- 当前仓库不是 `/home/jenn/src/colameta-dev`；
- 实现会修改 `PROJECT_MASTER_TASKBOOK.md`；
- 实现会创建或修改 registry record；
- 实现会重新实现 reader，而不是消费 reader result；
- 实现需要修改 `/home/jenn/tools/colameta`；
- 实现需要 fetch、pull、push 或远端写入；
- validator result 会声称 delivery_state accepted；
- 测试需要 executor run 或服务重启。

## 10. 交接

v1.3 成功后，下一步候选是：

```text
stage_01_v1_4_master_hash_binding_v1
```

中文解释：v1.4 可以使用 validator result 作为证据输入，但不能把 validator result
当成 accepted。

## 11. 非授权边界

这份任务书不授权：

- implementation；
- code changes；
- registry mutation；
- reader mutation；
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

真正要实现 Master validator，还需要 Commander 以后按精确 hash 和范围单独授权。
