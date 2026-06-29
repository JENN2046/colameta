from __future__ import annotations

import copy
import unittest

from runner.commander_decision_request import (
    COMMANDER_DECISION_REQUEST_AVAILABLE,
    CommanderDecisionRequestError,
    assert_commander_decision_request_contract,
    build_commander_decision_request,
    commander_decision_request_field_inventory,
)
from runner.review_feedback_classification import classify_review_feedback
from runner.review_feedback_preview import build_review_feedback_preview
from runner.review_feedback_validator import (
    example_valid_feedback_for_preview,
    example_validation_context,
    validate_review_feedback_for_preview,
)


class CommanderDecisionRequestTests(unittest.TestCase):
    def request_for_decision(self, decision: str, *, pass_alias_policy: str | None = None) -> dict:
        feedback = example_valid_feedback_for_preview()
        feedback["review_decision_value"] = decision
        feedback["pass_alias_policy_id_when_used"] = pass_alias_policy
        validation = validate_review_feedback_for_preview(feedback, example_validation_context())
        preview = build_review_feedback_preview(feedback, validation)
        policy = {"mapping_policy_id": "stage-06-v6-4-decision-mapping"}
        if pass_alias_policy:
            policy["pass_alias_policy_ref"] = pass_alias_policy
        classification = classify_review_feedback(feedback, validation, preview, policy)
        return build_commander_decision_request(classification, feedback)

    def test_accept_request_contains_bindings_without_authorization(self) -> None:
        request = self.request_for_decision("ACCEPT")

        assert request["request_status"] == COMMANDER_DECISION_REQUEST_AVAILABLE
        assert request["normalized_classification"] == "accept_review_feedback"
        assert request["commander_authorization_granted"] is False
        assert request["emit_gate_event"] is False
        assert request["delivery_state_transitioned"] is False

    def test_native_decision_requests_map_to_actions(self) -> None:
        expected = {
            "NEEDS_FIX": "ask_whether_to_prepare_rework_or_gate_return",
            "PLAN_ADJUST": "ask_whether_to_prepare_plan_adjustment_draft",
            "ABORT": "ask_whether_to_prepare_abort_or_supersede_handling",
        }

        for decision, action in expected.items():
            with self.subTest(decision=decision):
                request = self.request_for_decision(decision)
                assert request["requested_commander_action"] == action
                assert request["execute_requested_action"] is False

    def test_pass_alias_request_maps_without_delivery_state(self) -> None:
        request = self.request_for_decision("PASS", pass_alias_policy="legacy-pass-alias-policy-v1")

        assert request["normalized_classification"] == "accept_review_feedback"
        assert request["source_review_decision_value"] == "PASS"
        assert request["delivery_state_transitioned"] is False

    def test_request_field_inventory_lists_allowed_responses(self) -> None:
        inventory = commander_decision_request_field_inventory()

        assert "commander_decision_request_id" in inventory["required_fields"]
        assert "AUTHORIZE_GATE_REVIEW_REQUEST" in inventory["allowed_commander_responses"]
        assert "emit_gate_event" in inventory["forbidden_request_effects"]

    def test_contract_rejects_missing_non_authority_notice(self) -> None:
        request = self.request_for_decision("ACCEPT")
        mutated = copy.deepcopy(request)
        mutated["non_authority_notice"]["request_does_not_emit_gate_event"] = False

        with self.assertRaises(CommanderDecisionRequestError) as raised:
            assert_commander_decision_request_contract(mutated)

        assert raised.exception.error_code == "COMMANDER_DECISION_REQUEST_NOTICE_MISSING"

    def test_contract_rejects_forbidden_effect(self) -> None:
        request = self.request_for_decision("ACCEPT")
        mutated = copy.deepcopy(request)
        mutated["emit_gate_event"] = True

        with self.assertRaises(CommanderDecisionRequestError) as raised:
            assert_commander_decision_request_contract(mutated)

        assert raised.exception.error_code == "FORBIDDEN_COMMANDER_DECISION_REQUEST_EFFECT"


if __name__ == "__main__":
    unittest.main()

