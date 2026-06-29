# Version Taskbook: Stage 0 / v0.4 Executor Session HEAD Classification Report

```text id="version-stage-00-v0-4-boundary-banner"
VERSION TASKBOOK DRAFT ONLY.
This document defines a candidate Version Execution Taskbook for Stage 0. It
does not authorize execution, executor dispatch, code edits, test execution,
commit, push, service restart, runtime reload, session cleanup, route
transition, Delivery State Gate transition, or accepted delivery state.
```

```yaml id="version-taskbook-summary"
version_execution_taskbook:
  document_type: version_execution_taskbook
  schema_version: version_execution_taskbook.discussion_draft.v1
  version_id: stage_00_v0_4_executor_session_head_classification_report
  version: v0.4
  name: Executor Session HEAD Classification Report
  chinese_name: 执行器会话 HEAD 分类报告
  parent_stage_id: stage_00_baseline_closeout
  parent_stage_name: Baseline Closeout And Execution-State Clarity
  status: discussion_draft
  authority_status: planning_reference_only
  execution_authorization_status: not_authorized
  dispatch_status: not_authorized
  executor_run_authorized: false
  test_execution_authorized: false
  service_restart_authorized: false
  runtime_reload_authorized: false
  session_cleanup_authorized: false
  created_from_head: 0f29388
  created_from_head_meaning: historical_creation_baseline_not_execution_or_freeze_snapshot
  created_from_head_subject: "docs: add runtime freshness version taskbook"
  origin_main_observed: 018ff63
  local_tracking_ref_sync_status_at_creation: local_ahead_remote_tracking_ref
  local_ahead_origin_main_at_creation: 3
```

`Executor Session HEAD Classification Report` = 执行器会话 HEAD 分类报告。中文意思是：
它把 executor session 记录的 HEAD、当前 Git HEAD、operation running 状态、
runner 状态、worktree 状态和 v1.10 分类结果放在一起，说明 mismatch 是当前活跃
风险、历史 stale metadata、未知，还是没有 mismatch。

---

## 1. Parent Binding

```yaml id="parent-binding"
parent_binding:
  master_taskbook_ref:
    path: PROJECT_MASTER_TASKBOOK.md
    raw_snapshot_sha256: 1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34
    review_status: freeze_candidate_confirmed_for_exact_hash
  stage_taskbook_ref:
    path: docs/taskbooks/stages/STAGE_00_BASELINE_CLOSEOUT.md
    raw_snapshot_sha256: 12103877ba181c48056299b800c546e55ac7f68b7df82f4f657a4bd2f0e91489
    stage_id: stage_00_baseline_closeout
  stage_freeze_packet_ref:
    path: docs/taskbooks/stages/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_0_6.md
    raw_snapshot_sha256: 94ea9101a120e0935e834533ed0315a6fe3e77e3d4ecb48db37fa6851e75b5ce
    review_status: hash_specific_freeze_candidate_confirmation_recorded
  previous_version_taskbook_refs:
    - path: docs/taskbooks/versions/stage-00/VERSION_STAGE_00_V0_1_REPOSITORY_RUNTIME_REALITY_SNAPSHOT.md
      raw_snapshot_sha256: 6393181ffd38f46f319b2d3dd350e3749d59d22c0b588688a558308232897d8d
      version_id: stage_00_v0_1_repository_runtime_reality_snapshot
      status: local_baseline_commit_not_pushed_at_creation
    - path: docs/taskbooks/versions/stage-00/VERSION_STAGE_00_V0_2_VALIDATION_TRUTH_SOURCE_REPORT.md
      raw_snapshot_sha256: 52adaf2a391081ef73a7dd1f91f1af48d8daea546da80232b9b3afe2ebbc2ec8
      version_id: stage_00_v0_2_validation_truth_source_report
      status: local_baseline_commit_not_pushed_at_creation
    - path: docs/taskbooks/versions/stage-00/VERSION_STAGE_00_V0_3_RUNTIME_FRESHNESS_REPORT.md
      raw_snapshot_sha256: 7234b7a38116fcd72115023d8cf35335bb5b8f7324ecbc6613153c7946b7ea1c
      version_id: stage_00_v0_3_runtime_freshness_report
      status: local_baseline_commit_not_pushed_at_creation
  implementation_history_ref:
    version: v1.10
    name: Executor Session Head Mismatch Classification
    prompt_path: .colameta/prompts/v1.10.md
    prompt_sha256: 4ebfa01bf2ef17f7c37eb6ce11e8a092bc250bdeb3092b4c2f32485176f535be
  supports_project_goal: true
```

