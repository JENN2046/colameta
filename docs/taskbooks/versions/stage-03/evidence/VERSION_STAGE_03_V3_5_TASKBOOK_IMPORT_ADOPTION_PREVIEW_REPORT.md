# Evidence Report: Stage 3 / v3.5 Taskbook Import Adoption Preview V1

```yaml id="stage-03-v3-5-evidence-summary"
evidence_report:
  report_id: stage_03_v3_5_taskbook_import_adoption_preview_evidence
  source_version_taskbook: docs/taskbooks/versions/stage-03/VERSION_STAGE_03_V3_5_TASKBOOK_IMPORT_ADOPTION_PREVIEW_V1.md
  source_version_taskbook_sha256: fc14101c9369d483281e16c4df98ed36258a00b6a1d256db234d03f6d2c619e4
  implementation_authorization_head: 1a384e4c39749226b87b801182624cd6ad5074f0
  master_taskbook_sha256: 1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34
  stage_03_taskbook_sha256: c5402734ef6990687a6a03ec6b17769f598ff0319b350b6a2371144985ece7ff
  v3_4_mapping_helper_sha256: eb9925f2d1f3a2ba79db945a8a04d13f7b978856b7228ed2b61bfda277ebbc47
  v3_4_mapping_evidence_sha256: 787dce0b588c0d1bbaa7fbf28fe03258aa6535386280c48e517fbbf6355342af
  import_adoption_preview_helper_sha256: 8eec69f790b9aad14720a193b9c3e0a4c55d58d59800057c49c6ac441fd36585
  import_adoption_preview_tests_sha256: 20fea107ba58613e771fd516f9338c6f89eb3eb1a474d54734e5d7c42d1dc44c
  status: local_evidence_report
  authority_status: evidence_only_not_import_adoption
  review_acceptance: false
  delivery_state_accepted: false
```

This report records the local implementation evidence for `Taskbook Import
Adoption Preview V1`. The slice adds an adoption preview helper, focused
adoption preview tests, and this English evidence report with a full Chinese
companion.

The adoption preview consumes only v3.4 mapping output. It prepares a
hash-bound Commander decision request, but the request remains `not_confirmed`
and authorizes no actions by itself. It does not mutate `.colameta/plan.json`,
expand allowed files, commit, dispatch an executor, create a ReviewDecision,
emit a GateEvent, or write delivery state.

---

## 1. Commands Run

```text id="commands-run"
git status -sb
  result: PASS
  observed_after_v3_4_commit_before_reports:
    ## main...origin/main [ahead 61]
    ?? runner/taskbook_import_adoption_preview.py
    ?? tests/test_taskbook_import_adoption_preview.py

git rev-parse HEAD
  result: PASS
  observed: 1a384e4c39749226b87b801182624cd6ad5074f0

git rev-list --count origin/main..HEAD
  result: PASS
  observed: 61

sha256sum PROJECT_MASTER_TASKBOOK.md docs/taskbooks/stages/STAGE_03_EXTERNAL_TASKBOOK_IMPORT.md docs/taskbooks/versions/stage-03/VERSION_STAGE_03_V3_5_TASKBOOK_IMPORT_ADOPTION_PREVIEW_V1.md runner/taskbook_version_candidate_mapping.py runner/taskbook_import_adoption_preview.py tests/test_taskbook_import_adoption_preview.py docs/taskbooks/versions/stage-03/evidence/VERSION_STAGE_03_V3_4_TASKBOOK_TO_VERSION_CANDIDATE_MAPPING_REPORT.md
  result: PASS
  observed:
    PROJECT_MASTER_TASKBOOK.md = 1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34
    docs/taskbooks/stages/STAGE_03_EXTERNAL_TASKBOOK_IMPORT.md = c5402734ef6990687a6a03ec6b17769f598ff0319b350b6a2371144985ece7ff
    docs/taskbooks/versions/stage-03/VERSION_STAGE_03_V3_5_TASKBOOK_IMPORT_ADOPTION_PREVIEW_V1.md = fc14101c9369d483281e16c4df98ed36258a00b6a1d256db234d03f6d2c619e4
    runner/taskbook_version_candidate_mapping.py = eb9925f2d1f3a2ba79db945a8a04d13f7b978856b7228ed2b61bfda277ebbc47
    runner/taskbook_import_adoption_preview.py = 8eec69f790b9aad14720a193b9c3e0a4c55d58d59800057c49c6ac441fd36585
    tests/test_taskbook_import_adoption_preview.py = 20fea107ba58613e771fd516f9338c6f89eb3eb1a474d54734e5d7c42d1dc44c
    docs/taskbooks/versions/stage-03/evidence/VERSION_STAGE_03_V3_4_TASKBOOK_TO_VERSION_CANDIDATE_MAPPING_REPORT.md = 787dce0b588c0d1bbaa7fbf28fe03258aa6535386280c48e517fbbf6355342af

.venv/bin/python -m compileall runner/taskbook_import_adoption_preview.py
  result: PASS
  observed: command returned 0

.venv/bin/python -m unittest tests.test_taskbook_import_adoption_preview
  result: PASS
  observed: Ran 11 tests ... OK

git diff --check
  result: PASS
  observed: command returned 0

read-only adoption preview smoke:
  result: PASS
  observed:
    adoption_preview_status: adoption_preview_ready
    decision_status: not_confirmed
    explicit_authorized_actions: []
    target_plan_path: .colameta/plan.json
    plan_mutation_authorized: false
    adoption_executed: false
    delivery_state_accepted: false
    blockers:
      - adoption_execution_requires_separate_commander_confirmation
```

---

## 2. Commands Not Run

