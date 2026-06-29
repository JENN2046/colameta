# Stage 1 / v1.1 主任务书登记表 V1 证据报告中文 Companion

```yaml id="stage-01-v1-1-evidence-zh-cn-summary"
chinese_companion:
  source_document: docs/taskbooks/versions/stage-01/evidence/VERSION_STAGE_01_V1_1_MASTER_TASKBOOK_REGISTRY_REPORT.md
  source_sha256: b3fde1b72b2286fb02f9f2ca3eb5456e17a4e291329e156f5698cd8a144d165d
  translation_status: companion_draft
  authority_status: evidence_reference_only
```

这份中文 companion 对应英文证据报告。它的作用是把 Stage 1 / v1.1
`Master Taskbook Registry V1` 的实现证据用中文讲清楚。它不授权 commit、push、
executor run、route transition、review acceptance 或 delivery state accepted。

---

## 1. 这次做了什么

这次实现的是 `Master Taskbook Registry V1`，中文叫“主任务书登记表 V1”。

通俗说：我们没有改大计划本身，而是新建了一张机器可读的登记表，记录当前项目承认哪一份
`PROJECT_MASTER_TASKBOOK.md` 是 Master、它的 hash 是多少、它现在只是
`freeze_candidate_confirmed_for_exact_hash` 审查状态，以及它不能被当成执行授权。

核心文件是：

```yaml
registry_path: .colameta/taskbooks/master_taskbook_registry.json
helper: runner/master_taskbook_registry.py
tests: tests/test_master_taskbook_registry.py
```

---

## 2. 命令执行结果

已经执行并通过的关键验证：

```text
git status --short --branch
  结果：通过
  观察值：
    main 相对 origin/main 本地 ahead 48
    当前实现文件仍是未提交新增文件

git rev-parse HEAD
  结果：通过
  观察值：49aa038d3a05e29bd0e2454a458ca2494937b428

git rev-parse origin/main
  结果：通过
  观察值：018ff63b76872504407c537cd46e1e8a2ee5c22e

git rev-list --left-right --count origin/main...HEAD
  结果：通过
  观察值：0 48

sha256sum PROJECT_MASTER_TASKBOOK.md
  结果：通过
  观察值：1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34

.venv/bin/python -m compileall runner/master_taskbook_registry.py
  结果：通过

.venv/bin/python -m unittest tests.test_master_taskbook_registry
  结果：通过，15 个测试 OK

.venv/bin/python - <<'PY' ... load_master_taskbook_registry('.') ...
  结果：通过
  观察值：
    ok=True
    master_hash_verified=True
    master_expected_sha256=1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34
    master_actual_sha256=1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34

git diff --check
  结果：通过

rg 检查英文 evidence 必备字段
  结果：通过

rg 检查中文 companion 必备字段
  结果：通过

.venv/bin/python -m unittest discover -s tests
  结果：通过，153 个测试 OK
```

注意：WSL shell 里的裸 `python` 命令不可用，报错是 `python: command not found`。
所以实际使用的是项目本地 `.venv/bin/python`。这不是偷偷改口径，而是如实记录：
原命令名不可用，等价的项目本地 Python 解释器验证通过。

---

## 3. 没有执行的命令

明确没有执行：

```yaml
commands_not_run:
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
  - credential_read_or_write
```

中文大白话：这次只是在本地做第一刀实现和验证，没有碰远端，没有跑执行器，没有重启服务，
也没有推进任何 Delivery State Gate 状态。

---

## 4. 改了哪些文件

创建了这些文件：

```yaml
files_changed:
  created:
    - .colameta/taskbooks/master_taskbook_registry.json
    - runner/master_taskbook_registry.py
    - tests/test_master_taskbook_registry.py
    - docs/taskbooks/versions/stage-01/evidence/VERSION_STAGE_01_V1_1_MASTER_TASKBOOK_REGISTRY_REPORT.md
    - docs/taskbooks/versions/stage-01/evidence/zh-CN/VERSION_STAGE_01_V1_1_MASTER_TASKBOOK_REGISTRY_REPORT.zh-CN.md
  modified: []
  forbidden_files_touched: []
```

这些都在实施路线启动前总闸口材料允许的 writable allowed_files 范围内。

---

## 5. 登记表记录了什么

`master_taskbook_registry.json` 记录了这些核心字段：

