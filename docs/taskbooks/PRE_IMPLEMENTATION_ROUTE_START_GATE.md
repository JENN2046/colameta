# Pre-Implementation Route Start Gate Packet

```text id="pre-implementation-route-start-gate-banner"
PRE-IMPLEMENTATION ROUTE START GATE MATERIAL DRAFT.
This packet prepares the first local implementation route-start authorization
for the Stage 0-6 Thin Governed Loop. It does not authorize implementation,
code edits, commit, push, fetch, pull, executor run, route transition, remote
write, release, deploy, or Delivery State Gate transition by itself.
```

```yaml id="pre-implementation-route-start-gate-summary"
pre_implementation_route_start_gate:
  document_type: pre_implementation_route_start_gate_packet
  schema_version: pre_implementation_route_start_gate.material_draft.v1
  status: route_start_gate_material_draft
  authority_status: commander_confirmation_prompt_draft_only
  project: ColaMeta
  workspace: /home/jenn/src/colameta-dev
  stable_service_runtime_path: /home/jenn/tools/colameta
  branch: main
  material_generation_head: 25a70bd5578f140d2d6f591ee13aae5ddf56da28
  material_generation_head_short: 25a70bd
  origin_main_observed_local_tracking_ref_at_material_generation: 018ff63b76872504407c537cd46e1e8a2ee5c22e
  ahead_origin_main_from_local_refs_at_material_generation: 47
  behind_origin_main_from_local_refs_at_material_generation: 0
  live_remote_status_not_validated: true
  worktree_status_at_material_generation: clean
  prepared_for_gate: pre_implementation_route_start_gate
  prepared_gate_outcome_requested: commander_hash_specific_local_implementation_authorization
  implementation_authority: false
  commit_authority: false
  push_authority: false
  fetch_authority: false
  pull_authority: false
  executor_authority: false
  route_transition_authority: false
  remote_write_authority: false
```

`Pre-Implementation Route Start Gate` means the last planning gate before a
specific local implementation slice may be authorized. It is not implementation
authorization. It only collects the exact route entry, boundary, allowed files,
validation commands, forbidden actions, and Commander confirmation language.

---

## 1. Gate Preconditions

```yaml id="gate-preconditions"
gate_preconditions:
  required_completed_reviews:
    - master_taskbook_freeze_candidate_confirmed_for_exact_hash
    - stage_0_6_stage_taskbook_set_freeze_candidate_confirmed_for_exact_hash
    - stage_0_6_version_sets_freeze_candidate_confirmed_for_exact_hash
    - stage_0_6_full_chain_closeout_review_clean
  current_closeout_review:
    outcome: GO
    meaning: ready_to_prepare_pre_implementation_route_start_gate_materials
  required_before_execution_start:
    - commander_exact_confirmation_prompt_accepted
    - worktree_clean_at_authorization_time
    - target_hashes_still_match
    - allowed_files_bound
    - forbidden_actions_bound
    - validation_commands_bound
```

This packet can be used only if the exact referenced hashes still match the
current repository. If any referenced file changes, the Commander prompt must be
regenerated.

---

## 2. Hash-Bound Planning Inputs

```yaml id="hash-bound-planning-inputs"
hash_bound_planning_inputs:
  master_taskbook:
    path: PROJECT_MASTER_TASKBOOK.md
    sha256: 1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34
    review_status: freeze_candidate_confirmed_for_exact_hash
  master_freeze_packet:
    path: FREEZE_CANDIDATE_REVIEW_PACKET.md
    sha256: 4199671538a07d3422ef510f1ad8718724b587e24cfa9014ccb6f2a1e0ef1236
    review_status: hash_specific_freeze_candidate_confirmation_recorded
  stage_0_6_stage_set_packet:
    path: docs/taskbooks/stages/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_0_6.md
    sha256: 94ea9101a120e0935e834533ed0315a6fe3e77e3d4ecb48db37fa6851e75b5ce
    review_status: hash_specific_freeze_candidate_confirmation_recorded
  stage_01_v1_1_taskbook:
    path: docs/taskbooks/versions/stage-01/VERSION_STAGE_01_V1_1_MASTER_TASKBOOK_REGISTRY_V1.md
    sha256: 503af0ff7cdac71c55b9fa3d47a09d3fc484c851daffb244a52385ac0dd2b896
    target_slice: first_local_implementation_slice
  stage_01_version_set_packet:
    path: docs/taskbooks/versions/stage-01/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_01_VERSIONS.md
    sha256: c4ef865c84ab634a7b3626cdc6924a4e51420a1d6d94bb274aeb9f13d354fce5
    review_status: hash_specific_freeze_candidate_confirmation_recorded
  stage_06_version_set_packet:
    path: docs/taskbooks/versions/stage-06/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_06_VERSIONS.md
    sha256: ffdb39ba91cdd1c016ec03030c0079731895f74e055b91fa50b0932db8cf0284
    role: latest_stage_0_6_version_packet_in_chain
```

