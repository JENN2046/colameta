from __future__ import annotations

from dataclasses import FrozenInstanceError
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from runner.mcp_result_artifacts import MCPResultArtifactStore
from runner.mcp_project_routing import (
    OPERATOR_TARGET_ISOLATED,
    TOOL_ROUTE_CONTINUATIONS,
    ProjectRouteContext,
    ProjectRouteServerFactory,
)
from runner.mcp_server import MCPPlanningBridgeServer, MCPToolInputError
from runner.project_registry import ProjectRegistry


class _RecordingServer:
    constructed: list[tuple[str, dict[str, object]]] = []

    def __init__(self, project_root: str, **kwargs: object):
        self.constructed.append((project_root, kwargs))
        self.project_root = project_root
        self.service_mode = False
        self.mcp_exposure_profile = "normal"
        self.work_item_scope_mode = None
        self._mcp_result_artifact_store = object()
        self._gate_review_preview_store = object()
        self._review_manifest_store = object()
        self._current_facts_preview_store = object()
        self._operator_private_state = object()


def _recording_serving_server() -> _RecordingServer:
    server = object.__new__(_RecordingServer)
    server.project_root = "/serving"
    server.service_mode = True
    server.mcp_exposure_profile = "commander"
    server.work_item_scope_mode = "bounded_pilot"
    server._mcp_result_artifact_store = object()
    server._gate_review_preview_store = object()
    server._review_manifest_store = object()
    server._current_facts_preview_store = object()
    server._operator_private_state = object()
    return server


