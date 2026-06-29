from __future__ import annotations

import copy
import unittest

from runner.reviewer_handoff_generator import (
    BLOCKED_FOR_REVIEWER_HANDOFF,
    HANDOFF_GENERATION_FAILED_CLOSED,
    HANDOFF_PACKAGE_GENERATED,
    ReviewerHandoffGeneratorError,
    assert_reviewer_handoff_generator_result_contract,
    generate_reviewer_handoff_package,
)
from runner.reviewer_handoff_schema import ALLOWED_REVIEW_DECISIONS, HANDOFF_SCHEMA_CHECK_PASSED


class ReviewerHandoffGeneratorTests(unittest.TestCase):
    def inputs(self) -> dict:
        return {
            "reviewer_handoff_schema_ref": {"version_id": "stage_05_v5_1_reviewer_handoff_schema_v1"},
            "handoff_package_id": "handoff-package-example",
            "master_taskbook_ref": {"path": "PROJECT_MASTER_TASKBOOK.md"},
            "stage_taskbook_ref": {"path": "docs/taskbooks/stages/STAGE_05_REVIEWER_HANDOFF_PACKAGE.md"},
            "version_taskbook_ref": {"version_id": "stage_05_v5_2_reviewer_handoff_generator_v1"},
            "stage_4_audit_package_ref": {"audit_package_id": "audit-package-example"},
            "execution_receipt_refs": [{"receipt_id": "local-receipt-example"}],
            "claim_summary": {"summary": "Evidence is ready for reviewer inspection."},
            "changed_files": [{"path": "runner/example.py"}],
            "validation_truth": [{"execution_status": "passed"}],
            "scope_evidence": [{"scope_result": "in_scope"}],
            "known_risks": [{"risk_id": "review_required"}],
            "known_gaps": [],
            "reviewer_questions": [{"question_id": "accept_or_fix", "text": "Choose a review decision."}],
            "generated_at": "2026-06-30T00:00:00+08:00",
        }

    def test_generator_outputs_schema_valid_package_without_decision(self) -> None:
        result = generate_reviewer_handoff_package(self.inputs())

        assert result["generation_status"] == HANDOFF_PACKAGE_GENERATED
        assert result["schema_validation_result"]["handoff_schema_check_result"] == HANDOFF_SCHEMA_CHECK_PASSED
        assert result["reviewer_handoff_package"]["allowed_review_decisions"] == list(ALLOWED_REVIEW_DECISIONS)
        assert result["recommended_decision"] is None
        assert result["review_decision_created"] is False
        assert result["delivery_state_accepted"] is False

    def test_missing_validation_truth_blocks_handoff(self) -> None:
        inputs = self.inputs()
        inputs["validation_truth"] = []

        result = generate_reviewer_handoff_package(inputs)

        assert result["generation_status"] == HANDOFF_GENERATION_FAILED_CLOSED
        assert "validation_truth" in result["schema_validation_result"]["rejected_fields"]

    def test_missing_schema_ref_blocks_handoff_without_acceptance(self) -> None:
        inputs = self.inputs()
        inputs["reviewer_handoff_schema_ref"] = {}

        result = generate_reviewer_handoff_package(inputs)

        assert result["generation_status"] == BLOCKED_FOR_REVIEWER_HANDOFF
        assert "reviewer_handoff_schema_ref" in result["missing_input_report"]["missing_inputs"]
        assert result["review_decision_created"] is False

    def test_allowed_review_decisions_are_not_expanded_from_inputs(self) -> None:
        inputs = self.inputs()
        inputs["allowed_review_decisions"] = ["ACCEPT", "AUTO_ACCEPT"]

        result = generate_reviewer_handoff_package(inputs)

        assert result["reviewer_handoff_package"]["allowed_review_decisions"] == list(ALLOWED_REVIEW_DECISIONS)

    def test_forbidden_accept_recommendation_fails_closed(self) -> None:
        inputs = self.inputs()
        inputs["recommend_accept"] = True

        result = generate_reviewer_handoff_package(inputs)

        assert result["generation_status"] == HANDOFF_GENERATION_FAILED_CLOSED
        assert "FORBIDDEN_GENERATOR_INPUT_CLAIM" in {item["code"] for item in result["failures_and_blockers"]}

    def test_known_risks_are_preserved(self) -> None:
        result = generate_reviewer_handoff_package(self.inputs())

        assert result["reviewer_handoff_package"]["known_risks"][0]["risk_id"] == "review_required"

    def test_non_object_inputs_fail_closed(self) -> None:
        result = generate_reviewer_handoff_package("not inputs")  # type: ignore[arg-type]

        assert result["generation_status"] == HANDOFF_GENERATION_FAILED_CLOSED
        assert "GENERATOR_INPUTS_INVALID" in {item["code"] for item in result["failures_and_blockers"]}

    def test_result_contract_rejects_delivery_state_accepted(self) -> None:
        result = generate_reviewer_handoff_package(self.inputs())
        mutated = copy.deepcopy(result)
        mutated["delivery_state_accepted"] = True

        with self.assertRaises(ReviewerHandoffGeneratorError) as raised:
            assert_reviewer_handoff_generator_result_contract(mutated)

        assert raised.exception.error_code == "FORBIDDEN_HANDOFF_GENERATOR_RESULT_CLAIM"


if __name__ == "__main__":
    unittest.main()