This Version Taskbook is subordinate to Stage 0. It may report and explain the
existing v1.10 executor-session HEAD mismatch classification behavior, but it
must not mutate session files, start or resume an executor, clean stale metadata,
or reinterpret classification labels as delivery state.

中文解释：这份 Version 只做“分类报告”，不能清理 session，不能开 executor，
不能把 stale session 说成当前运行，也不能把分类结果当成 accepted。

---

## 2. Task Goal

```yaml id="task-goal"
task_goal:
  primary_goal: >
    Produce a bounded Executor Session HEAD Classification Report that records
    the current Git HEAD, executor-session recorded HEAD if observable,
    operation-running evidence, runner/latest-run evidence, worktree evidence,
    v1.10 classification status, operator message, limitations, and known
    unknowns.
  minimum_readiness_claim: >
    Executor-session HEAD mismatch evidence is explainable enough that later
    governance work can distinguish an active operation mismatch from completed
    idle stale session metadata, unknown mismatch, and no mismatch.
  gate_question: >
    Can a reviewer tell whether executor-session HEAD mismatch represents an
    active operation risk, historical stale metadata, unknown evidence, or no
    mismatch without cleaning or rewriting session state?
  explicit_non_goal: >
    This version is not session cleanup, executor resume, executor start,
    service restart, runtime reload, code mutation, classification
    implementation, or delivery-state acceptance.
```

---

## 3. Candidate Execution Envelope

This section is an envelope candidate only. It becomes executable only if the
Commander separately authorizes it by exact hash and scope.

```yaml id="candidate-execution-envelope"
execution_envelope_candidate:
  authorization_status: not_authorized
  parent_hashes:
    master_taskbook_hash: 1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34
    stage_taskbook_hash: 12103877ba181c48056299b800c546e55ac7f68b7df82f4f657a4bd2f0e91489
    stage_freeze_packet_hash: 94ea9101a120e0935e834533ed0315a6fe3e77e3d4ecb48db37fa6851e75b5ce
    previous_v0_1_taskbook_hash: 6393181ffd38f46f319b2d3dd350e3749d59d22c0b588688a558308232897d8d
    previous_v0_2_taskbook_hash: 52adaf2a391081ef73a7dd1f91f1af48d8daea546da80232b9b3afe2ebbc2ec8
    previous_v0_3_taskbook_hash: 7234b7a38116fcd72115023d8cf35335bb5b8f7324ecbc6613153c7946b7ea1c
  task_goal_ref: task_goal.primary_goal
  definition_of_good:
    - executor session HEAD classification report exists at the declared reporting destination
    - report records current_git_head and session_recorded_head_or_known_unknown separately
    - report records operation_running evidence or known_unknown
    - report records runner/latest-run evidence or known_unknown
    - report uses the v1.10 classification vocabulary without inventing delivery_state
    - report does not clean, rewrite, start, resume, or kill executor/session/runtime state
  allowed_autonomy_after_explicit_authorization:
    - local read-only inspection
    - local HTTP status probe against localhost status endpoint
    - local report file creation under allowed output paths
    - narrow report correction if validation finds missing required fields
```

`Executor Session HEAD mismatch` = 执行器会话 HEAD 不匹配。中文意思是：executor
session 记录的 HEAD 和当前 Git HEAD 不一样。它可能是真风险，也可能只是历史
metadata，必须分类，而不能直接当成“正在跑旧代码”。

---

## 4. Allowed Files And Mutations

