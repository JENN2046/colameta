from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import patch

from runner.cloud_agent_client import CloudRelayToolBridge, RelayRequest
from runner.cloud_pairing import CloudAgentCredential
from runner.mcp_server import MCPPlanningBridgeServer
from runner.project_registry import ProjectRegistry
from runner.runtime_observability import (
    build_apps_connector_closeout_packet,
    build_service_readiness_summary,
    build_stable_replacement_cadence,
    get_connector_runtime_health_status,
)


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
        assert "get_web_gpt_service_entrypoint" in tool_defs
        assert "get_commander_app_manifest" in tool_defs
        assert "render_commander_app" in tool_defs
        assert "get_apps_connector_smoke_packet" in tool_defs
        assert "get_stable_replacement_cadence" in tool_defs
        assert "get_stage_parallel_plan_preview" in tool_defs
        assert "get_stage_parallel_run_preview" in tool_defs
        assert "get_stage_parallel_worktree_assignment_preview" in tool_defs
        assert "get_stage_parallel_executor_group_preview" in tool_defs
        assert "get_stage_parallel_executor_results_packet" in tool_defs
        assert "get_stage_parallel_group_status" in tool_defs
        assert "get_stage_parallel_merge_preview" in tool_defs
        assert "get_stage_parallel_closeout_packet" in tool_defs
        assert "manage_stage_parallel_worktrees" in tool_defs
        assert "manage_stage_parallel_executor_group" in tool_defs
        assert "manage_stage_parallel_executor_runs" in tool_defs
        assert "get_connector_runtime_health_status" in tool_defs
        commander_schema = tool_defs["get_commander_app_manifest"].input_schema
        assert commander_schema["properties"]["tunnel_client"]["additionalProperties"] is False
        assert commander_schema["properties"]["control_plane"]["additionalProperties"] is False
        assert tool_defs["get_commander_app_manifest"].title == "Get Commander App Manifest"
        assert tool_defs["render_commander_app"].title == "Render Commander App"
        assert tool_defs["get_apps_connector_smoke_packet"].title == "Get Apps Connector Smoke Packet"
        assert tool_defs["get_stable_replacement_cadence"].title == "Get Stable Replacement Cadence"
        assert tool_defs["get_stage_parallel_plan_preview"].title == "Get Stage Parallel Plan Preview"
        assert tool_defs["get_stage_parallel_run_preview"].title == "Get Stage Parallel Run Preview"
        assert tool_defs["get_stage_parallel_worktree_assignment_preview"].title == "Get Stage Parallel Worktree Assignment Preview"
        assert tool_defs["get_stage_parallel_executor_group_preview"].title == "Get Stage Parallel Executor Group Preview"
        assert tool_defs["get_stage_parallel_executor_results_packet"].title == "Get Stage Parallel Executor Results Packet"
        assert tool_defs["get_stage_parallel_group_status"].title == "Get Stage Parallel Group Status"
        assert tool_defs["get_stage_parallel_merge_preview"].title == "Get Stage Parallel Merge Preview"
        assert tool_defs["get_stage_parallel_closeout_packet"].title == "Get Stage Parallel Closeout Packet"
        assert tool_defs["manage_stage_parallel_worktrees"].title == "Manage Stage Parallel Worktrees"
        assert tool_defs["manage_stage_parallel_executor_group"].title == "Manage Stage Parallel Executor Group"
        assert tool_defs["manage_stage_parallel_executor_runs"].title == "Manage Stage Parallel Executor Runs"
        assert tool_defs["render_commander_app"].meta["ui"]["resourceUri"] == "ui://colameta/commander/v1.html"
        assert tool_defs["render_commander_app"].meta["ui"]["visibility"] == ["model", "app"]
        assert tool_defs["get_commander_app_manifest"].annotations["idempotentHint"] is True
        assert tool_defs["render_commander_app"].annotations["readOnlyHint"] is True
        assert tool_defs["render_commander_app"].annotations["idempotentHint"] is True
        connector_schema = tool_defs["get_connector_runtime_health_status"].input_schema
        assert connector_schema["properties"]["tunnel_client"]["additionalProperties"] is False
        assert connector_schema["properties"]["control_plane"]["additionalProperties"] is False
        assert "get_stable_promotion_readiness" in tool_defs
        assert "get_agent_consumer_contract" in server._visible_tool_names()
        assert "get_service_entry_profile" in server._visible_tool_names()
        assert "get_web_gpt_service_entrypoint" in server._visible_tool_names()
        assert "get_commander_app_manifest" in server._visible_tool_names()
        assert "render_commander_app" in server._visible_tool_names()
        assert "get_apps_connector_smoke_packet" in server._visible_tool_names()
        assert "get_stable_replacement_cadence" in server._visible_tool_names()
        assert "get_stage_parallel_plan_preview" in server._visible_tool_names()
        assert "get_stage_parallel_run_preview" in server._visible_tool_names()
        assert "get_stage_parallel_worktree_assignment_preview" in server._visible_tool_names()
        assert "get_stage_parallel_executor_group_preview" in server._visible_tool_names()
        assert "get_stage_parallel_executor_results_packet" in server._visible_tool_names()
        assert "get_stage_parallel_group_status" in server._visible_tool_names()
        assert "get_stage_parallel_merge_preview" in server._visible_tool_names()
        assert "get_stage_parallel_closeout_packet" in server._visible_tool_names()
        assert "manage_stage_parallel_worktrees" in server._visible_tool_names()
        assert "manage_stage_parallel_executor_group" in server._visible_tool_names()
        assert "manage_stage_parallel_executor_runs" in server._visible_tool_names()
        assert "get_connector_runtime_health_status" in server._visible_tool_names()
        assert "get_stable_promotion_readiness" in server._visible_tool_names()
        assert server.get_required_scope_for_tool("get_agent_consumer_contract", {}) == "mcp:read"
        assert server.get_required_scope_for_tool("get_service_entry_profile", {}) == "mcp:read"
        assert server.get_required_scope_for_tool("get_web_gpt_service_entrypoint", {}) == "mcp:read"
        assert server.get_required_scope_for_tool("get_commander_app_manifest", {}) == "mcp:read"
        assert server.get_required_scope_for_tool("render_commander_app", {}) == "mcp:read"
        assert server.get_required_scope_for_tool("get_apps_connector_smoke_packet", {}) == "mcp:read"
        assert server.get_required_scope_for_tool("get_stable_replacement_cadence", {}) == "mcp:read"
        assert server.get_required_scope_for_tool("get_stage_parallel_plan_preview", {}) == "mcp:read"
        assert server.get_required_scope_for_tool("get_stage_parallel_run_preview", {}) == "mcp:read"
        assert server.get_required_scope_for_tool("get_stage_parallel_worktree_assignment_preview", {}) == "mcp:read"
        assert server.get_required_scope_for_tool("get_stage_parallel_executor_group_preview", {}) == "mcp:read"
        assert server.get_required_scope_for_tool("get_stage_parallel_executor_results_packet", {}) == "mcp:read"
        assert server.get_required_scope_for_tool("get_stage_parallel_group_status", {}) == "mcp:read"
        assert server.get_required_scope_for_tool("get_stage_parallel_merge_preview", {}) == "mcp:read"
        assert server.get_required_scope_for_tool("get_stage_parallel_closeout_packet", {}) == "mcp:read"
        assert server.get_required_scope_for_tool("manage_stage_parallel_worktrees", {"action": "status"}) == "mcp:read"
        assert server.get_required_scope_for_tool("manage_stage_parallel_worktrees", {"action": "preview"}) == "mcp:preview"
        assert server.get_required_scope_for_tool("manage_stage_parallel_worktrees", {"action": "discard"}) == "mcp:preview"
        assert server.get_required_scope_for_tool("manage_stage_parallel_worktrees", {"action": "apply"}) == "mcp:commit"
        assert server.get_required_scope_for_tool("manage_stage_parallel_executor_group", {"action": "status"}) == "mcp:read"
        assert server.get_required_scope_for_tool("manage_stage_parallel_executor_group", {"action": "preview"}) == "mcp:preview"
        assert server.get_required_scope_for_tool("manage_stage_parallel_executor_group", {"action": "discard"}) == "mcp:preview"
        assert server.get_required_scope_for_tool("manage_stage_parallel_executor_group", {"action": "apply"}) == "mcp:commit"
        assert server.get_required_scope_for_tool("manage_stage_parallel_executor_runs", {"action": "status"}) == "mcp:read"
        assert server.get_required_scope_for_tool("manage_stage_parallel_executor_runs", {"action": "preview"}) == "mcp:preview"
        assert server.get_required_scope_for_tool("manage_stage_parallel_executor_runs", {"action": "discard"}) == "mcp:preview"
        assert server.get_required_scope_for_tool("manage_stage_parallel_executor_runs", {"action": "apply"}) == "mcp:commit"
        assert server.get_required_scope_for_tool("get_connector_runtime_health_status", {}) == "mcp:read"
        assert server.get_required_scope_for_tool("get_stable_promotion_readiness", {}) == "mcp:read"
        widget_html = server._commander_widget_html()
        assert "Readiness" in widget_html
        assert "Next Step" in widget_html
        assert "Primary blocker" in widget_html
        assert "Safe next action" in widget_html
        assert "get_apps_connector_smoke_packet" in widget_html
        assert "get_stable_replacement_cadence" in widget_html

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
        assert profiles["web_gpt_commander"]["first_reads"][3]["tool"] == "render_commander_app"
        assert profiles["reviewer_agent"]["default_authority"] == "review_only"
        assert data["entry_sequence"][0]["tool"] == "list_registered_projects"
        assert data["entry_sequence"][1]["tool"] == "get_agent_consumer_contract"
        assert data["entry_sequence"][2]["tool"] == "get_service_entry_profile"
        assert data["entry_sequence"][3]["tool"] == "render_commander_app"
        assert data["entry_sequence"][4]["tool"] == "get_stable_replacement_cadence"
        assert data["entry_sequence"][5]["tool"] == "get_stage_parallel_plan_preview"
        assert data["entry_sequence"][6]["tool"] == "get_stage_parallel_run_preview"
        assert data["entry_sequence"][7]["tool"] == "get_stage_parallel_worktree_assignment_preview"
        assert data["entry_sequence"][8]["tool"] == "get_stage_parallel_executor_group_preview"
        assert data["entry_sequence"][9]["tool"] == "manage_stage_parallel_executor_runs"
        assert data["entry_sequence"][10]["tool"] == "get_stage_parallel_executor_results_packet"
        assert data["entry_sequence"][11]["tool"] == "get_stage_parallel_group_status"
        assert data["entry_sequence"][12]["tool"] == "get_stage_parallel_merge_preview"
        assert data["entry_sequence"][13]["tool"] == "get_stage_parallel_closeout_packet"
        assert data["entry_sequence"][14]["tool"] == "get_stable_promotion_readiness"
        assert data["entry_sequence"][15]["tool"] == "get_apps_connector_smoke_packet"
        assert data["entry_sequence"][16]["tool"] == "get_connector_runtime_health_status"
        assert data["entry_sequence"][17]["tool"] == "analyze_project_state"
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

        result = server.call_tool_for_agent(
            "get_commander_app_manifest",
            {
                "project_name": "demo-project",
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
        assert data["project_name"] == "demo-project"
        assert data["connector"]["external_connector_status"] == "healthy"
        assert data["readiness"]["status"] in {"ready", "needs_attention", "blocked"}
        assert data["readiness"]["read_only"] is True
        assert data["readiness"]["components"]["operator_closeout"]["status"]
        assert data["readiness"]["safe_next_actions"][0]["authority"] in {"read_only", "preview_or_task_packet_only"}
        assert data["apps_connector_closeout"]["status"] in {"ready", "needs_attention"}
        assert data["apps_connector_closeout"]["project_list_check"]["tool"] == "list_registered_projects"
        assert data["apps_connector_closeout"]["connector_closeout_check"]["tool"] == "get_connector_runtime_health_status"
        assert "apps_connector_closeout" in data["commander_panel"]["primary_sections"]
        assert any(
            item["tool"] == "get_connector_runtime_health_status"
            and "tunnel_client" in item.get("arguments", {})
            for item in data["commander_panel"]["read_actions"]
        )
        assert "service_readiness" in data["commander_panel"]["primary_sections"]
        assert data["authority_boundary"]["does_not_authorize_executor_run"] is True
        assert "Delivery accepted" in data["authority_boundary"]["requires_explicit_commander_authorization_for"]

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

        reviewer_result = server.call_tool_for_agent("get_service_entry_profile", {"profile_id": "reviewer_agent"})

        assert reviewer_result["ok"] is True
        assert reviewer_result["data"]["selected_profile"]["default_authority"] == "review_only"

        invalid_result = server.call_tool_for_agent("get_service_entry_profile", {"profile_id": "unknown"})

        assert invalid_result["ok"] is False
        assert invalid_result["error_code"] == "UNKNOWN_SERVICE_ENTRY_PROFILE"
        assert "reviewer_agent" in invalid_result["details"]["available_profile_ids"]

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
