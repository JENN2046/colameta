# Evidence Report: Stage 3 / v3.1 External Taskbook Schema V1

```yaml id="stage-03-v3-1-evidence-summary"
evidence_report:
  report_id: stage_03_v3_1_external_taskbook_schema_evidence
  source_version_taskbook: docs/taskbooks/versions/stage-03/VERSION_STAGE_03_V3_1_EXTERNAL_TASKBOOK_SCHEMA_V1.md
  source_version_taskbook_sha256: 0d92e1d7779db1d89253986cd40c045dc75b25c0b2f31dbb46143d3b5d1f3232
  implementation_authorization_head: 0dbd14462add847865e1a17a15fd11dcb0cabcc9
  master_taskbook_sha256: 1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34
  stage_03_taskbook_sha256: c5402734ef6990687a6a03ec6b17769f598ff0319b350b6a2371144985ece7ff
  stage_2_version_set_confirmation_sha256: 3de9f207f7a80ce1ec3f2cb374c1f10b4903014be18d0dbe6d2defa1224e8f58
  stage_2_gate_readiness_evidence_sha256: 2f660ddfe5dbc38d2d2a4531913945668fc4cdb556b1f5d0f155378c7fdbd392
  external_taskbook_schema_sha256: 3f40f58f6680644c9ff2feaf57860ebcc6e01d9abdf22646c7223ace55f09291
  external_taskbook_schema_helper_sha256: 2dfcf5aab88d31d6a95a45464d65abb699473f32a856dfb78c8721278970db82
  external_taskbook_schema_tests_sha256: 0bc08f8d9f4d73bf9c317057037356a609953502cb31a0c53d66c74a9b38e579
  status: local_evidence_report
  authority_status: evidence_only_not_review_acceptance
  review_acceptance: false
  delivery_state_accepted: false
```

This report records the local implementation evidence for `External Taskbook
Schema V1`. The slice adds a minimal schema file, a schema helper, focused
schema tests, and this English evidence report with a full Chinese companion.

The schema treats externally authored Version Execution Taskbooks as bounded
claims. It does not treat external taskbooks as trusted facts, does not mutate
the plan, does not expand allowed files, does not authorize execution, and does
not map manual acceptance to accepted delivery state.

---

## 1. Commands Run

```text id="commands-run"
git status -sb
  result: PASS
  observed_after_implementation_before_reports:
    ## main...origin/main [ahead 57]
    ?? .colameta/taskbooks/external_taskbook_schema.json
    ?? runner/external_taskbook_schema.py
    ?? tests/test_external_taskbook_schema.py

git rev-parse HEAD
  result: PASS
  observed: 0dbd14462add847865e1a17a15fd11dcb0cabcc9

git rev-parse origin/main
  result: PASS
  observed: 018ff63b76872504407c537cd46e1e8a2ee5c22e

git rev-list --count origin/main..HEAD
  result: PASS
  observed: 57

sha256sum PROJECT_MASTER_TASKBOOK.md docs/taskbooks/stages/STAGE_03_EXTERNAL_TASKBOOK_IMPORT.md docs/taskbooks/versions/stage-03/VERSION_STAGE_03_V3_1_EXTERNAL_TASKBOOK_SCHEMA_V1.md docs/taskbooks/versions/stage-02/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_02_VERSIONS.md docs/taskbooks/versions/stage-02/evidence/VERSION_STAGE_02_V2_4_STAGE_TASKBOOK_GATE_READINESS_REPORT.md .colameta/taskbooks/external_taskbook_schema.json runner/external_taskbook_schema.py tests/test_external_taskbook_schema.py
  result: PASS
  observed:
    PROJECT_MASTER_TASKBOOK.md = 1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34
    docs/taskbooks/stages/STAGE_03_EXTERNAL_TASKBOOK_IMPORT.md = c5402734ef6990687a6a03ec6b17769f598ff0319b350b6a2371144985ece7ff
    docs/taskbooks/versions/stage-03/VERSION_STAGE_03_V3_1_EXTERNAL_TASKBOOK_SCHEMA_V1.md = 0d92e1d7779db1d89253986cd40c045dc75b25c0b2f31dbb46143d3b5d1f3232
    docs/taskbooks/versions/stage-02/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_02_VERSIONS.md = 3de9f207f7a80ce1ec3f2cb374c1f10b4903014be18d0dbe6d2defa1224e8f58
    docs/taskbooks/versions/stage-02/evidence/VERSION_STAGE_02_V2_4_STAGE_TASKBOOK_GATE_READINESS_REPORT.md = 2f660ddfe5dbc38d2d2a4531913945668fc4cdb556b1f5d0f155378c7fdbd392
    .colameta/taskbooks/external_taskbook_schema.json = 3f40f58f6680644c9ff2feaf57860ebcc6e01d9abdf22646c7223ace55f09291
    runner/external_taskbook_schema.py = 2dfcf5aab88d31d6a95a45464d65abb699473f32a856dfb78c8721278970db82
    tests/test_external_taskbook_schema.py = 0bc08f8d9f4d73bf9c317057037356a609953502cb31a0c53d66c74a9b38e579

.venv/bin/python -m compileall runner/external_taskbook_schema.py
  result: PASS
  observed: command returned 0

.venv/bin/python -m unittest tests.test_external_taskbook_schema
  result: PASS
  observed: Ran 13 tests ... OK

git diff --check
  result: PASS
  observed: command returned 0

read-only helper smoke:
  command: schema_contract_summary(".") and preview_external_taskbook_claim_shape(valid_claim)
  result: PASS
  observed:
    schema_contract_status: valid
    schema_sha256: 3f40f58f6680644c9ff2feaf57860ebcc6e01d9abdf22646c7223ace55f09291
    schema_check_result: schema_check_passed
    schema_result_is_authority: false
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
  - delivery_state_transition
  - modifying_/home/jenn/tools/colameta
```