def _make_git_checkout(tmp_path: Path, name: str) -> Path:
    project = tmp_path / name
    project.mkdir()
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    subprocess.run(
        ["git", "-C", str(project), "config", "user.email", f"{name}@example.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(project), "config", "user.name", name],
        check=True,
    )
    (project / "README.md").write_text(f"{name}\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(project), "add", "."], check=True)
    subprocess.run(["git", "-C", str(project), "commit", "-qm", "fixture"], check=True)
    return project


def _service_with_projects(
    tmp_path: Path,
    projects: dict[str, Path],
) -> MCPPlanningBridgeServer:
    registry = ProjectRegistry(
        registry_path=str(tmp_path / "registry.json"),
        user_settings_path=str(tmp_path / "settings.json"),
    )
    for project_name, project_root in projects.items():
        registered = registry.register_project(
            str(project_root),
            project_name=project_name,
            project_mode="managed",
        )
        assert registered["ok"] is True
    server = MCPPlanningBridgeServer(
        str(tmp_path),
        service_mode=True,
        exposure_profile="commander",
    )
    server.project_registry = registry
    return server


def test_project_route_context_is_a_frozen_value_object() -> None:
    context = ProjectRouteContext(
        project_root="/target",
        public_project_name="requested-alias",
        require_managed=True,
    )

    assert context == ProjectRouteContext(
        project_root="/target",
        public_project_name="requested-alias",
        require_managed=True,
    )
    with pytest.raises(FrozenInstanceError):
        context.project_root = "/replacement"  # type: ignore[misc]


def test_factory_constructs_with_only_the_target_root_and_keeps_operator_isolated() -> None:
    serving_server = _recording_serving_server()
    factory = ProjectRouteServerFactory(serving_server)
    context = ProjectRouteContext(
        project_root="/target",
        public_project_name="target",
        require_managed=True,
    )
    _RecordingServer.constructed.clear()

    target = factory.create(context, OPERATOR_TARGET_ISOLATED)

    assert _RecordingServer.constructed == [("/target", {})]
    assert target.service_mode is False
    assert target.mcp_exposure_profile == "normal"
    assert target.work_item_scope_mode is None
    assert target._mcp_result_artifact_store is not serving_server._mcp_result_artifact_store
    assert target._gate_review_preview_store is not serving_server._gate_review_preview_store
    assert target._review_manifest_store is not serving_server._review_manifest_store
    assert (
        target._current_facts_preview_store
        is not serving_server._current_facts_preview_store
    )
    assert target._operator_private_state is not serving_server._operator_private_state


def test_tool_route_factory_reads_latest_continuation_stores_on_every_create() -> None:
    serving_server = _recording_serving_server()
    factory = ProjectRouteServerFactory(serving_server)
    context = ProjectRouteContext(
        project_root="/target",
        public_project_name="target",
        require_managed=False,
    )
    first_result_store = serving_server._mcp_result_artifact_store
    first_gate_store = serving_server._gate_review_preview_store

    first_target = factory.create(context, TOOL_ROUTE_CONTINUATIONS)

    assert first_target._mcp_result_artifact_store is first_result_store
    assert first_target._gate_review_preview_store is first_gate_store
    assert first_target._review_manifest_store is not serving_server._review_manifest_store

    latest_result_store = object()
    latest_gate_store = object()
    serving_server._mcp_result_artifact_store = latest_result_store
    serving_server._gate_review_preview_store = latest_gate_store

    latest_target = factory.create(context, TOOL_ROUTE_CONTINUATIONS)

    assert latest_target._mcp_result_artifact_store is latest_result_store
    assert latest_target._gate_review_preview_store is latest_gate_store
    assert latest_target._review_manifest_store is not serving_server._review_manifest_store


def test_route_context_uses_requested_trimmed_name_and_preserves_resolver_choice(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path))
    resolver_calls: list[str] = []

    def resolve_read_only(_params: dict) -> tuple[str, dict]:
        resolver_calls.append("read_only")
        return str(tmp_path / "read-target"), {"project_name": "canonical-read-name"}

    def resolve_managed(_params: dict) -> tuple[str, dict]:
        resolver_calls.append("managed")
        return str(tmp_path / "managed-target"), {"project_name": "canonical-managed-name"}

    monkeypatch.setattr(server, "_resolve_read_only_project_context", resolve_read_only)
    monkeypatch.setattr(server, "_resolve_managed_project_context", resolve_managed)

    read_context = server._resolve_project_route_context(
        {"project_name": "  requested-read-alias  "},
        require_managed=False,
    )
    managed_context = server._resolve_project_route_context(
        {"project_name": "  requested-managed-alias  "},
        require_managed=True,
    )
    unnamed_context = server._resolve_project_route_context(
        {},
        require_managed=False,
    )

    assert resolver_calls == ["read_only", "managed", "read_only"]
    assert read_context == ProjectRouteContext(
        project_root=str(tmp_path / "read-target"),
        public_project_name="requested-read-alias",
        require_managed=False,
    )
    assert managed_context == ProjectRouteContext(
        project_root=str(tmp_path / "managed-target"),
        public_project_name="requested-managed-alias",
        require_managed=True,
    )
    assert unnamed_context.public_project_name is None


def test_tool_and_operator_entries_use_the_same_factory_seam(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path / "service"))
    routed_params: list[dict] = []

    def routed_tool(params: dict) -> dict:
        routed_params.append(dict(params))
        return {
            "workflow": "thin_governed_loop_preview",
            "result": {
                "next_request_payload": {},
                "copy_paste_next_request": {},
                "generated_input_bundle_summary": {"next_request_shape": {}},
            },
            "next_action": {
                "tool": "probe",
                "arguments": {},
            },
        }

    tool_target = SimpleNamespace(tools={"probe": routed_tool})
    operator_target = SimpleNamespace(project_root=str(tmp_path / "operator-target"))

    class _FactorySpy:
        def __init__(self) -> None:
            self.calls: list[tuple[ProjectRouteContext, object]] = []

        def create(
            self,
            context: ProjectRouteContext,
            binding_policy: object,
        ) -> object:
            self.calls.append((context, binding_policy))
            if binding_policy is TOOL_ROUTE_CONTINUATIONS:
                return tool_target
            return operator_target

    factory = _FactorySpy()
    server._project_route_server_factory = factory  # type: ignore[assignment]
    monkeypatch.setattr(
        server,
        "_resolve_read_only_project_context",
        lambda _params: (
            str(tmp_path / "tool-target"),
            {"project_name": "canonical-name"},
        ),
    )
    monkeypatch.setattr(
        server,
        "_resolve_managed_project_context",
        lambda _params: (
            str(tmp_path / "operator-target"),
            {"project_name": "canonical-name"},
        ),
    )

    routed_result = server._route_project_name_tool(
        "probe",
        {
            "project_name": "  requested-alias  ",
            "payload": "kept",
        },
        require_managed=False,
    )
    selected_operator_target = server._operator_target_server(
        {
            "project_name": "  operator-alias  ",
            "project_root": "/ignored/operator/override",
        }
    )

    assert routed_params == [
        {
            "payload": "kept",
            "__context_binding_project_name": "requested-alias",
        }
    ]
    assert routed_result["result"]["next_request_payload"]["project_name"] == (
        "requested-alias"
    )
    assert routed_result["result"]["copy_paste_next_request"]["project_name"] == (
        "requested-alias"
    )
    assert routed_result["result"]["generated_input_bundle_summary"][
        "next_request_shape"
    ]["project_name"] == "requested-alias"
    assert routed_result["next_action"]["arguments"]["project_name"] == (
        "requested-alias"
    )
    assert selected_operator_target is operator_target
    assert factory.calls == [
        (
            ProjectRouteContext(
                project_root=str(tmp_path / "tool-target"),
                public_project_name="requested-alias",
                require_managed=False,
            ),
            TOOL_ROUTE_CONTINUATIONS,
        ),
        (
            ProjectRouteContext(
                project_root=str(tmp_path / "operator-target"),
                public_project_name="operator-alias",
                require_managed=True,
            ),
            OPERATOR_TARGET_ISOLATED,
        ),
    ]


