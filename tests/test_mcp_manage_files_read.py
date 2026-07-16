from pathlib import Path

from runner.mcp_server import (
    MCP_MANAGE_FILES_READ_TARGET_CHARS,
    MCPPlanningBridgeServer,
)
from runner.path_policy import RunnerPathPolicy


ROOT = Path(__file__).resolve().parents[1]


def test_registry_review_and_decision_yaml_are_narrowly_readable() -> None:
    policy = RunnerPathPolicy()

    assert policy.is_allowed_source_path(
        "control-plane/registry/reports/f4-r9.manifest.yaml"
    )
    assert policy.is_allowed_source_path(
        "control-plane/registry/decisions/f4-r9-freeze.yaml"
    )
    assert not policy.is_allowed_source_path(
        "control-plane/registry/drafts/f4-r9-amendment.yaml"
    )
    assert not policy.is_allowed_source_path("config/production.yaml")


def test_manage_files_read_packages_connector_sized_result_and_keeps_project() -> None:
    server = MCPPlanningBridgeServer(str(ROOT))
    params = {
        "action": "read",
        "project_name": "AGENTS_OS_Workspace",
        "file": "CURRENT_STATE.md",
    }
    shaped = server._shape_mcp_call_result(
        {
            "ok": True,
            "tool": "manage_files",
            "data": {"content": "x" * 30000},
        },
        params,
    )

    structured = shaped["structuredContent"]
    assert structured["packaged"] is True
    assert structured["package_mode"] == "manifest"
    assert (
        structured["summary"]["target_tool_result_chars"]
        == MCP_MANAGE_FILES_READ_TARGET_CHARS
    )
    next_read = structured["recommended_next_reads"][0]
    assert next_read["tool"] == "manage_files"
    assert next_read["arguments"]["project_name"] == "AGENTS_OS_Workspace"
    assert next_read["arguments"]["max_chars"] == 20000


def test_manage_files_non_read_keeps_general_result_limit() -> None:
    server = MCPPlanningBridgeServer(str(ROOT))
    shaped = server._shape_mcp_call_result(
        {
            "ok": True,
            "tool": "manage_files",
            "data": {"results": ["x" * 30000]},
        },
        {"action": "search", "query": "x"},
    )

    assert shaped["structuredContent"].get("packaged") is not True


def test_runtime_status_compares_loaded_runtime_checkout_not_requested_project(
    monkeypatch,
) -> None:
    server = MCPPlanningBridgeServer(str(ROOT))
    calls: list[str] = []

    monkeypatch.setattr(
        "runner.mcp_server.loaded_runtime_project_root",
        lambda: "/runtime/colameta",
    )

    observed_kwargs: list[dict[str, object]] = []

    def fake_runtime_status(project_root: str, **kwargs: object) -> dict[str, object]:
        calls.append(project_root)
        observed_kwargs.append(kwargs)
        return {
            "ok": True,
            "project_checkout": {"project_root": project_root, "head": "runtime-head"},
            "restart_needed": False,
        }

    monkeypatch.setattr("runner.mcp_server.get_runtime_version_status", fake_runtime_status)
    monkeypatch.setattr(
        "runner.mcp_server.git_checkout_metadata",
        lambda project_root: {
            "project_root": project_root,
            "head": "requested-head",
            "head_available": True,
        },
    )

    status = server._runtime_version_status_for_project("/projects/agents-os")

    assert calls == ["/projects/agents-os"]
    assert observed_kwargs[0]["runtime_project_root"] == "/runtime/colameta"
    assert status["restart_needed"] is False
    assert status["runtime_project_root"] == "/runtime/colameta"
    assert status["requested_project_checkout_head"] == "requested-head"
