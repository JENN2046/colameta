from __future__ import annotations

import copy
import unittest

from runner.execution_evidence_receipt import (
    EVIDENCE_RECEIPT_FAILED_CLOSED,
    EVIDENCE_RECEIPT_READY,
    ExecutionEvidenceReceiptError,
    assert_execution_evidence_receipt_contract,
    build_execution_evidence_receipt,
)


class ExecutionEvidenceReceiptTests(unittest.TestCase):
    def report(self) -> dict:
        from tests.test_executor_report import ExecutorReportTests

        helper = ExecutorReportTests("test_mixed_report_preserves_receipt_refs_and_authority_modes")
        return helper.build_report([helper.local_record(), helper.imported_record()])

    def build_receipt(self, records: list[dict], evidence_hashes: dict | None = None) -> dict:
        return build_execution_evidence_receipt(
            evidence_receipt_id="execution-evidence-receipt-example",
            version_taskbook_ref={"version_id": "stage_04_v4_6_execution_evidence_receipt_v1"},
            master_taskbook_hash="1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34",
            stage_taskbook_hash="05e6114a666942c0641c635905c2295feaa62b98bd9e7b5166babd662e015a41",
            executor_report_records=records,
            evidence_hashes=evidence_hashes if evidence_hashes is not None else {"executor_report": "b" * 64, "local_receipt": "c" * 64},
        )

    def report_record(self) -> dict:
        return {
            "executor_report_ref": {"executor_report_id": "executor-report-example", "report_schema_version": "executor_report.v1"},
            "executor_report": self.report(),
        }

    def test_evidence_receipt_binds_report_and_receipt_refs(self) -> None:
        receipt = self.build_receipt([self.report_record()])

        assert receipt["evidence_receipt_status"] == EVIDENCE_RECEIPT_READY
        assert len(receipt["executor_report_refs"]) == 1
        assert len(receipt["execution_receipt_refs"]) == 2
        assert receipt["changed_files_summary_ref"]["item_count"] == 2
        assert receipt["validation_truth_summary_ref"]["item_count"] == 2
        assert receipt["review_accepted"] is False
        assert receipt["delivery_state_accepted"] is False

    def test_known_gaps_and_remaining_risks_are_preserved(self) -> None:
        receipt = self.build_receipt([self.report_record()])

        assert receipt["known_gaps"]
        assert receipt["remaining_risks"]
        assert receipt["known_gaps"][0]["executor_report_ref"]["executor_report_id"] == "executor-report-example"

    def test_missing_report_records_fail_closed(self) -> None:
        receipt = self.build_receipt([])

        assert receipt["evidence_receipt_status"] == EVIDENCE_RECEIPT_FAILED_CLOSED
        assert "executor_report_records_missing" in {item["code"] for item in receipt["failures_and_blockers"]}

    def test_missing_report_ref_fails_closed(self) -> None:
        record = self.report_record()
        record["executor_report_ref"] = {}

        receipt = self.build_receipt([record])

        assert receipt["evidence_receipt_status"] == EVIDENCE_RECEIPT_FAILED_CLOSED
        assert "executor_report_ref_missing" in {item["code"] for item in receipt["failures_and_blockers"]}

    def test_report_without_receipt_refs_fails_closed(self) -> None:
        record = self.report_record()
        record["executor_report"]["receipt_refs"] = []

        receipt = self.build_receipt([record])

        assert receipt["evidence_receipt_status"] == EVIDENCE_RECEIPT_FAILED_CLOSED
        assert "execution_receipt_refs_missing" in {item["code"] for item in receipt["failures_and_blockers"]}

    def test_missing_evidence_hashes_fail_closed(self) -> None:
        receipt = self.build_receipt([self.report_record()], evidence_hashes={})

        assert receipt["evidence_receipt_status"] == EVIDENCE_RECEIPT_FAILED_CLOSED
        assert "evidence_hashes_invalid" in {item["code"] for item in receipt["failures_and_blockers"]}

    def test_invalid_evidence_hash_fails_closed(self) -> None:
        receipt = self.build_receipt([self.report_record()], evidence_hashes={"executor_report": "not-a-sha"})

        assert receipt["evidence_receipt_status"] == EVIDENCE_RECEIPT_FAILED_CLOSED
        assert "evidence_hashes_invalid" in {item["code"] for item in receipt["failures_and_blockers"]}

    def test_report_authority_claim_fails_closed(self) -> None:
        record = self.report_record()
        record["executor_report"]["review_accepted"] = True

        receipt = self.build_receipt([record])

        assert receipt["evidence_receipt_status"] == EVIDENCE_RECEIPT_FAILED_CLOSED
        assert "executor_report_contract_failed" in {item["code"] for item in receipt["failures_and_blockers"]}

    def test_result_contract_rejects_delivery_state_accepted(self) -> None:
        receipt = self.build_receipt([self.report_record()])
        mutated = copy.deepcopy(receipt)
        mutated["delivery_state_accepted"] = True

        with self.assertRaises(ExecutionEvidenceReceiptError) as raised:
            assert_execution_evidence_receipt_contract(mutated)

        assert raised.exception.error_code == "FORBIDDEN_EVIDENCE_RECEIPT_RESULT_CLAIM"

    def test_result_contract_rejects_authority_boundary_mutation(self) -> None:
        receipt = self.build_receipt([self.report_record()])
        mutated = copy.deepcopy(receipt)
        mutated["authority_boundary"]["evidence_receipt_writes_delivery_state"] = True

        with self.assertRaises(ExecutionEvidenceReceiptError) as raised:
            assert_execution_evidence_receipt_contract(mutated)

        assert raised.exception.error_code == "FORBIDDEN_EVIDENCE_RECEIPT_AUTHORITY_CLAIM"


if __name__ == "__main__":
    unittest.main()
