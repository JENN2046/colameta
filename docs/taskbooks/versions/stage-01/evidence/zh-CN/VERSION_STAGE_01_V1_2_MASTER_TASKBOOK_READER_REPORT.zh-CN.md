# Stage 1 / v1.2 主任务书读取器 V1 证据报告中文 Companion

```yaml id="stage-01-v1-2-evidence-zh-cn-summary"
chinese_companion:
  source_document: docs/taskbooks/versions/stage-01/evidence/VERSION_STAGE_01_V1_2_MASTER_TASKBOOK_READER_REPORT.md
  source_sha256: 2dda8d2079bbe6bc07c63e6f4143c0101b3121a04420097a0de7e2d0e234f65c
  translation_status: companion_draft
  authority_status: evidence_reference_only
```

这份中文 companion 对应英文证据报告。它解释 Stage 1 / v1.2
`Master Taskbook Reader V1`，中文叫“主任务书读取器 V1”。它不授权 commit、push、
executor run、route transition、review acceptance 或 delivery state accepted。

---

## 1. 这次做了什么

这次实现的是一个只读 reader。中文大白话：它根据 v1.1 已经创建的
`.colameta/taskbooks/master_taskbook_registry.json`，找到 `PROJECT_MASTER_TASKBOOK.md`，
读取 Master 内容，算出内容 hash 和文件大小，然后返回一个有边界的读取结果。

它明确不做：

- 不修改 `PROJECT_MASTER_TASKBOOK.md`；
- 不修改 `.colameta/taskbooks/master_taskbook_registry.json`；
- 不判断 `project_final_goal` 是否合格；
- 不创建 ReviewDecision；
- 不创建 GateEvent；
- 不声称 delivery state accepted。

---

## 2. 命令执行结果

关键验证结果：

```text
git status --short --branch
  结果：通过
  观察值：
    main 相对 origin/main 本地 ahead 49
    当前新增英文 evidence report
    当前新增中文 companion
    当前新增 runner/master_taskbook_reader.py
    当前新增 tests/test_master_taskbook_reader.py

git rev-parse HEAD
  结果：通过
  观察值：c437b92eb0385ff2b870be1acfc995c69087594d

sha256sum PROJECT_MASTER_TASKBOOK.md
  结果：通过
  观察值：1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34

sha256sum .colameta/taskbooks/master_taskbook_registry.json
  结果：通过
  观察值：86baca398528b1cc5c635101e6fe25f0bf0e65d9363b5d5e1680e7c7bb753a3c

.venv/bin/python -m compileall runner/master_taskbook_reader.py
  结果：通过

.venv/bin/python -m unittest tests.test_master_taskbook_reader
  结果：通过，6 个测试 OK

.venv/bin/python -m unittest discover -s tests
  结果：通过，159 个测试 OK

read_master_taskbook(".")
  结果：通过
  命令边界：显式传入 observed_git_head=c437b92eb0385ff2b870be1acfc995c69087594d
  read_status: read_ok
  raw_content_sha256: 1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34
  path_within_repository: true
  failure_reason_or_none: null
```

注意：WSL shell 里的裸 `python` 命令仍不可用，报错是 `python: command not found`。
实际验证使用项目本地 `.venv/bin/python`，版本是 Python 3.12.3。

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
  - git_add_or_staging
  - commit
  - credential_read_or_write
  - registry_creation_or_repair
  - review_acceptance
  - delivery_state_transition
```

中文解释：这次只做本地 reader，不碰远端，不跑执行器，不重启服务，不改 registry，
也不推进 Delivery State Gate。

---

## 4. 改了哪些文件

创建了这些文件：

```yaml
files_changed:
  created:
    - runner/master_taskbook_reader.py
    - tests/test_master_taskbook_reader.py
    - docs/taskbooks/versions/stage-01/evidence/VERSION_STAGE_01_V1_2_MASTER_TASKBOOK_READER_REPORT.md
    - docs/taskbooks/versions/stage-01/evidence/zh-CN/VERSION_STAGE_01_V1_2_MASTER_TASKBOOK_READER_REPORT.zh-CN.md
  modified: []
  forbidden_files_touched: []
