# Version Taskbook: Stage 0 / v0.1 Repository And Runtime Reality Snapshot

```text id="version-stage-00-v0-1-boundary-banner"
VERSION TASKBOOK DRAFT ONLY.
This document defines a candidate Version Execution Taskbook for Stage 0. It
does not authorize execution, executor dispatch, code edits, commit, push,
runtime restart, route transition, Delivery State Gate transition, or accepted
delivery state.
```

```yaml id="version-taskbook-summary"
version_execution_taskbook:
  document_type: version_execution_taskbook
  schema_version: version_execution_taskbook.discussion_draft.v1
  version_id: stage_00_v0_1_repository_runtime_reality_snapshot
  version: v0.1
  name: Repository And Runtime Reality Snapshot
  chinese_name: 仓库与运行态现实快照
  parent_stage_id: stage_00_baseline_closeout
  parent_stage_name: Baseline Closeout And Execution-State Clarity
  status: discussion_draft
  authority_status: planning_reference_only
  execution_authorization_status: not_authorized
  dispatch_status: not_authorized
  executor_run_authorized: false
  created_from_head: 018ff63
  created_from_head_meaning: historical_creation_baseline_not_execution_or_freeze_snapshot
  created_from_head_subject: "docs: record stage freeze confirmation"
  origin_main_observed: 018ff63
  remote_sync_status_at_creation: synced
```

`Version Execution Taskbook` = 版本执行任务书。中文意思是：它把某个 Stage
下面的一次小交付切成可验证、可审查、可授权的执行边界。

`Repository And Runtime Reality Snapshot` = 仓库与运行态现实快照。中文意思是：
只把当前仓库、远端、运行服务、executor session、验证事实和已知未知项说清楚，
不顺手修东西。

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
  supports_project_goal: true
```

This Version Taskbook is subordinate to Stage 0. If it conflicts with the
Master or Stage 0 Taskbook, the conflict must be treated as a taskbook defect,
not as authority to reinterpret the parent documents.

中文解释：这份 Version 只能服务 Stage 0，不能反过来改写 Master 或 Stage 0。

---

## 2. Task Goal

```yaml id="task-goal"
task_goal:
  primary_goal: >
    Produce a bounded, read-only Repository And Runtime Reality Snapshot report
    that records the current repository state, remote sync state, worktree
    state, stable runtime path, service status evidence, executor-session
    freshness evidence, validation truth-source evidence, and known unknowns.
  minimum_readiness_claim: >
    The repository and runtime baseline is observable enough to support later
    governed claims without relying on stale session memory or summary labels.
  gate_question: >
    Can later Stage 0 and Stage 1 claims start from a declared, evidence-backed
    repository/runtime baseline?
  explicit_non_goal: >
    This version is not code hardening, runtime cleanup, executor dispatch,
    dashboard work, route transition, or delivery-state acceptance.
```

中文解释：这一步的目标是“看清楚并写下来”，不是“修好一切”。

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
  task_goal_ref: task_goal.primary_goal
  definition_of_good:
    - snapshot report exists at the declared reporting destination
    - report records command evidence and limitations
    - report separates observed facts from inferred status
    - report records known_unknowns explicitly
    - report does not mutate code, plan, runtime, or delivery state
  allowed_autonomy_after_explicit_authorization:
    - local read-only inspection
    - local report file creation under allowed output paths
    - narrow report correction if validation finds missing required fields
```

`Execution Envelope` = 执行信封。中文意思是：真正执行前必须有一封“边界信”，
写清楚能读什么、能写什么、不能做什么、怎么验证。这里还不是授权。

---

## 4. Allowed Files And Mutations

```yaml id="allowed-files-and-mutations"
allowed_files:
  read_only:
    - PROJECT_MASTER_TASKBOOK.md
    - PROJECT_MASTER_TASKBOOK.zh-CN.md
    - FREEZE_CANDIDATE_REVIEW_PACKET.md
    - FREEZE_CANDIDATE_REVIEW_PACKET.zh-CN.md
    - docs/taskbooks/stages/README.md
    - docs/taskbooks/stages/STAGE_00_BASELINE_CLOSEOUT.md
    - docs/taskbooks/stages/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_0_6.md
    - docs/taskbooks/stages/zh-CN/STAGE_00_BASELINE_CLOSEOUT.zh-CN.md
    - docs/taskbooks/stages/zh-CN/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_0_6.zh-CN.md
    - docs/taskbooks/CHINESE_COMPANION_POLICY.md
    - docs/taskbooks/CHINESE_COMPANION_INDEX.md
    - .colameta/plan.json
    - .colameta/plan.zh-CN.md
    - .colameta/state.json
    - runner/**
    - tests/**
  writable_after_separate_execution_authorization:
    - docs/taskbooks/versions/stage-00/evidence/VERSION_STAGE_00_V0_1_REALITY_SNAPSHOT_REPORT.md
    - docs/taskbooks/versions/stage-00/evidence/zh-CN/VERSION_STAGE_00_V0_1_REALITY_SNAPSHOT_REPORT.zh-CN.md

allowed_mutations:
  - create_or_update_declared_snapshot_report_only_after_explicit_execution_authorization
  - create_or_update_declared_chinese_report_companion_only_after_explicit_execution_authorization

forbidden_files:
  mutation_targets:
    - /home/jenn/tools/colameta/**
    - runner/**
    - tests/**
    - PROJECT_MASTER_TASKBOOK.md
    - PROJECT_MASTER_TASKBOOK.zh-CN.md
    - docs/taskbooks/stages/**
    - .colameta/plan.json
    - .colameta/prompts/**
    - .git/**
    - "**/.env"
    - "**/*secret*"
    - "**/*credential*"
```

