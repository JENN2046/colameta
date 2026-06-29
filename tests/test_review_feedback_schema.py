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


class ReviewFeedbackSchemaTests(unittest.TestCase):
    def test_valid_feedback_passes_without_authority_effects(self) -> None:
        result = validate_review_feedback_schema(example_review_feedback())

        assert result["review_feedback_schema_check_result"] == REVIEW_FEEDBACK_SCHEMA_CHECK_PASSED
        assert result["review_decision_created"] is False
        assert result["gate_event_emitted"] is False
        assert result["delivery_state_transitioned"] is False

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

    def test_non_object_feedback_fails_closed(self) -> None:
        result = validate_review_feedback_schema("not feedback")  # type: ignore[arg-type]

        assert result["review_feedback_schema_check_result"] == REVIEW_FEEDBACK_SCHEMA_CHECK_FAILED_CLOSED
        assert result["recognized_fields"] == []
        assert result["rejection_reasons"][0]["code"] == "REVIEW_FEEDBACK_INVALID"


if __name__ == "__main__":
    unittest.main()

