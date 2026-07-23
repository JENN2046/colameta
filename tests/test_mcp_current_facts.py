from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import subprocess

from runner.current_facts_artifact import CURRENT_FACTS_ARCHIVE_ROOT
from runner.mcp_result_artifacts import MCPResultArtifactStore
from runner.mcp_server import MCPPlanningBridgeServer


def _make_git_checkout(tmp_path: Path) -> Path:
    project = tmp_path / "current-facts-mcp-project"
    project.mkdir()
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    subprocess.run(
        ["git", "-C", str(project), "config", "user.email", "current-facts@example.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(project), "config", "user.name", "Current Facts Fixture"],
        check=True,
    )
    (project / ".gitignore").write_text(".colameta/reports/**\n", encoding="utf-8")
    (project / "README.md").write_text("current facts fixture\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(project), "add", "."], check=True)
    subprocess.run(["git", "-C", str(project), "commit", "-qm", "fixture"], check=True)
    return project


def _data(result: dict) -> dict:
    assert result["ok"] is True
    data = result.get("data")
    assert isinstance(data, dict)
    return data


def _git_status(project: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(project), "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def test_current_facts_inspect_uses_a_recoverable_typed_result_artifact(tmp_path: Path) -> None:
    project = _make_git_checkout(tmp_path)
    server = MCPPlanningBridgeServer(str(project), exposure_profile="commander")
    server._mcp_result_artifact_store = MCPResultArtifactStore(page_chars=300)

    inspect = _data(
        server.call_tool_for_agent(
            "run_mcp_workflow",
            {"workflow": "current_facts", "phase": "inspect"},
        )
    )

    assert inspect["workflow"] == "current_facts"
    assert inspect["phase"] == "inspect"
    assert inspect["read_only"] is True
    assert inspect["side_effects"] is False
    assert inspect["current_facts"]["authority"] == "observation_only"
    assert inspect["artifact_id"] == inspect["result_artifact"]["artifact_id"]
    assert inspect["page_count"] > 1
    assert inspect["expires_at"] == inspect["result_artifact"]["expires_at"]
    assert inspect["recommended_next_reads"][0]["tool"] == "read_result_artifact"
    assert not (project / CURRENT_FACTS_ARCHIVE_ROOT).exists()

    pages: list[str] = []
    for page in range(1, inspect["page_count"] + 1):
        read = _data(
            server.call_tool_for_agent(
                "read_result_artifact",
                {"artifact_id": inspect["artifact_id"], "artifact_page": page},
            )
        )
        assert read["read_only"] is True
        assert read["side_effects"] is False
        assert read["content_sha256"] == inspect["content_sha256"]
        assert read["expires_at"] == inspect["expires_at"]
        pages.append(read["artifact_page"]["content"])

    restored = "".join(pages)
    assert hashlib.sha256(restored.encode("utf-8")).hexdigest() == inspect["content_sha256"]
    payload = json.loads(restored)
    assert payload["data"]["workflow"] == "current_facts"
    assert payload["data"]["current_facts"]["authority_boundary"]["snapshot_is_observation_only"] is True


def test_current_facts_preview_is_observational_until_its_explicit_apply(tmp_path: Path) -> None:
    project = _make_git_checkout(tmp_path)
    server = MCPPlanningBridgeServer(str(project), exposure_profile="commander")

    assert _git_status(project) == ""
    preview = _data(
        server.call_tool_for_agent(
            "run_mcp_workflow",
            {"workflow": "current_facts", "phase": "preview"},
        )
    )

    assert preview["read_only"] is True
    assert preview["side_effects"] is False
    assert _git_status(project) == ""
    assert not (project / CURRENT_FACTS_ARCHIVE_ROOT).exists()


def test_current_facts_archive_apply_requires_context_and_writes_only_after_preview(tmp_path: Path) -> None:
    project = _make_git_checkout(tmp_path)
    server = MCPPlanningBridgeServer(str(project), exposure_profile="commander")

    preview = _data(
        server.call_tool_for_agent(
            "run_mcp_workflow",
            {"workflow": "current_facts", "phase": "preview"},
        )
    )
    assert preview["requires_confirmation"] is True
    assert preview["context_binding"]["workflow_intent"] == "workflow:current_facts"
    assert not (project / CURRENT_FACTS_ARCHIVE_ROOT).exists()

    missing_binding = server.call_tool_for_agent(
        "run_mcp_workflow",
        {
            "workflow": "current_facts",
            "phase": "apply",
            "preview_id": preview["preview_id"],
        },
    )
    assert missing_binding["ok"] is False
    assert missing_binding["error_code"] == "CONTEXT_BINDING_MISMATCH"
    assert not (project / CURRENT_FACTS_ARCHIVE_ROOT).exists()

    apply_action = next(
        action
        for action in preview["next_actions"]
        if action.get("tool") == "run_mcp_workflow"
        and action.get("params", {}).get("phase") == "apply"
    )
    applied = _data(server.call_tool_for_agent("run_mcp_workflow", apply_action["params"]))
    assert applied["context_binding_verification"]["status"] == "matched"
    assert applied["side_effects"] is True
    assert applied["archive"]["status"] == "written"
    assert applied["changed_files"] == [
        item["path"] for item in applied["archive"]["files"]
    ]
    assert all(path.startswith(f"{CURRENT_FACTS_ARCHIVE_ROOT}/") for path in applied["changed_files"])
    assert all((project / path).is_file() for path in applied["changed_files"])


def test_current_facts_apply_fails_closed_when_the_previewed_observation_changes(tmp_path: Path) -> None:
    project = _make_git_checkout(tmp_path)
    server = MCPPlanningBridgeServer(str(project), exposure_profile="commander")
    original_analyze = server._tool_analyze_project_state
    baseline = original_analyze({})
    assert baseline["ok"] is True
    current_state = copy.deepcopy(baseline["canonical_state"])

    def analyze_fixture(_params: dict) -> dict:
        return {"ok": True, "canonical_state": copy.deepcopy(current_state)}

    server._tool_analyze_project_state = analyze_fixture  # type: ignore[method-assign]
    preview = _data(
        server.call_tool_for_agent(
            "run_mcp_workflow",
            {"workflow": "current_facts", "phase": "preview"},
        )
    )
    current_state["warnings"] = ["observation_changed_after_preview"]
    apply_action = next(
        action
        for action in preview["next_actions"]
        if action.get("params", {}).get("phase") == "apply"
    )

    stale = server.call_tool_for_agent("run_mcp_workflow", apply_action["params"])

    assert stale["ok"] is False
    assert stale["error_code"] == "CURRENT_FACTS_PREVIEW_STALE"
    assert not (project / CURRENT_FACTS_ARCHIVE_ROOT).exists()
