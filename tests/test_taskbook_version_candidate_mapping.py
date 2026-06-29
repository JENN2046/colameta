from __future__ import annotations

import copy
import unittest
from pathlib import Path

from runner.external_taskbook_validator import validate_external_taskbook_claim
from runner.taskbook_import_preview import render_taskbook_import_preview
from runner.taskbook_version_candidate_mapping import (
    MAPPING_BLOCKED_AUTHORITY_CONFUSION,
    MAPPING_BLOCKED_PREVIEW_NOT_READY,
    MAPPING_BLOCKED_SCOPE_CONFLICT,
    MAPPING_READY,
    TaskbookVersionCandidateMappingError,
    assert_version_candidate_mapping_contract,
    map_preview_to_version_candidate,
)

import tests.test_external_taskbook_validator as validator_fixture


class TaskbookVersionCandidateMappingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Path(__file__).resolve().parents[1]
        self.fixture = validator_fixture.ExternalTaskbookValidatorTests()
        self.fixture.setUp()
        self.preview_hash = "c" * 64

    def valid_validator_result(self) -> dict:
        return validate_external_taskbook_claim(self.fixture.valid_claim(), project_root=self.repo)

    def valid_preview(self) -> dict:
        return render_taskbook_import_preview(self.valid_validator_result())

    def valid_mapping(self) -> dict:
        validator_result = self.valid_validator_result()
        preview = render_taskbook_import_preview(validator_result)
        return map_preview_to_version_candidate(
            preview,
            import_preview_hash=self.preview_hash,
            normalized_claims_candidate=validator_result["normalized_claims_candidate"],
        )

    def test_preview_ready_maps_to_candidate_only_version_candidate(self) -> None:
        mapping = self.valid_mapping()

        assert mapping["mapping_status"] == MAPPING_READY
        assert mapping["version_candidate_id"] == "version_candidate_aaaaaaaaaaaa"
        assert mapping["source_taskbook_ref"]["external_taskbook_hash"] == "a" * 64
        assert mapping["import_preview_ref"]["import_preview_hash"] == self.preview_hash
        assert mapping["candidate_parent_refs"]["master_taskbook_ref"]["path"] == "PROJECT_MASTER_TASKBOOK.md"
        assert mapping["candidate_parent_refs"]["stage_taskbook_ref"]["stage_id"] == "stage_03_external_taskbook_import"
        assert mapping["candidate_allowed_files"]["candidate_only"] is True
        assert mapping["candidate_allowed_files"]["authorized_delta"] is False
        assert mapping["candidate_acceptance_commands"]["authorized_to_run"] is False
        assert mapping["plan_item_inserted"] is False
        assert mapping["delivery_state_accepted"] is False

    def test_mapping_ready_still_lists_adoption_blockers(self) -> None:
        mapping = self.valid_mapping()

        blocker_codes = {item["code"] for item in mapping["adoption_blockers"]}
        decisions = {item["decision_id"] for item in mapping["required_commander_decisions"]}

        assert "adoption_requires_separate_commander_decision" in blocker_codes
        assert "hash_specific_adoption_decision" in decisions

    def test_blocked_preview_does_not_map(self) -> None:
        claim = self.fixture.valid_claim()
        claim["stage_taskbook_ref"]["stage_id"] = "stage_99_wrong"
        validator_result = validate_external_taskbook_claim(claim, project_root=self.repo)
        preview = render_taskbook_import_preview(validator_result)

        mapping = map_preview_to_version_candidate(
            preview,
            import_preview_hash=self.preview_hash,
            normalized_claims_candidate=validator_result["normalized_claims_candidate"],
        )

        assert mapping["mapping_status"] == MAPPING_BLOCKED_PREVIEW_NOT_READY
        assert mapping["adoption_blockers"][0]["code"] == "import_preview_not_ready"
        assert mapping["plan_mutation_authorized"] is False

    def test_missing_normalized_claim_blocks_mapping(self) -> None:
        mapping = map_preview_to_version_candidate(
            self.valid_preview(),
            import_preview_hash=self.preview_hash,
            normalized_claims_candidate={},
        )

        assert mapping["mapping_status"] == MAPPING_BLOCKED_SCOPE_CONFLICT
        assert mapping["adoption_blockers"][0]["code"] == "normalized_claims_candidate_missing_required_fields"

    def test_invalid_import_preview_hash_blocks_mapping(self) -> None:
        validator_result = self.valid_validator_result()
        preview = render_taskbook_import_preview(validator_result)

        mapping = map_preview_to_version_candidate(
            preview,
            import_preview_hash="not-a-sha",
            normalized_claims_candidate=validator_result["normalized_claims_candidate"],
        )

        assert mapping["mapping_status"] == MAPPING_BLOCKED_SCOPE_CONFLICT
        assert mapping["adoption_blockers"][0]["code"] == "import_preview_hash_invalid"

    def test_authority_confused_preview_blocks_mapping(self) -> None:
        preview = self.valid_preview()
        preview["adoption_authorized"] = True

        mapping = map_preview_to_version_candidate(
            preview,
            import_preview_hash=self.preview_hash,
            normalized_claims_candidate={},
        )

        assert mapping["mapping_status"] == MAPPING_BLOCKED_AUTHORITY_CONFUSION
        assert mapping["adoption_blockers"][0]["code"] == "import_preview_authority_confusion"
        assert mapping["plan_item_inserted"] is False

    def test_mapping_contract_rejects_plan_insertion_claim(self) -> None:
        mapping = self.valid_mapping()
        mutated = copy.deepcopy(mapping)
        mutated["plan_item_inserted"] = True

        with self.assertRaises(TaskbookVersionCandidateMappingError) as raised:
            assert_version_candidate_mapping_contract(mutated)

        assert raised.exception.error_code == "FORBIDDEN_MAPPING_RESULT_CLAIM"

    def test_mapping_contract_rejects_delivery_state_authority(self) -> None:
        mapping = self.valid_mapping()
        mutated = copy.deepcopy(mapping)
        mutated["authority_boundary"]["mapping_writes_delivery_state"] = True

        with self.assertRaises(TaskbookVersionCandidateMappingError) as raised:
            assert_version_candidate_mapping_contract(mutated)

        assert raised.exception.error_code == "FORBIDDEN_MAPPING_AUTHORITY_CLAIM"

    def test_mapping_ready_requires_adoption_blockers(self) -> None:
        mapping = self.valid_mapping()
        mutated = copy.deepcopy(mapping)
        mutated["adoption_blockers"] = []

        with self.assertRaises(TaskbookVersionCandidateMappingError) as raised:
            assert_version_candidate_mapping_contract(mutated)

        assert raised.exception.error_code == "MAPPING_READY_WITHOUT_ADOPTION_BLOCKERS"

    def test_candidate_allowed_files_must_remain_candidate_only(self) -> None:
        mapping = self.valid_mapping()
        mutated = copy.deepcopy(mapping)
        mutated["candidate_allowed_files"]["candidate_only"] = False

        with self.assertRaises(TaskbookVersionCandidateMappingError) as raised:
            assert_version_candidate_mapping_contract(mutated)

        assert raised.exception.error_code == "CANDIDATE_ALLOWED_FILES_NOT_CANDIDATE_ONLY"

    def test_candidate_allowed_files_cannot_authorize_delta(self) -> None:
        mapping = self.valid_mapping()
        mutated = copy.deepcopy(mapping)
        mutated["candidate_allowed_files"]["authorized_delta"] = True

        with self.assertRaises(TaskbookVersionCandidateMappingError) as raised:
            assert_version_candidate_mapping_contract(mutated)

        assert raised.exception.error_code == "FORBIDDEN_MAPPING_RESULT_CLAIM"


if __name__ == "__main__":
    unittest.main()
