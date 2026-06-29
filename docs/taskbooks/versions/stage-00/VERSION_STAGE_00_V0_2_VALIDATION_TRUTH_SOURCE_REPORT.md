# Version Taskbook: Stage 0 / v0.2 Validation Truth Source Report

```text id="version-stage-00-v0-2-boundary-banner"
VERSION TASKBOOK DRAFT ONLY.
This document defines a candidate Version Execution Taskbook for Stage 0. It
does not authorize execution, executor dispatch, code edits, test execution,
commit, push, runtime restart, route transition, Delivery State Gate
transition, or accepted delivery state.
```

```yaml id="version-taskbook-summary"
version_execution_taskbook:
  document_type: version_execution_taskbook
  schema_version: version_execution_taskbook.discussion_draft.v1
  version_id: stage_00_v0_2_validation_truth_source_report
  version: v0.2
  name: Validation Truth Source Report
  chinese_name: 验证真相来源报告
  parent_stage_id: stage_00_baseline_closeout
  parent_stage_name: Baseline Closeout And Execution-State Clarity
  status: discussion_draft
  authority_status: planning_reference_only
  execution_authorization_status: not_authorized
  dispatch_status: not_authorized
  executor_run_authorized: false
  test_execution_authorized: false
  created_from_head: f60f801
  created_from_head_meaning: historical_creation_baseline_not_execution_or_freeze_snapshot
  created_from_head_subject: "docs: add stage 0 reality snapshot version taskbook"
  origin_main_observed: 018ff63
  local_tracking_ref_sync_status_at_creation: local_ahead_remote_tracking_ref
  local_ahead_origin_main_at_creation: 1
```

`Validation Truth Source Report` = 验证真相来源报告。中文意思是：它说明验证结论
到底来自哪些命令、文件、报告或人工检查，并明确区分真实验证证据、摘要标签、
未运行项和已知未知项。

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
  previous_version_taskbook_ref:
    path: docs/taskbooks/versions/stage-00/VERSION_STAGE_00_V0_1_REPOSITORY_RUNTIME_REALITY_SNAPSHOT.md
    raw_snapshot_sha256: 6393181ffd38f46f319b2d3dd350e3749d59d22c0b588688a558308232897d8d
    version_id: stage_00_v0_1_repository_runtime_reality_snapshot
    status: local_baseline_commit_not_pushed_at_creation
  supports_project_goal: true
```

This Version Taskbook is subordinate to Stage 0. It may clarify validation
evidence boundaries, but it must not redefine accepted delivery state,
Commander authority, Delivery State Gate authority, or executor authority.

中文解释：这份 Version 只说明“验证证据从哪里来”，不能把验证通过偷换成
accepted，也不能给 executor 扩权。

---

## 2. Task Goal

```yaml id="task-goal"
task_goal:
  primary_goal: >
    Produce a bounded Validation Truth Source Report that inventories the
    validation claims, validation commands, validation artifacts, runtime
    labels, summary labels, unrun checks, and known unknowns relevant to the
    current ColaMeta self-development baseline.
  minimum_readiness_claim: >
    Validation conclusions are explainable enough that later Stage 0 and Stage
    1 claims do not rely on summary labels such as PASSED, COMPLETED, or
    VERSION_PASSED without command or evidence provenance.
  gate_question: >
    Can a reviewer tell what was actually validated, what merely reported a
    summary label, what was not run, and what remains unknown?
  explicit_non_goal: >
    This version is not validation hardening, test-suite execution, code
    mutation, report truth repair, runtime cleanup, executor dispatch, or
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
    previous_version_taskbook_hash: 6393181ffd38f46f319b2d3dd350e3749d59d22c0b588688a558308232897d8d
  task_goal_ref: task_goal.primary_goal
  definition_of_good:
    - validation truth-source report exists at the declared reporting destination
    - report distinguishes command evidence from summary labels
    - report lists validation commands available without claiming they ran
    - report records commands_run and commands_not_run separately
    - report records validation_not_run_reason where applicable
    - report records validation_inconsistent_or_none explicitly
    - report covers executor report status vocabulary if observable
    - report does not map PASSED, COMPLETED, BLOCKED, or VERSION_PASSED into delivery_state
  allowed_autonomy_after_explicit_authorization:
    - local read-only inspection
    - local report file creation under allowed output paths
    - narrow report correction if validation finds missing required fields
