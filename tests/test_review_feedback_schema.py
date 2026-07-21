from __future__ import annotations

import copy
import unittest

from runner.review_feedback_schema import (
    REVIEW_FEEDBACK_SCHEMA_CHECK_FAILED_CLOSED,
    REVIEW_FEEDBACK_SCHEMA_CHECK_PASSED,
    ReviewFeedbackSchemaError,
    assert_review_feedback_schema_result_contract,
    example_review_feedback,
    review_feedback_field_inventory,
    validate_review_feedback_schema,
)
from runner.validation_truth import evidence_record_sha256


class ReviewFeedbackSchemaTests(unittest.TestCase):
    def attach_provenance(
        self,
        feedback: dict,
        *,
        subject_path: str = "$",
        claimed_subject: str = "review",
        claimed_completed: bool = True,
    ) -> None:
        subjects = {
            "$": "review",
            "$.master_taskbook_hash": "hash_binding",
            "$.stage_taskbook_hash": "hash_binding",
        }
        paths = list(subjects)
        if subject_path not in subjects:
            paths.append(subject_path)
        digest = evidence_record_sha256(feedback)
        feedback["evidence_provenance"] = {
            "schema_version": "evidence_provenance.v1",
            "entries": [
                {
                    "subject_path": path,
                    "evidence_kind": "observed",
                    "binding": {
                        "record_id": feedback["review_feedback_id"],
                        "record_schema_version": feedback["review_feedback_schema_version"],
                        "subject_path": path,
                        "content_sha256": digest,
                    },
                    "claimed_evidence_subject": (
                        claimed_subject if path == subject_path else subjects[path]
                    ),
                    "claimed_subject_requires_execution": False,
                    "claimed_subject_operation_completed": (
                        claimed_completed if path == subject_path else True
                    ),
                    "claimed_execution_performed": False,
                    "claimed_eligible_for_acceptance": True,
                }
                for path in paths
            ],
        }

    def test_valid_feedback_passes_without_authority_effects(self) -> None:
        result = validate_review_feedback_schema(example_review_feedback())

        assert result["review_feedback_schema_check_result"] == REVIEW_FEEDBACK_SCHEMA_CHECK_PASSED
        assert result["review_decision_created"] is False
        assert result["gate_event_emitted"] is False
        assert result["delivery_state_transitioned"] is False
        assert result["evidence_provenance"]["provenance_status"] == "legacy_unclassified"

    def test_observed_review_and_hash_binding_need_no_execution(self) -> None:
        review = example_review_feedback()
        self.attach_provenance(review)
        review_result = validate_review_feedback_schema(
            review,
            expected_master_taskbook_hash=review["master_taskbook_hash"],
            expected_stage_taskbook_hash=review["stage_taskbook_hash"],
        )

        hash_binding = example_review_feedback()
        self.attach_provenance(
            hash_binding,
            subject_path="$.master_taskbook_hash",
            claimed_subject="hash_binding",
        )
        hash_result = validate_review_feedback_schema(
            hash_binding,
            expected_master_taskbook_hash=hash_binding["master_taskbook_hash"],
            expected_stage_taskbook_hash=hash_binding["stage_taskbook_hash"],
        )

        for result in (review_result, hash_result):
            assert result["review_feedback_schema_check_result"] == REVIEW_FEEDBACK_SCHEMA_CHECK_PASSED
            assert all(
                entry["subject_requires_execution"] is False
                and entry["execution_performed"] is False
                and entry["eligible_for_acceptance"] is True
                for entry in result["evidence_provenance"]["entries"]
            )

    def test_hash_binding_needs_authoritative_expected_hash(self) -> None:
        feedback = example_review_feedback()
        self.attach_provenance(
            feedback,
            subject_path="$.master_taskbook_hash",
            claimed_subject="hash_binding",
        )

        missing_context = validate_review_feedback_schema(feedback)
        mismatched_context = validate_review_feedback_schema(
            feedback,
            expected_master_taskbook_hash="0" * 64,
        )

        for result in (missing_context, mismatched_context):
            assert result["review_feedback_schema_check_result"] == (
                REVIEW_FEEDBACK_SCHEMA_CHECK_FAILED_CLOSED
            )
            assert result["evidence_provenance"]["eligible_for_acceptance"] is False
            assert "EVIDENCE_PROVENANCE_COMPLETION_MISMATCH" in {
                item["code"] for item in result["rejection_reasons"]
            }

    def test_review_provenance_downgrade_path_and_completion_fail_closed(self) -> None:
        downgrade = example_review_feedback()
        self.attach_provenance(downgrade, claimed_subject="execution")
        downgrade_result = validate_review_feedback_schema(downgrade)

        path = example_review_feedback()
        self.attach_provenance(path, subject_path="$.reviewer_notes")
        path_result = validate_review_feedback_schema(path)

        completion = example_review_feedback()
        self.attach_provenance(completion, claimed_completed=False)
        completion_result = validate_review_feedback_schema(completion)

        assert "EVIDENCE_PROVENANCE_SUBJECT_DOWNGRADE" in {
            item["code"] for item in downgrade_result["rejection_reasons"]
        }
        assert "EVIDENCE_PROVENANCE_PATH_MISMATCH" in {
            item["code"] for item in path_result["rejection_reasons"]
        }
        assert "EVIDENCE_PROVENANCE_COMPLETION_MISMATCH" in {
            item["code"] for item in completion_result["rejection_reasons"]
        }

    def test_field_inventory_includes_required_decisions_and_boundary(self) -> None:
        inventory = review_feedback_field_inventory()

        assert inventory["allowed_review_decision_values"] == ["ACCEPT", "NEEDS_FIX", "PLAN_ADJUST", "ABORT"]
        assert inventory["legacy_aliases"]["PASS"]["maps_to"] == "ACCEPT"
        assert all(value is False for value in inventory["authority_boundary"].values())

    def test_missing_handoff_ref_fails_closed(self) -> None:
        feedback = example_review_feedback()
        feedback["reviewer_handoff_package_ref"] = {}

        result = validate_review_feedback_schema(feedback)

        assert result["review_feedback_schema_check_result"] == REVIEW_FEEDBACK_SCHEMA_CHECK_FAILED_CLOSED
        assert "reviewer_handoff_package_ref" in result["rejected_fields"]

    def test_invalid_master_hash_fails_closed(self) -> None:
        feedback = example_review_feedback()
        feedback["master_taskbook_hash"] = "not-a-hash"

        result = validate_review_feedback_schema(feedback)

        assert result["review_feedback_schema_check_result"] == REVIEW_FEEDBACK_SCHEMA_CHECK_FAILED_CLOSED
        assert "master_taskbook_hash" in result["rejected_fields"]

    def test_unknown_decision_value_fails_closed(self) -> None:
        feedback = example_review_feedback()
        feedback["review_decision_value"] = "AUTO_ACCEPT"

        result = validate_review_feedback_schema(feedback)

        assert result["review_feedback_schema_check_result"] == REVIEW_FEEDBACK_SCHEMA_CHECK_FAILED_CLOSED
        assert "review_decision_value" in result["rejected_fields"]

    def test_pass_alias_without_policy_ref_fails_closed(self) -> None:
        feedback = example_review_feedback(review_decision_value="PASS")

        result = validate_review_feedback_schema(feedback)

        assert result["review_feedback_schema_check_result"] == REVIEW_FEEDBACK_SCHEMA_CHECK_FAILED_CLOSED
        assert result["normalized_review_decision_value"] is None

    def test_pass_alias_with_policy_ref_maps_only_to_accept(self) -> None:
        feedback = example_review_feedback(
            review_decision_value="PASS",
            pass_alias_policy_id_when_used="legacy-pass-alias-policy-v1",
        )

        result = validate_review_feedback_schema(feedback)

        assert result["review_feedback_schema_check_result"] == REVIEW_FEEDBACK_SCHEMA_CHECK_PASSED
        assert result["pass_alias_used"] is True
        assert result["normalized_review_decision_value"] == "ACCEPT"
        assert result["delivery_state_transitioned"] is False

    def test_forbidden_delivery_state_claim_fails_closed(self) -> None:
        feedback = example_review_feedback()
        feedback["accept_means_delivery_state_accepted"] = True

        result = validate_review_feedback_schema(feedback)

        assert result["review_feedback_schema_check_result"] == REVIEW_FEEDBACK_SCHEMA_CHECK_FAILED_CLOSED
        assert "FORBIDDEN_REVIEW_FEEDBACK_AUTHORITY_CLAIM" in {item["code"] for item in result["rejection_reasons"]}

    def test_result_contract_rejects_gate_event_emitted(self) -> None:
        result = validate_review_feedback_schema(example_review_feedback())
        mutated = copy.deepcopy(result)
        mutated["gate_event_emitted"] = True

        with self.assertRaises(ReviewFeedbackSchemaError) as raised:
            assert_review_feedback_schema_result_contract(mutated)

        assert raised.exception.error_code == "FORBIDDEN_REVIEW_FEEDBACK_SCHEMA_RESULT_CLAIM"

    def test_result_contract_rejects_provenance_authority_mutation(self) -> None:
        result = validate_review_feedback_schema(example_review_feedback())
        mutated = copy.deepcopy(result)
        mutated["evidence_provenance"]["authority_boundary"][
            "creates_review_decision"
        ] = True

        with self.assertRaises(ReviewFeedbackSchemaError) as raised:
            assert_review_feedback_schema_result_contract(mutated)

        assert raised.exception.error_code == "FORBIDDEN_REVIEW_FEEDBACK_SCHEMA_RESULT_CLAIM"

    def test_non_object_feedback_fails_closed(self) -> None:
        result = validate_review_feedback_schema("not feedback")  # type: ignore[arg-type]

        assert result["review_feedback_schema_check_result"] == REVIEW_FEEDBACK_SCHEMA_CHECK_FAILED_CLOSED
        assert result["recognized_fields"] == []
        assert result["rejection_reasons"][0]["code"] == "REVIEW_FEEDBACK_INVALID"


if __name__ == "__main__":
    unittest.main()
