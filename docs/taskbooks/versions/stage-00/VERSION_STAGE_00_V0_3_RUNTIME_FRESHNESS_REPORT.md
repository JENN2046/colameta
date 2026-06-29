# Version Taskbook: Stage 0 / v0.3 Runtime Freshness Report

```text id="version-stage-00-v0-3-boundary-banner"
VERSION TASKBOOK DRAFT ONLY.
This document defines a candidate Version Execution Taskbook for Stage 0. It
does not authorize execution, executor dispatch, code edits, test execution,
commit, push, service restart, runtime reload, route transition, Delivery State
Gate transition, or accepted delivery state.
```

```yaml id="version-taskbook-summary"
version_execution_taskbook:
  document_type: version_execution_taskbook
  schema_version: version_execution_taskbook.discussion_draft.v1
  version_id: stage_00_v0_3_runtime_freshness_report
  version: v0.3
  name: Runtime Freshness Report
  chinese_name: 运行时代码新鲜度报告
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
  created_from_head: da3910e
  created_from_head_meaning: historical_creation_baseline_not_execution_or_freeze_snapshot
  created_from_head_subject: "docs: add validation truth source version taskbook"
  origin_main_observed: 018ff63
  remote_sync_status_at_creation: local_ahead_remote
  local_ahead_origin_main_at_creation: 2
```

`Runtime Freshness Report` = 运行时代码新鲜度报告。中文意思是：它说明当前正在
运行的 ColaMeta 服务是否能被解释为来自稳定运行目录、是否与自进化 repo 的期望
版本或 HEAD 关系清楚，以及哪些新鲜度问题仍然未知。

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
  supports_project_goal: true
```

This Version Taskbook is subordinate to Stage 0. It may clarify runtime
freshness evidence boundaries, but it must not restart services, reload code,
modify the stable tool installation, or reinterpret runtime labels as delivery
state.

中文解释：这份 Version 只说明“当前运行的服务是不是新鲜、来源是否清楚”，不能
重启服务、不能 reload、不能改 `/home/jenn/tools/colameta`。

---

## 2. Task Goal

```yaml id="task-goal"
task_goal:
  primary_goal: >
    Produce a bounded Runtime Freshness Report that records the stable service
    runtime path, stable CLI path, observed service endpoint status, loaded-code
    freshness signal if available, process evidence if available, relationship
    to the self-development repository HEAD, and known unknowns.
  minimum_readiness_claim: >
    Runtime status is explainable enough that later governance work can
    distinguish a current loaded service, a stale loaded service, an unavailable
    service, and an unknown service state.
  gate_question: >
    Can a reviewer tell whether the running service is current, stale,
    unavailable, or unknown without relying on chat memory or summary labels?
  explicit_non_goal: >
    This version is not service restart, runtime reload, code deployment,
    package installation, process management, executor dispatch, or
    delivery-state acceptance.
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
    previous_v0_1_taskbook_hash: 818727b598ecb11b6c2b6a61711b9cbe8bff48f98dc1448796f63cf370d94e6f
    previous_v0_2_taskbook_hash: c2d903ce992e96f02a1672c61269a0a990cb8a163db7b8c56ccec4ccc68fcb26
  task_goal_ref: task_goal.primary_goal
  definition_of_good:
    - runtime freshness report exists at the declared reporting destination
    - report distinguishes stable tool runtime path from self-development repo path
    - report records endpoint status or unavailable reason
    - report records loaded-code freshness signal or known_unknown
    - report records process evidence or known_unknown
    - report does not restart, reload, deploy, or mutate runtime files
  allowed_autonomy_after_explicit_authorization:
    - local read-only inspection
    - local HTTP status probe against localhost status endpoint
    - local process listing inspection
    - local report file creation under allowed output paths
    - narrow report correction if validation finds missing required fields
```

`Loaded-code freshness` = 已加载代码新鲜度。中文意思是：运行中的服务到底加载了
哪份代码、是否和我们当前期望的 repo/commit/版本相符，必须能被解释。

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
    - docs/taskbooks/versions/stage-00/zh-CN/VERSION_STAGE_00_V0_1_REPOSITORY_RUNTIME_REALITY_SNAPSHOT.zh-CN.md
    - docs/taskbooks/versions/stage-00/zh-CN/VERSION_STAGE_00_V0_2_VALIDATION_TRUTH_SOURCE_REPORT.zh-CN.md
    - docs/taskbooks/CHINESE_COMPANION_POLICY.md
    - docs/taskbooks/CHINESE_COMPANION_INDEX.md
    - .colameta/plan.json
    - .colameta/plan.zh-CN.md
    - .colameta/state.json
    - runner/**
    - tests/**
    - /home/jenn/tools/colameta/.venv/bin/colameta
  writable_after_separate_execution_authorization:
    - docs/taskbooks/versions/stage-00/evidence/VERSION_STAGE_00_V0_3_RUNTIME_FRESHNESS_REPORT.md
    - docs/taskbooks/versions/stage-00/evidence/zh-CN/VERSION_STAGE_00_V0_3_RUNTIME_FRESHNESS_REPORT.zh-CN.md

allowed_mutations:
  - create_or_update_declared_runtime_freshness_report_only_after_explicit_execution_authorization
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
    - docs/taskbooks/versions/stage-00/zh-CN/VERSION_STAGE_00_V0_1_REPOSITORY_RUNTIME_REALITY_SNAPSHOT.zh-CN.md
    - docs/taskbooks/versions/stage-00/zh-CN/VERSION_STAGE_00_V0_2_VALIDATION_TRUTH_SOURCE_REPORT.zh-CN.md
    - .colameta/plan.json
    - .colameta/prompts/**
    - .git/**
    - "**/.env"
    - "**/*secret*"
    - "**/*credential*"
```