```

`Validation Truth Source` = 验证真相来源。中文意思是：不要只看“通过/失败”摘要，
而要知道这个结论是哪个命令、哪个报告、哪个文件、哪个人工检查支撑的。

---

## 4. Allowed Files And Mutations

```yaml id="allowed-files-and-mutations"
allowed_files:
  read_only:
    - PROJECT_MASTER_TASKBOOK.md
    - PROJECT_MASTER_TASKBOOK.zh-CN.md
    - docs/taskbooks/stages/STAGE_00_BASELINE_CLOSEOUT.md
    - docs/taskbooks/stages/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_0_6.md
    - docs/taskbooks/**
    - docs/taskbooks/versions/stage-00/VERSION_STAGE_00_V0_1_REPOSITORY_RUNTIME_REALITY_SNAPSHOT.md
    - docs/taskbooks/versions/stage-00/zh-CN/VERSION_STAGE_00_V0_1_REPOSITORY_RUNTIME_REALITY_SNAPSHOT.zh-CN.md
    - docs/taskbooks/CHINESE_COMPANION_POLICY.md
    - docs/taskbooks/CHINESE_COMPANION_INDEX.md
    - .colameta/plan.json
    - .colameta/plan.zh-CN.md
    - .colameta/state.json
    - .colameta/prompts/**
    - runner/**
    - tests/**
    - pyproject.toml
    - pytest.ini
    - setup.cfg
    - tox.ini
  writable_after_separate_execution_authorization:
    - docs/taskbooks/versions/stage-00/evidence/VERSION_STAGE_00_V0_2_VALIDATION_TRUTH_SOURCE_REPORT.md
    - docs/taskbooks/versions/stage-00/evidence/zh-CN/VERSION_STAGE_00_V0_2_VALIDATION_TRUTH_SOURCE_REPORT.zh-CN.md

allowed_mutations:
  - create_or_update_declared_validation_truth_report_only_after_explicit_execution_authorization
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
    - docs/taskbooks/versions/stage-00/zh-CN/VERSION_STAGE_00_V0_1_REPOSITORY_RUNTIME_REALITY_SNAPSHOT.zh-CN.md
    - .colameta/plan.json
    - .colameta/prompts/**
    - .git/**
    - "**/.env"
    - "**/*secret*"
    - "**/*credential*"
```

`.colameta/state.json` is volatile observed runtime metadata only. It must not
be treated as validation truth authority, delivery_state authority,
accepted-state authority, blocked-state authority, executor truth authority, or
a substitute for command evidence.

中文解释：未来真正执行时，最多只能写验证真相来源报告和中文报告，不能改代码、
不能跑测试、不能改计划、不能动稳定工具目录。

---

## 5. Evidence Collection Scope

```yaml id="evidence-collection-scope"
evidence_collection_scope:
  validation_claims:
    - current_plan_version_status_labels
    - runner_report_status_labels_if_observable
    - web_status_validation_labels_if_observable
    - prior_commit_or_taskbook_validation_claims
  validation_sources:
    - validation_commands_declared_in_taskbooks
    - validation_commands_declared_in_project_files
    - test_discovery_surfaces
    - smoke_or_unit_test_entrypoints
    - manual_acceptance_requirements
  truth_separation:
    - commands_run
    - commands_not_run
    - labels_observed
    - labels_not_backed_by_current_command_evidence
    - validation_not_run_reason
    - validation_inconsistent_or_none
  executor_report_status_vocabulary:
    - executed
    - validated
    - blocked
    - failed
    - stale
  known_unknowns:
    - unknown_name
    - why_unknown
    - what_would_resolve_it
