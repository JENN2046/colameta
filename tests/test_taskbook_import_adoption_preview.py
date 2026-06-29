from __future__ import annotations

import copy
import unittest
from pathlib import Path

from runner.taskbook_import_adoption_preview import (
    ADOPTION_PREVIEW_BLOCKED_AUTHORITY_CONFUSION,
    ADOPTION_PREVIEW_BLOCKED_MAPPING_NOT_READY,
    ADOPTION_PREVIEW_BLOCKED_PLAN_SCOPE_CONFLICT,
    ADOPTION_PREVIEW_READY,
    TaskbookImportAdoptionPreviewError,
    assert_taskbook_import_adoption_preview_contract,
    render_taskbook_import_adoption_preview,
)

import tests.test_taskbook_version_candidate_mapping as mapping_fixture


class TaskbookImportAdoptionPreviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Path(__file__).resolve().parents[1]
        self.fixture = mapping_fixture.TaskbookVersionCandidateMappingTests()
        self.fixture.setUp()
        self.mapping_hash = "d" * 64
        self.plan_diff_hash = "e" * 64
        self.allowed_files_delta_hash = "f" * 64
        self.current_head = "1a384e4c39749226b87b801182624cd6ad5074f0"

    def valid_adoption_preview(self) -> dict:
        return render_taskbook_import_adoption_preview(
            self.fixture.valid_mapping(),
            mapping_hash=self.mapping_hash,
            current_head=self.current_head,
            candidate_plan_diff_hash=self.plan_diff_hash,
            candidate_allowed_files_delta_hash=self.allowed_files_delta_hash,
        )

    def test_mapping_ready_renders_hash_bound_adoption_preview(self) -> None:
        preview = self.valid_adoption_preview()

        assert preview["adoption_preview_status"] == ADOPTION_PREVIEW_READY
        assert preview["source_taskbook_ref"]["external_taskbook_hash"] == "a" * 64
        assert preview["import_preview_ref"]["import_preview_hash"] == "c" * 64
        assert preview["mapping_ref"]["mapping_hash"] == self.mapping_hash
        assert preview["target_plan_path"] == ".colameta/plan.json"
        assert preview["candidate_plan_diff_summary"]["candidate_only"] is True
        assert preview["candidate_plan_diff_summary"]["plan_mutation_applied"] is False
        assert preview["candidate_allowed_files_delta"]["allowed_files_expansion_authorized"] is False
        assert preview["commander_decision_request"]["decision_status"] == "not_confirmed"
        assert preview["commander_decision_request"]["explicit_authorized_actions"] == []
        assert preview["adoption_executed"] is False
        assert preview["delivery_state_accepted"] is False

    def test_ready_preview_lists_separate_authorization_blocker(self) -> None:
        preview = self.valid_adoption_preview()

        blocker_codes = {item["code"] for item in preview["blockers"]}

        assert "adoption_execution_requires_separate_commander_confirmation" in blocker_codes
        assert "plan_mutation" in preview["commander_decision_request"]["must_authorize_separately"]
        assert "executor_dispatch" in preview["commander_decision_request"]["explicit_unauthorized_actions"]

    def test_mapping_not_ready_blocks_adoption_preview(self) -> None:
        mapping = self.fixture.valid_mapping()
        mapping["mapping_status"] = "mapping_blocked_scope_conflict"

        preview = render_taskbook_import_adoption_preview(
            mapping,
            mapping_hash=self.mapping_hash,
            current_head=self.current_head,
            candidate_plan_diff_hash=self.plan_diff_hash,
            candidate_allowed_files_delta_hash=self.allowed_files_delta_hash,
        )

        assert preview["adoption_preview_status"] == ADOPTION_PREVIEW_BLOCKED_MAPPING_NOT_READY
        assert preview["blockers"][0]["code"] == "mapping_not_ready"
        assert preview["plan_mutation_authorized"] is False

    def test_invalid_hash_inputs_block_plan_scope(self) -> None:
        preview = render_taskbook_import_adoption_preview(
            self.fixture.valid_mapping(),
            mapping_hash="not-a-sha",
            current_head=self.current_head,
            candidate_plan_diff_hash=self.plan_diff_hash,
            candidate_allowed_files_delta_hash=self.allowed_files_delta_hash,
        )

        assert preview["adoption_preview_status"] == ADOPTION_PREVIEW_BLOCKED_PLAN_SCOPE_CONFLICT
        assert preview["blockers"][0]["code"] == "required_exact_hash_authorization_inputs_invalid"
        assert "mapping_hash" in preview["blockers"][0]["details"]["invalid_fields"]

    def test_wrong_target_plan_path_blocks_plan_scope(self) -> None:
        preview = render_taskbook_import_adoption_preview(
            self.fixture.valid_mapping(),
            mapping_hash=self.mapping_hash,
            current_head=self.current_head,
            candidate_plan_diff_hash=self.plan_diff_hash,
            candidate_allowed_files_delta_hash=self.allowed_files_delta_hash,
            target_plan_path="PROJECT_MASTER_TASKBOOK.md",
        )

        assert preview["adoption_preview_status"] == ADOPTION_PREVIEW_BLOCKED_PLAN_SCOPE_CONFLICT
        assert "target_plan_path" in preview["blockers"][0]["details"]["invalid_fields"]

    def test_authority_confused_mapping_blocks_adoption_preview(self) -> None:
        mapping = self.fixture.valid_mapping()
        mapping["plan_item_inserted"] = True

        preview = render_taskbook_import_adoption_preview(
            mapping,
            mapping_hash=self.mapping_hash,
            current_head=self.current_head,
            candidate_plan_diff_hash=self.plan_diff_hash,
            candidate_allowed_files_delta_hash=self.allowed_files_delta_hash,
        )

        assert preview["adoption_preview_status"] == ADOPTION_PREVIEW_BLOCKED_AUTHORITY_CONFUSION
        assert preview["blockers"][0]["code"] == "mapping_authority_confusion"
        assert preview["adoption_executed"] is False

    def test_contract_rejects_executed_adoption(self) -> None:
        preview = self.valid_adoption_preview()
        mutated = copy.deepcopy(preview)
        mutated["adoption_executed"] = True

        with self.assertRaises(TaskbookImportAdoptionPreviewError) as raised:
            assert_taskbook_import_adoption_preview_contract(mutated)

        assert raised.exception.error_code == "FORBIDDEN_ADOPTION_PREVIEW_RESULT_CLAIM"

    def test_contract_rejects_plan_mutation_authority(self) -> None:
        preview = self.valid_adoption_preview()
        mutated = copy.deepcopy(preview)
        mutated["authority_boundary"]["adoption_preview_mutates_plan"] = True

        with self.assertRaises(TaskbookImportAdoptionPreviewError) as raised:
            assert_taskbook_import_adoption_preview_contract(mutated)

        assert raised.exception.error_code == "FORBIDDEN_ADOPTION_PREVIEW_AUTHORITY_CLAIM"

    def test_commander_decision_request_must_remain_not_confirmed(self) -> None:
        preview = self.valid_adoption_preview()
        mutated = copy.deepcopy(preview)
        mutated["commander_decision_request"]["decision_status"] = "confirmed"

        with self.assertRaises(TaskbookImportAdoptionPreviewError) as raised:
            assert_taskbook_import_adoption_preview_contract(mutated)

        assert raised.exception.error_code == "COMMANDER_DECISION_REQUEST_NOT_PENDING"

    def test_commander_decision_request_cannot_authorize_actions(self) -> None:
        preview = self.valid_adoption_preview()
        mutated = copy.deepcopy(preview)
        mutated["commander_decision_request"]["explicit_authorized_actions"] = ["plan_mutation"]

        with self.assertRaises(TaskbookImportAdoptionPreviewError) as raised:
            assert_taskbook_import_adoption_preview_contract(mutated)

        assert raised.exception.error_code == "COMMANDER_DECISION_REQUEST_AUTHORIZES_ACTIONS"

    def test_contract_requires_blockers_even_when_ready(self) -> None:
        preview = self.valid_adoption_preview()
        mutated = copy.deepcopy(preview)
        mutated["blockers"] = []

        with self.assertRaises(TaskbookImportAdoptionPreviewError) as raised:
            assert_taskbook_import_adoption_preview_contract(mutated)

        assert raised.exception.error_code == "ADOPTION_PREVIEW_BLOCKERS_REQUIRED"


if __name__ == "__main__":
    unittest.main()
