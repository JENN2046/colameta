# Version Taskbook: Stage 0 / v0.5 Local Remote Baseline Report

```text id="version-stage-00-v0-5-boundary-banner"
VERSION TASKBOOK DRAFT ONLY.
This document defines a candidate Version Execution Taskbook for Stage 0. It
does not authorize execution, executor dispatch, code edits, test execution,
commit, push, fetch, pull, merge, rebase, remote write, route transition,
Delivery State Gate transition, or accepted delivery state.
```

```yaml id="version-taskbook-summary"
version_execution_taskbook:
  document_type: version_execution_taskbook
  schema_version: version_execution_taskbook.discussion_draft.v1
  version_id: stage_00_v0_5_local_remote_baseline_report
  version: v0.5
  name: Local Remote Baseline Report
  chinese_name: 本地与远端基线报告
  parent_stage_id: stage_00_baseline_closeout
  parent_stage_name: Baseline Closeout And Execution-State Clarity
  status: discussion_draft
  authority_status: planning_reference_only
  execution_authorization_status: not_authorized
  dispatch_status: not_authorized
  executor_run_authorized: false
  test_execution_authorized: false
  fetch_authorized: false
  push_authorized: false
  pull_authorized: false
  merge_authorized: false
  rebase_authorized: false
  remote_write_authorized: false
  route_transition_authorized: false
  created_from_head: c715c2c
  created_from_head_meaning: historical_creation_baseline_not_execution_or_freeze_snapshot
  created_from_head_subject: "docs: add executor session head classification version taskbook"
  origin_main_observed_from_local_tracking_ref: 018ff63
  remote_tracking_ref_meaning: locally_observed_origin_main_ref_not_live_remote_probe
  local_tracking_ref_sync_status_at_creation: local_ahead_remote_tracking_ref
  local_ahead_origin_main_at_creation: 4
```

`Local Remote Baseline Report` = 本地与远端基线报告。中文意思是：它把当前本地
分支、当前 HEAD、本地记录的 `origin/main`、ahead/behind、未提交文件和未 push
commit 分开说明，避免把“本地领先远端跟踪引用”误说成“远端已经同步”。

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
      raw_snapshot_sha256: 818727b598ecb11b6c2b6a61711b9cbe8bff48f98dc1448796f63cf370d94e6f
      version_id: stage_00_v0_1_repository_runtime_reality_snapshot
      status: local_baseline_commit_not_pushed_at_creation
    - path: docs/taskbooks/versions/stage-00/VERSION_STAGE_00_V0_2_VALIDATION_TRUTH_SOURCE_REPORT.md
      raw_snapshot_sha256: c2d903ce992e96f02a1672c61269a0a990cb8a163db7b8c56ccec4ccc68fcb26
      version_id: stage_00_v0_2_validation_truth_source_report
      status: local_baseline_commit_not_pushed_at_creation
    - path: docs/taskbooks/versions/stage-00/VERSION_STAGE_00_V0_3_RUNTIME_FRESHNESS_REPORT.md
      raw_snapshot_sha256: dd630e615929d04cb3921f3312aaa45718b44bd8ab72f5c17993dcf35b342e1f
      version_id: stage_00_v0_3_runtime_freshness_report
      status: local_baseline_commit_not_pushed_at_creation
    - path: docs/taskbooks/versions/stage-00/VERSION_STAGE_00_V0_4_EXECUTOR_SESSION_HEAD_CLASSIFICATION_REPORT.md
      raw_snapshot_sha256: e7efc8b3560c8e3476d5ebeb9bc44659e74a95c725911ee82eaa27a33643452c
      version_id: stage_00_v0_4_executor_session_head_classification_report
      status: local_baseline_commit_not_pushed_at_creation
  supports_project_goal: true