The stable runtime directory `/home/jenn/tools/colameta` may be observed only
through explicit read-only checks. It must not be modified, reinstalled,
reloaded, restarted, or used as a place to write evidence.

`.colameta/state.json` is volatile observed runtime metadata only. It must not
be treated as runtime freshness authority, delivery_state authority,
accepted-state authority, blocked-state authority, executor truth authority, or
a substitute for endpoint/process evidence.

中文解释：未来真正执行时，最多只能写运行态新鲜度报告和中文报告，不能改代码、
不能重启服务、不能动稳定工具目录。

---

## 5. Evidence Collection Scope

```yaml id="evidence-collection-scope"
evidence_collection_scope:
  runtime_paths:
    - stable_service_runtime_path
    - stable_cli_path
    - self_development_repo_path
    - whether_stable_cli_exists
  service_endpoint:
    - web_console_status_endpoint
    - mcp_endpoint_path
    - status_endpoint_response_or_unavailable_reason
    - endpoint_claims_about_project_path_if_available
    - endpoint_claims_about_loaded_code_if_available
  process_evidence:
    - colameta_process_candidates
    - process_command_line_if_available
    - process_working_directory_if_available
    - pid_if_available
  freshness_classification:
    - current
    - stale
    - unavailable
    - unknown
  known_unknowns:
    - unknown_name
    - why_unknown
    - what_would_resolve_it
```

---

## 6. Acceptance Commands

These commands are proposed for an explicitly authorized future execution of
this Version Taskbook. They are read-only probes and report-validation commands,
not service-control commands.

```yaml id="acceptance-commands"
acceptance_commands:
  preflight_read_only:
    - git status --short --branch
    - git rev-parse HEAD
    - git rev-parse origin/main
    - git rev-list --left-right --count origin/main...HEAD
    - test -x /home/jenn/tools/colameta/.venv/bin/colameta
  runtime_inventory:
    - readlink -f /home/jenn/tools/colameta/.venv/bin/colameta
    - ps -ef | rg "colameta|8801|8766" || true
    - curl -fsS http://127.0.0.1:8801/api/status || true
  taskbook_hash_checks:
    - sha256sum PROJECT_MASTER_TASKBOOK.md docs/taskbooks/stages/STAGE_00_BASELINE_CLOSEOUT.md docs/taskbooks/versions/stage-00/VERSION_STAGE_00_V0_1_REPOSITORY_RUNTIME_REALITY_SNAPSHOT.md docs/taskbooks/versions/stage-00/VERSION_STAGE_00_V0_2_VALIDATION_TRUTH_SOURCE_REPORT.md
  report_validation:
    - git diff --check -- docs/taskbooks/versions/stage-00/evidence/VERSION_STAGE_00_V0_3_RUNTIME_FRESHNESS_REPORT.md docs/taskbooks/versions/stage-00/evidence/zh-CN/VERSION_STAGE_00_V0_3_RUNTIME_FRESHNESS_REPORT.zh-CN.md
    - rg -n "stable_service_runtime_path|stable_cli_path|self_development_repo_path|status_endpoint_response_or_unavailable_reason|freshness_classification|known_unknowns|not_validated|remaining_risks" docs/taskbooks/versions/stage-00/evidence/VERSION_STAGE_00_V0_3_RUNTIME_FRESHNESS_REPORT.md
    - rg -n "source_document|source_sha256|stable_service_runtime_path|freshness_classification|known_unknowns|not_validated|remaining_risks" docs/taskbooks/versions/stage-00/evidence/zh-CN/VERSION_STAGE_00_V0_3_RUNTIME_FRESHNESS_REPORT.zh-CN.md
```

If `curl` fails because the service is down, the report must record
`unavailable` or `known_unknown`; the `|| true` suffix prevents a local endpoint
failure from aborting evidence capture. The report must not restart the service
or convert the failure into a pass.