---

## 3. Implementation Entry

```yaml id="implementation-entry"
implementation_entry:
  route_name: Stage 0-6 Thin Governed Loop Local Implementation Route
  entry_stage: stage_01_master_taskbook_anchoring
  entry_version: stage_01_v1_1_master_taskbook_registry_v1
  entry_reason: >
    Stage 0 is a baseline and reality-clarity stage. The first narrow local
    implementation slice should begin at Stage 1 / v1.1, where the Master
    Taskbook becomes a machine-readable registry anchor without mutating the
    Master Taskbook or granting active execution authority.
  route_start_mode: local_only
  implementation_model: thin_governed_slice
  skipped_scopes:
    - full_taskbook_platform
    - full_delivery_state_gate_runtime
    - external_taskbook_import_runtime
    - executor_dispatch
    - codex_router_bridge
```

The route starts with the smallest useful governance primitive: a Master
Taskbook registry contract and helper. It must not jump directly into the whole
Stage 0-6 platform.

---

## 4. First Implementation Slice

```yaml id="first-implementation-slice"
first_implementation_slice:
  stage: Stage 1
  version: v1.1
  name: Master Taskbook Registry V1
  chinese_name: 主任务书登记表 V1
  source_taskbook: docs/taskbooks/versions/stage-01/VERSION_STAGE_01_V1_1_MASTER_TASKBOOK_REGISTRY_V1.md
  primary_goal: >
    Create the minimal local Master Taskbook registry capability that records
    PROJECT_MASTER_TASKBOOK.md by path, hash, review-status boundary, observed
    local git state, and mutation boundary.
  minimum_deliverables:
    - machine_readable_master_registry_record
    - registry_helper_that_loads_and_validates_required_fields
    - fail_closed_behavior_for_missing_or_mismatched_required_fields
    - focused_unit_tests_for_registry_contract
    - evidence_report_with_commands_run_and_commands_not_run
    - Chinese evidence companion with source hash binding
  explicit_non_goals:
    - do_not_mutate_PROJECT_MASTER_TASKBOOK_md
    - do_not_create_full_taskbook_registry_platform
    - do_not_implement_stage_taskbook_management
    - do_not_implement_external_taskbook_import
    - do_not_dispatch_executor
    - do_not_claim_delivery_state_accepted
```

---

## 5. Authorization Boundary

```yaml id="authorization-boundary"
authorization_boundary:
  this_packet_authorizes: []
  commander_confirmation_would_authorize:
    - local_code_edits_within_allowed_files_only
    - local_document_edits_within_allowed_files_only
    - local_validation_commands_listed_in_this_packet
    - local_evidence_report_generation
  commander_confirmation_would_not_authorize:
    - commit
    - push
    - fetch
    - pull
    - executor_run
    - route_transition
    - remote_write
    - release
    - deploy
    - service_restart
    - modifying_/home/jenn/tools/colameta
    - modifying_PROJECT_MASTER_TASKBOOK_md
    - modifying_freeze_candidate_packets_except_separately_authorized_sync
    - delivery_state_transition
    - review_acceptance
```

Any commit after implementation requires a separate local commit authorization
or a separate controlled commit preview workflow.

---

## 6. Allowed Files

