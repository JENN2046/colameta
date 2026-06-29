from __future__ import annotations

import copy
import unittest
from pathlib import Path

from runner.external_taskbook_validator import VALIDATION_FAILED_CLOSED, validate_external_taskbook_claim
from runner.taskbook_import_preview import (
    PREVIEW_BLOCKED_AUTHORITY_CONFUSION,
    PREVIEW_BLOCKED_INVALID_VALIDATOR_RESULT,
    PREVIEW_BLOCKED_MISSING_REQUIRED_CLAIM,
    PREVIEW_READY,
    TaskbookImportPreviewError,
    assert_taskbook_import_preview_contract,
    render_taskbook_import_preview,
)

import tests.test_external_taskbook_validator as validator_fixture


class TaskbookImportPreviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Path(__file__).resolve().parents[1]
        self.fixture = validator_fixture.ExternalTaskbookValidatorTests()
        self.fixture.setUp()

    def valid_validator_result(self) -> dict:
        return validate_external_taskbook_claim(self.fixture.valid_claim(), project_root=self.repo)

    def test_valid_validator_result_renders_candidate_only_preview(self) -> None:
        preview = render_taskbook_import_preview(self.valid_validator_result())

        assert preview["preview_status"] == PREVIEW_READY
        assert preview["blockers"] == []
        assert preview["source_claim_ref"]["external_taskbook_hash"] == "a" * 64
        assert preview["validator_result_ref"]["validation_result"] == "validation_passed"
        assert preview["recognized_claims_summary"]["recognized_fields_count"] == 12
        assert preview["proposed_allowed_files_candidate_delta"]["candidate_only"] is True
        assert preview["proposed_allowed_files_candidate_delta"]["authorized_delta"] is False
        assert preview["proposed_acceptance_commands_summary"]["authorized_to_run"] is False
        assert preview["proposed_manual_acceptance_summary"]["manual_acceptance_is_delivery_state_accepted"] is False
        assert preview["adoption_authorized"] is False
        assert preview["plan_mutation_authorized"] is False
        assert preview["delivery_state_accepted"] is False

    def test_required_commander_decisions_are_explicit_for_ready_preview(self) -> None:
        preview = render_taskbook_import_preview(self.valid_validator_result())

        decisions = {item["decision_id"] for item in preview["required_commander_decisions"]}

        assert "decide_whether_to_consider_mapping" in decisions
        assert "hash_specific_adoption_decision" in decisions
        assert "execution_authorization" in decisions

    def test_failed_validator_result_blocks_preview(self) -> None:
        claim = self.fixture.valid_claim()
        claim["master_taskbook_ref"]["raw_snapshot_sha256"] = "0" * 64
        validator_result = validate_external_taskbook_claim(claim, project_root=self.repo)

        preview = render_taskbook_import_preview(validator_result)

        assert validator_result["validation_result"] == VALIDATION_FAILED_CLOSED
        assert preview["preview_status"] == PREVIEW_BLOCKED_INVALID_VALIDATOR_RESULT
        assert preview["blockers"][0]["code"] == "validator_result_not_passed"
        assert preview["proposed_allowed_files_candidate_delta"]["authorized_delta"] is False

    def test_missing_normalized_claim_blocks_preview(self) -> None:
        validator_result = self.valid_validator_result()
        validator_result["normalized_claims_candidate"] = {}

        preview = render_taskbook_import_preview(validator_result)

        assert preview["preview_status"] == PREVIEW_BLOCKED_MISSING_REQUIRED_CLAIM
        assert preview["blockers"][0]["code"] == "normalized_claim_missing"

    def test_authority_confused_validator_result_blocks_preview(self) -> None:
        validator_result = self.valid_validator_result()
        validator_result["delivery_state_accepted"] = True

        preview = render_taskbook_import_preview(validator_result)

        assert preview["preview_status"] == PREVIEW_BLOCKED_AUTHORITY_CONFUSION
        assert preview["blockers"][0]["code"] == "validator_result_authority_confusion"
        assert preview["delivery_state_accepted"] is False

    def test_preview_contract_rejects_adoption_authority(self) -> None:
        preview = render_taskbook_import_preview(self.valid_validator_result())
        mutated = copy.deepcopy(preview)
        mutated["adoption_authorized"] = True

        with self.assertRaises(TaskbookImportPreviewError) as raised:
            assert_taskbook_import_preview_contract(mutated)

        assert raised.exception.error_code == "FORBIDDEN_PREVIEW_RESULT_CLAIM"

    def test_preview_contract_rejects_delivery_state_authority(self) -> None:
        preview = render_taskbook_import_preview(self.valid_validator_result())
        mutated = copy.deepcopy(preview)
        mutated["authority_boundary"]["preview_writes_delivery_state"] = True

        with self.assertRaises(TaskbookImportPreviewError) as raised:
            assert_taskbook_import_preview_contract(mutated)

        assert raised.exception.error_code == "FORBIDDEN_PREVIEW_AUTHORITY_CLAIM"

    def test_preview_ready_cannot_include_blockers(self) -> None:
        preview = render_taskbook_import_preview(self.valid_validator_result())
        mutated = copy.deepcopy(preview)
        mutated["blockers"] = [{"code": "fake", "message": "fake", "details": {}}]

        with self.assertRaises(TaskbookImportPreviewError) as raised:
            assert_taskbook_import_preview_contract(mutated)

        assert raised.exception.error_code == "PREVIEW_READY_WITH_BLOCKERS"

    def test_blocked_preview_must_include_blockers(self) -> None:
        preview = render_taskbook_import_preview(self.valid_validator_result())
        mutated = copy.deepcopy(preview)
        mutated["preview_status"] = PREVIEW_BLOCKED_INVALID_VALIDATOR_RESULT

        with self.assertRaises(TaskbookImportPreviewError) as raised:
            assert_taskbook_import_preview_contract(mutated)

        assert raised.exception.error_code == "BLOCKED_PREVIEW_WITHOUT_BLOCKERS"

    def test_allowed_files_delta_must_remain_candidate_only(self) -> None:
        preview = render_taskbook_import_preview(self.valid_validator_result())
        mutated = copy.deepcopy(preview)
        mutated["proposed_allowed_files_candidate_delta"]["authorized_delta"] = True

        with self.assertRaises(TaskbookImportPreviewError) as raised:
            assert_taskbook_import_preview_contract(mutated)

        assert raised.exception.error_code == "ALLOWED_FILES_DELTA_NOT_CANDIDATE_ONLY"

    def test_invalid_validator_result_type_blocks_preview(self) -> None:
        preview = render_taskbook_import_preview("not a result")  # type: ignore[arg-type]

        assert preview["preview_status"] == PREVIEW_BLOCKED_AUTHORITY_CONFUSION
        assert preview["source_claim_ref"]["external_taskbook_hash"] is None


if __name__ == "__main__":
    unittest.main()