```

This Version Taskbook is subordinate to Stage 0. It may report local Git state
and the locally observed remote-tracking reference, but it must not perform
remote synchronization or treat a local remote-tracking ref as live remote truth.

中文解释：这份 Version 只报告本地 Git 现实和本地 `origin/main` 引用。它不能
`fetch`，不能 `push`，也不能说“远端实时状态已经验证”。

---

## 2. Task Goal

```yaml id="task-goal"
task_goal:
  primary_goal: >
    Produce a bounded Local Remote Baseline Report that records current branch,
    current local HEAD, locally observed origin/main ref, ahead/behind counts,
    worktree status, staged status, untracked-file status, unpushed commit
    summary, and known unknowns without performing fetch, pull, push, merge,
    rebase, or any remote action.
  minimum_readiness_claim: >
    Local repository state and local remote-tracking-ref state are separated
    clearly enough that later governance work can distinguish local commits,
    unpushed commits, clean or dirty worktree state, and unverified live remote
    freshness.
  gate_question: >
    Can a reviewer tell exactly what is local, what is only the local
    origin/main tracking ref, what is ahead or behind, and what remains
    unknown because no fetch or remote probe was authorized?
  explicit_non_goal: >
    This version is not remote synchronization, fetch, push, pull, merge,
    rebase, release, deployment, branch management, or delivery-state
    acceptance.
```

`origin/main local tracking ref` = 本地远端跟踪引用。中文意思是：本地 Git 里记录的
`origin/main` 指针，不等于刚刚联网确认过的远端最新状态。

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
    previous_v0_1_taskbook_hash: 818727b598ecb11b6c2b6a61711b9cbe8bff48f98dc1448796f63cf370d94e6f
    previous_v0_2_taskbook_hash: c2d903ce992e96f02a1672c61269a0a990cb8a163db7b8c56ccec4ccc68fcb26
    previous_v0_3_taskbook_hash: dd630e615929d04cb3921f3312aaa45718b44bd8ab72f5c17993dcf35b342e1f
    previous_v0_4_taskbook_hash: e7efc8b3560c8e3476d5ebeb9bc44659e74a95c725911ee82eaa27a33643452c
  task_goal_ref: task_goal.primary_goal
  definition_of_good:
    - report records current_branch and current_local_head separately
    - report records origin_main_local_tracking_ref separately from live_remote_status
    - report records ahead_count and behind_count from local refs
    - report records worktree, staged, and untracked states
    - report lists unpushed commits or known_unknown
    - report states that no fetch, pull, push, merge, rebase, or remote write was performed
  allowed_autonomy_after_explicit_authorization:
    - local read-only git inspection
    - local report file creation under allowed output paths
    - narrow report correction if validation finds missing required fields
```

`ahead_count` = 本地领先数量。中文意思是：当前本地分支相对本地 `origin/main`
引用多出来的 commit 数量，不代表远端已经收到了这些 commit。

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
    - docs/taskbooks/versions/stage-00/VERSION_STAGE_00_V0_4_EXECUTOR_SESSION_HEAD_CLASSIFICATION_REPORT.md
    - docs/taskbooks/versions/stage-00/zh-CN/VERSION_STAGE_00_V0_1_REPOSITORY_RUNTIME_REALITY_SNAPSHOT.zh-CN.md
    - docs/taskbooks/versions/stage-00/zh-CN/VERSION_STAGE_00_V0_2_VALIDATION_TRUTH_SOURCE_REPORT.zh-CN.md
    - docs/taskbooks/versions/stage-00/zh-CN/VERSION_STAGE_00_V0_3_RUNTIME_FRESHNESS_REPORT.zh-CN.md
    - docs/taskbooks/versions/stage-00/zh-CN/VERSION_STAGE_00_V0_4_EXECUTOR_SESSION_HEAD_CLASSIFICATION_REPORT.zh-CN.md
    - docs/taskbooks/CHINESE_COMPANION_POLICY.md
    - docs/taskbooks/CHINESE_COMPANION_INDEX.md
  writable_after_separate_execution_authorization:
    - docs/taskbooks/versions/stage-00/evidence/VERSION_STAGE_00_V0_5_LOCAL_REMOTE_BASELINE_REPORT.md
    - docs/taskbooks/versions/stage-00/evidence/zh-CN/VERSION_STAGE_00_V0_5_LOCAL_REMOTE_BASELINE_REPORT.zh-CN.md

allowed_observations:
  - git_metadata_via_non_mutating_git_commands_only