```yaml id="allowed-files-and-mutations"
allowed_files:
  read_only:
    - PROJECT_MASTER_TASKBOOK.md
    - PROJECT_MASTER_TASKBOOK.zh-CN.md
    - docs/taskbooks/stages/STAGE_00_BASELINE_CLOSEOUT.md
    - docs/taskbooks/stages/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_0_6.md
    - docs/taskbooks/versions/stage-00/VERSION_STAGE_00_V0_1_REPOSITORY_RUNTIME_REALITY_SNAPSHOT.md
    - docs/taskbooks/versions/stage-00/VERSION_STAGE_00_V0_2_VALIDATION_TRUTH_SOURCE_REPORT.md
    - docs/taskbooks/versions/stage-00/VERSION_STAGE_00_V0_3_RUNTIME_FRESHNESS_REPORT.md
    - docs/taskbooks/versions/stage-00/zh-CN/VERSION_STAGE_00_V0_1_REPOSITORY_RUNTIME_REALITY_SNAPSHOT.zh-CN.md
    - docs/taskbooks/versions/stage-00/zh-CN/VERSION_STAGE_00_V0_2_VALIDATION_TRUTH_SOURCE_REPORT.zh-CN.md
    - docs/taskbooks/versions/stage-00/zh-CN/VERSION_STAGE_00_V0_3_RUNTIME_FRESHNESS_REPORT.zh-CN.md
    - docs/taskbooks/CHINESE_COMPANION_POLICY.md
    - docs/taskbooks/CHINESE_COMPANION_INDEX.md
    - .colameta/plan.json
    - .colameta/plan.zh-CN.md
    - .colameta/state.json
    - .colameta/prompts/v1.10.md
    - .colameta/prompts/zh-CN/v1.10.zh-CN.md
    - .colameta/runtime/**
    - runner/executor_session.py
    - runner/web_console.py
    - runner/web_console_presenter.py
    - tests/test_executor_session_head_mismatch.py
  writable_after_separate_execution_authorization:
    - docs/taskbooks/versions/stage-00/evidence/VERSION_STAGE_00_V0_4_EXECUTOR_SESSION_HEAD_CLASSIFICATION_REPORT.md
    - docs/taskbooks/versions/stage-00/evidence/zh-CN/VERSION_STAGE_00_V0_4_EXECUTOR_SESSION_HEAD_CLASSIFICATION_REPORT.zh-CN.md

allowed_mutations:
  - create_or_update_declared_executor_session_head_classification_report_only_after_explicit_execution_authorization
  - create_or_update_declared_chinese_report_companion_only_after_explicit_execution_authorization

forbidden_files:
  mutation_targets:
    - /home/jenn/tools/colameta/**
    - runner/**
    - tests/**
    - PROJECT_MASTER_TASKBOOK.md
    - PROJECT_MASTER_TASKBOOK.zh-CN.md
    - docs/taskbooks/stages/**
    - docs/taskbooks/versions/stage-00/VERSION_STAGE_00_V0_1_REPOSITORY_RUNTIME_REALITY_SNAPSHOT.md
    - docs/taskbooks/versions/stage-00/VERSION_STAGE_00_V0_2_VALIDATION_TRUTH_SOURCE_REPORT.md
    - docs/taskbooks/versions/stage-00/VERSION_STAGE_00_V0_3_RUNTIME_FRESHNESS_REPORT.md
    - docs/taskbooks/versions/stage-00/zh-CN/VERSION_STAGE_00_V0_1_REPOSITORY_RUNTIME_REALITY_SNAPSHOT.zh-CN.md
    - docs/taskbooks/versions/stage-00/zh-CN/VERSION_STAGE_00_V0_2_VALIDATION_TRUTH_SOURCE_REPORT.zh-CN.md
    - docs/taskbooks/versions/stage-00/zh-CN/VERSION_STAGE_00_V0_3_RUNTIME_FRESHNESS_REPORT.zh-CN.md
    - .colameta/plan.json
    - .colameta/runtime/**
    - .colameta/prompts/**
    - .git/**
    - "**/.env"
    - "**/*secret*"
    - "**/*credential*"
```

