from __future__ import annotations

import copy
import unittest
from pathlib import Path

from runner.core_orchestrator import WorkflowOrchestrator
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

    def test_thin_loop_workflow_entrypoint_is_read_only_preview(self) -> None:
        project_root = str(Path(__file__).resolve().parents[1])
        output = WorkflowOrchestrator(project_root).handle(
            "thin_governed_loop_preview",
            {"phase": "preview"},
        )

        assert output.ok is True
        assert output.workflow == "thin_governed_loop_preview"
        assert output.status == "succeeded"
        assert output.risk_level == "info"
        assert output.requires_confirmation is False
        assert output.changed_files == []
        assert output.preview_ids == []
        assert output.result["read_only"] is True
        assert output.result["side_effects"] is False
        assert output.result["input_mode"] == "example"
        assert output.result["thin_loop"]["thin_loop_status"] == THIN_LOOP_PASSED
        assert output.result["forbidden_authority_outputs"] == {
            "delivery_state_accepted": False,
            "review_decision_created": False,
            "gate_event_emitted": False,
            "executor_dispatch_authorized": False,
        }

    def test_thin_loop_workflow_accepts_real_input_objects(self) -> None:
        project_root = str(Path(__file__).resolve().parents[1])
        inputs = example_stage_3_6_inputs()
        output = WorkflowOrchestrator(project_root).handle(
            "thin_governed_loop_preview",
            {
                "phase": "preview",
                "input_mode": "provided",
                "current_head": inputs["current_head"],
                "external_taskbook_claim": inputs["external_taskbook_claim"],
                "execution_envelope": inputs["execution_envelope"],
                "local_execution_receipt": inputs["local_execution_receipt"],
                "review_feedback": inputs["review_feedback"],
            },
        )

        assert output.ok is True
        assert output.status == "succeeded"
        assert output.result["input_mode"] == "provided"
        assert output.result["thin_loop"]["thin_loop_status"] == THIN_LOOP_PASSED
        assert output.result["thin_loop"]["delivery_state_accepted"] is False
        assert output.result["forbidden_authority_outputs"]["delivery_state_accepted"] is False

    def test_thin_loop_workflow_template_mode_returns_input_contract_only(self) -> None:
        project_root = str(Path(__file__).resolve().parents[1])
        output = WorkflowOrchestrator(project_root).handle(
            "thin_governed_loop_preview",
            {"phase": "preview", "input_mode": "template"},
        )

        assert output.ok is True
        assert output.status == "succeeded"
        assert output.requires_confirmation is False
        assert output.changed_files == []
        assert output.preview_ids == []
        assert output.result["input_mode"] == "template"
        assert output.result["thin_loop"]["thin_loop_status"] == "thin_governed_loop_input_template_ready"
        contract = output.result["input_contract"]
        assert contract["accepted_input_modes"] == ["example", "template", "draft", "provided"]
        assert [item["field"] for item in contract["provided_mode_required_objects"]] == [
            "external_taskbook_claim",
            "execution_envelope",
            "local_execution_receipt",
            "review_feedback",
        ]
        assert contract["minimal_request_shape"]["input_mode"] == "provided"
        assert contract["draft_request_shape"]["input_mode"] == "draft"
        assert contract["draft_mode_output"]["submit_as"] == "thin_loop_inputs"
        assert contract["read_only_boundary"]["writes_delivery_state"] is False

    def test_thin_loop_workflow_draft_mode_returns_reusable_input_bundle(self) -> None:
        project_root = str(Path(__file__).resolve().parents[1])
        orchestrator = WorkflowOrchestrator(project_root)
        draft_seed = {
            "source_id": "seeded-thin-loop-taskbook",
            "allowed_files": ["runner/seeded_feature.py", "tests/test_seeded_feature.py"],
            "forbidden_files": ["PROJECT_MASTER_TASKBOOK.md", ".colameta/plan.json", "**/.env"],
            "validation_commands": ["python -m unittest tests.test_seeded_feature", "git diff --check"],
            "review_decision_value": "PLAN_ADJUST",
            "reviewer_notes": "Seeded review says the plan needs adjustment.",
            "unknown_seed_field": "ignored",
        }
        expected_applied_seed_fields = sorted(set(draft_seed) - {"unknown_seed_field"})

        draft_output = orchestrator.handle(
            "thin_governed_loop_preview",
            {"phase": "preview", "input_mode": "draft", "draft_seed": draft_seed},
        )

        assert draft_output.ok is True
        assert draft_output.status == "succeeded"
        assert draft_output.requires_confirmation is False
        assert draft_output.changed_files == []
        assert draft_output.preview_ids == []
        assert draft_output.result["input_mode"] == "draft"
        assert draft_output.result["thin_loop"]["thin_loop_status"] == "thin_governed_loop_input_draft_ready"
        assert draft_output.result["thin_loop"]["stage_results"] == {}
        assert draft_output.result["generated_input_bundle_summary"]["reusable_as"] == "thin_loop_inputs"
        assert "allowed_files" in draft_output.result["generated_input_bundle_summary"]["seed_fields_applied"]
        assert draft_output.result["generated_input_bundle_summary"]["seed_fields_ignored"] == ["unknown_seed_field"]
        assert draft_output.result["generated_input_bundle_summary"]["seed_fields_unknown"] == ["unknown_seed_field"]
        assert draft_output.result["generated_input_bundle_summary"]["copy_paste_field"] == "next_request_payload"
        assert draft_output.result["generated_input_bundle_summary"]["next_request_shape"]["thin_loop_inputs"] == "<generated_input_bundle>"
        assert draft_output.result["generated_input_bundle_summary"]["next_request_shape"]["input_mode"] == "provided"
        assert (
            draft_output.result["generated_input_bundle_summary"]["copy_paste_next_request_shape"]["field"]
            == "next_request_payload"
        )
        assert draft_output.result["generated_input_bundle_summary"]["next_request_shape"]["project_name"] == (
            "<same managed project_name or route used for this draft call>"
        )
        assert draft_output.result["forbidden_authority_outputs"]["executor_dispatch_authorized"] is False
        bundle = draft_output.result["generated_input_bundle"]
        next_request_payload = draft_output.result["next_request_payload"]
        assert draft_output.result["copy_paste_next_request"] == next_request_payload
        assert next_request_payload["workflow"] == "thin_governed_loop_preview"
        assert next_request_payload["phase"] == "preview"
        assert next_request_payload["input_mode"] == "provided"
        assert next_request_payload["thin_loop_inputs"] == bundle
        assert bundle["input_mode"] == "provided"
        assert isinstance(bundle["current_head"], str)
        assert bundle["current_head"]
        assert bundle["draft_seed_applied"] == expected_applied_seed_fields
        assert bundle["draft_seed_ignored"] == ["unknown_seed_field"]
        assert bundle["draft_seed_unknown"] == ["unknown_seed_field"]
        assert "unknown_seed_field" not in bundle["draft_seed_applied"]
        for field in (
            "external_taskbook_claim",
            "execution_envelope",
            "local_execution_receipt",
            "review_feedback",
        ):
            assert isinstance(bundle[field], dict)
        assert bundle["external_taskbook_claim"]["source"]["source_id"] == "seeded-thin-loop-taskbook"
        assert bundle["external_taskbook_claim"]["allowed_files"] == draft_seed["allowed_files"]
        assert bundle["execution_envelope"]["allowed_files"] == draft_seed["allowed_files"]
        assert bundle["execution_envelope"]["validation_commands"] == draft_seed["validation_commands"]
        assert bundle["local_execution_receipt"]["touched_files"] == draft_seed["allowed_files"]
        assert bundle["local_execution_receipt"]["validation_commands"] == draft_seed["validation_commands"]
        assert bundle["review_feedback"]["review_decision_value"] == "PLAN_ADJUST"
        assert bundle["review_feedback"]["reviewer_notes"] == draft_seed["reviewer_notes"]
        assert "draft" in draft_output.result["input_contract"]["accepted_input_modes"]
        assert "draft_seed" in draft_output.result["input_contract"]["transport"]["bundle_allowed_fields"]

        provided_output = orchestrator.handle(
            "thin_governed_loop_preview",
            next_request_payload,
        )

        assert provided_output.ok is True
        assert provided_output.status == "succeeded"
        assert provided_output.result["input_mode"] == "provided"
        assert provided_output.result["thin_loop"]["thin_loop_status"] == THIN_LOOP_PASSED
        assert provided_output.result["thin_loop"]["requested_commander_action"] == "ask_whether_to_prepare_plan_adjustment_draft"
        assert provided_output.result["thin_loop"]["delivery_state_accepted"] is False

    def test_thin_loop_workflow_draft_ignores_pass_alias_without_policy(self) -> None:
        project_root = str(Path(__file__).resolve().parents[1])
        orchestrator = WorkflowOrchestrator(project_root)

        draft_output = orchestrator.handle(
            "thin_governed_loop_preview",
            {"phase": "preview", "input_mode": "draft", "draft_seed": {"review_decision_value": "PASS"}},
        )

        assert draft_output.ok is True
        bundle = draft_output.result["generated_input_bundle"]
        assert "review_decision_value" not in bundle["draft_seed_applied"]
        assert bundle["draft_seed_ignored"] == ["review_decision_value"]
        assert bundle["draft_seed_unknown"] == []
        assert bundle["review_feedback"]["review_decision_value"] == "NEEDS_FIX"

        provided_output = orchestrator.handle(
            "thin_governed_loop_preview",
            {"phase": "preview", "thin_loop_inputs": bundle},
        )

        assert provided_output.ok is True
        assert provided_output.result["thin_loop"]["thin_loop_status"] == THIN_LOOP_PASSED

    def test_thin_loop_workflow_fails_closed_when_provided_inputs_are_incomplete(self) -> None:
        project_root = str(Path(__file__).resolve().parents[1])
        inputs = example_stage_3_6_inputs()
        output = WorkflowOrchestrator(project_root).handle(
            "thin_governed_loop_preview",
            {
                "phase": "preview",
                "input_mode": "provided",
                "external_taskbook_claim": inputs["external_taskbook_claim"],
            },
        )

        assert output.ok is False
        assert output.status == "blocked"
        assert output.result["input_mode"] == "provided"
        assert output.result["thin_loop"]["thin_loop_status"] == THIN_LOOP_FAILED_CLOSED
        assert "缺少真实输入对象：execution_envelope" in output.blockers
        assert output.result["input_contract"]["minimal_request_shape"]["workflow"] == "thin_governed_loop_preview"
        assert output.result["forbidden_authority_outputs"]["delivery_state_accepted"] is False

    def test_thin_loop_workflow_rejects_unknown_input_mode_with_contract(self) -> None:
        project_root = str(Path(__file__).resolve().parents[1])
        output = WorkflowOrchestrator(project_root).handle(
            "thin_governed_loop_preview",
            {"phase": "preview", "input_mode": "surprise"},
        )

        assert output.ok is False
        assert output.status == "blocked"
        assert output.result["input_mode"] == "surprise"
        assert output.result["thin_loop"]["blockers"][0]["code"] == "thin_loop_invalid_input_mode"
        assert "input_mode 必须是 example、template、draft 或 provided。" in output.blockers
        assert "template" in output.result["input_contract"]["accepted_input_modes"]


if __name__ == "__main__":
    unittest.main()
