from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class RunnerCliProductReadinessTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="colameta-runner-cli-product-")
        self.tmp_path = Path(self._tmp.name)
        self.project = self.tmp_path / "managed-project"
        self.project.mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_doctor_json_outputs_product_readiness_packet(self) -> None:
        from scripts import runner_cli

        packet = {
            "ok": True,
            "source": "product_readiness",
            "status": "ready",
            "ready": True,
            "ops_check": {"beta_gate_ready": True},
        }
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
            patch.object(runner_cli, "build_product_readiness_packet", return_value=packet),
        ):
            result = runner_cli._run_product_doctor(["doctor", str(self.project), "--json"])

        payload = json.loads(stdout.getvalue())
        assert result == 0
        assert stderr.getvalue() == ""
        assert payload["source"] == "product_readiness"
        assert payload["ready"] is True

    def test_connect_chatgpt_json_outputs_read_only_connection_packet(self) -> None:
        from scripts import runner_cli

        packet = {
            "ok": True,
            "source": "chatgpt_connection_readiness",
            "read_only": True,
            "side_effects": False,
            "connector_url": "https://example.test/mcp",
            "status": "ready",
            "ready": True,
        }
        stdout = io.StringIO()
        with (
            contextlib.redirect_stdout(stdout),
            patch.object(runner_cli, "build_chatgpt_connection_packet", return_value=packet) as build_packet,
        ):
            result = runner_cli._run_connect_chatgpt(
                ["connect-chatgpt", str(self.project), "--project-name", "demo-project", "--json"]
            )

        payload = json.loads(stdout.getvalue())
        assert result == 0
        assert payload["read_only"] is True
        assert payload["connector_url"] == "https://example.test/mcp"
        assert build_packet.call_args.kwargs["project_name"] == "demo-project"

    def test_app_smoke_json_outputs_external_handoff_packet(self) -> None:
        from scripts import runner_cli

        packet = {
            "ok": True,
            "source": "apps_connector_smoke_handoff",
            "read_only": True,
            "side_effects": False,
            "status": "needs_attention",
            "safe_next_action": {"tool": "get_apps_connector_smoke_packet"},
        }
        stdout = io.StringIO()
        with (
            contextlib.redirect_stdout(stdout),
            patch.object(runner_cli, "build_apps_connector_smoke_handoff_packet", return_value=packet),
        ):
            result = runner_cli._run_app_smoke(["app-smoke", str(self.project), "--json"])

        payload = json.loads(stdout.getvalue())
        assert result == 0
        assert payload["source"] == "apps_connector_smoke_handoff"
        assert payload["safe_next_action"]["tool"] == "get_apps_connector_smoke_packet"


class RunnerCliConnectorRuntimeHealthTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="colameta-runner-cli-health-")
        self.tmp_path = Path(self._tmp.name)
        self.project = self.tmp_path / "managed-project"
        self.project.mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_connector_runtime_summary_reports_process_table_source_without_secrets(self) -> None:
        from scripts import runner_cli

        stderr = io.StringIO()
        metadata = {
            "pid": 12345,
            "project_root": str(self.project),
            "web_host": "127.0.0.1",
            "web_port": 8801,
            "mcp_host": "127.0.0.1",
            "mcp_port": 8766,
            "web_url": "http://127.0.0.1:8801",
            "mcp_url": "http://127.0.0.1:8766/mcp",
            "enable_web": True,
            "enable_mcp": True,
            "discovered_from_process_table": True,
        }
        runtime_status = {
            "project_checkout_head": "a" * 40,
            "runtime_loaded_code_stale": False,
            "reload_needed_for_verification": False,
            "reload_awareness_reason": "installed_package_matches_project_checkout",
        }

        with (
            contextlib.redirect_stderr(stderr),
            patch.object(runner_cli, "get_runtime_version_status", return_value=runtime_status),
            patch.object(runner_cli, "git_checkout_metadata", return_value={"head": "b" * 40}),
        ):
            runner_cli._print_connector_runtime_health_summary(
                project_path=str(self.project),
                metadata=metadata,
                state="running",
                web_state="healthy",
                mcp_state="healthy",
            )

        output = stderr.getvalue()
        assert "Connector/runtime: local_service=healthy source=process_table external_connector=unverified" in output
        assert "closeout=local_runtime_ready_external_connector_unverified" in output
        assert "LOCAL_SERVICE_HEALTHY" in output
        assert "WEB_ENDPOINT_HEALTHY" in output
        assert "MCP_ENDPOINT_HEALTHY" in output
        assert "CONNECTOR_HEALTH_UNVERIFIED" in output
        assert "Apps connector: status=needs_attention" in output
        assert "project_list=list_registered_projects" in output
        assert "preferred=get_apps_connector_smoke_packet" in output
        assert "fallback=get_connector_runtime_health_status" in output
        assert "metadata=refresh_if_tool_missing" in output
        assert "apps_reauth=reconnect_apps_connector" in output
        assert "Stable cadence: status=dev_ahead_stable" in output
        assert "replacement_required=False" in output
        assert "cadence=batch_when_ready" in output
        assert "batch=None" in output
        assert "size=empty" in output
        assert "posture=continue_batching" in output
        assert "risk=unknown" in output
        assert "review=keep_batching" in output
        assert "token" not in output.lower()
        assert "secret" not in output.lower()

    def test_status_collects_sanitized_tunnel_evidence_when_explicitly_requested(self) -> None:
        from scripts import runner_cli

        class FakeResponse:
            status = 200

            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
                return False

        stderr = io.StringIO()
        requested_urls: list[str] = []
        metadata = {
            "pid": 12345,
            "project_root": str(self.project),
            "web_host": "127.0.0.1",
            "web_port": 8801,
            "mcp_host": "127.0.0.1",
            "mcp_port": 8766,
            "web_url": "http://127.0.0.1:8801",
            "mcp_url": "http://127.0.0.1:8766/mcp",
            "enable_web": True,
            "enable_mcp": True,
            "discovered_from_process_table": False,
        }
        runtime_status = {
            "project_checkout_head": "a" * 40,
            "runtime_loaded_code_stale": False,
            "reload_needed_for_verification": False,
            "reload_awareness_reason": "installed_package_matches_project_checkout",
        }

        def fake_urlopen(url: str, timeout: float = 0) -> FakeResponse:
            requested_urls.append(url)
            return FakeResponse()

        with (
            contextlib.redirect_stderr(stderr),
            patch.object(runner_cli, "_read_service_metadata", return_value=metadata),
            patch.object(runner_cli, "_is_pid_running", return_value=True),
            patch.object(runner_cli, "_probe_service_health", return_value=("healthy", "healthy")),
            patch.object(runner_cli, "get_runtime_version_status", return_value=runtime_status),
            patch.object(runner_cli, "git_checkout_metadata", return_value={"head": "b" * 40}),
            patch.object(runner_cli.urllib.request, "urlopen", side_effect=fake_urlopen),
        ):
            result = runner_cli._run_service_status(
                [
                    "status",
                    str(self.project),
                    "--tunnel-admin-port",
                    "8080",
                    "--tunnel-pid",
                    "4034",
                ]
            )

        output = stderr.getvalue()
        assert result == 0
        assert requested_urls == ["http://127.0.0.1:8080/healthz", "http://127.0.0.1:8080/readyz"]
        assert "external_connector=healthy" in output
        assert "closeout=connector_closeout_ready" in output
        assert "TUNNEL_CLIENT_HEALTHZ_READY" in output
        assert "TUNNEL_CONTROL_PLANE_READYZ_READY" in output
        assert "evidence=tunnel_admin_probe" in output
        assert "Apps connector: status=ready" in output
        assert "closeout=connector_closeout_ready" in output
        assert "decision=ready" in output
        assert "preferred=get_apps_connector_smoke_packet" in output
        assert "apps_reauth=reconnect_apps_connector" in output
        assert "Stable cadence: status=dev_ahead_stable" in output
        assert "replacement_required=False" in output
        assert "batch=None" in output
        assert "size=empty" in output
        assert "review=keep_batching" in output
        assert "token" not in output.lower()
        assert "secret" not in output.lower()

    def test_status_json_outputs_apps_connector_closeout_packet(self) -> None:
        from scripts import runner_cli

        class FakeResponse:
            status = 200

            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
                return False

        stdout = io.StringIO()
        stderr = io.StringIO()
        metadata = {
            "pid": 12345,
            "project_root": str(self.project),
            "web_host": "127.0.0.1",
            "web_port": 8801,
            "mcp_host": "127.0.0.1",
            "mcp_port": 8766,
            "web_url": "http://127.0.0.1:8801",
            "mcp_url": "http://127.0.0.1:8766/mcp",
            "enable_web": True,
            "enable_mcp": True,
            "discovered_from_process_table": False,
        }
        runtime_status = {
            "project_checkout_head": "a" * 40,
            "runtime_loaded_code_stale": False,
            "reload_needed_for_verification": False,
            "reload_awareness_reason": "installed_package_matches_project_checkout",
        }

        with (
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
            patch.object(runner_cli, "_read_service_metadata", return_value=metadata),
            patch.object(runner_cli, "_is_pid_running", return_value=True),
            patch.object(runner_cli, "_probe_service_health", return_value=("healthy", "healthy")),
            patch.object(runner_cli, "get_runtime_version_status", return_value=runtime_status),
            patch.object(runner_cli, "git_checkout_metadata", return_value={"head": "b" * 40}),
            patch.object(runner_cli.urllib.request, "urlopen", return_value=FakeResponse()),
        ):
            result = runner_cli._run_service_status(
                [
                    "status",
                    str(self.project),
                    "--json",
                    "--tunnel-admin-port",
                    "8080",
                    "--tunnel-pid",
                    "4034",
                ]
            )

        payload = json.loads(stdout.getvalue())
        assert result == 0
        assert stderr.getvalue() == ""
        assert payload["ok"] is True
        assert payload["read_only"] is True
        assert payload["service"]["state"] == "running"
        assert payload["connector_runtime_health"]["overall_status"] == "healthy"
        assert payload["apps_connector_closeout"]["status"] == "ready"
        assert payload["apps_connector_smoke_packet"]["preferred"]["tool"] == "get_apps_connector_smoke_packet"
        assert payload["stable_replacement_cadence"]["status"] == "dev_ahead_stable"
        assert payload["stable_replacement_cadence"]["stable_replacement_not_required"] is True
        assert payload["stable_replacement_cadence"]["recommended_cadence"] == "batch_when_ready"
        assert payload["stable_replacement_cadence"]["dev_batch_summary"]["status"] == "unavailable"
        assert payload["stable_replacement_cadence"]["dev_batch_summary"]["commit_count_since_stable"] is None
        assert payload["stable_replacement_cadence"]["batch_review_summary"]["status"] == "unavailable"
        assert (
            payload["stable_replacement_cadence"]["batch_review_summary"]["suggested_review_action"]
            == "keep_batching"
        )
        assert (
            payload["apps_connector_smoke_packet"]["metadata_refresh_guidance"]["expected_tool"]
            == "get_apps_connector_smoke_packet"
        )
        assert (
            payload["apps_connector_closeout"]["connector_closeout_check"]["current_operator_closeout"]
            == "connector_closeout_ready"
        )
        assert payload["tunnel_evidence"]["provided"] is True
        serialized = json.dumps(payload, ensure_ascii=False)
        assert "raw_token" not in serialized.lower()
        assert "secret_value" not in serialized.lower()

    def test_status_tunnel_evidence_requires_port_and_pid_together(self) -> None:
        from scripts import runner_cli

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            result = runner_cli._run_service_status(
                ["status", str(self.project), "--with-tunnel-evidence", "--tunnel-admin-port", "8080"]
            )

        output = stderr.getvalue()
        assert result == 1
        assert "--tunnel-admin-port" in output
        assert "--tunnel-pid" in output

    def test_status_tunnel_evidence_rejects_non_loopback_admin_host(self) -> None:
        from scripts import runner_cli

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            result = runner_cli._run_service_status(
                [
                    "status",
                    str(self.project),
                    "--tunnel-admin-host",
                    "example.com",
                    "--tunnel-admin-port",
                    "8080",
                    "--tunnel-pid",
                    "4034",
                ]
            )

        output = stderr.getvalue()
        assert result == 1
        assert "loopback" in output
        assert "example.com" in output

    def test_ops_check_json_can_fail_on_not_ready_when_explicitly_requested(self) -> None:
        from scripts import runner_cli

        packet = {
            "ok": True,
            "status": "needs_attention",
            "ops_check_ready": True,
            "connector_smoke_ready": False,
            "beta_gate_ready": False,
            "checks": {},
        }
        stdout = io.StringIO()
        with (
            contextlib.redirect_stdout(stdout),
            patch.object(runner_cli, "build_production_ops_packet", return_value=packet),
        ):
            result = runner_cli._run_ops_check(
                [
                    "ops-check",
                    str(self.project),
                    "--json",
                    "--no-network",
                    "--fail-on-not-ready",
                ]
            )

        assert result == 2
        payload = json.loads(stdout.getvalue())
        assert payload["status"] == "needs_attention"
        assert payload["beta_gate_ready"] is False

    def test_ops_check_default_does_not_fail_on_not_ready(self) -> None:
        from scripts import runner_cli

        packet = {
            "ok": True,
            "status": "needs_attention",
            "ops_check_ready": True,
            "connector_smoke_ready": False,
            "beta_gate_ready": False,
            "checks": {},
        }
        stderr = io.StringIO()
        with (
            contextlib.redirect_stderr(stderr),
            patch.object(runner_cli, "build_production_ops_packet", return_value=packet),
        ):
            result = runner_cli._run_ops_check(["ops-check", str(self.project), "--no-network"])

        assert result == 0
        assert "beta_gate_ready=False" in stderr.getvalue()

    def test_ops_check_write_status_rejects_repo_path(self) -> None:
        from scripts import runner_cli

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            result = runner_cli._run_ops_check(
                [
                    "ops-check",
                    str(self.project),
                    "--no-network",
                    "--write-status",
                    str(self.project / "last-status.json"),
                ]
            )

        assert result == 1
        assert "refuses repository paths" in stderr.getvalue()

    def test_ops_check_redacts_secret_like_missing_project_path_before_packet_build(self) -> None:
        from runner.production_ops import REDACTED_PROJECT_ROOT
        from scripts import runner_cli

        secret_dir_name = "project-sk-not-a-real-token-value"
        missing_project = self.tmp_path / secret_dir_name
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
            patch.object(
                runner_cli,
                "build_production_ops_packet",
                side_effect=AssertionError("missing project path should be rejected before packet build"),
            ),
        ):
            result = runner_cli._run_ops_check(["ops-check", str(missing_project), "--no-network"])

        assert result == 1
        assert stdout.getvalue() == ""
        output = stderr.getvalue()
        assert "项目目录不存在" in output
        assert REDACTED_PROJECT_ROOT in output
        assert secret_dir_name not in output
        assert "sk-not-a-real-token-value" not in output

    def test_ops_check_write_status_accepts_local_state_path(self) -> None:
        from scripts import runner_cli

        packet = {
            "ok": True,
            "status": "ready",
            "ops_check_ready": True,
            "connector_smoke_ready": True,
            "beta_gate_ready": True,
            "checks": {},
        }
        status_path = self.tmp_path / "state" / "last-status.json"
        stdout = io.StringIO()
        with (
            contextlib.redirect_stdout(stdout),
            patch.object(runner_cli, "build_production_ops_packet", return_value=packet),
        ):
            result = runner_cli._run_ops_check(
                [
                    "ops-check",
                    str(self.project),
                    "--no-network",
                    "--json",
                    "--write-status",
                    str(status_path),
                ]
            )

        assert result == 0
        assert status_path.exists()
        written = json.loads(status_path.read_text(encoding="utf-8"))
        assert written["beta_gate_ready"] is True
        payload = json.loads(stdout.getvalue())
        assert payload["status_written_path"] == str(status_path)

    def test_ops_check_write_status_handles_io_failure(self) -> None:
        from scripts import runner_cli

        packet = {
            "ok": True,
            "status": "ready",
            "ops_check_ready": True,
            "connector_smoke_ready": True,
            "beta_gate_ready": True,
            "checks": {},
        }
        stderr = io.StringIO()
        with (
            contextlib.redirect_stderr(stderr),
            patch.object(runner_cli, "build_production_ops_packet", return_value=packet),
            patch.object(runner_cli, "write_status_packet", side_effect=OSError("disk full")),
        ):
            result = runner_cli._run_ops_check(
                [
                    "ops-check",
                    str(self.project),
                    "--no-network",
                    "--write-status",
                    str(self.tmp_path / "state" / "last-status.json"),
                ]
            )

        assert result == 1
        output = stderr.getvalue()
        assert "ops-check 写 status 失败" in output
        assert "disk full" in output

    def test_ops_check_rejects_secret_like_status_path_before_write(self) -> None:
        from scripts import runner_cli

        status_path = self.tmp_path / "state" / "sk-not-a-real-token-value" / "last-status.json"
        stderr = io.StringIO()
        stdout = io.StringIO()
        with (
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
            patch.object(
                runner_cli,
                "build_production_ops_packet",
                side_effect=AssertionError("status path should be rejected before packet build"),
            ),
        ):
            result = runner_cli._run_ops_check(
                [
                    "ops-check",
                    str(self.project),
                    "--no-network",
                    "--json",
                    "--write-status",
                    str(status_path),
                ]
            )

        assert result == 1
        assert not status_path.exists()
        assert not status_path.parent.exists()
        assert stdout.getvalue() == ""
        output = stderr.getvalue()
        assert "secret-like" in output
        assert "sk-not-a-real-token-value" not in output


if __name__ == "__main__":
    unittest.main()