```yaml id="allowed-files"
allowed_files:
  read_only:
    - PROJECT_MASTER_TASKBOOK.md
    - PROJECT_MASTER_TASKBOOK.zh-CN.md
    - FREEZE_CANDIDATE_REVIEW_PACKET.md
    - FREEZE_CANDIDATE_REVIEW_PACKET.zh-CN.md
    - docs/taskbooks/stages/README.md
    - docs/taskbooks/stages/STAGE_01_MASTER_TASKBOOK_ANCHORING.md
    - docs/taskbooks/stages/zh-CN/STAGE_01_MASTER_TASKBOOK_ANCHORING.zh-CN.md
    - docs/taskbooks/stages/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_0_6.md
    - docs/taskbooks/stages/zh-CN/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_0_6.zh-CN.md
    - docs/taskbooks/versions/stage-01/VERSION_STAGE_01_V1_1_MASTER_TASKBOOK_REGISTRY_V1.md
    - docs/taskbooks/versions/stage-01/zh-CN/VERSION_STAGE_01_V1_1_MASTER_TASKBOOK_REGISTRY_V1.zh-CN.md
    - docs/taskbooks/versions/stage-01/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_01_VERSIONS.md
    - docs/taskbooks/versions/stage-01/zh-CN/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_01_VERSIONS.zh-CN.md
    - docs/taskbooks/CHINESE_COMPANION_POLICY.md
    - docs/taskbooks/CHINESE_COMPANION_INDEX.md
    - pyproject.toml
    - runner/**
    - tests/**
  writable_after_commander_confirmation:
    - .colameta/taskbooks/master_taskbook_registry.json
    - runner/master_taskbook_registry.py
    - tests/test_master_taskbook_registry.py
    - docs/taskbooks/versions/stage-01/evidence/VERSION_STAGE_01_V1_1_MASTER_TASKBOOK_REGISTRY_REPORT.md
    - docs/taskbooks/versions/stage-01/evidence/zh-CN/VERSION_STAGE_01_V1_1_MASTER_TASKBOOK_REGISTRY_REPORT.zh-CN.md
  forbidden_write_targets:
    - /home/jenn/tools/colameta/**
    - PROJECT_MASTER_TASKBOOK.md
    - PROJECT_MASTER_TASKBOOK.zh-CN.md
    - FREEZE_CANDIDATE_REVIEW_PACKET.md
    - docs/taskbooks/stages/**
    - docs/taskbooks/versions/stage-00/**
    - docs/taskbooks/versions/stage-02/**
    - docs/taskbooks/versions/stage-03/**
    - docs/taskbooks/versions/stage-04/**
    - docs/taskbooks/versions/stage-05/**
    - docs/taskbooks/versions/stage-06/**
    - .colameta/state.json
    - .colameta/runtime/**
    - .colameta/logs/**
    - .colameta/reports/**
    - .git/**
    - "**/.env"
    - "**/*secret*"
    - "**/*credential*"
```

The allowed file list is closed. If implementation discovers that another file
is required, the implementation must stop and request a new boundary.

---

## 7. Validation Commands

```yaml id="validation-commands"
validation_commands:
  preflight:
    - git status --short --branch
    - git rev-parse HEAD
    - git rev-parse origin/main
    - git rev-list --left-right --count origin/main...HEAD
    - sha256sum PROJECT_MASTER_TASKBOOK.md docs/taskbooks/versions/stage-01/VERSION_STAGE_01_V1_1_MASTER_TASKBOOK_REGISTRY_V1.md
  focused_validation:
    - python -m compileall runner/master_taskbook_registry.py
    - python -m unittest tests.test_master_taskbook_registry
  report_validation:
    - git diff --check
    - rg -n "master_taskbook_path|master_raw_snapshot_sha256|master_review_status|master_authority_boundary|mutation_boundary|known_unknowns|remaining_risks" docs/taskbooks/versions/stage-01/evidence/VERSION_STAGE_01_V1_1_MASTER_TASKBOOK_REGISTRY_REPORT.md
    - rg -n "source_document|source_sha256|主任务书|登记表|变更边界|已知未知|剩余风险" docs/taskbooks/versions/stage-01/evidence/zh-CN/VERSION_STAGE_01_V1_1_MASTER_TASKBOOK_REGISTRY_REPORT.zh-CN.md
  optional_broader_validation_after_focused_pass:
    - python -m unittest discover -s tests
```

These commands are not run by this packet. They become runnable only under the
exact Commander authorization.

---

## 8. Forbidden Actions

```yaml id="forbidden-actions"
forbidden_actions:
  always_forbidden_under_this_gate:
    - fetch
    - pull
    - push
    - force_push
    - remote_write
    - executor_run
    - route_transition
    - service_restart
    - release
    - deploy
    - credential_read_or_write
    - modifying_/home/jenn/tools/colameta
    - modifying_PROJECT_MASTER_TASKBOOK_md
    - modifying_freeze_confirmation_packets
    - allowed_files_expansion_without_new_authorization
    - claiming_review_acceptance
    - claiming_delivery_state_accepted
    - marking_P0_closed_by_implementation_alone
```

---

## 9. Stop Conditions

```yaml id="stop-conditions"
stop_conditions:
  must_stop_and_return_to_commander_if:
    - worktree_not_clean_at_authorization_time
    - current_head_does_not_match_authorized_head
    - any_hash_bound_planning_input_changed
    - implementation_requires_file_outside_allowed_writable_set
    - tests_require_service_restart_or_executor_run
    - registry_would_claim_Master_active_authority
    - registry_would_claim_delivery_state_accepted
    - remote_state_must_be_known_but_fetch_is_required
```