The full test suite was not run because the v3.1 implementation authorization
was narrowed to the focused External Taskbook schema test command.

---

## 3. Files Changed

```yaml id="files-changed"
files_changed:
  created:
    - .colameta/taskbooks/external_taskbook_schema.json
    - runner/external_taskbook_schema.py
    - tests/test_external_taskbook_schema.py
    - docs/taskbooks/versions/stage-03/evidence/VERSION_STAGE_03_V3_1_EXTERNAL_TASKBOOK_SCHEMA_REPORT.md
    - docs/taskbooks/versions/stage-03/evidence/zh-CN/VERSION_STAGE_03_V3_1_EXTERNAL_TASKBOOK_SCHEMA_REPORT.zh-CN.md
  modified: []
  forbidden_files_touched: []
```

`PROJECT_MASTER_TASKBOOK.md`, Stage Taskbook sources, Stage 0-2 Version files,
`.colameta/plan.json`, executor state, route state, and service runtime stayed
read-only for this slice.

---

## 4. Schema Contract Summary

```yaml id="schema-contract-summary"
schema_contract_summary:
  schema_file: .colameta/taskbooks/external_taskbook_schema.json
  schema_version: external_taskbook_schema.v1
  schema_id: external_taskbook.claim.schema.v1
  claim_kind: external_version_execution_taskbook_claim.v1
  schema_result_is_authority: false
  creates_review_decision: false
  emits_gate_event: false
  writes_delivery_state: false
```

---

## 5. Required Field Table

```yaml id="required-field-table"
required_field_table:
  required_fields:
    - source
    - provenance
    - external_taskbook_hash
    - expected_hash_authority_ref
    - master_taskbook_ref
    - stage_taskbook_ref
    - allowed_files
    - forbidden_files
    - acceptance_commands
    - manual_acceptance
    - out_of_scope
    - supports_stage_and_master_goals
  rejection_fields:
    - rejected_fields
    - rejection_reasons
    - known_conflicts
  normalized_output_fields:
    - normalized_claims
    - normalized_output_candidate
    - version_candidate_mapping
```

---

## 6. Forbidden Authority Claims Check

```yaml id="forbidden-authority-claims-check"
forbidden_authority_claims_check:
  rejected_claims:
    - external_taskbook_is_trusted_fact
    - external_taskbook_mutates_plan
    - external_taskbook_authorizes_execution
    - external_taskbook_expands_allowed_files
    - manual_acceptance_means_delivery_state_accepted
  result_authority_boundary:
    schema_result_is_authority: false
    creates_review_decision: false
    emits_gate_event: false
    writes_delivery_state: false
```

Focused tests cover forbidden external execution authority claims, manual
acceptance being treated as accepted delivery state, schema-level truthy
authority claims, and missing or malformed required fields.

---

## 7. Example Valid Claim Shape

```yaml id="example-valid-claim-shape"
example_valid_claim_shape:
  schema_check_result: schema_check_passed
  normalized_output_candidate:
    claim_kind: external_version_execution_taskbook_claim.v1
  version_candidate_mapping:
    mapping_status: schema_claim_shape_only_not_adopted
  authority_boundary:
    external_taskbook_is_trusted_fact: false
    external_taskbook_mutates_plan: false
    external_taskbook_authorizes_execution: false
    external_taskbook_expands_allowed_files: false
    manual_acceptance_means_delivery_state_accepted: false
```

---

## 8. Example Rejected Claim Shape

```yaml id="example-rejected-claim-shape"
example_rejected_claim_shape:
  missing_required_field:
    result: schema_check_failed_closed
    observed_reason: REQUIRED_FIELD_MISSING
  invalid_external_taskbook_hash:
    result: schema_check_failed_closed
    observed_reason: FIELD_TYPE_INVALID
  missing_expected_hash_authority_document:
    result: schema_check_failed_closed
    observed_reason: EXPECTED_HASH_AUTHORITY_REF_INVALID
  forbidden_authority_claim:
    result: schema_check_failed_closed
    observed_reason: FORBIDDEN_AUTHORITY_CLAIM
```

---

## 9. Known Gaps And Remaining Risks

```yaml id="known-gaps-and-remaining-risks"
known_gaps:
  - This helper performs schema contract and example claim shape checks only; v3.2 owns full import validation.
  - The schema does not parse arbitrary Markdown taskbook text; it defines the normalized JSON claim shape.
  - Only the focused v3.1 unittest module was run under this narrow authorization.
remaining_risks:
  - v3.2 must consume this schema without turning schema_check_passed into import adoption.
  - Future external taskbook formats may need additional field types or richer provenance rules.
```
