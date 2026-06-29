# Evidence Report: Stage 3 / v3.3 Taskbook Import Preview V1

```yaml id="stage-03-v3-3-evidence-summary"
evidence_report:
  report_id: stage_03_v3_3_taskbook_import_preview_evidence
  source_version_taskbook: docs/taskbooks/versions/stage-03/VERSION_STAGE_03_V3_3_TASKBOOK_IMPORT_PREVIEW_V1.md
  source_version_taskbook_sha256: 8443c5ac8b9927a308da382bd2fd3e39992636b27f059539f0de46f802c78768
  implementation_authorization_head: 2bf635704cb311120368865ac8a0a994d91d4124
  master_taskbook_sha256: 1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34
  stage_03_taskbook_sha256: c5402734ef6990687a6a03ec6b17769f598ff0319b350b6a2371144985ece7ff
  v3_2_validator_helper_sha256: 42e9bc43b2942cba72e3ee802b80be80fa284975250253a18fc2a68cda4dc44f
  v3_2_validator_evidence_sha256: 75d1bdfdecd8c621275111aa96a1fb2218b4550909e0edba254d64ca2bac4420
  taskbook_import_preview_helper_sha256: 5717d7da4cfc0143484c6bfbb8ce66a712a05e880af0cee6726d296375aecca7
  taskbook_import_preview_tests_sha256: 6b22a81443d46810ba4df41b38269e9754bf25cb1e27a52023bd36dabaa09c55
  status: local_evidence_report
  authority_status: evidence_only_not_import_adoption
  review_acceptance: false
  delivery_state_accepted: false
```

This report records the local implementation evidence for `Taskbook Import
Preview V1`. The slice adds a read-only preview helper, focused rendering and
contract tests, and this English evidence report with a full Chinese companion.

The preview consumes only a v3.2 validator result. It summarizes the validated
claim as candidate-only information for Commander and reviewer inspection. It
does not adopt an import, mutate plan, expand allowed files, authorize
acceptance commands, dispatch an executor, create a ReviewDecision, emit a
GateEvent, or write delivery state.

---

## 1. Commands Run

```text id="commands-run"
git status -sb
  result: PASS
  observed_after_v3_2_commit_before_reports:
    ## main...origin/main [ahead 59]
    ?? runner/taskbook_import_preview.py
    ?? tests/test_taskbook_import_preview.py

git rev-parse HEAD
  result: PASS
  observed: 2bf635704cb311120368865ac8a0a994d91d4124

git rev-list --count origin/main..HEAD
  result: PASS
  observed: 59

sha256sum PROJECT_MASTER_TASKBOOK.md docs/taskbooks/stages/STAGE_03_EXTERNAL_TASKBOOK_IMPORT.md docs/taskbooks/versions/stage-03/VERSION_STAGE_03_V3_3_TASKBOOK_IMPORT_PREVIEW_V1.md runner/external_taskbook_validator.py runner/taskbook_import_preview.py tests/test_taskbook_import_preview.py docs/taskbooks/versions/stage-03/evidence/VERSION_STAGE_03_V3_2_EXTERNAL_TASKBOOK_VALIDATOR_REPORT.md
  result: PASS
  observed:
    PROJECT_MASTER_TASKBOOK.md = 1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34
    docs/taskbooks/stages/STAGE_03_EXTERNAL_TASKBOOK_IMPORT.md = c5402734ef6990687a6a03ec6b17769f598ff0319b350b6a2371144985ece7ff
    docs/taskbooks/versions/stage-03/VERSION_STAGE_03_V3_3_TASKBOOK_IMPORT_PREVIEW_V1.md = 8443c5ac8b9927a308da382bd2fd3e39992636b27f059539f0de46f802c78768
    runner/external_taskbook_validator.py = 42e9bc43b2942cba72e3ee802b80be80fa284975250253a18fc2a68cda4dc44f
    runner/taskbook_import_preview.py = 5717d7da4cfc0143484c6bfbb8ce66a712a05e880af0cee6726d296375aecca7
    tests/test_taskbook_import_preview.py = 6b22a81443d46810ba4df41b38269e9754bf25cb1e27a52023bd36dabaa09c55
    docs/taskbooks/versions/stage-03/evidence/VERSION_STAGE_03_V3_2_EXTERNAL_TASKBOOK_VALIDATOR_REPORT.md = 75d1bdfdecd8c621275111aa96a1fb2218b4550909e0edba254d64ca2bac4420

.venv/bin/python -m compileall runner/taskbook_import_preview.py
  result: PASS
  observed: command returned 0

.venv/bin/python -m unittest tests.test_taskbook_import_preview
  result: PASS
  observed: Ran 11 tests ... OK

git diff --check
  result: PASS
  observed: command returned 0

read-only preview smoke:
  result: PASS
  observed:
    preview_status: preview_ready
    blockers: []
    candidate_only: true
    authorized_delta: false
    adoption_authorized: false
    delivery_state_accepted: false
    required_commander_decisions:
      - decide_whether_to_consider_mapping
      - hash_specific_adoption_decision
      - execution_authorization
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
to the focused Taskbook Import Preview test command.

---

## 3. Files Changed

```yaml id="files-changed"
files_changed:
  created:
    - runner/taskbook_import_preview.py
    - tests/test_taskbook_import_preview.py
    - docs/taskbooks/versions/stage-03/evidence/VERSION_STAGE_03_V3_3_TASKBOOK_IMPORT_PREVIEW_REPORT.md
    - docs/taskbooks/versions/stage-03/evidence/zh-CN/VERSION_STAGE_03_V3_3_TASKBOOK_IMPORT_PREVIEW_REPORT.zh-CN.md
  modified: []
  forbidden_files_touched: []
