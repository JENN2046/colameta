# 证据报告中文 companion：Stage 3 / v3.4 Taskbook-to-Version-Candidate Mapping V1

```yaml id="stage-03-v3-4-evidence-zh-cn-summary"
chinese_companion:
  companion_id: stage_03_v3_4_taskbook_to_version_candidate_mapping_evidence_zh_cn
  source_report: docs/taskbooks/versions/stage-03/evidence/VERSION_STAGE_03_V3_4_TASKBOOK_TO_VERSION_CANDIDATE_MAPPING_REPORT.md
  source_sha256: 787dce0b588c0d1bbaa7fbf28fe03258aa6535386280c48e517fbbf6355342af
  language: zh-CN
  authority_status: non_authoritative_reading_companion
  review_acceptance: false
  delivery_state_accepted: false
```

这份文件是 v3.4 英文证据报告的中文阅读 companion。它不是新的权威副本，不产生计划插入、外部任务书采用、allowed_files 扩展、执行授权、审查接受、GateEvent 或 delivery state accepted。

v3.4 的目标是实现 `Taskbook-to-Version-Candidate Mapping V1`，中文是“任务书到版本候选映射 V1”。它把 v3.3 的 import preview 和 v3.2 产生的 `normalized_claims_candidate` 翻译成 ColaMeta 内部的 Version candidate 对象。

最关键的边界：mapping_ready 只表示“候选对象可以被展示和继续审查”，不表示“已经写入计划”，也不表示“可以执行”。

---

## 1. 本轮实现摘要

```yaml id="stage-03-v3-4-implementation-summary-zh-cn"
implementation_summary:
  source_version_taskbook: docs/taskbooks/versions/stage-03/VERSION_STAGE_03_V3_4_TASKBOOK_TO_VERSION_CANDIDATE_MAPPING_V1.md
  source_version_taskbook_sha256: a1ef7d80d50655dc24b19c23d696cd69a16bbc0fbaa0aa35811b858c41e849b1
  implementation_authorization_head: 2f74ea3a9b0301f1dda6908ab22adca3c037177b
  master_taskbook_sha256: 1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34
  stage_03_taskbook_sha256: c5402734ef6990687a6a03ec6b17769f598ff0319b350b6a2371144985ece7ff
  v3_3_import_preview_helper_sha256: 5717d7da4cfc0143484c6bfbb8ce66a712a05e880af0cee6726d296375aecca7
  v3_3_import_preview_evidence_sha256: b6b3c999155f89b301ed42a4b8f7f65a7d6d8aa8f4159f89f551c200355c4285
  version_candidate_mapping_helper_sha256: eb9925f2d1f3a2ba79db945a8a04d13f7b978856b7228ed2b61bfda277ebbc47
  version_candidate_mapping_tests_sha256: 06e3f2c48184f09732603c90f33b736fdb194de2a0a916e7188a44bdb2a45f67
```

本轮新增 4 个允许范围内的文件：

```yaml id="stage-03-v3-4-files-changed-zh-cn"
files_changed:
  created:
    - runner/taskbook_version_candidate_mapping.py
    - tests/test_taskbook_version_candidate_mapping.py
    - docs/taskbooks/versions/stage-03/evidence/VERSION_STAGE_03_V3_4_TASKBOOK_TO_VERSION_CANDIDATE_MAPPING_REPORT.md
    - docs/taskbooks/versions/stage-03/evidence/zh-CN/VERSION_STAGE_03_V3_4_TASKBOOK_TO_VERSION_CANDIDATE_MAPPING_REPORT.zh-CN.md
  modified: []
  forbidden_files_touched: []
```

本轮没有修改 Master、中文 Master companion、Stage Taskbook、Version Taskbook、freeze packet、`.colameta/plan.json`、executor state、route state 或服务运行时。

---

## 2. Mapping Contract 中文解释

`mapping` 在这里的意思是“映射”：把已经通过 preview 的外部任务书请求，转成 ColaMeta 内部能理解的 Version candidate 形状。

它必须输出：