```

---

## 6. Acceptance Commands

These commands are proposed for an explicitly authorized future execution of
this Version Taskbook. They are inventory and report-validation commands, not
test-suite execution commands.

```yaml id="acceptance-commands"
acceptance_commands:
  preflight_read_only:
    - git status --short --branch
    - git rev-parse HEAD
    - git rev-parse origin/main || true
    - git rev-list --left-right --count origin/main...HEAD || true
  validation_inventory:
    - rg -n "unittest|pytest|compileall|smoke|validation|acceptance_commands|manual_acceptance|VERSION_PASSED|PASSED|COMPLETED|BLOCKED|executed|validated|failed|stale|validation_inconsistent" runner tests docs/taskbooks .colameta/plan.json .colameta/plan.zh-CN.md .colameta/state.json .colameta/prompts || true
    - find runner tests docs/taskbooks .colameta/prompts -maxdepth 3 -type f \( -name "pyproject.toml" -o -name "pytest.ini" -o -name "setup.cfg" -o -name "tox.ini" \) -print || true
    - find . -maxdepth 1 -type f \( -name "pyproject.toml" -o -name "pytest.ini" -o -name "setup.cfg" -o -name "tox.ini" \) -print || true
    - git log -5 --oneline
  taskbook_hash_checks:
    - sha256sum PROJECT_MASTER_TASKBOOK.md docs/taskbooks/stages/STAGE_00_BASELINE_CLOSEOUT.md docs/taskbooks/versions/stage-00/VERSION_STAGE_00_V0_1_REPOSITORY_RUNTIME_REALITY_SNAPSHOT.md
  report_validation:
    - git diff --check -- docs/taskbooks/versions/stage-00/evidence/VERSION_STAGE_00_V0_2_VALIDATION_TRUTH_SOURCE_REPORT.md docs/taskbooks/versions/stage-00/evidence/zh-CN/VERSION_STAGE_00_V0_2_VALIDATION_TRUTH_SOURCE_REPORT.zh-CN.md
    - rg -n "commands_run|commands_not_run|labels_observed|validation_not_run_reason|validation_inconsistent_or_none|executor_report_status_vocabulary|known_unknowns|remaining_risks" docs/taskbooks/versions/stage-00/evidence/VERSION_STAGE_00_V0_2_VALIDATION_TRUTH_SOURCE_REPORT.md
    - rg -n "source_document|source_sha256|commands_run|commands_not_run|known_unknowns|remaining_risks" docs/taskbooks/versions/stage-00/evidence/zh-CN/VERSION_STAGE_00_V0_2_VALIDATION_TRUTH_SOURCE_REPORT.zh-CN.md
```

Running unit tests, smoke tests, or executor validation is out of scope for this
version unless a later exact authorization expands the envelope. The report may
inventory such commands, but it must mark them as not run.

If the local `origin/main` tracking ref is unavailable, the report must record
`known_unknown` for local tracking ref context; it must not auto-fetch or contact
the remote. If validation evidence conflicts with summary labels, the report
must record `validation_inconsistent_or_none` rather than hiding the conflict.

中文解释：这份 v0.2 先盘点验证入口和验证声明，不直接跑测试。因为跑测试可能写
缓存、改状态或产生副作用，必须另有授权。

---

## 7. Manual Acceptance

```yaml id="manual-acceptance"
manual_acceptance:
  required_checks:
    - report separates validation evidence from summary labels
    - report lists commands_run and commands_not_run separately
    - report includes validation_not_run_reason for unrun checks
    - report includes validation_inconsistent_or_none
    - report identifies whether PASSED, COMPLETED, BLOCKED, and VERSION_PASSED are labels or evidence-backed outcomes
    - report distinguishes executor report status vocabulary: executed, validated, blocked, failed, and stale
    - report states that no Delivery State Gate transition was applied
    - Chinese report companion explains technical terms in Chinese
  reviewer_must_not_accept_if:
    - report claims validation passed without command evidence
    - report hides not-run validation commands
    - report maps runtime labels directly into delivery_state
    - report mutates files outside allowed output paths
