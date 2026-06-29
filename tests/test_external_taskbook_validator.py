from __future__ import annotations

import copy
import unittest
from pathlib import Path

from runner.external_taskbook_validator import (
    EXPECTED_MASTER_TASKBOOK_REF,
    EXPECTED_STAGE_TASKBOOK_REF,
    VALIDATION_FAILED_CLOSED,
    VALIDATION_PASSED,
    ExternalTaskbookValidatorError,
    assert_external_taskbook_validation_result_contract,
    validate_external_taskbook_claim,
)


class ExternalTaskbookValidatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Path(__file__).resolve().parents[1]

    def valid_claim(self) -> dict:
        return {
            "source": {
                "system": "commander_chat",
                "source_id": "external-taskbook-validator-example",
                "received_at": "2026-06-30T00:00:00+08:00",
            },
            "provenance": {
                "provided_by": "Commander",
                "capture_method": "pasted_text",
                "provenance_note": "Local validator example only.",
            },
            "external_taskbook_hash": "a" * 64,
            "expected_hash_authority_ref": {
                "authority_document": "commander_confirmation_prompt",
                "authority_hash": "b" * 64,
            },
            "master_taskbook_ref": dict(EXPECTED_MASTER_TASKBOOK_REF),
            "stage_taskbook_ref": dict(EXPECTED_STAGE_TASKBOOK_REF),
            "allowed_files": [
                "runner/example.py",
                "tests/test_example.py",
            ],
            "forbidden_files": [
                "PROJECT_MASTER_TASKBOOK.md",
                ".colameta/plan.json",
                "**/.env",
            ],
            "acceptance_commands": [
                "python -m unittest tests.test_example",
                "git diff --check",
            ],
            "manual_acceptance": {
                "required": True,
                "reviewer": "Commander",
                "acceptance_note": "Manual review required before adoption.",
            },
            "out_of_scope": [
                "plan mutation",
                "executor dispatch",
                "delivery state accepted",
            ],
            "supports_stage_and_master_goals": {
                "supports_stage_goal": True,
                "supports_master_goal": True,
                "rationale": "External taskbook remains a bounded claim until reviewed.",
            },
        }

    def validate(self, claim: dict) -> dict:
        return validate_external_taskbook_claim(claim, project_root=self.repo)

    def test_valid_claim_passes_as_evidence_only(self) -> None:
        result = self.validate(self.valid_claim())

        assert result["validation_result"] == VALIDATION_PASSED
        assert result["fail_closed_result"] == "pass"
        assert result["recognized_fields"]
        assert result["rejected_fields"] == []
        assert result["rejection_reasons"] == []
        assert result["normalized_claims_candidate"]["external_taskbook_hash"] == "a" * 64
        assert result["version_candidate_mapping"]["mapping_status"] == "schema_claim_shape_only_not_adopted"
        assert result["authority_boundary"]["validator_result_is_authority"] is False
        assert result["authority_boundary"]["writes_delivery_state"] is False
        assert result["external_taskbook_authorizes_execution"] is False

    def test_missing_required_field_fails_closed_without_auto_repair(self) -> None:
        claim = self.valid_claim()
        del claim["expected_hash_authority_ref"]

        result = self.validate(claim)

        assert result["validation_result"] == VALIDATION_FAILED_CLOSED
        assert "expected_hash_authority_ref" in result["rejected_fields"]
        assert result["normalized_claims_candidate"] == {}
        assert "expected_hash_authority_ref" not in result["recognized_fields"]

    def test_missing_authority_hash_fails_closed(self) -> None:
        claim = self.valid_claim()
        del claim["expected_hash_authority_ref"]["authority_hash"]

        result = self.validate(claim)

        assert result["validation_result"] == VALIDATION_FAILED_CLOSED
        assert "expected_hash_authority_ref" in result["rejected_fields"]
        assert "EXPECTED_HASH_AUTHORITY_HASH_INVALID" in {item["code"] for item in result["rejection_reasons"]}

    def test_master_reference_mismatch_fails_closed(self) -> None:
        claim = self.valid_claim()
        claim["master_taskbook_ref"]["raw_snapshot_sha256"] = "0" * 64

        result = self.validate(claim)

        assert result["validation_result"] == VALIDATION_FAILED_CLOSED
        assert "master_taskbook_ref" in result["rejected_fields"]
        assert "REFERENCE_MISMATCH" in {item["code"] for item in result["rejection_reasons"]}
        assert "reference_mismatch" in {item["conflict_type"] for item in result["known_conflicts"]}

    def test_stage_reference_mismatch_fails_closed(self) -> None:
        claim = self.valid_claim()
        claim["stage_taskbook_ref"]["stage_id"] = "stage_99_wrong"

        result = self.validate(claim)

        assert result["validation_result"] == VALIDATION_FAILED_CLOSED
        assert "stage_taskbook_ref" in result["rejected_fields"]

    def test_allowed_and_forbidden_overlap_fails_closed(self) -> None:
        claim = self.valid_claim()
        claim["forbidden_files"].append("runner/example.py")

        result = self.validate(claim)

        assert result["validation_result"] == VALIDATION_FAILED_CLOSED
        assert "allowed_files" in result["rejected_fields"]
        assert "forbidden_files" in result["rejected_fields"]
        assert "ALLOWED_FORBIDDEN_FILES_OVERLAP" in {item["code"] for item in result["rejection_reasons"]}

    def test_allowed_files_reject_hard_forbidden_targets(self) -> None:
        hard_targets = (
            "PROJECT_MASTER_TASKBOOK.md",
            ".colameta/plan.json",
            ".git/config",
            "runner/*.py",
            "../outside.py",
            "secrets/token.txt",
        )
        for target in hard_targets:
            with self.subTest(target=target):
                claim = self.valid_claim()
                claim["allowed_files"] = [target]

                result = self.validate(claim)

                assert result["validation_result"] == VALIDATION_FAILED_CLOSED
                assert "allowed_files" in result["rejected_fields"]

    def test_acceptance_commands_reject_remote_or_executor_actions(self) -> None:
        claim = self.valid_claim()
        claim["acceptance_commands"].append("git push origin main")

        result = self.validate(claim)

        assert result["validation_result"] == VALIDATION_FAILED_CLOSED
        assert "acceptance_commands" in result["rejected_fields"]
        assert "ACCEPTANCE_COMMAND_FORBIDDEN" in {item["code"] for item in result["rejection_reasons"]}

    def test_goal_support_false_fails_closed(self) -> None:
        claim = self.valid_claim()
        claim["supports_stage_and_master_goals"]["supports_stage_goal"] = False

        result = self.validate(claim)

        assert result["validation_result"] == VALIDATION_FAILED_CLOSED
        assert "supports_stage_and_master_goals" in result["rejected_fields"]
        assert "GOAL_SUPPORT_INVALID" in {item["code"] for item in result["rejection_reasons"]}

    def test_goal_support_rationale_missing_fails_closed(self) -> None:
        claim = self.valid_claim()
        claim["supports_stage_and_master_goals"]["rationale"] = ""

        result = self.validate(claim)

        assert result["validation_result"] == VALIDATION_FAILED_CLOSED
        assert "GOAL_SUPPORT_RATIONALE_MISSING" in {item["code"] for item in result["rejection_reasons"]}

    def test_plan_mutation_authority_claim_fails_closed(self) -> None:
        claim = self.valid_claim()
        claim["external_taskbook_mutates_plan"] = True

        result = self.validate(claim)

        assert result["validation_result"] == VALIDATION_FAILED_CLOSED
        assert "FORBIDDEN_AUTHORITY_CLAIM" in {item["code"] for item in result["rejection_reasons"]}
        assert result["known_conflicts"][0]["conflict_type"] == "authority_boundary"

    def test_manual_acceptance_to_delivery_state_claim_fails_closed(self) -> None:
        claim = self.valid_claim()
        claim["manual_acceptance"]["manual_acceptance_means_delivery_state_accepted"] = True

        result = self.validate(claim)

        assert result["validation_result"] == VALIDATION_FAILED_CLOSED
        assert "FORBIDDEN_AUTHORITY_CLAIM" in {item["code"] for item in result["rejection_reasons"]}

    def test_validation_result_contract_rejects_authority_laundering(self) -> None:
        result = self.validate(self.valid_claim())
        mutated = copy.deepcopy(result)
        mutated["authority_boundary"]["writes_delivery_state"] = True

        with self.assertRaises(ExternalTaskbookValidatorError) as raised:
            assert_external_taskbook_validation_result_contract(mutated)

        assert raised.exception.error_code == "FORBIDDEN_VALIDATOR_AUTHORITY_CLAIM"

    def test_validation_result_contract_rejects_top_level_accepted_claim(self) -> None:
        result = self.validate(self.valid_claim())
        mutated = copy.deepcopy(result)
        mutated["delivery_state_accepted"] = True

        with self.assertRaises(ExternalTaskbookValidatorError) as raised:
            assert_external_taskbook_validation_result_contract(mutated)

        assert raised.exception.error_code == "FORBIDDEN_VALIDATOR_RESULT_CLAIM"

    def test_non_object_claim_fails_closed(self) -> None:
        result = validate_external_taskbook_claim("not a dict", project_root=self.repo)  # type: ignore[arg-type]

        assert result["validation_result"] == VALIDATION_FAILED_CLOSED
        assert result["recognized_fields"] == []
        assert result["rejected_fields"] == []
        assert result["rejection_reasons"][0]["code"] == "CLAIM_INVALID"


if __name__ == "__main__":
    unittest.main()
