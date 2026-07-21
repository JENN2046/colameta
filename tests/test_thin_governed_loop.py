from __future__ import annotations

import copy
import unittest
from pathlib import Path
from unittest.mock import patch

from runner.continuation_snapshot import snapshot_from_fact_bundle
from runner.core_orchestrator import WorkflowOrchestrator
from runner.master_taskbook_registry import MasterTaskbookRegistryError
from runner.thin_governed_loop import (
    BASELINE_ANCHOR_READY,
    MASTER_ANCHOR_VERIFIED,
    STAGE_ANCHOR_VERIFIED,
    THIN_LOOP_FAILED_CLOSED,
    THIN_LOOP_PASSED,
    build_draft_evidence_provenance,
    example_stage_3_6_inputs,
    run_stage_0_6_thin_governed_loop,
    run_stage_3_6_thin_governed_loop,
    verify_stage_0_2_governance_anchors,
)


class ThinGovernedLoopTests(unittest.TestCase):
    def test_stage_0_2_anchors_verify_repository_master_and_stage_bindings(self) -> None:
        project_root = Path(__file__).resolve().parents[1]

        result = verify_stage_0_2_governance_anchors(project_root)

        assert result["anchor_status"] == THIN_LOOP_PASSED
        assert result["blockers"] == []
        assert result["read_only"] is True
        assert result["side_effects"] is False
        assert result["stage_results"]["stage_00_baseline"]["baseline_anchor"] == BASELINE_ANCHOR_READY
        assert result["stage_results"]["stage_01_master_anchor"]["master_registry"] == MASTER_ANCHOR_VERIFIED
        assert result["stage_results"]["stage_02_stage_taskbook"]["stage_registry"] == STAGE_ANCHOR_VERIFIED
        assert result["stage_results"]["stage_02_stage_taskbook"]["registered_stage_ids"] == [
            "stage_02_stage_taskbook_management"
        ]

    def test_stage_0_6_thin_loop_connects_hash_bound_anchors_to_review_intake(self) -> None:
        result = run_stage_0_6_thin_governed_loop(example_stage_3_6_inputs())

        assert result["thin_loop_status"] == THIN_LOOP_PASSED
        assert result["blockers"] == []
        assert result["thin_loop_path"] == [
            "repository_runtime_baseline",
            "master_taskbook_anchor",
            "stage_taskbook_registry",
            "external_taskbook_import",
            "execution_envelope",
            "local_execution_receipt",
            "reviewer_handoff_package",
            "review_feedback_intake",
        ]
        assert result["stage_results"]["stage_01_master_anchor"]["master_registry"] == MASTER_ANCHOR_VERIFIED
        assert result["stage_results"]["stage_06_feedback_intake"]["feedback_classification"] == (
            "review_feedback_classification_ready"
        )
        assert result["governance_anchors"]["read_only"] is True
        assert result["governance_anchors"]["side_effects"] is False
        assert result["delivery_state_accepted"] is False
        assert result["review_decision_created"] is False
        assert result["gate_event_emitted"] is False
        assert result["executor_dispatch_authorized"] is False

    def test_stage_0_6_thin_loop_fails_closed_on_master_anchor_error(self) -> None:
        error = MasterTaskbookRegistryError("MASTER_HASH_MISMATCH", "redacted")
        with patch("runner.thin_governed_loop.load_master_taskbook_registry", side_effect=error):
            result = run_stage_0_6_thin_governed_loop(example_stage_3_6_inputs())

        assert result["thin_loop_status"] == THIN_LOOP_FAILED_CLOSED
        assert any(item["code"] == "stage_01_master_anchor_invalid" for item in result["blockers"])
        assert result["stage_results"]["stage_01_master_anchor"]["master_registry"] == "blocked"
        assert result["delivery_state_accepted"] is False
        assert result["review_decision_created"] is False
        assert result["gate_event_emitted"] is False

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
        assert output.result["thin_loop"]["stage_results"]["stage_00_baseline"]["baseline_anchor"] == (
            BASELINE_ANCHOR_READY
        )
        assert output.result["thin_loop"]["stage_results"]["stage_01_master_anchor"]["master_registry"] == (
            MASTER_ANCHOR_VERIFIED
        )
        assert output.result["thin_loop"]["stage_results"]["stage_02_stage_taskbook"]["stage_registry"] == (
            STAGE_ANCHOR_VERIFIED
        )
        assert output.result["forbidden_authority_outputs"] == {
            "delivery_state_accepted": False,
            "review_decision_created": False,
            "gate_event_emitted": False,
            "executor_dispatch_authorized": False,
        }

    def test_legacy_provided_inputs_are_parseable_but_unclassified_and_ineligible(self) -> None:
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
        provenance = output.result["thin_loop"]["evidence_provenance"]
        assert provenance["provenance_status"] == "legacy_unclassified"
        assert provenance["legacy_read_parse_only"] is True
        assert provenance["eligible_for_acceptance"] is False
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

    def test_prov_01_draft_packet_can_be_ready_while_receipt_remains_not_run(self) -> None:
        project_root = str(Path(__file__).resolve().parents[1])
        orchestrator = WorkflowOrchestrator(project_root)
        draft_seed = {
            "source_id": "seeded-thin-loop-taskbook",
            "goal": "Make the command path feel natural for a Commander.",
            "task_tier": "M1",
            "allowed_files": ["runner/seeded_feature.py", "tests/test_seeded_feature.py"],
            "forbidden_files": ["PROJECT_MASTER_TASKBOOK.md", ".colameta/plan.json", "**/.env"],
            "context_files": ["README.md"],
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
        assert draft_output.result["generated_input_bundle_summary"]["direct_execution_packet_field"] == "codex_execution_packet"
        assert draft_output.result["generated_input_bundle_summary"]["provided_preview_is_optional_for_m0_m2"] is True
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
        packet = draft_output.result["codex_execution_packet"]
        assert packet["packet_kind"] == "thin_governed_loop_codex_execution_packet"
        assert packet["packet_status"] == "ready"
        assert packet["direct_execution_ready"] is True
        assert packet["blockers"] == []
        assert packet["task_tier"] == "M1"
        assert packet["objective"] == "Make the command path feel natural for a Commander."
        assert packet["scope"]["allowed_files"] == draft_seed["allowed_files"]
        assert packet["scope"]["context_files"] == ["README.md"]
        assert packet["validation"]["commands"] == draft_seed["validation_commands"]
        assert packet["execution_boundary"]["local_codex_direct_execution_ready"] is True
        assert packet["execution_boundary"]["colameta_executor_dispatch_authorized"] is False
        assert packet["execution_boundary"]["commit_or_push_authorized"] is False
        assert packet["closeout_summary_template"]["forbidden_claims"]["delivery_accepted"] is False
        assert "Make the command path feel natural for a Commander." in packet["copy_paste_codex_prompt"]
        assert "python -m unittest tests.test_seeded_feature" in draft_output.result["copy_paste_codex_prompt"]
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
        assert bundle["external_taskbook_claim"]["provenance"]["provenance_note"] == (
            "Draft goal: Make the command path feel natural for a Commander."
        )
        assert "Draft goal: Make the command path feel natural for a Commander." in (
            bundle["external_taskbook_claim"]["manual_acceptance"]["acceptance_note"]
        )
        assert bundle["external_taskbook_claim"]["allowed_files"] == draft_seed["allowed_files"]
        assert bundle["execution_envelope"]["allowed_files"] == draft_seed["allowed_files"]
        assert bundle["execution_envelope"]["validation_commands"] == draft_seed["validation_commands"]
        receipt = bundle["local_execution_receipt"]
        assert receipt["execution_result"] == "blocked_before_execution"
        assert receipt["command_attempts"] == []
        assert receipt["touched_files"] == []
        assert receipt["observed_mutations"] == []
        assert bundle["local_execution_receipt"]["validation_commands"] == draft_seed["validation_commands"]
        assert receipt["validation_results"] == []
        assert receipt["validation_summary"] == "not_run"
        assert receipt["scope_check_result"] == "not_run"
        assert bundle["review_feedback"]["review_decision_value"] == "PLAN_ADJUST"
        assert bundle["review_feedback"]["reviewer_notes"] == draft_seed["reviewer_notes"]
        provenance = bundle["evidence_provenance"]
        assert provenance["schema_version"] == "evidence_provenance.v1"
        by_path = {entry["subject_path"]: entry for entry in provenance["entries"]}
        assert by_path["local_execution_receipt"]["evidence_kind"] == "draft"
        assert by_path["local_execution_receipt"]["claimed_execution_performed"] is False
        assert by_path["local_execution_receipt"]["claimed_eligible_for_acceptance"] is False
        assert by_path["local_execution_receipt.validation_results"]["evidence_kind"] == "draft"
        assert by_path["review_feedback"]["evidence_kind"] == "placeholder"
        assert by_path["review_feedback.master_taskbook_hash"]["evidence_kind"] == "placeholder"
        assert by_path["review_feedback.stage_taskbook_hash"]["evidence_kind"] == "placeholder"
        assert all(entry["claimed_eligible_for_acceptance"] is False for entry in provenance["entries"])
        assert draft_output.result["thin_loop"]["evidence_provenance"] == {
            "schema_version": "evidence_provenance.v1",
            "provenance_status": "draft_non_acceptable",
            "eligible_for_acceptance": False,
        }
        assert "draft" in draft_output.result["input_contract"]["accepted_input_modes"]
        assert "draft_seed" in draft_output.result["input_contract"]["transport"]["bundle_allowed_fields"]

        provided_output = orchestrator.handle(
            "thin_governed_loop_preview",
            next_request_payload,
        )

        assert provided_output.ok is False
        assert provided_output.status == "blocked"
        assert provided_output.result["input_mode"] == "provided"
        assert provided_output.result["thin_loop"]["thin_loop_status"] == THIN_LOOP_FAILED_CLOSED
        assert provided_output.result["thin_loop"]["evidence_provenance"]["eligible_for_acceptance"] is False
        assert any(
            item["code"] == "thin_loop_evidence_provenance_ineligible"
            for item in provided_output.result["thin_loop"]["blockers"]
        )
        assert provided_output.result["thin_loop"]["requested_commander_action"] == "ask_whether_to_prepare_plan_adjustment_draft"
        assert provided_output.result["thin_loop"]["delivery_state_accepted"] is False

    def test_prov_03_simulated_or_placeholder_evidence_fails_closed_without_becoming_observed(self) -> None:
        for evidence_kind in ("simulated", "placeholder"):
            with self.subTest(evidence_kind=evidence_kind):
                inputs = example_stage_3_6_inputs()
                provenance = build_draft_evidence_provenance(inputs)
                for entry in provenance["entries"]:
                    entry["evidence_kind"] = evidence_kind
                inputs["evidence_provenance"] = provenance

                result = run_stage_3_6_thin_governed_loop(inputs)

                assert result["thin_loop_status"] == THIN_LOOP_FAILED_CLOSED
                assert result["evidence_provenance"]["eligible_for_acceptance"] is False
                assert all(
                    entry["evidence_kind"] != "observed"
                    for entry in result["evidence_provenance"]["entries"]
                )
                assert any(
                    item["code"] == "thin_loop_evidence_provenance_ineligible"
                    for item in result["blockers"]
                )

    def test_acceptance_aware_provenance_fails_closed_when_required_subject_is_omitted(self) -> None:
        inputs = example_stage_3_6_inputs()
        provenance = build_draft_evidence_provenance(inputs)
        for entry in provenance["entries"]:
            requires_execution = entry["subject_path"] in {
                "local_execution_receipt",
                "local_execution_receipt.validation_results",
            }
            entry["evidence_kind"] = "observed"
            entry["claimed_subject_operation_completed"] = True
            entry["claimed_execution_performed"] = requires_execution
            entry["claimed_eligible_for_acceptance"] = True
        omitted_path = "review_feedback.stage_taskbook_hash"
        provenance["entries"] = [
            entry for entry in provenance["entries"] if entry["subject_path"] != omitted_path
        ]
        inputs["evidence_provenance"] = provenance

        result = run_stage_3_6_thin_governed_loop(inputs)

        assert result["thin_loop_status"] == THIN_LOOP_FAILED_CLOSED
        assert result["evidence_provenance"]["eligible_for_acceptance"] is False
        coverage = next(
            reason
            for reason in result["evidence_provenance_rejection_reasons"]
            if reason["code"] == "EVIDENCE_PROVENANCE_SUBJECT_COVERAGE_INCOMPLETE"
        )
        assert coverage["details"]["missing_subject_paths"] == [omitted_path]
        assert any(
            item["code"] == "thin_loop_evidence_provenance_ineligible"
            for item in result["blockers"]
        )

    def test_observed_not_run_validation_cannot_claim_completed_or_eligible(self) -> None:
        inputs = example_stage_3_6_inputs()
        receipt = inputs["local_execution_receipt"]
        receipt["validation_results"] = [
            {"command": "python -m pytest -q", "result": "not_run"}
        ]
        receipt["validation_summary"] = "not_run"
        provenance = build_draft_evidence_provenance(inputs)
        for entry in provenance["entries"]:
            subject_path = entry["subject_path"]
            requires_execution = subject_path in {
                "local_execution_receipt",
                "local_execution_receipt.validation_results",
            }
            entry["evidence_kind"] = "observed"
            entry["claimed_subject_operation_completed"] = True
            entry["claimed_execution_performed"] = requires_execution
            entry["claimed_eligible_for_acceptance"] = True
        inputs["evidence_provenance"] = provenance

        result = run_stage_3_6_thin_governed_loop(inputs)

        assert result["thin_loop_status"] == THIN_LOOP_FAILED_CLOSED
        entries = {
            entry["subject_path"]: entry
            for entry in result["evidence_provenance"]["entries"]
        }
        validation = entries["local_execution_receipt.validation_results"]
        assert validation["subject_operation_completed"] is False
        assert validation["execution_performed"] is False
        assert validation["eligible_for_acceptance"] is False
        assert "EVIDENCE_PROVENANCE_COMPLETION_MISMATCH" in {
            reason["code"]
            for reason in result["evidence_provenance_rejection_reasons"]
        }

    def test_prov_02_draft_review_and_hash_values_are_placeholder_evidence(self) -> None:
        project_root = str(Path(__file__).resolve().parents[1])
        output = WorkflowOrchestrator(project_root).handle(
            "thin_governed_loop_preview",
            {"phase": "preview", "input_mode": "draft", "draft_seed": {}},
        )

        entries = {
            entry["subject_path"]: entry
            for entry in output.result["generated_input_bundle"]["evidence_provenance"]["entries"]
        }
        placeholder_paths = {
            "review_feedback",
            "review_feedback.master_taskbook_hash",
            "review_feedback.stage_taskbook_hash",
        }
        assert all(entries[path]["evidence_kind"] == "placeholder" for path in placeholder_paths)
        assert all(entries[path]["claimed_eligible_for_acceptance"] is False for path in placeholder_paths)

    def test_thin_loop_draft_packet_preserves_canonical_human_review_decision(self) -> None:
        project_root = str(Path(__file__).resolve().parents[1])
        session_status = {
            "ok": True,
            "matches_current_head": False,
            "current_head": "b" * 40,
            "record": {
                "provider": "codex",
                "conversation_id": "private-conversation",
                "current_head": "a" * 40,
            },
        }
        snapshot = snapshot_from_fact_bundle(
            project_root,
            {
                "executor_session_status": session_status,
                "continuation_preview": {
                    "ok": True,
                    "selected_provider": "codex",
                    "identity_present": True,
                },
                "selected_provider": "codex",
                "requested_provider": "codex",
                "identity_present": True,
                "provider_resume_supported": True,
                "resume_invocation_verified": True,
                "operation_running": True,
                "job_status": "running",
                "latest_run_status": "running",
                "worktree_clean": False,
            },
        )
        draft_output = WorkflowOrchestrator(
            project_root,
            continuation_snapshot=snapshot,
        ).handle(
            "thin_governed_loop_preview",
            {
                "phase": "preview",
                "input_mode": "draft",
                "draft_seed": {
                    "goal": "Update a small docs sentence.",
                    "allowed_files": ["docs/example.md"],
                    "validation_commands": ["git diff --check"],
                },
            },
        )

        assert draft_output.ok is True
        packet = draft_output.result["codex_execution_packet"]
        guidance = packet["executor_session_recovery"]
        assert guidance["status"] == "continuation_human_review_required"
        assert guidance["recommended_action"] == "human_review"
        assert guidance["recommended_session_mode"] == "blocked"
        assert guidance["resume_existing_allowed_by_packet"] is False
        assert guidance["start_new_allowed_by_packet"] is False
        assert guidance["managed_executor_mode_hint"] is None
        assert guidance["canonical_continuation_decision"]["recommended_action"] == "human_review"
        assert guidance["invocation_uses_canonical_decision"] is True
        assert "possibly active head mismatch" in guidance["safe_recovery_steps"][0].lower()
        assert "start a fresh local codex session" not in packet["copy_paste_codex_prompt"].lower()

    def test_thin_loop_draft_packet_blocks_missing_validation_without_example_evidence(self) -> None:
        project_root = str(Path(__file__).resolve().parents[1])
        draft_output = WorkflowOrchestrator(project_root).handle(
            "thin_governed_loop_preview",
            {
                "phase": "preview",
                "input_mode": "draft",
                "draft_seed": {
                    "goal": "Update a small docs sentence.",
                    "allowed_files": ["docs/example.md"],
                },
            },
        )

        assert draft_output.ok is True
        packet = draft_output.result["codex_execution_packet"]
        assert packet["packet_status"] == "blocked"
        assert packet["direct_execution_ready"] is False
        assert packet["validation"]["commands"] == []
        assert packet["validation"]["run_validation_after_changes"] is False
        assert packet["execution_boundary"]["local_codex_direct_execution_ready"] is False
        assert [item["code"] for item in packet["blockers"]] == ["validation_commands_required"]
        assert "tests.test_example" not in packet["copy_paste_codex_prompt"]
        assert "<missing: provide validation_commands>" in packet["copy_paste_codex_prompt"]

        bundle = draft_output.result["generated_input_bundle"]
        assert bundle["execution_envelope"]["validation_commands"] == []
        assert bundle["execution_envelope"]["allowed_commands"] == []
        assert bundle["external_taskbook_claim"]["acceptance_commands"] == []
        assert bundle["local_execution_receipt"]["execution_result"] == "blocked_before_execution"
        assert bundle["local_execution_receipt"]["validation_commands"] == []
        assert bundle["local_execution_receipt"]["validation_results"] == []
        assert bundle["local_execution_receipt"]["command_attempts"] == []

    def test_thin_loop_draft_packet_blocks_invalid_task_tier(self) -> None:
        project_root = str(Path(__file__).resolve().parents[1])
        draft_output = WorkflowOrchestrator(project_root).handle(
            "thin_governed_loop_preview",
            {
                "phase": "preview",
                "input_mode": "draft",
                "draft_seed": {
                    "goal": "Update a small docs sentence.",
                    "task_tier": "M3",
                    "allowed_files": ["docs/example.md"],
                    "validation_commands": ["git diff --check"],
                },
            },
        )

        assert draft_output.ok is True
        bundle = draft_output.result["generated_input_bundle"]
        assert "task_tier" not in bundle["draft_seed_applied"]
        assert bundle["draft_seed_ignored"] == ["task_tier"]
        assert bundle["draft_seed_unknown"] == []

        packet = draft_output.result["codex_execution_packet"]
        assert packet["packet_status"] == "blocked"
        assert packet["direct_execution_ready"] is False
        assert packet["task_tier"] == "M3"
        assert packet["task_tier_status"]["valid"] is False
        assert [item["code"] for item in packet["blockers"]] == ["invalid_task_tier"]
        assert packet["execution_boundary"]["local_codex_direct_execution_ready"] is False
        assert "Task tier: M3" in packet["copy_paste_codex_prompt"]

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
        assert draft_output.result["codex_execution_packet"]["packet_status"] == "blocked"
        assert [item["code"] for item in draft_output.result["codex_execution_packet"]["blockers"]] == [
            "allowed_files_required",
            "validation_commands_required",
        ]

        provided_output = orchestrator.handle(
            "thin_governed_loop_preview",
            {"phase": "preview", "thin_loop_inputs": bundle},
        )

        assert provided_output.ok is False
        assert provided_output.status == "blocked"
        assert provided_output.result["thin_loop"]["thin_loop_status"] == THIN_LOOP_FAILED_CLOSED

    def test_thin_loop_workflow_draft_accepts_objective_alias(self) -> None:
        project_root = str(Path(__file__).resolve().parents[1])
        orchestrator = WorkflowOrchestrator(project_root)

        draft_output = orchestrator.handle(
            "thin_governed_loop_preview",
            {
                "phase": "preview",
                "input_mode": "draft",
                "draft_seed": {"objective": "Use ColaMeta to guide a small local optimization."},
            },
        )

        assert draft_output.ok is True
        bundle = draft_output.result["generated_input_bundle"]
        assert bundle["draft_seed_applied"] == ["objective"]
        assert bundle["draft_seed_ignored"] == []
        assert bundle["draft_seed_unknown"] == []
        assert bundle["review_feedback"]["reviewer_notes"] == (
            "Draft goal: Use ColaMeta to guide a small local optimization."
        )

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