The `runner/**` and `tests/**` paths are read-only evidence sources for this
version and forbidden mutation targets.

`.colameta/state.json` is volatile observed runtime metadata only. It must not
be treated as delivery_state authority, accepted-state authority, blocked-state
authority, executor truth authority, or a substitute for live repository and
runtime evidence.

中文解释：未来真正执行时，最多只能写快照报告和中文报告，不能改代码、不能改
Stage、不能改 Master、不能改稳定工具目录。

---

## 5. Evidence Collection Scope

```yaml id="evidence-collection-scope"
evidence_collection_scope:
  repository:
    - current_branch
    - current_head
    - origin_main_head
    - ahead_behind_count
    - worktree_status
    - untracked_files
    - latest_commit_subject
  taskbook_refs:
    - master_taskbook_hash
    - stage_00_taskbook_hash
    - stage_0_6_freeze_packet_hash
    - this_version_taskbook_hash_if_known
  stable_runtime:
    - stable_service_runtime_path
    - stable_cli_path
    - whether_cli_path_exists
    - service_status_endpoint_result_or_unavailable_reason
  runtime_truth:
    - loaded_code_freshness_status_or_known_unknown
    - executor_session_head_match_status_or_known_unknown
    - current_operation_status_or_known_unknown
  validation_truth:
    - validation_commands_available
    - validation_summary_source
    - validation_not_run_reason_if_not_run
  known_unknowns:
    - unknown_name
    - why_unknown
    - what_would_resolve_it
```

---

## 6. Acceptance Commands

These commands are the proposed local checks for an explicitly authorized
future execution of this Version Taskbook. They are not authorized by this
document alone.

```yaml id="acceptance-commands"
acceptance_commands:
  preflight_read_only:
    - git status --short --branch
    - git rev-parse HEAD
    - git rev-parse origin/main
    - git rev-list --left-right --count origin/main...HEAD
    - test -x /home/jenn/tools/colameta/.venv/bin/colameta
  evidence_probes:
    - git log -1 --oneline
    - git diff --name-status
    - sha256sum PROJECT_MASTER_TASKBOOK.md docs/taskbooks/stages/STAGE_00_BASELINE_CLOSEOUT.md
    - curl -fsS http://127.0.0.1:8801/api/status
  report_validation:
    - git diff --check -- docs/taskbooks/versions/stage-00/evidence/VERSION_STAGE_00_V0_1_REALITY_SNAPSHOT_REPORT.md docs/taskbooks/versions/stage-00/evidence/zh-CN/VERSION_STAGE_00_V0_1_REALITY_SNAPSHOT_REPORT.zh-CN.md
    - rg -n "known_unknowns|not_validated|remaining_risks|commands_run" docs/taskbooks/versions/stage-00/evidence/VERSION_STAGE_00_V0_1_REALITY_SNAPSHOT_REPORT.md
    - rg -n "source_document|source_sha256|known_unknowns|not_validated|remaining_risks" docs/taskbooks/versions/stage-00/evidence/zh-CN/VERSION_STAGE_00_V0_1_REALITY_SNAPSHOT_REPORT.zh-CN.md
```

`curl -fsS http://127.0.0.1:8801/api/status` may fail if the local service is
down. That failure should be recorded as evidence or a known unknown; it must
not be converted into a fake pass.

中文解释：这些命令是未来执行时的候选验收命令。现在写在任务书里，不代表已经
执行，也不代表已经授权。

---

## 7. Manual Acceptance

