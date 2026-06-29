from __future__ import annotations

import copy
import unittest

from runner.local_execution_receipt import (
    RECEIPT_CHECK_FAILED_CLOSED,
    RECEIPT_CHECK_PASSED,
    LocalExecutionReceiptError,
    assert_local_execution_receipt_result_contract,
    validate_local_execution_receipt,
)


class LocalExecutionReceiptTests(unittest.TestCase):
    def valid_receipt(self, execution_result: str = "executed", validation_result: str = "passed") -> dict:
        return {
            "receipt_id": "local-execution-receipt-example",
            "receipt_schema_version": "local_execution_receipt.v1",
            "receipt_kind": "local_execution_receipt",
            "local_execution_authorization_ref": {"authorization_id": "local-exec-auth"},
            "execution_envelope_ref": {"envelope_id": "execution-envelope-example"},
            "run_preview_ref": {"run_preview_id": "run-preview-example"},
            "version_taskbook_ref": {"version_id": "stage_04_v4_3_taskbook_bound_local_execution_receipt_v1"},
            "master_taskbook_hash": "1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34",
            "stage_taskbook_hash": "05e6114a666942c0641c635905c2295feaa62b98bd9e7b5166babd662e015a41",
            "started_at": "2026-06-30T00:00:00+08:00",
            "completed_at": "2026-06-30T00:01:00+08:00",
            "execution_result": execution_result,
            "command_attempts": [
                {"command": "python -m unittest tests.test_example", "exit_code": 0, "result": "passed"}
            ],
            "touched_files": ["runner/example.py", "tests/test_example.py"],
            "observed_mutations": [{"path": "runner/example.py", "mutation_type": "modified"}],
            "validation_commands": ["python -m unittest tests.test_example"],
            "validation_results": [{"command": "python -m unittest tests.test_example", "result": validation_result}],
            "validation_summary": validation_result,
            "scope_check_result": "passed",
            "blocked_or_failed_reasons": [],
            "known_gaps": [],
            "remaining_risks": [{"risk_id": "review_required", "risk": "Reviewer has not accepted delivery."}],
        }

    def test_executed_receipt_passes_without_self_acceptance(self) -> None:
        result = validate_local_execution_receipt(self.valid_receipt())

        assert result["receipt_check_result"] == RECEIPT_CHECK_PASSED
        assert result["execution_result"] == "executed"
        assert result["truth_distinction"]["executed_is_reviewed"] is False
        assert result["truth_distinction"]["receipt_self_accepts_delivery"] is False
        assert result["review_accepted"] is False
        assert result["delivery_state_accepted"] is False

    def test_blocked_before_execution_receipt_can_be_truthful(self) -> None:
        receipt = self.valid_receipt("blocked_before_execution", "not_run")
        receipt["command_attempts"] = []
        receipt["touched_files"] = []
        receipt["observed_mutations"] = []
        receipt["scope_check_result"] = "blocked"
        receipt["known_gaps"] = [{"gap_id": "touched_files_unknown", "reason": "Execution was blocked before file access."}]
        receipt["blocked_or_failed_reasons"] = [{"code": "authorization_missing"}]

        result = validate_local_execution_receipt(receipt)

        assert result["receipt_check_result"] == RECEIPT_CHECK_PASSED
        assert result["execution_result"] == "blocked_before_execution"

    def test_validation_failed_case_can_be_truthful(self) -> None:
        receipt = self.valid_receipt("executed_with_failures", "failed")
        receipt["validation_summary"] = "failed"
        receipt["blocked_or_failed_reasons"] = [{"code": "validation_failed"}]

        result = validate_local_execution_receipt(receipt)

        assert result["receipt_check_result"] == RECEIPT_CHECK_PASSED
        assert result["execution_result"] == "executed_with_failures"

    def test_scope_violation_case_can_be_truthful(self) -> None:
        receipt = self.valid_receipt("failed_scope_check", "blocked")
        receipt["scope_check_result"] = "failed"
        receipt["blocked_or_failed_reasons"] = [{"code": "scope_violation"}]

        result = validate_local_execution_receipt(receipt)

        assert result["receipt_check_result"] == RECEIPT_CHECK_PASSED
        assert result["execution_result"] == "failed_scope_check"

    def test_missing_local_execution_authorization_ref_fails_closed(self) -> None:
        receipt = self.valid_receipt()
        receipt["local_execution_authorization_ref"] = {}

        result = validate_local_execution_receipt(receipt)

        assert result["receipt_check_result"] == RECEIPT_CHECK_FAILED_CLOSED
        assert "local_execution_authorization_ref" in result["rejected_fields"]

    def test_missing_execution_result_fails_closed(self) -> None:
        receipt = self.valid_receipt()
        del receipt["execution_result"]

        result = validate_local_execution_receipt(receipt)

        assert result["receipt_check_result"] == RECEIPT_CHECK_FAILED_CLOSED
        assert "execution_result" in result["rejected_fields"]

    def test_touched_files_unknown_without_known_gap_fails_closed(self) -> None:
        receipt = self.valid_receipt()
        receipt["touched_files"] = []

        result = validate_local_execution_receipt(receipt)

        assert result["receipt_check_result"] == RECEIPT_CHECK_FAILED_CLOSED
        assert "TOUCHED_FILES_UNKNOWN_WITHOUT_KNOWN_GAP" in {item["code"] for item in result["rejection_reasons"]}

    def test_validation_failed_but_summary_claims_passed_fails_closed(self) -> None:
        receipt = self.valid_receipt("executed_with_failures", "failed")
        receipt["validation_summary"] = "passed"

        result = validate_local_execution_receipt(receipt)

        assert result["receipt_check_result"] == RECEIPT_CHECK_FAILED_CLOSED
        assert "VALIDATION_FAILED_BUT_SUMMARY_CLAIMS_PASSED" in {item["code"] for item in result["rejection_reasons"]}

    def test_forbidden_review_acceptance_claim_fails_closed(self) -> None:
        receipt = self.valid_receipt()
        receipt["review_accepted"] = True

        result = validate_local_execution_receipt(receipt)

        assert result["receipt_check_result"] == RECEIPT_CHECK_FAILED_CLOSED
        assert "FORBIDDEN_RECEIPT_AUTHORITY_CLAIM" in {item["code"] for item in result["rejection_reasons"]}

    def test_result_contract_rejects_delivery_state_accepted(self) -> None:
        result = validate_local_execution_receipt(self.valid_receipt())
        mutated = copy.deepcopy(result)
        mutated["delivery_state_accepted"] = True

        with self.assertRaises(LocalExecutionReceiptError) as raised:
            assert_local_execution_receipt_result_contract(mutated)

        assert raised.exception.error_code == "FORBIDDEN_RECEIPT_RESULT_CLAIM"

    def test_result_contract_rejects_authority_boundary_mutation(self) -> None:
        result = validate_local_execution_receipt(self.valid_receipt())
        mutated = copy.deepcopy(result)
        mutated["authority_boundary"]["receipt_writes_delivery_state"] = True

        with self.assertRaises(LocalExecutionReceiptError) as raised:
            assert_local_execution_receipt_result_contract(mutated)

        assert raised.exception.error_code == "FORBIDDEN_RECEIPT_RESULT_AUTHORITY_CLAIM"

    def test_non_object_receipt_fails_closed(self) -> None:
        result = validate_local_execution_receipt("not a receipt")  # type: ignore[arg-type]

        assert result["receipt_check_result"] == RECEIPT_CHECK_FAILED_CLOSED
        assert result["recognized_fields"] == []
        assert result["rejection_reasons"][0]["code"] == "RECEIPT_INVALID"


if __name__ == "__main__":
    unittest.main()
