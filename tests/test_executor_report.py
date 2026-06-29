from __future__ import annotations

import copy
import unittest

from runner.executor_report import (
    EXECUTOR_REPORT_FAILED_CLOSED,
    EXECUTOR_REPORT_READY,
    ExecutorReportError,
    assert_executor_report_contract,
    build_executor_report,
)
from runner.imported_execution_receipt import (
    AUTHORITY_BOUNDARY_EXPECTATIONS as IMPORTED_AUTHORITY_BOUNDARY,
    validate_imported_execution_receipt,
)
from runner.local_execution_receipt import validate_local_execution_receipt


class ExecutorReportTests(unittest.TestCase):
    def local_receipt(self) -> dict:
        return {
            "receipt_id": "local-receipt-example",
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
            "execution_result": "executed",
            "command_attempts": [{"command": "python -m unittest tests.test_example", "exit_code": 0, "result": "passed"}],
            "touched_files": ["runner/example.py"],
            "observed_mutations": [{"path": "runner/example.py", "mutation_type": "modified"}],
            "validation_commands": ["python -m unittest tests.test_example"],
            "validation_results": [{"command": "python -m unittest tests.test_example", "result": "passed"}],
            "validation_summary": "passed",
            "scope_check_result": "passed",
            "blocked_or_failed_reasons": [],
            "known_gaps": [],
            "remaining_risks": [{"risk_id": "review_required", "risk": "Reviewer has not accepted delivery."}],
        }

    def imported_receipt(self) -> dict:
        return {
            "receipt_id": "imported-receipt-example",
            "receipt_kind": "imported_execution_receipt",
            "imported_receipt_authorization_ref": {"authorization_id": "commander-import-auth"},
            "source_provenance": {"source_type": "manual_report", "source_ref": "external-report"},
            "source_receipt_hash": "a" * 64,
            "version_taskbook_ref": {"version_id": "stage_04_v4_4_imported_execution_receipt_v1"},
            "master_taskbook_hash": "1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34",
            "stage_taskbook_hash": "05e6114a666942c0641c635905c2295feaa62b98bd9e7b5166babd662e015a41",
            "claimed_execution_envelope_ref": {"envelope_id": "external-envelope-claim"},
            "claimed_commands": [{"claim_status": "claimed", "command": "python -m unittest tests.test_example"}],
            "claimed_touched_files": [{"claim_status": "claimed", "path": "runner/example.py"}],
            "claimed_mutations": [{"claim_status": "claimed", "path": "runner/example.py", "mutation_type": "modified"}],
            "claimed_validation_results": [
                {"claim_status": "claimed", "command": "python -m unittest tests.test_example", "result": "passed"}
            ],
            "confidence_level": "medium",
            "known_gaps": [{"gap_id": "external_runtime_not_verified"}],
            "adoption_blockers": [{"blocker_id": "separate_adoption_authority_required"}],
            "authority_boundary": dict(IMPORTED_AUTHORITY_BOUNDARY),
        }

    def build_report(self, records: list[dict]) -> dict:
        return build_executor_report(
            executor_report_id="executor-report-example",
            version_taskbook_ref={"version_id": "stage_04_v4_5_taskbook_bound_executor_report_v1"},
            master_taskbook_hash="1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34",
            stage_taskbook_hash="05e6114a666942c0641c635905c2295feaa62b98bd9e7b5166babd662e015a41",
            receipt_records=records,
        )

    def local_record(self) -> dict:
        receipt = self.local_receipt()
        return {
            "receipt_ref": {"receipt_id": receipt["receipt_id"], "receipt_kind": receipt["receipt_kind"]},
            "authority_mode": "local_execution",
            "receipt": receipt,
            "receipt_validation_result": validate_local_execution_receipt(receipt),
        }

    def imported_record(self) -> dict:
        receipt = self.imported_receipt()
        return {
            "receipt_ref": {"receipt_id": receipt["receipt_id"], "receipt_kind": receipt["receipt_kind"]},
            "authority_mode": "imported_execution",
            "receipt": receipt,
            "receipt_validation_result": validate_imported_execution_receipt(receipt),
        }

    def test_local_receipt_report_case_is_reviewable_not_accepting(self) -> None:
        report = self.build_report([self.local_record()])

        assert report["report_status"] == EXECUTOR_REPORT_READY
        assert report["receipt_refs"][0]["authority_mode"] == "local_execution"
        assert report["command_result_summary"][0]["receipt_ref"]["receipt_id"] == "local-receipt-example"
        assert report["command_result_summary"][0]["claim_status"] == "observed"
        assert report["review_accepted"] is False
        assert report["delivery_state_accepted"] is False

    def test_imported_receipt_report_case_preserves_claim_boundary(self) -> None:
        report = self.build_report([self.imported_record()])

        assert report["report_status"] == EXECUTOR_REPORT_READY
        assert report["receipt_refs"][0]["authority_mode"] == "imported_execution"
        assert report["command_result_summary"][0]["claim_status"] == "claimed"
        assert report["changed_files_summary"][0]["claim_status"] == "claimed"
        assert report["imported_receipt_adopted_as_fact"] is False

    def test_mixed_report_preserves_receipt_refs_and_authority_modes(self) -> None:
        report = self.build_report([self.local_record(), self.imported_record()])

        assert report["report_status"] == EXECUTOR_REPORT_READY
        assert report["authority_modes"] == ["imported_execution", "local_execution"]
        assert len(report["receipt_refs"]) == 2
        assert len(report["validation_truth_summary"]) == 2

    def test_empty_receipt_records_fail_closed(self) -> None:
        report = self.build_report([])

        assert report["report_status"] == EXECUTOR_REPORT_FAILED_CLOSED
        assert "receipt_records_missing" in {item["code"] for item in report["failures_and_blockers"]}

    def test_receipt_without_ref_fails_closed(self) -> None:
        record = self.local_record()
        record["receipt_ref"] = {}

        report = self.build_report([record])

        assert report["report_status"] == EXECUTOR_REPORT_FAILED_CLOSED
        assert "receipt_ref_missing" in {item["code"] for item in report["failures_and_blockers"]}

    def test_unsupported_authority_mode_fails_closed(self) -> None:
        record = self.local_record()
        record["authority_mode"] = "ambient_execution"

        report = self.build_report([record])

        assert report["report_status"] == EXECUTOR_REPORT_FAILED_CLOSED
        assert "authority_mode_unsupported" in {item["code"] for item in report["failures_and_blockers"]}

    def test_validation_passed_without_command_evidence_fails_closed(self) -> None:
        record = self.imported_record()
        record["receipt"]["claimed_commands"] = []

        report = self.build_report([record])

        assert report["report_status"] == EXECUTOR_REPORT_FAILED_CLOSED
        assert "validation_passed_without_command_evidence" in {item["code"] for item in report["failures_and_blockers"]}

    def test_forbidden_review_acceptance_claim_fails_closed(self) -> None:
        record = self.local_record()
        record["receipt"]["review_accepted"] = True

        report = self.build_report([record])

        assert report["report_status"] == EXECUTOR_REPORT_FAILED_CLOSED
        assert "forbidden_report_authority_claim" in {item["code"] for item in report["failures_and_blockers"]}

    def test_result_contract_rejects_delivery_state_accepted(self) -> None:
        report = self.build_report([self.local_record()])
        mutated = copy.deepcopy(report)
        mutated["delivery_state_accepted"] = True

        with self.assertRaises(ExecutorReportError) as raised:
            assert_executor_report_contract(mutated)

        assert raised.exception.error_code == "FORBIDDEN_EXECUTOR_REPORT_RESULT_CLAIM"

    def test_result_contract_rejects_authority_boundary_mutation(self) -> None:
        report = self.build_report([self.local_record()])
        mutated = copy.deepcopy(report)
        mutated["authority_boundary"]["executor_report_writes_delivery_state"] = True

        with self.assertRaises(ExecutorReportError) as raised:
            assert_executor_report_contract(mutated)

        assert raised.exception.error_code == "FORBIDDEN_EXECUTOR_REPORT_AUTHORITY_CLAIM"


if __name__ == "__main__":
    unittest.main()
