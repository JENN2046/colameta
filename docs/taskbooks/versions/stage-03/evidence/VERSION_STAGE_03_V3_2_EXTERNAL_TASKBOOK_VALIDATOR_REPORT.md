# Evidence Report: Stage 3 / v3.2 External Taskbook Validator V1

```yaml id="stage-03-v3-2-evidence-summary"
evidence_report:
  report_id: stage_03_v3_2_external_taskbook_validator_evidence
  source_version_taskbook: docs/taskbooks/versions/stage-03/VERSION_STAGE_03_V3_2_EXTERNAL_TASKBOOK_VALIDATOR_V1.md
  source_version_taskbook_sha256: 7bdf06889b25439f9ca8ed70a2e93962f1ab6bec9566fe7b752aa47ad9ebb927
  implementation_authorization_head: c259bcfaf434f310d703e724a75abe8c5e0e5db0
  master_taskbook_sha256: 1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34
  stage_03_taskbook_sha256: c5402734ef6990687a6a03ec6b17769f598ff0319b350b6a2371144985ece7ff
  v3_1_schema_file_sha256: 3f40f58f6680644c9ff2feaf57860ebcc6e01d9abdf22646c7223ace55f09291
  v3_1_schema_helper_sha256: 2dfcf5aab88d31d6a95a45464d65abb699473f32a856dfb78c8721278970db82
  v3_1_schema_evidence_sha256: 02616de6a67c9551eb581d3fffdd2fd7bf6442571e194eb1573bbc9b6b3229f5
  external_taskbook_validator_helper_sha256: 42e9bc43b2942cba72e3ee802b80be80fa284975250253a18fc2a68cda4dc44f
  external_taskbook_validator_tests_sha256: 16e49d75dcdd8029eacc72e8fcf8c503c05f16cca3207f9a715e1d16d2126164
  status: local_evidence_report
  authority_status: evidence_only_not_import_adoption
  review_acceptance: false
  delivery_state_accepted: false
```

This report records the local implementation evidence for `External Taskbook
Validator V1`. The slice adds a fail-closed validator helper, focused tests,
and this English evidence report with a full Chinese companion.

The validator consumes the v3.1 schema helper and adds expected Master/Stage
binding, hash-authority, file-boundary, command-boundary, goal-support, and
authority-confusion checks. A passed validator result is still evidence only:
it is not import adoption, plan mutation, executor authorization, review
acceptance, GateEvent emission, or accepted delivery state.

---

## 1. Commands Run

