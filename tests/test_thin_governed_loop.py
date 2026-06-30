from __future__ import annotations

import copy
import unittest

from runner.thin_governed_loop import (
    THIN_LOOP_FAILED_CLOSED,
    THIN_LOOP_PASSED,
    example_stage_3_6_inputs,
    run_stage_3_6_thin_governed_loop,
)


class ThinGovernedLoopTests(unittest.TestCase):
    def test_stage_3_6_thin_loop_connects_import_to_feedback_without_authority(self) -> None:
        result = run_stage_3_6_thin_governed_loop(example_stage_3_6_inputs())

        assert result["thin_loop_status"] == THIN_LOOP_PASSED
        assert result["blockers"] == []
        assert result["thin_loop_path"] == [
            "external_taskbook_import",
            "execution_envelope",
            "local_execution_receipt",
            "reviewer_handoff_package",
            "review_feedback_intake",
        ]
        assert result["stage_results"]["stage_03_import"]["adoption_preview"] == "adoption_preview_ready"
        assert result["stage_results"]["stage_04_execution_evidence"]["audit_package_handoff_readiness"] == "ready_for_reviewer_handoff"
        assert result["stage_results"]["stage_05_reviewer_handoff"]["handoff_generation"] == "reviewer_handoff_package_generated"
        assert result["stage_results"]["stage_06_feedback_intake"]["feedback_classification"] == "review_feedback_classification_ready"
        assert result["requested_commander_action"] == "ask_whether_to_prepare_rework_or_gate_return"
        assert result["delivery_state_accepted"] is False
        assert result["review_decision_created"] is False
        assert result["gate_event_emitted"] is False
        assert result["executor_dispatch_authorized"] is False
        assert all(value is False for value in result["authority_boundary"].values())

    def test_stage_3_6_thin_loop_fails_closed_on_import_mismatch(self) -> None:
        inputs = example_stage_3_6_inputs()
        inputs["external_taskbook_claim"] = copy.deepcopy(inputs["external_taskbook_claim"])
        inputs["external_taskbook_claim"]["stage_taskbook_ref"]["stage_id"] = "stage_99_wrong"

        result = run_stage_3_6_thin_governed_loop(inputs)

        assert result["thin_loop_status"] == THIN_LOOP_FAILED_CLOSED
        assert any(item["stage"] == "stage_03_import" for item in result["blockers"])
        assert result["delivery_state_accepted"] is False
        assert result["review_decision_created"] is False
        assert result["gate_event_emitted"] is False

    def test_stage_3_6_thin_loop_fails_closed_on_feedback_binding_mismatch(self) -> None:
        inputs = example_stage_3_6_inputs()
        inputs["review_feedback"] = copy.deepcopy(inputs["review_feedback"])
        inputs["review_feedback"]["workspace_snapshot_ref"] = {"head": "different-head"}

        result = run_stage_3_6_thin_governed_loop(inputs)

        assert result["thin_loop_status"] == THIN_LOOP_FAILED_CLOSED
        assert any(item["stage"] == "stage_06_feedback_intake" for item in result["blockers"])
        assert result["requested_commander_action"] == "ask_whether_to_return_for_clarification"
        assert result["delivery_state_accepted"] is False

    def test_stage_3_6_thin_loop_fails_closed_on_missing_review_value(self) -> None:
        inputs = example_stage_3_6_inputs()
        inputs["review_feedback"] = copy.deepcopy(inputs["review_feedback"])
        del inputs["review_feedback"]["review_decision_value"]

        result = run_stage_3_6_thin_governed_loop(inputs)

        assert result["thin_loop_status"] == THIN_LOOP_FAILED_CLOSED
        assert any(item["field"] == "review_decision_adapter" for item in result["blockers"])
        assert result["delivery_state_accepted"] is False


if __name__ == "__main__":
    unittest.main()