```yaml id="manual-acceptance"
manual_acceptance:
  required_checks:
    - report clearly separates observed facts from inferred labels
    - report includes known_unknowns even when empty
    - report states whether runtime status came from live endpoint, local files, or was unavailable
    - report states that no Delivery State Gate transition was applied
    - Chinese report companion explains technical terms in Chinese
  reviewer_must_not_accept_if:
    - report hides service unavailability
    - report maps PASSED, COMPLETED, or BLOCKED directly into delivery_state
    - report omits command evidence
    - report mutates files outside allowed output paths
```

---

## 8. Evidence Package Contract

```yaml id="evidence-package-contract"
evidence_package_contract:
  evidence_package_id: stage_00_v0_1_reality_snapshot_evidence
  schema_version: evidence_package.minimum.v1
  task_ref:
    taskbook_id: stage_00_v0_1_repository_runtime_reality_snapshot
    task_id: repository_runtime_reality_snapshot
    scope_ref: docs/taskbooks/versions/stage-00/VERSION_STAGE_00_V0_1_REPOSITORY_RUNTIME_REALITY_SNAPSHOT.md
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
      - snapshot_report
      - chinese_snapshot_report_companion
      - command_evidence_summary
  checks:
    required:
      - git_status_check
      - git_sync_check
      - taskbook_hash_check
      - runtime_status_probe_or_known_unknown
      - report_schema_check
  not_validated: required_even_when_empty
  remaining_risks: required_even_when_empty
  authority_required:
    - Delivery State Gate before any delivery_state transition
    - Commander before any further execution or push
```

`Evidence Package` = 证据包。中文意思是：把“做了什么、看到了什么、没验证什么、
还有什么风险”收起来给审查，不等于批准。

---

## 9. Stop Conditions

```yaml id="stop-conditions"
stop_conditions:
  - repository_path_is_not_/home/jenn/src/colameta-dev
  - stable_runtime_path_probe_would_require_mutation
  - command_would_modify_runtime_or_repo_outside_allowed_output_paths
  - untracked_allowed_output_file_exists_and_was_not_created_by_current_authorized_execution
  - service_status_probe_requires_restart_or_login
  - git_remote_probe_requires_credential_exposure
  - evidence_cannot_distinguish_observed_fact_from_summary_label
  - requested_action_would_expand_into_code_hardening_or_cleanup
```

---

## 10. Out Of Scope

```yaml id="out-of-scope"
out_of_scope:
  - modify runner code
  - modify tests
  - modify .colameta/plan.json
  - modify Master or Stage Taskbooks
  - modify /home/jenn/tools/colameta
  - restart service
  - run executor
  - clean stale sessions automatically
  - classify delivery_state
  - emit GateEvent
  - commit
  - push
  - release or deploy
```

---

## 11. Reporting Destination

```yaml id="reporting-destination"
reporting_destination:
  primary_report: docs/taskbooks/versions/stage-00/evidence/VERSION_STAGE_00_V0_1_REALITY_SNAPSHOT_REPORT.md
  chinese_companion_report: docs/taskbooks/versions/stage-00/evidence/zh-CN/VERSION_STAGE_00_V0_1_REALITY_SNAPSHOT_REPORT.zh-CN.md
  required_report_status: generated_only_after_separate_execution_authorization
  report_authority: evidence_only_not_delivery_state
```

---

## 12. Forbidden Authority Claims

```yaml id="forbidden-authority-claims"
forbidden_authority_claims:
  - snapshot_report_means_delivery_state_accepted
  - runtime_status_label_means_delivery_state
  - validation_passed_means_commander_accepted
  - ReviewDecision_ACCEPT_means_GateEvent_accepted
  - hash_match_means_execution_authorized
  - this_version_taskbook_authorizes_executor_run
  - this_version_taskbook_authorizes_commit_or_push
```

---

## 13. Reviewer Packet Requirements

```yaml id="reviewer-packet-requirements"
reviewer_packet_requirements:
  must_include:
    - version_taskbook_path
    - version_taskbook_hash
    - master_taskbook_ref
    - stage_taskbook_ref
    - snapshot_report_ref
    - chinese_report_companion_ref
    - commands_run
    - commands_not_run
    - known_unknowns
    - remaining_risks
    - allowed_files_actual_touch_list
  must_exclude:
    - secrets
    - chain_of_thought
    - raw credential paths
    - unrelated logs
```

---

## 14. Initial Commander Gate

```yaml id="initial-commander-gate"
initial_commander_gate:
  current_gate_status: taskbook_draft_created
  next_required_decision: review_or_revise_this_version_taskbook
  execution_requires_future_token: AUTHORIZE_STAGE_00_V0_1_REALITY_SNAPSHOT_EXECUTION_FOR_EXACT_HASH_ONLY
  commit_requires_separate_authorization: true
  push_requires_separate_authorization: true
```

中文解释：下一步只能审查或修改这份 Version Taskbook。真正执行快照，需要后续新的
精确授权口令。
