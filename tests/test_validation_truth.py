from __future__ import annotations

import copy
import unittest

from runner.validation_truth import (
    AUTHORITY_BOUNDARY_EXPECTATIONS,
    VALIDATION_TRUTH_CHECK_FAILED_CLOSED,
    VALIDATION_TRUTH_CHECK_PASSED,
    ValidationTruthError,
    assert_validation_truth_result_contract,
    validate_validation_truth,
)


class ValidationTruthTests(unittest.TestCase):
    def validation_truth(self, execution_status: str = "passed") -> dict:
        return {
            "validation_truth_id": f"validation-truth-{execution_status}",
            "validation_command": ".venv/bin/python -m unittest tests.test_example",
            "command_source_ref": {"source": "version_taskbook.acceptance_commands"},
            "execution_status": execution_status,
            "exit_code": 0 if execution_status == "passed" else 1 if execution_status == "failed" else None,
            "output_summary": "Ran 1 test ... OK" if execution_status == "passed" else "",
            "evidence_ref": {"evidence_id": "example-evidence"},
            "failure_reason": "assertion failed" if execution_status == "failed" else "",
            "blocker_reason": "authorization missing" if execution_status in {"blocked", "not_run"} else "",
            "known_gaps": [{"gap_id": "not_checked"}] if execution_status == "unvalidated" else [],
            "authority_boundary": dict(AUTHORITY_BOUNDARY_EXPECTATIONS),
        }

    def test_passed_with_command_evidence_passes(self) -> None:
        result = validate_validation_truth(self.validation_truth("passed"))

        assert result["validation_truth_check_result"] == VALIDATION_TRUTH_CHECK_PASSED
        assert result["execution_status"] == "passed"
        assert result["truth_boundary"]["runtime_label_alone_as_truth"] is False
        assert result["delivery_state_accepted"] is False

    def test_failed_with_failure_reason_passes_without_summarizing_passed(self) -> None:
        result = validate_validation_truth(self.validation_truth("failed"))

        assert result["validation_truth_check_result"] == VALIDATION_TRUTH_CHECK_PASSED
        assert result["execution_status"] == "failed"

    def test_blocked_with_blocker_reason_passes(self) -> None:
        result = validate_validation_truth(self.validation_truth("blocked"))

        assert result["validation_truth_check_result"] == VALIDATION_TRUTH_CHECK_PASSED
        assert result["execution_status"] == "blocked"

    def test_not_run_with_blocker_reason_passes(self) -> None:
        result = validate_validation_truth(self.validation_truth("not_run"))

        assert result["validation_truth_check_result"] == VALIDATION_TRUTH_CHECK_PASSED
        assert result["execution_status"] == "not_run"

    def test_unvalidated_with_known_gap_passes(self) -> None:
        result = validate_validation_truth(self.validation_truth("unvalidated"))

        assert result["validation_truth_check_result"] == VALIDATION_TRUTH_CHECK_PASSED
        assert result["execution_status"] == "unvalidated"

    def test_failed_summarized_as_passed_fails_closed(self) -> None:
        truth = self.validation_truth("failed")
        truth["summary_status"] = "passed"

        result = validate_validation_truth(truth)

        assert result["validation_truth_check_result"] == VALIDATION_TRUTH_CHECK_FAILED_CLOSED
        assert "FAILED_SUMMARIZED_AS_PASSED" in {item["code"] for item in result["rejection_reasons"]}

    def test_not_run_summarized_as_passed_fails_closed(self) -> None:
        truth = self.validation_truth("not_run")
        truth["summary_status"] = "passed"

        result = validate_validation_truth(truth)

        assert result["validation_truth_check_result"] == VALIDATION_TRUTH_CHECK_FAILED_CLOSED
        assert "NOT_RUN_SUMMARIZED_AS_PASSED" in {item["code"] for item in result["rejection_reasons"]}

    def test_passed_without_evidence_ref_fails_closed(self) -> None:
        truth = self.validation_truth("passed")
        truth["evidence_ref"] = {}

        result = validate_validation_truth(truth)

        assert result["validation_truth_check_result"] == VALIDATION_TRUTH_CHECK_FAILED_CLOSED
        assert "PASSED_WITHOUT_EVIDENCE_REF" in {item["code"] for item in result["rejection_reasons"]}

    def test_runtime_passed_label_alone_fails_closed(self) -> None:
        truth = self.validation_truth("passed")
        truth["runtime_label"] = "PASSED"
        truth["evidence_ref"] = {}
        truth["command_source_ref"] = {}

        result = validate_validation_truth(truth)

        assert result["validation_truth_check_result"] == VALIDATION_TRUTH_CHECK_FAILED_CLOSED
        assert "RUNTIME_LABEL_ALONE_AS_TRUTH" in {item["code"] for item in result["rejection_reasons"]}

    def test_delivery_state_claim_fails_closed(self) -> None:
        truth = self.validation_truth("passed")
        truth["delivery_state_accepted"] = True

        result = validate_validation_truth(truth)

        assert result["validation_truth_check_result"] == VALIDATION_TRUTH_CHECK_FAILED_CLOSED
        assert "FORBIDDEN_VALIDATION_TRUTH_AUTHORITY_CLAIM" in {item["code"] for item in result["rejection_reasons"]}

    def test_result_contract_rejects_delivery_state_accepted(self) -> None:
        result = validate_validation_truth(self.validation_truth("passed"))
        mutated = copy.deepcopy(result)
        mutated["delivery_state_accepted"] = True

        with self.assertRaises(ValidationTruthError) as raised:
            assert_validation_truth_result_contract(mutated)

        assert raised.exception.error_code == "FORBIDDEN_VALIDATION_TRUTH_RESULT_CLAIM"

    def test_non_object_truth_fails_closed(self) -> None:
        result = validate_validation_truth("not truth")  # type: ignore[arg-type]

        assert result["validation_truth_check_result"] == VALIDATION_TRUTH_CHECK_FAILED_CLOSED
        assert result["recognized_fields"] == []
        assert result["rejection_reasons"][0]["code"] == "VALIDATION_TRUTH_INVALID"


if __name__ == "__main__":
    unittest.main()