```yaml id="stage-03-v3-4-mapping-contract-zh-cn"
mapping_contract_summary:
  helper: runner.taskbook_version_candidate_mapping.map_preview_to_version_candidate
  accepted_input:
    - import_preview
    - import_preview_hash
    - normalized_claims_candidate
  mapping_statuses:
    - mapping_ready
    - mapping_blocked_preview_not_ready
    - mapping_blocked_scope_conflict
    - mapping_blocked_authority_confusion
  required_output_fields:
    - version_candidate_id
    - mapping_status
    - source_taskbook_ref
    - import_preview_ref
    - candidate_parent_refs
    - candidate_version_identity
    - candidate_allowed_files
    - candidate_forbidden_files
    - candidate_acceptance_commands
    - candidate_manual_acceptance
    - candidate_evidence_requirements
    - candidate_out_of_scope
    - adoption_blockers
    - required_commander_decisions
    - authority_boundary
```

中文解释：

```yaml id="stage-03-v3-4-field-meaning-zh-cn"
field_meaning:
  version_candidate_id: 内部版本候选 ID，不是 plan item ID。
  mapping_status: 映射状态。
  source_taskbook_ref: 外部任务书来源 hash 和来源摘要。
  import_preview_ref: v3.3 preview 的引用和 hash。
  candidate_parent_refs: 候选 Master / Stage 绑定。
  candidate_version_identity: 候选版本身份。
  candidate_allowed_files: 候选 allowed_files，不是授权范围变化。
  candidate_forbidden_files: 候选 forbidden_files。
  candidate_acceptance_commands: 候选验证命令，不是运行授权。
  candidate_manual_acceptance: 候选人工确认，不是状态接受。
  candidate_evidence_requirements: 采用之前需要的证据。
  candidate_out_of_scope: 外部任务书明确不覆盖的范围。
  adoption_blockers: 采用阻塞项。
  required_commander_decisions: 继续前需要 Commander 决定的事项。
  authority_boundary: 权限边界。
```

---

## 3. preview_ready 正向案例

```yaml id="stage-03-v3-4-positive-case-zh-cn"
preview_ready_positive_case:
  mapping_status: mapping_ready
  version_candidate_id: version_candidate_aaaaaaaaaaaa
  source_taskbook_hash_preserved: true
  import_preview_hash_preserved: true
  parent_refs_preserved:
    master_taskbook_ref: PROJECT_MASTER_TASKBOOK.md
    stage_taskbook_ref: stage_03_external_taskbook_import
  candidate_allowed_files:
    candidate_only: true
    authorized_delta: false
  candidate_acceptance_commands:
    candidate_only: true
    authorized_to_run: false
  plan_item_inserted: false
  delivery_state_accepted: false
```

中文解释：即使 mapping_ready，也只是候选对象 ready。它仍然没有插入 plan，没有授权 allowed_files 变化，也没有进入 accepted 状态。

---

## 4. blocked preview 负向案例

```yaml id="stage-03-v3-4-negative-case-zh-cn"
preview_blocked_negative_case:
  mapping_status: mapping_blocked_preview_not_ready
  blocker_code: import_preview_not_ready
  plan_mutation_authorized: false
  plan_item_inserted: false
  delivery_state_accepted: false
```

中文解释：如果 v3.3 preview 没有 ready，v3.4 不能继续映射。它会直接 block。

---

## 5. Preservation Check = 保留检查

```yaml id="stage-03-v3-4-preservation-check-zh-cn"
preservation_check:
  source_taskbook_hash:
    preserved_from: normalized_claims_candidate.external_taskbook_hash
    output_field: source_taskbook_ref.external_taskbook_hash
  import_preview_hash:
    preserved_from: map_preview_to_version_candidate.import_preview_hash
    output_field: import_preview_ref.import_preview_hash
  master_taskbook_ref:
    preserved_from: normalized_claims_candidate.master_taskbook_ref
    output_field: candidate_parent_refs.master_taskbook_ref
  stage_taskbook_ref:
    preserved_from: normalized_claims_candidate.stage_taskbook_ref
    output_field: candidate_parent_refs.stage_taskbook_ref
  required_commander_decisions:
    preserved_from: import_preview.required_commander_decisions
    output_field: required_commander_decisions
```

