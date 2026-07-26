from __future__ import annotations

import copy
import unittest

from runner.audit_package_taskbook_binding import (
    AUDIT_PACKAGE_FAILED_CLOSED,
    AUDIT_PACKAGE_READY,
    BLOCKED_MISSING_EVIDENCE,
    BLOCKED_SCOPE_VIOLATION,
    BLOCKED_UNKNOWN_NEEDS_REVIEW,
    BLOCKED_VALIDATION_FAILURE,
    READY_FOR_REVIEWER_HANDOFF,
    AuditPackageTaskbookBindingError,
    assert_audit_package_taskbook_binding_contract,
    build_audit_package_taskbook_binding,
)


class AuditPackageTaskbookBindingTests(unittest.TestCase):
    def build_package(self, **overrides: object) -> dict:
        values = {
            "audit_package_id": "audit-package-example",
            "version_taskbook_ref": {"version_id": "stage_04_v4_9_audit_package_taskbook_binding_v1"},
            "master_taskbook_hash": "895b91afe29d32c9742c6f8b1d91b2f0507522deed875d5a7999cc484f351e63",
            "stage_taskbook_hash": "af9dac09893b49af08788ebeac9dfb569f89eb87f693625ef7cd41413de9c7ff",
            "execution_envelope_ref": {"envelope_id": "execution-envelope-example"},
            "run_preview_ref": {"run_preview_id": "run-preview-example"},
            "execution_receipt_refs": [{"receipt_id": "local-receipt-example"}],
            "executor_report_ref": {"executor_report_id": "executor-report-example"},
            "execution_evidence_receipt_ref": {"evidence_receipt_id": "execution-evidence-receipt-example"},
            "validation_truth_summary_ref": {"validation_truth_summary_id": "validation-summary-example"},
            "scope_evidence_pack_ref": {"scope_pack_id": "scope-pack-example"},
            "validation_truth_statuses": ["passed"],
            "scope_result": "in_scope",
            "known_gaps": [],
            "remaining_risks": [{"risk_id": "review_required"}],
        }
        values.update(overrides)
        return build_audit_package_taskbook_binding(**values)

    def test_ready_package_is_not_review_acceptance(self) -> None:
        package = self.build_package()

        assert package["audit_package_status"] == AUDIT_PACKAGE_READY
        assert package["handoff_readiness"] == READY_FOR_REVIEWER_HANDOFF
        assert package["reviewer_handoff_completed"] is False
        assert package["review_accepted"] is False
        assert package["delivery_state_accepted"] is False

    def test_missing_evidence_blocks_handoff_readiness(self) -> None:
        package = self.build_package(execution_receipt_refs=[])

        assert package["audit_package_status"] == AUDIT_PACKAGE_READY
        assert package["handoff_readiness"] == BLOCKED_MISSING_EVIDENCE
        assert "execution_receipt_refs" in package["missing_evidence_refs"]

    def test_scope_violation_blocks_handoff_readiness(self) -> None:
        package = self.build_package(scope_result="out_of_scope")

        assert package["handoff_readiness"] == BLOCKED_SCOPE_VIOLATION

    def test_validation_failure_blocks_handoff_readiness(self) -> None:
        package = self.build_package(validation_truth_statuses=["passed", "failed"])

        assert package["handoff_readiness"] == BLOCKED_VALIDATION_FAILURE

    def test_unknown_scope_blocks_handoff_readiness(self) -> None:
        package = self.build_package(scope_result="unknown_needs_review")

        assert package["handoff_readiness"] == BLOCKED_UNKNOWN_NEEDS_REVIEW

    def test_known_gaps_and_risks_are_preserved(self) -> None:
        package = self.build_package(
            known_gaps=[{"gap_id": "external_receipt_not_adopted"}],
            remaining_risks=[{"risk_id": "reviewer_required"}],
        )

        assert package["known_gaps"][0]["gap_id"] == "external_receipt_not_adopted"
        assert package["remaining_risks"][0]["risk_id"] == "reviewer_required"

    def test_forbidden_reviewer_handoff_completed_claim_fails_closed(self) -> None:
        package = self.build_package(extra_claims={"reviewer_handoff_completed": True})

        assert package["audit_package_status"] == AUDIT_PACKAGE_FAILED_CLOSED
        assert "FORBIDDEN_AUDIT_PACKAGE_AUTHORITY_CLAIM" in {item["code"] for item in package["failures_and_blockers"]}

    def test_forbidden_authority_boundary_fails_closed(self) -> None:
        package = self.build_package(authority_boundary={"audit_package_writes_delivery_state": True})

        assert package["audit_package_status"] == AUDIT_PACKAGE_FAILED_CLOSED
        assert "FORBIDDEN_AUDIT_PACKAGE_AUTHORITY_BOUNDARY" in {item["code"] for item in package["failures_and_blockers"]}

    def test_result_contract_rejects_delivery_state_accepted(self) -> None:
        package = self.build_package()
        mutated = copy.deepcopy(package)
        mutated["delivery_state_accepted"] = True

        with self.assertRaises(AuditPackageTaskbookBindingError) as raised:
            assert_audit_package_taskbook_binding_contract(mutated)

        assert raised.exception.error_code == "FORBIDDEN_AUDIT_PACKAGE_RESULT_CLAIM"

    def test_result_contract_rejects_missing_required_field(self) -> None:
        package = self.build_package()
        del package["scope_evidence_pack_ref"]

        with self.assertRaises(AuditPackageTaskbookBindingError) as raised:
            assert_audit_package_taskbook_binding_contract(package)

        assert raised.exception.error_code == "AUDIT_PACKAGE_REQUIRED_FIELD_MISSING"


if __name__ == "__main__":
    unittest.main()