```yaml id="commands-not-run"
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

The full test suite was not run because this implementation slice is narrowed
to the focused Taskbook Import Adoption Preview test command.

---

## 3. Files Changed

```yaml id="files-changed"
files_changed:
  created:
    - runner/taskbook_import_adoption_preview.py
    - tests/test_taskbook_import_adoption_preview.py
    - docs/taskbooks/versions/stage-03/evidence/VERSION_STAGE_03_V3_5_TASKBOOK_IMPORT_ADOPTION_PREVIEW_REPORT.md
    - docs/taskbooks/versions/stage-03/evidence/zh-CN/VERSION_STAGE_03_V3_5_TASKBOOK_IMPORT_ADOPTION_PREVIEW_REPORT.zh-CN.md
  modified: []
  forbidden_files_touched: []
```

`PROJECT_MASTER_TASKBOOK.md`, the Chinese Master companion, Stage Taskbooks,
Version Taskbooks, freeze packets, `.colameta/plan.json`, executor state, route
state, and service runtime stayed read-only for this slice.

---

## 4. Adoption Preview Contract Summary

```yaml id="adoption-preview-contract-summary"
adoption_preview_contract_summary:
  helper: runner.taskbook_import_adoption_preview.render_taskbook_import_adoption_preview
  accepted_input:
    - version_candidate_mapping
    - mapping_hash
    - current_head
    - candidate_plan_diff_hash
    - candidate_allowed_files_delta_hash
  adoption_preview_statuses:
    - adoption_preview_ready
    - adoption_preview_blocked_mapping_not_ready
    - adoption_preview_blocked_plan_scope_conflict
    - adoption_preview_blocked_authority_confusion
  required_output_fields:
    - adoption_preview_id
    - adoption_preview_status
    - source_taskbook_ref
    - import_preview_ref
    - mapping_ref
    - target_plan_path
    - candidate_plan_diff_summary
    - candidate_allowed_files_delta
    - candidate_forbidden_files_summary
    - candidate_acceptance_commands_summary
    - candidate_manual_acceptance_summary
    - required_exact_hash_authorization
    - commander_decision_request
    - blockers
    - risks
    - authority_boundary
```

---

## 5. Mapping Ready Positive Case

```yaml id="mapping-ready-positive-case"
mapping_ready_positive_case:
  adoption_preview_status: adoption_preview_ready
  target_plan_path: .colameta/plan.json
  decision_status: not_confirmed
  explicit_authorized_actions: []
  candidate_plan_diff_summary:
    candidate_only: true
    plan_mutation_authorized: false
    plan_mutation_applied: false
  candidate_allowed_files_delta:
    candidate_only: true
    allowed_files_expansion_authorized: false
  adoption_executed: false
  delivery_state_accepted: false
  blockers:
    - adoption_execution_requires_separate_commander_confirmation
```

---

## 6. Mapping Blocked Negative Case

```yaml id="mapping-blocked-negative-case"
mapping_blocked_negative_case:
  adoption_preview_status: adoption_preview_blocked_mapping_not_ready
  blocker_code: mapping_not_ready
  plan_mutation_authorized: false
  adoption_executed: false
  delivery_state_accepted: false
```

Additional negative tests cover invalid hash inputs, wrong target plan path,
authority-confused mapping, executed adoption claims, plan mutation authority,
Commander request confirmation claims, Commander request authorized actions,
and missing blockers.

---

## 7. Commander Decision Request Example

```yaml id="commander-decision-request-example"
commander_decision_request_example:
  target_repository_path: /home/jenn/src/colameta-dev
  current_head: 1a384e4c39749226b87b801182624cd6ad5074f0
  source_taskbook_hash: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
  import_preview_hash: cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
  mapping_hash: dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd
  target_plan_path: .colameta/plan.json
  candidate_plan_diff_hash: eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee
  candidate_allowed_files_delta_hash: ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff
  decision_status: not_confirmed
  explicit_authorized_actions: []
  explicit_unauthorized_actions:
    - implementation
    - commit
    - push
    - fetch
    - pull
    - executor_dispatch
    - route_transition
    - remote_write
    - delivery_state_accepted
    - release_or_deploy
  invalidation_rule: Any mismatch in repository path, current head, source hash, preview hash, mapping hash, target plan path, candidate plan diff hash, or allowed-files delta hash invalidates this request.
```

The request is a prompt-ready structure for a future Commander confirmation. It
is not itself Commander confirmation.

---

## 8. Authority Boundary Check

```yaml id="authority-boundary-check"
authority_boundary_check:
  adoption_preview_result_is_authority: false
  adoption_preview_executes_adoption: false
  adoption_preview_mutates_plan: false
  adoption_preview_expands_allowed_files: false
  adoption_preview_authorizes_executor_dispatch: false
  adoption_preview_records_commander_confirmation: false
  adoption_preview_writes_delivery_state: false
  creates_review_decision: false
  emits_gate_event: false
  adoption_executed: false
  plan_mutation_authorized: false
  allowed_files_expansion_authorized: false
  executor_dispatch_authorized: false
  delivery_state_accepted: false
  commander_confirmation_recorded: false
```

---

## 9. Known Gaps And Remaining Risks

```yaml id="known-gaps-and-remaining-risks"
known_gaps:
  - Adoption preview prepares a request structure only; it does not compute or apply a real plan diff.
  - Adoption preview does not write to .colameta/plan.json.
  - Adoption preview does not authorize commit, executor dispatch, route transition, or delivery state transition.
  - Only the focused v3.5 unittest module was run under this narrow slice.
remaining_risks:
  - Future plan mutation code must require a separate hash-specific Commander confirmation.
  - Future UI/report surfaces must not treat commander_decision_request as commander confirmation.
  - Future adoption code must invalidate the request if any bound hash, HEAD, path, or candidate diff hash changes.
```
