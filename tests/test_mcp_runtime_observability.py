from __future__ import annotations

import os
import tempfile
import unittest
import json
from pathlib import Path

from runner.cloud_agent_client import CloudRelayToolBridge, RelayRequest
from runner.cloud_pairing import CloudAgentCredential
from runner.mcp_server import MCPPlanningBridgeServer
from runner.project_registry import ProjectRegistry


HEAD_A = "a" * 40


class MCPRuntimeObservabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="colameta-mcp-runtime-observability-")
        self.tmp_path = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def make_git_checkout(self, head: str = HEAD_A, branch: str = "main", *, managed: bool = False) -> Path:
        project = self.tmp_path / f"project-{branch}"
        git_dir = project / ".git"
        ref_dir = git_dir / "refs" / "heads"
        ref_dir.mkdir(parents=True)
        (git_dir / "HEAD").write_text(f"ref: refs/heads/{branch}\n", encoding="utf-8")
        (ref_dir / branch).write_text(f"{head}\n", encoding="utf-8")
        if managed:
            runner_dir = project / ".colameta"
            runner_dir.mkdir()
            (runner_dir / "plan.json").write_text(json.dumps({"project_name": "demo-project"}), encoding="utf-8")
        return project

    def temp_registry(self) -> ProjectRegistry:
        return ProjectRegistry(
            registry_path=str(self.tmp_path / "project-registry.json"),
            user_settings_path=str(self.tmp_path / "settings.json"),
        )

    def register_demo_project(self, registry: ProjectRegistry, project: Path) -> None:
        registered = registry.register_project(
            str(project),
            project_name="demo-project",
            last_selected=False,
        )
        assert registered["ok"] is True

    def test_runtime_version_status_tool_is_registered_read_only_and_scoped(self) -> None:
        project = self.make_git_checkout()
        server = MCPPlanningBridgeServer(str(project))

        assert "get_runtime_version_status" in [tool.name for tool in server.tool_defs]
        assert server.get_required_scope_for_tool("get_runtime_version_status", {}) == "mcp:read"

        result = server.call_tool_for_agent("get_runtime_version_status", {})

        assert result["ok"] is True
        assert result["tool"] == "get_runtime_version_status"
        data = result["data"]
        assert data["read_only"] is True
        assert data["side_effects"] is False
        assert data["project_checkout"]["project_root"] == os.path.abspath(str(project))
        for forbidden_field in ("restart", "reload", "kill", "apply"):
            assert forbidden_field not in result
            assert forbidden_field not in data

    def test_web_gpt_service_entrypoint_is_read_only_and_guides_project_routing(self) -> None:
        project = self.make_git_checkout()
        server = MCPPlanningBridgeServer(str(project), service_mode=True)
        server.project_registry = self.temp_registry()
        self.register_demo_project(server.project_registry, project)
        tool_defs = {tool.name: tool for tool in server.tool_defs}

        assert "get_web_gpt_service_entrypoint" in tool_defs
        assert "get_stable_promotion_readiness" in tool_defs
        assert "get_web_gpt_service_entrypoint" in server._visible_tool_names()
        assert "get_stable_promotion_readiness" in server._visible_tool_names()
        assert server.get_required_scope_for_tool("get_web_gpt_service_entrypoint", {}) == "mcp:read"
        assert server.get_required_scope_for_tool("get_stable_promotion_readiness", {}) == "mcp:read"

        result = server.call_tool_for_agent("get_web_gpt_service_entrypoint", {})

        assert result["ok"] is True
        assert result["tool"] == "get_web_gpt_service_entrypoint"
        data = result["data"]
        assert data["ok"] is True
        assert data["read_only"] is True
        assert data["side_effects"] is False
        assert data["service_profile"]["mode"] == "service"
        assert data["service_profile"]["project_name_required_for_project_tools"] is True
        assert "demo-project" in [item["project_name"] for item in data["registered_projects"]]
        assert data["entry_sequence"][0]["tool"] == "list_registered_projects"
        assert data["entry_sequence"][1]["tool"] == "get_stable_promotion_readiness"
        assert data["entry_sequence"][2]["tool"] == "analyze_project_state"
        thin_flow = data["recommended_flows"]["thin_governed_loop_input_draft"]
        assert thin_flow["tool"] == "run_mcp_workflow"
        assert thin_flow["draft_arguments"]["input_mode"] == "draft"
        assert "result.next_request_payload" in thin_flow["next_step"]
        assert thin_flow["provided_arguments"]["input_mode"] == "provided"
        assert thin_flow["provided_arguments"]["thin_loop_inputs"] == "<generated_input_bundle>"
        assert data["safety_boundary"]["does_not_authorize_stable_promotion"] is True
        assert "stable promotion" in data["web_gpt_handoff_prompt"]

    def test_thin_loop_draft_next_payload_preserves_routed_project_name(self) -> None:
        project = self.make_git_checkout(managed=True)
        server = MCPPlanningBridgeServer(str(project), service_mode=True)
        server.project_registry = self.temp_registry()
        self.register_demo_project(server.project_registry, project)

        result = server.call_tool_for_agent(
            "run_mcp_workflow",
            {
                "workflow": "thin_governed_loop_preview",
                "phase": "preview",
                "project_name": "demo-project",
                "input_mode": "draft",
                "draft_seed": {
                    "source_id": "routed-demo",
                    "allowed_files": ["docs/demo.md"],
                    "validation_commands": ["git status --short"],
                    "review_decision_value": "NEEDS_FIX",
                },
            },
        )

        assert result["ok"] is True
        data = result["data"]
        assert data["ok"] is True
        next_payload = data["result"]["next_request_payload"]
        assert next_payload["project_name"] == "demo-project"
        assert data["result"]["copy_paste_next_request"]["project_name"] == "demo-project"
        assert data["result"]["generated_input_bundle_summary"]["next_request_shape"]["project_name"] == "demo-project"

    def test_stable_promotion_readiness_tool_is_read_only_and_non_authorizing(self) -> None:
        project = self.make_git_checkout()
        server = MCPPlanningBridgeServer(str(project))

        result = server.call_tool_for_agent("get_stable_promotion_readiness", {})

        assert result["ok"] is True
        assert result["tool"] == "get_stable_promotion_readiness"
        data = result["data"]
        assert data["ok"] is True
        assert data["read_only"] is True
        assert data["side_effects"] is False
        assert data["stable_production_ready"] is False
        assert data["safety_boundary"]["does_not_authorize_stable_replacement"] is True
        assert "get_stable_promotion_readiness" in data["tool_support"]["required_visible_tools"]
        for forbidden_field in ("restart", "reload", "kill", "apply", "deploy"):
            assert forbidden_field not in result

    def test_thin_governed_loop_preview_workflow_is_read_only_and_callable(self) -> None:
        project = Path(__file__).resolve().parents[1]
        server = MCPPlanningBridgeServer(str(project))
        tool_defs = {tool.name: tool for tool in server.tool_defs}

        assert "run_mcp_workflow" in tool_defs
        workflow_enum = tool_defs["run_mcp_workflow"].input_schema["properties"]["workflow"]["enum"]
        assert "thin_governed_loop_preview" in workflow_enum
        input_mode_enum = tool_defs["run_mcp_workflow"].input_schema["properties"]["input_mode"]["enum"]
        assert "template" in input_mode_enum
        assert "draft" in input_mode_enum
        assert "draft_seed" in tool_defs["run_mcp_workflow"].input_schema["properties"]
        assert server.get_required_scope_for_tool(
            "run_mcp_workflow",
            {"workflow": "thin_governed_loop_preview", "phase": "preview"},
        ) == "mcp:read"

        result = server.call_tool_for_agent(
            "run_mcp_workflow",
            {"workflow": "thin_governed_loop_preview", "phase": "preview"},
        )

        assert result["ok"] is True
        assert result["tool"] == "run_mcp_workflow"
        data = result["data"]
        assert data["ok"] is True
        assert data["workflow"] == "thin_governed_loop_preview"
        assert data["status"] == "succeeded"
        assert data["requires_confirmation"] is False
        assert data["changed_files"] == []
        assert data["preview_ids"] == []
        assert data["result"]["read_only"] is True
        assert data["result"]["side_effects"] is False
        assert data["result"]["thin_loop"]["thin_loop_status"] == "thin_governed_loop_passed"
        assert data["result"]["forbidden_authority_outputs"]["delivery_state_accepted"] is False

    def test_service_mode_missing_project_name_gives_operator_hint(self) -> None:
        project = self.make_git_checkout()
        server = MCPPlanningBridgeServer(str(project), service_mode=True)
        server.project_registry = self.temp_registry()
        self.register_demo_project(server.project_registry, project)

        result = server.call_tool_for_agent("manage_git", {"action": "push_status"})

        assert result["ok"] is False
        assert result["error_code"] == "PROJECT_NAME_REQUIRED"
        assert "list_registered_projects" in result["message"]
        assert "已登记 project_name 示例" in result["message"]
        assert "可用 project_name 示例" not in result["message"]
        assert "demo-project" in result["message"]
        assert result["details"]["required_param"] == "project_name"
        assert "demo-project" in result["details"]["available_project_names"]

    def test_auth_context_missing_project_name_does_not_enumerate_projects(self) -> None:
        project = self.make_git_checkout()
        server = MCPPlanningBridgeServer(str(project), service_mode=False)
        server.project_registry = self.temp_registry()
        self.register_demo_project(server.project_registry, project)

        result = server.call_tool_for_agent(
            "manage_git",
            {"action": "push_status"},
            auth_context={"mode": "cloud-relay", "device_id": "device-a", "scopes": ["mcp:read"]},
        )

        assert result["ok"] is False
        assert result["error_code"] == "PROJECT_NAME_REQUIRED"
        assert "list_registered_projects" in result["message"]
        assert "demo-project" not in result["message"]
        assert "available_project_names" not in result["details"]

    def test_cloud_relay_missing_project_name_returns_controlled_error(self) -> None:
        project = self.make_git_checkout()
        bridge = CloudRelayToolBridge(str(project), service_mode=True)
        server = bridge._get_server()
        server.project_registry = self.temp_registry()
        self.register_demo_project(server.project_registry, project)
        request = RelayRequest(
            request_id="req-1",
            tool_name="manage_git",
            arguments={"action": "push_status"},
            scopes=["mcp:read"],
        )
        credential = CloudAgentCredential(
            device_id="device-a",
            relay_url="http://example.invalid",
            agent_token="token",
            scopes=["mcp:read"],
            created_at="now",
        )

        response = bridge.handle_relay_request(request, credential)

        assert response.ok is False
        assert response.error_code == "PROJECT_NAME_REQUIRED"
        assert response.message is not None
        assert "list_registered_projects" in response.message
        assert "demo-project" not in response.message
        assert isinstance(response.data, dict)
        assert "available_project_names" not in response.data


if __name__ == "__main__":
    unittest.main()