```yaml
master_taskbook_path: PROJECT_MASTER_TASKBOOK.md
master_raw_snapshot_sha256: 1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34
master_review_status: freeze_candidate_confirmed_for_exact_hash
master_authority_boundary:
  review_status_is_reference_only: true
  active_execution_authority: false
  executor_authority: false
  route_transition_authority: false
  delivery_state_authority: false
  review_acceptance_authority: false
  freeze_candidate_implies_accepted: false
mutation_boundary:
  master_taskbook_mutation_allowed: false
  registry_can_mutate_master: false
  requires_separate_hash_specific_authorization: true
```

`master_taskbook_path` = 主任务书路径。

`master_raw_snapshot_sha256` = 主任务书当前快照 hash。

`master_review_status` = 主任务书当前审查状态。这里的重点是：
`freeze_candidate_confirmed_for_exact_hash` 只是“这个 hash 的候选冻结状态已确认”，
不是“可以执行”，也不是“已经 accepted”。

`master_authority_boundary` = 主任务书权威边界。它说明主任务书可以作为规划锚点，
但不能直接变成 executor 权限、route transition 权限、review acceptance 权限或
delivery state accepted。

`mutation_boundary` = 变更边界。它说明登记表不能偷偷改主任务书，后续如果要改 Master，
必须另走精确 hash 的独立授权。

---

## 6. Helper 做了什么

`runner/master_taskbook_registry.py` 做的是读取和校验登记表。

它会校验：

- 必填字段是否存在；
- `workspace` 是否就是当前项目目录；
- `PROJECT_MASTER_TASKBOOK.md` 的实际 sha256 是否等于登记表里的 hash；
- `schema_version`、`registry_record_id`、`project` 是否是精确值；
- `project_final_goal_ref` 是否保持精确的只读锚点边界；
- `source_stage_taskbook_ref` 和 `source_version_taskbook_ref` 是否绑定精确路径、hash 和 id；
- source ref 指向的实际文件 hash 是否匹配登记表；
- `master_review_status` 是否保持为精确的 freeze candidate 审查状态；
- `master_authority_boundary` 是否没有偷渡执行权限；
- `mutation_boundary` 是否没有偷渡修改 Master 的能力；
- 本地 ahead/behind 字段是否是非负整数；
- live remote 状态是否明确记录为未验证。

如果这些条件不满足，helper 会 fail closed。中文就是：宁可拒绝通过，也不含糊放行。

---

## 7. 测试覆盖了什么

`tests/test_master_taskbook_registry.py` 覆盖了这些失败关闭场景：

- 缺少必填字段；
- Master hash 不匹配；
- 登记表声称 Master 有 active execution authority；
- 登记表声称自己可以修改 Master；
- Master 路径逃出项目目录；
- live remote 边界被错误标记。
- schema version 错误；
- registry record id 错误；
- project final goal ref 被改成 active authority；
- 额外塞入 delivery_state_accepted 这类权限字段；
- source ref 的 id 错误；
- source ref 指向文件的实际 hash 不匹配；
- 默认 registry 路径被 symlink 指向项目外部。

这些测试保证：登记表只能登记 Master，不能把 Master 的 freeze candidate 状态洗成执行授权。

---

## 8. 已知未知

```yaml
known_unknowns:
  - live_remote_status_not_validated: true
  - no_fetch_pull_or_remote_probe_was_authorized_or_run
  - registry_created_against_local_origin_main_tracking_ref_only
  - review_acceptance_not_performed
  - delivery_state_gate_transition_not_performed
```

已知未知 = 我们明确知道自己没有验证的东西。

这次没有 fetch / pull，所以没有验证实时远端状态。这里只记录本地
`origin/main` tracking ref。这个边界是故意保留的，不能写成“远端已同步”。

---

## 9. 剩余风险

```yaml
remaining_risks:
  - 当前 registry 还是本地治理锚点，尚未接入用户可见流程。
  - 后续仍需要 Stage 1 / v1.2 reader、v1.3 required-field validator、v1.4 hash binding、v1.5 mutation hard gate。
  - 当前 registry 不创建 ReviewDecision，不创建 GateEvent，也不产生 Delivery State Gate accepted。
```

剩余风险 = 做完这一刀后，仍然不能假装整个 Stage 1 已经完成。

中文总结：第一刀已经把主任务书登记表立起来了，但它只是锚点，不是完整系统。