allowed_mutations:
  - create_or_update_declared_local_remote_baseline_report_only_after_explicit_execution_authorization
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
    - docs/taskbooks/versions/stage-00/VERSION_STAGE_00_V0_4_EXECUTOR_SESSION_HEAD_CLASSIFICATION_REPORT.md
    - docs/taskbooks/versions/stage-00/zh-CN/VERSION_STAGE_00_V0_1_REPOSITORY_RUNTIME_REALITY_SNAPSHOT.zh-CN.md
    - docs/taskbooks/versions/stage-00/zh-CN/VERSION_STAGE_00_V0_2_VALIDATION_TRUTH_SOURCE_REPORT.zh-CN.md
    - docs/taskbooks/versions/stage-00/zh-CN/VERSION_STAGE_00_V0_3_RUNTIME_FRESHNESS_REPORT.zh-CN.md
    - docs/taskbooks/versions/stage-00/zh-CN/VERSION_STAGE_00_V0_4_EXECUTOR_SESSION_HEAD_CLASSIFICATION_REPORT.zh-CN.md
    - .colameta/**
    - .git/**
    - "**/.env"
    - "**/*secret*"
    - "**/*credential*"
```

Git metadata may be observed only through non-mutating Git commands. This
Version must not edit `.git`, create commits, move branches, update refs, fetch,
pull, push, merge, or rebase.

中文解释：可以用只读 Git 命令看状态，但不能改 `.git`，不能移动分支，不能同步远端。

---

## 5. Remote-Tracking Boundary

```yaml id="remote-tracking-boundary"
remote_tracking_boundary:
  origin_main_meaning: locally_observed_remote_tracking_ref
  live_remote_status: not_validated_without_separate_fetch_or_remote_probe_authorization
  fetch_status: not_authorized
  push_status: not_authorized
  report_must_say:
    - origin_main_is_local_tracking_ref
    - ahead_behind_counts_are_based_on_local_refs
    - live_remote_freshness_is_not_validated
    - no_remote_sync_was_performed
  forbidden_claims:
    - origin_main_is_live_remote_truth
    - ahead_zero_means_remote_fresh_without_fetch
    - local_ahead_commits_are_pushed
    - report_authorizes_push
```

中文解释：`origin/main` 只能说是“本地记录的远端跟踪引用”。如果没有单独授权
`fetch` 或远端探测，就不能说它是远端此刻最新状态。

---

## 6. Evidence Collection Scope

```yaml id="evidence-collection-scope"
evidence_collection_scope:
  branch_context:
    - current_branch
    - upstream_branch_or_known_unknown
  head_context:
    - current_local_head
    - current_local_head_subject
    - origin_main_local_tracking_ref
    - origin_main_subject_if_available
  divergence_context:
    - ahead_count_from_local_refs
    - behind_count_from_local_refs
    - unpushed_commit_subjects_or_known_unknown
  worktree_context:
    - worktree_short_status
    - staged_changes_or_none
    - unstaged_changes_or_none
    - untracked_files_or_none
  remote_freshness_context:
    - fetch_performed_false
    - live_remote_status_not_validated
    - what_would_resolve_live_remote_unknown
  known_unknowns:
    - unknown_name
    - why_unknown
    - what_would_resolve_it
