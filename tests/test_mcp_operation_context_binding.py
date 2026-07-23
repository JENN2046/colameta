from __future__ import annotations

import copy
from pathlib import Path
import subprocess

from runner.mcp_server import MCPPlanningBridgeServer
from runner.project_context_binding import OPERATION_CONTEXT_BINDING_FIELDS


def _make_git_checkout(tmp_path: Path) -> Path:
    project = tmp_path / "mcp-binding-project"
    project.mkdir()
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    subprocess.run(
        ["git", "-C", str(project), "config", "user.email", "mcp-binding@example.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(project), "config", "user.name", "MCP Binding Fixture"],
        check=True,
    )
    (project / "README.md").write_text("old\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(project), "add", "."], check=True)
    subprocess.run(["git", "-C", str(project), "commit", "-qm", "fixture"], check=True)
    return project


def _data(result: dict) -> dict:
    assert result["ok"] is True
    value = result.get("data")
    assert isinstance(value, dict)
    return value


def test_commander_context_contract_is_copyable_and_required_before_patch_apply(tmp_path: Path) -> None:
    project = _make_git_checkout(tmp_path)
    server = MCPPlanningBridgeServer(str(project), exposure_profile="commander")

    preview = _data(
        server.call_tool_for_agent(
            "run_mcp_workflow",
            {
                "workflow": "small_project_patch",
                "phase": "preview",
                "file": "README.md",
                "old_text": "old\n",
                "new_text": "new\n",
            },
        )
    )
    binding = preview["context_binding"]
    assert tuple(binding) == OPERATION_CONTEXT_BINDING_FIELDS
    assert binding["workflow_intent"] == "workflow:small_project_patch"
    assert binding["review_unit"] == "operation:workflow:small_project_patch"
    assert preview["context_binding_contract"]["confirmation_required"] is True
    assert preview["context_binding_contract"]["current_call_requires_context_binding"] is False

    preview_id = preview["preview_ids"][0]
    apply_action = next(
        action
        for action in preview["next_actions"]
        if action.get("tool") == "run_mcp_workflow"
        and action.get("params", {}).get("phase") == "apply"
    )
    assert apply_action["params"]["context_binding"] == binding

    tampered = copy.deepcopy(binding)
    tampered["head"] = "0" * 40
    blocked = server.call_tool_for_agent(
        "run_mcp_workflow",
        {
            "workflow": "small_project_patch",
            "phase": "apply",
            "preview_id": preview_id,
            "context_binding": tampered,
        },
    )
    assert blocked["ok"] is False
    assert blocked["error_code"] == "CONTEXT_BINDING_MISMATCH"
    assert (project / "README.md").read_text(encoding="utf-8") == "old\n"

    applied = _data(server.call_tool_for_agent("run_mcp_workflow", apply_action["params"]))
    assert applied["context_binding_verification"]["status"] == "matched"
    assert applied["context_binding_contract"]["current_call_requires_context_binding"] is True
    assert (project / "README.md").read_text(encoding="utf-8") == "new\n"


def test_context_gate_precedes_validation_run_and_commander_keeps_canonical_freshness(tmp_path: Path) -> None:
    project = _make_git_checkout(tmp_path)
    server = MCPPlanningBridgeServer(str(project), exposure_profile="commander")

    inspect = _data(server.call_tool_for_agent("manage_validation_run", {"action": "inspect"}))
    binding = inspect["context_binding"]
    assert binding["workflow_intent"] == "validation_run"

    missing_binding = server.call_tool_for_agent(
        "manage_validation_run",
        {"action": "run", "preview_id": "missing-id"},
    )
    assert missing_binding["ok"] is False
    assert missing_binding["error_code"] == "CONTEXT_BINDING_MISMATCH"

    with_binding = _data(
        server.call_tool_for_agent(
            "manage_validation_run",
            {
                "action": "run",
                "preview_id": "missing-id",
                "context_binding": binding,
            },
        )
    )
    assert with_binding["error_code"] == "PREVIEW_NOT_FOUND"

    analyzed = _data(server.call_tool_for_agent("analyze_project_state", {}))
    canonical = analyzed["canonical_state"]
    assert canonical["context_binding"]["head"]
    assert canonical["observed_at"]
    assert canonical["currently_observed"]["runtime"]["status"] == "not_observed"
    assert canonical["authority_boundary"]["not_observed_is_not_unavailable"] is True


def test_git_workflow_and_manage_git_share_one_confirmation_identity(tmp_path: Path) -> None:
    project = _make_git_checkout(tmp_path)
    server = MCPPlanningBridgeServer(str(project), exposure_profile="commander")

    assert server._operation_context_identity(
        "run_mcp_workflow", {"workflow": "git_commit", "phase": "preview"}
    ) == ("git_commit", "operation:git_commit")
    assert server._operation_context_identity(
        "manage_git", {"action": "commit_apply"}
    ) == ("git_commit", "operation:git_commit")

    (project / "README.md").write_text("changed\n", encoding="utf-8")
    preview = _data(
        server.call_tool_for_agent(
            "run_mcp_workflow",
            {
                "workflow": "git_commit",
                "phase": "preview",
                "message": "test: change readme",
            },
        )
    )
    apply_action = preview["next_actions"][0]
    assert apply_action["tool"] == "manage_git"
    assert apply_action["params"]["action"] == "commit_apply"
    assert apply_action["params"]["context_binding"] == preview["context_binding"]
    canonical_summary = preview["unified_status"]["canonical_project_state"]
    assert canonical_summary["current_conclusion"]["status"] == "action_required"
    assert preview["unified_status"]["status_scope"] == "operation_local"

    direct_readiness = _data(
        server.call_tool_for_agent("manage_git", {"action": "commit_readiness"})
    )
    direct_status = direct_readiness["unified_status"]
    assert direct_status["status_scope"] == "operation_local"
    assert direct_status["canonical_project_state"]["current_conclusion"]["status"] == (
        "action_required"
    )

    by_name = {definition.name: definition for definition in server.tool_defs}
    for name in ("run_mcp_workflow", "manage_validation_run", "manage_git"):
        contract = by_name[name].input_schema["properties"]["context_binding"]
        assert tuple(contract["required"]) == OPERATION_CONTEXT_BINDING_FIELDS
        assert contract["additionalProperties"] is False


def test_context_gate_covers_every_commander_side_effect_boundary(tmp_path: Path) -> None:
    """Keep the public Commander confirmation matrix explicit and complete."""

    server = MCPPlanningBridgeServer(str(tmp_path / "project"), exposure_profile="commander")

    workflow_boundaries = {
        "plan_update": {"apply"},
        "small_project_patch": {"apply"},
        "docs_update": {"apply"},
        "git_commit": {"commit"},
        "git_restore_file": {"apply"},
        "git_revert": {"apply"},
        "git_undo_version": {"apply"},
        "agent_dispatch": {"apply", "run"},
        "prompt_to_plan": {"apply", "apply_all", "plan_apply", "run"},
        "current_facts": {"apply"},
        "operator_batch": {"execute"},
    }
    for workflow, phases in workflow_boundaries.items():
        for phase in phases:
            params = {"workflow": workflow, "phase": phase}
            assert server._operation_context_required("run_mcp_workflow", params) is True
            assert server._operation_context_identity("run_mcp_workflow", params) is not None

    for action in {
        "commit_apply",
        "push_apply",
        "pull_apply",
        "restore_file_apply",
        "revert_apply",
    }:
        assert server._operation_context_required("manage_git", {"action": action}) is True
    assert server._operation_context_required(
        "manage_validation_run", {"action": "run"}
    ) is True

    # These have stricter, dedicated immutable contracts.  Unsupported phase
    # names also retain their own precise error instead of being masked.
    assert server._operation_context_required(
        "run_mcp_workflow", {"workflow": "review_manifest", "phase": "read"}
    ) is False
    assert server._operation_context_required(
        "run_mcp_workflow", {"workflow": "result_artifact", "phase": "read"}
    ) is False
    assert server._operation_context_required(
        "run_mcp_workflow", {"workflow": "gate_review_request", "phase": "apply"}
    ) is False
    assert server._operation_context_required(
        "run_mcp_workflow", {"workflow": "git_commit", "phase": "apply"}
    ) is False