def test_tool_route_still_rejects_nonempty_project_root_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path))
    monkeypatch.setattr(
        server,
        "_resolve_read_only_project_context",
        lambda _params: pytest.fail("resolver must not run after override rejection"),
    )

    with pytest.raises(MCPToolInputError) as exc_info:
        server._route_project_name_tool(
            "probe",
            {
                "project_name": "target",
                "project_root": " /untrusted/override ",
            },
            require_managed=False,
        )

    assert exc_info.value.error_code == "PROJECT_ROOT_OVERRIDE_NOT_ALLOWED"


def test_same_root_operator_returns_self_without_calling_factory_or_rejecting_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path))

    class _FailingFactory:
        def create(self, _context: ProjectRouteContext, _binding_policy: object) -> object:
            pytest.fail("same-root operator routing must not construct a server")

    server._project_route_server_factory = _FailingFactory()  # type: ignore[assignment]
    monkeypatch.setattr(
        server,
        "_resolve_managed_project_context",
        lambda _params: (
            f"{server.project_root}/.",
            {"project_name": "same-root"},
        ),
    )

    selected = server._operator_target_server(
        {
            "project_name": "same-root",
            "project_root": "/ignored/operator/override",
        }
    )

    assert selected is server


def test_routed_artifact_can_be_read_by_a_later_public_call(tmp_path: Path) -> None:
    project = _make_git_checkout(tmp_path, "artifact-target")
    server = _service_with_projects(tmp_path, {"artifact-target": project})
    server._mcp_result_artifact_store = MCPResultArtifactStore(page_chars=300)

    inspected = server.call_tool_for_agent(
        "run_mcp_workflow",
        {
            "workflow": "current_facts",
            "phase": "inspect",
            "project_name": "artifact-target",
        },
    )

    assert inspected["ok"] is True
    contract = inspected["data"]
    assert contract["outcome"] == "completed"
    evidence = contract["evidence"]
    assert evidence["kind"] == "result_artifact"
    read = server.call_tool_for_agent(
        "read_result_artifact",
        {
            "artifact_id": evidence["artifact_id"],
            "artifact_page": 1,
        },
    )
    assert read["ok"] is True
    assert read["data"]["evidence"]["artifact_id"] == evidence["artifact_id"]
    assert (
        read["data"]["facts"]["artifact_page"]["content_sha256"]
        == evidence["content_sha256"]
    )


def test_project_preview_and_context_binding_cannot_cross_routes(
    tmp_path: Path,
) -> None:
    project_a = _make_git_checkout(tmp_path, "project-a")
    project_b = _make_git_checkout(tmp_path, "project-b")
    server = _service_with_projects(
        tmp_path,
        {
            "project-a": project_a,
            "project-b": project_b,
        },
    )

    previewed = server.call_tool_for_agent(
        "run_mcp_workflow",
        {
            "workflow": "small_project_patch",
            "phase": "preview",
            "project_name": "project-a",
            "file": "README.md",
            "old_text": "project-a\n",
            "new_text": "changed-a\n",
        },
    )

    assert previewed["ok"] is True
    contract = previewed["data"]
    assert contract["outcome"] == "confirmation_required"
    assert contract["context_binding"]["project_name"] == "project-a"
    cross_project_arguments = {
        **contract["next_action"]["arguments"],
        "project_name": "project-b",
    }
    blocked = server.call_tool_for_agent(
        "run_mcp_workflow",
        cross_project_arguments,
    )

    assert blocked["ok"] is False
    assert blocked["data"]["outcome"] == "blocked"
    assert blocked["data"]["error"]["code"] == "PROJECT_CONTEXT_MISMATCH"
    assert (project_a / "README.md").read_text(encoding="utf-8") == "project-a\n"
    assert (project_b / "README.md").read_text(encoding="utf-8") == "project-b\n"


def test_public_route_returns_project_name_without_project_root(tmp_path: Path) -> None:
    project = _make_git_checkout(tmp_path, "public-route")
    server = _service_with_projects(tmp_path, {"public-route": project})

    analyzed = server.call_tool_for_agent(
        "analyze_project_state",
        {"project_name": "public-route"},
    )

    assert analyzed["ok"] is True
    contract = analyzed["data"]
    assert contract["context_binding"]["project_name"] == "public-route"
    serialized = json.dumps(analyzed, ensure_ascii=False)
    assert str(project) not in serialized
    assert "project_root" not in serialized