`.colameta/runtime/**` and `.colameta/state.json` are volatile observed runtime
metadata only. They must not be treated as delivery_state authority,
accepted-state authority, blocked-state authority, executor truth authority, or
permission to clean, rewrite, start, resume, or kill any executor/session state.

中文解释：未来真正执行时，最多只能写分类报告和中文报告。runtime/session 文件只能
只读观察，不能清理、不能重写、不能当权威。

---

## 5. Classification Vocabulary

```yaml id="classification-vocabulary"
classification_vocabulary:
  allowed_status_values:
    - none
    - active_operation_head_mismatch
    - completed_idle_stale_session
    - unknown_head_mismatch
  status_meanings:
    none: No mismatch, no session, or session HEAD matches current Git HEAD.
    active_operation_head_mismatch: A running or active operation has a recorded session HEAD different from current Git HEAD.
    completed_idle_stale_session: Historical completed idle session metadata records an older HEAD, but evidence indicates no active operation.
    unknown_head_mismatch: A mismatch exists but evidence is insufficient to classify active versus historical idle.
  forbidden_mappings:
    - completed_idle_stale_session_to_running_operation
    - completed_idle_stale_session_to_executor_authorized
    - active_operation_head_mismatch_to_auto_resume
    - unknown_head_mismatch_to_cleanup_permission
    - any_classification_to_delivery_state
```

中文解释：这里沿用 v1.10 的分类词，不重新发明状态。分类只是解释风险，不是授权。

---

## 6. Evidence Collection Scope

```yaml id="evidence-collection-scope"
evidence_collection_scope:
  git_context:
    - current_git_head
    - origin_main_head
    - ahead_behind_count
    - worktree_status
  session_context:
    - session_file_presence_or_known_unknown
    - session_recorded_head_or_known_unknown
    - session_matches_current_head_or_known_unknown
    - resume_warnings_or_known_unknown
    - risk_warnings_or_known_unknown
  operation_context:
    - operation_running_or_known_unknown
    - latest_run_state_or_known_unknown
    - runner_state_or_known_unknown
    - worktree_clean_or_known_unknown
  classification_context:
    - classification_status_or_known_unknown
    - classification_reason_or_known_unknown
    - operator_message_or_known_unknown
    - dangerous_actions_authorized_false
  known_unknowns:
    - unknown_name
    - why_unknown
    - what_would_resolve_it
```

---

## 7. Acceptance Commands

These commands are proposed for an explicitly authorized future execution of
this Version Taskbook. They are read-only probes and report-validation commands,
not executor-control commands.

```yaml id="acceptance-commands"
acceptance_commands:
  preflight_read_only:
    - git status --short --branch
    - git rev-parse HEAD
    - git rev-parse origin/main || true
    - git rev-list --left-right --count origin/main...HEAD || true
  session_inventory:
    - test -e .colameta/runtime/executor-session.json && sha256sum .colameta/runtime/executor-session.json || true
    - curl -fsS http://127.0.0.1:8801/api/status || true
    - rg -n "active_operation_head_mismatch|completed_idle_stale_session|unknown_head_mismatch|head_mismatch|executor_session_head_mismatch" runner/executor_session.py runner/web_console.py runner/web_console_presenter.py tests/test_executor_session_head_mismatch.py .colameta/prompts/v1.10.md
  taskbook_hash_checks:
    - sha256sum PROJECT_MASTER_TASKBOOK.md docs/taskbooks/stages/STAGE_00_BASELINE_CLOSEOUT.md docs/taskbooks/versions/stage-00/VERSION_STAGE_00_V0_1_REPOSITORY_RUNTIME_REALITY_SNAPSHOT.md docs/taskbooks/versions/stage-00/VERSION_STAGE_00_V0_2_VALIDATION_TRUTH_SOURCE_REPORT.md docs/taskbooks/versions/stage-00/VERSION_STAGE_00_V0_3_RUNTIME_FRESHNESS_REPORT.md
  report_validation:
    - git diff --check -- docs/taskbooks/versions/stage-00/evidence/VERSION_STAGE_00_V0_4_EXECUTOR_SESSION_HEAD_CLASSIFICATION_REPORT.md docs/taskbooks/versions/stage-00/evidence/zh-CN/VERSION_STAGE_00_V0_4_EXECUTOR_SESSION_HEAD_CLASSIFICATION_REPORT.zh-CN.md
    - rg -n "current_git_head|session_recorded_head_or_known_unknown|operation_running_or_known_unknown|classification_status_or_known_unknown|known_unknowns|not_validated|remaining_risks" docs/taskbooks/versions/stage-00/evidence/VERSION_STAGE_00_V0_4_EXECUTOR_SESSION_HEAD_CLASSIFICATION_REPORT.md
    - rg -n "source_document|source_sha256|classification_status_or_known_unknown|known_unknowns|not_validated|remaining_risks" docs/taskbooks/versions/stage-00/evidence/zh-CN/VERSION_STAGE_00_V0_4_EXECUTOR_SESSION_HEAD_CLASSIFICATION_REPORT.zh-CN.md
```

