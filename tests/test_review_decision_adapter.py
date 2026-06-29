from __future__ import annotations

import copy
import unittest

from runner.review_decision_adapter import (
    ADAPTER_STATUS_ADAPTED,
    ADAPTER_STATUS_FAILED_CLOSED,
    ReviewDecisionAdapterError,
    adapt_review_decision_value,
    assert_review_decision_adapter_contract,
    review_decision_adapter_inventory,
)


class ReviewDecisionAdapterTests(unittest.TestCase):
    def test_native_values_map_to_themselves_without_authority_effects(self) -> None:
        for value in ("ACCEPT", "NEEDS_FIX", "PLAN_ADJUST", "ABORT"):
            with self.subTest(value=value):
                result = adapt_review_decision_value(value)
                assert result["adapter_status"] == ADAPTER_STATUS_ADAPTED
                assert result["normalized_review_decision_value"] == value
                assert result["alias_disclosure"]["alias_used"] is False
                assert result["review_decision_created"] is False
                assert result["gate_event_emitted"] is False
                assert result["delivery_state_transitioned"] is False

    def test_pass_alias_requires_policy_ref(self) -> None:
        result = adapt_review_decision_value("PASS")

        assert result["adapter_status"] == ADAPTER_STATUS_FAILED_CLOSED
        assert result["normalized_review_decision_value"] is None
        assert result["adapter_errors"][0]["code"] == "PASS_ALIAS_POLICY_REF_MISSING"

    def test_pass_alias_with_policy_ref_maps_to_accept_and_surfaces_alias(self) -> None:
        result = adapt_review_decision_value("PASS", alias_policy_ref="legacy-pass-alias-policy-v1")

        assert result["adapter_status"] == ADAPTER_STATUS_ADAPTED
        assert result["normalized_review_decision_value"] == "ACCEPT"
        assert result["alias_policy_ref_when_used"] == "legacy-pass-alias-policy-v1"
        assert result["alias_disclosure"]["must_surface_alias"] is True
        assert result["alias_disclosure"]["does_not_mean_delivery_state_accepted"] is True

    def test_unknown_value_fails_closed(self) -> None:
        result = adapt_review_decision_value("AUTO_ACCEPT")

        assert result["adapter_status"] == ADAPTER_STATUS_FAILED_CLOSED
        assert result["adapter_errors"][0]["code"] == "UNKNOWN_REVIEW_VALUE"

    def test_runtime_state_equivalence_value_fails_closed(self) -> None:
        result = adapt_review_decision_value("PASSED")

        assert result["adapter_status"] == ADAPTER_STATUS_FAILED_CLOSED
        assert result["adapter_errors"][0]["code"] == "RUNTIME_STATE_EQUIVALENCE_FORBIDDEN"

    def test_forbidden_equivalence_claim_fails_closed(self) -> None:
        result = adapt_review_decision_value("ACCEPT", forbidden_equivalence_claims={"ACCEPT_equals_delivery_state_accepted": True})

        assert result["adapter_status"] == ADAPTER_STATUS_FAILED_CLOSED
        assert result["adapter_errors"][0]["code"] == "FORBIDDEN_RUNTIME_OR_DELIVERY_STATE_EQUIVALENCE"

    def test_inventory_lists_runtime_values_as_rejected(self) -> None:
        inventory = review_decision_adapter_inventory()

        assert "ACCEPT" in inventory["accepted_native_values"]
        assert inventory["legacy_alias_values"]["PASS"]["requires_policy_ref"] is True
        assert "PASSED" in inventory["runtime_state_values_rejected"]

    def test_contract_rejects_review_decision_creation_claim(self) -> None:
        result = adapt_review_decision_value("ACCEPT")
        mutated = copy.deepcopy(result)
        mutated["review_decision_created"] = True

        with self.assertRaises(ReviewDecisionAdapterError) as raised:
            assert_review_decision_adapter_contract(mutated)

        assert raised.exception.error_code == "FORBIDDEN_REVIEW_DECISION_ADAPTER_OUTPUT"


if __name__ == "__main__":
    unittest.main()