---

## 10. Evidence Requirements

```yaml id="evidence-requirements"
evidence_requirements:
  evidence_report_required: true
  evidence_report_path: docs/taskbooks/versions/stage-01/evidence/VERSION_STAGE_01_V1_1_MASTER_TASKBOOK_REGISTRY_REPORT.md
  chinese_companion_required: true
  chinese_companion_path: docs/taskbooks/versions/stage-01/evidence/zh-CN/VERSION_STAGE_01_V1_1_MASTER_TASKBOOK_REGISTRY_REPORT.zh-CN.md
  required_sections:
    - commands_run
    - commands_not_run
    - files_changed
    - registry_record_summary
    - master_hash_check
    - authority_boundary_check
    - validation_results
    - known_unknowns
    - remaining_risks
  forbidden_evidence_claims:
    - review_acceptance
    - delivery_state_accepted
    - executor_completion
    - remote_sync_verified_without_remote_probe
```

---

## 11. Commander Confirmation Prompt Draft

```text id="commander-confirmation-prompt-draft"
AUTHORIZE_STAGE_01_V1_1_LOCAL_IMPLEMENTATION_START_FOR_EXACT_GATE_ONLY

Target:
- Project: ColaMeta
- Workspace: /home/jenn/src/colameta-dev
- Gate material generation HEAD: 25a70bd5578f140d2d6f591ee13aae5ddf56da28
- Current observed HEAD at final confirmation:
  <TO_BE_FILLED_AFTER_PACKET_STORAGE_AND_FINAL_REVIEW>
- Local origin/main tracking ref observed at gate material generation:
  018ff63b76872504407c537cd46e1e8a2ee5c22e
- Local ahead origin/main from local refs at gate material generation: 47
- Master Taskbook sha256:
  1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34
- Pre-implementation route start gate packet sha256:
  <TO_BE_FILLED_AFTER_THIS_PACKET_IS_STORED>
- First implementation slice:
  Stage 1 / v1.1 / Master Taskbook Registry V1
- Source Version Taskbook:
  docs/taskbooks/versions/stage-01/VERSION_STAGE_01_V1_1_MASTER_TASKBOOK_REGISTRY_V1.md
- Source Version Taskbook sha256:
  503af0ff7cdac71c55b9fa3d47a09d3fc484c851daffb244a52385ac0dd2b896

Meaning:
- authorize local implementation start for this exact Stage 1 / v1.1 slice only
- authorize edits only inside the writable allowed_files listed in
  docs/taskbooks/PRE_IMPLEMENTATION_ROUTE_START_GATE.md
- authorize the validation commands listed in that packet
- authorize local evidence report generation for this slice
- keep Master, Stage, Version freeze packets, remote state, executor state, and
  Delivery State Gate unchanged

Does not authorize:
- commit
- push
- fetch
- pull
- executor run
- route transition
- remote write
- service restart
- release / deploy
- modifying /home/jenn/tools/colameta
- modifying PROJECT_MASTER_TASKBOOK.md
- modifying freeze confirmation packets
- allowed_files expansion
- review acceptance
- delivery state accepted
```

This prompt is a draft until this packet is stored and hashed. The final prompt
must replace `<TO_BE_FILLED_AFTER_THIS_PACKET_IS_STORED>` with the exact hash of
this packet, replace `<TO_BE_FILLED_AFTER_PACKET_STORAGE_AND_FINAL_REVIEW>` with
the exact current HEAD observed after packet storage, and must be confirmed by
Commander before any implementation starts.

---

## 12. Gate Outcome

```yaml id="gate-outcome"
gate_outcome:
  current_packet_outcome: MATERIAL_DRAFT_READY_FOR_REVIEW
  may_enter_implementation_without_commander_confirmation: false
  next_allowed_review_outcomes:
    - RETURN_TO_GATE_MATERIAL_FIXES
    - READY_FOR_HASH_SPECIFIC_COMMANDER_CONFIRMATION
  next_forbidden_outcomes:
    - IMPLEMENTATION_AUTHORIZED_BY_THIS_PACKET_ALONE
    - EXECUTOR_AUTHORIZED_BY_THIS_PACKET_ALONE
    - COMMIT_AUTHORIZED_BY_THIS_PACKET_ALONE
    - PUSH_AUTHORIZED_BY_THIS_PACKET_ALONE
```
