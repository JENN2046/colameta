from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from runner.mcp_server import MCPPlanningBridgeServer
from runner.mcp_stage_7_9_preview import STAGE_7_9_PREVIEW_WORKFLOW


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MASTER = {
    "path": "PROJECT_MASTER_TASKBOOK.md",
    "sha256": "1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34",
}
STAGE_7 = {
    "path": "docs/taskbooks/stages/STAGE_07_DRIFT_EVIDENCE_AND_CORRECTION.md",
    "sha256": "24cec5e48435254731cce4bb2e72c8810df3d041f57c142d5674d82a632cb142",
}
STAGE_8 = {
    "path": "docs/taskbooks/stages/STAGE_08_PLAN_ADJUSTMENT_CONTROL.md",
    "sha256": "60421ba765b238b9671f1f9baf878cf716c6e6e5cd05524bfa746610fd9a3755",
}
STAGE_9 = {
    "path": "docs/taskbooks/stages/STAGE_09_CONTROLLED_CONTINUE_AND_LONG_RUN_TRACE.md",
    "sha256": "5bfe6e4632748bd33f5a763963bc54b5e546bd3349ad536ec5b693522c7d696d",
}


def _make_stage_project(tmp_path: Path) -> Path:
    project = tmp_path / "stage-7-9-project"
    project.mkdir()
    for reference in (MASTER, STAGE_7, STAGE_8, STAGE_9):
        source = REPOSITORY_ROOT / reference["path"]
        target = project / reference["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    (project / "README.md").write_text("stage 7-9 integration fixture\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    subprocess.run(["git", "-C", str(project), "config", "user.email", "stage@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(project), "config", "user.name", "Stage Fixture"], check=True)
    subprocess.run(["git", "-C", str(project), "add", "."], check=True)
    subprocess.run(["git", "-C", str(project), "commit", "-qm", "fixture"], check=True)
    return project


def _data(result: dict) -> dict:
    assert result["ok"] is True
    payload = result.get("data")
    assert isinstance(payload, dict)
    return payload


def _git_status(project: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(project), "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def _inspect(server: MCPPlanningBridgeServer) -> dict:
    return _data(
        server.call_tool_for_agent(
            "run_mcp_workflow",
            {"workflow": STAGE_7_9_PREVIEW_WORKFLOW, "phase": "inspect"},
        )
    )


def _journey_inputs(context: dict) -> dict:
    drift_pack_id = "stage-7-pack-integration"
    return {
        "stage_7_drift_evidence_inputs": {
            "drift_evidence_pack_id": drift_pack_id,
            "master_taskbook_ref": dict(MASTER),
            "stage_taskbook_ref": {"stage_id": "stage_07_drift_evidence_and_correction", **STAGE_7},
            "version_taskbook_ref": {"version": "v1.13", "name": "Stage 7 fixture"},
            "execution_evidence_ref": {"evidence_id": "execution-evidence-fixture", "status": "completed"},
            "changed_files": ["runner/example.py"],
            "validation_truth": {"status": "passed", "truth_source": "fixture"},
            "scope_evidence": {"scope_result": "in_scope", "scope_pack_id": "scope-fixture"},
            "forbidden_files_evidence": {"forbidden_files_touched": [], "source": "fixture"},
            "out_of_scope_evidence": {"out_of_scope_files": [], "source": "fixture"},
        },
        "stage_8_plan_adjustment_inputs": {
            "commander_decision_request": {
                "commander_decision_request_id": "cdr-stage-8-fixture",
                "request_status": "commander_decision_request_available",
                "source_review_decision_value": "PLAN_ADJUST",
                "normalized_classification": "plan_adjust_review_feedback",
                "requested_commander_action": "ask_whether_to_prepare_plan_adjustment_draft",
            },
            "master_taskbook_ref": dict(MASTER),
            "master_taskbook_hash": MASTER["sha256"],
            "affected_stage_refs": [{"stage_id": "stage_08_plan_adjustment_control", **STAGE_8}],
            "affected_version_refs": [{"version": "v1.14", "name": "Stage 8 fixture"}],
            "drift_evidence_ref": {"drift_evidence_pack_id": drift_pack_id},
            "proposed_change_summary": "Candidate-only Stage 8 wording adjustment for human review.",
            "proposed_diff_or_patch_preview": {
                "candidate_only": True,
                "files": [{"path": STAGE_8["path"], "action": "preview_modify"}],
            },
            "continued_master_goal_service_explanation": "The candidate preserves the preview-only boundary and remains subject to a human decision.",
        },
        "stage_9_continue_readiness_inputs": {
            "plan": {
                "project_name": context["project_name"],
                "plan_version": "stage-9-fixture",
                "versions": [
                    {"version": "v1.1", "name": "Current", "enabled": True},
                    {"version": "v1.2", "name": "Next", "enabled": True},
                ],
            },
            "state": {
                "project_name": context["project_name"],
                "status": "VERSION_PASSED",
                "current_version": "v1.1",
                "current_version_index": 0,
                "versions": [
                    {"version": "v1.1", "name": "Current", "status": "PASSED"},
                    {"version": "v1.2", "name": "Next", "status": "NOT_STARTED"},
                ],
            },
            "review_decision_ref": {
                "review_decision_id": "rd-stage-9-fixture",
                "normalized_review_decision_value": "PLAN_ADJUST",
            },
            "continue_gate_ref": {
                "continue_gate_id": "cg-stage-9-fixture",
                "gate_status": "requested",
                "gate_type": "controlled_continue_gate",
                "separate_from_review_decision": True,
                "target_next_version": "v1.2",
            },
            "taskbook_hash_refs": {
                "master_taskbook_ref": {
                    "path": MASTER["path"],
                    "expected_sha256": MASTER["sha256"],
                    "actual_sha256": MASTER["sha256"],
                },
                "stage_taskbook_ref": {
                    "path": STAGE_9["path"],
                    "expected_sha256": STAGE_9["sha256"],
                    "actual_sha256": STAGE_9["sha256"],
                },
                "version_taskbook_ref": {
                    "version": "v1.2",
                    "expected_sha256": "c" * 64,
                    "actual_sha256": "c" * 64,
                },
            },
            "git_facts": {
                "current_head": context["head"],
                "expected_head": context["head"],
                "current_branch": context["branch"],
                "git_status_short": "",
            },
            "blocking_review_comments": [],
        },
    }


def _preview(server: MCPPlanningBridgeServer, inspect: dict, inputs: dict) -> dict:
    return server.call_tool_for_agent(
        "run_mcp_workflow",
        {
            "workflow": STAGE_7_9_PREVIEW_WORKFLOW,
            "phase": "preview",
            "stage_7_9_context": inspect["stage_7_9_context"],
            "stage_7_9_inputs": inputs,
        },
    )


def test_stage_7_9_inspect_returns_a_hash_bound_read_only_template(tmp_path: Path) -> None:
    project = _make_stage_project(tmp_path)
    server = MCPPlanningBridgeServer(str(project), exposure_profile="commander")

    inspect = _inspect(server)

    assert inspect["workflow"] == STAGE_7_9_PREVIEW_WORKFLOW
    assert inspect["read_only"] is True
    assert inspect["side_effects"] is False
    assert inspect["stage_7_9_context"]["workflow_intent"] == STAGE_7_9_PREVIEW_WORKFLOW
    assert inspect["stage_7_9_context"]["review_unit"] == "stage_07_to_stage_09_preview"
    assert inspect["stage_7_9_context"]["runner_plan"] == {
        "mode": "source-only",
        "plan_sha256": None,
    }
    assert inspect["stage_7_9_context"]["current_version"] is None
    assert [item["path"] for item in inspect["frozen_taskbook_bindings"]] == [
        MASTER["path"],
        STAGE_7["path"],
        STAGE_8["path"],
        STAGE_9["path"],
    ]
    assert inspect["input_contract"]["required_scope"] == "mcp:read"
    assert _git_status(project) == ""


def test_stage_7_9_preview_connects_valid_plan_adjust_handoff_without_side_effects(tmp_path: Path) -> None:
    project = _make_stage_project(tmp_path)
    server = MCPPlanningBridgeServer(str(project), exposure_profile="commander")
    inspect = _inspect(server)
    inputs = _journey_inputs(inspect["stage_7_9_context"])
    inputs["stage_9_continue_readiness_inputs"]["private_runtime_marker"] = "must-not-appear-in-public-result"

    preview = _data(_preview(server, inspect, inputs))

    assert preview["journey_status"] == "human_decision_required"
    assert preview["read_only"] is True
    assert preview["side_effects"] is False
    assert preview["stage_results"]["stage_7"]["status"] == "drift_evidence_pack_generated"
    assert preview["stage_results"]["stage_8"]["status"] == "plan_adjustment_preview_available"
    assert preview["stage_results"]["stage_9"]["can_continue"] is False
    assert "PLAN_ADJUST_BLOCKS_CONTINUE" in preview["stage_results"]["stage_9"]["blocker_codes"]
    assert preview["next_human_decision"]["action"] == "review_stage_8_plan_adjustment_preview"
    assert preview["authority_boundary"]["read_only"] is True
    assert preview["authority_boundary"]["side_effects"] is False
    assert all(
        value is True
        for key, value in preview["authority_boundary"].items()
        if key not in {"side_effects"}
    )
    assert "must-not-appear-in-public-result" not in json.dumps(preview, ensure_ascii=False)
    assert _git_status(project) == ""


def test_stage_7_9_preview_requires_inspect_context(tmp_path: Path) -> None:
    project = _make_stage_project(tmp_path)
    server = MCPPlanningBridgeServer(str(project), exposure_profile="commander")
    inspect = _inspect(server)

    result = server.call_tool_for_agent(
        "run_mcp_workflow",
        {
            "workflow": STAGE_7_9_PREVIEW_WORKFLOW,
            "phase": "preview",
            "stage_7_9_inputs": _journey_inputs(inspect["stage_7_9_context"]),
        },
    )

    assert result["ok"] is False
    assert result["error_code"] == "STAGE_7_9_CONTEXT_REQUIRED"


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("branch", "different-branch"),
        ("head", "0" * 40),
        ("runner_plan", {"mode": "managed", "plan_sha256": "0" * 64}),
        ("current_version", "v9.9"),
    ],
)
def test_stage_7_9_preview_rejects_changed_context(
    tmp_path: Path,
    field: str,
    replacement: object,
) -> None:
    project = _make_stage_project(tmp_path)
    server = MCPPlanningBridgeServer(str(project), exposure_profile="commander")
    inspect = _inspect(server)
    changed_context = copy.deepcopy(inspect["stage_7_9_context"])
    changed_context[field] = replacement

    result = server.call_tool_for_agent(
        "run_mcp_workflow",
        {
            "workflow": STAGE_7_9_PREVIEW_WORKFLOW,
            "phase": "preview",
            "stage_7_9_context": changed_context,
            "stage_7_9_inputs": _journey_inputs(inspect["stage_7_9_context"]),
        },
    )

    assert result["ok"] is False
    assert result["error_code"] == "STAGE_7_9_CONTEXT_MISMATCH"


def test_stage_7_9_inspect_rejects_changed_frozen_taskbook_bytes(tmp_path: Path) -> None:
    project = _make_stage_project(tmp_path)
    taskbook = project / STAGE_8["path"]
    taskbook.write_text("changed taskbook bytes\n", encoding="utf-8")
    server = MCPPlanningBridgeServer(str(project), exposure_profile="commander")

    result = server.call_tool_for_agent(
        "run_mcp_workflow",
        {"workflow": STAGE_7_9_PREVIEW_WORKFLOW, "phase": "inspect"},
    )

    assert result["ok"] is False
    assert result["error_code"] == "STAGE_7_9_TASKBOOK_BINDING_MISMATCH"


def test_stage_7_9_preview_rejects_wrong_taskbook_binding(tmp_path: Path) -> None:
    project = _make_stage_project(tmp_path)
    server = MCPPlanningBridgeServer(str(project), exposure_profile="commander")
    inspect = _inspect(server)
    inputs = _journey_inputs(inspect["stage_7_9_context"])
    inputs["stage_7_drift_evidence_inputs"]["master_taskbook_ref"]["sha256"] = "0" * 64

    result = _preview(server, inspect, inputs)

    assert result["ok"] is False
    assert result["error_code"] == "STAGE_7_9_TASKBOOK_BINDING_MISMATCH"


def test_stage_7_9_preview_rejects_missing_stage_input(tmp_path: Path) -> None:
    project = _make_stage_project(tmp_path)
    server = MCPPlanningBridgeServer(str(project), exposure_profile="commander")
    inspect = _inspect(server)
    inputs = _journey_inputs(inspect["stage_7_9_context"])
    inputs.pop("stage_9_continue_readiness_inputs")

    result = _preview(server, inspect, inputs)

    assert result["ok"] is False
    assert result["error_code"] == "STAGE_7_9_INPUTS_REQUIRED"


def test_stage_7_9_preview_stops_on_invalid_stage_7_evidence(tmp_path: Path) -> None:
    project = _make_stage_project(tmp_path)
    server = MCPPlanningBridgeServer(str(project), exposure_profile="commander")
    inspect = _inspect(server)
    inputs = _journey_inputs(inspect["stage_7_9_context"])
    inputs["stage_7_drift_evidence_inputs"]["changed_files"] = []

    result = _preview(server, inspect, inputs)

    assert result["ok"] is False
    assert result["error_code"] == "STAGE_7_9_STAGE_7_FAILED_CLOSED"


def test_stage_7_9_preview_stops_on_non_plan_adjust_stage_8_source(tmp_path: Path) -> None:
    project = _make_stage_project(tmp_path)
    server = MCPPlanningBridgeServer(str(project), exposure_profile="commander")
    inspect = _inspect(server)
    inputs = _journey_inputs(inspect["stage_7_9_context"])
    inputs["stage_8_plan_adjustment_inputs"]["commander_decision_request"]["source_review_decision_value"] = "ACCEPT"

    result = _preview(server, inspect, inputs)

    assert result["ok"] is False
    assert result["error_code"] == "STAGE_7_9_STAGE_8_FAILED_CLOSED"


def test_stage_7_9_preview_requires_stage_8_to_reference_generated_drift_pack(tmp_path: Path) -> None:
    project = _make_stage_project(tmp_path)
    server = MCPPlanningBridgeServer(str(project), exposure_profile="commander")
    inspect = _inspect(server)
    inputs = _journey_inputs(inspect["stage_7_9_context"])
    inputs["stage_8_plan_adjustment_inputs"]["drift_evidence_ref"]["drift_evidence_pack_id"] = "wrong-pack"

    result = _preview(server, inspect, inputs)

    assert result["ok"] is False
    assert result["error_code"] == "STAGE_7_9_DRIFT_PACK_BINDING_MISMATCH"


def test_stage_7_9_preview_stops_when_stage_9_readiness_inputs_are_incomplete(tmp_path: Path) -> None:
    project = _make_stage_project(tmp_path)
    server = MCPPlanningBridgeServer(str(project), exposure_profile="commander")
    inspect = _inspect(server)
    inputs = _journey_inputs(inspect["stage_7_9_context"])
    inputs["stage_9_continue_readiness_inputs"].pop("plan")

    result = _preview(server, inspect, inputs)

    assert result["ok"] is False
    assert result["error_code"] == "STAGE_7_9_STAGE_9_FAILED_CLOSED"


def test_stage_7_9_preview_rejects_every_side_effect_phase(tmp_path: Path) -> None:
    project = _make_stage_project(tmp_path)
    server = MCPPlanningBridgeServer(str(project), exposure_profile="commander")

    for phase in ("apply", "apply_all", "plan_apply", "run", "commit", "execute"):
        result = server.call_tool_for_agent(
            "run_mcp_workflow",
            {"workflow": STAGE_7_9_PREVIEW_WORKFLOW, "phase": phase},
        )
        assert result["ok"] is False
        assert result["error_code"] == "STAGE_7_9_PHASE_NOT_SUPPORTED"
