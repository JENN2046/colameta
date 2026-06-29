from __future__ import annotations

import copy
import unittest

from runner.review_feedback_preview import (
    PREVIEW_AVAILABLE,
    PREVIEW_FAILED_CLOSED,
    ReviewFeedbackPreviewError,
    assert_review_feedback_preview_contract,
    build_review_feedback_preview,
    preview_mapping_inventory,
)
from runner.review_feedback_validator import (
    example_valid_feedback_for_preview,
    example_validation_context,
    validate_review_feedback_for_preview,
)


class ReviewFeedbackPreviewTests(unittest.TestCase):
    def preview_for_decision(self, decision: str, *, pass_alias_policy: str | None = None) -> dict:
        feedback = example_valid_feedback_for_preview()
        feedback["review_decision_value"] = decision
        feedback["pass_alias_policy_id_when_used"] = pass_alias_policy
        validation = validate_review_feedback_for_preview(feedback, example_validation_context())
        return build_review_feedback_preview(feedback, validation)

    def test_accept_preview_creates_no_request_or_state(self) -> None:
        preview = self.preview_for_decision("ACCEPT")

        assert preview["preview_status"] == PREVIEW_AVAILABLE
        assert preview["candidate_classification"] == "candidate_accept_path"
        assert preview["commander_decision_request_created"] is False
        assert preview["review_decision_created"] is False
        assert preview["gate_event_emitted"] is False
        assert preview["delivery_state_transitioned"] is False

    def test_needs_fix_preview_maps_to_rework_question(self) -> None:
        preview = self.preview_for_decision("NEEDS_FIX")

        assert preview["candidate_classification"] == "candidate_needs_fix_path"
        assert "rework" in preview["candidate_commander_decision_request_shape"]["preview_question"]

    def test_plan_adjust_preview_maps_without_plan_mutation(self) -> None:
        preview = self.preview_for_decision("PLAN_ADJUST")

        assert preview["candidate_classification"] == "candidate_plan_adjust_path"
        assert preview["boundary_notice"]["preview_is_not_plan_mutation"] is True

    def test_abort_preview_maps_without_runtime_cancel(self) -> None:
        preview = self.preview_for_decision("ABORT")

        assert preview["candidate_classification"] == "candidate_abort_path"
        assert preview["candidate_commander_decision_request_shape"]["commander_decision_request_id_created"] is False

    def test_pass_alias_preview_preserves_alias_notice(self) -> None:
        preview = self.preview_for_decision("PASS", pass_alias_policy="legacy-pass-alias-policy-v1")

        assert preview["candidate_classification"] == "candidate_accept_path"
        assert preview["alias_mapping_notice"]["pass_alias_used"] is True
        assert preview["alias_mapping_notice"]["does_not_mean_delivery_state_accepted"] is True

    def test_invalid_validation_status_fails_closed(self) -> None:
        feedback = example_valid_feedback_for_preview()
        validation = {"validation_status": "invalid_binding_mismatch"}

        preview = build_review_feedback_preview(feedback, validation)

        assert preview["preview_status"] == PREVIEW_FAILED_CLOSED
        assert preview["candidate_classification"] == "candidate_blocked_unclear_feedback"
        assert preview["candidate_commander_decision_request_shape"] is None

    def test_mapping_inventory_includes_all_candidate_paths(self) -> None:
        inventory = preview_mapping_inventory()

        assert "candidate_accept_path" in inventory["candidate_classification_values"]
        assert "candidate_blocked_unclear_feedback" in inventory["candidate_classification_values"]
        assert "commander_decision_request_id" in inventory["forbidden_outputs"]

    def test_contract_rejects_actionable_request_id(self) -> None:
        preview = self.preview_for_decision("ACCEPT")
        mutated = copy.deepcopy(preview)
        mutated["candidate_commander_decision_request_shape"]["commander_decision_request_id"] = "cdr-1"

        with self.assertRaises(ReviewFeedbackPreviewError) as raised:
            assert_review_feedback_preview_contract(mutated)

        assert raised.exception.error_code == "FORBIDDEN_REVIEW_FEEDBACK_PREVIEW_OUTPUT"

    def test_contract_rejects_missing_boundary_notice(self) -> None:
        preview = self.preview_for_decision("ACCEPT")
        mutated = copy.deepcopy(preview)
        mutated["boundary_notice"]["preview_is_not_gate_event"] = False

        with self.assertRaises(ReviewFeedbackPreviewError) as raised:
            assert_review_feedback_preview_contract(mutated)

        assert raised.exception.error_code == "PREVIEW_BOUNDARY_NOTICE_MISSING"


if __name__ == "__main__":
    unittest.main()