```

---

## 7. Acceptance Commands

These commands are proposed for an explicitly authorized future execution of
this Version Taskbook. They are local read-only Git probes and report-validation
commands, not synchronization commands.

```yaml id="acceptance-commands"
acceptance_commands:
  preflight_read_only:
    - git status --short --branch
    - git rev-parse --abbrev-ref HEAD
    - git rev-parse HEAD
    - git rev-parse --verify origin/main || true
    - git rev-list --left-right --count origin/main...HEAD || true
  local_commit_inventory:
    - git log --oneline --decorate --max-count=20 origin/main..HEAD || true
    - git log --oneline --decorate --max-count=5 HEAD
  worktree_inventory:
    - git diff --name-status
    - git diff --cached --name-status
    - git ls-files --others --exclude-standard
  taskbook_hash_checks:
    - sha256sum PROJECT_MASTER_TASKBOOK.md docs/taskbooks/stages/STAGE_00_BASELINE_CLOSEOUT.md docs/taskbooks/versions/stage-00/VERSION_STAGE_00_V0_1_REPOSITORY_RUNTIME_REALITY_SNAPSHOT.md docs/taskbooks/versions/stage-00/VERSION_STAGE_00_V0_2_VALIDATION_TRUTH_SOURCE_REPORT.md docs/taskbooks/versions/stage-00/VERSION_STAGE_00_V0_3_RUNTIME_FRESHNESS_REPORT.md docs/taskbooks/versions/stage-00/VERSION_STAGE_00_V0_4_EXECUTOR_SESSION_HEAD_CLASSIFICATION_REPORT.md
  report_validation:
    - git diff --check -- docs/taskbooks/versions/stage-00/evidence/VERSION_STAGE_00_V0_5_LOCAL_REMOTE_BASELINE_REPORT.md docs/taskbooks/versions/stage-00/evidence/zh-CN/VERSION_STAGE_00_V0_5_LOCAL_REMOTE_BASELINE_REPORT.zh-CN.md
    - rg -n "current_branch|current_local_head|origin_main_local_tracking_ref|ahead_count_from_local_refs|behind_count_from_local_refs|live_remote_status_not_validated|known_unknowns|not_validated|remaining_risks" docs/taskbooks/versions/stage-00/evidence/VERSION_STAGE_00_V0_5_LOCAL_REMOTE_BASELINE_REPORT.md
    - rg -n "source_document|source_sha256|origin_main_local_tracking_ref|live_remote_status_not_validated|known_unknowns|not_validated|remaining_risks" docs/taskbooks/versions/stage-00/evidence/zh-CN/VERSION_STAGE_00_V0_5_LOCAL_REMOTE_BASELINE_REPORT.zh-CN.md
```

`git fetch`, `git pull`, `git push`, `git merge`, and `git rebase` are
intentionally absent. If live remote freshness is needed, that requires a
separate Commander authorization and a separate report boundary.

If the local `origin/main` tracking ref is unavailable, the report must record
`known_unknown` for origin/main, ahead/behind counts, and unpushed commit
inventory; it must not auto-fetch or contact the remote to fill the gap.

中文解释：验收命令只能看本地 Git 状态。没有 `fetch`，所以报告必须承认远端实时
新鲜度没有验证。

---

## 8. Manual Acceptance

```yaml id="manual-acceptance"
manual_acceptance:
  required_checks:
    - report separates current_local_head from origin_main_local_tracking_ref
    - report explains that origin/main is a local tracking ref unless fetch is separately authorized
    - report records ahead_count_from_local_refs and behind_count_from_local_refs
    - report records worktree, staged, and untracked state
    - report lists unpushed commits or explains why unknown
    - report states that no fetch, pull, push, merge, rebase, or remote write was performed
    - report states that no Delivery State Gate transition was applied
    - Chinese report companion explains technical terms in Chinese
  reviewer_must_not_accept_if:
    - report claims live remote freshness without authorized fetch or remote probe
    - report treats local ahead commits as pushed
    - report hides dirty worktree or untracked files
    - report performs or implies remote synchronization
    - report maps local_remote_sync_status directly into delivery_state
```

---

## 9. Evidence Package Contract

```yaml id="evidence-package-contract"
evidence_package_contract:
  evidence_package_id: stage_00_v0_5_local_remote_baseline_evidence
  schema_version: evidence_package.minimum.v1
  task_ref:
    taskbook_id: stage_00_v0_5_local_remote_baseline_report
    task_id: local_remote_baseline_report
    scope_ref: docs/taskbooks/versions/stage-00/VERSION_STAGE_00_V0_5_LOCAL_REMOTE_BASELINE_REPORT.md
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
      - local_remote_baseline_report
      - chinese_local_remote_baseline_report_companion
      - local_head_summary
      - local_remote_tracking_ref_summary
      - worktree_status_summary
  checks:
    required:
      - branch_head_check
      - local_remote_tracking_ref_check
      - ahead_behind_check_from_local_refs
      - worktree_inventory_check
      - no_remote_action_check
      - report_schema_check
  not_validated: required_even_when_empty
  remaining_risks: required_even_when_empty
  authority_required:
    - Delivery State Gate before any delivery_state transition
    - Commander before any fetch, pull, push, merge, rebase, route transition, further execution, commit, or remote action