If the session file or status endpoint is unavailable, the report must record
`known_unknown` or `unavailable`; it must not create, clean, rewrite, or delete
session metadata.

If the local `origin/main` tracking ref is unavailable, the report must record
`known_unknown` for local tracking ref context; it must not auto-fetch or contact
the remote to fill the gap.

中文解释：这些命令只能观察。session 文件或接口不可用，就写 unknown/unavailable，
不能顺手清理或重写。
本地 `origin/main` 跟踪引用不可用时，也只能写 `known_unknown`，不能自动 `fetch`
或联系远端。

---

## 8. Manual Acceptance

```yaml id="manual-acceptance"
manual_acceptance:
  required_checks:
    - report separates current_git_head from session_recorded_head_or_known_unknown
    - report identifies classification_status_or_known_unknown using allowed vocabulary
    - report explains whether operation_running evidence exists or is unknown
    - report states that no session cleanup, executor start, executor resume, service restart, or runtime reload was performed
    - report states that no Delivery State Gate transition was applied
    - Chinese report companion explains technical terms in Chinese
  reviewer_must_not_accept_if:
    - report treats completed_idle_stale_session as active running operation
    - report treats unknown_head_mismatch as permission to clean or resume
    - report hides missing evidence
    - report mutates runtime/session files
    - report maps classification directly into delivery_state
```

---

## 9. Evidence Package Contract

```yaml id="evidence-package-contract"
evidence_package_contract:
  evidence_package_id: stage_00_v0_4_executor_session_head_classification_evidence
  schema_version: evidence_package.minimum.v1
  task_ref:
    taskbook_id: stage_00_v0_4_executor_session_head_classification_report
    task_id: executor_session_head_classification_report
    scope_ref: docs/taskbooks/versions/stage-00/VERSION_STAGE_00_V0_4_EXECUTOR_SESSION_HEAD_CLASSIFICATION_REPORT.md
  submission:
    submitted_by: codex_or_executor_after_separate_authorization
    submitted_summary_required: true
    requested_gate_action: request_acceptance_review
  state_context:
    delivery_state_seen: must_be_observed_context_only
    condition_flags_seen: must_be_observed_context_only
    state_version_seen: optional_if_no_state_store_is_available
  artifacts:
    required:
      - executor_session_head_classification_report
      - chinese_executor_session_head_classification_report_companion
      - session_or_known_unknown_summary
      - classification_boundary_summary
  checks:
    required:
      - git_head_check
      - session_inventory_or_known_unknown
      - classification_vocabulary_check
      - dangerous_action_non_authorization_check
      - report_schema_check
  not_validated: required_even_when_empty
  remaining_risks: required_even_when_empty
  authority_required:
    - Delivery State Gate before any delivery_state transition
    - Commander before any session cleanup, executor dispatch, restart, reload, further execution, commit, or push
```