```text id="commands-run"
git status -sb
  result: PASS
  observed_after_v3_1_commit_before_reports:
    ## main...origin/main [ahead 58]
    ?? runner/external_taskbook_validator.py
    ?? tests/test_external_taskbook_validator.py

git rev-parse HEAD
  result: PASS
  observed: c259bcfaf434f310d703e724a75abe8c5e0e5db0

git rev-list --count origin/main..HEAD
  result: PASS
  observed: 58

sha256sum PROJECT_MASTER_TASKBOOK.md docs/taskbooks/stages/STAGE_03_EXTERNAL_TASKBOOK_IMPORT.md docs/taskbooks/versions/stage-03/VERSION_STAGE_03_V3_2_EXTERNAL_TASKBOOK_VALIDATOR_V1.md .colameta/taskbooks/external_taskbook_schema.json runner/external_taskbook_schema.py runner/external_taskbook_validator.py tests/test_external_taskbook_validator.py docs/taskbooks/versions/stage-03/evidence/VERSION_STAGE_03_V3_1_EXTERNAL_TASKBOOK_SCHEMA_REPORT.md
  result: PASS
  observed:
    PROJECT_MASTER_TASKBOOK.md = 1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34
    docs/taskbooks/stages/STAGE_03_EXTERNAL_TASKBOOK_IMPORT.md = c5402734ef6990687a6a03ec6b17769f598ff0319b350b6a2371144985ece7ff
    docs/taskbooks/versions/stage-03/VERSION_STAGE_03_V3_2_EXTERNAL_TASKBOOK_VALIDATOR_V1.md = 7bdf06889b25439f9ca8ed70a2e93962f1ab6bec9566fe7b752aa47ad9ebb927
    .colameta/taskbooks/external_taskbook_schema.json = 3f40f58f6680644c9ff2feaf57860ebcc6e01d9abdf22646c7223ace55f09291
    runner/external_taskbook_schema.py = 2dfcf5aab88d31d6a95a45464d65abb699473f32a856dfb78c8721278970db82
    runner/external_taskbook_validator.py = 42e9bc43b2942cba72e3ee802b80be80fa284975250253a18fc2a68cda4dc44f
    tests/test_external_taskbook_validator.py = 16e49d75dcdd8029eacc72e8fcf8c503c05f16cca3207f9a715e1d16d2126164
    docs/taskbooks/versions/stage-03/evidence/VERSION_STAGE_03_V3_1_EXTERNAL_TASKBOOK_SCHEMA_REPORT.md = 02616de6a67c9551eb581d3fffdd2fd7bf6442571e194eb1573bbc9b6b3229f5

.venv/bin/python -m compileall runner/external_taskbook_validator.py
  result: PASS
  observed: command returned 0

.venv/bin/python -m unittest tests.test_external_taskbook_validator
  result: PASS
  observed: Ran 15 tests ... OK

git diff --check
  result: PASS
  observed: command returned 0

read-only validator smoke:
  result: PASS
  observed:
    validation_result: validation_passed
    fail_closed_result: pass
    recognized_fields: 12
    rejected_fields: []
    known_conflicts: []
    validator_result_is_authority: false
    writes_delivery_state: false
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
  - gate_event_emission
  - delivery_state_transition
  - modifying_/home/jenn/tools/colameta
```

The full test suite was not run because this implementation slice is narrowed
to the focused External Taskbook validator test command.

---

## 3. Files Changed

```yaml id="files-changed"
files_changed:
  created:
    - runner/external_taskbook_validator.py
    - tests/test_external_taskbook_validator.py
    - docs/taskbooks/versions/stage-03/evidence/VERSION_STAGE_03_V3_2_EXTERNAL_TASKBOOK_VALIDATOR_REPORT.md
    - docs/taskbooks/versions/stage-03/evidence/zh-CN/VERSION_STAGE_03_V3_2_EXTERNAL_TASKBOOK_VALIDATOR_REPORT.zh-CN.md
  modified: []
  forbidden_files_touched: []
```

`PROJECT_MASTER_TASKBOOK.md`, the Chinese Master companion, Stage Taskbooks,
Version Taskbooks, freeze packets, `.colameta/plan.json`, executor state, route
state, and service runtime stayed read-only for this slice.

---

## 4. Validator Behavior Summary

```yaml id="validator-behavior-summary"
validator_behavior_summary:
  helper: runner.external_taskbook_validator.validate_external_taskbook_claim
  consumes:
    - runner.external_taskbook_schema.load_external_taskbook_schema
    - runner.external_taskbook_schema.preview_external_taskbook_claim_shape
  validation_result_values:
    - validation_passed
    - validation_failed_closed
  pass_result:
    validation_result: validation_passed
    fail_closed_result: pass
  fail_result:
    validation_result: validation_failed_closed
    fail_closed_result: fail_closed
  required_outputs:
    - validation_result
    - recognized_fields
    - rejected_fields
    - rejection_reasons
    - known_conflicts
    - normalized_claims_candidate
```

The helper does not repair missing authority fields. If required schema fields
are absent or malformed, the validator returns `validation_failed_closed` and
does not emit a normalized claim candidate.

---

## 5. Positive Case Result