```

---

## 10. Stop Conditions

```yaml id="stop-conditions"
stop_conditions:
  - repository_path_is_not_/home/jenn/src/colameta-dev
  - command_would_fetch_pull_push_merge_rebase_or_update_refs
  - command_would_contact_remote_without_separate_authorization
  - command_would_modify_git_metadata
  - command_would_modify_runtime_or_repo_outside_allowed_output_paths
  - untracked_allowed_output_file_exists_and_was_not_created_by_current_authorized_execution
  - command_would_require_credentials_or_remote_url_disclosure
  - evidence_cannot_distinguish_local_ref_from_live_remote_truth
  - requested_action_would_expand_into_push_release_deploy_or_route_transition
```

---

## 11. Out Of Scope

```yaml id="out-of-scope"
out_of_scope:
  - git fetch
  - git pull
  - git push
  - git merge
  - git rebase
  - branch creation
  - branch deletion
  - tag creation
  - release or deploy
  - remote write
  - executor dispatch
  - service restart
  - runtime reload
  - code mutation
  - modify /home/jenn/tools/colameta
  - modify runner code
  - modify tests
  - modify .colameta files
  - classify delivery_state
  - emit GateEvent
  - commit
  - route transition
```

---

## 12. Reporting Destination

```yaml id="reporting-destination"
reporting_destination:
  primary_report: docs/taskbooks/versions/stage-00/evidence/VERSION_STAGE_00_V0_5_LOCAL_REMOTE_BASELINE_REPORT.md
  chinese_companion_report: docs/taskbooks/versions/stage-00/evidence/zh-CN/VERSION_STAGE_00_V0_5_LOCAL_REMOTE_BASELINE_REPORT.zh-CN.md
  required_report_status: generated_only_after_separate_execution_authorization
  report_authority: evidence_only_not_delivery_state
```

---

## 13. Forbidden Authority Claims

```yaml id="forbidden-authority-claims"
forbidden_authority_claims:
  - origin_main_local_tracking_ref_means_live_remote_fresh
  - ahead_zero_means_remote_verified_without_fetch
  - local_ahead_commit_means_pushed
  - clean_worktree_means_delivery_accepted
  - local_remote_report_authorizes_push
  - this_version_taskbook_authorizes_fetch
  - this_version_taskbook_authorizes_pull_or_push
  - this_version_taskbook_authorizes_commit_or_route_transition
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
    - local_remote_baseline_report_ref
    - chinese_report_companion_ref
    - commands_run
    - commands_not_run
    - current_branch
    - current_local_head
    - origin_main_local_tracking_ref
    - ahead_count_from_local_refs
    - behind_count_from_local_refs
    - worktree_status
    - unpushed_commits_or_known_unknown
    - live_remote_status_not_validated
    - known_unknowns
    - remaining_risks
    - allowed_files_actual_touch_list
  must_exclude:
    - secrets
    - chain_of_thought
    - credential-bearing remote URLs
    - raw credential paths
    - unrelated logs
```

---

## 15. Initial Commander Gate

```yaml id="initial-commander-gate"
initial_commander_gate:
  current_gate_status: taskbook_draft_created
  next_required_decision: review_or_revise_this_version_taskbook
  execution_requires_future_token: AUTHORIZE_STAGE_00_V0_5_LOCAL_REMOTE_BASELINE_REPORT_EXECUTION_FOR_EXACT_HASH_ONLY
  fetch_requires_separate_authorization: true
  push_requires_separate_authorization: true
  commit_requires_separate_authorization: true
  route_transition_requires_separate_authorization: true
```

中文解释：下一步只能审查或修改这份 Version Taskbook。真正执行本地与远端基线
报告，需要后续新的精确授权口令；`fetch` 和 `push` 都不是这份草稿授权的事。
