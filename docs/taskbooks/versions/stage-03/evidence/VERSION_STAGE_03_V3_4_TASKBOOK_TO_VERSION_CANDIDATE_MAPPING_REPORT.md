# Evidence Report: Stage 3 / v3.4 Taskbook-to-Version-Candidate Mapping V1

```yaml id="stage-03-v3-4-evidence-summary"
evidence_report:
  report_id: stage_03_v3_4_taskbook_to_version_candidate_mapping_evidence
  source_version_taskbook: docs/taskbooks/versions/stage-03/VERSION_STAGE_03_V3_4_TASKBOOK_TO_VERSION_CANDIDATE_MAPPING_V1.md
  source_version_taskbook_sha256: a1ef7d80d50655dc24b19c23d696cd69a16bbc0fbaa0aa35811b858c41e849b1
  implementation_authorization_head: 2f74ea3a9b0301f1dda6908ab22adca3c037177b
  master_taskbook_sha256: 1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34
  stage_03_taskbook_sha256: c5402734ef6990687a6a03ec6b17769f598ff0319b350b6a2371144985ece7ff
  v3_3_import_preview_helper_sha256: 5717d7da4cfc0143484c6bfbb8ce66a712a05e880af0cee6726d296375aecca7
  v3_3_import_preview_evidence_sha256: b6b3c999155f89b301ed42a4b8f7f65a7d6d8aa8f4159f89f551c200355c4285
  version_candidate_mapping_helper_sha256: eb9925f2d1f3a2ba79db945a8a04d13f7b978856b7228ed2b61bfda277ebbc47
  version_candidate_mapping_tests_sha256: 06e3f2c48184f09732603c90f33b736fdb194de2a0a916e7188a44bdb2a45f67
  status: local_evidence_report
  authority_status: evidence_only_not_import_adoption
  review_acceptance: false
  delivery_state_accepted: false
```

This report records the local implementation evidence for
`Taskbook-to-Version-Candidate Mapping V1`. The slice adds a candidate mapping
helper, focused mapping tests, and this English evidence report with a full
Chinese companion.

The mapping consumes v3.3 import preview output plus the validator-normalized
claim candidate required to preserve Master/Stage references. It maps the
preview into an internal Version candidate object while keeping every output
candidate-only. It does not insert a plan item, mutate `.colameta/plan.json`,
expand allowed files, dispatch an executor, create a ReviewDecision, emit a
GateEvent, or write delivery state.

---

## 1. Commands Run

```text id="commands-run"
git status -sb
  result: PASS
  observed_after_v3_3_commit_before_reports:
    ## main...origin/main [ahead 60]
    ?? runner/taskbook_version_candidate_mapping.py
    ?? tests/test_taskbook_version_candidate_mapping.py

git rev-parse HEAD
  result: PASS
  observed: 2f74ea3a9b0301f1dda6908ab22adca3c037177b

git rev-list --count origin/main..HEAD
  result: PASS
  observed: 60

sha256sum PROJECT_MASTER_TASKBOOK.md docs/taskbooks/stages/STAGE_03_EXTERNAL_TASKBOOK_IMPORT.md docs/taskbooks/versions/stage-03/VERSION_STAGE_03_V3_4_TASKBOOK_TO_VERSION_CANDIDATE_MAPPING_V1.md runner/taskbook_import_preview.py runner/taskbook_version_candidate_mapping.py tests/test_taskbook_version_candidate_mapping.py docs/taskbooks/versions/stage-03/evidence/VERSION_STAGE_03_V3_3_TASKBOOK_IMPORT_PREVIEW_REPORT.md
  result: PASS
  observed:
    PROJECT_MASTER_TASKBOOK.md = 1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34
    docs/taskbooks/stages/STAGE_03_EXTERNAL_TASKBOOK_IMPORT.md = c5402734ef6990687a6a03ec6b17769f598ff0319b350b6a2371144985ece7ff
    docs/taskbooks/versions/stage-03/VERSION_STAGE_03_V3_4_TASKBOOK_TO_VERSION_CANDIDATE_MAPPING_V1.md = a1ef7d80d50655dc24b19c23d696cd69a16bbc0fbaa0aa35811b858c41e849b1
    runner/taskbook_import_preview.py = 5717d7da4cfc0143484c6bfbb8ce66a712a05e880af0cee6726d296375aecca7
    runner/taskbook_version_candidate_mapping.py = eb9925f2d1f3a2ba79db945a8a04d13f7b978856b7228ed2b61bfda277ebbc47
    tests/test_taskbook_version_candidate_mapping.py = 06e3f2c48184f09732603c90f33b736fdb194de2a0a916e7188a44bdb2a45f67
    docs/taskbooks/versions/stage-03/evidence/VERSION_STAGE_03_V3_3_TASKBOOK_IMPORT_PREVIEW_REPORT.md = b6b3c999155f89b301ed42a4b8f7f65a7d6d8aa8f4159f89f551c200355c4285

.venv/bin/python -m compileall runner/taskbook_version_candidate_mapping.py
  result: PASS
  observed: command returned 0

.venv/bin/python -m unittest tests.test_taskbook_version_candidate_mapping
  result: PASS
  observed: Ran 11 tests ... OK

git diff --check
  result: PASS
  observed: command returned 0

read-only mapping smoke:
  result: PASS
  observed:
    mapping_status: mapping_ready
    version_candidate_id: version_candidate_aaaaaaaaaaaa
    import_preview_hash: cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
    candidate_only: true
    authorized_delta: false
    plan_item_inserted: false
    delivery_state_accepted: false
    adoption_blockers:
      - adoption_requires_separate_commander_decision
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
to the focused Version candidate mapping test command.

---

## 3. Files Changed

```yaml id="files-changed"
files_changed:
  created:
    - runner/taskbook_version_candidate_mapping.py
    - tests/test_taskbook_version_candidate_mapping.py
    - docs/taskbooks/versions/stage-03/evidence/VERSION_STAGE_03_V3_4_TASKBOOK_TO_VERSION_CANDIDATE_MAPPING_REPORT.md
    - docs/taskbooks/versions/stage-03/evidence/zh-CN/VERSION_STAGE_03_V3_4_TASKBOOK_TO_VERSION_CANDIDATE_MAPPING_REPORT.zh-CN.md
  modified: []
  forbidden_files_touched: []
