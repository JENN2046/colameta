from __future__ import annotations

import copy
import unittest

from runner.drift_evidence_schema import (
    AUTHORITY_BOUNDARY_EXPECTATIONS,
    DRIFT_EVIDENCE_SCHEMA_CHECK_FAILED_CLOSED,
    DRIFT_EVIDENCE_SCHEMA_CHECK_PASSED,
    DriftEvidenceSchemaError,
    assert_drift_evidence_schema_result_contract,
    drift_evidence_field_inventory,
    example_drift_evidence_pack,
    validate_drift_evidence_schema,
)


class DriftEvidenceSchemaTests(unittest.TestCase):
    def test_valid_minimum_pack_passes_without_authority_effects(self) -> None:
        result = validate_drift_evidence_schema(example_drift_evidence_pack())

        assert result["drift_evidence_schema_check_result"] == DRIFT_EVIDENCE_SCHEMA_CHECK_PASSED
        assert result["validation_result"] == "passed"
        assert result["semantic_alignment_pass"] is False
        assert result["no_drift_confirmed"] is False
        assert result["review_decision_created"] is False
        assert result["gate_event_emitted"] is False
        assert result["delivery_state_accepted"] is False
        assert result["plan_mutated"] is False
        assert result["taskbook_rewritten"] is False
        assert result["executor_continuation_authorized"] is False
        assert result["commit_or_push"] is False
        assert result["stage_scope_expanded"] is False
        assert result["semantic_drift_judgment"] is None
        assert all(value is False for value in result["authority_boundary"].values())

    def test_field_inventory_lists_minimum_stage_7_contract_and_boundary(self) -> None:
        inventory = drift_evidence_field_inventory()

        for field in (
            "drift_evidence_pack_id",
            "master_taskbook_ref",
            "stage_taskbook_ref",
            "version_taskbook_ref",
            "execution_evidence_ref",
            "changed_files",
            "validation_truth",
            "scope_evidence",
            "forbidden_files_evidence",
            "out_of_scope_evidence",
            "master_goal_alignment_questions",
            "reviewer_drift_checklist",
            "plan_adjustment_trigger_conditions",
        ):
            assert field in inventory["required_fields"]
        assert inventory["authority_boundary"] == AUTHORITY_BOUNDARY_EXPECTATIONS
        assert all(value is False for value in inventory["authority_boundary"].values())

    def test_missing_taskbook_refs_fail_closed(self) -> None:
        pack = example_drift_evidence_pack()
        del pack["master_taskbook_ref"]
        pack["stage_taskbook_ref"] = {}
        pack["version_taskbook_ref"] = "v1.12"

        result = validate_drift_evidence_schema(pack)

        assert result["drift_evidence_schema_check_result"] == DRIFT_EVIDENCE_SCHEMA_CHECK_FAILED_CLOSED
        assert "master_taskbook_ref" in result["rejected_fields"]
        assert "stage_taskbook_ref" in result["rejected_fields"]
        assert "version_taskbook_ref" in result["rejected_fields"]
        assert {"REQUIRED_FIELD_MISSING", "REQUIRED_REF_MISSING"} <= {item["code"] for item in result["rejection_reasons"]}

    def test_missing_execution_changed_files_validation_and_scope_fail_closed(self) -> None:
        pack = example_drift_evidence_pack()
        pack["execution_evidence_ref"] = []
        pack["changed_files"] = []
        pack["validation_truth"] = {}
        pack["scope_evidence"] = None

        result = validate_drift_evidence_schema(pack)

        assert result["drift_evidence_schema_check_result"] == DRIFT_EVIDENCE_SCHEMA_CHECK_FAILED_CLOSED
        assert "execution_evidence_ref" in result["rejected_fields"]
        assert "changed_files" in result["rejected_fields"]
        assert "validation_truth" in result["rejected_fields"]
        assert "scope_evidence" in result["rejected_fields"]
        assert "REQUIRED_EVIDENCE_MISSING" in {item["code"] for item in result["rejection_reasons"]}
        assert "CHANGED_FILES_MISSING" in {item["code"] for item in result["rejection_reasons"]}

    def test_missing_forbidden_and_out_of_scope_evidence_fail_closed(self) -> None:
        pack = example_drift_evidence_pack()
        pack["forbidden_files_evidence"] = []
        pack["out_of_scope_evidence"] = {}

        result = validate_drift_evidence_schema(pack)

        assert result["drift_evidence_schema_check_result"] == DRIFT_EVIDENCE_SCHEMA_CHECK_FAILED_CLOSED
        assert "forbidden_files_evidence" in result["rejected_fields"]
        assert "out_of_scope_evidence" in result["rejected_fields"]

    def test_missing_reviewer_questions_checklist_and_triggers_fail_closed(self) -> None:
        pack = example_drift_evidence_pack()
        pack["master_goal_alignment_questions"] = []
        pack["reviewer_drift_checklist"] = []
        pack["plan_adjustment_trigger_conditions"] = []

        result = validate_drift_evidence_schema(pack)

        assert result["drift_evidence_schema_check_result"] == DRIFT_EVIDENCE_SCHEMA_CHECK_FAILED_CLOSED
        assert "master_goal_alignment_questions" in result["rejected_fields"]
        assert "reviewer_drift_checklist" in result["rejected_fields"]
        assert "plan_adjustment_trigger_conditions" in result["rejected_fields"]
        assert "STRUCTURED_LIST_MISSING" in {item["code"] for item in result["rejection_reasons"]}

    def test_string_refs_are_rejected_instead_of_inferred(self) -> None:
        pack = example_drift_evidence_pack()
        pack["master_taskbook_ref"] = "PROJECT_MASTER_TASKBOOK.md"
        pack["execution_evidence_ref"] = "executor-report-example"

        result = validate_drift_evidence_schema(pack)

        assert result["drift_evidence_schema_check_result"] == DRIFT_EVIDENCE_SCHEMA_CHECK_FAILED_CLOSED
        assert "master_taskbook_ref" in result["rejected_fields"]
        assert "execution_evidence_ref" in result["rejected_fields"]

    def test_any_prefilled_reviewer_answers_fail_closed(self) -> None:
        pack = example_drift_evidence_pack()
        pack["master_goal_alignment_questions"][0]["answer"] = "UNCLEAR"
        pack["reviewer_drift_checklist"][0]["recommended_answer"] = "DRIFT_VISIBLE"

        result = validate_drift_evidence_schema(pack)

        assert result["drift_evidence_schema_check_result"] == DRIFT_EVIDENCE_SCHEMA_CHECK_FAILED_CLOSED
        assert "master_goal_alignment_questions" in result["rejected_fields"]
        assert "reviewer_drift_checklist" in result["rejected_fields"]
        assert "MASTER_GOAL_ALIGNMENT_QUESTIONS_INVALID" in {item["code"] for item in result["rejection_reasons"]}
        assert "REVIEWER_DRIFT_CHECKLIST_INVALID" in {item["code"] for item in result["rejection_reasons"]}

    def test_explicit_unanswered_marker_is_allowed(self) -> None:
        pack = example_drift_evidence_pack()
        pack["master_goal_alignment_questions"][0]["answer"] = "UNANSWERED"
        pack["reviewer_drift_checklist"][0]["recommended_answer"] = "UNANSWERED"

        result = validate_drift_evidence_schema(pack)

        assert result["drift_evidence_schema_check_result"] == DRIFT_EVIDENCE_SCHEMA_CHECK_PASSED

    def test_nested_authority_claims_fail_closed(self) -> None:
        for claim_key in (
            "semantic_alignment_pass",
            "no_drift_confirmed",
            "review_decision_created",
            "gate_event_emitted",
            "delivery_state_accepted",
            "plan_mutated",
            "taskbook_rewritten",
            "executor_continuation_authorized",
            "commit_or_push",
            "stage_scope_expanded",
        ):
            with self.subTest(claim_key=claim_key):
                pack = example_drift_evidence_pack()
                pack["nested_claims"] = {"authority": {claim_key: True}}

                result = validate_drift_evidence_schema(pack)

                assert result["drift_evidence_schema_check_result"] == DRIFT_EVIDENCE_SCHEMA_CHECK_FAILED_CLOSED
                assert "FORBIDDEN_DRIFT_EVIDENCE_AUTHORITY_CLAIM" in {item["code"] for item in result["rejection_reasons"]}
                assert any(item["claim"] == claim_key for item in result["known_conflicts"])

    def test_plan_adjust_action_claims_fail_closed(self) -> None:
        for claim_key in ("plan_diff_created", "plan_patch_created", "apply_request_created", "taskbook_mutation_created"):
            with self.subTest(claim_key=claim_key):
                pack = example_drift_evidence_pack()
                pack["plan_adjustment_trigger_conditions"][0][claim_key] = True

                result = validate_drift_evidence_schema(pack)

                assert result["drift_evidence_schema_check_result"] == DRIFT_EVIDENCE_SCHEMA_CHECK_FAILED_CLOSED
                assert "FORBIDDEN_DRIFT_EVIDENCE_AUTHORITY_CLAIM" in {item["code"] for item in result["rejection_reasons"]}
                assert any(item["claim"] == claim_key for item in result["known_conflicts"])

    def test_result_contract_rejects_truthy_authority_boundary(self) -> None:
        result = validate_drift_evidence_schema(example_drift_evidence_pack())
        mutated = copy.deepcopy(result)
        mutated["authority_boundary"]["commit_or_push"] = True

        with self.assertRaises(DriftEvidenceSchemaError) as raised:
            assert_drift_evidence_schema_result_contract(mutated)

        assert raised.exception.error_code == "FORBIDDEN_DRIFT_EVIDENCE_SCHEMA_RESULT_AUTHORITY_CLAIM"

    def test_result_contract_rejects_truthy_top_level_claim(self) -> None:
        result = validate_drift_evidence_schema(example_drift_evidence_pack())
        mutated = copy.deepcopy(result)
        mutated["delivery_state_accepted"] = True

        with self.assertRaises(DriftEvidenceSchemaError) as raised:
            assert_drift_evidence_schema_result_contract(mutated)

        assert raised.exception.error_code == "FORBIDDEN_DRIFT_EVIDENCE_SCHEMA_RESULT_CLAIM"

    def test_non_object_pack_fails_closed(self) -> None:
        result = validate_drift_evidence_schema("not a pack")  # type: ignore[arg-type]

        assert result["drift_evidence_schema_check_result"] == DRIFT_EVIDENCE_SCHEMA_CHECK_FAILED_CLOSED
        assert result["recognized_fields"] == []
        assert result["rejection_reasons"][0]["code"] == "DRIFT_EVIDENCE_PACK_INVALID"


if __name__ == "__main__":
    unittest.main()