中文解释：mapping 不能把外部来源 hash、preview hash、Master / Stage 绑定和 Commander 决策需求弄丢。丢了就不能继续。

---

## 6. 权限边界

```yaml id="stage-03-v3-4-authority-boundary-zh-cn"
authority_boundary_check:
  mapping_result_is_authority: false
  mapping_inserts_plan_item: false
  mapping_mutates_plan: false
  mapping_expands_allowed_files: false
  mapping_authorizes_executor_dispatch: false
  mapping_writes_delivery_state: false
  creates_review_decision: false
  emits_gate_event: false
  plan_item_inserted: false
  plan_mutation_authorized: false
  allowed_files_expansion_authorized: false
  executor_dispatch_authorized: false
  delivery_state_accepted: false
```

中文大白话：mapping 可以生成“候选对象”，但不能把候选对象塞进计划，也不能让它变成可执行任务。

---

## 7. 已运行验证

```text id="stage-03-v3-4-validation-zh-cn"
git status -sb
  result: PASS
  observed_after_v3_3_commit_before_reports:
    ## main...origin/main [ahead 60]
    ?? runner/taskbook_version_candidate_mapping.py
    ?? tests/test_taskbook_version_candidate_mapping.py

git rev-parse HEAD
  result: PASS
  observed: 2f74ea3a9b0301f1dda6908ab22adca3c037177b

git rev-list --count origin/main..HEAD
  result: PASS
  observed: 60

sha256sum PROJECT_MASTER_TASKBOOK.md docs/taskbooks/stages/STAGE_03_EXTERNAL_TASKBOOK_IMPORT.md docs/taskbooks/versions/stage-03/VERSION_STAGE_03_V3_4_TASKBOOK_TO_VERSION_CANDIDATE_MAPPING_V1.md runner/taskbook_import_preview.py runner/taskbook_version_candidate_mapping.py tests/test_taskbook_version_candidate_mapping.py docs/taskbooks/versions/stage-03/evidence/VERSION_STAGE_03_V3_3_TASKBOOK_IMPORT_PREVIEW_REPORT.md
  result: PASS

.venv/bin/python -m compileall runner/taskbook_version_candidate_mapping.py
  result: PASS

.venv/bin/python -m unittest tests.test_taskbook_version_candidate_mapping
  result: PASS
  observed: Ran 11 tests ... OK

git diff --check
  result: PASS

read-only mapping smoke
  result: PASS
  observed:
    mapping_status: mapping_ready
    version_candidate_id: version_candidate_aaaaaaaaaaaa
    candidate_only: true
    authorized_delta: false
    plan_item_inserted: false
    delivery_state_accepted: false
```

---

## 8. 没有运行或没有授权的动作

```yaml id="stage-03-v3-4-not-authorized-zh-cn"
not_authorized_and_not_run:
  - fetch
  - pull
  - push
  - force_push
  - executor_run
  - route_transition
  - service_restart
  - release
  - deploy
  - remote_write
  - full_unittest_discovery
  - plan_mutation
  - plan_insertion
  - allowed_files_expansion
  - import_adoption
  - review_acceptance
  - review_decision_creation
  - gate_event_emission
  - delivery_state_transition
  - acceptance_command_execution
  - modifying_/home/jenn/tools/colameta
```

---

## 9. 已知缺口和剩余风险

```yaml id="stage-03-v3-4-known-gaps-zh-cn"
known_gaps:
  - mapping 消费结构化 preview 和 normalized claim，不解析任意外部 Markdown taskbook。
  - mapping 只创建候选对象，不写入 .colameta/plan.json。
  - mapping 不授权采用、allowed_files 扩展、命令执行或状态转换。
  - 本轮只运行了 v3.4 focused unittest module。
remaining_risks:
  - v3.5 必须保持 import adoption 为 preview-only，除非单独 hard gate 授权实际采用。
  - 未来 plan insertion 代码只能在明确 hash-specific adoption 授权后消费这个 mapping。
  - UI/report 层不能把 mapping_ready 当成 accepted、adopted 或 executable。
```

结论：v3.4 已经把外部任务书从 preview 转成内部 Version candidate 的候选结构，但没有把它写入计划，也没有放开执行或状态推进。