```

`PROJECT_MASTER_TASKBOOK.md`, the Chinese Master companion, Stage Taskbooks,
Version Taskbooks, freeze packets, `.colameta/plan.json`, executor state, route
state, and service runtime stayed read-only for this slice.

---

## 4. Preview Contract Summary

```yaml id="preview-contract-summary"
preview_contract_summary:
  helper: runner.taskbook_import_preview.render_taskbook_import_preview
  accepted_input:
    - v3_2_validator_result
  preview_statuses:
    - preview_ready
    - preview_blocked_invalid_validator_result
    - preview_blocked_authority_confusion
    - preview_blocked_missing_required_claim
  required_output_fields:
    - preview_id
    - preview_status
    - source_claim_ref
    - validator_result_ref
    - recognized_claims_summary
    - rejected_claims_summary
    - proposed_version_candidate_identity
    - proposed_scope_summary
    - proposed_allowed_files_candidate_delta
    - proposed_forbidden_files_summary
    - proposed_acceptance_commands_summary
    - proposed_manual_acceptance_summary
    - required_commander_decisions
    - blockers
    - authority_boundary
```

---

## 5. Valid Preview Example

```yaml id="valid-preview-example"
valid_preview_example:
  preview_status: preview_ready
  blockers: []
  proposed_version_candidate_identity:
    candidate_only: true
    authorized_for_mapping: false
    identity_status: candidate_identity_preview_only_not_mapped
  proposed_allowed_files_candidate_delta:
    candidate_only: true
    authorized_delta: false
  proposed_acceptance_commands_summary:
    candidate_only: true
    authorized_to_run: false
  proposed_manual_acceptance_summary:
    candidate_only: true
    manual_acceptance_is_delivery_state_accepted: false
  required_commander_decisions:
    - decide_whether_to_consider_mapping
    - hash_specific_adoption_decision
    - execution_authorization
```

---

## 6. Invalid Validator Result Example

```yaml id="invalid-validator-result-example"
invalid_validator_result_example:
  preview_status: preview_blocked_invalid_validator_result
  blocker_code: validator_result_not_passed
  authorized_delta: false
  adoption_authorized: false
  delivery_state_accepted: false
```

Authority-confused validator results are also blocked before preview rendering
continues.

---

## 7. Authority Boundary Check

```yaml id="authority-boundary-check"
authority_boundary_check:
  preview_result_is_authority: false
  preview_authorizes_adoption: false
  preview_mutates_plan: false
  preview_expands_allowed_files: false
  preview_authorizes_executor_dispatch: false
  preview_writes_delivery_state: false
  creates_review_decision: false
  emits_gate_event: false
  adoption_authorized: false
  plan_mutation_authorized: false
  allowed_files_expansion_authorized: false
  executor_dispatch_authorized: false
  delivery_state_accepted: false
```

Focused tests cover preview-contract rejection for adoption authority,
delivery-state authority, ready previews with blockers, blocked previews
without blockers, and allowed-files delta authorization.

---

## 8. Candidate Delta Labeling Check

```yaml id="candidate-delta-labeling-check"
candidate_delta_labeling_check:
  proposed_version_candidate_identity:
    candidate_only: true
    authorized_for_mapping: false
  proposed_scope_summary:
    candidate_only: true
  proposed_allowed_files_candidate_delta:
    candidate_only: true
    authorized_delta: false
  proposed_forbidden_files_summary:
    candidate_only: true
  proposed_acceptance_commands_summary:
    candidate_only: true
    authorized_to_run: false
  proposed_manual_acceptance_summary:
    candidate_only: true
    manual_acceptance_is_delivery_state_accepted: false
```

---

## 9. Known Gaps And Remaining Risks

```yaml id="known-gaps-and-remaining-risks"
known_gaps:
  - The preview consumes structured validator results; it does not parse arbitrary external Markdown taskbook text.
  - The preview does not map an external taskbook into a Version candidate; v3.4 owns mapping.
  - The preview does not adopt external taskbooks, mutate plan, or expand allowed files.
  - Only the focused v3.3 unittest module was run under this narrow slice.
remaining_risks:
  - v3.4 must preserve the boundary between preview and Version candidate mapping.
  - v3.5 must keep adoption as preview-only unless a separate hard gate authorizes actual adoption.
  - Future UI or report presenters must not collapse candidate deltas into authorized deltas.
```
