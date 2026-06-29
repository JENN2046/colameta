from __future__ import annotations

import copy
import unittest

from runner.reviewer_handoff_schema import (
    ALLOWED_REVIEW_DECISIONS,
    HANDOFF_SCHEMA_CHECK_FAILED_CLOSED,
    HANDOFF_SCHEMA_CHECK_PASSED,
    ReviewerHandoffSchemaError,
    assert_reviewer_handoff_schema_result_contract,
    validate_reviewer_handoff_package,
)


class ReviewerHandoffSchemaTests(unittest.TestCase):
    def package(self) -> dict:
        return {
            "handoff_package_id": "handoff-package-example",
            "handoff_schema_version": "reviewer_handoff_package.v1",
            "master_taskbook_ref": {"path": "PROJECT_MASTER_TASKBOOK.md"},
            "stage_taskbook_ref": {"path": "docs/taskbooks/stages/STAGE_05_REVIEWER_HANDOFF_PACKAGE.md"},
            "version_taskbook_ref": {"version_id": "stage_05_v5_1_reviewer_handoff_schema_v1"},
            "stage_4_audit_package_ref": {"audit_package_id": "audit-package-example"},
            "execution_receipt_refs": [{"receipt_id": "local-receipt-example"}],
            "claim_summary": {"summary": "Evidence is ready for reviewer inspection."},
            "changed_files": [{"path": "runner/example.py"}],
            "validation_truth": [{"execution_status": "passed"}],
            "scope_evidence": [{"scope_result": "in_scope"}],
            "known_risks": [{"risk_id": "review_required"}],
            "known_gaps": [],
            "reviewer_questions": [{"question_id": "accept_or_fix", "text": "Choose a review decision."}],
            "allowed_review_decisions": list(ALLOWED_REVIEW_DECISIONS),
            "forbidden_generator_claims": ["recommend_accept", "delivery_state_accepted"],
            "generated_at": "2026-06-30T00:00:00+08:00",
        }

    def test_valid_package_passes_without_acceptance(self) -> None:
        result = validate_reviewer_handoff_package(self.package())

        assert result["handoff_schema_check_result"] == HANDOFF_SCHEMA_CHECK_PASSED
        assert result["review_decision_created"] is False
        assert result["review_acceptance_recorded"] is False
        assert result["delivery_state_accepted"] is False

    def test_missing_master_ref_fails_closed(self) -> None:
        package = self.package()
        package["master_taskbook_ref"] = {}

        result = validate_reviewer_handoff_package(package)

        assert result["handoff_schema_check_result"] == HANDOFF_SCHEMA_CHECK_FAILED_CLOSED
        assert "master_taskbook_ref" in result["rejected_fields"]

    def test_missing_validation_truth_fails_closed(self) -> None:
        package = self.package()
        package["validation_truth"] = []

        result = validate_reviewer_handoff_package(package)

        assert result["handoff_schema_check_result"] == HANDOFF_SCHEMA_CHECK_FAILED_CLOSED
        assert "validation_truth" in result["rejected_fields"]

    def test_missing_changed_files_fails_closed(self) -> None:
        package = self.package()
        package["changed_files"] = []

        result = validate_reviewer_handoff_package(package)

        assert result["handoff_schema_check_result"] == HANDOFF_SCHEMA_CHECK_FAILED_CLOSED
        assert "changed_files" in result["rejected_fields"]

    def test_missing_reviewer_questions_fails_closed(self) -> None:
        package = self.package()
        package["reviewer_questions"] = []

        result = validate_reviewer_handoff_package(package)

        assert result["handoff_schema_check_result"] == HANDOFF_SCHEMA_CHECK_FAILED_CLOSED
        assert "reviewer_questions" in result["rejected_fields"]

    def test_allowed_review_decision_expansion_fails_closed(self) -> None:
        package = self.package()
        package["allowed_review_decisions"] = list(ALLOWED_REVIEW_DECISIONS) + ["AUTO_ACCEPT"]

        result = validate_reviewer_handoff_package(package)

        assert result["handoff_schema_check_result"] == HANDOFF_SCHEMA_CHECK_FAILED_CLOSED
        assert "ALLOWED_REVIEW_DECISIONS_MISMATCH" in {item["code"] for item in result["rejection_reasons"]}

    def test_allowed_review_decision_missing_value_fails_closed(self) -> None:
        package = self.package()
        package["allowed_review_decisions"] = ["ACCEPT", "NEEDS_FIX", "ABORT"]

        result = validate_reviewer_handoff_package(package)

        assert result["handoff_schema_check_result"] == HANDOFF_SCHEMA_CHECK_FAILED_CLOSED
        assert "allowed_review_decisions" in result["rejected_fields"]

    def test_generator_recommends_accept_fails_closed(self) -> None:
        package = self.package()
        package["recommend_accept"] = True

        result = validate_reviewer_handoff_package(package)

        assert result["handoff_schema_check_result"] == HANDOFF_SCHEMA_CHECK_FAILED_CLOSED
        assert "FORBIDDEN_GENERATOR_AUTHORITY_CLAIM" in {item["code"] for item in result["rejection_reasons"]}

    def test_recommended_accept_decision_fails_closed(self) -> None:
        package = self.package()
        package["recommended_decision"] = "ACCEPT"

        result = validate_reviewer_handoff_package(package)

        assert result["handoff_schema_check_result"] == HANDOFF_SCHEMA_CHECK_FAILED_CLOSED
        assert "GENERATOR_RECOMMENDS_ACCEPT" in {item["code"] for item in result["rejection_reasons"]}

    def test_result_contract_rejects_delivery_state_accepted(self) -> None:
        result = validate_reviewer_handoff_package(self.package())
        mutated = copy.deepcopy(result)
        mutated["delivery_state_accepted"] = True

        with self.assertRaises(ReviewerHandoffSchemaError) as raised:
            assert_reviewer_handoff_schema_result_contract(mutated)

        assert raised.exception.error_code == "FORBIDDEN_HANDOFF_SCHEMA_RESULT_CLAIM"

    def test_non_object_package_fails_closed(self) -> None:
        result = validate_reviewer_handoff_package("not package")  # type: ignore[arg-type]

        assert result["handoff_schema_check_result"] == HANDOFF_SCHEMA_CHECK_FAILED_CLOSED
        assert result["recognized_fields"] == []
        assert result["rejection_reasons"][0]["code"] == "HANDOFF_PACKAGE_INVALID"


if __name__ == "__main__":
    unittest.main()