---

## 10. Stop Conditions

```yaml id="stop-conditions"
stop_conditions:
  - repository_path_is_not_/home/jenn/src/colameta-dev
  - session_probe_requires_writing_or_cleaning_session_metadata
  - service_probe_requires_restart_reload_or_login
  - command_would_modify_runtime_or_repo_outside_allowed_output_paths
  - untracked_allowed_output_file_exists_and_was_not_created_by_current_authorized_execution
  - command_would_require_network_beyond_localhost_or_credentials
  - evidence_cannot_distinguish_active_operation_from_historical_idle_metadata
  - requested_action_would_expand_into_executor_start_resume_cleanup_or_runtime_reload
```

---

## 11. Out Of Scope

```yaml id="out-of-scope"
out_of_scope:
  - start executor
  - resume executor
  - kill executor
  - clean executor session
  - rewrite executor session
  - restart service
  - reload runtime code
  - modify /home/jenn/tools/colameta
  - run tests
  - modify runner code
  - modify tests
  - modify .colameta/plan.json
  - modify Master or Stage Taskbooks
  - repair classification implementation
  - classify delivery_state
  - emit GateEvent
  - commit
  - push
  - release or deploy
```

---

## 12. Reporting Destination

```yaml id="reporting-destination"
reporting_destination:
  primary_report: docs/taskbooks/versions/stage-00/evidence/VERSION_STAGE_00_V0_4_EXECUTOR_SESSION_HEAD_CLASSIFICATION_REPORT.md
  chinese_companion_report: docs/taskbooks/versions/stage-00/evidence/zh-CN/VERSION_STAGE_00_V0_4_EXECUTOR_SESSION_HEAD_CLASSIFICATION_REPORT.zh-CN.md
  required_report_status: generated_only_after_separate_execution_authorization
  report_authority: evidence_only_not_delivery_state
```

---

## 13. Forbidden Authority Claims

```yaml id="forbidden-authority-claims"
forbidden_authority_claims:
  - head_mismatch_means_active_operation
  - completed_idle_stale_session_means_executor_running
  - unknown_head_mismatch_means_cleanup_authorized
  - active_operation_head_mismatch_means_resume_authorized
  - classification_status_means_delivery_state
  - session_file_hash_means_execution_authorized
  - this_version_taskbook_authorizes_session_cleanup
  - this_version_taskbook_authorizes_executor_run
  - this_version_taskbook_authorizes_commit_or_push
```

---

## 14. Reviewer Packet Requirements

```yaml id="reviewer-packet-requirements"
reviewer_packet_requirements:
  must_include:
    - version_taskbook_path
    - version_taskbook_hash
    - master_taskbook_ref
    - stage_taskbook_ref
    - previous_version_taskbook_refs
    - executor_session_head_classification_report_ref
    - chinese_report_companion_ref
    - commands_run
    - commands_not_run
    - current_git_head
    - session_recorded_head_or_known_unknown
    - operation_running_or_known_unknown
    - classification_status_or_known_unknown
    - known_unknowns
    - remaining_risks
    - allowed_files_actual_touch_list
  must_exclude:
    - secrets
    - chain_of_thought
    - raw credential paths
    - unrelated logs
    - raw session file if it may contain sensitive metadata
```

---

## 15. Initial Commander Gate

```yaml id="initial-commander-gate"
initial_commander_gate:
  current_gate_status: taskbook_draft_created
  next_required_decision: review_or_revise_this_version_taskbook
  execution_requires_future_token: AUTHORIZE_STAGE_00_V0_4_EXECUTOR_SESSION_HEAD_CLASSIFICATION_REPORT_EXECUTION_FOR_EXACT_HASH_ONLY
  session_cleanup_requires_separate_authorization: true
  executor_dispatch_requires_separate_authorization: true
  commit_requires_separate_authorization: true
  push_requires_separate_authorization: true
```

中文解释：下一步只能审查或修改这份 Version Taskbook。真正执行 executor session
HEAD 分类报告，需要后续新的精确授权口令。