Process command-line evidence from `ps -ef` must be redacted before it is
recorded in any report. Reports must not include secrets, tokens, credential
paths, private environment values, or unrelated process details.

中文解释：这些命令只能观察。服务不可用就写不可用或未知，不能顺手重启。

---

## 7. Manual Acceptance

```yaml id="manual-acceptance"
manual_acceptance:
  required_checks:
    - report separates stable runtime path from self-development repo path
    - report includes endpoint response or unavailable reason
    - report includes process evidence or known_unknown
    - report explains freshness_classification and its evidence basis
    - report states that no service restart or runtime reload was performed
    - report states that no Delivery State Gate transition was applied
    - Chinese report companion explains technical terms in Chinese
  reviewer_must_not_accept_if:
    - report hides service unavailability
    - report claims runtime freshness without endpoint/process evidence or known_unknown
    - report mutates stable runtime files
    - report maps runtime status directly into delivery_state
```

---

## 8. Evidence Package Contract

```yaml id="evidence-package-contract"
evidence_package_contract:
  evidence_package_id: stage_00_v0_3_runtime_freshness_evidence
  schema_version: evidence_package.minimum.v1
  task_ref:
    taskbook_id: stage_00_v0_3_runtime_freshness_report
    task_id: runtime_freshness_report
    scope_ref: docs/taskbooks/versions/stage-00/VERSION_STAGE_00_V0_3_RUNTIME_FRESHNESS_REPORT.md
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
      - runtime_freshness_report
      - chinese_runtime_freshness_report_companion
      - endpoint_or_unavailable_summary
      - process_evidence_or_known_unknown_summary
  checks:
    required:
      - runtime_path_check
      - endpoint_probe_or_unavailable_reason
      - process_inventory_or_known_unknown
      - freshness_classification_boundary_check
      - report_schema_check
  not_validated: required_even_when_empty
  remaining_risks: required_even_when_empty
  authority_required:
    - Delivery State Gate before any delivery_state transition
    - Commander before any restart, reload, executor dispatch, further execution, commit, or push
```

---

## 9. Stop Conditions

```yaml id="stop-conditions"
stop_conditions:
  - repository_path_is_not_/home/jenn/src/colameta-dev
  - stable_runtime_probe_requires_mutation
  - service_probe_requires_restart_reload_or_login
  - command_would_modify_runtime_or_repo_outside_allowed_output_paths
  - untracked_allowed_output_file_exists_and_was_not_created_by_current_authorized_execution
  - command_would_require_network_beyond_localhost_or_credentials
  - evidence_cannot_distinguish_loaded_runtime_from_self_development_repo
  - requested_action_would_expand_into_runtime_reload_restart_or_deploy
```

---

## 10. Out Of Scope

```yaml id="out-of-scope"
out_of_scope:
  - restart service
  - reload runtime code
  - modify /home/jenn/tools/colameta
  - reinstall or update dependencies
  - run executor
  - run tests
  - modify runner code
  - modify tests
  - modify .colameta/plan.json
  - modify Master or Stage Taskbooks
  - repair runtime freshness
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
  primary_report: docs/taskbooks/versions/stage-00/evidence/VERSION_STAGE_00_V0_3_RUNTIME_FRESHNESS_REPORT.md
  chinese_companion_report: docs/taskbooks/versions/stage-00/evidence/zh-CN/VERSION_STAGE_00_V0_3_RUNTIME_FRESHNESS_REPORT.zh-CN.md
  required_report_status: generated_only_after_separate_execution_authorization
  report_authority: evidence_only_not_delivery_state
```

---

## 12. Forbidden Authority Claims

```yaml id="forbidden-authority-claims"
forbidden_authority_claims:
  - endpoint_available_means_delivery_state_accepted
  - process_running_means_runtime_freshness_current
  - status_label_means_loaded_code_current
  - stable_cli_exists_means_service_loaded_from_that_cli
  - runtime_current_means_GateEvent_accepted
  - hash_match_means_execution_authorized
  - this_version_taskbook_authorizes_restart_or_reload
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
    - previous_version_taskbook_refs
    - runtime_freshness_report_ref
    - chinese_report_companion_ref
    - commands_run
    - commands_not_run
    - endpoint_response_or_unavailable_reason
    - process_evidence_or_known_unknown
    - freshness_classification
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
  execution_requires_future_token: AUTHORIZE_STAGE_00_V0_3_RUNTIME_FRESHNESS_REPORT_EXECUTION_FOR_EXACT_HASH_ONLY
  service_restart_requires_separate_authorization: true
  runtime_reload_requires_separate_authorization: true
  commit_requires_separate_authorization: true
  push_requires_separate_authorization: true
```

中文解释：下一步只能审查或修改这份 Version Taskbook。真正执行运行态新鲜度报告，
需要后续新的精确授权口令。
