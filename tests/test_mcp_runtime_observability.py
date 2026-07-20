from __future__ import annotations

import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import unittest
import json
import urllib.request
from pathlib import Path
from unittest.mock import patch

from runner.cloud_agent_client import CloudRelayToolBridge, RelayRequest
from runner.cloud_pairing import CloudAgentCredential
from runner.mcp_server import MCPPlanningBridgeServer, MCP_TOOL_POLICIES, _MCPRateLimiter
from runner.project_registry import ProjectRegistry
from runner.product_console import record_product_console_action_result
from runner.runtime_observability import (
    build_apps_connector_closeout_packet,
    build_service_readiness_summary,
    build_stable_replacement_cadence,
    get_connector_runtime_health_status,
)


HEAD_A = "a" * 40
HOST = "127.0.0.1"


def free_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((HOST, 0))
        return int(sock.getsockname()[1])


class _PermissiveOAuthProvider:
    def validate_scope(self, token_payload: dict, required_scope: str) -> bool:
        return True


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

    def test_all_exposed_tools_have_policy_registry_entries(self) -> None:
        project = self.make_git_checkout()
        server = MCPPlanningBridgeServer(str(project), service_mode=False)

        missing = sorted(set(server.tools) - set(MCP_TOOL_POLICIES))

        assert missing == []

    def test_unknown_tool_action_fails_closed_before_handler(self) -> None:
        project = self.make_git_checkout()
        server = MCPPlanningBridgeServer(str(project), service_mode=False)

        result = server.call_tool_for_agent("manage_git_remote", {"action": "push_apply_typo"})

        assert result["ok"] is False
        assert result["error_code"] == "TOOL_POLICY_DENIED"
        assert result["details"]["policy"] == "mcp_tool_registry_fail_closed"

    def test_run_mcp_workflow_policy_matrix_covers_supported_workflow_phases(self) -> None:
        project = self.make_git_checkout()
        server = MCPPlanningBridgeServer(str(project), service_mode=False)
        expected_scopes = {
            ("auto_preview", "preview"): "mcp:preview",
            ("project_status", "inspect"): "mcp:read",
            ("source_onboarding", "preview"): "mcp:preview",
            ("plan_update", "preview"): "mcp:preview",
            ("plan_update", "apply"): "mcp:plan",
            ("small_project_patch", "status"): "mcp:read",
            ("small_project_patch", "preview"): "mcp:preview",
            ("small_project_patch", "apply"): "mcp:commit",
            ("docs_update", "inspect"): "mcp:read",
            ("docs_update", "preview"): "mcp:preview",
            ("docs_update", "apply"): "mcp:commit",
            ("git_commit", "status"): "mcp:read",
            ("git_commit", "preview"): "mcp:preview",
            ("git_commit", "commit"): "mcp:commit",
            ("git_restore_file", "preview"): "mcp:preview",
            ("git_restore_file", "apply"): "mcp:commit",
            ("git_revert", "preview"): "mcp:preview",
            ("git_revert", "apply"): "mcp:commit",
            ("git_undo_version", "inspect"): "mcp:read",
            ("git_undo_version", "preview"): "mcp:preview",
            ("git_undo_version", "apply"): "mcp:commit",
            ("agent_dispatch", "status"): "mcp:read",
            ("agent_dispatch", "run_preview"): "mcp:preview",
            ("agent_dispatch", "run"): "mcp:commit",
            ("prompt_to_plan", "preview"): "mcp:preview",
            ("prompt_to_plan", "plan_preview"): "mcp:preview",
            ("prompt_to_plan", "run_preview"): "mcp:preview",
            ("prompt_to_plan", "apply"): "mcp:commit",
            ("prompt_to_plan", "plan_apply"): "mcp:plan",
            ("prompt_to_plan", "apply_all"): "mcp:commit",
            ("prompt_to_plan", "run"): "mcp:commit",
            ("thin_governed_loop_preview", "preview"): "mcp:read",
            ("gate_review_request", "inspect"): "mcp:read",
            ("gate_review_request", "status"): "mcp:read",
            ("gate_review_request", "preview"): "mcp:preview",
            ("gate_review_request", "apply"): "mcp:commit",
            ("operator_batch", "preview"): "mcp:commit",
            ("operator_batch", "execute"): "mcp:commit",
            ("operator_batch", "status"): "mcp:read",
        }
        tool_def = next(tool for tool in server.tool_defs if tool.name == "run_mcp_workflow")
        declared_workflows = set(tool_def.input_schema["properties"]["workflow"]["enum"])
        covered_workflows = {workflow for workflow, _phase in expected_scopes}

        assert declared_workflows == covered_workflows

        for (workflow, phase), expected_scope in expected_scopes.items():
            assert (
                server.get_required_scope_for_tool(
                    "run_mcp_workflow",
                    {"workflow": workflow, "phase": phase},
                )
                == expected_scope
            )

        unsupported = server.call_tool_for_agent(
            "run_mcp_workflow",
            {"workflow": "prompt_to_plan", "phase": "inspect"},
        )

        assert unsupported["ok"] is False
        assert unsupported["error_code"] == "TOOL_POLICY_DENIED"

    def test_rate_limiter_rejects_global_overflow_without_creating_client_buckets(self) -> None:
        limiter = _MCPRateLimiter(
            global_per_minute=1,
            global_burst=1,
            client_per_minute=1000,
            client_burst=1000,
            max_client_buckets=16,
        )

        assert limiter.check("bearer:first")["ok"] is True
        for index in range(100):
            result = limiter.check(f"bearer:random-{index}")
            assert result["ok"] is False
            assert result["reason_code"] == "MCP_GLOBAL_RATE_LIMITED"

        assert list(limiter._client_buckets) == ["bearer:first"]

    def test_rate_limiter_has_hard_client_bucket_cap(self) -> None:
        limiter = _MCPRateLimiter(
            global_per_minute=1000,
            global_burst=1000,
            client_per_minute=1000,
            client_burst=1000,
            max_client_buckets=2,
        )

        assert limiter.check("bearer:first")["ok"] is True
        assert limiter.check("bearer:second")["ok"] is True
        result = limiter.check("bearer:third")

        assert result["ok"] is False
        assert result["reason_code"] == "MCP_CLIENT_BUCKET_LIMITED"
        assert sorted(limiter._client_buckets) == ["bearer:first", "bearer:second"]

    def test_connector_runtime_local_service_evidence_uses_web_api_healthz(self) -> None:
        project = self.make_git_checkout(managed=True)
        server = MCPPlanningBridgeServer(str(project), service_mode=True)
        requested_urls: list[str] = []

        class FakeResponse:
            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, *_: object) -> None:
                return None

            def read(self) -> bytes:
                return b'{"ok": true, "service": "colameta-web-console"}'

        def fake_urlopen(url: str, timeout: int = 0) -> FakeResponse:
            requested_urls.append(url)
            assert timeout == 2
            return FakeResponse()

        cmdline = [
            "python",
            "colameta",
            "serve",
            str(project),
            "--web-host",
            "127.0.0.1",
            "--web-port",
            "8801",
            "--mcp-host",
            "127.0.0.1",
            "--mcp-port",
            "8766",
        ]

        with (
            patch("runner.mcp_server.os.getpid", return_value=24680),
            patch("runner.mcp_server.ServiceLifecycleStore.read_process_cmdline_parts", return_value=cmdline),
            patch("runner.mcp_server.urllib.request.urlopen", side_effect=fake_urlopen),
        ):
            evidence = server._connector_runtime_local_service_evidence(str(project))

        assert evidence is not None
        assert evidence["pid"] == 24680
        assert evidence["health_source"] == "process_table"
        assert evidence["web_state"] == "healthy"
        assert evidence["web_url"] == "http://127.0.0.1:8801"
        assert evidence["mcp_state"] == "healthy"
        assert evidence["mcp_url"] == "http://127.0.0.1:8766/mcp"
        assert requested_urls == ["http://127.0.0.1:8801/api/healthz"]

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
        health = data["connector_runtime_health"]
        assert health["read_only"] is True
        assert health["local_service"]["status"] == "unverified"
        assert health["external_connector"]["status"] == "unverified"
        assert health["operator_closeout"]["status"] == "local_service_attention_needed"
        assert health["operator_closeout"]["decision"] == "blocked"
        assert "CONNECTOR_HEALTH_UNVERIFIED" in health["reason_codes"]
        for forbidden_field in ("restart", "reload", "kill", "apply"):
            assert forbidden_field not in result
            assert forbidden_field not in data

    def test_mcp_healthz_runtime_provenance_uses_loaded_runtime_root(self) -> None:
        project = self.make_git_checkout()
        runtime_root = str(self.tmp_path / "stable-runtime-root")
        calls: list[tuple[str | None, str | None]] = []

        def fake_runtime_healthz_provenance(project_root: str | None, *, runtime_project_root: str | None) -> dict[str, object]:
            calls.append((project_root, runtime_project_root))
            return {
                "loaded_runtime_head": None,
                "runtime_project_checkout_head": HEAD_A,
                "runtime_loaded_code_stale": False,
                "reload_needed_for_verification": False,
                "installed_package_matches_project_checkout": True,
                "installed_package_project_source_clean": True,
                "installed_package_source_cleanliness_status": "clean",
            }

        server = MCPPlanningBridgeServer(str(project), service_mode=True)
        port = free_tcp_port()
        errors: list[BaseException] = []

        def run_server() -> None:
            try:
                server.serve_http(host=HOST, port=port, auth_mode="none")
            except BaseException as exc:  # noqa: BLE001 - surfaced after shutdown
                errors.append(exc)

        with (
            patch("runner.mcp_server.loaded_runtime_project_root", return_value=runtime_root),
            patch("runner.mcp_server.runtime_healthz_provenance", side_effect=fake_runtime_healthz_provenance),
        ):
            thread = threading.Thread(target=run_server, daemon=True)
            thread.start()
            try:
                deadline = time.monotonic() + 8
                health: dict[str, object] | None = None
                while time.monotonic() < deadline:
                    if errors:
                        raise AssertionError(f"MCP server failed: {errors[0]}")
                    try:
                        with urllib.request.urlopen(f"http://{HOST}:{port}/healthz", timeout=0.5) as response:
                            health = json.loads(response.read().decode("utf-8"))
                            break
                    except Exception:
                        time.sleep(0.05)
                assert health is not None
            finally:
                httpd = getattr(server, "_httpd", None)
                if httpd is not None:
                    httpd.shutdown()
                thread.join(timeout=2)

        assert health["runtime_project_checkout_head"] == HEAD_A
        assert calls
        assert all(call == (str(project), runtime_root) for call in calls)

    def test_runtime_version_status_tool_uses_current_local_service_evidence(self) -> None:
        project = self.make_git_checkout(managed=True)
        server = MCPPlanningBridgeServer(str(project), service_mode=True)
        server.project_registry = self.temp_registry()
        self.register_demo_project(server.project_registry, project)
        requested_urls: list[str] = []

        class FakeResponse:
            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, *_: object) -> None:
                return None

            def read(self) -> bytes:
                return b'{"ok": true, "service": "colameta-web-console"}'

        def fake_urlopen(url: str, timeout: int = 0) -> FakeResponse:
            requested_urls.append(url)
            assert timeout == 2
            return FakeResponse()

        cmdline = [
            "python",
            "colameta",
            "serve",
            str(project),
            "--web-host",
            "127.0.0.1",
            "--web-port",
            "8801",
            "--mcp-host",
            "127.0.0.1",
            "--mcp-port",
            "8766",
        ]

        with (
            patch("runner.mcp_server.os.getpid", return_value=24680),
            patch("runner.mcp_server.ServiceLifecycleStore.read_process_cmdline_parts", return_value=cmdline),
            patch("runner.mcp_server.urllib.request.urlopen", side_effect=fake_urlopen),
        ):
            result = server.call_tool_for_agent("get_runtime_version_status", {"project_name": "demo-project"})

        assert result["ok"] is True
        health = result["data"]["connector_runtime_health"]
        assert health["local_service"]["status"] == "healthy"
        assert health["local_service"]["pid"] == 24680
        assert health["local_service"]["health_source"] == "process_table"
        assert health["local_service"]["web"]["reason_code"] == "WEB_ENDPOINT_HEALTHY"
        assert health["local_service"]["mcp"]["reason_code"] == "MCP_ENDPOINT_HEALTHY"
        assert requested_urls == ["http://127.0.0.1:8801/api/healthz"]

    def test_connector_runtime_health_separates_local_and_external_evidence(self) -> None:
        health = get_connector_runtime_health_status(
            runtime_status={
                "runtime_loaded_code_stale": False,
                "reload_needed_for_verification": False,
                "reload_awareness_reason": "installed_package_matches_project_checkout",
                "loaded_runtime": {"source_root": "/tmp/colameta-runtime"},
                "project_checkout": {"project_root": str(self.tmp_path)},
            },
            local_service={
                "state": "running",
                "health_source": "process_table",
                "pid": 12345,
                "project_root": str(self.tmp_path),
                "discovered_from_process_table": True,
                "enable_web": True,
                "web_state": "healthy",
                "web_url": "http://127.0.0.1:8801",
                "web_host": "127.0.0.1",
                "web_port": 8801,
                "enable_mcp": True,
                "mcp_state": "healthy",
                "mcp_url": "http://127.0.0.1:8766/mcp",
                "mcp_host": "127.0.0.1",
                "mcp_port": 8766,
            },
        )

        assert health["ok"] is True
        assert health["read_only"] is True
        assert health["side_effects"] is False
        assert health["runtime"]["status"] == "healthy"
        assert health["local_service"]["status"] == "healthy"
        assert health["local_service"]["health_source"] == "process_table"
        assert health["local_service"]["pid"] == 12345
        assert health["local_service"]["web"]["reason_code"] == "WEB_ENDPOINT_HEALTHY"
        assert health["local_service"]["mcp"]["reason_code"] == "MCP_ENDPOINT_HEALTHY"
        assert health["external_connector"]["status"] == "unverified"
        assert health["external_connector"]["tunnel_client"]["reason_code"] == "CONNECTOR_HEALTH_UNVERIFIED"
        assert health["external_connector"]["control_plane"]["reason_code"] == "TUNNEL_CONTROL_PLANE_UNVERIFIED"
        assert health["operator_closeout"]["status"] == "local_runtime_ready_external_connector_unverified"
        assert health["operator_closeout"]["decision"] == "blocked"
        assert health["operator_closeout"]["evidence_gap_count"] == 2
        assert health["operator_closeout"]["evidence_gaps"] == [
            {
                "component": "tunnel_client",
                "reason_code": "CONNECTOR_HEALTH_UNVERIFIED",
                "safe_evidence_needed": (
                    "sanitized tunnel-client runtime status from an approved status surface, "
                    "not config, logs, or tokens"
                ),
            },
            {
                "component": "tunnel_control_plane",
                "reason_code": "TUNNEL_CONTROL_PLANE_UNVERIFIED",
                "safe_evidence_needed": (
                    "sanitized tunnel control-plane status from an approved status surface, "
                    "not provider raw responses"
                ),
            },
        ]
        assert "restart_or_replace_stable_service" in health["operator_closeout"]["not_authorized_actions"]
        assert health["safety_boundary"]["does_not_read_provider_auth"] is True

    def test_connector_runtime_health_closes_out_with_sanitized_external_evidence(self) -> None:
        health = get_connector_runtime_health_status(
            runtime_status={
                "runtime_loaded_code_stale": False,
                "reload_needed_for_verification": False,
                "reload_awareness_reason": "installed_package_matches_project_checkout",
            },
            local_service={
                "state": "running",
                "health_source": "process_table",
                "pid": 12345,
                "enable_web": True,
                "web_state": "healthy",
                "enable_mcp": True,
                "mcp_state": "healthy",
            },
            tunnel_client={
                "status": "healthy",
                "reason_code": "TUNNEL_CLIENT_HEALTHY",
                "evidence_source": "sanitized_status_surface",
                "raw_token": "must-not-return",
            },
            control_plane={
                "status": "healthy",
                "reason_code": "TUNNEL_CONTROL_PLANE_HEALTHY",
                "evidence_source": "Bearer must-not-return",
            },
        )

        assert health["external_connector"]["status"] == "healthy"
        assert health["operator_closeout"]["status"] == "connector_closeout_ready"
        assert health["operator_closeout"]["decision"] == "ready"
        assert health["operator_closeout"]["evidence_gap_count"] == 0
        assert health["evidence_gaps"] == []
        serialized = json.dumps(health, ensure_ascii=False)
        assert "must-not-return" not in serialized
        assert "Bearer" not in serialized

    def test_connector_runtime_health_blocks_when_control_plane_evidence_is_missing(self) -> None:
        health = get_connector_runtime_health_status(
            runtime_status={
                "runtime_loaded_code_stale": False,
                "reload_needed_for_verification": False,
                "reload_awareness_reason": "installed_package_matches_project_checkout",
            },
            local_service={
                "state": "running",
                "health_source": "process_table",
                "pid": 12345,
                "enable_web": True,
                "web_state": "healthy",
                "enable_mcp": True,
                "mcp_state": "healthy",
            },
            tunnel_client={"status": "healthy", "reason_code": "TUNNEL_CLIENT_HEALTHY"},
        )

        assert health["external_connector"]["status"] == "unverified"
        assert health["external_connector"]["tunnel_client"]["status"] == "healthy"
        assert health["external_connector"]["control_plane"]["status"] == "unverified"
        assert health["operator_closeout"]["status"] == "local_runtime_ready_external_connector_unverified"
        assert health["operator_closeout"]["decision"] == "blocked"
        assert [gap["component"] for gap in health["evidence_gaps"]] == ["tunnel_control_plane"]

    def test_connector_runtime_health_distinguishes_degraded_external_evidence(self) -> None:
        health = get_connector_runtime_health_status(
            runtime_status={
                "runtime_loaded_code_stale": False,
                "reload_needed_for_verification": False,
                "reload_awareness_reason": "installed_package_matches_project_checkout",
            },
            local_service={
                "state": "running",
                "health_source": "process_table",
                "pid": 12345,
                "enable_web": True,
                "web_state": "healthy",
                "enable_mcp": True,
                "mcp_state": "healthy",
            },
            tunnel_client={"status": "degraded"},
            control_plane={"status": "healthy"},
        )

        assert health["overall_status"] == "local_runtime_observed_external_connector_degraded"
        assert health["external_connector"]["status"] == "degraded"
        assert health["external_connector"]["tunnel_client"]["status"] == "degraded"
        assert health["external_connector"]["tunnel_client"]["reason_code"] == "TUNNEL_CLIENT_DEGRADED"
        assert health["external_connector"]["control_plane"]["status"] == "healthy"
        assert health["operator_closeout"]["status"] == "external_connector_attention_needed"
        assert health["operator_closeout"]["decision"] == "blocked"

    def test_connector_runtime_health_fails_closed_without_evidence(self) -> None:
        health = get_connector_runtime_health_status()

        assert health["overall_status"] == "local_runtime_observed_external_connector_unverified"
        assert health["runtime"]["status"] == "unverified"
        assert health["local_service"]["status"] == "unverified"
        assert health["external_connector"]["status"] == "unverified"
        assert health["operator_closeout"]["status"] == "local_service_attention_needed"
        assert health["operator_closeout"]["decision"] == "blocked"
        assert {gap["component"] for gap in health["evidence_gaps"]} == {
            "runtime",
            "local_service",
            "tunnel_client",
            "tunnel_control_plane",
        }
        assert "LOCAL_SERVICE_HEALTH_UNVERIFIED" in health["reason_codes"]
        assert "CONNECTOR_HEALTH_UNVERIFIED" in health["reason_codes"]

    def test_connector_runtime_health_tool_accepts_sanitized_external_evidence(self) -> None:
        project = self.make_git_checkout(managed=True)
        server = MCPPlanningBridgeServer(str(project), service_mode=True)
        server.project_registry = self.temp_registry()
        self.register_demo_project(server.project_registry, project)
        runtime_status = {
            "runtime_loaded_code_stale": False,
            "reload_needed_for_verification": False,
            "reload_awareness_reason": "installed_package_matches_project_checkout",
        }
        local_service = {
            "state": "running",
            "health_source": "process_table",
            "pid": 12345,
            "enable_web": True,
            "web_state": "healthy",
            "enable_mcp": True,
            "mcp_state": "healthy",
        }

        with (
            patch("runner.mcp_server.get_runtime_version_status", return_value=runtime_status),
            patch.object(server, "_connector_runtime_local_service_evidence", return_value=local_service),
        ):
            result = server.call_tool_for_agent(
                "get_connector_runtime_health_status",
                {
                    "project_name": "demo-project",
                    "tunnel_client": {"status": "healthy", "reason_code": "TUNNEL_CLIENT_HEALTHY"},
                    "control_plane": {"status": "healthy", "reason_code": "TUNNEL_CONTROL_PLANE_HEALTHY"},
                },
            )

        assert result["ok"] is True
        assert result["tool"] == "get_connector_runtime_health_status"
        data = result["data"]
        assert data["read_only"] is True
        assert data["side_effects"] is False
        assert data["external_connector"]["status"] == "healthy"
        assert data["operator_closeout"]["status"] == "connector_closeout_ready"
        assert data["operator_closeout"]["decision"] == "ready"

    def test_service_readiness_summary_collapses_connector_closeout(self) -> None:
        connector_health = get_connector_runtime_health_status(
            runtime_status={
                "runtime_loaded_code_stale": False,
                "reload_needed_for_verification": False,
                "reload_awareness_reason": "project_checkout_matches_loaded_runtime",
            },
            local_service={
                "state": "running",
                "health_source": "process_table",
                "pid": 12345,
                "enable_web": True,
                "web_state": "healthy",
                "enable_mcp": True,
                "mcp_state": "healthy",
            },
            tunnel_client={"status": "healthy", "reason_code": "TUNNEL_CLIENT_HEALTHY"},
            control_plane={"status": "healthy", "reason_code": "CONTROL_PLANE_HEALTHY"},
        )

        summary = build_service_readiness_summary(
            connector_health=connector_health,
            project_name="demo-project",
        )

        assert summary["read_only"] is True
        assert summary["side_effects"] is False
        assert summary["status"] == "ready"
        assert summary["decision"] == "ready"
        assert summary["components"]["operator_closeout"]["status"] == "connector_closeout_ready"
        assert summary["safe_next_actions"][0]["authority"] == "preview_or_task_packet_only"
        assert "executor_run" in summary["not_authorized_actions"]

    def test_apps_connector_closeout_packet_keeps_apps_smoke_explicit(self) -> None:
        connector_health = get_connector_runtime_health_status(
            runtime_status={
                "runtime_loaded_code_stale": False,
                "reload_needed_for_verification": False,
                "reload_awareness_reason": "project_checkout_matches_loaded_runtime",
            },
            local_service={
                "state": "running",
                "health_source": "process_table",
                "pid": 12345,
                "enable_web": True,
                "web_state": "healthy",
                "enable_mcp": True,
                "mcp_state": "healthy",
            },
            tunnel_client={"status": "healthy", "reason_code": "TUNNEL_CLIENT_HEALTHZ_READY"},
            control_plane={"status": "healthy", "reason_code": "TUNNEL_CONTROL_PLANE_READYZ_READY"},
        )

        packet = build_apps_connector_closeout_packet(
            project_name="demo-project",
            connector_health=connector_health,
        )

        assert packet["read_only"] is True
        assert packet["side_effects"] is False
        assert packet["status"] == "ready"
        assert packet["preferred_smoke_tool"]["tool"] == "get_apps_connector_smoke_packet"
        assert packet["preferred_smoke_tool"]["arguments"]["project_name"] == "demo-project"
        assert packet["preferred_smoke_tool"]["fallback_tool"] == "get_connector_runtime_health_status"
        assert packet["metadata_refresh_guidance"]["expected_tool"] == "get_apps_connector_smoke_packet"
        assert packet["metadata_refresh_guidance"]["status"] == "refresh_if_tool_missing"
        assert packet["project_list_check"]["tool"] == "list_registered_projects"
        assert packet["project_list_check"]["expected_project_name"] == "demo-project"
        assert packet["connector_closeout_check"]["current_operator_closeout"] == "connector_closeout_ready"
        assert packet["connector_closeout_check"]["arguments"]["tunnel_client"]["reason_code"] == "TUNNEL_CLIENT_HEALTHZ_READY"
        assert packet["apps_connector_reachability"]["local_service_can_verify_chatgpt_session"] is False
        assert packet["token_expired_recovery"]["not_local_service_fix"] is True
        assert "read_tokens_or_cookies" in packet["token_expired_recovery"]["not_authorized_actions"]

    def test_stable_replacement_cadence_does_not_push_small_dev_drift_to_stable(self) -> None:
        cadence = build_stable_replacement_cadence(
            project_root="/tmp/demo",
            candidate_head=HEAD_A,
            stable_runtime_dir="/tmp/stable",
            stable_runtime_head="b" * 40,
        )

        assert cadence["status"] == "dev_ahead_stable"
        assert cadence["candidate_differs_from_stable"] is True
        assert cadence["replacement_possible"] is True
        assert cadence["replacement_available"] is False
        assert cadence["stable_replacement_not_required"] is True
        assert cadence["replacement_urgency"] == "optional_batch"
        assert cadence["recommended_cadence"] == "batch_when_ready"
        assert cadence["exact_authorization_required"] is False
        assert cadence["exact_authorization_phrase"] is None
        assert cadence["batch_review_summary"]["suggested_review_action"] == "keep_batching"
        assert cadence["authorization_policy"]["do_not_request_authorization_for_small_productization_commits"] is True
        assert "operator_explicitly_requests_stable_batch_promotion" in cadence["promotion_triggers"]

    def test_stable_replacement_cadence_summarizes_dev_batch_commits(self) -> None:
        repo = self.tmp_path / "batch-repo"
        repo.mkdir()

        def git(*args: str) -> str:
            completed = subprocess.run(
                ["git", *args],
                cwd=repo,
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
            assert completed.returncode == 0, completed.stderr
            return completed.stdout.strip()

        git("init")
        git("config", "user.email", "colameta@example.test")
        git("config", "user.name", "ColaMeta Test")
        stable_head = ""
        changes = [
            ("README.md", "Seed baseline"),
            ("runner/mcp_server.py", "Smooth Apps connector smoke entry"),
            ("runner/web_console_v2_assets.py", "Clarify Web Commander cadence"),
            ("scripts/runner_cli.py", "Expose colameta status review packet"),
            ("docs/USAGE.md", "Document stable batch review packet"),
            ("tests/test_batch_review.py", "Test stable batch review packet"),
        ]
        for index, (path, subject) in enumerate(changes):
            target = repo / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f"{subject}\n", encoding="utf-8")
            git("add", path)
            git("commit", "-m", subject)
            if index == 0:
                stable_head = git("rev-parse", "HEAD")
        candidate_head = git("rev-parse", "HEAD")

        cadence = build_stable_replacement_cadence(
            project_root=str(repo),
            candidate_head=candidate_head,
            stable_runtime_dir="/tmp/stable",
            stable_runtime_head=stable_head,
        )

        batch = cadence["dev_batch_summary"]
        review = cadence["batch_review_summary"]
        assert cadence["status"] == "dev_ahead_stable"
        assert cadence["stable_replacement_not_required"] is True
        assert cadence["exact_authorization_required"] is False
        assert batch["status"] == "available"
        assert batch["commit_count_since_stable"] == 5
        assert batch["from_stable_head"] == stable_head
        assert batch["to_candidate_head"] == candidate_head
        assert batch["batch_size"] == "medium"
        assert batch["promotion_posture"] == "review_batch_when_ready"
        assert batch["recent_commit_subjects"][0] == "Test stable batch review packet"
        assert "Smooth Apps connector smoke entry" in batch["recent_commit_subjects"]
        assert review["status"] == "available"
        assert review["surfaces"] == ["MCP", "Web", "CLI", "docs", "tests"]
        assert review["risk_level"] == "moderate"
        assert review["suggested_review_action"] == "ready_for_human_review"
        assert "5 commits since stable covering MCP/Web/CLI/docs/tests" in review["theme_summary"]
        assert review["changed_file_count"] == 5
        assert cadence["safety_boundary"]["does_not_request_stable_replacement"] is True

    def test_service_readiness_summary_explains_attention_and_blocked_states(self) -> None:
        attention_health = get_connector_runtime_health_status(
            runtime_status={
                "runtime_loaded_code_stale": False,
                "reload_needed_for_verification": False,
                "reload_awareness_reason": "project_checkout_matches_loaded_runtime",
            },
            local_service={
                "state": "running",
                "health_source": "process_table",
                "pid": 12345,
                "enable_web": True,
                "web_state": "healthy",
                "enable_mcp": True,
                "mcp_state": "healthy",
            },
        )
        attention = build_service_readiness_summary(
            connector_health=attention_health,
            project_name="demo-project",
        )
        assert attention["status"] == "needs_attention"
        assert attention["primary_blocker"]["component"] == "tunnel_client"
        assert attention["safe_next_actions"][0]["tool"] == "get_connector_runtime_health_status"

        blocked = build_service_readiness_summary(connector_health=get_connector_runtime_health_status())
        assert blocked["status"] == "blocked"
        assert blocked["safe_next_actions"][0]["tool"] == "get_web_gpt_service_entrypoint"

    def test_connector_runtime_health_tool_rejects_unsanitized_external_fields(self) -> None:
        project = self.make_git_checkout(managed=True)
        server = MCPPlanningBridgeServer(str(project), service_mode=True)
        server.project_registry = self.temp_registry()
        self.register_demo_project(server.project_registry, project)

        result = server.call_tool_for_agent(
            "get_connector_runtime_health_status",
            {
                "project_name": "demo-project",
                "tunnel_client": {
                    "status": "healthy",
                    "reason_code": "TUNNEL_CLIENT_HEALTHY",
                    "raw_token": "must-not-return",
                },
            },
        )

        assert result["ok"] is False
        assert result["error_code"] == "UNSAFE_CONNECTOR_EVIDENCE"
        serialized = json.dumps(result, ensure_ascii=False)
        assert "must-not-return" not in serialized
        assert "raw_token" not in serialized

    def test_apps_connector_smoke_packet_is_read_only_and_surfaces_stable_drift(self) -> None:
        project = self.make_git_checkout(head=HEAD_A, managed=True)
        stable = self.make_git_checkout(head="b" * 40, branch="stable")
        server = MCPPlanningBridgeServer(str(project), service_mode=True)
        server.project_registry = self.temp_registry()
        self.register_demo_project(server.project_registry, project)
        runtime_status = {
            "project_checkout_head": HEAD_A,
            "loaded_runtime_head": HEAD_A,
            "runtime_loaded_code_stale": False,
            "reload_needed_for_verification": False,
            "reload_awareness_reason": "project_checkout_matches_loaded_runtime",
        }
        local_service = {
            "state": "running",
            "health_source": "process_table",
            "pid": 12345,
            "enable_web": True,
            "web_state": "healthy",
            "enable_mcp": True,
            "mcp_state": "healthy",
            "project_root": str(project),
        }
        record_product_console_action_result(
            str(project),
            action_id="submission_evidence_activity",
            tool="submission_evidence_activity_summary",
            mode="read",
            status="updated",
            message="Submission evidence activity | recovery refreshed",
            project_name="demo-project",
            result_ok=True,
        )

        with (
            patch("runner.mcp_server.DEFAULT_STABLE_RUNTIME_DIR", str(stable)),
            patch("runner.mcp_server.get_runtime_version_status", return_value=runtime_status),
            patch.object(server, "_connector_runtime_local_service_evidence", return_value=local_service),
        ):
            result = server.call_tool_for_agent(
                "get_apps_connector_smoke_packet",
                {
                    "project_name": "demo-project",
                    "tunnel_client": {
                        "status": "healthy",
                        "reason_code": "TUNNEL_CLIENT_HEALTHZ_READY",
                        "evidence_source": "sanitized_test",
                        "last_observed_at": "2026-07-03T00:00:00Z",
                    },
                    "control_plane": {
                        "status": "healthy",
                        "reason_code": "TUNNEL_CONTROL_PLANE_READYZ_READY",
                        "evidence_source": "sanitized_test",
                        "last_observed_at": "2026-07-03T00:00:00Z",
                    },
                },
            )

        assert result["ok"] is True
        assert result["tool"] == "get_apps_connector_smoke_packet"
        data = result["data"]
        assert data["read_only"] is True
        assert data["side_effects"] is False
        assert data["apps_connector_closeout"]["status"] == "ready"
        assert data["apps_connector_closeout"]["project_list_check"]["tool"] == "list_registered_projects"
        closeout_evidence = data["apps_connector_closeout"]["release_submission_evidence"]
        assert closeout_evidence["source"] == "release_submission_evidence_closeout"
        assert closeout_evidence["tool"] == "get_release_submission_readiness"
        assert closeout_evidence["read_only"] is True
        assert closeout_evidence["side_effects"] is False
        assert closeout_evidence["evidence_progress"]["source"] == "submission_evidence_progress"
        assert closeout_evidence["evidence_progress"]["total_count"] == 10
        activity = closeout_evidence["submission_evidence_activity"]
        assert activity["available"] is True
        assert activity["action_id"] == "submission_evidence_activity"
        assert activity["tool"] == "submission_evidence_activity_summary"
        assert activity["status"] == "updated"
        assert activity["result_ok"] is True
        assert activity["read_only_summary"] is True
        assert activity["authority_boundary"]["does_not_write_runtime_state"] is True
        assert data["release_submission_evidence"] == closeout_evidence
        assert data["metadata_refresh_guidance"]["expected_tool"] == "get_apps_connector_smoke_packet"
        assert data["operator_sequence"][1]["tool"] == "get_apps_connector_smoke_packet"
        assert data["connector_runtime_health"]["overall_status"] == "healthy"
        assert data["stable_replacement_hint"]["status"] == "dev_ahead_stable"
        assert data["stable_replacement_hint"]["candidate_head"] == HEAD_A
        assert data["stable_replacement_hint"]["stable_runtime_head"] == "b" * 40
        assert data["stable_replacement_hint"]["stable_replacement_not_required"] is True
        assert data["stable_replacement_hint"]["recommended_cadence"] == "batch_when_ready"
        assert data["stable_replacement_hint"]["exact_authorization_required"] is False
        assert data["stable_replacement_hint"]["exact_authorization_phrase"] is None
        assert data["authority_boundary"]["does_not_authorize_stable_replacement"] is True

    def test_stable_replacement_cadence_tool_is_read_only_and_batch_oriented(self) -> None:
        project = self.make_git_checkout(head=HEAD_A, managed=True)
        stable = self.make_git_checkout(head="b" * 40, branch="stable")
        server = MCPPlanningBridgeServer(str(project), service_mode=True)
        server.project_registry = self.temp_registry()
        self.register_demo_project(server.project_registry, project)
        runtime_status = {
            "project_checkout_head": HEAD_A,
            "loaded_runtime_head": HEAD_A,
            "runtime_loaded_code_stale": False,
            "reload_needed_for_verification": False,
            "reload_awareness_reason": "project_checkout_matches_loaded_runtime",
        }
        local_service = {
            "state": "running",
            "health_source": "process_table",
            "pid": 12345,
            "enable_web": True,
            "web_state": "healthy",
            "enable_mcp": True,
            "mcp_state": "healthy",
            "project_root": str(project),
        }

        with (
            patch("runner.mcp_server.DEFAULT_STABLE_RUNTIME_DIR", str(stable)),
            patch("runner.mcp_server.get_runtime_version_status", return_value=runtime_status),
            patch.object(server, "_connector_runtime_local_service_evidence", return_value=local_service),
        ):
            result = server.call_tool_for_agent(
                "get_stable_replacement_cadence",
                {"project_name": "demo-project"},
            )

        assert result["ok"] is True
        assert result["tool"] == "get_stable_replacement_cadence"
        data = result["data"]
        assert data["read_only"] is True
        assert data["source"] == "stable_replacement_cadence"
        assert data["status"] == "dev_ahead_stable"
        assert data["replacement_possible"] is True
        assert data["replacement_available"] is False
        assert data["stable_replacement_not_required"] is True
        assert data["recommended_cadence"] == "batch_when_ready"
        assert data["dev_batch_summary"]["status"] in {"available", "unavailable"}
        assert data["batch_review_summary"]["suggested_review_action"] in {
            "keep_batching",
            "ready_for_human_review",
        }
        assert data["exact_authorization_required"] is False
        assert data["safety_boundary"]["does_not_request_stable_replacement"] is True

    def test_web_gpt_service_entrypoint_is_read_only_and_guides_project_routing(self) -> None:
        project = self.make_git_checkout()
        server = MCPPlanningBridgeServer(str(project), service_mode=True)
        server.project_registry = self.temp_registry()
        self.register_demo_project(server.project_registry, project)
        tool_defs = {tool.name: tool for tool in server.tool_defs}

        assert "get_agent_consumer_contract" in tool_defs
        assert "get_service_entry_profile" in tool_defs
        assert "get_agent_operator_flow_packet" in tool_defs
        assert "get_web_gpt_service_entrypoint" in tool_defs
        assert "get_product_readiness_status" in tool_defs
        assert "get_chatgpt_app_readiness" in tool_defs
        assert "get_full_loop_authority_status" in tool_defs
        assert "get_product_console_map" in tool_defs
        assert "get_release_submission_readiness" in tool_defs
        assert "get_submission_evidence_auto_draft" in tool_defs
        assert "get_submission_evidence_fill_preview" in tool_defs
        assert "manage_submission_evidence_revision" in tool_defs
        assert "init_submission_evidence" in tool_defs
        assert "fill_submission_evidence_files" in tool_defs
        assert "mark_submission_evidence_ready_fields" in tool_defs
        assert "get_commander_app_manifest" in tool_defs
        assert "render_commander_app" in tool_defs
        assert "get_apps_connector_smoke_packet" in tool_defs
        assert "get_stable_replacement_cadence" in tool_defs
        assert "get_stage_parallel_plan_preview" in tool_defs
        assert "get_stage_parallel_run_preview" in tool_defs
        assert "get_stage_parallel_worktree_assignment_preview" in tool_defs
        assert "get_stage_parallel_next_action_packet" in tool_defs
        assert "get_stage_parallel_executor_group_preview" in tool_defs
        assert "get_stage_parallel_executor_results_packet" in tool_defs
        assert "get_stage_parallel_group_status" in tool_defs
        assert "get_stage_parallel_merge_preview" in tool_defs
        assert "get_stage_parallel_closeout_packet" in tool_defs
        assert "manage_stage_parallel_worktrees" in tool_defs
        assert "manage_stage_parallel_shard_inputs" in tool_defs
        assert "manage_stage_parallel_executor_group" in tool_defs
        assert "manage_stage_parallel_executor_runs" in tool_defs
        assert "manage_stage_parallel_merges" in tool_defs
        assert "get_connector_runtime_health_status" in tool_defs
        commander_schema = tool_defs["get_commander_app_manifest"].input_schema
        assert "reviewer_agent" in commander_schema["properties"]["profile_id"]["enum"]
        assert commander_schema["properties"]["tunnel_client"]["additionalProperties"] is False
        assert commander_schema["properties"]["control_plane"]["additionalProperties"] is False
        assert tool_defs["get_agent_operator_flow_packet"].title == "Get Agent Operator Flow Packet"
        assert tool_defs["get_product_readiness_status"].title == "Get Product Readiness Status"
        assert tool_defs["get_chatgpt_app_readiness"].title == "Get ChatGPT App Readiness"
        assert tool_defs["get_full_loop_authority_status"].title == "Get Full Loop Authority Status"
        assert tool_defs["get_product_console_map"].title == "Get Product Console Map"
        assert tool_defs["get_release_submission_readiness"].title == "Get Release Submission Readiness"
        assert tool_defs["get_submission_evidence_auto_draft"].title == "Get Submission Evidence Auto Draft"
        assert tool_defs["get_submission_evidence_auto_draft"].annotations["readOnlyHint"] is True
        assert tool_defs["get_submission_evidence_fill_preview"].title == "Get Submission Evidence Fill Preview"
        assert tool_defs["get_submission_evidence_fill_preview"].annotations["readOnlyHint"] is True
        assert tool_defs["manage_submission_evidence_revision"].title == "Manage Submission Evidence Revision"
        assert tool_defs["manage_submission_evidence_revision"].annotations["destructiveHint"] is True
        assert tool_defs["init_submission_evidence"].title == "Initialize Submission Evidence"
        assert tool_defs["init_submission_evidence"].annotations["readOnlyHint"] is False
        assert tool_defs["init_submission_evidence"].annotations["destructiveHint"] is False
        assert tool_defs["fill_submission_evidence_files"].title == "Fill Submission Evidence Files"
        assert tool_defs["fill_submission_evidence_files"].annotations["readOnlyHint"] is False
        assert tool_defs["fill_submission_evidence_files"].annotations["destructiveHint"] is False
        assert tool_defs["mark_submission_evidence_ready_fields"].title == "Mark Submission Evidence Ready Fields"
        assert tool_defs["mark_submission_evidence_ready_fields"].annotations["readOnlyHint"] is False
        assert tool_defs["mark_submission_evidence_ready_fields"].annotations["destructiveHint"] is False
        assert tool_defs["get_commander_app_manifest"].title == "Get Commander App Manifest"
        assert tool_defs["render_commander_app"].title == "Render Commander App"
        assert tool_defs["get_apps_connector_smoke_packet"].title == "Get Apps Connector Smoke Packet"
        assert tool_defs["get_stable_replacement_cadence"].title == "Get Stable Replacement Cadence"
        assert tool_defs["get_stage_parallel_plan_preview"].title == "Get Stage Parallel Plan Preview"
        assert tool_defs["get_stage_parallel_run_preview"].title == "Get Stage Parallel Run Preview"
        assert tool_defs["get_stage_parallel_worktree_assignment_preview"].title == "Get Stage Parallel Worktree Assignment Preview"
        assert tool_defs["get_stage_parallel_next_action_packet"].title == "Get Stage Parallel Next Action Packet"
        assert tool_defs["get_stage_parallel_executor_group_preview"].title == "Get Stage Parallel Executor Group Preview"
        assert tool_defs["get_stage_parallel_executor_results_packet"].title == "Get Stage Parallel Executor Results Packet"
        assert tool_defs["get_stage_parallel_group_status"].title == "Get Stage Parallel Group Status"
        assert tool_defs["get_stage_parallel_merge_preview"].title == "Get Stage Parallel Merge Preview"
        assert tool_defs["get_stage_parallel_closeout_packet"].title == "Get Stage Parallel Closeout Packet"
        assert tool_defs["manage_stage_parallel_worktrees"].title == "Manage Stage Parallel Worktrees"
        assert tool_defs["manage_stage_parallel_shard_inputs"].title == "Manage Stage Parallel Shard Inputs"
        assert tool_defs["manage_stage_parallel_executor_group"].title == "Manage Stage Parallel Executor Group"
        assert tool_defs["manage_stage_parallel_executor_runs"].title == "Manage Stage Parallel Executor Runs"
        assert tool_defs["manage_stage_parallel_merges"].title == "Manage Stage Parallel Merges"
        assert tool_defs["render_commander_app"].meta["ui"]["resourceUri"] == "ui://colameta/commander/v1.html"
        assert tool_defs["render_commander_app"].meta["ui"]["visibility"] == ["model", "app"]
        assert tool_defs["get_commander_app_manifest"].annotations["idempotentHint"] is True
        assert tool_defs["render_commander_app"].annotations["readOnlyHint"] is True
        assert tool_defs["render_commander_app"].annotations["idempotentHint"] is True
        assert tool_defs["record_product_console_action_result"].annotations["readOnlyHint"] is False
        assert tool_defs["record_product_console_action_result"].annotations["idempotentHint"] is True
        assert "action_fingerprint" in tool_defs["record_product_console_action_result"].input_schema["properties"]
        connector_schema = tool_defs["get_connector_runtime_health_status"].input_schema
        assert connector_schema["properties"]["tunnel_client"]["additionalProperties"] is False
        assert connector_schema["properties"]["control_plane"]["additionalProperties"] is False
        assert "get_stable_promotion_readiness" in tool_defs
        assert "get_agent_consumer_contract" in server._visible_tool_names()
        assert "get_service_entry_profile" in server._visible_tool_names()
        assert "get_agent_operator_flow_packet" in server._visible_tool_names()
        assert "get_web_gpt_service_entrypoint" in server._visible_tool_names()
        assert "get_product_readiness_status" in server._visible_tool_names()
        assert "get_chatgpt_app_readiness" in server._visible_tool_names()
        assert "get_full_loop_authority_status" in server._visible_tool_names()
        assert "get_product_console_map" in server._visible_tool_names()
        assert "get_release_submission_readiness" in server._visible_tool_names()
        assert "get_submission_evidence_auto_draft" in server._visible_tool_names()
        assert "get_submission_evidence_fill_preview" in server._visible_tool_names()
        assert "manage_submission_evidence_revision" in server._visible_tool_names()
        assert "init_submission_evidence" in server._visible_tool_names()
        assert "fill_submission_evidence_files" in server._visible_tool_names()
        assert "mark_submission_evidence_ready_fields" in server._visible_tool_names()
        assert "record_product_console_action_result" in server._visible_tool_names()
        assert "get_commander_app_manifest" in server._visible_tool_names()
        assert "render_commander_app" in server._visible_tool_names()
        assert "get_apps_connector_smoke_packet" in server._visible_tool_names()
        assert "get_stable_replacement_cadence" in server._visible_tool_names()
        assert "get_stage_parallel_plan_preview" in server._visible_tool_names()
        assert "get_stage_parallel_run_preview" in server._visible_tool_names()
        assert "get_stage_parallel_worktree_assignment_preview" in server._visible_tool_names()
        assert "get_stage_parallel_next_action_packet" in server._visible_tool_names()
        assert "get_stage_parallel_executor_group_preview" in server._visible_tool_names()
        assert "get_stage_parallel_executor_results_packet" in server._visible_tool_names()
        assert "get_stage_parallel_group_status" in server._visible_tool_names()
        assert "get_stage_parallel_merge_preview" in server._visible_tool_names()
        assert "get_stage_parallel_closeout_packet" in server._visible_tool_names()
        assert "manage_stage_parallel_worktrees" in server._visible_tool_names()
        assert "manage_stage_parallel_shard_inputs" in server._visible_tool_names()
        assert "manage_stage_parallel_executor_group" in server._visible_tool_names()
        assert "manage_stage_parallel_executor_runs" in server._visible_tool_names()
        assert "manage_stage_parallel_merges" in server._visible_tool_names()
        assert "get_connector_runtime_health_status" in server._visible_tool_names()
        assert "get_stable_promotion_readiness" in server._visible_tool_names()
        assert server.get_required_scope_for_tool("get_agent_consumer_contract", {}) == "mcp:read"
        assert server.get_required_scope_for_tool("get_service_entry_profile", {}) == "mcp:read"
        assert server.get_required_scope_for_tool("get_agent_operator_flow_packet", {}) == "mcp:read"
        assert server.get_required_scope_for_tool("get_web_gpt_service_entrypoint", {}) == "mcp:read"
        assert server.get_required_scope_for_tool("get_product_readiness_status", {}) == "mcp:read"
        assert server.get_required_scope_for_tool("get_chatgpt_app_readiness", {}) == "mcp:read"
        assert server.get_required_scope_for_tool("get_full_loop_authority_status", {}) == "mcp:read"
        assert server.get_required_scope_for_tool("get_product_console_map", {}) == "mcp:read"
        assert server.get_required_scope_for_tool("get_release_submission_readiness", {}) == "mcp:read"
        assert server.get_required_scope_for_tool("get_submission_evidence_auto_draft", {}) == "mcp:read"
        assert server.get_required_scope_for_tool("get_submission_evidence_fill_preview", {}) == "mcp:read"
        assert server.get_required_scope_for_tool(
            "manage_submission_evidence_revision", {"action": "status"}
        ) == "mcp:read"
        assert server.get_required_scope_for_tool(
            "manage_submission_evidence_revision", {"action": "preview"}
        ) == "mcp:preview"
        assert server.get_required_scope_for_tool(
            "manage_submission_evidence_revision", {"action": "apply"}
        ) == "mcp:commit"
        assert server.get_required_scope_for_tool("init_submission_evidence", {}) == "mcp:commit"
        assert server.get_required_scope_for_tool("fill_submission_evidence_files", {}) == "mcp:commit"
        assert server.get_required_scope_for_tool("mark_submission_evidence_ready_fields", {}) == "mcp:commit"
        assert server.get_required_scope_for_tool("record_product_console_action_result", {"status": "updated"}) == "mcp:commit"
        assert server.get_required_scope_for_tool("get_commander_app_manifest", {}) == "mcp:read"
        assert server.get_required_scope_for_tool("render_commander_app", {}) == "mcp:read"
        assert server.get_required_scope_for_tool("get_apps_connector_smoke_packet", {}) == "mcp:read"
        assert server.get_required_scope_for_tool("get_stable_replacement_cadence", {}) == "mcp:read"
        assert server.get_required_scope_for_tool("get_stage_parallel_plan_preview", {}) == "mcp:read"
        assert server.get_required_scope_for_tool("get_stage_parallel_run_preview", {}) == "mcp:read"
        assert server.get_required_scope_for_tool("get_stage_parallel_worktree_assignment_preview", {}) == "mcp:read"
        assert server.get_required_scope_for_tool("get_stage_parallel_next_action_packet", {}) == "mcp:read"
        assert server.get_required_scope_for_tool("get_stage_parallel_executor_group_preview", {}) == "mcp:read"
        assert server.get_required_scope_for_tool("get_stage_parallel_executor_results_packet", {}) == "mcp:read"
        assert server.get_required_scope_for_tool("get_stage_parallel_group_status", {}) == "mcp:read"
        assert server.get_required_scope_for_tool("get_stage_parallel_merge_preview", {}) == "mcp:read"
        assert server.get_required_scope_for_tool("get_stage_parallel_closeout_packet", {}) == "mcp:read"
        assert server.get_required_scope_for_tool("manage_stage_parallel_worktrees", {"action": "status"}) == "mcp:read"
        assert server.get_required_scope_for_tool("manage_stage_parallel_worktrees", {"action": "preview"}) == "mcp:preview"
        assert server.get_required_scope_for_tool("manage_stage_parallel_worktrees", {"action": "discard"}) == "mcp:preview"
        assert server.get_required_scope_for_tool("manage_stage_parallel_worktrees", {"action": "apply"}) == "mcp:commit"
        assert server.get_required_scope_for_tool("manage_stage_parallel_shard_inputs", {"action": "status"}) == "mcp:read"
        assert server.get_required_scope_for_tool("manage_stage_parallel_shard_inputs", {"action": "preview"}) == "mcp:preview"
        assert server.get_required_scope_for_tool("manage_stage_parallel_shard_inputs", {"action": "discard"}) == "mcp:preview"
        assert server.get_required_scope_for_tool("manage_stage_parallel_shard_inputs", {"action": "apply"}) == "mcp:commit"
        assert server.get_required_scope_for_tool("manage_stage_parallel_executor_group", {"action": "status"}) == "mcp:read"
        assert server.get_required_scope_for_tool("manage_stage_parallel_executor_group", {"action": "preview"}) == "mcp:preview"
        assert server.get_required_scope_for_tool("manage_stage_parallel_executor_group", {"action": "discard"}) == "mcp:preview"
        assert server.get_required_scope_for_tool("manage_stage_parallel_executor_group", {"action": "apply"}) == "mcp:commit"
        assert server.get_required_scope_for_tool("manage_stage_parallel_executor_runs", {"action": "status"}) == "mcp:read"
        assert server.get_required_scope_for_tool("manage_stage_parallel_executor_runs", {"action": "preview"}) == "mcp:preview"
        assert server.get_required_scope_for_tool("manage_stage_parallel_executor_runs", {"action": "discard"}) == "mcp:preview"
        assert server.get_required_scope_for_tool("manage_stage_parallel_executor_runs", {"action": "apply"}) == "mcp:commit"
        assert server.get_required_scope_for_tool("manage_stage_parallel_merges", {"action": "status"}) == "mcp:read"
        assert server.get_required_scope_for_tool("manage_stage_parallel_merges", {"action": "preview"}) == "mcp:preview"
        assert server.get_required_scope_for_tool("manage_stage_parallel_merges", {"action": "discard"}) == "mcp:preview"
        assert server.get_required_scope_for_tool("manage_stage_parallel_merges", {"action": "apply"}) == "mcp:commit"
        assert server.get_required_scope_for_tool("get_connector_runtime_health_status", {}) == "mcp:read"
        assert server.get_required_scope_for_tool("get_stable_promotion_readiness", {}) == "mcp:read"
        assert server.get_required_scope_for_tool(
            "manage_stable_promotion_evidence", {"action": "status"}
        ) == "mcp:read"
        assert server.get_required_scope_for_tool(
            "manage_stable_promotion_evidence", {"action": "preview"}
        ) == "mcp:preview"
        assert server.get_required_scope_for_tool(
            "manage_stable_promotion_evidence", {"action": "discard"}
        ) == "mcp:preview"
        assert server.get_required_scope_for_tool(
            "manage_stable_promotion_evidence", {"action": "apply"}
        ) == "mcp:commit"
        widget_html = server._commander_widget_html()
        assert "Readiness" in widget_html
        assert "Next Step" in widget_html
        assert "Flow persona" in widget_html
        assert "Primary blocker" in widget_html
        assert "Safe next action" in widget_html
        assert "Release Evidence" in widget_html
        assert "Recommended Actions" in widget_html
        assert "Evidence blockers" in widget_html
        assert "recommendedActions" in widget_html
        assert "callToolWithArgs" in widget_html
        assert "viewState = {}" in widget_html
        assert "viewState = Object.assign({}, viewState, manifest || {}, data)" in widget_html
        assert "var current = viewState" in widget_html
        assert "action-run" in widget_html
        assert "action-run-status" in widget_html
        assert "action-refresh-queue" in widget_html
        assert "action-refresh" in widget_html
        assert "action-record" in widget_html
        assert "rememberActionRunStatus" in widget_html
        assert "pendingBridgeCalls" in widget_html
        assert "bridgeMessageId" in widget_html
        assert "rememberBridgeToolResult" in widget_html
        assert "bridgeTimeoutMs" in widget_html
        assert "markBridgeToolTimeout" in widget_html
        assert "via bridge timeout" in widget_html
        assert "resultFailed" in widget_html
        assert "via bridge" in widget_html
        assert "refreshKey" in widget_html
        assert "recordKey" in widget_html
        assert "renderActionRefreshQueue" in widget_html
        assert "refresh queue" in widget_html
        assert "record_product_console_action_result" in widget_html
        assert "record action result" in widget_html
        assert "action_fingerprint: action.action_fingerprint" in widget_html
        assert "recorded result refresh" in widget_html
        assert "recordActionResultSucceeded" in widget_html
        assert "result.status === \"updated\"" in widget_html
        assert "result.result_status === \"recorded\"" in widget_html
        assert "result_status: normalized && normalized.status" in widget_html
        assert "var directStatus = resultFailed(normalized) ? \"failed\" : \"updated\"" in widget_html
        assert "recordStatus.status === \"recorded\"" in widget_html
        assert "refresh current" in widget_html
        assert "next_refresh_actions" in widget_html
        assert "last_action_result" in widget_html
        assert "errorSummary" in widget_html
        assert "bridge fallback after direct failure" in widget_html
        assert "colameta-commander-" in widget_html
        assert "Copy failed; payload below:" in widget_html
        assert "Copy unavailable; payload below:" in widget_html
        assert "Last run" in widget_html
        assert "Confirm outside" in widget_html
        assert "Preview first" in widget_html
        assert "completionFollowupItemForGroup" in widget_html
        assert "shared action " in widget_html
        assert "shared_by_component_count" in widget_html
        assert "stablePreviewActionIsRunnable" in widget_html
        assert "stablePreviewConfirmationMessage" in widget_html
        assert "stablePreviewToolCall" in widget_html
        assert "stablePreviewResultCanAdvance" in widget_html
        assert "stablePreviewConsoleRefreshArgs" in widget_html
        assert "stable preview refresh" in widget_html
        assert "previewActionConfirmations" in widget_html
        assert "Review preview" in widget_html
        assert "Confirm preview" in widget_html
        assert "confirmation_required" in widget_html
        assert 'args.action === "preview"' in widget_html
        assert 'resultContract.expected_result_kind === "preview_packet"' in widget_html
        assert "recommended_first_actions" in widget_html
        assert "requires_explicit_confirmation" in widget_html
        assert "does_not_authorize_stable_replacement" in widget_html
        assert "evidenceProgress" in widget_html
        assert "evidenceBundle" in widget_html
        assert "release_submission_evidence_bundle" in widget_html
        assert "clearStaleEvidenceState" in widget_html
        assert "submissionPreviewCardModels" in widget_html
        assert "copy_payload" in widget_html
        assert "primary.action_key = item.action_key" in widget_html
        assert "primary.action_fingerprint = item.action_fingerprint" in widget_html
        assert "primary.arguments.action_fingerprint = primary.action_fingerprint" in widget_html
        assert "action_key: action.action_key" in widget_html
        assert "action_fingerprint: action.action_fingerprint" in widget_html
        assert "renderEvidenceRefreshQueue" in widget_html
        assert "fillPlan.draft_entries" in widget_html
        assert "ready \" + (progress.complete_count || 0)" in widget_html
        assert "get_agent_operator_flow_packet" in widget_html
        assert "get_product_console_map" in widget_html
        assert "get_release_submission_readiness" in widget_html
        assert "get_submission_evidence_auto_draft" in widget_html
        assert "get_submission_evidence_fill_preview" in widget_html
        assert "get_apps_connector_smoke_packet" in widget_html
        assert "get_stable_replacement_cadence" in widget_html

    def test_commander_closeout_record_copy_puts_fingerprint_in_arguments(self) -> None:
        if shutil.which("node") is None:
            self.skipTest("node is required for commander closeout payload behavior smoke")

        project = self.make_git_checkout()
        server = MCPPlanningBridgeServer(str(project), service_mode=False)
        widget_html = server._commander_widget_html()
        function_source = widget_html.split("function closeoutFollowupAction", 1)[1].split(
            "function closeoutFollowupKey", 1
        )[0]
        script = "function closeoutFollowupAction" + function_source + r'''
const assert = require("assert");
const result = closeoutFollowupAction({
  item_id: "submission_evidence_activity",
  action_id: "submission_evidence_activity",
  action_key: "submission_evidence_activity|submission_evidence_activity_summary|read",
  action_fingerprint: "bound-fingerprint",
  required_scope: "mcp:commit",
  primary_action: {
    tool: "record_product_console_action_result",
    arguments: {
      action_id: "submission_evidence_activity",
      tool: "submission_evidence_activity_summary",
      mode: "read",
      status: "updated",
    },
  },
});
assert.strictEqual(result.arguments.action_fingerprint, "bound-fingerprint");
assert.strictEqual(result.action_key, "submission_evidence_activity|submission_evidence_activity_summary|read");
assert.strictEqual(result.required_scope, "mcp:commit");
'''
        completed = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=False, timeout=15)
        assert completed.returncode == 0, completed.stdout + completed.stderr

    def test_web_gpt_service_entrypoint_lists_commander_sequence(self) -> None:
        project = self.make_git_checkout(managed=True)
        server = MCPPlanningBridgeServer(str(project), service_mode=True)
        server.project_registry = self.temp_registry()
        self.register_demo_project(server.project_registry, project)

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
        profiles = {item["profile_id"]: item for item in data["service_entry_profiles"]}
        assert set(profiles) == {
            "web_gpt_commander",
            "local_codex_commander",
            "reviewer_agent",
            "planner_agent",
            "source_observer",
        }
        assert profiles["web_gpt_commander"]["first_reads"][1]["tool"] == "get_agent_consumer_contract"
        assert profiles["web_gpt_commander"]["first_reads"][2]["tool"] == "get_agent_operator_flow_packet"
        assert profiles["web_gpt_commander"]["first_reads"][4]["tool"] == "render_commander_app"
        assert profiles["reviewer_agent"]["default_authority"] == "review_only"
        entry_tools = [item["tool"] for item in data["entry_sequence"]]
        assert entry_tools[:5] == [
            "list_registered_projects",
            "get_agent_consumer_contract",
            "get_service_entry_profile",
            "get_agent_operator_flow_packet",
            "render_commander_app",
        ]
        assert data["entry_sequence"][4]["arguments"]["profile_id"] == "web_gpt_commander"
        for tool in {
            "get_stable_replacement_cadence",
            "get_stage_parallel_plan_preview",
            "get_stage_parallel_run_preview",
            "get_stage_parallel_worktree_assignment_preview",
            "get_stage_parallel_next_action_packet",
            "manage_stage_parallel_shard_inputs",
            "get_stage_parallel_executor_group_preview",
            "manage_stage_parallel_executor_runs",
            "get_stage_parallel_executor_results_packet",
            "get_stage_parallel_group_status",
            "get_stage_parallel_merge_preview",
            "manage_stage_parallel_merges",
            "get_stage_parallel_closeout_packet",
            "get_stable_promotion_readiness",
            "get_apps_connector_smoke_packet",
            "get_connector_runtime_health_status",
            "analyze_project_state",
        }:
            assert tool in entry_tools
        thin_flow = data["recommended_flows"]["thin_governed_loop_input_draft"]
        assert thin_flow["tool"] == "run_mcp_workflow"
        assert thin_flow["draft_arguments"]["input_mode"] == "draft"
        assert thin_flow["draft_arguments"]["draft_seed"]["task_tier"] == "M0-M2"
        assert thin_flow["direct_codex_packet_field"] == "result.codex_execution_packet"
        assert "result.codex_execution_packet.packet_status=ready" in thin_flow["next_step"]
        assert "result.codex_execution_packet.copy_paste_codex_prompt" in thin_flow["next_step"]
        assert "result.next_request_payload" in thin_flow["next_step"]
        assert thin_flow["provided_arguments"]["input_mode"] == "provided"
        assert thin_flow["provided_arguments"]["thin_loop_inputs"] == "<generated_input_bundle>"
        assert data["safety_boundary"]["does_not_authorize_stable_promotion"] is True
        assert "stable promotion" in data["web_gpt_handoff_prompt"]

    def test_commander_widget_js_copy_action_reports_success_and_fallbacks(self) -> None:
        if shutil.which("node") is None:
            self.skipTest("node is required for commander widget behavior smoke")

        project = self.make_git_checkout()
        server = MCPPlanningBridgeServer(str(project), service_mode=False)
        widget_html = server._commander_widget_html()
        widget_script = widget_html.split("<script>", 1)[1].split("</script>", 1)[0]
        script_path = self.tmp_path / "commander-widget-copy-smoke.js"
        script_path.write_text(
            f"""
const assert = require("assert");
const vm = require("vm");

class Element {{
  constructor(tagName, id) {{
    this.tagName = tagName;
    this.id = id || "";
    this.children = [];
    this.listeners = {{}};
    this.className = "";
    this.type = "";
    this.title = "";
    this.disabled = false;
    this._textContent = "";
    this._innerHTML = "";
  }}
  appendChild(child) {{
    this.children.push(child);
    return child;
  }}
  addEventListener(name, fn) {{
    if (!this.listeners[name]) this.listeners[name] = [];
    this.listeners[name].push(fn);
  }}
  set textContent(value) {{
    this._textContent = value === undefined || value === null ? "" : String(value);
  }}
  get textContent() {{
    return this._textContent + this.children.map(function (child) {{ return child.textContent || ""; }}).join("");
  }}
  set innerHTML(value) {{
    this._innerHTML = value === undefined || value === null ? "" : String(value);
    if (this._innerHTML === "") this.children = [];
  }}
  get innerHTML() {{
    return this._innerHTML;
  }}
}}

const elements = {{}};
function byId(id) {{
  if (!elements[id]) elements[id] = new Element("div", id);
  return elements[id];
}}
function findByClass(root, className, out) {{
  out = out || [];
  if (!root) return out;
  const classes = String(root.className || "").split(/\\s+/);
  if (classes.indexOf(className) >= 0) out.push(root);
  (root.children || []).forEach(function (child) {{ findByClass(child, className, out); }});
  return out;
}}
function dispatch(name, event) {{
  (listeners[name] || []).forEach(function (fn) {{ fn(event); }});
}}
function copyButton() {{
  return findByClass(byId("recommended-actions"), "action-copy")[0];
}}
async function flushPromises() {{
  await Promise.resolve();
  await Promise.resolve();
}}

const listeners = {{}};
let copiedText = "";
global.document = {{
  getElementById: byId,
  createElement: function (tagName) {{ return new Element(tagName); }},
  querySelectorAll: function () {{ return []; }}
}};
global.navigator = {{}};
global.window = {{
  parent: {{
    postMessage: function () {{ throw new Error("copy path should not use bridge"); }}
  }},
  addEventListener: function (name, fn) {{
    if (!listeners[name]) listeners[name] = [];
    listeners[name].push(fn);
  }}
}};

vm.runInThisContext({json.dumps(widget_script)});

(async function () {{
  dispatch("openai:set_globals", {{
    detail: {{
      globals: {{
        toolOutput: {{
          source: "product_console_map",
          project_name: "demo-project",
          recommended_first_actions: [{{
            action_id: "copy_action",
            label: "Copy action",
            mode: "read",
            tool: "get_product_readiness_status",
            arguments: {{ project_name: "demo-project" }},
            runbook: "docs/runbook.md",
            required_scope: "mcp:read",
            action_fingerprint: "copy123",
            requires_explicit_confirmation: false,
            last_action_result: {{ status: "not_recorded" }},
            next_refresh_actions: []
          }}]
        }}
      }}
    }}
  }});

  assert(copyButton(), "copy button should exist");

  await copyButton().listeners.click[0]();
  let logText = byId("log").textContent;
  assert(logText.includes("Copy unavailable; payload below:"), logText);
  assert(logText.includes('"tool": "get_product_readiness_status"'), logText);
  assert(logText.includes('"action_fingerprint": "copy123"'), logText);

  navigator.clipboard = {{
    writeText: async function (value) {{
      copiedText = value;
    }}
  }};
  await copyButton().listeners.click[0]();
  await flushPromises();
  assert.strictEqual(byId("log").textContent, "Copied recommended action.");
  const copied = JSON.parse(copiedText);
  assert.strictEqual(copied.tool, "get_product_readiness_status");
  assert.deepStrictEqual(copied.arguments, {{ project_name: "demo-project" }});
  assert.strictEqual(copied.runbook, "docs/runbook.md");
  assert.strictEqual(copied.action_id, "copy_action");
  assert.strictEqual(copied.action_fingerprint, "copy123");
  assert.strictEqual(copied.mode, "read");
  assert.strictEqual(copied.required_scope, "mcp:read");
  assert.strictEqual(copied.requires_explicit_confirmation, false);

  navigator.clipboard = {{
    writeText: async function () {{
      throw new Error("clipboard denied");
    }}
  }};
  await copyButton().listeners.click[0]();
  await flushPromises();
  logText = byId("log").textContent;
  assert(logText.includes("Copy failed; payload below:"), logText);
  assert(logText.includes('"tool": "get_product_readiness_status"'), logText);
}})().catch(function (err) {{
  console.error(err && err.stack ? err.stack : err);
  process.exit(1);
}});
""",
            encoding="utf-8",
        )
        completed = subprocess.run(["node", str(script_path)], capture_output=True, text=True, check=False, timeout=15)
        assert completed.returncode == 0, completed.stdout + completed.stderr

    def test_commander_widget_js_copy_evidence_reports_success_and_fallbacks(self) -> None:
        if shutil.which("node") is None:
            self.skipTest("node is required for commander widget behavior smoke")

        project = self.make_git_checkout()
        server = MCPPlanningBridgeServer(str(project), service_mode=False)
        widget_html = server._commander_widget_html()
        widget_script = widget_html.split("<script>", 1)[1].split("</script>", 1)[0]
        script_path = self.tmp_path / "commander-widget-evidence-copy-smoke.js"
        script_path.write_text(
            f"""
const assert = require("assert");
const vm = require("vm");

class Element {{
  constructor(tagName, id) {{
    this.tagName = tagName;
    this.id = id || "";
    this.children = [];
    this.listeners = {{}};
    this.className = "";
    this.type = "";
    this.title = "";
    this.disabled = false;
    this._textContent = "";
    this._innerHTML = "";
  }}
  appendChild(child) {{
    this.children.push(child);
    return child;
  }}
  addEventListener(name, fn) {{
    if (!this.listeners[name]) this.listeners[name] = [];
    this.listeners[name].push(fn);
  }}
  set textContent(value) {{
    this._textContent = value === undefined || value === null ? "" : String(value);
  }}
  get textContent() {{
    return this._textContent + this.children.map(function (child) {{ return child.textContent || ""; }}).join("");
  }}
  set innerHTML(value) {{
    this._innerHTML = value === undefined || value === null ? "" : String(value);
    if (this._innerHTML === "") this.children = [];
  }}
  get innerHTML() {{
    return this._innerHTML;
  }}
}}

const elements = {{}};
function byId(id) {{
  if (!elements[id]) elements[id] = new Element("div", id);
  return elements[id];
}}
function findByClass(root, className, out) {{
  out = out || [];
  if (!root) return out;
  const classes = String(root.className || "").split(/\\s+/);
  if (classes.indexOf(className) >= 0) out.push(root);
  (root.children || []).forEach(function (child) {{ findByClass(child, className, out); }});
  return out;
}}
function dispatch(name, event) {{
  (listeners[name] || []).forEach(function (fn) {{ fn(event); }});
}}
function evidenceCopyButton() {{
  return findByClass(byId("submission-evidence"), "evidence-copy")[0];
}}
function evidenceCardCount() {{
  return findByClass(byId("submission-evidence"), "evidence-card").length;
}}
async function flushPromises() {{
  await Promise.resolve();
  await Promise.resolve();
}}

const listeners = {{}};
let copiedText = "";
global.document = {{
  getElementById: byId,
  createElement: function (tagName) {{ return new Element(tagName); }},
  querySelectorAll: function () {{ return []; }}
}};
global.navigator = {{}};
global.window = {{
  parent: {{
    postMessage: function () {{ throw new Error("evidence copy path should not use bridge"); }}
  }},
  addEventListener: function (name, fn) {{
    if (!listeners[name]) listeners[name] = [];
    listeners[name].push(fn);
  }}
}};

vm.runInThisContext({json.dumps(widget_script)});

(async function () {{
  dispatch("openai:set_globals", {{
    detail: {{
      globals: {{
        toolOutput: {{
          source: "release_submission_readiness",
          project_name: "demo-project",
          status: "needs_evidence",
          submission_evidence_entry_templates: [{{
            key: "connector_closeout",
            title: "Connector closeout",
            status: "missing",
            default_filename: "connector-closeout.md",
            default_path: "docs/submission/connector-closeout.md",
            content_prompt: "Summarize connector evidence.",
            required_sections: ["result", "evidence"],
            copyable_entry_shape: {{
              key: "connector_closeout",
              filename: "connector-closeout.md",
              content: "Operator-confirmed connector closeout evidence"
            }}
          }}]
        }}
      }}
    }}
  }});

  assert.strictEqual(evidenceCardCount(), 1, "one evidence card should render");
  assert(evidenceCopyButton(), "evidence copy button should exist");

  await evidenceCopyButton().listeners.click[0]();
  let logText = byId("log").textContent;
  assert(logText.includes("Copy unavailable; payload below:"), logText);
  assert(logText.includes('"key": "connector_closeout"'), logText);
  assert(logText.includes('"filename": "connector-closeout.md"'), logText);

  navigator.clipboard = {{
    writeText: async function (value) {{
      copiedText = value;
    }}
  }};
  await evidenceCopyButton().listeners.click[0]();
  await flushPromises();
  assert.strictEqual(byId("log").textContent, "Copied evidence entry shape.");
  const copied = JSON.parse(copiedText);
  assert.strictEqual(copied.key, "connector_closeout");
  assert.strictEqual(copied.filename, "connector-closeout.md");
  assert.strictEqual(copied.content, "Operator-confirmed connector closeout evidence");

  navigator.clipboard = {{
    writeText: async function () {{
      throw new Error("clipboard denied");
    }}
  }};
  await evidenceCopyButton().listeners.click[0]();
  await flushPromises();
  logText = byId("log").textContent;
  assert(logText.includes("Copy failed; payload below:"), logText);
  assert(logText.includes('"key": "connector_closeout"'), logText);

  navigator.clipboard = {{
    writeText: async function (value) {{
      copiedText = value;
    }}
  }};
  dispatch("openai:set_globals", {{
    detail: {{
      globals: {{
        toolOutput: {{
          source: "submission_evidence_fill_preview",
          project_name: "demo-project",
          status: "preview_ready",
          summary: "Prepared a read-only fill payload preview with 2 evidence entries.",
          copyable_tool_call: {{
            tool: "fill_submission_evidence_files",
            arguments: {{
              project_name: "demo-project",
              entries: [
                {{ key: "logo", filename: "logo.md", content: "<operator-confirmed evidence text>" }},
                {{ key: "screenshot", filename: "screenshot.md", content: "<operator-confirmed evidence text>" }}
              ],
              mark_ready: false
            }},
            required_scope: "mcp:commit",
            result_contract: {{
              refresh_after: [
                {{ tool: "get_release_submission_readiness", why: "Refresh submission evidence and manifest status." }},
                {{ tool: "get_product_console_map", why: "Refresh recommended actions after local submission evidence changes." }}
              ]
            }}
          }},
          operator_instructions: ["Review every entry before writing files."]
        }}
      }}
    }}
  }});
  assert.strictEqual(evidenceCardCount(), 2, "fill preview should render both evidence cards");
  await evidenceCopyButton().listeners.click[0]();
  await flushPromises();
  assert.strictEqual(byId("log").textContent, "Copied evidence tool call.");
  const copiedCall = JSON.parse(copiedText);
  assert.strictEqual(copiedCall.tool, "fill_submission_evidence_files");
  assert.strictEqual(copiedCall.arguments.project_name, "demo-project");
  assert.strictEqual(copiedCall.arguments.entries.length, 2);
  assert.strictEqual(copiedCall.arguments.entries[1].key, "screenshot");
  assert.strictEqual(copiedCall.arguments.mark_ready, false);
  assert.strictEqual(copiedCall.result_contract.refresh_after[0].tool, "get_release_submission_readiness");
  assert.strictEqual(copiedCall.result_contract.refresh_after[1].tool, "get_product_console_map");

  const revisionCall = {{
    tool: "manage_submission_evidence_revision",
    arguments: {{
      project_name: "demo-project",
      action: "preview",
      key: "logo",
      ref: "docs/submission/logo.md",
      content: "<operator-confirmed complete replacement evidence Markdown>"
    }},
    required_scope: "mcp:preview"
  }};
  dispatch("openai:set_globals", {{
    detail: {{ globals: {{ toolOutput: {{
      source: "submission_evidence_fill_preview",
      project_name: "demo-project",
      status: "content_review_required",
      summary: "Prepared a bounded evidence revision call.",
      copyable_tool_call: revisionCall,
      evidence_bundle: {{
        fill_plan: {{
          status: "evidence_content_review_required",
          why: "Revise unfinished evidence.",
          content_review_entries: [{{
            key: "logo",
            current_status: "review_required",
            refs: ["docs/submission/logo.md"],
            required_sections: ["asset_path", "dimensions", "review_notes"],
            file_states: [{{ ref: "docs/submission/logo.md", status: "review_required", reason_codes: ["DRAFT_CONTENT"] }}],
            revision_preview_calls: [revisionCall]
          }}]
        }}
      }}
    }} }} }}
  }});
  assert.strictEqual(evidenceCardCount(), 1, "content review should render a revision card");
  await evidenceCopyButton().listeners.click[0]();
  await flushPromises();
  assert.strictEqual(byId("log").textContent, "Copied bounded evidence revision preview call.");
  const copiedRevision = JSON.parse(copiedText);
  assert.strictEqual(copiedRevision.tool, "manage_submission_evidence_revision");
  assert.strictEqual(copiedRevision.arguments.action, "preview");
  assert.strictEqual(copiedRevision.arguments.ref, "docs/submission/logo.md");
  assert.strictEqual(copiedRevision.required_scope, "mcp:preview");
}})().catch(function (err) {{
  console.error(err && err.stack ? err.stack : err);
  process.exit(1);
}});
""",
            encoding="utf-8",
        )
        completed = subprocess.run(["node", str(script_path)], capture_output=True, text=True, check=False, timeout=15)
        assert completed.returncode == 0, completed.stdout + completed.stderr

    def test_commander_widget_js_renders_evidence_empty_progress_and_fill_plan(self) -> None:
        if shutil.which("node") is None:
            self.skipTest("node is required for commander widget behavior smoke")

        project = self.make_git_checkout()
        server = MCPPlanningBridgeServer(str(project), service_mode=False)
        widget_html = server._commander_widget_html()
        widget_script = widget_html.split("<script>", 1)[1].split("</script>", 1)[0]
        script_path = self.tmp_path / "commander-widget-evidence-states-smoke.js"
        script_path.write_text(
            f"""
const assert = require("assert");
const vm = require("vm");

class Element {{
  constructor(tagName, id) {{
    this.tagName = tagName;
    this.id = id || "";
    this.children = [];
    this.listeners = {{}};
    this.className = "";
    this.type = "";
    this.title = "";
    this.disabled = false;
    this._textContent = "";
    this._innerHTML = "";
  }}
  appendChild(child) {{
    this.children.push(child);
    return child;
  }}
  addEventListener(name, fn) {{
    if (!this.listeners[name]) this.listeners[name] = [];
    this.listeners[name].push(fn);
  }}
  set textContent(value) {{
    this._textContent = value === undefined || value === null ? "" : String(value);
  }}
  get textContent() {{
    return this._textContent + this.children.map(function (child) {{ return child.textContent || ""; }}).join("");
  }}
  set innerHTML(value) {{
    this._innerHTML = value === undefined || value === null ? "" : String(value);
    if (this._innerHTML === "") this.children = [];
  }}
  get innerHTML() {{
    return this._innerHTML;
  }}
}}

const elements = {{}};
function byId(id) {{
  if (!elements[id]) elements[id] = new Element("div", id);
  return elements[id];
}}
function findByClass(root, className, out) {{
  out = out || [];
  if (!root) return out;
  const classes = String(root.className || "").split(/\\s+/);
  if (classes.indexOf(className) >= 0) out.push(root);
  (root.children || []).forEach(function (child) {{ findByClass(child, className, out); }});
  return out;
}}
function dispatchToolOutput(toolOutput) {{
  (listeners["openai:set_globals"] || []).forEach(function (fn) {{
    fn({{ detail: {{ globals: {{ toolOutput: toolOutput }} }} }});
  }});
}}
function evidenceCards() {{
  return findByClass(byId("submission-evidence"), "evidence-card");
}}
function notes() {{
  return findByClass(byId("submission-evidence"), "note");
}}
function evidenceText(className) {{
  return findByClass(byId("submission-evidence"), className)
    .map(function (node) {{ return node.textContent; }})
    .join("\\n");
}}
function evidenceRefreshButtons() {{
  return findByClass(byId("submission-evidence"), "evidence-refresh");
}}
function evidenceRecoveryButtons() {{
  return findByClass(byId("submission-evidence"), "evidence-recovery");
}}
function evidenceActivityText() {{
  return byId("submission-activity").textContent;
}}
function evidenceActivityCopyButton() {{
  return byId("submission-activity-copy");
}}
function evidenceActivityRecordButton() {{
  return byId("submission-activity-record");
}}
function evidenceActivityRecordStatus() {{
  return byId("submission-activity-record-status").textContent;
}}
function closeoutGroupText() {{
  return byId("closeout-action-groups").textContent;
}}
function productCompletionCategoryText() {{
  return byId("product-completion-categories").textContent;
}}
function operatorSessionTrailText() {{
  return byId("operator-session-trail").textContent;
}}
function operatorSessionRecoveryCopyButton() {{
  return findByClass(byId("operator-session-trail"), "operator-session-recovery-copy")[0];
}}
function operatorSessionRecoveryRunButton() {{
  return findByClass(byId("operator-session-trail"), "operator-session-recovery-run")[0];
}}
function productCompletionFollowupRecordButton() {{
  return findByClass(byId("product-completion-categories"), "closeout-followup-record")[0];
}}
function productCompletionFollowupCopyButton() {{
  return findByClass(byId("product-completion-categories"), "closeout-followup-copy")[0];
}}
function productCompletionFollowupRefreshButton() {{
  return findByClass(byId("product-completion-categories"), "closeout-followup-refresh")[0];
}}
function closeoutFollowupRecordButton() {{
  return findByClass(byId("closeout-action-groups"), "closeout-followup-record")[0];
}}
function closeoutFollowupRefreshButton() {{
  return findByClass(byId("closeout-action-groups"), "closeout-followup-refresh")[0];
}}
function closeoutFollowupCopyButton() {{
  return findByClass(byId("closeout-action-groups"), "closeout-followup-copy")[0];
}}
function closeoutFollowupRunButton() {{
  return findByClass(byId("closeout-action-groups"), "closeout-followup-run")[0];
}}
async function flushPromises() {{
  await Promise.resolve();
  await Promise.resolve();
}}

const listeners = {{}};
const toolCalls = [];
let copiedText = "";
global.document = {{
  getElementById: byId,
  createElement: function (tagName) {{ return new Element(tagName); }},
  querySelectorAll: function () {{ return []; }}
}};
global.navigator = {{
  clipboard: {{
    writeText: async function (value) {{
      copiedText = value;
    }}
  }}
}};
global.window = {{
  openai: {{
    callTool: async function (name, args) {{
      toolCalls.push({{ name: name, args: args }});
      if (name === "record_product_console_action_result") {{
        assert.strictEqual(args.action_id, "submission_evidence_activity");
        assert.strictEqual(args.tool, "submission_evidence_activity_summary");
        assert.strictEqual(args.mode, "read");
        assert.strictEqual(args.status, "updated");
        assert.strictEqual(args.result_ok, true);
        assert(args.message.includes("Submission evidence activity"), args.message);
        assert(args.message.includes("get_submission_evidence_fill_preview via direct call | refreshed"), args.message);
        return {{ structuredContent: {{ source: "product_console_action_results", status: "recorded" }} }};
      }}
      return {{
        structuredContent: {{
          source: name === "get_product_console_map" ? "product_console_map" : "release_submission_readiness",
          project_name: args.project_name,
          status: "refreshed",
          recommended_first_actions: []
        }}
      }};
    }}
  }},
  parent: {{
    postMessage: function () {{ throw new Error("evidence render path should not use bridge"); }}
  }},
  addEventListener: function (name, fn) {{
    if (!listeners[name]) listeners[name] = [];
    listeners[name].push(fn);
  }}
}};

vm.runInThisContext({json.dumps(widget_script)});

(async function () {{
  dispatchToolOutput({{
    source: "product_console_map",
    project_name: "demo-project",
    recommended_first_actions: [],
    completion_surface: {{
      status: "needs_attention",
      ready: false,
      summary: "Product console closeout needs attention: 1 gap(s) remain.",
      progress_state: {{
        source: "product_console_closeout_progress_state",
        status: "recorded_needs_review",
        label: "Recorded, Needs Review",
        severity: "needs_attention",
        completion_status: "needs_attention",
        ready: false,
        message: "Action evidence has been recorded; review remaining gaps before claiming closeout ready.",
        next_step: "Review remaining closeout gaps and follow the next Product Console action group.",
        operator_guidance: [
          "Recorded evidence is useful, but it is not the same as closeout ready.",
          "Resolve every remaining gap and refresh before accepting the closeout."
        ],
        recommended_action: {{
          tool: "get_product_console_map",
          required_scope: "mcp:read",
          why: "Re-read Product Console to inspect remaining closeout gaps."
        }},
        followup_count: 1,
        gap_count: 1,
        pending_refresh_count: 0,
        stored_result_count: 1,
        submission_evidence_activity_recorded: true
      }},
      product_completion_overview: {{
        source: "product_completion_overview",
        status: "needs_attention",
        ready: false,
        summary: "Product completion needs attention: 4/5 categories ready, 0 blocker category(s), 1 attention category(s).",
        ready_category_count: 4,
        total_category_count: 5,
        blocker_category_count: 0,
        needs_attention_category_count: 1,
        categories: [{{
          category_id: "submission_evidence_activity",
          component: "submission_evidence_activity",
          label: "Evidence Activity",
          status: "needs_attention",
          ready: false,
          severity: "needs_attention",
          gap_codes: ["SUBMISSION_EVIDENCE_ACTIVITY_NOT_RECORDED"],
          message: "Submission evidence activity has not been recorded after the latest refresh.",
          next_step: "Record the latest submission evidence activity after refresh/recovery actions.",
          display_order: 1,
          followup_position: 1,
          followup_item: {{
            item_id: "submission_evidence_activity",
            shared_by_component_count: 2
          }},
          primary_tool: "record_product_console_action_result",
          required_scope: "mcp:commit",
          gate_level: "explicit_apply_or_run_required"
        }}, {{
          category_id: "submission_evidence",
          component: "submission_evidence",
          label: "Submission Evidence",
          status: "needs_attention",
          ready: false,
          severity: "needs_attention",
          gap_codes: ["SUBMISSION_EVIDENCE_NOT_READY"],
          message: "Submission evidence is waiting on the shared follow-up.",
          next_step: "Use the shared Evidence Activity follow-up.",
          display_order: 2,
          followup_position: 1,
          followup_item: {{
            item_id: "submission_evidence_activity",
            shared_by_component_count: 2
          }},
          primary_tool: "record_product_console_action_result",
          required_scope: "mcp:commit",
          gate_level: "explicit_apply_or_run_required"
        }}, {{
          category_id: "product_readiness",
          component: "product_readiness",
          label: "Product Readiness",
          status: "ready",
          ready: true,
          severity: "ready",
          gap_codes: [],
          message: "Product readiness is complete.",
          next_step: "Keep this category green while resolving the remaining closeout gaps.",
          display_order: 2,
          has_followup: false
        }}],
        next_step: "Review remaining closeout gaps and follow the next Product Console action group."
      }},
      operator_session_trail: {{
        source: "product_console_operator_session_trail",
        status: "refresh_pending",
        summary: "Operator trail has 1 pending refresh action(s).",
        stored_result_count: 1,
        stale_result_count: 0,
        pending_refresh_count: 1,
        followup_count: 1,
        next_item: {{
          item_id: "submission_evidence_activity",
          label: "Evidence Activity",
          primary_tool: "record_product_console_action_result",
          required_scope: "mcp:commit"
        }},
        pending_refreshes: [{{
          tool: "get_product_console_map",
          after_result_status: "updated",
          source_action_key: "submission_evidence_activity|submission_evidence_activity_summary|read",
          why: "Refresh Product Console after recording evidence activity."
        }}],
        recent_events: [{{
          event_id: "latest_result",
          label: "Latest Result",
          status: "updated",
          tool: "submission_evidence_activity_summary",
          message: "Recorded recovery refreshed",
          observed_at: "2026-01-02T03:04:05Z"
        }}],
        recovery_action_count: 2,
        recovery_actions: [{{
          action_id: "operator_refresh_1",
          kind: "pending_refresh",
          label: "Refresh get_product_console_map",
          tool: "get_product_console_map",
          arguments: {{ project_name: "demo-project" }},
          mode: "read",
          required_scope: "mcp:read",
          gate_level: "read_only",
          can_run_now: true,
          copy_payload: {{
            tool: "get_product_console_map",
            arguments: {{ project_name: "demo-project" }},
            source_action_key: "submission_evidence_activity|submission_evidence_activity_summary|read",
            after_result_status: "updated"
          }}
        }}, {{
          action_id: "operator_followup_submission_evidence_activity",
          kind: "next_followup",
          label: "Follow Evidence Activity",
          tool: "record_product_console_action_result",
          arguments: {{
            action_id: "submission_evidence_activity",
            tool: "submission_evidence_activity_summary",
            mode: "read",
            status: "updated",
            message: "Submission evidence activity | get_submission_evidence_fill_preview via direct call | refreshed",
            result_ok: true
          }},
          required_scope: "mcp:commit",
          gate_level: "explicit_apply_or_run_required",
          can_run_now: false
        }}]
      }},
      gaps: [{{
        component: "submission_evidence_activity",
        status: "not_recorded",
        code: "SUBMISSION_EVIDENCE_ACTIVITY_NOT_RECORDED"
      }}],
      safe_next_action: {{
        action: "record_submission_evidence_activity",
        tool: "record_product_console_action_result",
        authority: "commit"
      }},
      action_groups: [{{
        group_id: "submission_evidence_activity",
        label: "Evidence Activity",
        status: "needs_attention",
        component: "submission_evidence_activity",
        gap_codes: ["SUBMISSION_EVIDENCE_ACTIVITY_NOT_RECORDED"],
        primary_action: {{
          action: "record_submission_evidence_activity",
          tool: "record_product_console_action_result",
          authority: "commit"
        }},
        action_refs: [],
        empty_state: "Record the latest submission evidence activity after refresh/recovery actions."
      }}, {{
        group_id: "submission_evidence",
        label: "Submission Evidence",
        status: "needs_attention",
        component: "submission_evidence",
        gap_codes: ["SUBMISSION_EVIDENCE_NOT_READY"],
        primary_action: {{
          action: "record_submission_evidence_activity",
          tool: "record_product_console_action_result",
          authority: "commit"
        }},
        action_refs: [],
        empty_state: "Use the shared Evidence Activity follow-up."
      }}],
      followup_queue: {{
        source: "product_console_closeout_followup_queue",
        status: "needs_attention",
        total_count: 1,
        next_item: {{
          item_id: "submission_evidence_activity",
          label: "Evidence Activity",
          status: "needs_attention",
          component: "submission_evidence_activity",
          gap_codes: ["SUBMISSION_EVIDENCE_ACTIVITY_NOT_RECORDED"],
          primary_tool: "record_product_console_action_result",
          required_scope: "mcp:commit",
          gate_level: "explicit_apply_or_run_required",
          primary_action: {{
            action: "record_submission_evidence_activity",
            tool: "record_product_console_action_result",
            arguments: {{
              action_id: "submission_evidence_activity",
              tool: "submission_evidence_activity_summary",
              mode: "read",
              status: "updated",
              message: "Submission evidence activity | get_submission_evidence_fill_preview via direct call | refreshed",
              result_ok: true
            }},
            authority: "commit"
          }}
        }},
        items: [{{
          item_id: "submission_evidence_activity",
          label: "Evidence Activity",
          status: "needs_attention",
          component: "submission_evidence_activity",
          components: ["submission_evidence_activity", "submission_evidence"],
          shared_by_component_count: 2,
          position: 1,
          gap_codes: ["SUBMISSION_EVIDENCE_ACTIVITY_NOT_RECORDED"],
          primary_tool: "record_product_console_action_result",
          required_scope: "mcp:commit",
          gate_level: "explicit_apply_or_run_required",
          primary_action: {{
            action: "record_submission_evidence_activity",
            tool: "record_product_console_action_result",
            arguments: {{
              action_id: "submission_evidence_activity",
              tool: "submission_evidence_activity_summary",
              mode: "read",
              status: "updated",
              message: "Submission evidence activity | get_submission_evidence_fill_preview via direct call | refreshed",
              result_ok: true
            }},
            authority: "commit"
          }}
        }}]
      }}
    }},
    action_result_state: {{
      submission_evidence_activity: {{
        available: true,
        status: "updated",
        message: "Recorded recovery refreshed",
        observed_at: "2026-01-02T03:04:05Z"
      }}
    }}
  }});
  assert.strictEqual(evidenceCards().length, 0, "empty state should not render evidence cards");
  assert.strictEqual(notes().length, 1, "empty state should render one note");
  assert(notes()[0].textContent.includes("No evidence progress yet"), notes()[0].textContent);
  assert.strictEqual(byId("submission-status").textContent, "-");
  assert.strictEqual(byId("submission-blockers").textContent, "none");
  assert(evidenceActivityText().includes("recorded | updated | Recorded recovery refreshed | 2026-01-02T03:04:05Z"), evidenceActivityText());
  assert.strictEqual(evidenceActivityRecordButton().disabled, false);
  assert(byId("closeout-status").textContent.includes("needs_attention"), byId("closeout-status").textContent);
  assert(byId("closeout-status").textContent.includes("4/5 categories ready"), byId("closeout-status").textContent);
  assert(byId("closeout-status").textContent.includes("Recorded, Needs Review"), byId("closeout-status").textContent);
  assert(byId("closeout-status").textContent.includes("Review remaining closeout gaps"), byId("closeout-status").textContent);
  assert(byId("closeout-gaps").textContent.includes("submission_evidence_activity | not_recorded | SUBMISSION_EVIDENCE_ACTIVITY_NOT_RECORDED"), byId("closeout-gaps").textContent);
  assert.strictEqual(byId("closeout-next").textContent, "record_submission_evidence_activity | record_product_console_action_result | commit");
  assert(operatorSessionTrailText().includes("Operator Trail | refresh_pending"), operatorSessionTrailText());
  assert(operatorSessionTrailText().includes("refresh 1"), operatorSessionTrailText());
  assert(operatorSessionTrailText().includes("records 1"), operatorSessionTrailText());
  assert(operatorSessionTrailText().includes("Latest Result updated submission_evidence_activity_summary"), operatorSessionTrailText());
  assert(operatorSessionTrailText().includes("next Evidence Activity"), operatorSessionTrailText());
  assert(operatorSessionRecoveryCopyButton(), "operator recovery copy should render");
  assert(operatorSessionRecoveryRunButton(), "operator recovery run should render");
  assert.strictEqual(operatorSessionRecoveryRunButton().disabled, false);
  const operatorRecoveryRun = operatorSessionRecoveryRunButton();
  assert(productCompletionCategoryText().includes("Product Readiness | ready"), productCompletionCategoryText());
  assert(productCompletionCategoryText().includes("Evidence Activity | needs_attention"), productCompletionCategoryText());
  assert(productCompletionCategoryText().includes("gaps 1"), productCompletionCategoryText());
  assert(productCompletionCategoryText().includes("record_product_console_action_result"), productCompletionCategoryText());
  assert(productCompletionCategoryText().includes("mcp:commit"), productCompletionCategoryText());
  assert(productCompletionCategoryText().includes("followup 1"), productCompletionCategoryText());
  assert(productCompletionCategoryText().includes("shared action 2"), productCompletionCategoryText());
  assert(productCompletionCategoryText().includes("Record the latest submission evidence activity"), productCompletionCategoryText());
  assert(productCompletionFollowupCopyButton(), "product completion category copy should render");
  assert(productCompletionFollowupRecordButton(), "product completion category record should render");
  assert(productCompletionFollowupRefreshButton(), "product completion category refresh should render");
  assert.strictEqual(
    findByClass(byId("product-completion-categories"), "closeout-followup-copy").length,
    2,
    "both categories covered by a shared queue item must expose its controls"
  );
  assert(closeoutGroupText().includes("Evidence Activity | needs_attention"), closeoutGroupText());
  assert(closeoutGroupText().includes("gaps 1"), closeoutGroupText());
  assert(closeoutGroupText().includes("followup 1"), closeoutGroupText());
  assert(closeoutGroupText().includes("shared action 2"), closeoutGroupText());
  assert(closeoutGroupText().includes("record_submission_evidence_activity | record_product_console_action_result | commit"), closeoutGroupText());
  assert(closeoutGroupText().includes("Record the latest submission evidence activity"), closeoutGroupText());
  assert(closeoutGroupText().includes("Confirm required"), closeoutGroupText());
  assert(closeoutGroupText().includes("Record"), closeoutGroupText());
  assert(closeoutFollowupCopyButton(), "closeout follow-up copy should render");
  assert(closeoutFollowupRecordButton(), "closeout follow-up record should render");
  assert(closeoutFollowupRefreshButton(), "closeout follow-up refresh should render");
  assert.strictEqual(
    findByClass(byId("closeout-action-groups"), "closeout-followup-copy").length,
    2,
    "both action groups covered by a shared queue item must expose its controls"
  );

  operatorSessionRecoveryCopyButton().listeners.click[0]();
  await flushPromises();
  const operatorRecoveryCopyPayload = copiedText || byId("log").textContent;
  assert(operatorRecoveryCopyPayload.includes('"tool": "get_product_console_map"'), operatorRecoveryCopyPayload);

  closeoutFollowupCopyButton().listeners.click[0]();
  await flushPromises();
  const closeoutCopyPayload = copiedText || byId("log").textContent;
  assert(closeoutCopyPayload.includes('"item_id": "submission_evidence_activity"'), closeoutCopyPayload);
  assert(closeoutCopyPayload.includes('"tool": "record_product_console_action_result"'), closeoutCopyPayload);

  await closeoutFollowupRecordButton().listeners.click[0]();
  assert.deepStrictEqual(toolCalls.map(function (call) {{ return call.name; }}), [
    "record_product_console_action_result",
    "get_product_console_map"
  ]);
  toolCalls.length = 0;

  await operatorRecoveryRun.listeners.click[0]();
  assert.strictEqual(toolCalls[0].name, "get_product_console_map");
  toolCalls.length = 0;

  dispatchToolOutput({{
    source: "product_console_map",
    project_name: "demo-project",
    completion_surface: {{
      status: "blocked",
      ready: false,
      summary: "Product console closeout needs attention: 1 gap(s) remain.",
      gaps: [{{
        component: "product_readiness",
        status: "blocked",
        code: "PRODUCT_READINESS_NOT_READY"
      }}],
      safe_next_action: {{
        action: "read_product_readiness",
        tool: "get_product_readiness_status",
        authority: "read_only"
      }},
      action_groups: [{{
        group_id: "product_readiness",
        label: "Product Readiness",
        status: "blocked",
        component: "product_readiness",
        gap_codes: ["PRODUCT_READINESS_NOT_READY"],
        primary_action: {{
          action: "read_product_readiness",
          tool: "get_product_readiness_status",
          authority: "read_only"
        }},
        action_refs: [],
        empty_state: "Read product readiness before continuing."
      }}],
      followup_queue: {{
        source: "product_console_closeout_followup_queue",
        status: "blocked",
        total_count: 1,
        next_item: {{
          item_id: "product_readiness",
          label: "Product Readiness",
          status: "blocked",
          component: "product_readiness",
          gap_codes: ["PRODUCT_READINESS_NOT_READY"],
          primary_tool: "get_product_readiness_status",
          required_scope: "mcp:read",
          gate_level: "read_only",
          primary_action: {{
            action: "read_product_readiness",
            tool: "get_product_readiness_status",
            arguments: {{ project_name: "demo-project" }},
            authority: "read_only"
          }}
        }}
      }}
    }}
  }});
  assert(closeoutFollowupRunButton(), "read-only closeout follow-up run should render");
  assert.strictEqual(closeoutFollowupRunButton().disabled, false);
  await closeoutFollowupRunButton().listeners.click[0]();
  assert.deepStrictEqual(toolCalls.map(function (call) {{ return call.name; }}), [
    "get_product_readiness_status"
  ]);
  assert.deepStrictEqual(toolCalls[0].args, {{ project_name: "demo-project" }});
  toolCalls.length = 0;

  dispatchToolOutput({{
    source: "release_submission_readiness",
    project_name: "demo-project",
    status: "needs_evidence",
    submission_materials: {{
      evidence_progress: {{
        complete_count: 1,
        total_count: 3,
        counts: {{ needs_attention: 2, placeholder: 1 }},
        rows: [{{
          key: "connector_closeout",
          status: "needs_attention",
          default_path: "docs/submission/connector-closeout.md",
          template: {{
            title: "Connector closeout",
            content_prompt: "Summarize connector evidence.",
            required_sections: ["result", "evidence"],
            copyable_entry_shape: {{
              key: "connector_closeout",
              filename: "connector-closeout.md",
              content: "operator evidence"
            }}
          }}
        }}]
      }}
    }}
  }});
  assert.strictEqual(byId("submission-status").textContent, "needs_evidence");
  assert.strictEqual(byId("submission-blockers").textContent, "ready 1/3 | attention 2 | placeholder 1");
  assert.strictEqual(evidenceCards().length, 1, "progress row should render one evidence card");
  assert(evidenceText("evidence-title").includes("Connector closeout | needs_attention"), evidenceText("evidence-title"));
  assert(evidenceText("evidence-path").includes("docs/submission/connector-closeout.md"), evidenceText("evidence-path"));
  assert(evidenceText("evidence-purpose").includes("Summarize connector evidence."), evidenceText("evidence-purpose"));
  assert(evidenceText("evidence-tag").includes("result"), evidenceText("evidence-tag"));

  dispatchToolOutput({{
    source: "product_console_map",
    project_name: "demo-project",
    release_submission_evidence_bundle: {{
      progress_summary: {{
        complete_count: 0,
        total_count: 2,
        counts: {{ needs_attention: 1, placeholder: 1 }}
      }},
      fill_plan: {{
        status: "draft_ready",
        why: "prepare evidence draft",
        draft_entries: [{{
          key: "submission_summary",
          current_status: "draft",
          default_path: "docs/submission/summary.md",
          filename: "summary.md",
          purpose: "Explain submission status.",
          required_sections: ["status"],
          copyable_entry_shape: {{
            key: "submission_summary",
            filename: "summary.md",
            content: "draft submission summary"
          }}
        }}]
      }}
    }}
  }});
  assert.strictEqual(byId("submission-blockers").textContent, "plan draft_ready | ready 0/2 | attention 1 | placeholder 1");
  assert.strictEqual(byId("closeout-status").textContent, "-");
  assert(closeoutGroupText().includes("Read Product Console to load closeout action groups."), closeoutGroupText());
  assert.strictEqual(evidenceCards().length, 1, "fill plan should replace progress-row cards");
  assert(evidenceText("evidence-title").includes("submission_summary | draft"), evidenceText("evidence-title"));
  assert(evidenceText("evidence-path").includes("docs/submission/summary.md"), evidenceText("evidence-path"));
  assert(evidenceText("evidence-purpose").includes("Explain submission status."), evidenceText("evidence-purpose"));
  assert(evidenceText("evidence-tag").includes("status"), evidenceText("evidence-tag"));

  dispatchToolOutput({{
    source: "product_console_map",
    project_name: "demo-project",
    release_submission_evidence_bundle: {{
      progress_summary: {{
        complete_count: 0,
        total_count: 1,
        counts: {{ needs_attention: 0, placeholder: 0, review_required: 1 }}
      }},
      fill_plan: {{
        status: "evidence_content_review_required",
        why: "Edit unfinished evidence before marking ready.",
        content_review_entries: [{{
          key: "logo",
          current_status: "review_required",
          refs: ["docs/submission/logo.md"],
          required_sections: ["asset_path"],
          file_states: [{{
            ref: "docs/submission/logo.md",
            status: "review_required",
            reason_codes: ["DRAFT_CONTENT", "HUMAN_REVIEW_PENDING"]
          }}]
        }}]
      }}
    }}
  }});
  assert.strictEqual(
    byId("submission-blockers").textContent,
    "plan evidence_content_review_required | ready 0/1 | attention 0 | placeholder 0 | review 1"
  );
  assert.strictEqual(evidenceCards().length, 1, "content review plan should render the blocked evidence file");
  assert(evidenceText("evidence-title").includes("logo | review_required"), evidenceText("evidence-title"));
  assert(evidenceText("evidence-path").includes("docs/submission/logo.md"), evidenceText("evidence-path"));
  assert(evidenceText("evidence-tag").includes("DRAFT_CONTENT"), evidenceText("evidence-tag"));
  assert(evidenceText("evidence-tag").includes("HUMAN_REVIEW_PENDING"), evidenceText("evidence-tag"));

  dispatchToolOutput({{
    source: "product_console_map",
    project_name: "demo-project",
    recommended_first_actions: [{{
      action_id: "read_submission_context",
      label: "Read submission context",
      mode: "read",
      tool: "get_release_readiness",
      arguments: {{ project_name: "demo-project" }},
      evidence_context: {{
        entry_templates: [{{
          key: "action_attached_evidence",
          title: "Action attached evidence",
          status: "suggested",
          default_filename: "action-attached.md",
          default_path: "docs/submission/action-attached.md",
          purpose: "Capture evidence attached to the recommended action.",
          required_sections: ["observation", "decision"],
          copyable_entry_shape: {{
            key: "action_attached_evidence",
            filename: "action-attached.md",
            content: "operator action evidence"
          }}
        }}]
      }}
    }}]
  }});
  assert.strictEqual(byId("submission-blockers").textContent, "none");
  assert.strictEqual(evidenceCards().length, 1, "recommended action evidence context should render one evidence card");
  assert(evidenceText("evidence-title").includes("Action attached evidence | suggested"), evidenceText("evidence-title"));
  assert(evidenceText("evidence-path").includes("docs/submission/action-attached.md"), evidenceText("evidence-path"));
  assert(evidenceText("evidence-purpose").includes("Capture evidence attached to the recommended action."), evidenceText("evidence-purpose"));
  assert(evidenceText("evidence-tag").includes("observation"), evidenceText("evidence-tag"));
  assert(evidenceText("evidence-tag").includes("decision"), evidenceText("evidence-tag"));

  dispatchToolOutput({{
    source: "submission_evidence_fill_preview",
    project_name: "demo-project",
    status: "preview_ready",
    summary: "Prepared a read-only fill payload preview with 1 evidence entries.",
    copyable_tool_call: {{
      tool: "fill_submission_evidence_files",
      arguments: {{
        project_name: "demo-project",
        entries: [{{
          key: "logo",
          filename: "logo.md",
          content: "<operator-confirmed evidence text>"
        }}],
        mark_ready: false
      }},
      result_contract: {{
        refresh_after: [
          {{ tool: "get_release_submission_readiness", why: "Refresh submission evidence and manifest status." }},
          {{ tool: "get_product_console_map", why: "Refresh recommended actions after local submission evidence changes." }}
        ]
      }}
    }},
    operator_instructions: ["Review every entry before writing files."]
  }});
  assert.strictEqual(byId("submission-status").textContent, "preview_ready");
  assert.strictEqual(byId("submission-blockers").textContent, "preview preview_ready | tool fill_submission_evidence_files | entries 1");
  assert.strictEqual(evidenceCards().length, 1, "fill preview entries should render one evidence card");
  assert.strictEqual(evidenceRefreshButtons().length, 2, "fill preview should render post-execution refresh buttons");
  assert(evidenceText("evidence-title").includes("logo | preview_ready"), evidenceText("evidence-title"));
  assert(evidenceText("evidence-path").includes("logo.md"), evidenceText("evidence-path"));
  assert(evidenceText("evidence-purpose").includes("Prepared a read-only fill payload preview"), evidenceText("evidence-purpose"));
  assert(evidenceText("evidence-tag").includes("Review every entry before writing files."), evidenceText("evidence-tag"));
  await evidenceRefreshButtons()[0].listeners.click[0]();
  await flushPromises();
  assert.strictEqual(toolCalls[0].name, "get_release_submission_readiness");
  assert.deepStrictEqual(toolCalls[0].args, {{ project_name: "demo-project" }});
  assert(evidenceActivityText().includes("refresh | updated | get_release_submission_readiness via direct call | refreshed"), evidenceActivityText());

  dispatchToolOutput({{
    source: "submission_evidence_fill_preview",
    project_name: "demo-project",
    status: "review_ready",
    summary: "Prepared a read-only ready-field marking payload for human-reviewed evidence.",
    copyable_tool_call: {{
      tool: "mark_submission_evidence_ready_fields",
      arguments: {{
        project_name: "demo-project",
        keys: ["logo"],
        review_confirmation: "human_reviewed"
      }},
      result_contract: {{
        refresh_after: [
          {{ tool: "get_release_submission_readiness", why: "Refresh submission evidence and manifest status." }},
          {{ tool: "get_product_console_map", why: "Refresh recommended actions after local submission evidence changes." }}
        ]
      }}
    }},
    evidence_bundle: {{
      fill_plan: {{
        review_entries: [{{
          key: "logo",
          refs: ["docs/submission/logo.md"],
          current_status: "filled_not_marked_ready"
        }}]
      }}
    }},
    operator_instructions: ["Use review_confirmation=human_reviewed only after review."]
  }});
  assert.strictEqual(byId("submission-status").textContent, "review_ready");
  assert.strictEqual(byId("submission-blockers").textContent, "preview review_ready | tool mark_submission_evidence_ready_fields | keys 1");
  assert.strictEqual(evidenceCards().length, 1, "mark-ready preview keys should render one evidence card");
  assert.strictEqual(evidenceRefreshButtons().length, 2, "mark-ready preview should render post-execution refresh buttons");
  assert(evidenceText("evidence-title").includes("logo | review_ready"), evidenceText("evidence-title"));
  assert(evidenceText("evidence-path").includes("docs/submission/logo.md"), evidenceText("evidence-path"));
  assert(evidenceText("evidence-purpose").includes("ready-field marking payload"), evidenceText("evidence-purpose"));
  assert(evidenceText("evidence-tag").includes("human_reviewed"), evidenceText("evidence-tag"));

  dispatchToolOutput({{
    source: "submission_evidence_fill_preview",
    project_name: "demo-project",
    status: "content_review_required",
    summary: "Unfinished evidence blocks mark-ready.",
    copyable_tool_call: {{
      tool: "manage_submission_evidence_revision",
      arguments: {{
        project_name: "demo-project",
        action: "preview",
        key: "logo",
        ref: "docs/submission/logo.md",
        content: "<operator-confirmed complete replacement evidence Markdown>"
      }},
      required_scope: "mcp:preview"
    }},
    evidence_bundle: {{
      fill_plan: {{
        status: "evidence_content_review_required",
        why: "Edit unfinished evidence before marking ready.",
        content_review_entries: [{{
          key: "logo",
          current_status: "review_required",
          refs: ["docs/submission/logo.md"],
          required_sections: ["asset_path"],
          file_states: [{{
            ref: "docs/submission/logo.md",
            status: "review_required",
            reason_codes: ["DRAFT_CONTENT", "HUMAN_REVIEW_PENDING"]
          }}]
        }}]
      }}
    }},
    operator_instructions: ["Edit the referenced file before refreshing readiness."]
  }});
  assert.strictEqual(byId("submission-status").textContent, "content_review_required");
  assert.strictEqual(
    byId("submission-blockers").textContent,
    "preview content_review_required | tool manage_submission_evidence_revision"
  );
  assert.strictEqual(evidenceCards().length, 1, "content-review preview should render the nested evidence entry");
  assert(evidenceText("evidence-title").includes("logo | review_required"), evidenceText("evidence-title"));
  assert(evidenceText("evidence-path").includes("docs/submission/logo.md"), evidenceText("evidence-path"));
  assert(evidenceText("evidence-tag").includes("DRAFT_CONTENT"), evidenceText("evidence-tag"));
  assert(evidenceText("evidence-tag").includes("HUMAN_REVIEW_PENDING"), evidenceText("evidence-tag"));

  dispatchToolOutput({{
    source: "submission_evidence_fill",
    project_name: "demo-project",
    ok: false,
    status: "failed",
    error_code: "SUBMISSION_EVIDENCE_INPUT_INVALID",
    safe_recovery_actions: [
      {{
        tool: "get_release_submission_readiness",
        arguments: {{}},
        required_scope: "mcp:read",
        side_effects: false,
        why: "Refresh current submission evidence status before retrying."
      }},
      {{
        tool: "get_submission_evidence_fill_preview",
        arguments: {{ selected_keys: ["logo"] }},
        required_scope: "mcp:read",
        side_effects: false,
        why: "Regenerate the bounded fill payload."
      }}
    ]
  }});
  assert.strictEqual(byId("submission-status").textContent, "failed");
  assert.strictEqual(byId("submission-blockers").textContent, "failed SUBMISSION_EVIDENCE_INPUT_INVALID | recovery actions 2");
  assert(evidenceActivityText().includes("result | failed | SUBMISSION_EVIDENCE_INPUT_INVALID"), evidenceActivityText());
  assert.strictEqual(evidenceRecoveryButtons().length, 2, "failed commit result should render safe recovery buttons");
  assert.strictEqual(evidenceRecoveryButtons()[1].textContent, "get_submission_evidence_fill_preview");
  await evidenceRecoveryButtons()[1].listeners.click[0]();
  await flushPromises();
  const recoveryCall = toolCalls[toolCalls.length - 1];
  assert.strictEqual(recoveryCall.name, "get_submission_evidence_fill_preview");
  assert.deepStrictEqual(recoveryCall.args, {{ selected_keys: ["logo"], project_name: "demo-project" }});
  assert.strictEqual(evidenceRecoveryButtons().length, 0, "successful refresh should clear stale recovery actions");
  assert(evidenceActivityText().includes("recovery | updated | get_submission_evidence_fill_preview via direct call | refreshed"), evidenceActivityText());
  assert(!evidenceActivityText().includes("SUBMISSION_EVIDENCE_INPUT_INVALID"), evidenceActivityText());
  await evidenceActivityCopyButton().listeners.click[0]();
  await flushPromises();
  const activityLog = byId("log").textContent;
  const activityPayload = copiedText || activityLog.split("payload below:\\n", 2)[1];
  assert(activityLog === "Copied evidence activity summary." || activityLog.includes("payload below:"), activityLog);
  const activitySummary = JSON.parse(activityPayload);
  assert.strictEqual(activitySummary.source, "submission_evidence_activity_summary");
  assert.strictEqual(activitySummary.project_name, "demo-project");
  assert.strictEqual(activitySummary.submission_status, "refreshed");
  assert(activitySummary.rows.some(function (row) {{
    return row.includes("recovery | updated | get_submission_evidence_fill_preview via direct call | refreshed");
  }}), JSON.stringify(activitySummary.rows));
  assert.strictEqual(activitySummary.authority_boundary.read_only_summary, true);
  assert.strictEqual(activitySummary.authority_boundary.does_not_write_files, true);
  assert.strictEqual(activitySummary.authority_boundary.does_not_mark_ready_fields, true);
  assert.strictEqual(evidenceActivityRecordButton().disabled, false);
  await evidenceActivityRecordButton().listeners.click[0]();
  await flushPromises();
  assert.deepStrictEqual(toolCalls.slice(-2).map(function (call) {{ return call.name; }}), [
    "record_product_console_action_result",
    "get_product_console_map"
  ]);
  assert.strictEqual(evidenceActivityRecordButton().disabled, true);
  assert(evidenceActivityRecordStatus().includes("recorded | refresh current"), evidenceActivityRecordStatus());

  dispatchToolOutput({{
    source: "apps_connector_smoke_packet",
    project_name: "demo-project",
    action_result_state: {{
      submission_evidence_activity: {{ available: false }}
    }},
    apps_connector_closeout: {{
      release_submission_evidence: {{
        status: "ready",
        ready: true,
        evidence_progress: {{
          complete_count: 3,
          total_count: 3,
          counts: {{ needs_attention: 0, placeholder: 0 }}
        }},
        submission_evidence_activity: {{
          available: true,
          status: "updated",
          message: "Closeout evidence activity refreshed",
          observed_at: "2026-01-03T04:05:06Z",
          read_only_summary: true
        }}
      }}
    }}
  }});
  assert(evidenceActivityText().includes("closeout | updated | Closeout evidence activity refreshed | 2026-01-03T04:05:06Z"), evidenceActivityText());
}})().catch(function (err) {{
  console.error(err && err.stack ? err.stack : err);
  process.exit(1);
}});
""",
            encoding="utf-8",
        )
        completed = subprocess.run(["node", str(script_path)], capture_output=True, text=True, check=False, timeout=15)
        assert completed.returncode == 0, completed.stdout + completed.stderr

    def test_commander_widget_js_preserves_actions_and_updates_bridge_status(self) -> None:
        if shutil.which("node") is None:
            self.skipTest("node is required for commander widget behavior smoke")

        project = self.make_git_checkout()
        server = MCPPlanningBridgeServer(str(project), service_mode=False)
        widget_html = server._commander_widget_html()
        widget_script = widget_html.split("<script>", 1)[1].split("</script>", 1)[0]
        script_path = self.tmp_path / "commander-widget-behavior-smoke.js"
        script_path.write_text(
            f"""
const assert = require("assert");
const vm = require("vm");

class Element {{
  constructor(tagName, id) {{
    this.tagName = tagName;
    this.id = id || "";
    this.children = [];
    this.listeners = {{}};
    this.className = "";
    this.type = "";
    this.title = "";
    this.disabled = false;
    this._textContent = "";
    this._innerHTML = "";
  }}
  appendChild(child) {{
    this.children.push(child);
    return child;
  }}
  addEventListener(name, fn) {{
    if (!this.listeners[name]) this.listeners[name] = [];
    this.listeners[name].push(fn);
  }}
  set textContent(value) {{
    this._textContent = value === undefined || value === null ? "" : String(value);
  }}
  get textContent() {{
    return this._textContent + this.children.map(function (child) {{ return child.textContent || ""; }}).join("");
  }}
  set innerHTML(value) {{
    this._innerHTML = value === undefined || value === null ? "" : String(value);
    if (this._innerHTML === "") this.children = [];
  }}
  get innerHTML() {{
    return this._innerHTML;
  }}
}}

const elements = {{}};
function byId(id) {{
  if (!elements[id]) elements[id] = new Element("div", id);
  return elements[id];
}}
function findByClass(root, className, out) {{
  out = out || [];
  if (!root) return out;
  const classes = String(root.className || "").split(/\\s+/);
  if (classes.indexOf(className) >= 0) out.push(root);
  (root.children || []).forEach(function (child) {{ findByClass(child, className, out); }});
  return out;
}}
function dispatch(name, event) {{
  (listeners[name] || []).forEach(function (fn) {{ fn(event); }});
}}
function recommendedActionCount() {{
  return findByClass(byId("recommended-actions"), "recommended-action").length;
}}
function actionStatusText() {{
  return findByClass(byId("recommended-actions"), "action-run-status")
    .map(function (node) {{ return node.textContent; }})
    .join("\\n");
}}

const listeners = {{}};
const parentMessages = [];
global.document = {{
  getElementById: byId,
  createElement: function (tagName) {{ return new Element(tagName); }},
  querySelectorAll: function () {{ return []; }}
}};
global.navigator = {{}};
global.window = {{
  parent: {{
    postMessage: function (message) {{ parentMessages.push(message); }}
  }},
  addEventListener: function (name, fn) {{
    if (!listeners[name]) listeners[name] = [];
    listeners[name].push(fn);
  }}
}};

vm.runInThisContext({json.dumps(widget_script)});

(async function () {{
  const consoleMap = {{
    source: "product_console_map",
    project_name: "demo-project",
    recommended_first_actions: [{{
      action_id: "readiness_check",
      label: "Read readiness",
      mode: "read",
      tool: "get_product_readiness_status",
      arguments: {{ project_name: "demo-project" }},
      required_scope: "mcp:read",
      action_fingerprint: "abc123",
      last_action_result: {{ status: "not_recorded" }},
      next_refresh_actions: [],
      evidence_context: {{
        key: "logo",
        refs: ["docs/submission/logo.md"],
        required_sections: ["asset_path", "dimensions"],
        human_review_required: true,
        content_review_required: true,
        mark_ready_blocked: true,
        unfinished_reason_codes: ["DRAFT_CONTENT"],
        review_sequence_position: 1,
        review_sequence_total: 2,
        marks_only_this_key: true
      }}
    }}]
  }};

  dispatch("openai:set_globals", {{ detail: {{ globals: {{ toolOutput: consoleMap }} }} }});
  assert.strictEqual(recommendedActionCount(), 1, "console map should render one action");
  const reviewContext = findByClass(byId("recommended-actions"), "recommended-action-review-context")[0];
  assert(reviewContext.textContent.includes("human review required"), reviewContext.textContent);
  assert(reviewContext.textContent.includes("key logo"), reviewContext.textContent);
  assert(reviewContext.textContent.includes("item 1/2"), reviewContext.textContent);
  assert(reviewContext.textContent.includes("file docs/submission/logo.md"), reviewContext.textContent);
  assert(reviewContext.textContent.includes("check dimensions"), reviewContext.textContent);
  assert(reviewContext.textContent.includes("blocked DRAFT_CONTENT"), reviewContext.textContent);
  assert(reviewContext.textContent.includes("mark ready blocked"), reviewContext.textContent);
  assert(reviewContext.textContent.includes("marks this key only"), reviewContext.textContent);

  dispatch("message", {{
    data: {{
      method: "ui/notifications/tool-result",
      params: {{
        id: "unmatched",
        structuredContent: {{ source: "product_console_action_results", status: "recorded" }}
      }}
    }}
  }});
  assert.strictEqual(recommendedActionCount(), 1, "record result must not drop console actions");

  const runButton = findByClass(byId("recommended-actions"), "action-run")[0];
  assert(runButton, "run button should exist");
  await runButton.listeners.click[0]();
  assert.strictEqual(parentMessages.length, 1, "bridge fallback should post one request");
  assert(actionStatusText().includes("requested"), "action should show requested after bridge post");

  dispatch("message", {{
    data: {{
      id: parentMessages[0].id,
      result: {{
        structuredContent: {{ source: "product_readiness", status: "ready", ready: true }}
      }}
    }}
  }});
  assert.strictEqual(recommendedActionCount(), 1, "bridge result must preserve console actions");
  const statusText = actionStatusText();
  assert(statusText.includes("updated"), statusText);
  assert(statusText.includes("get_product_readiness_status via bridge | ready"), statusText);
}})().catch(function (err) {{
  console.error(err && err.stack ? err.stack : err);
  process.exit(1);
}});
""",
            encoding="utf-8",
        )
        completed = subprocess.run(["node", str(script_path)], capture_output=True, text=True, check=False, timeout=15)
        assert completed.returncode == 0, completed.stdout + completed.stderr

    def test_commander_widget_js_marks_unanswered_bridge_calls_failed(self) -> None:
        if shutil.which("node") is None:
            self.skipTest("node is required for commander widget behavior smoke")

        project = self.make_git_checkout()
        server = MCPPlanningBridgeServer(str(project), service_mode=False)
        widget_html = server._commander_widget_html()
        widget_script = widget_html.split("<script>", 1)[1].split("</script>", 1)[0]
        script_path = self.tmp_path / "commander-widget-bridge-timeout-smoke.js"
        script_path.write_text(
            f"""
const assert = require("assert");
const vm = require("vm");

class Element {{
  constructor(tagName, id) {{
    this.tagName = tagName;
    this.id = id || "";
    this.children = [];
    this.listeners = {{}};
    this.className = "";
    this.type = "";
    this.title = "";
    this.disabled = false;
    this._textContent = "";
    this._innerHTML = "";
  }}
  appendChild(child) {{
    this.children.push(child);
    return child;
  }}
  addEventListener(name, fn) {{
    if (!this.listeners[name]) this.listeners[name] = [];
    this.listeners[name].push(fn);
  }}
  set textContent(value) {{
    this._textContent = value === undefined || value === null ? "" : String(value);
  }}
  get textContent() {{
    return this._textContent + this.children.map(function (child) {{ return child.textContent || ""; }}).join("");
  }}
  set innerHTML(value) {{
    this._innerHTML = value === undefined || value === null ? "" : String(value);
    if (this._innerHTML === "") this.children = [];
  }}
  get innerHTML() {{
    return this._innerHTML;
  }}
}}

const elements = {{}};
function byId(id) {{
  if (!elements[id]) elements[id] = new Element("div", id);
  return elements[id];
}}
function findByClass(root, className, out) {{
  out = out || [];
  if (!root) return out;
  const classes = String(root.className || "").split(/\\s+/);
  if (classes.indexOf(className) >= 0) out.push(root);
  (root.children || []).forEach(function (child) {{ findByClass(child, className, out); }});
  return out;
}}
function dispatch(name, event) {{
  (listeners[name] || []).forEach(function (fn) {{ fn(event); }});
}}
function recommendedActionCount() {{
  return findByClass(byId("recommended-actions"), "recommended-action").length;
}}
function actionStatusText() {{
  return findByClass(byId("recommended-actions"), "action-run-status")
    .map(function (node) {{ return node.textContent; }})
    .join("\\n");
}}
function runButton() {{
  return findByClass(byId("recommended-actions"), "action-run")[0];
}}

const listeners = {{}};
const parentMessages = [];
const timers = [];
global.document = {{
  getElementById: byId,
  createElement: function (tagName) {{ return new Element(tagName); }},
  querySelectorAll: function () {{ return []; }}
}};
global.navigator = {{}};
global.window = {{
  __colametaBridgeTimeoutMs: 5,
  parent: {{
    postMessage: function (message) {{ parentMessages.push(message); }}
  }},
  addEventListener: function (name, fn) {{
    if (!listeners[name]) listeners[name] = [];
    listeners[name].push(fn);
  }},
  setTimeout: function (fn, ms) {{
    timers.push({{ fn: fn, ms: ms, cleared: false }});
    return timers.length;
  }},
  clearTimeout: function (id) {{
    if (timers[id - 1]) timers[id - 1].cleared = true;
  }}
}};

vm.runInThisContext({json.dumps(widget_script)});

(async function () {{
  dispatch("openai:set_globals", {{
    detail: {{
      globals: {{
        toolOutput: {{
          source: "product_console_map",
          project_name: "demo-project",
          recommended_first_actions: [{{
            action_id: "readiness_check",
            label: "Read readiness",
            mode: "read",
            tool: "get_product_readiness_status",
            arguments: {{ project_name: "demo-project" }},
            required_scope: "mcp:read",
            action_fingerprint: "abc123",
            last_action_result: {{ status: "not_recorded" }},
            next_refresh_actions: []
          }}]
        }}
      }}
    }}
  }});

  assert.strictEqual(recommendedActionCount(), 1, "console map should render one action");
  assert(runButton(), "run button should exist");

  await runButton().listeners.click[0]();
  assert.strictEqual(parentMessages.length, 1, "bridge fallback should post one request");
  assert.strictEqual(timers.length, 1, "bridge fallback should arm one timeout");
  assert.strictEqual(timers[0].ms, 5);
  assert(actionStatusText().includes("requested"), "action should show requested before timeout");

  timers[0].fn();
  assert.strictEqual(recommendedActionCount(), 1, "timeout render must preserve console actions");
  let statusText = actionStatusText();
  assert(statusText.includes("failed"), statusText);
  assert(statusText.includes("get_product_readiness_status via bridge timeout"), statusText);
  assert.strictEqual(runButton().disabled, false, "failed action should remain retryable");

  dispatch("message", {{
    data: {{
      id: parentMessages[0].id,
      result: {{
        structuredContent: {{ source: "product_readiness", status: "ready", ready: true }}
      }}
    }}
  }});
  statusText = actionStatusText();
  assert(statusText.includes("failed"), statusText);
  assert(statusText.includes("bridge timeout"), statusText);
  assert(!statusText.includes("via bridge | ready"), statusText);

  await runButton().listeners.click[0]();
  assert.strictEqual(parentMessages.length, 2, "retry should post a second bridge request");
  assert.strictEqual(timers.length, 2, "retry should arm a second timeout");
  statusText = actionStatusText();
  assert(statusText.includes("requested"), statusText);
  assert(!statusText.includes("bridge timeout"), statusText);

  dispatch("message", {{
    data: {{
      id: parentMessages[1].id,
      result: {{
        structuredContent: {{ source: "product_readiness", status: "ready", ready: true }}
      }}
    }}
  }});
  statusText = actionStatusText();
  assert(statusText.includes("updated"), statusText);
  assert(statusText.includes("get_product_readiness_status via bridge | ready"), statusText);
  assert.strictEqual(timers[1].cleared, true, "successful retry should clear its timeout");

  timers[1].fn();
  statusText = actionStatusText();
  assert(statusText.includes("updated"), statusText);
  assert(!statusText.includes("bridge timeout"), statusText);
}})().catch(function (err) {{
  console.error(err && err.stack ? err.stack : err);
  process.exit(1);
}});
""",
            encoding="utf-8",
        )
        completed = subprocess.run(["node", str(script_path)], capture_output=True, text=True, check=False, timeout=15)
        assert completed.returncode == 0, completed.stdout + completed.stderr

    def test_commander_widget_js_runs_refresh_queue_and_reports_direct_failures(self) -> None:
        if shutil.which("node") is None:
            self.skipTest("node is required for commander widget behavior smoke")

        project = self.make_git_checkout()
        server = MCPPlanningBridgeServer(str(project), service_mode=False)
        widget_html = server._commander_widget_html()
        widget_script = widget_html.split("<script>", 1)[1].split("</script>", 1)[0]
        script_path = self.tmp_path / "commander-widget-refresh-smoke.js"
        script_path.write_text(
            f"""
const assert = require("assert");
const vm = require("vm");

class Element {{
  constructor(tagName, id) {{
    this.tagName = tagName;
    this.id = id || "";
    this.children = [];
    this.listeners = {{}};
    this.className = "";
    this.type = "";
    this.title = "";
    this.disabled = false;
    this._textContent = "";
    this._innerHTML = "";
  }}
  appendChild(child) {{
    this.children.push(child);
    return child;
  }}
  addEventListener(name, fn) {{
    if (!this.listeners[name]) this.listeners[name] = [];
    this.listeners[name].push(fn);
  }}
  set textContent(value) {{
    this._textContent = value === undefined || value === null ? "" : String(value);
  }}
  get textContent() {{
    return this._textContent + this.children.map(function (child) {{ return child.textContent || ""; }}).join("");
  }}
  set innerHTML(value) {{
    this._innerHTML = value === undefined || value === null ? "" : String(value);
    if (this._innerHTML === "") this.children = [];
  }}
  get innerHTML() {{
    return this._innerHTML;
  }}
}}

const elements = {{}};
function byId(id) {{
  if (!elements[id]) elements[id] = new Element("div", id);
  return elements[id];
}}
function findByClass(root, className, out) {{
  out = out || [];
  if (!root) return out;
  const classes = String(root.className || "").split(/\\s+/);
  if (classes.indexOf(className) >= 0) out.push(root);
  (root.children || []).forEach(function (child) {{ findByClass(child, className, out); }});
  return out;
}}
function dispatch(name, event) {{
  (listeners[name] || []).forEach(function (fn) {{ fn(event); }});
}}
function recommendedActionCount() {{
  return findByClass(byId("recommended-actions"), "recommended-action").length;
}}
function refreshButtons() {{
  return findByClass(byId("recommended-actions"), "action-refresh");
}}
function refreshStatusText() {{
  return findByClass(byId("recommended-actions"), "action-refresh-label")
    .map(function (node) {{ return node.textContent; }})
    .join("\\n");
}}

const listeners = {{}};
const calls = [];
global.document = {{
  getElementById: byId,
  createElement: function (tagName) {{ return new Element(tagName); }},
  querySelectorAll: function () {{ return []; }}
}};
global.navigator = {{}};
global.window = {{
  parent: {{
    postMessage: function () {{ throw new Error("direct path should not use bridge"); }}
  }},
  addEventListener: function (name, fn) {{
    if (!listeners[name]) listeners[name] = [];
    listeners[name].push(fn);
  }},
  openai: {{
    callTool: async function (name, args) {{
      calls.push({{ name, args }});
      assert.strictEqual(args.project_name, "demo-project");
      if (name === "get_runtime_version_status") {{
        return {{ structuredContent: {{ source: "runtime_version_status", status: "current" }} }};
      }}
      if (name === "get_connector_runtime_health_status") {{
        return {{ structuredContent: {{ source: "connector_runtime_health", status: "failed", ok: false, error: "probe failed" }} }};
      }}
      throw new Error("unexpected tool " + name);
    }}
  }}
}};

vm.runInThisContext({json.dumps(widget_script)});

(async function () {{
  dispatch("openai:set_globals", {{
    detail: {{
      globals: {{
        toolOutput: {{
          source: "product_console_map",
          project_name: "demo-project",
          recommended_first_actions: [{{
            action_id: "refresh_surface",
            label: "Refresh surfaces",
            mode: "read",
            tool: "get_product_readiness_status",
            arguments: {{ project_name: "demo-project" }},
            required_scope: "mcp:read",
            action_fingerprint: "refresh123",
            last_action_result: {{ status: "not_recorded" }},
            next_refresh_actions: [
              {{
                tool: "get_runtime_version_status",
                arguments: {{ project_name: "demo-project" }},
                why: "refresh runtime status"
              }},
              {{
                tool: "get_connector_runtime_health_status",
                arguments: {{ project_name: "demo-project" }},
                why: "refresh connector status"
              }}
            ]
          }}]
        }}
      }}
    }}
  }});

  assert.strictEqual(recommendedActionCount(), 1, "console map should render one action");
  assert.strictEqual(refreshButtons().length, 2, "refresh queue should render two buttons");

  await refreshButtons()[0].listeners.click[0]();
  assert.strictEqual(recommendedActionCount(), 1, "successful refresh must preserve console actions");
  let statusText = refreshStatusText();
  assert(statusText.includes("updated"), statusText);
  assert(statusText.includes("get_runtime_version_status via direct call | current"), statusText);

  await refreshButtons()[1].listeners.click[0]();
  assert.strictEqual(recommendedActionCount(), 1, "failed refresh must preserve console actions");
  statusText = refreshStatusText();
  assert(statusText.includes("failed"), statusText);
  assert(statusText.includes("get_connector_runtime_health_status via direct call | failed"), statusText);
  assert.deepStrictEqual(calls.map(function (call) {{ return call.name; }}), [
    "get_runtime_version_status",
    "get_connector_runtime_health_status"
  ]);
}})().catch(function (err) {{
  console.error(err && err.stack ? err.stack : err);
  process.exit(1);
}});
""",
            encoding="utf-8",
        )
        completed = subprocess.run(["node", str(script_path)], capture_output=True, text=True, check=False, timeout=15)
        assert completed.returncode == 0, completed.stdout + completed.stderr

    def test_commander_widget_js_records_failed_action_and_recovers_record_failure(self) -> None:
        if shutil.which("node") is None:
            self.skipTest("node is required for commander widget behavior smoke")

        project = self.make_git_checkout()
        server = MCPPlanningBridgeServer(str(project), service_mode=False)
        widget_html = server._commander_widget_html()
        widget_script = widget_html.split("<script>", 1)[1].split("</script>", 1)[0]
        script_path = self.tmp_path / "commander-widget-record-failure-smoke.js"
        script_path.write_text(
            f"""
const assert = require("assert");
const vm = require("vm");

class Element {{
  constructor(tagName, id) {{
    this.tagName = tagName;
    this.id = id || "";
    this.children = [];
    this.listeners = {{}};
    this.className = "";
    this.type = "";
    this.title = "";
    this.disabled = false;
    this._textContent = "";
    this._innerHTML = "";
  }}
  appendChild(child) {{
    this.children.push(child);
    return child;
  }}
  addEventListener(name, fn) {{
    if (!this.listeners[name]) this.listeners[name] = [];
    this.listeners[name].push(fn);
  }}
  set textContent(value) {{
    this._textContent = value === undefined || value === null ? "" : String(value);
  }}
  get textContent() {{
    return this._textContent + this.children.map(function (child) {{ return child.textContent || ""; }}).join("");
  }}
  set innerHTML(value) {{
    this._innerHTML = value === undefined || value === null ? "" : String(value);
    if (this._innerHTML === "") this.children = [];
  }}
  get innerHTML() {{
    return this._innerHTML;
  }}
}}

const elements = {{}};
function byId(id) {{
  if (!elements[id]) elements[id] = new Element("div", id);
  return elements[id];
}}
function findByClass(root, className, out) {{
  out = out || [];
  if (!root) return out;
  const classes = String(root.className || "").split(/\\s+/);
  if (classes.indexOf(className) >= 0) out.push(root);
  (root.children || []).forEach(function (child) {{ findByClass(child, className, out); }});
  return out;
}}
function dispatch(name, event) {{
  (listeners[name] || []).forEach(function (fn) {{ fn(event); }});
}}
function statusText() {{
  return findByClass(byId("recommended-actions"), "action-run-status")
    .map(function (node) {{ return node.textContent; }})
    .join("\\n");
}}
function runButton() {{
  return findByClass(byId("recommended-actions"), "action-run")[0];
}}
function recordButton() {{
  return findByClass(byId("recommended-actions"), "action-record")[0];
}}

const listeners = {{}};
const calls = [];
let recordAttempts = 0;
global.document = {{
  getElementById: byId,
  createElement: function (tagName) {{ return new Element(tagName); }},
  querySelectorAll: function () {{ return []; }}
}};
global.navigator = {{}};
global.window = {{
  parent: {{
    postMessage: function () {{ throw new Error("direct path should not use bridge"); }}
  }},
  addEventListener: function (name, fn) {{
    if (!listeners[name]) listeners[name] = [];
    listeners[name].push(fn);
  }},
  openai: {{
    callTool: async function (name, args) {{
      calls.push({{ name, args }});
      if (name === "get_connector_runtime_health_status") {{
        return {{ structuredContent: {{ source: "connector_runtime_health", status: "failed", ok: false, error: "probe failed" }} }};
      }}
      if (name === "record_product_console_action_result") {{
        recordAttempts += 1;
        assert.strictEqual(args.action_fingerprint, "failed123");
        assert.strictEqual(args.status, "failed");
        assert.strictEqual(args.result_ok, false);
        assert(args.message.includes("get_connector_runtime_health_status via direct call | failed"), args.message);
        if (recordAttempts === 1) {{
          return {{ structuredContent: {{ source: "product_console_action_results", status: "failed", ok: false, error: "write failed" }} }};
        }}
        return {{ structuredContent: {{ source: "product_console_action_results", status: "recorded" }} }};
      }}
      if (name === "get_product_console_map") {{
        return {{
          structuredContent: {{
            source: "product_console_map",
            project_name: "demo-project",
            recommended_first_actions: [{{
              action_id: "connector_health",
              label: "Read connector health",
              mode: "read",
              tool: "get_connector_runtime_health_status",
              arguments: {{ project_name: "demo-project" }},
              required_scope: "mcp:read",
              action_fingerprint: "failed123",
              last_action_result: {{ status: "failed", message: "recorded failure", observed_at: "2026-01-01T00:00:00Z" }},
              next_refresh_actions: []
            }}]
          }}
        }};
      }}
      throw new Error("unexpected tool " + name);
    }}
  }}
}};

vm.runInThisContext({json.dumps(widget_script)});

(async function () {{
  dispatch("openai:set_globals", {{
    detail: {{
      globals: {{
        toolOutput: {{
          source: "product_console_map",
          project_name: "demo-project",
          recommended_first_actions: [{{
            action_id: "connector_health",
            label: "Read connector health",
            mode: "read",
            tool: "get_connector_runtime_health_status",
            arguments: {{ project_name: "demo-project" }},
            required_scope: "mcp:read",
            action_fingerprint: "failed123",
            last_action_result: {{ status: "not_recorded" }},
            next_refresh_actions: []
          }}]
        }}
      }}
    }}
  }});

  assert(runButton(), "run button should exist");
  assert(recordButton(), "record button should exist");
  assert.strictEqual(recordButton().disabled, true, "record starts disabled");

  await runButton().listeners.click[0]();
  let text = statusText();
  assert(text.includes("Last run | failed"), text);
  assert(text.includes("get_connector_runtime_health_status via direct call | failed"), text);
  assert.strictEqual(recordButton().disabled, false, "failed run can be recorded");

  await recordButton().listeners.click[0]();
  text = statusText();
  assert(text.includes("failed"), text);
  assert(text.includes("record_product_console_action_result via direct call | failed"), text);
  assert.strictEqual(recordButton().disabled, false, "record failure should remain retryable");

  await recordButton().listeners.click[0]();
  assert.strictEqual(recordAttempts, 2);
  assert.deepStrictEqual(calls.map(function (call) {{ return call.name; }}), [
    "get_connector_runtime_health_status",
    "record_product_console_action_result",
    "record_product_console_action_result",
    "get_product_console_map"
  ]);
  assert.strictEqual(recordButton().disabled, true, "record disables after failed run evidence is recorded");
  text = statusText();
  assert(text.includes("recorded"), text);
  assert(text.includes("refresh current"), text);
}})().catch(function (err) {{
  console.error(err && err.stack ? err.stack : err);
  process.exit(1);
}});
""",
            encoding="utf-8",
        )
        completed = subprocess.run(["node", str(script_path)], capture_output=True, text=True, check=False, timeout=15)
        assert completed.returncode == 0, completed.stdout + completed.stderr

    def test_commander_widget_js_records_direct_action_and_refreshes_console(self) -> None:
        if shutil.which("node") is None:
            self.skipTest("node is required for commander widget behavior smoke")

        project = self.make_git_checkout()
        server = MCPPlanningBridgeServer(str(project), service_mode=False)
        widget_html = server._commander_widget_html()
        widget_script = widget_html.split("<script>", 1)[1].split("</script>", 1)[0]
        script_path = self.tmp_path / "commander-widget-record-smoke.js"
        script_path.write_text(
            f"""
const assert = require("assert");
const vm = require("vm");

class Element {{
  constructor(tagName, id) {{
    this.tagName = tagName;
    this.id = id || "";
    this.children = [];
    this.listeners = {{}};
    this.className = "";
    this.type = "";
    this.title = "";
    this.disabled = false;
    this._textContent = "";
    this._innerHTML = "";
  }}
  appendChild(child) {{
    this.children.push(child);
    return child;
  }}
  addEventListener(name, fn) {{
    if (!this.listeners[name]) this.listeners[name] = [];
    this.listeners[name].push(fn);
  }}
  set textContent(value) {{
    this._textContent = value === undefined || value === null ? "" : String(value);
  }}
  get textContent() {{
    return this._textContent + this.children.map(function (child) {{ return child.textContent || ""; }}).join("");
  }}
  set innerHTML(value) {{
    this._innerHTML = value === undefined || value === null ? "" : String(value);
    if (this._innerHTML === "") this.children = [];
  }}
  get innerHTML() {{
    return this._innerHTML;
  }}
}}

const elements = {{}};
function byId(id) {{
  if (!elements[id]) elements[id] = new Element("div", id);
  return elements[id];
}}
function findByClass(root, className, out) {{
  out = out || [];
  if (!root) return out;
  const classes = String(root.className || "").split(/\\s+/);
  if (classes.indexOf(className) >= 0) out.push(root);
  (root.children || []).forEach(function (child) {{ findByClass(child, className, out); }});
  return out;
}}
function dispatch(name, event) {{
  (listeners[name] || []).forEach(function (fn) {{ fn(event); }});
}}
function recordStatusText() {{
  return findByClass(byId("recommended-actions"), "action-run-status")
    .map(function (node) {{ return node.textContent; }})
    .join("\\n");
}}
function runButton() {{
  return findByClass(byId("recommended-actions"), "action-run")[0];
}}
function recordButton() {{
  return findByClass(byId("recommended-actions"), "action-record")[0];
}}

const listeners = {{}};
const calls = [];
global.document = {{
  getElementById: byId,
  createElement: function (tagName) {{ return new Element(tagName); }},
  querySelectorAll: function () {{ return []; }}
}};
global.navigator = {{}};
global.window = {{
  parent: {{
    postMessage: function () {{ throw new Error("direct path should not use bridge"); }}
  }},
  addEventListener: function (name, fn) {{
    if (!listeners[name]) listeners[name] = [];
    listeners[name].push(fn);
  }},
  openai: {{
    callTool: async function (name, args) {{
      calls.push({{ name, args }});
      if (name === "get_product_readiness_status") {{
        return {{ structuredContent: {{ source: "product_readiness", status: "ready", ready: true }} }};
      }}
      if (name === "record_product_console_action_result") {{
        assert.strictEqual(args.action_fingerprint, "abc123");
        assert.strictEqual(args.status, "updated");
        assert.strictEqual(args.result_ok, true);
        return {{ structuredContent: {{ source: "product_console_action_results", status: "recorded" }} }};
      }}
      if (name === "get_product_console_map") {{
        return {{
          structuredContent: {{
            source: "product_console_map",
            project_name: "demo-project",
            recommended_first_actions: [{{
              action_id: "readiness_check",
              label: "Read readiness",
              mode: "read",
              tool: "get_product_readiness_status",
              arguments: {{ project_name: "demo-project" }},
              required_scope: "mcp:read",
              action_fingerprint: "abc123",
              last_action_result: {{ status: "updated", message: "recorded run", observed_at: "2026-01-01T00:00:00Z" }},
              next_refresh_actions: []
            }}]
          }}
        }};
      }}
      throw new Error("unexpected tool " + name);
    }}
  }}
}};

vm.runInThisContext({json.dumps(widget_script)});

(async function () {{
  dispatch("openai:set_globals", {{
    detail: {{
      globals: {{
        toolOutput: {{
          source: "product_console_map",
          project_name: "demo-project",
          recommended_first_actions: [{{
            action_id: "readiness_check",
            label: "Read readiness",
            mode: "read",
            tool: "get_product_readiness_status",
            arguments: {{ project_name: "demo-project" }},
            required_scope: "mcp:read",
            action_fingerprint: "abc123",
            last_action_result: {{ status: "not_recorded" }},
            next_refresh_actions: []
          }}]
        }}
      }}
    }}
  }});

  assert(runButton(), "run button should exist");
  assert(recordButton(), "record button should exist");
  assert.strictEqual(recordButton().disabled, true, "record starts disabled");

  await runButton().listeners.click[0]();
  assert.strictEqual(recordButton().disabled, false, "record enables after read action result");

  await recordButton().listeners.click[0]();
  assert.deepStrictEqual(calls.map(function (call) {{ return call.name; }}), [
    "get_product_readiness_status",
    "record_product_console_action_result",
    "get_product_console_map"
  ]);
  assert.strictEqual(recordButton().disabled, true, "record disables after successful record and refresh");
  const statusText = recordStatusText();
  assert(statusText.includes("recorded"), statusText);
  assert(statusText.includes("refresh current"), statusText);
}})().catch(function (err) {{
  console.error(err && err.stack ? err.stack : err);
  process.exit(1);
}});
""",
            encoding="utf-8",
        )
        completed = subprocess.run(["node", str(script_path)], capture_output=True, text=True, check=False, timeout=15)
        assert completed.returncode == 0, completed.stdout + completed.stderr

    def test_commander_widget_js_runs_confirmed_stable_preview_then_refreshes_to_apply(self) -> None:
        if shutil.which("node") is None:
            self.skipTest("node is required for commander widget behavior smoke")

        project = self.make_git_checkout()
        server = MCPPlanningBridgeServer(str(project), service_mode=False)
        widget_html = server._commander_widget_html()
        widget_script = widget_html.split("<script>", 1)[1].split("</script>", 1)[0]
        script_path = self.tmp_path / "commander-widget-stable-preview-smoke.js"
        script_path.write_text(
            f"""
const assert = require("assert");
const vm = require("vm");

class Element {{
  constructor(tagName, id) {{
    this.tagName = tagName;
    this.id = id || "";
    this.children = [];
    this.listeners = {{}};
    this.className = "";
    this.type = "";
    this.title = "";
    this.disabled = false;
    this._textContent = "";
    this._innerHTML = "";
  }}
  appendChild(child) {{ this.children.push(child); return child; }}
  addEventListener(name, fn) {{
    if (!this.listeners[name]) this.listeners[name] = [];
    this.listeners[name].push(fn);
  }}
  set textContent(value) {{ this._textContent = value === undefined || value === null ? "" : String(value); }}
  get textContent() {{
    return this._textContent + this.children.map(function (child) {{ return child.textContent || ""; }}).join("");
  }}
  set innerHTML(value) {{
    this._innerHTML = value === undefined || value === null ? "" : String(value);
    if (this._innerHTML === "") this.children = [];
  }}
  get innerHTML() {{ return this._innerHTML; }}
}}

const elements = {{}};
function byId(id) {{
  if (!elements[id]) elements[id] = new Element("div", id);
  return elements[id];
}}
function findByClass(root, className, out) {{
  out = out || [];
  if (!root) return out;
  const classes = String(root.className || "").split(/\\s+/);
  if (classes.indexOf(className) >= 0) out.push(root);
  (root.children || []).forEach(function (child) {{ findByClass(child, className, out); }});
  return out;
}}
function dispatch(name, event) {{
  (listeners[name] || []).forEach(function (fn) {{ fn(event); }});
}}
function runButton() {{ return findByClass(byId("recommended-actions"), "action-run")[0]; }}
function recordButton() {{ return findByClass(byId("recommended-actions"), "action-record")[0]; }}
function actionStatusText() {{
  return findByClass(byId("recommended-actions"), "action-run-status")
    .map(function (node) {{ return node.textContent; }})
    .join("\\n");
}}
function previewAction(fingerprint, head) {{
  return {{
    action_id: "persist_artifact_manifest",
    label: "Preview Stable Promotion Artifact Evidence",
    mode: "preview",
    status: "available",
    tool: "manage_stable_promotion_evidence",
    arguments: {{ action: "preview", candidate_head: head, project_name: "demo-project" }},
    required_scope: "mcp:preview",
    requires_preview_confirm: true,
    requires_explicit_confirmation: true,
    side_effects: true,
    result_contract: {{ expected_result_kind: "preview_packet" }},
    authority_boundary: {{
      does_not_execute_now: true,
      does_not_authorize_stable_replacement: true
    }},
    action_fingerprint: fingerprint,
    last_action_result: {{ status: "not_recorded" }},
    next_refresh_actions: []
  }};
}}
function dispatchAction(action) {{
  dispatch("openai:set_globals", {{
    detail: {{ globals: {{ toolOutput: {{
      source: "product_console_map",
      project_name: "demo-project",
      recommended_first_actions: [action]
    }} }} }}
  }});
}}

const listeners = {{}};
const calls = [];
const parentMessages = [];
function flushPromises() {{ return new Promise(function (resolve) {{ setImmediate(resolve); }}); }}
global.document = {{
  getElementById: byId,
  createElement: function (tagName) {{ return new Element(tagName); }},
  querySelectorAll: function () {{ return []; }}
}};
global.navigator = {{}};
global.window = {{
  parent: {{ postMessage: function (message) {{ parentMessages.push(message); }} }},
  addEventListener: function (name, fn) {{
    if (!listeners[name]) listeners[name] = [];
    listeners[name].push(fn);
  }},
  openai: {{
    callTool: async function (name, args) {{
      calls.push({{ name, args }});
      if (name === "manage_stable_promotion_evidence") {{
        assert.deepStrictEqual(args, {{
          action: "preview",
          candidate_head: "b".repeat(40),
          project_name: "demo-project"
        }});
        return {{ structuredContent: {{
          source: "stable_promotion_artifact_evidence",
          action: "preview",
          preview_id: "preview_current",
          can_apply: true,
          next_action: {{
            tool: "manage_stable_promotion_evidence",
            arguments: {{ action: "apply", preview_id: "preview_current", project_name: "demo-project" }},
            required_scope: "mcp:commit"
          }}
        }} }};
      }}
      if (name === "record_product_console_action_result") {{
        assert.strictEqual(args.action_fingerprint, "preview-current");
        assert.strictEqual(args.mode, "preview");
        assert.strictEqual(args.status, "updated");
        assert.strictEqual(args.result_ok, true);
        return {{ structuredContent: {{ source: "product_console_action_results", status: "recorded" }} }};
      }}
      if (name === "get_product_console_map") {{
        return {{ structuredContent: {{
          source: "product_console_map",
          project_name: "demo-project",
          recommended_first_actions: [{{
            action_id: "persist_artifact_manifest",
            label: "Apply Stable Promotion Artifact Evidence",
            mode: "commit",
            tool: "manage_stable_promotion_evidence",
            arguments: {{ action: "apply", preview_id: "preview_current", project_name: "demo-project" }},
            required_scope: "mcp:commit",
            requires_explicit_confirmation: true,
            side_effects: true,
            action_fingerprint: "apply-current",
            last_action_result: {{ status: "not_recorded" }},
            next_refresh_actions: []
          }}]
        }} }};
      }}
      throw new Error("unexpected tool " + name);
    }}
  }}
}};

vm.runInThisContext({json.dumps(widget_script)});

(async function () {{
  const completedPreview = previewAction("preview-completed", "a".repeat(40));
  completedPreview.last_action_result = {{ status: "updated", message: "preview already created" }};
  dispatchAction(completedPreview);
  assert.strictEqual(runButton().disabled, true, "recorded preview result must remain locked after rerender");
  assert.strictEqual(runButton().textContent, "Preview created");

  const unsafePreview = previewAction("preview-unsafe", "a".repeat(40));
  unsafePreview.side_effects = false;
  dispatchAction(unsafePreview);
  assert.strictEqual(runButton().disabled, true, "preview metadata must match the bounded allowlist");
  assert.strictEqual(runButton().textContent, "Preview outside");

  dispatchAction(previewAction("preview-old", "a".repeat(40)));
  assert.strictEqual(runButton().disabled, false);
  assert.strictEqual(runButton().textContent, "Review preview");
  assert.strictEqual(recordButton().disabled, true);

  await runButton().listeners.click[0]();
  assert.strictEqual(calls.length, 0, "first click only arms confirmation");
  assert.strictEqual(runButton().textContent, "Confirm preview");
  assert.strictEqual(recordButton().disabled, true, "arming is not a recordable result");
  assert(actionStatusText().includes("Confirmation required"), actionStatusText());

  dispatchAction(previewAction("preview-current", "b".repeat(40)));
  assert.strictEqual(runButton().textContent, "Review preview", "changed fingerprint must invalidate confirmation");
  await runButton().listeners.click[0]();
  assert.strictEqual(calls.length, 0, "changed action also requires a fresh first click");
  assert(actionStatusText().includes("manage_stable_promotion_evidence"), actionStatusText());
  assert(actionStatusText().includes("candidate_head=" + "b".repeat(40)), actionStatusText());
  assert(actionStatusText().includes("project_name=demo-project"), actionStatusText());
  await runButton().listeners.click[0]();
  assert.deepStrictEqual(calls.map(function (call) {{ return call.name; }}), [
    "manage_stable_promotion_evidence",
    "get_product_console_map"
  ]);
  assert.strictEqual(runButton().textContent, "Confirm outside");
  assert.strictEqual(runButton().disabled, true, "commit-scoped apply remains unavailable in the widget");
  assert.strictEqual(recordButton().disabled, true, "auto-refresh replaces the preview card without a record write");
  assert.strictEqual(parentMessages.length, 0, "successful direct preview refresh stays on the direct path");

  window.openai.callTool = async function () {{ throw new Error("direct unavailable"); }};
  dispatchAction(previewAction("preview-bridge", "c".repeat(40)));
  await runButton().listeners.click[0]();
  await runButton().listeners.click[0]();
  assert.strictEqual(parentMessages.length, 1, "preview fallback should post one bridge request");
  assert.strictEqual(parentMessages[0].params.name, "manage_stable_promotion_evidence");
  dispatch("message", {{ data: {{
    id: parentMessages[0].id,
    result: {{ structuredContent: {{
      source: "stable_promotion_artifact_evidence",
      action: "preview",
      preview_id: "preview_bridge",
      can_apply: true
    }} }}
  }} }});
  await flushPromises();
  assert.strictEqual(parentMessages.length, 2, "successful preview result should request a read-only console refresh");
  assert.strictEqual(parentMessages[1].params.name, "get_product_console_map");
  assert.deepStrictEqual(parentMessages[1].params.arguments, {{ project_name: "demo-project" }});
  dispatch("message", {{ data: {{
    id: parentMessages[1].id,
    result: {{ structuredContent: {{
      source: "product_console_map",
      project_name: "demo-project",
      recommended_first_actions: [{{
        action_id: "persist_artifact_manifest",
        label: "Apply Stable Promotion Artifact Evidence",
        mode: "commit",
        tool: "manage_stable_promotion_evidence",
        arguments: {{ action: "apply", preview_id: "preview_bridge", project_name: "demo-project" }},
        required_scope: "mcp:commit",
        action_fingerprint: "apply-bridge",
        last_action_result: {{ status: "not_recorded" }},
        next_refresh_actions: []
      }}]
    }} }}
  }} }});
  assert.strictEqual(runButton().textContent, "Confirm outside");
  assert.strictEqual(runButton().disabled, true, "bridge refresh also advances to the external apply handoff");

  const failedDirectCalls = [];
  window.openai.callTool = async function (name) {{
    failedDirectCalls.push(name);
    return {{ structuredContent: {{
      source: "stable_promotion_artifact_evidence",
      status: "failed",
      ok: false,
      error: "preview rejected"
    }} }};
  }};
  dispatchAction(previewAction("preview-direct-failed", "d".repeat(40)));
  await runButton().listeners.click[0]();
  await runButton().listeners.click[0]();
  assert.deepStrictEqual(failedDirectCalls, ["manage_stable_promotion_evidence"]);
  assert.strictEqual(parentMessages.length, 2, "failed direct preview must not refresh or fall back");

  const malformedDirectCalls = [];
  window.openai.callTool = async function (name) {{
    malformedDirectCalls.push(name);
    return {{ structuredContent: {{
      source: "stable_promotion_artifact_evidence",
      action: "preview",
      can_apply: true
    }} }};
  }};
  dispatchAction(previewAction("preview-direct-malformed", "f".repeat(40)));
  await runButton().listeners.click[0]();
  await runButton().listeners.click[0]();
  assert.deepStrictEqual(malformedDirectCalls, ["manage_stable_promotion_evidence"]);
  assert.strictEqual(parentMessages.length, 2, "preview without preview_id must not refresh");

  window.openai.callTool = async function () {{ throw new Error("direct unavailable"); }};
  dispatchAction(previewAction("preview-bridge-failed", "e".repeat(40)));
  await runButton().listeners.click[0]();
  await runButton().listeners.click[0]();
  assert.strictEqual(parentMessages.length, 3, "failed bridge scenario starts with only the preview request");
  dispatch("message", {{ data: {{
    id: parentMessages[2].id,
    result: {{ structuredContent: {{
      source: "stable_promotion_artifact_evidence",
      status: "failed",
      ok: false,
      error: "preview rejected"
    }} }}
  }} }});
  await flushPromises();
  assert.strictEqual(parentMessages.length, 3, "failed bridge preview must not request a console refresh");
}})().catch(function (err) {{
  console.error(err && err.stack ? err.stack : err);
  process.exit(1);
}});
""",
            encoding="utf-8",
        )
        completed = subprocess.run(["node", str(script_path)], capture_output=True, text=True, check=False, timeout=15)
        assert completed.returncode == 0, completed.stdout + completed.stderr

    def test_stage_parallel_plan_preview_tool_is_read_only_and_project_routed(self) -> None:
        project = self.make_git_checkout(managed=True)
        server = MCPPlanningBridgeServer(str(project), service_mode=True)
        server.project_registry = self.temp_registry()
        self.register_demo_project(server.project_registry, project)

        missing_project = server.call_tool_for_agent("get_stage_parallel_plan_preview", {})
        assert missing_project["ok"] is False
        assert missing_project["error_code"] == "PROJECT_NAME_REQUIRED"

        result = server.call_tool_for_agent(
            "get_stage_parallel_plan_preview",
            {
                "project_name": "demo-project",
                "stage_id": "stage_parallel_dev",
                "task_intents": [
                    {
                        "task_id": "mcp_entry",
                        "title": "MCP entry",
                        "allowed_files": ["runner/mcp_server.py"],
                        "surfaces": ["MCP"],
                    },
                    {
                        "task_id": "docs_entry",
                        "title": "Docs entry",
                        "allowed_files": ["docs/USAGE.md"],
                        "surfaces": ["docs"],
                    },
                ],
            },
        )

        assert result["ok"] is True
        assert result["tool"] == "get_stage_parallel_plan_preview"
        data = result["data"]
        assert data["read_only"] is True
        assert data["side_effects"] is False
        assert data["source"] == "stage_parallel_plan_preview"
        assert data["project_name"] == "demo-project"
        assert data["stage_id"] == "stage_parallel_dev"
        assert data["suggested_next_action"] == "ready_for_parallel_run_preview"
        assert data["authority_boundary"]["does_not_authorize_executor_run"] is True
        assert data["authority_boundary"]["does_not_create_executor_preview"] is True
        assert data["authority_boundary"]["does_not_create_branch_or_worktree"] is True
        assert data["authority_boundary"]["does_not_commit"] is True
        assert data["authority_boundary"]["does_not_push"] is True

        run_result = server.call_tool_for_agent(
            "get_stage_parallel_run_preview",
            {
                "project_name": "demo-project",
                "stage_id": "stage_parallel_dev",
                "task_intents": [
                    {
                        "task_id": "mcp_entry",
                        "title": "MCP entry",
                        "allowed_files": ["runner/mcp_server.py"],
                        "surfaces": ["MCP"],
                    },
                    {
                        "task_id": "docs_entry",
                        "title": "Docs entry",
                        "allowed_files": ["docs/USAGE.md"],
                        "surfaces": ["docs"],
                    },
                ],
            },
        )
        assert run_result["ok"] is True
        assert run_result["tool"] == "get_stage_parallel_run_preview"
        run_data = run_result["data"]
        assert run_data["source"] == "stage_parallel_run_preview"
        assert run_data["status"] == "preview_ready"
        assert run_data["run_shards"][0]["executor_preview_request"]["status"] == "not_created"
        assert run_data["authority_boundary"]["does_not_create_executor_preview"] is True
        assert run_data["authority_boundary"]["does_not_authorize_executor_run"] is True

        worktree_result = server.call_tool_for_agent(
            "get_stage_parallel_worktree_assignment_preview",
            {
                "project_name": "demo-project",
                "stage_id": "stage_parallel_dev",
                "task_intents": [
                    {
                        "task_id": "mcp_entry",
                        "title": "MCP entry",
                        "allowed_files": ["runner/mcp_server.py"],
                        "surfaces": ["MCP"],
                    },
                    {
                        "task_id": "docs_entry",
                        "title": "Docs entry",
                        "allowed_files": ["docs/USAGE.md"],
                        "surfaces": ["docs"],
                    },
                ],
            },
        )
        assert worktree_result["ok"] is True
        assert worktree_result["tool"] == "get_stage_parallel_worktree_assignment_preview"
        worktree_data = worktree_result["data"]
        assert worktree_data["source"] == "stage_parallel_worktree_assignment_preview"
        assert worktree_data["status"] == "preview_ready"
        assert worktree_data["assignment_summary"]["creates_worktrees"] is False
        assert worktree_data["authority_boundary"]["does_not_create_branch_or_worktree"] is True

        status_result = server.call_tool_for_agent(
            "get_stage_parallel_group_status",
            {
                "project_name": "demo-project",
                "stage_id": "stage_parallel_dev",
                "task_intents": [
                    {
                        "task_id": "mcp_entry",
                        "title": "MCP entry",
                        "allowed_files": ["runner/mcp_server.py"],
                        "surfaces": ["MCP"],
                    },
                    {
                        "task_id": "docs_entry",
                        "title": "Docs entry",
                        "allowed_files": ["docs/USAGE.md"],
                        "surfaces": ["docs"],
                    },
                ],
            },
        )
        assert status_result["ok"] is True
        status_data = status_result["data"]
        assert status_data["source"] == "stage_parallel_group_status"
        assert status_data["status"] == "waiting_for_executor_results"
        assert status_data["authority_boundary"]["does_not_merge_parallel_results"] is True

        closeout_result = server.call_tool_for_agent(
            "get_stage_parallel_closeout_packet",
            {
                "project_name": "demo-project",
                "stage_id": "stage_parallel_dev",
                "task_intents": [
                    {
                        "task_id": "mcp_entry",
                        "title": "MCP entry",
                        "allowed_files": ["runner/mcp_server.py"],
                        "surfaces": ["MCP"],
                    },
                    {
                        "task_id": "docs_entry",
                        "title": "Docs entry",
                        "allowed_files": ["docs/USAGE.md"],
                        "surfaces": ["docs"],
                    },
                ],
                "executor_results": [
                    {
                        "task_id": "mcp_entry",
                        "status": "succeeded",
                        "validation_status": "passed",
                        "changed_files": ["runner/mcp_server.py"],
                    },
                    {
                        "task_id": "docs_entry",
                        "status": "succeeded",
                        "validation_status": "passed",
                        "changed_files": ["docs/USAGE.md"],
                    },
                ],
            },
        )
        assert closeout_result["ok"] is True
        assert closeout_result["tool"] == "get_stage_parallel_closeout_packet"
        closeout_data = closeout_result["data"]
        assert closeout_data["source"] == "stage_parallel_closeout_packet"
        assert closeout_data["status"] == "ready_for_human_review"
        assert closeout_data["authority_boundary"]["does_not_write_delivery_accepted"] is True

    def test_commander_app_manifest_is_read_only_and_rejects_unsanitized_evidence(self) -> None:
        project = self.make_git_checkout(managed=True)
        server = MCPPlanningBridgeServer(str(project), service_mode=True)
        server.project_registry = self.temp_registry()
        self.register_demo_project(server.project_registry, project)
        record_product_console_action_result(
            str(project),
            action_id="submission_evidence_activity",
            tool="submission_evidence_activity_summary",
            mode="read",
            status="updated",
            message="Submission evidence activity | commander manifest recovery refreshed",
            project_name="demo-project",
            result_ok=True,
        )

        result = server.call_tool_for_agent(
            "get_commander_app_manifest",
            {
                "project_name": "demo-project",
                "profile_id": "reviewer_agent",
                "tunnel_client": {
                    "status": "healthy",
                    "reason_code": "TUNNEL_CLIENT_HEALTHY",
                    "evidence_source": "sanitized_test",
                    "last_observed_at": "2026-07-03T00:00:00Z",
                },
                "control_plane": {
                    "status": "healthy",
                    "reason_code": "CONTROL_PLANE_HEALTHY",
                    "evidence_source": "sanitized_test",
                    "last_observed_at": "2026-07-03T00:00:00Z",
                },
            },
        )

        assert result["ok"] is True
        assert result["tool"] == "get_commander_app_manifest"
        data = result["data"]
        assert data["ok"] is True
        assert data["read_only"] is True
        assert data["side_effects"] is False
        assert data["app"]["archetype"] == "interactive-decoupled"
        assert data["app"]["render_tool"] == "render_commander_app"
        assert data["app"]["embedded_flow_profile_id"] == "reviewer_agent"
        assert data["project_name"] == "demo-project"
        assert data["connector"]["external_connector_status"] == "healthy"
        assert data["readiness"]["status"] in {"ready", "needs_attention", "blocked"}
        assert data["readiness"]["read_only"] is True
        assert data["readiness"]["components"]["operator_closeout"]["status"]
        assert data["readiness"]["safe_next_actions"][0]["authority"] in {"read_only", "preview_or_task_packet_only"}
        assert data["agent_operator_flow_profile"]["profile_id"] == "reviewer_agent"
        assert data["agent_operator_flow_profile"]["consumer_kind"] == "reviewer"
        assert data["agent_operator_flow"]["source"] == "agent_operator_flow_packet"
        assert data["agent_operator_flow"]["profile_id"] == "reviewer_agent"
        assert data["agent_operator_flow"]["current_state"]["resolved_flow_mode"] == "review"
        embedded_readiness = data["agent_operator_flow"]["current_state"]["readiness"]
        embedded_connector = data["agent_operator_flow"]["current_state"]["connector"]
        assert embedded_readiness["status"] == data["readiness"]["status"]
        assert embedded_connector["external_connector_status"] == data["connector"]["external_connector_status"]
        assert embedded_connector["operator_closeout"] == data["connector"]["operator_closeout_status"]
        assert (
            embedded_connector["evidence_gap_count"]
            == data["connector"]["operator_closeout"]["evidence_gap_count"]
        )
        assert data["agent_operator_flow"]["persona_safe_next_tool"] == "manage_workflow_run"
        assert data["agent_operator_flow"]["primary_next_action"]["tool"]
        assert data["initial_reads"][2]["arguments"]["profile_id"] == "reviewer_agent"
        assert data["initial_reads"][3]["arguments"]["profile_id"] == "reviewer_agent"
        assert data["initial_reads"][4]["arguments"]["profile_id"] == "reviewer_agent"
        assert data["apps_connector_closeout"]["status"] in {"ready", "needs_attention"}
        projections = data["domain_projections"]
        assert set(projections) == {"core", "service_operations", "app_submission"}
        assert projections["core"]["write_path"] == "application_commands_only"
        assert projections["core"]["read_only_surface"] is True
        assert (
            projections["service_operations"]["read_model"]["overall_status"]
            == data["connector"]["overall_status"]
        )
        assert (
            projections["app_submission"]["read_model"]["status"]
            == data["apps_connector_closeout"]["release_submission_evidence"]["status"]
        )
        assert projections["service_operations"]["can_write_work_item_state"] is False
        assert projections["app_submission"]["can_write_work_item_state"] is False
        assert data["apps_connector_closeout"]["project_list_check"]["tool"] == "list_registered_projects"
        assert data["apps_connector_closeout"]["connector_closeout_check"]["tool"] == "get_connector_runtime_health_status"
        release_evidence = data["apps_connector_closeout"]["release_submission_evidence"]
        assert release_evidence["source"] == "release_submission_evidence_closeout"
        assert release_evidence["evidence_progress"]["source"] == "submission_evidence_progress"
        assert release_evidence["evidence_progress"]["total_count"] == 10
        assert release_evidence["submission_evidence_activity"]["available"] is True
        assert release_evidence["submission_evidence_activity"]["status"] == "updated"
        assert release_evidence["submission_evidence_activity"]["read_only_summary"] is True
        assert release_evidence["authority_boundary"]["does_not_submit_app_for_review"] is True
        assert "apps_connector_closeout" in data["commander_panel"]["primary_sections"]
        assert "release_submission_evidence" in data["commander_panel"]["primary_sections"]
        assert "agent_operator_flow" in data["commander_panel"]["primary_sections"]
        assert any(
            item["tool"] == "get_agent_operator_flow_packet"
            and item["arguments"]["profile_id"] == "reviewer_agent"
            for item in data["commander_panel"]["read_actions"]
        )
        assert any(
            item["tool"] == "get_commander_app_manifest"
            and item["arguments"]["profile_id"] == "reviewer_agent"
            for item in data["commander_panel"]["read_actions"]
        )
        assert any(
            item["tool"] == "get_connector_runtime_health_status"
            and "tunnel_client" in item.get("arguments", {})
            for item in data["commander_panel"]["read_actions"]
        )
        assert any(
            item["tool"] == "get_product_console_map" and item["arguments"]["project_name"] == "demo-project"
            for item in data["commander_panel"]["read_actions"]
        )
        assert any(
            item["tool"] == "get_release_submission_readiness" and item["arguments"]["project_name"] == "demo-project"
            for item in data["commander_panel"]["read_actions"]
        )
        assert "service_readiness" in data["commander_panel"]["primary_sections"]
        assert data["authority_boundary"]["does_not_authorize_executor_run"] is True
        assert "Delivery accepted" in data["authority_boundary"]["requires_explicit_commander_authorization_for"]

        rendered = server.call_tool_for_agent(
            "render_commander_app",
            {"project_name": "demo-project", "profile_id": "source_observer"},
        )
        assert rendered["ok"] is True
        assert rendered["data"]["agent_operator_flow_profile"]["profile_id"] == "source_observer"
        assert rendered["data"]["app"]["embedded_flow_profile_id"] == "source_observer"

        rejected = server.call_tool_for_agent(
            "get_commander_app_manifest",
            {
                "project_name": "demo-project",
                "tunnel_client": {
                    "status": "healthy",
                    "raw_token": "must-not-return",
                },
            },
        )

        assert rejected["ok"] is False
        assert rejected["error_code"] == "UNSAFE_CONNECTOR_EVIDENCE"
        serialized = json.dumps(rejected, ensure_ascii=False)
        assert "must-not-return" not in serialized
        assert "raw_token" not in serialized

    def test_commander_app_manifest_embedded_flow_does_not_refresh_manifest_recursively(self) -> None:
        project = self.make_git_checkout(managed=True)
        server = MCPPlanningBridgeServer(str(project), service_mode=True)
        server.project_registry = self.temp_registry()
        self.register_demo_project(server.project_registry, project)
        completed_console = {
            "completion_surface": {
                "status": "ready",
                "ready": True,
                "gap_count": 0,
                "blocker_codes": [],
                "needs_attention_codes": [],
                "followup_queue": {"status": "ready", "next_item": None},
            }
        }

        with (
            patch(
                "runner.mcp_server.build_service_readiness_summary",
                return_value={"status": "ready", "safe_next_actions": [], "primary_blocker": None},
            ),
            patch(
                "runner.mcp_server.build_apps_connector_closeout_packet",
                return_value={
                    "status": "ready",
                    "connector_closeout_check": {
                        "tool": "get_connector_runtime_health_status",
                        "arguments": {"project_name": "demo-project"},
                    },
                },
            ),
            patch("runner.mcp_server.build_product_console_map", return_value=completed_console),
            patch.object(server, "_apps_connector_release_submission_evidence", return_value={"status": "ready"}),
        ):
            result = server.call_tool_for_agent(
                "get_commander_app_manifest",
                {"project_name": "demo-project", "profile_id": "web_gpt_commander"},
            )
            external_result = server.call_tool_for_agent(
                "get_agent_operator_flow_packet",
                {
                    "project_name": "demo-project",
                    "profile_id": "web_gpt_commander",
                    "_embedded_in_commander_manifest": True,
                },
            )

        assert result["ok"] is True, result
        embedded = result["data"]["agent_operator_flow"]
        assert embedded["primary_next_action"]["action_id"] == "continue_with_requested_work"
        assert embedded["primary_next_action"]["tool"] == "run_mcp_workflow"
        assert embedded["primary_next_action"]["arguments"]["workflow"] == "thin_governed_loop_preview"
        assert embedded["primary_next_action"]["tool"] != "get_commander_app_manifest"
        assert external_result["ok"] is True
        assert external_result["data"]["primary_next_action"]["tool"] == "get_commander_app_manifest"

    def test_product_readiness_tools_are_read_only_and_use_product_packet(self) -> None:
        project = self.make_git_checkout(managed=True)
        server = MCPPlanningBridgeServer(str(project), service_mode=False)
        readiness_packet = {
            "ok": True,
            "source": "product_readiness",
            "read_only": True,
            "side_effects": False,
            "status": "ready",
            "ready": True,
        }
        chatgpt_packet = {
            "ok": True,
            "source": "chatgpt_connection_readiness",
            "read_only": True,
            "side_effects": False,
            "status": "ready",
            "ready": True,
            "recommended_sequence": [{"tool": "list_registered_projects", "arguments": {}}],
        }

        with (
            patch("runner.mcp_server.build_product_readiness_packet", return_value=readiness_packet) as readiness,
            patch("runner.mcp_server.build_chatgpt_connection_packet", return_value=chatgpt_packet) as chatgpt,
        ):
            result = server.call_tool_for_agent("get_product_readiness_status", {})
            chatgpt_result = server.call_tool_for_agent("get_chatgpt_app_readiness", {})

        assert result["tool"] == "get_product_readiness_status"
        assert result["data"]["source"] == "product_readiness"
        assert result["data"]["read_only"] is True
        assert result["data"]["side_effects"] is False
        assert chatgpt_result["tool"] == "get_chatgpt_app_readiness"
        assert chatgpt_result["data"]["source"] == "chatgpt_connection_readiness"
        assert chatgpt_result["data"]["read_only"] is True
        readiness.assert_called_once_with(str(project))
        chatgpt.assert_called_once()

    def test_service_product_readiness_preserves_registered_project_name(self) -> None:
        project = self.make_git_checkout(managed=True)
        server = MCPPlanningBridgeServer(str(project), service_mode=True)
        server.project_registry = self.temp_registry()
        self.register_demo_project(server.project_registry, project)
        packet = {
            "ok": True,
            "source": "product_readiness",
            "read_only": True,
            "side_effects": False,
            "status": "blocked",
        }

        with patch("runner.mcp_server.build_product_readiness_packet", return_value=packet) as readiness:
            result = server.call_tool_for_agent(
                "get_product_readiness_status",
                {"project_name": "demo-project"},
            )

        assert result["ok"] is True
        readiness.assert_called_once_with(str(project), project_name="demo-project")

    def test_full_loop_authority_tool_is_read_only_and_does_not_echo_confirmation_ref(self) -> None:
        project = self.make_git_checkout(managed=True)
        server = MCPPlanningBridgeServer(str(project), service_mode=False)

        result = server.call_tool_for_agent(
            "get_full_loop_authority_status",
            {
                "enable_full_loop": True,
                "confirmation_mode": "preview-confirm",
                "operator_confirmation_ref": "receipt-secret-like-ref",
                "allow_executor_run": True,
                "allow_validation_run": True,
                "allow_local_commit": True,
                "allow_remote_push": True,
            },
        )

        assert result["ok"] is True
        assert result["tool"] == "get_full_loop_authority_status"
        data = result["data"]
        assert data["source"] == "full_loop_authority_status"
        assert data["read_only"] is True
        assert data["side_effects"] is False
        assert data["status"] == "ready"
        assert data["requested_controls"]["operator_confirmation_ref_present"] is True
        serialized = json.dumps(data, ensure_ascii=False)
        assert "receipt-secret-like-ref" not in serialized

    def test_product_console_map_tool_is_read_only_and_project_routed(self) -> None:
        project = self.make_git_checkout(managed=True)
        server = MCPPlanningBridgeServer(str(project), service_mode=True)
        server.project_registry = self.temp_registry()
        self.register_demo_project(server.project_registry, project)
        console_packet = {
            "ok": True,
            "source": "product_console_map",
            "read_only": True,
            "side_effects": False,
            "status": "ready_read_preview",
            "entries": [],
        }
        readiness_packet = {
            "status": "ready",
            "ready": True,
            "safe_next_action": {"tool": "render_commander_app"},
        }

        with (
            patch("runner.mcp_server.build_product_readiness_packet", return_value=readiness_packet),
            patch("runner.mcp_server.build_product_console_map", return_value=console_packet) as console_map,
        ):
            result = server.call_tool_for_agent("get_product_console_map", {"project_name": "demo-project"})

        assert result["ok"] is True
        assert result["tool"] == "get_product_console_map"
        assert result["data"]["source"] == "product_console_map"
        assert result["data"]["read_only"] is True
        console_map.assert_called_once_with(
            str(project),
            project_name="demo-project",
            readiness_packet=readiness_packet,
            stable_promotion_readiness=None,
        )

    def test_product_console_map_loads_stable_preflight_to_advance_stale_runtime_action(self) -> None:
        project = self.make_git_checkout(managed=True)
        server = MCPPlanningBridgeServer(str(project), service_mode=True)
        server.project_registry = self.temp_registry()
        self.register_demo_project(server.project_registry, project)
        readiness_packet = {
            "status": "blocked",
            "ready": False,
            "safe_next_action": {"tool": "get_stable_promotion_readiness"},
        }
        stable_packet = {
            "ok": True,
            "recommended_next_steps": [
                {
                    "tool": "manage_stable_promotion_evidence",
                    "arguments": {"action": "preview", "candidate_head": "a" * 40},
                    "required_scope": "mcp:preview",
                }
            ],
        }
        console_packet = {"ok": True, "source": "product_console_map", "read_only": True}

        with (
            patch("runner.mcp_server.build_product_readiness_packet", return_value=readiness_packet),
            patch("runner.mcp_server.get_stable_promotion_readiness", return_value=stable_packet),
            patch("runner.mcp_server.build_product_console_map", return_value=console_packet) as console_map,
        ):
            result = server.call_tool_for_agent("get_product_console_map", {"project_name": "demo-project"})

        assert result["ok"] is True
        assert stable_packet["recommended_next_steps"][0]["arguments"]["project_name"] == "demo-project"
        console_map.assert_called_once_with(
            str(project),
            project_name="demo-project",
            readiness_packet=readiness_packet,
            stable_promotion_readiness=stable_packet,
        )

    def test_release_submission_readiness_tool_is_read_only_and_project_routed(self) -> None:
        project = self.make_git_checkout(managed=True)
        server = MCPPlanningBridgeServer(str(project), service_mode=True)
        server.project_registry = self.temp_registry()
        self.register_demo_project(server.project_registry, project)
        release_packet = {
            "ok": True,
            "source": "release_submission_readiness",
            "read_only": True,
            "side_effects": False,
            "status": "needs_attention",
            "ready": False,
        }

        with patch("runner.mcp_server.build_release_submission_readiness", return_value=release_packet) as release:
            result = server.call_tool_for_agent(
                "get_release_submission_readiness",
                {
                    "project_name": "demo-project",
                    "app_name": "ColaMeta",
                    "logo_ready": True,
                    "screenshots_ready": True,
                    "submission_materials": {
                        "schema_version": "chatgpt_app_submission_materials.v1",
                        "app_description": "Project console for AI engineering workflows.",
                    },
                },
            )

        assert result["ok"] is True
        assert result["tool"] == "get_release_submission_readiness"
        assert result["data"]["source"] == "release_submission_readiness"
        assert result["data"]["read_only"] is True
        assert release.call_args.kwargs["project_name"] == "demo-project"
        assert release.call_args.kwargs["app_name"] == "ColaMeta"
        assert release.call_args.kwargs["logo_ready"] is True
        assert release.call_args.kwargs["submission_materials"]["schema_version"] == "chatgpt_app_submission_materials.v1"
        assert release.call_args.kwargs["submission_materials"]["app_description"].startswith("Project console")

    def test_submission_evidence_fill_preview_tool_is_read_only_and_project_routed(self) -> None:
        project = self.make_git_checkout(managed=True)
        server = MCPPlanningBridgeServer(str(project), service_mode=True)
        server.project_registry = self.temp_registry()
        self.register_demo_project(server.project_registry, project)
        preview_packet = {
            "ok": True,
            "source": "submission_evidence_fill_preview",
            "read_only": True,
            "side_effects": False,
            "status": "preview_ready",
            "copyable_tool_call": {
                "tool": "fill_submission_evidence_files",
                "arguments": {"project_name": "demo-project", "entries": [], "mark_ready": False},
            },
        }

        with patch("runner.mcp_server.build_submission_evidence_fill_preview", return_value=preview_packet) as preview:
            result = server.call_tool_for_agent(
                "get_submission_evidence_fill_preview",
                {
                    "project_name": "demo-project",
                    "selected_keys": ["logo"],
                },
            )

        assert result["ok"] is True
        assert result["tool"] == "get_submission_evidence_fill_preview"
        assert result["data"]["source"] == "submission_evidence_fill_preview"
        assert result["data"]["read_only"] is True
        preview.assert_called_once_with(str(project), project_name="demo-project", selected_keys=["logo"])

    def test_submission_evidence_auto_draft_tool_is_read_only_and_project_routed(self) -> None:
        project = self.make_git_checkout(managed=True)
        server = MCPPlanningBridgeServer(str(project), service_mode=True)
        server.project_registry = self.temp_registry()
        self.register_demo_project(server.project_registry, project)
        runtime_packet = {
            "project_checkout_head": HEAD_A,
            "loaded_runtime_head": HEAD_A,
            "runtime_loaded_code_stale": False,
            "reload_needed_for_verification": False,
            "reload_awareness_reason": "loaded_code_verified_current",
        }
        connector_packet = {
            "overall_status": "ready",
            "local_service": {"status": "ready"},
            "external_connector": {"status": "ready"},
            "operator_closeout": {"status": "ready"},
        }

        with (
            patch.object(server, "_connector_runtime_local_service_evidence", return_value={"status": "ready"}),
            patch("runner.mcp_server.loaded_runtime_project_root", return_value="/runtime/colameta"),
            patch("runner.mcp_server.get_runtime_version_status", return_value=runtime_packet) as runtime_status,
            patch("runner.mcp_server.get_connector_runtime_health_status", return_value=connector_packet) as connector_health,
        ):
            result = server.call_tool_for_agent(
                "get_submission_evidence_auto_draft",
                {
                    "project_name": "demo-project",
                    "selected_keys": ["mcp_tool_info"],
                },
            )

        assert result["ok"] is True
        assert result["tool"] == "get_submission_evidence_auto_draft"
        data = result["data"]
        assert data["source"] == "submission_evidence_auto_draft"
        assert data["read_only"] is True
        assert data["side_effects"] is False
        assert data["status"] == "draft_ready"
        assert data["project_root"] == str(project)
        assert data["generated_keys"] == ["mcp_tool_info"]
        assert data["authority_boundary"]["does_not_write_files"] is True
        assert data["authority_boundary"]["does_not_mark_ready_fields"] is True
        assert data["authority_boundary"]["does_not_submit_app_for_review"] is True
        copyable = data["copyable_tool_call"]
        assert copyable["tool"] == "fill_submission_evidence_files"
        assert copyable["required_scope"] == "mcp:commit"
        assert copyable["arguments"]["project_name"] == "demo-project"
        assert copyable["arguments"]["mark_ready"] is False
        entries = copyable["arguments"]["entries"]
        assert len(entries) == 1
        assert entries[0]["key"] == "mcp_tool_info"
        assert entries[0]["filename"] == "mcp-tool-info.md"
        assert "# MCP Tool Information Evidence" in entries[0]["content"]
        assert "`get_submission_evidence_auto_draft`" in entries[0]["content"]
        assert "`manage_stage_parallel_worktrees` | `action-dependent`" in entries[0]["content"]
        assert "mcp:unknown" not in entries[0]["content"]
        runtime_status.assert_called_once_with(
            str(project),
            runtime_project_root="/runtime/colameta",
            local_service={"status": "ready"},
        )
        connector_health.assert_called_once_with(runtime_status=runtime_packet, local_service={"status": "ready"})

    def test_init_submission_evidence_tool_is_commit_scoped_and_project_routed(self) -> None:
        project = self.make_git_checkout(managed=True)
        server = MCPPlanningBridgeServer(str(project), service_mode=True)
        server.project_registry = self.temp_registry()
        self.register_demo_project(server.project_registry, project)
        scaffold_packet = {
            "ok": True,
            "source": "submission_evidence_scaffold",
            "schema_version": "submission_evidence_scaffold.v1",
            "manifest_created": True,
            "created_files": ["docs/chatgpt-app-submission-materials.json"],
            "existing_files": [],
        }

        with patch("runner.mcp_server.init_submission_evidence_scaffold", return_value=scaffold_packet) as scaffold:
            result = server.call_tool_for_agent(
                "init_submission_evidence",
                {
                    "project_name": "demo-project",
                    "app_name": "Demo App",
                    "company_url": "https://example.test",
                    "privacy_policy_url": "https://example.test/privacy",
                },
            )

        assert result["ok"] is True
        assert result["tool"] == "init_submission_evidence"
        assert result["data"]["source"] == "submission_evidence_scaffold"
        scaffold.assert_called_once()
        assert scaffold.call_args.args == (str(project),)
        assert scaffold.call_args.kwargs["app_name"] == "Demo App"
        assert scaffold.call_args.kwargs["company_url"] == "https://example.test"

    def test_fill_submission_evidence_files_tool_is_commit_scoped_and_project_routed(self) -> None:
        project = self.make_git_checkout(managed=True)
        server = MCPPlanningBridgeServer(str(project), service_mode=True)
        server.project_registry = self.temp_registry()
        self.register_demo_project(server.project_registry, project)
        fill_packet = {
            "ok": True,
            "source": "submission_evidence_fill",
            "schema_version": "submission_evidence_fill.v1",
            "created_files": ["docs/submission/logo.md"],
            "changed_files": ["docs/chatgpt-app-submission-materials.json", "docs/submission/logo.md"],
            "ready_fields_marked": [],
        }

        with patch("runner.mcp_server.fill_submission_evidence_files", return_value=fill_packet) as fill:
            result = server.call_tool_for_agent(
                "fill_submission_evidence_files",
                {
                    "project_name": "demo-project",
                    "entries": [{"key": "logo", "filename": "logo.md", "content": "reviewed\n"}],
                },
            )

        assert result["ok"] is True
        assert result["tool"] == "fill_submission_evidence_files"
        assert result["data"]["source"] == "submission_evidence_fill"
        fill.assert_called_once()
        assert fill.call_args.args == (str(project),)
        assert fill.call_args.kwargs["entries"] == [{"key": "logo", "filename": "logo.md", "content": "reviewed\n"}]
        assert fill.call_args.kwargs["mark_ready"] is False

    def test_submission_evidence_revision_tool_is_action_scoped_and_project_routed(self) -> None:
        project = self.make_git_checkout(managed=True)
        server = MCPPlanningBridgeServer(str(project), service_mode=True)
        server.project_registry = self.temp_registry()
        self.register_demo_project(server.project_registry, project)
        preview_packet = {
            "ok": True,
            "source": "submission_evidence_revision",
            "schema_version": "submission_evidence_revision.v1",
            "action": "preview",
            "preview_id": "evidence_revision_demo",
            "content_included": False,
            "copyable_apply_call": {
                "tool": "manage_submission_evidence_revision",
                "arguments": {
                    "action": "apply",
                    "preview_id": "evidence_revision_demo",
                    "content": "<resubmit exact content>",
                },
                "required_scope": "mcp:commit",
            },
        }

        with patch("runner.mcp_server.MCPSubmissionEvidenceRevisionManager") as manager_cls:
            manager_cls.return_value.handle.return_value = preview_packet
            result = server.call_tool_for_agent(
                "manage_submission_evidence_revision",
                {
                    "project_name": "demo-project",
                    "action": "preview",
                    "key": "logo",
                    "ref": "docs/submission/logo.md",
                    "content": "# Logo Evidence\n",
                },
            )

        assert result["ok"] is True
        assert result["tool"] == "manage_submission_evidence_revision"
        assert result["data"]["preview_id"] == "evidence_revision_demo"
        assert result["data"]["copyable_apply_call"]["arguments"]["project_name"] == "demo-project"
        manager_cls.assert_called_once_with(str(project))
        assert manager_cls.return_value.handle.call_args.args[0] == "preview"
        assert manager_cls.return_value.handle.call_args.args[1]["content"] == "# Logo Evidence\n"

    def test_mark_submission_evidence_ready_fields_tool_is_commit_scoped_and_project_routed(self) -> None:
        project = self.make_git_checkout(managed=True)
        server = MCPPlanningBridgeServer(str(project), service_mode=True)
        server.project_registry = self.temp_registry()
        self.register_demo_project(server.project_registry, project)
        mark_packet = {
            "ok": True,
            "source": "submission_evidence_mark_ready",
            "schema_version": "submission_evidence_mark_ready.v1",
            "changed_files": ["docs/chatgpt-app-submission-materials.json"],
            "ready_fields_marked": ["logo_ready"],
        }

        with patch("runner.mcp_server.mark_submission_evidence_ready_fields", return_value=mark_packet) as mark:
            result = server.call_tool_for_agent(
                "mark_submission_evidence_ready_fields",
                {
                    "project_name": "demo-project",
                    "keys": ["logo"],
                    "review_confirmation": "human_reviewed",
                },
            )

        assert result["ok"] is True
        assert result["tool"] == "mark_submission_evidence_ready_fields"
        assert result["data"]["source"] == "submission_evidence_mark_ready"
        mark.assert_called_once()
        assert mark.call_args.args == (str(project),)
        assert mark.call_args.kwargs["keys"] == ["logo"]
        assert mark.call_args.kwargs["review_confirmation"] == "human_reviewed"

    def test_agent_consumer_contract_is_read_only_and_guides_standard_envelope(self) -> None:
        project = self.make_git_checkout()
        server = MCPPlanningBridgeServer(str(project), service_mode=True)

        result = server.call_tool_for_agent("get_agent_consumer_contract", {})

        assert result["ok"] is True
        assert result["tool"] == "get_agent_consumer_contract"
        data = result["data"]
        assert data["ok"] is True
        assert data["read_only"] is True
        assert data["side_effects"] is False
        assert data["contract_version"] == "agent_consumer_contract.v1"
        assert data["outer_tool_result_envelope"]["success_required_fields"] == ["ok", "tool", "data"]
        assert data["outer_tool_result_envelope"]["error_required_fields"] == [
            "ok",
            "tool",
            "error_code",
            "message",
            "details",
        ]
        assert data["data_payload_recommendation"]["standard_success_fields"] == [
            "ok",
            "read_only",
            "side_effects",
        ]
        assert data["project_routing_contract"]["missing_project_name_error_code"] == "PROJECT_NAME_REQUIRED"
        assert data["project_routing_contract"]["project_root_override_error_code"] == "PROJECT_ROOT_OVERRIDE_NOT_ALLOWED"
        assert data["authority_boundary"]["read_only_tools_do_not_write_delivery_state"] is True
        assert data["service_entry_profiles_version"] == "service_entry_profiles.v1"
        profiles = {item["profile_id"]: item for item in data["service_entry_profiles"]}
        assert profiles["local_codex_commander"]["consumer_kind"] == "local_codex"
        assert profiles["web_gpt_commander"]["executor_status_polling_guidance"]["max_poll_attempts"] == 3
        assert profiles["local_codex_commander"]["executor_status_polling_guidance"]["max_poll_attempts"] == 24
        assert profiles["planner_agent"]["write_boundary"].endswith("review acceptance.")
        assert profiles["source_observer"]["primary_workflow"] == "source_observation"
        thin_rule = data["thin_loop_consumer_rule"]
        assert "result.codex_execution_packet.packet_status is ready" in thin_rule["m0_m2_direct_mode"]
        assert "result.codex_execution_packet.copy_paste_codex_prompt" in thin_rule["m0_m2_direct_mode"]
        assert "formal thin-loop evidence preview" in thin_rule["provided_mode"]
        assert "executor dispatch" in thin_rule["authority"]

    def test_service_entry_profile_selector_defaults_and_fails_closed(self) -> None:
        project = self.make_git_checkout()
        server = MCPPlanningBridgeServer(str(project), service_mode=True)

        default_result = server.call_tool_for_agent("get_service_entry_profile", {})

        assert default_result["ok"] is True
        assert default_result["tool"] == "get_service_entry_profile"
        default_data = default_result["data"]
        assert default_data["ok"] is True
        assert default_data["read_only"] is True
        assert default_data["side_effects"] is False
        assert default_data["profile_id"] == "web_gpt_commander"
        assert default_data["selected_profile"]["consumer_kind"] == "web_gpt"
        assert default_data["selected_profile"]["executor_status_polling_guidance"]["next_poll_after_seconds"] == 3
        assert default_data["recommended_next_reads"][0]["tool"] == "list_registered_projects"
        assert "tool_search" in default_data["tool_surface_guidance"]["if_tool_not_visible_in_current_apps_surface"]
        assert default_data["tool_surface_guidance"]["http_mcp_fallback"]["endpoint"] == "http://127.0.0.1:8766/mcp"

        reviewer_result = server.call_tool_for_agent("get_service_entry_profile", {"profile_id": "reviewer_agent"})

        assert reviewer_result["ok"] is True
        assert reviewer_result["data"]["selected_profile"]["default_authority"] == "review_only"

        invalid_result = server.call_tool_for_agent("get_service_entry_profile", {"profile_id": "unknown"})

        assert invalid_result["ok"] is False
        assert invalid_result["error_code"] == "UNKNOWN_SERVICE_ENTRY_PROFILE"
        assert "reviewer_agent" in invalid_result["details"]["available_profile_ids"]

    def test_agent_operator_flow_packet_is_role_aware_and_read_only(self) -> None:
        project = self.make_git_checkout(managed=True)
        server = MCPPlanningBridgeServer(str(project), service_mode=True)
        server.project_registry = self.temp_registry()
        self.register_demo_project(server.project_registry, project)

        planner_result = server.call_tool_for_agent(
            "get_agent_operator_flow_packet",
            {
                "project_name": "demo-project",
                "profile_id": "planner_agent",
                "task_brief": "Make the onboarding flow easier for other agents.",
            },
        )

        assert planner_result["ok"] is True
        assert planner_result["tool"] == "get_agent_operator_flow_packet"
        planner = planner_result["data"]
        assert planner["ok"] is True
        assert planner["source"] == "agent_operator_flow_packet"
        assert planner["read_only"] is True
        assert planner["side_effects"] is False
        assert planner["current_state"]["resolved_flow_mode"] == "planning"
        assert planner["primary_next_action"]["tool"] == "run_mcp_workflow"
        assert planner["primary_next_action"]["gate_level"] == "read_only_workflow_packet"
        assert planner["primary_next_action"]["requires_confirmation_before_preview"] is False
        assert planner["primary_next_action"]["requires_confirmation_before_write_or_run"] is False
        assert planner["primary_next_action"]["arguments"]["workflow"] == "thin_governed_loop_preview"
        assert planner["primary_next_action"]["arguments"]["draft_seed"]["goal"].startswith("Make the onboarding")
        assert planner["persona_safe_next_tool"] == "run_mcp_workflow"
        assert planner["requires_confirmation_before_preview"] is False
        assert planner["requires_confirmation_before_write_or_run"] is True
        assert "executor_run" in planner["forbidden_workflows"]
        assert "tool_search" in planner["tool_surface_guidance"]["if_tool_not_visible_in_current_apps_surface"]
        assert planner["tool_surface_guidance"]["http_mcp_fallback"]["method"] == "tools/call"
        assert planner["copyable_tool_call"]["tool"] == "run_mcp_workflow"
        assert planner["authority_boundary"]["does_not_start_executor"] is True
        assert planner["authority_boundary"]["does_not_replace_stable"] is True
        assert any(item["tool"] == "get_stage_parallel_next_action_packet" for item in planner["advanced_actions"])

        reviewer_result = server.call_tool_for_agent(
            "get_agent_operator_flow_packet",
            {"project_name": "demo-project", "profile_id": "reviewer_agent"},
        )
        reviewer = reviewer_result["data"]
        assert reviewer["current_state"]["resolved_flow_mode"] == "review"
        assert reviewer["primary_next_action"]["tool"] == "manage_workflow_run"
        assert reviewer["primary_next_action"]["arguments"]["action"] == "list"
        assert reviewer["primary_next_action"]["gate_level"] == "read_only"
        assert reviewer["persona_safe_next_tool"] == "manage_workflow_run"
        reviewer_tools = {item["tool"] for item in reviewer["advanced_actions"]}
        assert "run_mcp_workflow" not in reviewer_tools
        assert "get_stage_parallel_next_action_packet" not in reviewer_tools
        assert "list_executor_run_reports" not in reviewer_tools
        assert "get_stable_replacement_cadence" not in reviewer_tools
        assert "source_write" in reviewer["forbidden_workflows"]

        source_result = server.call_tool_for_agent(
            "get_agent_operator_flow_packet",
            {"project_name": "demo-project", "profile_id": "source_observer"},
        )
        source = source_result["data"]
        assert source["current_state"]["resolved_flow_mode"] == "source_observation"
        assert source["primary_next_action"]["tool"] == "analyze_project_state"
        assert source["primary_next_action"]["gate_level"] == "read_only"
        source_tools = {item["tool"] for item in source["advanced_actions"]}
        assert "get_runtime_version_status" in source_tools
        assert "run_mcp_workflow" not in source_tools
        assert "get_stage_parallel_next_action_packet" not in source_tools
        assert "list_executor_run_reports" not in source_tools
        assert "get_stable_replacement_cadence" not in source_tools
        assert "managed_workflow_apply" in source["forbidden_workflows"]

    def test_agent_operator_flow_prioritizes_product_console_closeout_followup(self) -> None:
        project = self.make_git_checkout(managed=True)
        server = MCPPlanningBridgeServer(str(project), service_mode=True)
        server.project_registry = self.temp_registry()
        self.register_demo_project(server.project_registry, project)
        product_console = {
            "source": "product_console_map",
            "completion_surface": {
                "source": "product_console_completion_surface",
                "status": "needs_attention",
                "ready": False,
                "gap_count": 1,
                "blocker_codes": [],
                "needs_attention_codes": ["SUBMISSION_EVIDENCE_ACTIVITY_NOT_RECORDED"],
                "followup_queue": {
                    "source": "product_console_closeout_followup_queue",
                    "status": "needs_attention",
                    "total_count": 1,
                    "next_item": {
                        "item_id": "submission_evidence_activity",
                        "label": "Evidence Activity",
                        "primary_tool": "record_product_console_action_result",
                        "required_scope": "mcp:commit",
                        "gate_level": "explicit_apply_or_run_required",
                        "requires_confirmation_before_write_or_run": True,
                        "empty_state": "Record the latest submission evidence activity after refresh/recovery actions.",
                        "primary_action": {
                            "action": "record_submission_evidence_activity",
                            "tool": "record_product_console_action_result",
                            "arguments": {
                                "action_id": "submission_evidence_activity",
                                "tool": "submission_evidence_activity_summary",
                                "mode": "read",
                                "status": "updated",
                                "message": "<operator-confirmed submission evidence activity summary>",
                                "result_ok": True,
                            },
                            "authority": "commit",
                            "why": "Record the latest submission evidence activity summary.",
                        },
                    },
                },
            },
        }

        with (
            patch(
                "runner.mcp_server.build_service_readiness_summary",
                return_value={"status": "ready", "safe_next_actions": [], "primary_blocker": None},
            ),
            patch("runner.mcp_server.build_apps_connector_closeout_packet", return_value={"status": "ready"}),
            patch("runner.mcp_server.build_product_console_map", return_value=product_console) as product_console_builder,
        ):
            result = server.call_tool_for_agent(
                "get_agent_operator_flow_packet",
                {"project_name": "demo-project", "profile_id": "web_gpt_commander"},
            )

        assert result["ok"] is True
        flow = result["data"]
        assert flow["read_only"] is True
        assert flow["side_effects"] is False
        assert flow["current_state"]["product_console"]["completion_status"] == "needs_attention"
        assert flow["current_state"]["product_console"]["followup_queue"]["next_item_id"] == "submission_evidence_activity"
        assert flow["primary_next_action"]["derived_from"] == "product_console_closeout_followup_queue"
        assert flow["primary_next_action"]["action_id"] == "product_console_closeout_submission_evidence_activity"
        assert flow["primary_next_action"]["tool"] == "record_product_console_action_result"
        assert flow["primary_next_action"]["gate_level"] == "explicit_apply_or_run_required"
        assert flow["primary_next_action"]["requires_confirmation_before_write_or_run"] is True
        assert flow["primary_next_action"]["requires_confirmation_before_preview"] is False
        assert flow["copyable_tool_call"]["arguments"]["action_id"] == "submission_evidence_activity"
        assert (
            flow["advanced_context"]["product_console_completion_surface"]["followup_queue"]["source"]
            == "product_console_closeout_followup_queue"
        )
        readiness_projection = product_console_builder.call_args.kwargs["readiness_packet"]
        assert readiness_projection["source"] == "service_readiness_summary_projection"
        assert readiness_projection["authority_boundary"]["does_not_run_remote_preflight"] is True
        assert flow["authority_boundary"]["does_not_commit"] is True

    def test_agent_operator_flow_parallel_stage_reuses_next_action_without_side_effects(self) -> None:
        project = self.make_git_checkout(managed=True)
        server = MCPPlanningBridgeServer(str(project), service_mode=True)
        server.project_registry = self.temp_registry()
        self.register_demo_project(server.project_registry, project)

        result = server.call_tool_for_agent(
            "get_agent_operator_flow_packet",
            {
                "project_name": "demo-project",
                "profile_id": "local_codex_commander",
                "task_mode": "parallel_stage",
                "task_intents": [
                    {
                        "task_id": "docs_flow",
                        "title": "Tighten agent flow docs",
                        "allowed_files": ["docs/USAGE.md"],
                        "surfaces": ["docs"],
                        "risk_level": "low",
                    }
                ],
            },
        )

        assert result["ok"] is True
        data = result["data"]
        assert data["read_only"] is True
        assert data["side_effects"] is False
        assert data["current_state"]["resolved_flow_mode"] == "parallel_stage"
        assert data["primary_next_action"]["derived_from"] == "get_stage_parallel_next_action_packet"
        assert data["primary_next_action"]["copyable_tool_call"]["tool"] == data["copyable_tool_call"]["tool"]
        assert data["primary_next_action"]["gate_level"] in {"read_only", "preview_artifact", "preview_gate"}
        assert data["authority_boundary"]["does_not_create_preview_artifact"] is True
        embedded = data["advanced_context"]["embedded_read_only_packets"]["stage_parallel_next_action_packet"]
        assert embedded["read_only"] is True
        assert embedded["side_effects"] is False

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
        packet = data["result"]["codex_execution_packet"]
        assert packet["packet_status"] == "ready"
        assert packet["direct_execution_ready"] is True
        assert packet["execution_boundary"]["colameta_executor_dispatch_authorized"] is False
        assert packet["execution_boundary"]["commit_or_push_authorized"] is False
        assert packet["copy_paste_codex_prompt"]

    def test_list_executor_run_reports_has_standard_success_shape(self) -> None:
        project = self.make_git_checkout(managed=True)
        server = MCPPlanningBridgeServer(str(project), service_mode=True)
        server.project_registry = self.temp_registry()
        self.register_demo_project(server.project_registry, project)

        result = server.call_tool_for_agent(
            "list_executor_run_reports",
            {"project_name": "demo-project", "limit": 5},
        )

        assert result["ok"] is True
        assert result["tool"] == "list_executor_run_reports"
        data = result["data"]
        assert data["ok"] is True
        assert data["read_only"] is True
        assert data["side_effects"] is False
        assert data["reports"] == []
        assert data["message"] == "No executor run reports found."

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
        assert data["result"]["thin_loop"]["stage_results"]["stage_00_baseline"]["baseline_anchor"] == (
            "baseline_anchor_ready"
        )
        assert data["result"]["thin_loop"]["stage_results"]["stage_01_master_anchor"]["master_registry"] == (
            "master_anchor_verified"
        )
        assert data["result"]["thin_loop"]["stage_results"]["stage_02_stage_taskbook"]["stage_registry"] == (
            "stage_anchor_verified"
        )
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

    def external_oauth_context(self) -> dict:
        return {"mode": "external-oauth", "token": {}, "oauth_provider": _PermissiveOAuthProvider()}

    def test_external_oauth_remote_policy_denies_git_remote_push_apply(self) -> None:
        project = self.make_git_checkout()
        server = MCPPlanningBridgeServer(str(project), service_mode=False)

        result = server.call_tool_for_agent(
            "manage_git_remote",
            {"project_name": "demo-project", "action": "push_apply", "preview_id": "preview-1"},
            auth_context=self.external_oauth_context(),
        )

        assert result["ok"] is False
        assert result["error_code"] == "REMOTE_POLICY_DENIED"
        assert result["details"]["policy"] == "remote_public"
        assert result["details"]["reason_code"] == "REMOTE_MCP_COMMIT_DENIED"

    def test_external_oauth_remote_policy_denies_executor_and_validation_runs(self) -> None:
        project = self.make_git_checkout()
        server = MCPPlanningBridgeServer(str(project), service_mode=False)

        executor_result = server.call_tool_for_agent(
            "manage_executor_workflow",
            {"project_name": "demo-project", "action": "run_once", "preview_id": "exec-preview-1"},
            auth_context=self.external_oauth_context(),
        )
        validation_result = server.call_tool_for_agent(
            "manage_validation_run",
            {"project_name": "demo-project", "action": "run", "preview_id": "validation-preview-1"},
            auth_context=self.external_oauth_context(),
        )

        assert executor_result["ok"] is False
        assert executor_result["error_code"] == "REMOTE_POLICY_DENIED"
        assert executor_result["details"]["reason_code"] == "REMOTE_MCP_COMMIT_DENIED"
        assert validation_result["ok"] is False
        assert validation_result["error_code"] == "REMOTE_POLICY_DENIED"
        assert validation_result["details"]["reason_code"] == "REMOTE_MCP_COMMIT_DENIED"

    def test_external_oauth_remote_policy_denies_plan_scope(self) -> None:
        project = self.make_git_checkout()
        server = MCPPlanningBridgeServer(str(project), service_mode=False)

        result = server.call_tool_for_agent(
            "manage_runner_plan",
            {"action": "apply", "preview_id": "plan-preview-1"},
            auth_context=self.external_oauth_context(),
        )

        assert result["ok"] is False
        assert result["error_code"] == "REMOTE_POLICY_DENIED"
        assert result["details"]["required_scope"] == "mcp:plan"
        assert result["details"]["reason_code"] == "REMOTE_MCP_PLAN_DENIED"

    def test_external_oauth_remote_policy_denies_all_commit_scope_tools(self) -> None:
        project = self.make_git_checkout()
        server = MCPPlanningBridgeServer(str(project), service_mode=False)

        result = server.call_tool_for_agent(
            "manage_project_docs",
            {"project_name": "demo-project", "action": "apply", "preview_id": "doc-preview-1"},
            auth_context=self.external_oauth_context(),
        )

        assert result["ok"] is False
        assert result["error_code"] == "REMOTE_POLICY_DENIED"
        assert result["details"]["policy"] == "remote_public"
        assert result["details"]["required_scope"] == "mcp:commit"
        assert result["details"]["reason_code"] == "REMOTE_MCP_COMMIT_DENIED"

    def test_durable_project_memory_mutations_require_commit_scope(self) -> None:
        project = self.make_git_checkout()
        server = MCPPlanningBridgeServer(str(project), service_mode=False)
        cases = [
            ("manage_project_memory", {"action": "add"}),
            ("manage_project_memory", {"action": "update"}),
            ("manage_project_memory", {"action": "delete"}),
            ("manage_runner_record", {"action": "add"}),
            ("manage_runner_record", {"action": "update"}),
            ("manage_runner_record", {"action": "delete"}),
            ("todo_add", {}),
            ("todo_update", {}),
            ("todo_delete", {}),
            ("decision_add", {}),
            ("decision_update", {}),
            ("decision_delete", {}),
        ]

        for tool_name, params in cases:
            assert server.get_required_scope_for_tool(tool_name, params) == "mcp:commit"

    def test_external_oauth_remote_policy_denies_preview_badged_durable_memory_writes(self) -> None:
        project = self.make_git_checkout()
        server = MCPPlanningBridgeServer(str(project), service_mode=False)
        calls = [
            ("manage_project_memory", {"project_name": "demo-project", "action": "add", "content": "remote write"}),
            ("manage_runner_record", {"project_name": "demo-project", "action": "delete", "id": "rec-1"}),
            ("todo_add", {"project_name": "demo-project", "content": "remote todo"}),
            ("decision_update", {"project_name": "demo-project", "id": "decision-1", "decision": "remote decision"}),
        ]

        for tool_name, params in calls:
            result = server.call_tool_for_agent(
                tool_name,
                params,
                auth_context=self.external_oauth_context(),
            )

            assert result["ok"] is False
            assert result["error_code"] == "REMOTE_POLICY_DENIED"
            assert result["details"]["policy"] == "remote_public"
            assert result["details"]["required_scope"] == "mcp:commit"
            assert result["details"]["reason_code"] == "REMOTE_MCP_COMMIT_DENIED"

    def test_external_oauth_remote_policy_denies_run_mcp_workflow_plan_update_apply(self) -> None:
        project = self.make_git_checkout()
        server = MCPPlanningBridgeServer(str(project), service_mode=False)

        result = server.call_tool_for_agent(
            "run_mcp_workflow",
            {"project_name": "demo-project", "workflow": "plan_update", "phase": "apply"},
            auth_context=self.external_oauth_context(),
        )

        assert result["ok"] is False
        assert result["error_code"] == "REMOTE_POLICY_DENIED"
        assert result["details"]["required_scope"] == "mcp:plan"
        assert result["details"]["reason_code"] == "REMOTE_MCP_PLAN_DENIED"

    def test_external_oauth_remote_policy_denies_docs_update_apply_with_conflicting_preview_phase(self) -> None:
        project = self.make_git_checkout()
        server = MCPPlanningBridgeServer(str(project), service_mode=False)

        result = server.call_tool_for_agent(
            "run_mcp_workflow",
            {
                "project_name": "demo-project",
                "workflow": "docs_update",
                "docs_action": "apply",
                "phase": "preview",
                "preview_id": "doc-preview-1",
            },
            auth_context=self.external_oauth_context(),
        )

        assert result["ok"] is False
        assert result["error_code"] == "REMOTE_POLICY_DENIED"
        assert result["details"]["required_scope"] == "mcp:commit"
        assert result["details"]["reason_code"] == "REMOTE_MCP_COMMIT_DENIED"


if __name__ == "__main__":
    unittest.main()
