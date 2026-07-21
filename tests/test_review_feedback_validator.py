from __future__ import annotations

import copy
import unittest

from runner.review_feedback_validator import (
    INVALID_BINDING_MISMATCH,
    INVALID_FORBIDDEN_AUTHORITY_CLAIM,
    INVALID_MISSING_REQUIRED_FIELD,
    INVALID_PASS_ALIAS_POLICY_MISSING,
    INVALID_UNKNOWN_REVIEW_DECISION,
    VALID_FOR_PREVIEW,
    ReviewFeedbackValidatorError,
    assert_review_feedback_validator_result_contract,
    example_valid_feedback_for_preview,
    example_validation_context,
    validate_review_feedback_for_preview,
    validator_rule_inventory,
)
from runner.validation_truth import evidence_record_sha256


class ReviewFeedbackValidatorTests(unittest.TestCase):
    @staticmethod
    def attach_master_hash_provenance(feedback: dict) -> None:
        feedback["evidence_provenance"] = {
            "schema_version": "evidence_provenance.v1",
            "entries": [
                {
                    "subject_path": "$",
                    "evidence_kind": "observed",
                    "binding": {
                        "record_id": feedback["review_feedback_id"],
                        "record_schema_version": feedback["review_feedback_schema_version"],
                        "subject_path": "$",
                        "content_sha256": evidence_record_sha256(feedback),
                    },
                    "claimed_evidence_subject": "review",
                    "claimed_subject_requires_execution": False,
                    "claimed_subject_operation_completed": True,
                    "claimed_execution_performed": False,
                    "claimed_eligible_for_acceptance": True,
                },
                {
                    "subject_path": "$.master_taskbook_hash",
                    "evidence_kind": "observed",
                    "binding": {
                        "record_id": feedback["review_feedback_id"],
                        "record_schema_version": feedback["review_feedback_schema_version"],
                        "subject_path": "$.master_taskbook_hash",
                        "content_sha256": evidence_record_sha256(feedback),
                    },
                    "claimed_evidence_subject": "hash_binding",
                    "claimed_subject_requires_execution": False,
                    "claimed_subject_operation_completed": True,
                    "claimed_execution_performed": False,
                    "claimed_eligible_for_acceptance": True,
                },
                {
                    "subject_path": "$.stage_taskbook_hash",
                    "evidence_kind": "observed",
                    "binding": {
                        "record_id": feedback["review_feedback_id"],
                        "record_schema_version": feedback["review_feedback_schema_version"],
                        "subject_path": "$.stage_taskbook_hash",
                        "content_sha256": evidence_record_sha256(feedback),
                    },
                    "claimed_evidence_subject": "hash_binding",
                    "claimed_subject_requires_execution": False,
                    "claimed_subject_operation_completed": True,
                    "claimed_execution_performed": False,
                    "claimed_eligible_for_acceptance": True,
                },
            ],
        }

    def test_valid_feedback_is_valid_for_preview_only(self) -> None:
        result = validate_review_feedback_for_preview(example_valid_feedback_for_preview(), example_validation_context())

        assert result["validation_status"] == VALID_FOR_PREVIEW
        assert result["normalized_review_decision_value"] == "NEEDS_FIX"
        assert result["commander_decision_request_created"] is False
        assert result["review_decision_created"] is False
        assert result["gate_event_emitted"] is False
        assert result["delivery_state_transitioned"] is False

    def test_rule_inventory_names_forbidden_outputs(self) -> None:
        inventory = validator_rule_inventory()

        assert "review_feedback_candidate" in inventory["required_inputs"]
        assert VALID_FOR_PREVIEW in inventory["valid_validation_statuses"]
        assert "delivery_state_transition" in inventory["forbidden_outputs"]

    def test_missing_context_field_fails_closed(self) -> None:
        context = example_validation_context()
        del context["expected_workspace_snapshot_ref"]

        result = validate_review_feedback_for_preview(example_valid_feedback_for_preview(), context)

        assert result["validation_status"] == INVALID_MISSING_REQUIRED_FIELD
        assert result["validation_errors"][0]["code"] == "VALIDATION_CONTEXT_REQUIRED_FIELD_MISSING"

    def test_binding_mismatch_fails_closed(self) -> None:
        feedback = example_valid_feedback_for_preview()
        feedback["workspace_snapshot_ref"] = {"head": "different"}

        result = validate_review_feedback_for_preview(feedback, example_validation_context())

        assert result["validation_status"] == INVALID_BINDING_MISMATCH
        assert result["binding_check"]["status"] == "failed_closed"

    def test_expected_hash_context_is_forwarded_to_provenance_validator(self) -> None:
        context = example_validation_context()
        feedback = example_valid_feedback_for_preview()
        self.attach_master_hash_provenance(feedback)

        valid = validate_review_feedback_for_preview(feedback, context)

        assert valid["validation_status"] == VALID_FOR_PREVIEW
        assert valid["schema_check_result"] == "review_feedback_schema_check_passed"

        mismatched = example_valid_feedback_for_preview()
        mismatched["master_taskbook_hash"] = "0" * 64
        self.attach_master_hash_provenance(mismatched)
        rejected = validate_review_feedback_for_preview(mismatched, context)

        assert rejected["validation_status"] == INVALID_BINDING_MISMATCH
        assert rejected["schema_check_result"] == "review_feedback_schema_check_failed_closed"
        assert "EVIDENCE_PROVENANCE_COMPLETION_MISMATCH" in {
            item["code"] for item in rejected["validation_errors"]
        }

    def test_expected_stage_hash_context_is_forwarded_to_provenance_validator(self) -> None:
        context = example_validation_context()
        mismatched = example_valid_feedback_for_preview()
        mismatched["stage_taskbook_hash"] = "f" * 64
        self.attach_master_hash_provenance(mismatched)

        rejected = validate_review_feedback_for_preview(mismatched, context)

        assert rejected["validation_status"] == INVALID_BINDING_MISMATCH
        assert rejected["schema_check_result"] == "review_feedback_schema_check_failed_closed"
        assert "EVIDENCE_PROVENANCE_COMPLETION_MISMATCH" in {
            item["code"] for item in rejected["validation_errors"]
        }

    def test_unknown_decision_fails_closed(self) -> None:
        feedback = example_valid_feedback_for_preview()
        feedback["review_decision_value"] = "AUTO_ACCEPT"

        result = validate_review_feedback_for_preview(feedback, example_validation_context())

        assert result["validation_status"] == INVALID_UNKNOWN_REVIEW_DECISION
        assert result["normalized_review_decision_value"] is None

    def test_pass_alias_without_policy_fails_closed(self) -> None:
        feedback = example_valid_feedback_for_preview()
        feedback["review_decision_value"] = "PASS"
        feedback["pass_alias_policy_id_when_used"] = None

        result = validate_review_feedback_for_preview(feedback, example_validation_context())

        assert result["validation_status"] == INVALID_PASS_ALIAS_POLICY_MISSING
        assert result["pass_alias_policy_check"]["policy_ref_present"] is False

    def test_pass_alias_with_policy_is_valid_for_preview(self) -> None:
        feedback = example_valid_feedback_for_preview()
        feedback["review_decision_value"] = "PASS"
        feedback["pass_alias_policy_id_when_used"] = "legacy-pass-alias-policy-v1"

        result = validate_review_feedback_for_preview(feedback, example_validation_context())

        assert result["validation_status"] == VALID_FOR_PREVIEW
        assert result["normalized_review_decision_value"] == "ACCEPT"
        assert result["delivery_state_transitioned"] is False

    def test_forbidden_authority_claim_fails_closed(self) -> None:
        feedback = example_valid_feedback_for_preview()
        feedback["review_feedback_authorizes_executor_continuation"] = True

        result = validate_review_feedback_for_preview(feedback, example_validation_context())

        assert result["validation_status"] == INVALID_FORBIDDEN_AUTHORITY_CLAIM
        assert result["forbidden_claim_check"]["status"] == "failed_closed"

    def test_result_contract_rejects_commander_request_output(self) -> None:
        result = validate_review_feedback_for_preview(example_valid_feedback_for_preview(), example_validation_context())
        mutated = copy.deepcopy(result)
        mutated["commander_decision_request_created"] = True

        with self.assertRaises(ReviewFeedbackValidatorError) as raised:
            assert_review_feedback_validator_result_contract(mutated)

        assert raised.exception.error_code == "FORBIDDEN_REVIEW_FEEDBACK_VALIDATOR_OUTPUT"


if __name__ == "__main__":
    unittest.main()