```yaml id="positive-case-result"
positive_case_result:
  validation_result: validation_passed
  fail_closed_result: pass
  recognized_fields_count: 12
  rejected_fields: []
  known_conflicts: []
  version_candidate_mapping_status: schema_claim_shape_only_not_adopted
  authority_boundary:
    validator_result_is_authority: false
    external_taskbook_is_trusted_fact: false
    external_taskbook_mutates_plan: false
    external_taskbook_authorizes_execution: false
    external_taskbook_expands_allowed_files: false
    manual_acceptance_means_delivery_state_accepted: false
    creates_review_decision: false
    emits_gate_event: false
    writes_delivery_state: false
```

---

## 6. Negative Case Results

```yaml id="negative-case-results"
negative_case_results:
  missing_required_field:
    validation_result: validation_failed_closed
    rejected_field: expected_hash_authority_ref
  missing_authority_hash:
    validation_result: validation_failed_closed
    rejection_code: EXPECTED_HASH_AUTHORITY_HASH_INVALID
  master_reference_mismatch:
    validation_result: validation_failed_closed
    rejected_field: master_taskbook_ref
    rejection_code: REFERENCE_MISMATCH
  stage_reference_mismatch:
    validation_result: validation_failed_closed
    rejected_field: stage_taskbook_ref
  allowed_forbidden_overlap:
    validation_result: validation_failed_closed
    rejection_code: ALLOWED_FORBIDDEN_FILES_OVERLAP
  hard_forbidden_allowed_file:
    validation_result: validation_failed_closed
    rejected_field: allowed_files
  forbidden_acceptance_command:
    validation_result: validation_failed_closed
    rejection_code: ACCEPTANCE_COMMAND_FORBIDDEN
  goal_support_false_or_missing_rationale:
    validation_result: validation_failed_closed
    rejected_field: supports_stage_and_master_goals
  plan_mutation_or_delivery_state_authority_claim:
    validation_result: validation_failed_closed
    rejection_code: FORBIDDEN_AUTHORITY_CLAIM
```

---

## 7. Rejected Fields Table

```yaml id="rejected-fields-table"
rejected_fields_table:
  schema_layer:
    - missing required field
    - malformed sha256
    - empty required list
    - forbidden authority claim
  validator_layer:
    - expected_hash_authority_ref without valid authority_hash or authority_sha256
    - master_taskbook_ref mismatch
    - stage_taskbook_ref mismatch
    - allowed_files and forbidden_files overlap
    - hard-forbidden path inside allowed_files
    - remote or executor command inside acceptance_commands
    - supports_stage_and_master_goals missing true Stage or Master support
```

---

## 8. Authority Confusion Check

```yaml id="authority-confusion-check"
authority_confusion_check:
  validator_result_is_authority: false
  external_taskbook_is_trusted_fact: false
  external_taskbook_mutates_plan: false
  external_taskbook_authorizes_execution: false
  external_taskbook_expands_allowed_files: false
  manual_acceptance_means_delivery_state_accepted: false
  creates_review_decision: false
  emits_gate_event: false
  writes_delivery_state: false
```

Focused tests cover result-contract rejection for authority-boundary mutation
and a truthy top-level delivery-state acceptance claim. These tests are
negative fixtures only; they do not authorize any state transition.

---

## 9. Known Gaps And Remaining Risks

```yaml id="known-gaps-and-remaining-risks"
known_gaps:
  - The validator consumes structured claim dictionaries; it does not parse arbitrary Markdown taskbook text.
  - The validator checks external taskbooks as bounded claims only; v3.3 owns import preview.
  - The validator does not adopt a claim into plan or Version candidates.
  - Only the focused v3.2 unittest module was run under this narrow slice.
remaining_risks:
  - v3.3 must preserve the difference between validation_passed and import preview.
  - v3.4 must preserve the difference between import preview and Version candidate mapping.
  - v3.5 must keep adoption as a preview only unless a separate hard gate authorizes actual adoption.
```