```

---

## 8. Evidence Package Contract

```yaml id="evidence-package-contract"
evidence_package_contract:
  evidence_package_id: stage_00_v0_2_validation_truth_source_evidence
  schema_version: evidence_package.minimum.v1
  task_ref:
    taskbook_id: stage_00_v0_2_validation_truth_source_report
    task_id: validation_truth_source_report
    scope_ref: docs/taskbooks/versions/stage-00/VERSION_STAGE_00_V0_2_VALIDATION_TRUTH_SOURCE_REPORT.md
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
      - validation_truth_source_report
      - chinese_validation_truth_source_report_companion
      - command_inventory_summary
  checks:
    required:
      - validation_inventory_check
      - taskbook_hash_check
      - label_vs_evidence_boundary_check
      - validation_inconsistent_boundary_check
      - executor_report_status_boundary_check
      - report_schema_check
  not_validated: required_even_when_empty
  remaining_risks: required_even_when_empty
  authority_required:
    - Delivery State Gate before any delivery_state transition
    - Commander before any test execution, executor dispatch, further execution, commit, or push
```

---

## 9. Stop Conditions

```yaml id="stop-conditions"
stop_conditions:
  - repository_path_is_not_/home/jenn/src/colameta-dev
  - validation_inventory_requires_running_tests
  - command_would_modify_runtime_or_repo_outside_allowed_output_paths
  - untracked_allowed_output_file_exists_and_was_not_created_by_current_authorized_execution
  - command_would_require_network_or_credentials
  - evidence_cannot_distinguish_observed_fact_from_summary_label
  - requested_action_would_expand_into_validation_hardening_or_test_execution
```

---

## 10. Out Of Scope

```yaml id="out-of-scope"
out_of_scope:
  - run tests
  - modify runner code
  - modify tests
  - modify validation commands
  - modify .colameta/plan.json
  - modify Master or Stage Taskbooks
  - modify /home/jenn/tools/colameta
  - restart service
  - run executor
  - repair validation truth source
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
  primary_report: docs/taskbooks/versions/stage-00/evidence/VERSION_STAGE_00_V0_2_VALIDATION_TRUTH_SOURCE_REPORT.md
  chinese_companion_report: docs/taskbooks/versions/stage-00/evidence/zh-CN/VERSION_STAGE_00_V0_2_VALIDATION_TRUTH_SOURCE_REPORT.zh-CN.md
  required_report_status: generated_only_after_separate_execution_authorization
  report_authority: evidence_only_not_delivery_state
```

---

## 12. Forbidden Authority Claims

```yaml id="forbidden-authority-claims"
forbidden_authority_claims:
  - validation_label_means_command_was_run
  - validation_passed_means_delivery_state_accepted
  - PASSED_means_GateEvent_accepted
  - COMPLETED_means_GateEvent_accepted
  - BLOCKED_means_delivery_item_blocked
  - VERSION_PASSED_means_delivery_state_accepted
  - hash_match_means_execution_authorized
  - this_version_taskbook_authorizes_test_execution
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
    - previous_version_taskbook_ref
    - validation_truth_source_report_ref
    - chinese_report_companion_ref
    - commands_run
    - commands_not_run
    - labels_observed
    - labels_not_backed_by_current_command_evidence
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
  execution_requires_future_token: AUTHORIZE_STAGE_00_V0_2_VALIDATION_TRUTH_SOURCE_REPORT_EXECUTION_FOR_EXACT_HASH_ONLY
  test_execution_requires_separate_authorization: true
  commit_requires_separate_authorization: true
  push_requires_separate_authorization: true
```

中文解释：下一步只能审查或修改这份 Version Taskbook。真正执行验证真相来源报告，
需要后续新的精确授权口令。
