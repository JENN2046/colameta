from __future__ import annotations

import copy
import unittest

from runner.commander_decision_request import build_commander_decision_request
from runner.plan_adjustment_preview import (
    PLAN_ADJUSTMENT_PREVIEW_AVAILABLE,
    PLAN_ADJUSTMENT_PREVIEW_FAILED_CLOSED,
    PlanAdjustmentPreviewError,
    assert_plan_adjustment_preview_contract,
    build_plan_adjustment_preview,
    plan_adjustment_preview_inventory,
)
from runner.review_feedback_classification import classify_review_feedback
from runner.review_feedback_preview import build_review_feedback_preview
from runner.review_feedback_validator import (
    example_valid_feedback_for_preview,
    example_validation_context,
    validate_review_feedback_for_preview,
)


class PlanAdjustmentPreviewTests(unittest.TestCase):
    def commander_request_for_decision(self, decision: str) -> dict:
        feedback = example_valid_feedback_for_preview()
        feedback["review_decision_value"] = decision
        validation = validate_review_feedback_for_preview(feedback, example_validation_context())
        preview = build_review_feedback_preview(feedback, validation)
        classification = classify_review_feedback(
            feedback,
            validation,
            preview,
            {"mapping_policy_id": "stage-06-v6-4-decision-mapping"},
        )
        return build_commander_decision_request(classification, feedback)

    def plan_adjust_context(self) -> dict:
        return {
            "commander_decision_request": self.commander_request_for_decision("PLAN_ADJUST"),
            "master_taskbook_ref": {
                "path": "PROJECT_MASTER_TASKBOOK.md",
                "sha256": "1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34",
            },
            "affected_stage_refs": [
                {
                    "stage_id": "stage_08_plan_adjustment_control",
                    "path": "docs/taskbooks/stages/STAGE_08_PLAN_ADJUSTMENT_CONTROL.md",
                }
            ],
            "affected_version_refs": [
                {
                    "version": "v1.14",
                    "name": "Stage 8 Plan Adjustment Request Preview V1",
                }
            ],
            "proposed_change_summary": "Preview a bounded taskbook wording change for Commander review.",
            "proposed_diff_or_patch_preview": {
                "candidate_only": True,
                "files": [
                    {
                        "path": "docs/taskbooks/stages/STAGE_08_PLAN_ADJUSTMENT_CONTROL.md",
                        "action": "preview_modify",
                    }
                ],
            },
            "continued_master_goal_service_explanation": "The proposed adjustment keeps Stage 8 aligned with the master goal by preserving preview-only control.",
            "drift_evidence_ref": {"drift_evidence_pack_id": "drift-evidence-pack-example"},
        }

    def test_plan_adjust_commander_request_builds_preview_without_apply(self) -> None:
        result = build_plan_adjustment_preview(self.plan_adjust_context())

        assert result["preview_status"] == PLAN_ADJUSTMENT_PREVIEW_AVAILABLE
        assert result["source_orientation"]["is_plan_adjust_oriented"] is True
        assert result["master_taskbook_hash"] == "1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34"
        assert result["drift_evidence_ref"] == {"drift_evidence_pack_id": "drift-evidence-pack-example"}
        assert result["apply_allowed"] is False
        assert result["apply_gate_status"]["apply_allowed"] is False
        assert result["plan_mutated"] is False
        assert result["master_goal_mutated"] is False
        assert result["reviewer_bypassed"] is False
        assert result["review_decision_created"] is False
        assert result["gate_event_emitted"] is False
        assert result["executor_continuation_authorized"] is False
        assert result["commit_or_push"] is False
        assert result["route_transitioned"] is False
        assert result["delivery_state_accepted"] is False

    def test_optional_drift_evidence_is_not_required(self) -> None:
        context = self.plan_adjust_context()
        context.pop("drift_evidence_ref")

        result = build_plan_adjustment_preview(context)

        assert result["preview_status"] == PLAN_ADJUSTMENT_PREVIEW_AVAILABLE
        assert result["drift_evidence_ref"] is None

    def test_non_plan_adjust_source_fails_closed(self) -> None:
        context = self.plan_adjust_context()
        context["commander_decision_request"] = self.commander_request_for_decision("ACCEPT")

        result = build_plan_adjustment_preview(context)

        assert result["preview_status"] == PLAN_ADJUSTMENT_PREVIEW_FAILED_CLOSED
        assert "PLAN_ADJUST_SOURCE_REQUIRED" in {item["code"] for item in result["validation_errors"]}
        assert result["apply_allowed"] is False
        assert result["plan_mutated"] is False

    def test_missing_required_binding_fails_closed(self) -> None:
        context = self.plan_adjust_context()
        context.pop("master_taskbook_ref")

        result = build_plan_adjustment_preview(context)

        assert result["preview_status"] == PLAN_ADJUSTMENT_PREVIEW_FAILED_CLOSED
        missing_errors = [item for item in result["validation_errors"] if item["code"] == "PLAN_ADJUSTMENT_REQUIRED_FIELD_MISSING"]
        assert missing_errors
        assert "master_taskbook_ref" in missing_errors[0]["details"]["missing_fields"]

    def test_recursively_rejects_forbidden_truthy_claims_without_echoing_patch(self) -> None:
        context = self.plan_adjust_context()
        context["proposed_diff_or_patch_preview"]["ops"] = [
            {
                "path": "/versions/0",
                "value": {
                    "apply_allowed": "authorized",
                },
            }
        ]

        result = build_plan_adjustment_preview(context)

        assert result["preview_status"] == PLAN_ADJUSTMENT_PREVIEW_FAILED_CLOSED
        assert "FORBIDDEN_PLAN_ADJUSTMENT_AUTHORITY_CLAIM" in {item["code"] for item in result["validation_errors"]}
        assert "proposed_diff_or_patch_preview" not in result
        assert result["apply_allowed"] is False

    def test_json_patch_forbidden_target_path_fails_closed_without_echoing_patch(self) -> None:
        context = self.plan_adjust_context()
        context["proposed_diff_or_patch_preview"] = {
            "json_patch": [
                {
                    "op": "replace",
                    "path": "/delivery_state_accepted",
                    "value": True,
                }
            ]
        }

        result = build_plan_adjustment_preview(context)

        assert result["preview_status"] == PLAN_ADJUSTMENT_PREVIEW_FAILED_CLOSED
        assert "FORBIDDEN_PLAN_ADJUSTMENT_AUTHORITY_CLAIM" in {item["code"] for item in result["validation_errors"]}
        assert "proposed_diff_or_patch_preview" not in result
        assert result["apply_allowed"] is False

    def test_json_patch_segmented_forbidden_target_path_fails_closed(self) -> None:
        context = self.plan_adjust_context()
        context["proposed_diff_or_patch_preview"] = {
            "json_patch": [
                {
                    "op": "replace",
                    "path": "/review_decision/created",
                    "value": True,
                }
            ]
        }

        result = build_plan_adjustment_preview(context)

        assert result["preview_status"] == PLAN_ADJUSTMENT_PREVIEW_FAILED_CLOSED
        assert "FORBIDDEN_PLAN_ADJUSTMENT_AUTHORITY_CLAIM" in {item["code"] for item in result["validation_errors"]}

    def test_json_patch_pointer_forbidden_target_path_fails_closed(self) -> None:
        context = self.plan_adjust_context()
        context["proposed_diff_or_patch_preview"] = {
            "json_patch": [
                {
                    "pointer": "/gate_event/emitted",
                    "value": True,
                }
            ]
        }

        result = build_plan_adjustment_preview(context)

        assert result["preview_status"] == PLAN_ADJUSTMENT_PREVIEW_FAILED_CLOSED
        assert "FORBIDDEN_PLAN_ADJUSTMENT_AUTHORITY_CLAIM" in {item["code"] for item in result["validation_errors"]}

    def test_file_diff_path_with_forbidden_words_does_not_fail_closed(self) -> None:
        context = self.plan_adjust_context()
        context["proposed_diff_or_patch_preview"] = {
            "files": [
                {
                    "op": "modify",
                    "path": "docs/delivery_state_accepted_notes.md",
                    "action": "preview_modify",
                }
            ]
        }

        result = build_plan_adjustment_preview(context)

        assert result["preview_status"] == PLAN_ADJUSTMENT_PREVIEW_AVAILABLE
        assert result["validation_errors"] == []
        assert result["apply_allowed"] is False

    def test_project_master_taskbook_touch_requires_commander_hard_gate(self) -> None:
        context = self.plan_adjust_context()
        context["proposed_diff_or_patch_preview"] = {
            "files": [
                {
                    "path": "PROJECT_MASTER_TASKBOOK.md",
                    "action": "preview_modify",
                }
            ]
        }

        result = build_plan_adjustment_preview(context)

        assert result["preview_status"] == PLAN_ADJUSTMENT_PREVIEW_AVAILABLE
        assert result["commander_hard_gate_required"] is True
        assert result["apply_allowed"] is False
        assert any(reason["reason"] == "master_taskbook_path" for reason in result["commander_hard_gate_reasons"])

    def test_master_goal_field_touch_requires_commander_hard_gate(self) -> None:
        context = self.plan_adjust_context()
        context["proposed_diff_or_patch_preview"] = {
            "json_patch": [
                {
                    "op": "replace",
                    "path": "/project_final_goal",
                    "value": "Updated candidate wording.",
                }
            ]
        }

        result = build_plan_adjustment_preview(context)

        assert result["preview_status"] == PLAN_ADJUSTMENT_PREVIEW_AVAILABLE
        assert result["commander_hard_gate_required"] is True
        assert any(reason["reason"] == "master_goal_field" for reason in result["commander_hard_gate_reasons"])
        assert result["apply_gate_status"]["apply_allowed"] is False

    def test_non_master_preview_does_not_require_master_hard_gate(self) -> None:
        result = build_plan_adjustment_preview(self.plan_adjust_context())

        assert result["preview_status"] == PLAN_ADJUSTMENT_PREVIEW_AVAILABLE
        assert result["commander_hard_gate_required"] is False
        assert result["commander_hard_gate_reasons"] == []

    def test_contract_rejects_mutated_preview_claim(self) -> None:
        result = build_plan_adjustment_preview(self.plan_adjust_context())
        mutated = copy.deepcopy(result)
        mutated["plan_mutated"] = True

        with self.assertRaises(PlanAdjustmentPreviewError) as raised:
            assert_plan_adjustment_preview_contract(mutated)

        assert raised.exception.error_code == "FORBIDDEN_PLAN_ADJUSTMENT_PREVIEW_CLAIM"

    def test_does_not_mutate_inputs(self) -> None:
        context = self.plan_adjust_context()
        before = copy.deepcopy(context)

        build_plan_adjustment_preview(context)

        assert context == before

    def test_inventory_names_required_fields_and_forbidden_claims(self) -> None:
        inventory = plan_adjustment_preview_inventory()

        assert "source_refs" in inventory["required_fields"]
        assert inventory["accepted_source_indicators"]["requested_commander_action"] == "ask_whether_to_prepare_plan_adjustment_draft"
        assert "apply_allowed" in inventory["forbidden_claim_keys"]
        assert all(value is False for value in inventory["preview_only_boundaries"].values())


if __name__ == "__main__":
    unittest.main()
