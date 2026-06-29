from __future__ import annotations

import copy
import unittest

from runner.review_feedback_classification import (
    CLASSIFICATION_FAILED_CLOSED,
    CLASSIFICATION_READY,
    ReviewFeedbackClassificationError,
    assert_review_feedback_classification_contract,
    classification_mapping_inventory,
    classify_review_feedback,
)
from runner.review_feedback_preview import build_review_feedback_preview
from runner.review_feedback_validator import (
    example_valid_feedback_for_preview,
    example_validation_context,
    validate_review_feedback_for_preview,
)


class ReviewFeedbackClassificationTests(unittest.TestCase):
    def classification_for_decision(self, decision: str, *, pass_alias_policy: str | None = None) -> dict:
        feedback = example_valid_feedback_for_preview()
        feedback["review_decision_value"] = decision
        feedback["pass_alias_policy_id_when_used"] = pass_alias_policy
        validation = validate_review_feedback_for_preview(feedback, example_validation_context())
        preview = build_review_feedback_preview(feedback, validation)
        policy = {"mapping_policy_id": "stage-06-v6-4-decision-mapping"}
        if pass_alias_policy:
            policy["pass_alias_policy_ref"] = pass_alias_policy
        return classify_review_feedback(feedback, validation, preview, policy)

    def test_accept_classification_ready_without_authorization(self) -> None:
        result = self.classification_for_decision("ACCEPT")

        assert result["classification_status"] == CLASSIFICATION_READY
        assert result["normalized_classification"] == "accept_review_feedback"
        assert result["requested_commander_action"] == "ask_whether_to_request_delivery_state_gate_review"
        assert result["commander_authorization_granted"] is False
        assert result["delivery_state_transitioned"] is False

    def test_all_native_decisions_map_to_classifications(self) -> None:
        expected = {
            "NEEDS_FIX": "needs_fix_review_feedback",
            "PLAN_ADJUST": "plan_adjust_review_feedback",
            "ABORT": "abort_review_feedback",
        }

        for decision, classification in expected.items():
            with self.subTest(decision=decision):
                result = self.classification_for_decision(decision)
                assert result["normalized_classification"] == classification

    def test_pass_alias_requires_policy_ref(self) -> None:
        feedback = example_valid_feedback_for_preview()
        feedback["review_decision_value"] = "PASS"
        feedback["pass_alias_policy_id_when_used"] = "legacy-pass-alias-policy-v1"
        validation = validate_review_feedback_for_preview(feedback, example_validation_context())
        preview = build_review_feedback_preview(feedback, validation)

        result = classify_review_feedback(feedback, validation, preview, {"mapping_policy_id": "stage-06-v6-4-decision-mapping"})

        assert result["classification_status"] == CLASSIFICATION_FAILED_CLOSED
        assert result["normalized_classification"] == "accept_review_feedback"

    def test_pass_alias_with_policy_ref_maps_to_accept_classification(self) -> None:
        result = self.classification_for_decision("PASS", pass_alias_policy="legacy-pass-alias-policy-v1")

        assert result["classification_status"] == CLASSIFICATION_READY
        assert result["normalized_classification"] == "accept_review_feedback"
        assert result["pass_alias_handling"]["pass_alias_used"] is True

    def test_invalid_preview_fails_closed(self) -> None:
        feedback = example_valid_feedback_for_preview()
        validation = validate_review_feedback_for_preview(feedback, example_validation_context())
        result = classify_review_feedback(feedback, validation, {"preview_status": "failed"}, {"mapping_policy_id": "policy"})

        assert result["classification_status"] == CLASSIFICATION_FAILED_CLOSED

    def test_inventory_names_forbidden_claims(self) -> None:
        inventory = classification_mapping_inventory()

        assert inventory["decision_mapping"]["ACCEPT"] == "accept_review_feedback"
        assert "classification_is_delivery_state" in inventory["forbidden_classification_claims"]

    def test_contract_rejects_authorization_claim(self) -> None:
        result = self.classification_for_decision("ACCEPT")
        mutated = copy.deepcopy(result)
        mutated["commander_authorization_granted"] = True

        with self.assertRaises(ReviewFeedbackClassificationError) as raised:
            assert_review_feedback_classification_contract(mutated)

        assert raised.exception.error_code == "FORBIDDEN_REVIEW_FEEDBACK_CLASSIFICATION_CLAIM"


if __name__ == "__main__":
    unittest.main()

