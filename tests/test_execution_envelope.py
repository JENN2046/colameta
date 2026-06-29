from __future__ import annotations

import copy
import unittest

from runner.execution_envelope import (
    ENVELOPE_CHECK_FAILED_CLOSED,
    ENVELOPE_CHECK_PASSED,
    EXPECTED_MASTER_TASKBOOK_REF,
    EXPECTED_STAGE_TASKBOOK_REF,
    EXPECTED_VERSION_TASKBOOK_REF,
    ExecutionEnvelopeError,
    assert_execution_envelope_result_contract,
    validate_execution_envelope,
)


class ExecutionEnvelopeTests(unittest.TestCase):
    def valid_envelope(self, authority_mode: str = "validation_only") -> dict:
        return {
            "envelope_id": "execution-envelope-example",
            "envelope_schema_version": "execution_envelope.v1",
            "version_taskbook_ref": dict(EXPECTED_VERSION_TASKBOOK_REF),
            "master_taskbook_ref": dict(EXPECTED_MASTER_TASKBOOK_REF),
            "stage_taskbook_ref": dict(EXPECTED_STAGE_TASKBOOK_REF),
            "authority_mode": authority_mode,
            "local_execution_authorization_ref": {},
            "imported_receipt_authorization_ref": {},
            "allowed_files": ["runner/example.py", "tests/test_example.py"],
            "forbidden_files": ["PROJECT_MASTER_TASKBOOK.md", ".colameta/plan.json", "**/.env"],
            "allowed_commands": ["python -m unittest tests.test_example"],
            "validation_commands": ["python -m unittest tests.test_example", "git diff --check"],
            "timeout_limits": {"command_timeout_seconds": 120},
            "network_policy": {"network_allowed": False},
            "secrets_policy": {"read_secrets_allowed": False},
            "destructive_operation_policy": {"destructive_operations_allowed": False},
            "retry_policy": {"max_retries": 0},
            "stop_conditions": ["hash mismatch", "forbidden path touched"],
        }

    def test_validation_only_envelope_passes_as_non_authority(self) -> None:
        result = validate_execution_envelope(self.valid_envelope())

        assert result["envelope_check_result"] == ENVELOPE_CHECK_PASSED
        assert result["rejected_fields"] == []
        assert result["authority_mode"] == "validation_only"
        assert result["dispatch_authorized_by_envelope_existence"] is False
        assert result["executor_dispatch_authorized"] is False
        assert result["delivery_state_accepted"] is False
        assert result["authority_boundary"]["envelope_existence_authorizes_dispatch"] is False

    def test_local_execution_requires_local_authorization_ref(self) -> None:
        envelope = self.valid_envelope("local_execution")

        result = validate_execution_envelope(envelope)

        assert result["envelope_check_result"] == ENVELOPE_CHECK_FAILED_CLOSED
        assert "local_execution_authorization_ref" in result["rejected_fields"]
        assert "LOCAL_EXECUTION_AUTHORIZATION_REF_REQUIRED" in {item["code"] for item in result["rejection_reasons"]}

    def test_imported_receipt_requires_imported_receipt_authorization_ref(self) -> None:
        envelope = self.valid_envelope("imported_receipt")

        result = validate_execution_envelope(envelope)

        assert result["envelope_check_result"] == ENVELOPE_CHECK_FAILED_CLOSED
        assert "imported_receipt_authorization_ref" in result["rejected_fields"]

    def test_local_execution_with_authorization_ref_passes_but_does_not_dispatch(self) -> None:
        envelope = self.valid_envelope("local_execution")
        envelope["local_execution_authorization_ref"] = {
            "authorization_id": "local-execution-auth-example",
            "authority_status": "hash_specific_authorized_elsewhere",
        }

        result = validate_execution_envelope(envelope)

        assert result["envelope_check_result"] == ENVELOPE_CHECK_PASSED
        assert result["executor_dispatch_authorized"] is False

    def test_missing_version_taskbook_ref_fails_closed(self) -> None:
        envelope = self.valid_envelope()
        del envelope["version_taskbook_ref"]

        result = validate_execution_envelope(envelope)

        assert result["envelope_check_result"] == ENVELOPE_CHECK_FAILED_CLOSED
        assert "version_taskbook_ref" in result["rejected_fields"]

    def test_master_reference_mismatch_fails_closed(self) -> None:
        envelope = self.valid_envelope()
        envelope["master_taskbook_ref"]["raw_snapshot_sha256"] = "0" * 64

        result = validate_execution_envelope(envelope)

        assert result["envelope_check_result"] == ENVELOPE_CHECK_FAILED_CLOSED
        assert "master_taskbook_ref" in result["rejected_fields"]
        assert "reference_mismatch" in {item["conflict_type"] for item in result["known_conflicts"]}

    def test_stage_reference_mismatch_fails_closed(self) -> None:
        envelope = self.valid_envelope()
        envelope["stage_taskbook_ref"]["stage_id"] = "stage_99_wrong"

        result = validate_execution_envelope(envelope)

        assert result["envelope_check_result"] == ENVELOPE_CHECK_FAILED_CLOSED
        assert "stage_taskbook_ref" in result["rejected_fields"]

    def test_unknown_authority_mode_fails_closed(self) -> None:
        envelope = self.valid_envelope("unknown")

        result = validate_execution_envelope(envelope)

        assert result["envelope_check_result"] == ENVELOPE_CHECK_FAILED_CLOSED
        assert "authority_mode" in result["rejected_fields"]

    def test_empty_allowed_files_fails_closed(self) -> None:
        envelope = self.valid_envelope()
        envelope["allowed_files"] = []

        result = validate_execution_envelope(envelope)

        assert result["envelope_check_result"] == ENVELOPE_CHECK_FAILED_CLOSED
        assert "allowed_files" in result["rejected_fields"]

    def test_missing_validation_commands_fails_closed(self) -> None:
        envelope = self.valid_envelope()
        envelope["validation_commands"] = []

        result = validate_execution_envelope(envelope)

        assert result["envelope_check_result"] == ENVELOPE_CHECK_FAILED_CLOSED
        assert "validation_commands" in result["rejected_fields"]

    def test_forbidden_authority_claim_fails_closed(self) -> None:
        envelope = self.valid_envelope()
        envelope["dispatch_authorized_by_envelope_existence"] = True

        result = validate_execution_envelope(envelope)

        assert result["envelope_check_result"] == ENVELOPE_CHECK_FAILED_CLOSED
        assert "FORBIDDEN_ENVELOPE_AUTHORITY_CLAIM" in {item["code"] for item in result["rejection_reasons"]}

    def test_result_contract_rejects_dispatch_authority(self) -> None:
        result = validate_execution_envelope(self.valid_envelope())
        mutated = copy.deepcopy(result)
        mutated["authority_boundary"]["envelope_existence_authorizes_dispatch"] = True

        with self.assertRaises(ExecutionEnvelopeError) as raised:
            assert_execution_envelope_result_contract(mutated)

        assert raised.exception.error_code == "FORBIDDEN_ENVELOPE_RESULT_AUTHORITY_CLAIM"

    def test_result_contract_rejects_delivery_state_accepted(self) -> None:
        result = validate_execution_envelope(self.valid_envelope())
        mutated = copy.deepcopy(result)
        mutated["delivery_state_accepted"] = True

        with self.assertRaises(ExecutionEnvelopeError) as raised:
            assert_execution_envelope_result_contract(mutated)

        assert raised.exception.error_code == "FORBIDDEN_ENVELOPE_RESULT_CLAIM"

    def test_non_object_envelope_fails_closed(self) -> None:
        result = validate_execution_envelope("not an envelope")  # type: ignore[arg-type]

        assert result["envelope_check_result"] == ENVELOPE_CHECK_FAILED_CLOSED
        assert result["recognized_fields"] == []
        assert result["rejection_reasons"][0]["code"] == "ENVELOPE_INVALID"


if __name__ == "__main__":
    unittest.main()