```

`PROJECT_MASTER_TASKBOOK.md`, the Chinese Master companion, Stage Taskbooks,
Version Taskbooks, freeze packets, `.colameta/plan.json`, executor state, route
state, and service runtime stayed read-only for this slice.

---

## 4. Mapping Contract Summary

```yaml id="mapping-contract-summary"
mapping_contract_summary:
  helper: runner.taskbook_version_candidate_mapping.map_preview_to_version_candidate
  accepted_input:
    - import_preview
    - import_preview_hash
    - normalized_claims_candidate
  mapping_statuses:
    - mapping_ready
    - mapping_blocked_preview_not_ready
    - mapping_blocked_scope_conflict
    - mapping_blocked_authority_confusion
  required_output_fields:
    - version_candidate_id
    - mapping_status
    - source_taskbook_ref
    - import_preview_ref
    - candidate_parent_refs
    - candidate_version_identity
    - candidate_allowed_files
    - candidate_forbidden_files
    - candidate_acceptance_commands
    - candidate_manual_acceptance
    - candidate_evidence_requirements
    - candidate_out_of_scope
    - adoption_blockers
    - required_commander_decisions
    - authority_boundary
```

---

## 5. Preview Ready Positive Case

```yaml id="preview-ready-positive-case"
preview_ready_positive_case:
  mapping_status: mapping_ready
  version_candidate_id: version_candidate_aaaaaaaaaaaa
  source_taskbook_hash_preserved: true
  import_preview_hash_preserved: true
  parent_refs_preserved:
    master_taskbook_ref: PROJECT_MASTER_TASKBOOK.md
    stage_taskbook_ref: stage_03_external_taskbook_import
  candidate_allowed_files:
    candidate_only: true
    authorized_delta: false
  candidate_acceptance_commands:
    candidate_only: true
    authorized_to_run: false
  plan_item_inserted: false
  delivery_state_accepted: false
```

---

## 6. Preview Blocked Negative Case

```yaml id="preview-blocked-negative-case"
preview_blocked_negative_case:
  mapping_status: mapping_blocked_preview_not_ready
  blocker_code: import_preview_not_ready
  plan_mutation_authorized: false
  plan_item_inserted: false
  delivery_state_accepted: false
```

Additional negative tests cover missing normalized claims, invalid preview hash,
authority-confused preview input, plan insertion claims, delivery-state
authority claims, mapping-ready outputs without adoption blockers, and
candidate allowed-files authorization attempts.

---

## 7. Preservation Check

```yaml id="preservation-check"
preservation_check:
  source_taskbook_hash:
    preserved_from: normalized_claims_candidate.external_taskbook_hash
    output_field: source_taskbook_ref.external_taskbook_hash
  import_preview_hash:
    preserved_from: map_preview_to_version_candidate.import_preview_hash
    output_field: import_preview_ref.import_preview_hash
  master_taskbook_ref:
    preserved_from: normalized_claims_candidate.master_taskbook_ref
    output_field: candidate_parent_refs.master_taskbook_ref
  stage_taskbook_ref:
    preserved_from: normalized_claims_candidate.stage_taskbook_ref
    output_field: candidate_parent_refs.stage_taskbook_ref
  required_commander_decisions:
    preserved_from: import_preview.required_commander_decisions
    output_field: required_commander_decisions
```

---

## 8. Authority Boundary Check

```yaml id="authority-boundary-check"
authority_boundary_check:
  mapping_result_is_authority: false
  mapping_inserts_plan_item: false
  mapping_mutates_plan: false
  mapping_expands_allowed_files: false
  mapping_authorizes_executor_dispatch: false
  mapping_writes_delivery_state: false
  creates_review_decision: false
  emits_gate_event: false
  plan_item_inserted: false
  plan_mutation_authorized: false
  allowed_files_expansion_authorized: false
  executor_dispatch_authorized: false
  delivery_state_accepted: false
```

---

## 9. Known Gaps And Remaining Risks

```yaml id="known-gaps-and-remaining-risks"
known_gaps:
  - Mapping consumes structured preview and normalized-claim dictionaries; it does not parse arbitrary external Markdown taskbook text.
  - Mapping creates a candidate object only; it does not write to .colameta/plan.json.
  - Mapping does not authorize adoption, allowed_files expansion, command execution, or delivery state transition.
  - Only the focused v3.4 unittest module was run under this narrow slice.
remaining_risks:
  - v3.5 must keep import adoption as preview-only unless a separate hard gate authorizes actual adoption.
  - Future plan-insertion code must consume this mapping only after explicit hash-specific adoption authorization.
  - UI/report surfaces must not treat mapping_ready as accepted, adopted, or executable.
```