```

`PROJECT_MASTER_TASKBOOK.md` 和 `.colameta/taskbooks/master_taskbook_registry.json`
在这一刀里都是只读输入。

---

## 5. Reader Result = 读取结果

英文报告里的 reader_result 是：

```yaml
reader_result:
  registry_record_id: master_taskbook.current
  master_taskbook_path: PROJECT_MASTER_TASKBOOK.md
  resolved_master_taskbook_path: /home/jenn/src/colameta-dev/PROJECT_MASTER_TASKBOOK.md
  path_within_repository: true
  raw_content_sha256: 1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34
  observed_file_size_bytes: 163772
  observed_git_head: c437b92eb0385ff2b870be1acfc995c69087594d
  registry_review_status_boundary: freeze_candidate_confirmed_for_exact_hash
  read_status: read_ok
  failure_reason_or_none: null
  forbidden_result_fields_present: []
```

中文解释：

- `registry_record_id` = 使用哪条登记记录。
- `master_taskbook_path` = registry 里登记的 Master 路径。
- `resolved_master_taskbook_path` = 解析后的绝对路径。
- `path_within_repository` = 路径是否仍在项目目录内。
- `raw_content_sha256` = 读取到的 Master 原始内容 hash。
- `observed_file_size_bytes` = 文件大小。
- `registry_review_status_boundary` = registry 里保留的审查状态边界。
- `read_status` = 读取状态。
- `failure_reason_or_none` = 失败原因；成功时是 null。

这里最重要的是：读取成功不等于验收成功，不等于 accepted，也不等于可以执行。

---

## 6. 只读边界

这次 reader 测试覆盖：

- registry 缺失时 fail closed，并且不会自动创建 registry；
- Master 路径逃出项目目录时 fail closed；
- Master hash 不匹配时 fail closed；
- reader 不要求 `project_final_goal` 语义存在或合格；
- reader 调用前后 Master hash 不变；
- reader 调用前后 registry hash 不变；
- reader 用同一份原始 bytes 计算 `raw_content_sha256`，再把同一份 bytes 解码成 `raw_content`；
- CRLF 换行内容保留测试已覆盖；
- reader result 里没有 `delivery_state`、`accepted`、`executor_authorization`、
  `active_master_authority`、`review_decision_outcome` 这些越权字段。

`fail closed` = 失败时关闭。中文意思是：宁可明确失败，也不猜测、不修复、不悄悄通过。

---

## 7. Known Gaps = 已知缺口

```yaml
known_gaps:
  - live_remote_status_not_validated: true
  - no_fetch_pull_or_remote_probe_was_authorized_or_run
  - reader_result_is_local_only
  - reader_does_not_validate_project_final_goal_semantics
  - review_acceptance_not_performed
  - delivery_state_gate_transition_not_performed
```

已知缺口 = 我们知道自己这一刀还没有做什么。

这次没有 fetch / pull，所以没有验证实时远端状态。reader result 也是本地结果，
不是 ReviewDecision，不是 GateEvent，不是 Delivery State Gate accepted。

---

## 8. Remaining Risks = 剩余风险

```yaml
remaining_risks:
  - reader 可以把 Master 原文交给后续切片，但 v1.3 仍然要实现 required-field validation。
  - reader 依赖 v1.1 registry 继续保持有效，并在本切片中保持只读。
  - reader result 还没有暴露到 CLI、Web、executor 或 route-transition 表面。
```

剩余风险 = 做完 reader 以后，系统仍然没有完成 Stage 1。下一刀 v1.3 才会做字段校验。

中文总结：v1.2 只把“按登记表读取 Master”这条路打通了，而且保持只读。它不是验收器，
不是状态门，也不是执行器入口。
