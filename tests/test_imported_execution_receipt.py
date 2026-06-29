from __future__ import annotations

import copy
import unittest

from runner.imported_execution_receipt import (
    AUTHORITY_BOUNDARY_EXPECTATIONS,
    IMPORTED_RECEIPT_CHECK_FAILED_CLOSED,
    IMPORTED_RECEIPT_CHECK_PASSED,
    ImportedExecutionReceiptError,
    assert_imported_execution_receipt_result_contract,
    validate_imported_execution_receipt,
)


class ImportedExecutionReceiptTests(unittest.TestCase):
    def valid_receipt(self) -> dict:
        return {
            "receipt_id": "imported-execution-receipt-example",
            "receipt_kind": "imported_execution_receipt",
            "imported_receipt_authorization_ref": {"authorization_id": "commander-import-auth"},
            "source_provenance": {
                "source_type": "commander_supplied_report",
                "source_ref": "external-receipt-example",
                "observed_at": "2026-06-30T00:00:00+08:00",
            },
            "source_receipt_hash": "a" * 64,
            "version_taskbook_ref": {"version_id": "stage_04_v4_4_imported_execution_receipt_v1"},
            "master_taskbook_hash": "1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34",
            "stage_taskbook_hash": "05e6114a666942c0641c635905c2295feaa62b98bd9e7b5166babd662e015a41",
            "claimed_execution_envelope_ref": {"envelope_id": "external-envelope-claim"},
            "claimed_commands": [
                {"claim_status": "claimed", "command": "python -m unittest tests.test_example", "claimed_result": "passed"}
            ],
            "claimed_touched_files": [{"claim_status": "claimed", "path": "runner/example.py"}],
            "claimed_mutations": [{"claim_status": "claimed", "path": "runner/example.py", "mutation_type": "modified"}],
            "claimed_validation_results": [
                {"claim_status": "claimed", "command": "python -m unittest tests.test_example", "result": "passed"}
            ],
            "confidence_level": "medium",
            "known_gaps": [{"gap_id": "cannot_verify_source_runtime", "reason": "Source runtime is external to this repo."}],
            "adoption_blockers": [
                {"blocker_id": "separate_adoption_authority_required", "reason": "Import is not adopted as fact."}
            ],
            "authority_boundary": dict(AUTHORITY_BOUNDARY_EXPECTATIONS),
        }

    def test_valid_imported_receipt_passes_as_claim_only_evidence(self) -> None:
        result = validate_imported_execution_receipt(self.valid_receipt())

        assert result["imported_receipt_check_result"] == IMPORTED_RECEIPT_CHECK_PASSED
        assert result["claim_distinction"]["imported_receipt_is_local_execution"] is False
        assert result["claim_distinction"]["claimed_commands_are_verified_facts"] is False
        assert result["local_execution_performed"] is False
        assert result["imported_receipt_adopted_as_fact"] is False
        assert result["review_accepted"] is False
        assert result["delivery_state_accepted"] is False

    def test_missing_import_authorization_ref_fails_closed(self) -> None:
        receipt = self.valid_receipt()
        receipt["imported_receipt_authorization_ref"] = {}

        result = validate_imported_execution_receipt(receipt)

        assert result["imported_receipt_check_result"] == IMPORTED_RECEIPT_CHECK_FAILED_CLOSED
        assert "imported_receipt_authorization_ref" in result["rejected_fields"]

    def test_invalid_source_hash_fails_closed(self) -> None:
        receipt = self.valid_receipt()
        receipt["source_receipt_hash"] = "not-a-sha"

        result = validate_imported_execution_receipt(receipt)

        assert result["imported_receipt_check_result"] == IMPORTED_RECEIPT_CHECK_FAILED_CLOSED
        assert "source_receipt_hash" in result["rejected_fields"]

    def test_claimed_command_without_claim_label_fails_closed(self) -> None:
        receipt = self.valid_receipt()
        receipt["claimed_commands"][0].pop("claim_status")

        result = validate_imported_execution_receipt(receipt)

        assert result["imported_receipt_check_result"] == IMPORTED_RECEIPT_CHECK_FAILED_CLOSED
        assert "CLAIMED_ITEM_NOT_LABELED_AS_CLAIM" in {item["code"] for item in result["rejection_reasons"]}

    def test_claimed_mutations_must_be_a_list(self) -> None:
        receipt = self.valid_receipt()
        receipt["claimed_mutations"] = {"claim_status": "claimed", "path": "runner/example.py"}

        result = validate_imported_execution_receipt(receipt)

        assert result["imported_receipt_check_result"] == IMPORTED_RECEIPT_CHECK_FAILED_CLOSED
        assert "claimed_mutations" in result["rejected_fields"]

    def test_empty_adoption_blockers_fails_closed(self) -> None:
        receipt = self.valid_receipt()
        receipt["adoption_blockers"] = []

        result = validate_imported_execution_receipt(receipt)

        assert result["imported_receipt_check_result"] == IMPORTED_RECEIPT_CHECK_FAILED_CLOSED
        assert "ADOPTION_BLOCKERS_REQUIRED" in {item["code"] for item in result["rejection_reasons"]}

    def test_local_dispatch_authority_claim_fails_closed(self) -> None:
        receipt = self.valid_receipt()
        receipt["local_dispatch_authorized"] = True

        result = validate_imported_execution_receipt(receipt)

        assert result["imported_receipt_check_result"] == IMPORTED_RECEIPT_CHECK_FAILED_CLOSED
        assert "FORBIDDEN_IMPORTED_RECEIPT_AUTHORITY_CLAIM" in {item["code"] for item in result["rejection_reasons"]}

    def test_imported_receipt_adoption_claim_fails_closed(self) -> None:
        receipt = self.valid_receipt()
        receipt["imported_receipt_adopted_as_fact"] = True

        result = validate_imported_execution_receipt(receipt)

        assert result["imported_receipt_check_result"] == IMPORTED_RECEIPT_CHECK_FAILED_CLOSED
        assert "FORBIDDEN_IMPORTED_RECEIPT_AUTHORITY_CLAIM" in {item["code"] for item in result["rejection_reasons"]}

    def test_authority_boundary_must_remain_false(self) -> None:
        receipt = self.valid_receipt()
        receipt["authority_boundary"]["imported_receipt_writes_delivery_state"] = True

        result = validate_imported_execution_receipt(receipt)

        assert result["imported_receipt_check_result"] == IMPORTED_RECEIPT_CHECK_FAILED_CLOSED
        assert "authority_boundary" in result["rejected_fields"]

    def test_result_contract_rejects_delivery_state_accepted(self) -> None:
        result = validate_imported_execution_receipt(self.valid_receipt())
        mutated = copy.deepcopy(result)
        mutated["delivery_state_accepted"] = True

        with self.assertRaises(ImportedExecutionReceiptError) as raised:
            assert_imported_execution_receipt_result_contract(mutated)

        assert raised.exception.error_code == "FORBIDDEN_IMPORTED_RECEIPT_RESULT_CLAIM"

    def test_result_contract_rejects_authority_boundary_mutation(self) -> None:
        result = validate_imported_execution_receipt(self.valid_receipt())
        mutated = copy.deepcopy(result)
        mutated["authority_boundary"]["imported_receipt_adopted_as_fact"] = True

        with self.assertRaises(ImportedExecutionReceiptError) as raised:
            assert_imported_execution_receipt_result_contract(mutated)

        assert raised.exception.error_code == "FORBIDDEN_IMPORTED_RECEIPT_RESULT_AUTHORITY_CLAIM"

    def test_non_object_receipt_fails_closed(self) -> None:
        result = validate_imported_execution_receipt("not a receipt")  # type: ignore[arg-type]

        assert result["imported_receipt_check_result"] == IMPORTED_RECEIPT_CHECK_FAILED_CLOSED
        assert result["recognized_fields"] == []
        assert result["rejection_reasons"][0]["code"] == "IMPORTED_RECEIPT_INVALID"


if __name__ == "__main__":
    unittest.main()
