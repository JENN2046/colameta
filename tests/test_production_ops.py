from __future__ import annotations

import json
import subprocess
import tarfile
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch


HEAD = "a" * 40
NOW = datetime(2026, 7, 7, 0, 0, tzinfo=timezone.utc)


def completed(args: list[str], stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args, returncode, stdout=stdout, stderr="")


class FakeCommandRunner:
    def __init__(
        self,
        *,
        head: str = HEAD,
        systemd_active: bool = True,
        systemd_output: str | None = None,
        curl_ok: bool = True,
        web_health_payload: dict[str, object] | None = None,
        mcp_health_payload: dict[str, object] | None = None,
        cat_file_ok: bool = True,
    ) -> None:
        self.head = head
        self.systemd_active = systemd_active
        self.systemd_output = systemd_output
        self.curl_ok = curl_ok
        self.web_health_payload = web_health_payload or {
            "ok": True,
            "service": "colameta-web-console",
            "loaded_runtime_head": head,
            "runtime_loaded_code_stale": False,
            "reload_needed_for_verification": False,
            "installed_package_project_source_clean": True,
            "installed_package_source_cleanliness_status": "clean",
        }
        self.mcp_health_payload = mcp_health_payload or {
            "ok": True,
            "service": "colameta-mcp",
            "loaded_runtime_head": head,
            "runtime_loaded_code_stale": False,
            "reload_needed_for_verification": False,
            "installed_package_project_source_clean": True,
            "installed_package_source_cleanliness_status": "clean",
        }
        self.cat_file_ok = cat_file_ok
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        self.calls.append(args)
        if args[:2] == ["git", "-C"] and args[-2:] == ["rev-parse", "HEAD"]:
            return completed(args, f"{self.head}\n")
        if args[:2] == ["git", "-C"] and args[-2:] == ["rev-parse", "origin/main"]:
            return completed(args, f"{self.head}\n")
        if args[:2] == ["git", "-C"] and args[-3:-1] == ["cat-file", "-e"]:
            return completed(args, "", 0 if self.cat_file_ok else 1)
        if args[:3] == ["systemctl", "--user", "show"]:
            if self.systemd_output is not None:
                return completed(args, self.systemd_output)
            if self.systemd_active:
                return completed(args, "MainPID=123\nActiveState=active\nSubState=running\n")
            return completed(args, "MainPID=0\nActiveState=inactive\nSubState=dead\n")
        if args[:2] == ["curl", "-fsS"]:
            if not self.curl_ok:
                return completed(args, "", 22)
            payload = self.web_health_payload if args[-1].endswith("/api/healthz") else self.mcp_health_payload
            return completed(args, f"{json.dumps(payload)}\n200")
        return completed(args, "")


def ready_preflight(public_base_url: str, **kwargs: object) -> dict[str, object]:
    no_network = bool(kwargs.get("no_network"))
    expected_head = kwargs.get("expected_head")
    expected_runtime_head = expected_head if isinstance(expected_head, str) else None
    healthz_runtime = None
    if expected_runtime_head:
        healthz_runtime = {
            "loaded_runtime_head": expected_runtime_head,
            "runtime_loaded_code_stale": False,
            "reload_needed_for_verification": False,
            "installed_package_project_source_clean": True,
            "installed_package_source_cleanliness_status": "clean",
        }
    return {
        "ok": True,
        "public_base_url": public_base_url,
        "connector_url": f"{public_base_url}/mcp",
        "network_check": "not_run" if no_network else "run",
        "expected_runtime_head": expected_runtime_head,
        "healthz_runtime": healthz_runtime,
        "failures": [],
    }


def failed_preflight(public_base_url: str, **_: object) -> dict[str, object]:
    return {
        "ok": False,
        "public_base_url": public_base_url,
        "network_check": "run",
        "failures": ["healthz failed"],
    }


class ProductionOpsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="colameta-production-ops-")
        self.tmp_path = Path(self._tmp.name)
        self.project = self.tmp_path / "project"
        self.project.mkdir()
        self.stable = self.tmp_path / "stable"
        self.stable.mkdir()
        self.backups = self.tmp_path / "backups"
        self.backups.mkdir()
        self._write_backup("stable-before-test.tar.gz")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write_backup(self, name: str) -> None:
        payload = self.tmp_path / "payload.txt"
        payload.write_text("ok\n", encoding="utf-8")
        with tarfile.open(self.backups / name, "w:gz") as archive:
            archive.add(payload, arcname="colameta/payload.txt")

    def test_all_green_with_fresh_connector_smoke_sets_beta_gate_ready(self) -> None:
        from runner.production_ops import build_production_ops_packet

        packet = build_production_ops_packet(
            str(self.project),
            expected_head=HEAD,
            stable_runtime_dir=str(self.stable),
            backup_dir=str(self.backups),
            connector_smoke={"status": "ready", "last_observed_at": "2026-07-07T00:00:00Z"},
            command_runner=FakeCommandRunner(),
            preflight_runner=ready_preflight,
            now=NOW,
        )

        assert packet["status"] == "ready"
        assert packet["ops_check_ready"] is True
        assert packet["connector_smoke_ready"] is True
        assert packet["beta_gate_ready"] is True
        assert packet["checks"]["remote_https_mcp_preflight"]["reason_code"] == "REMOTE_PREFLIGHT_READY"
        assert packet["checks"]["remote_https_mcp_preflight"]["network_check"] == "run"
        assert packet["checks"]["backup_inventory"]["backup_sha256"]
        assert packet["checks"]["rollback_rehearsal"]["rehearsal_executed_restore"] is False

    def test_omitted_expected_head_falls_back_to_candidate_head(self) -> None:
        from runner.production_ops import build_production_ops_packet

        packet = build_production_ops_packet(
            str(self.project),
            stable_runtime_dir=str(self.stable),
            backup_dir=str(self.backups),
            connector_smoke={"status": "ready", "last_observed_at": "2026-07-07T00:00:00Z"},
            command_runner=FakeCommandRunner(),
            preflight_runner=ready_preflight,
            now=NOW,
        )

        assert packet["expected_head"] == HEAD
        assert packet["checks"]["candidate_head"]["expected_stable_head"] == HEAD
        assert packet["status"] == "ready"

    def test_invalid_explicit_expected_head_blocks_without_fallback(self) -> None:
        from runner.production_ops import build_production_ops_packet

        packet = build_production_ops_packet(
            str(self.project),
            expected_head="abc123",
            stable_runtime_dir=str(self.stable),
            backup_dir=str(self.backups),
            connector_smoke={"status": "ready", "last_observed_at": "2026-07-07T00:00:00Z"},
            command_runner=FakeCommandRunner(),
            preflight_runner=ready_preflight,
            now=NOW,
        )

        assert packet["status"] == "blocked"
        assert packet["ops_check_ready"] is False
        assert packet["beta_gate_ready"] is False
        assert packet["expected_head"] is None
        assert "expected_stable_head" not in packet["checks"]["candidate_head"]
        assert packet["checks"]["expected_head"]["reason_code"] == "EXPECTED_HEAD_INVALID"
        assert "EXPECTED_HEAD_INVALID" in packet["blocker_codes"]
        assert packet["checks"]["secret_redaction"]["status"] == "ready"

    def test_no_network_preflight_needs_attention_and_cannot_set_beta_gate_ready(self) -> None:
        from runner.production_ops import build_production_ops_packet

        packet = build_production_ops_packet(
            str(self.project),
            expected_head=HEAD,
            stable_runtime_dir=str(self.stable),
            backup_dir=str(self.backups),
            no_network=True,
            connector_smoke={"status": "ready", "last_observed_at": "2026-07-07T00:00:00Z"},
            command_runner=FakeCommandRunner(),
            preflight_runner=ready_preflight,
            now=NOW,
        )

        assert packet["status"] == "needs_attention"
        assert packet["ops_check_ready"] is False
        assert packet["connector_smoke_ready"] is True
        assert packet["beta_gate_ready"] is False
        assert packet["checks"]["remote_https_mcp_preflight"]["reason_code"] == "REMOTE_PREFLIGHT_NOT_RUN"
        assert "REMOTE_PREFLIGHT_NOT_RUN" in packet["needs_attention_codes"]

    def test_loopback_http_no_network_preflight_uses_local_http_allowance(self) -> None:
        from runner.production_ops import build_production_ops_packet

        packet = build_production_ops_packet(
            str(self.project),
            public_base_url="http://127.0.0.1:8766",
            expected_head=HEAD,
            stable_runtime_dir=str(self.stable),
            backup_dir=str(self.backups),
            no_network=True,
            connector_smoke={"status": "ready", "last_observed_at": "2026-07-07T00:00:00Z"},
            command_runner=FakeCommandRunner(),
            now=NOW,
        )

        assert packet["public_base_url"] == "http://127.0.0.1:8766"
        assert packet["checks"]["remote_https_mcp_preflight"]["reason_code"] == "REMOTE_PREFLIGHT_NOT_RUN"
        assert packet["status"] == "needs_attention"

    def test_remote_preflight_runner_receives_loopback_http_allowance(self) -> None:
        from runner.production_ops import build_production_ops_packet

        observed: dict[str, object] = {}

        def capturing_preflight(public_base_url: str, **kwargs: object) -> dict[str, object]:
            observed["public_base_url"] = public_base_url
            observed.update(kwargs)
            return ready_preflight(public_base_url, **kwargs)

        packet = build_production_ops_packet(
            str(self.project),
            public_base_url="http://localhost:8766/",
            expected_head=HEAD,
            stable_runtime_dir=str(self.stable),
            backup_dir=str(self.backups),
            no_network=True,
            connector_smoke={"status": "ready", "last_observed_at": "2026-07-07T00:00:00Z"},
            command_runner=FakeCommandRunner(),
            preflight_runner=capturing_preflight,
            now=NOW,
        )

        assert observed["public_base_url"] == "http://localhost:8766"
        assert observed["allow_local_http"] is True
        assert observed["no_network"] is True
        assert observed["expected_head"] == HEAD
        assert packet["checks"]["remote_https_mcp_preflight"]["reason_code"] == "REMOTE_PREFLIGHT_NOT_RUN"

    def test_loopback_http_network_preflight_cannot_satisfy_beta_gate(self) -> None:
        from runner.production_ops import build_production_ops_packet

        def fail_if_called(public_base_url: str, **kwargs: object) -> dict[str, object]:
            raise AssertionError(f"preflight should not probe loopback HTTP in network mode: {public_base_url} {kwargs}")

        packet = build_production_ops_packet(
            str(self.project),
            public_base_url="http://127.0.0.1:8766",
            expected_head=HEAD,
            stable_runtime_dir=str(self.stable),
            backup_dir=str(self.backups),
            connector_smoke={"status": "ready", "last_observed_at": "2026-07-07T00:00:00Z"},
            command_runner=FakeCommandRunner(),
            preflight_runner=fail_if_called,
            now=NOW,
        )

        assert packet["status"] == "needs_attention"
        assert packet["ops_check_ready"] is False
        assert packet["connector_smoke_ready"] is True
        assert packet["beta_gate_ready"] is False
        assert packet["checks"]["remote_https_mcp_preflight"]["reason_code"] == "REMOTE_PREFLIGHT_LOCAL_HTTP_NOT_REMOTE"
        assert "REMOTE_PREFLIGHT_LOCAL_HTTP_NOT_REMOTE" in packet["needs_attention_codes"]

    def test_loopback_https_public_base_url_is_rejected_before_remote_preflight(self) -> None:
        from runner.production_ops import REDACTED_PUBLIC_BASE_URL, build_production_ops_packet

        def fail_if_called(public_base_url: str, **kwargs: object) -> dict[str, object]:
            raise AssertionError(f"preflight should not probe loopback HTTPS: {public_base_url} {kwargs}")

        packet = build_production_ops_packet(
            str(self.project),
            public_base_url="https://127.0.0.1:8766",
            expected_head=HEAD,
            stable_runtime_dir=str(self.stable),
            backup_dir=str(self.backups),
            connector_smoke={"status": "ready", "last_observed_at": "2026-07-07T00:00:00Z"},
            command_runner=FakeCommandRunner(),
            preflight_runner=fail_if_called,
            now=NOW,
        )

        assert packet["status"] == "blocked"
        assert packet["ops_check_ready"] is False
        assert packet["public_base_url"] == REDACTED_PUBLIC_BASE_URL
        assert packet["checks"]["remote_https_mcp_preflight"]["reason_code"] == "PUBLIC_BASE_URL_REJECTED"
        assert "PUBLIC_BASE_URL_REJECTED" in packet["blocker_codes"]

    def test_private_https_public_base_url_is_rejected_before_remote_preflight(self) -> None:
        from runner.production_ops import REDACTED_PUBLIC_BASE_URL, build_production_ops_packet

        def fail_if_called(public_base_url: str, **kwargs: object) -> dict[str, object]:
            raise AssertionError(f"preflight should not probe private HTTPS: {public_base_url} {kwargs}")

        packet = build_production_ops_packet(
            str(self.project),
            public_base_url="https://192.168.1.10:8766",
            expected_head=HEAD,
            stable_runtime_dir=str(self.stable),
            backup_dir=str(self.backups),
            connector_smoke={"status": "ready", "last_observed_at": "2026-07-07T00:00:00Z"},
            command_runner=FakeCommandRunner(),
            preflight_runner=fail_if_called,
            now=NOW,
        )

        assert packet["status"] == "blocked"
        assert packet["ops_check_ready"] is False
        assert packet["public_base_url"] == REDACTED_PUBLIC_BASE_URL
        assert packet["checks"]["remote_https_mcp_preflight"]["reason_code"] == "PUBLIC_BASE_URL_REJECTED"
        assert "PUBLIC_BASE_URL_REJECTED" in packet["blocker_codes"]

    def test_remote_preflight_blocks_when_public_healthz_runtime_is_stale(self) -> None:
        from runner.production_ops import build_production_ops_packet

        stale_head = "b" * 40

        def stale_runtime_preflight(public_base_url: str, **kwargs: object) -> dict[str, object]:
            return {
                "ok": True,
                "public_base_url": public_base_url,
                "connector_url": f"{public_base_url}/mcp",
                "network_check": "run",
                "expected_runtime_head": kwargs.get("expected_head"),
                "healthz_runtime": {
                    "loaded_runtime_head": stale_head,
                    "runtime_loaded_code_stale": False,
                    "reload_needed_for_verification": False,
                    "installed_package_project_source_clean": True,
                    "installed_package_source_cleanliness_status": "clean",
                },
                "failures": [],
            }

        packet = build_production_ops_packet(
            str(self.project),
            expected_head=HEAD,
            stable_runtime_dir=str(self.stable),
            backup_dir=str(self.backups),
            connector_smoke={"status": "ready", "last_observed_at": "2026-07-07T00:00:00Z"},
            command_runner=FakeCommandRunner(),
            preflight_runner=stale_runtime_preflight,
            now=NOW,
        )

        check = packet["checks"]["remote_https_mcp_preflight"]
        assert packet["status"] == "blocked"
        assert packet["ops_check_ready"] is False
        assert check["reason_code"] == "REMOTE_PREFLIGHT_RUNTIME_UNVERIFIED"
        assert check["expected_runtime_head"] == HEAD
        assert check["healthz_runtime"]["loaded_runtime_head"] == stale_head
        assert "REMOTE_PREFLIGHT_RUNTIME_UNVERIFIED" in packet["blocker_codes"]

    def test_systemd_keyed_output_is_order_independent(self) -> None:
        from runner.production_ops import build_production_ops_packet

        packet = build_production_ops_packet(
            str(self.project),
            expected_head=HEAD,
            stable_runtime_dir=str(self.stable),
            backup_dir=str(self.backups),
            connector_smoke={"status": "ready", "last_observed_at": "2026-07-07T00:00:00Z"},
            command_runner=FakeCommandRunner(systemd_output="SubState=running\nMainPID=123\nActiveState=active\n"),
            preflight_runner=ready_preflight,
            now=NOW,
        )

        assert packet["status"] == "ready"
        assert packet["checks"]["stable_service"]["status"] == "ready"
        assert packet["checks"]["stable_service"]["main_pid"] == "123"

    def test_stable_inactive_is_blocked(self) -> None:
        from runner.production_ops import build_production_ops_packet

        packet = build_production_ops_packet(
            str(self.project),
            expected_head=HEAD,
            stable_runtime_dir=str(self.stable),
            backup_dir=str(self.backups),
            connector_smoke={"status": "ready", "last_observed_at": "2026-07-07T00:00:00Z"},
            command_runner=FakeCommandRunner(systemd_active=False),
            preflight_runner=ready_preflight,
            now=NOW,
        )

        assert packet["status"] == "blocked"
        assert packet["ops_check_ready"] is False
        assert "SYSTEMD_SERVICE_NOT_RUNNING" in packet["blocker_codes"]

    def test_local_health_requires_colameta_web_and_mcp_services(self) -> None:
        from runner.production_ops import build_production_ops_packet

        packet = build_production_ops_packet(
            str(self.project),
            expected_head=HEAD,
            stable_runtime_dir=str(self.stable),
            backup_dir=str(self.backups),
            connector_smoke={"status": "ready", "last_observed_at": "2026-07-07T00:00:00Z"},
            command_runner=FakeCommandRunner(web_health_payload={"ok": True, "service": "wrong-web"}),
            preflight_runner=ready_preflight,
            now=NOW,
        )

        check = packet["checks"]["local_stable_health"]
        assert packet["status"] == "blocked"
        assert packet["ops_check_ready"] is False
        assert check["reason_code"] == "LOCAL_STABLE_HEALTH_FAILED"
        assert check["web_healthz_http_status"] == "200"
        assert check["web_healthz_service"] == "wrong-web"
        assert "web_root_http_status" not in check

    def test_local_health_requires_mcp_health_service_identity(self) -> None:
        from runner.production_ops import build_production_ops_packet

        packet = build_production_ops_packet(
            str(self.project),
            expected_head=HEAD,
            stable_runtime_dir=str(self.stable),
            backup_dir=str(self.backups),
            connector_smoke={"status": "ready", "last_observed_at": "2026-07-07T00:00:00Z"},
            command_runner=FakeCommandRunner(mcp_health_payload={"ok": True, "service": "wrong-mcp"}),
            preflight_runner=ready_preflight,
            now=NOW,
        )

        check = packet["checks"]["local_stable_health"]
        assert packet["status"] == "blocked"
        assert check["reason_code"] == "LOCAL_STABLE_HEALTH_FAILED"
        assert check["mcp_healthz_http_status"] == "200"
        assert check["mcp_healthz_service"] == "wrong-mcp"

    def test_local_health_blocks_without_loaded_runtime_head(self) -> None:
        from runner.production_ops import build_production_ops_packet

        packet = build_production_ops_packet(
            str(self.project),
            expected_head=HEAD,
            stable_runtime_dir=str(self.stable),
            backup_dir=str(self.backups),
            connector_smoke={"status": "ready", "last_observed_at": "2026-07-07T00:00:00Z"},
            command_runner=FakeCommandRunner(
                web_health_payload={"ok": True, "service": "colameta-web-console"},
                mcp_health_payload={"ok": True, "service": "colameta-mcp"},
            ),
            preflight_runner=ready_preflight,
            now=NOW,
        )

        check = packet["checks"]["local_stable_health"]
        assert packet["status"] == "blocked"
        assert packet["ops_check_ready"] is False
        assert check["reason_code"] == "LOCAL_STABLE_RUNTIME_HEAD_UNVERIFIED"
        assert "LOCAL_STABLE_RUNTIME_HEAD_UNVERIFIED" in packet["blocker_codes"]

    def test_local_health_accepts_packaged_runtime_provenance_without_loaded_head(self) -> None:
        from runner.production_ops import build_production_ops_packet

        web_health = {
            "ok": True,
            "service": "colameta-web-console",
            "loaded_runtime_head": None,
            "runtime_project_checkout_head": HEAD,
            "runtime_loaded_code_stale": False,
            "reload_needed_for_verification": False,
            "reload_awareness_reason": "installed_package_matches_project_checkout",
            "installed_package_matches_project_checkout": True,
            "installed_package_verification_status": "match",
            "installed_package_project_source_clean": True,
            "installed_package_source_cleanliness_status": "clean",
        }
        mcp_health = {
            "ok": True,
            "service": "colameta-mcp",
            "loaded_runtime_head": None,
            "runtime_project_checkout_head": HEAD,
            "runtime_loaded_code_stale": False,
            "reload_needed_for_verification": False,
            "reload_awareness_reason": "installed_package_matches_project_checkout",
            "installed_package_matches_project_checkout": True,
            "installed_package_verification_status": "match",
            "installed_package_project_source_clean": True,
            "installed_package_source_cleanliness_status": "clean",
        }
        packet = build_production_ops_packet(
            str(self.project),
            expected_head=HEAD,
            stable_runtime_dir=str(self.stable),
            backup_dir=str(self.backups),
            connector_smoke={"status": "ready", "last_observed_at": "2026-07-07T00:00:00Z"},
            command_runner=FakeCommandRunner(web_health_payload=web_health, mcp_health_payload=mcp_health),
            preflight_runner=ready_preflight,
            now=NOW,
        )

        check = packet["checks"]["local_stable_health"]
        assert packet["status"] == "ready"
        assert packet["ops_check_ready"] is True
        assert check["reason_code"] == "LOCAL_STABLE_HEALTH_READY"
        assert check["web_runtime_project_checkout_head"] == HEAD
        assert check["mcp_runtime_project_checkout_head"] == HEAD
        assert check["web_installed_package_matches_project_checkout"] is True
        assert check["mcp_installed_package_verification_status"] == "match"
        assert check["web_installed_package_project_source_clean"] is True
        assert check["mcp_installed_package_source_cleanliness_status"] == "clean"

    def test_local_health_blocks_packaged_runtime_without_clean_checkout_evidence(self) -> None:
        from runner.production_ops import build_production_ops_packet

        web_health = {
            "ok": True,
            "service": "colameta-web-console",
            "loaded_runtime_head": None,
            "runtime_project_checkout_head": HEAD,
            "runtime_loaded_code_stale": False,
            "reload_needed_for_verification": False,
            "reload_awareness_reason": "installed_package_project_checkout_dirty",
            "installed_package_matches_project_checkout": False,
            "installed_package_verification_status": "dirty_project_checkout",
            "installed_package_project_source_clean": False,
            "installed_package_source_cleanliness_status": "dirty",
        }
        mcp_health = {
            "ok": True,
            "service": "colameta-mcp",
            "loaded_runtime_head": None,
            "runtime_project_checkout_head": HEAD,
            "runtime_loaded_code_stale": False,
            "reload_needed_for_verification": False,
            "reload_awareness_reason": "installed_package_project_checkout_dirty",
            "installed_package_matches_project_checkout": False,
            "installed_package_verification_status": "dirty_project_checkout",
            "installed_package_project_source_clean": False,
            "installed_package_source_cleanliness_status": "dirty",
        }
        packet = build_production_ops_packet(
            str(self.project),
            expected_head=HEAD,
            stable_runtime_dir=str(self.stable),
            backup_dir=str(self.backups),
            connector_smoke={"status": "ready", "last_observed_at": "2026-07-07T00:00:00Z"},
            command_runner=FakeCommandRunner(web_health_payload=web_health, mcp_health_payload=mcp_health),
            preflight_runner=ready_preflight,
            now=NOW,
        )

        check = packet["checks"]["local_stable_health"]
        assert packet["status"] == "blocked"
        assert packet["ops_check_ready"] is False
        assert check["reason_code"] == "LOCAL_STABLE_RUNTIME_HEAD_UNVERIFIED"
        assert check["web_installed_package_project_source_clean"] is False
        assert "LOCAL_STABLE_RUNTIME_HEAD_UNVERIFIED" in packet["blocker_codes"]

    def test_local_health_blocks_loaded_head_when_reload_verification_needed(self) -> None:
        from runner.production_ops import build_production_ops_packet

        web_health = {
            "ok": True,
            "service": "colameta-web-console",
            "loaded_runtime_head": HEAD,
            "runtime_loaded_code_stale": True,
            "reload_needed_for_verification": True,
            "reload_awareness_reason": "loaded_module_source_changed",
            "installed_package_project_source_clean": True,
            "installed_package_source_cleanliness_status": "clean",
        }
        mcp_health = {
            "ok": True,
            "service": "colameta-mcp",
            "loaded_runtime_head": HEAD,
            "runtime_loaded_code_stale": False,
            "reload_needed_for_verification": False,
            "installed_package_project_source_clean": True,
            "installed_package_source_cleanliness_status": "clean",
        }
        packet = build_production_ops_packet(
            str(self.project),
            expected_head=HEAD,
            stable_runtime_dir=str(self.stable),
            backup_dir=str(self.backups),
            connector_smoke={"status": "ready", "last_observed_at": "2026-07-07T00:00:00Z"},
            command_runner=FakeCommandRunner(web_health_payload=web_health, mcp_health_payload=mcp_health),
            preflight_runner=ready_preflight,
            now=NOW,
        )

        check = packet["checks"]["local_stable_health"]
        assert packet["status"] == "blocked"
        assert packet["ops_check_ready"] is False
        assert check["reason_code"] == "LOCAL_STABLE_RUNTIME_HEAD_UNVERIFIED"
        assert check["web_loaded_runtime_head"] == HEAD
        assert check["web_runtime_loaded_code_stale"] is True
        assert check["web_reload_needed_for_verification"] is True
        assert "LOCAL_STABLE_RUNTIME_HEAD_UNVERIFIED" in packet["blocker_codes"]

    def test_local_health_blocks_loaded_head_without_clean_source_evidence(self) -> None:
        from runner.production_ops import build_production_ops_packet

        web_health = {
            "ok": True,
            "service": "colameta-web-console",
            "loaded_runtime_head": HEAD,
            "runtime_loaded_code_stale": False,
            "reload_needed_for_verification": False,
            "installed_package_project_source_clean": False,
            "installed_package_source_cleanliness_status": "dirty",
        }
        mcp_health = {
            "ok": True,
            "service": "colameta-mcp",
            "loaded_runtime_head": HEAD,
            "runtime_loaded_code_stale": False,
            "reload_needed_for_verification": False,
            "installed_package_project_source_clean": True,
            "installed_package_source_cleanliness_status": "clean",
        }
        packet = build_production_ops_packet(
            str(self.project),
            expected_head=HEAD,
            stable_runtime_dir=str(self.stable),
            backup_dir=str(self.backups),
            connector_smoke={"status": "ready", "last_observed_at": "2026-07-07T00:00:00Z"},
            command_runner=FakeCommandRunner(web_health_payload=web_health, mcp_health_payload=mcp_health),
            preflight_runner=ready_preflight,
            now=NOW,
        )

        check = packet["checks"]["local_stable_health"]
        assert packet["status"] == "blocked"
        assert packet["ops_check_ready"] is False
        assert check["reason_code"] == "LOCAL_STABLE_RUNTIME_HEAD_UNVERIFIED"
        assert check["web_loaded_runtime_head"] == HEAD
        assert check["web_installed_package_project_source_clean"] is False
        assert check["web_installed_package_source_cleanliness_status"] == "dirty"
        assert "LOCAL_STABLE_RUNTIME_HEAD_UNVERIFIED" in packet["blocker_codes"]

    def test_local_health_blocks_loaded_runtime_head_mismatch(self) -> None:
        from runner.production_ops import build_production_ops_packet

        stale_head = "b" * 40
        packet = build_production_ops_packet(
            str(self.project),
            expected_head=HEAD,
            stable_runtime_dir=str(self.stable),
            backup_dir=str(self.backups),
            connector_smoke={"status": "ready", "last_observed_at": "2026-07-07T00:00:00Z"},
            command_runner=FakeCommandRunner(
                web_health_payload={
                    "ok": True,
                    "service": "colameta-web-console",
                    "loaded_runtime_head": stale_head,
                },
                mcp_health_payload={
                    "ok": True,
                    "service": "colameta-mcp",
                    "loaded_runtime_head": stale_head,
                },
            ),
            preflight_runner=ready_preflight,
            now=NOW,
        )

        check = packet["checks"]["local_stable_health"]
        assert packet["status"] == "blocked"
        assert packet["ops_check_ready"] is False
        assert check["reason_code"] == "LOCAL_STABLE_RUNTIME_HEAD_MISMATCH"
        assert check["web_loaded_runtime_head"] == stale_head
        assert check["mcp_loaded_runtime_head"] == stale_head
        assert check["expected_head"] == HEAD
        assert "LOCAL_STABLE_RUNTIME_HEAD_MISMATCH" in packet["blocker_codes"]

    def test_remote_preflight_failure_is_blocked(self) -> None:
        from runner.production_ops import build_production_ops_packet

        packet = build_production_ops_packet(
            str(self.project),
            expected_head=HEAD,
            stable_runtime_dir=str(self.stable),
            backup_dir=str(self.backups),
            connector_smoke={"status": "ready", "last_observed_at": "2026-07-07T00:00:00Z"},
            command_runner=FakeCommandRunner(),
            preflight_runner=failed_preflight,
            now=NOW,
        )

        assert packet["status"] == "blocked"
        assert packet["checks"]["remote_https_mcp_preflight"]["reason_code"] == "REMOTE_PREFLIGHT_FAILED"

    def test_missing_connector_smoke_needs_attention_not_blocked(self) -> None:
        from runner.production_ops import build_production_ops_packet

        packet = build_production_ops_packet(
            str(self.project),
            expected_head=HEAD,
            stable_runtime_dir=str(self.stable),
            backup_dir=str(self.backups),
            command_runner=FakeCommandRunner(),
            preflight_runner=ready_preflight,
            now=NOW,
        )

        assert packet["status"] == "needs_attention"
        assert packet["ops_check_ready"] is True
        assert packet["connector_smoke_ready"] is False
        assert packet["beta_gate_ready"] is False
        assert "CONNECTOR_SMOKE_MISSING" in packet["needs_attention_codes"]

    def test_stale_connector_smoke_needs_attention(self) -> None:
        from runner.production_ops import build_production_ops_packet

        packet = build_production_ops_packet(
            str(self.project),
            expected_head=HEAD,
            stable_runtime_dir=str(self.stable),
            backup_dir=str(self.backups),
            connector_smoke={"status": "ready", "last_observed_at": "2026-07-05T00:00:00Z"},
            command_runner=FakeCommandRunner(),
            preflight_runner=ready_preflight,
            now=NOW,
        )

        assert packet["status"] == "needs_attention"
        assert packet["checks"]["connector_smoke"]["reason_code"] == "CONNECTOR_SMOKE_STALE"

    def test_future_connector_smoke_needs_attention(self) -> None:
        from runner.production_ops import build_production_ops_packet

        packet = build_production_ops_packet(
            str(self.project),
            expected_head=HEAD,
            stable_runtime_dir=str(self.stable),
            backup_dir=str(self.backups),
            connector_smoke={"status": "ready", "last_observed_at": "2026-07-07T00:01:00Z"},
            command_runner=FakeCommandRunner(),
            preflight_runner=ready_preflight,
            now=NOW,
        )

        assert packet["status"] == "needs_attention"
        assert packet["connector_smoke_ready"] is False
        assert packet["beta_gate_ready"] is False
        assert packet["checks"]["connector_smoke"]["reason_code"] == "CONNECTOR_SMOKE_STALE"

    def test_invalid_connector_smoke_observed_at_is_redacted_before_stale_packet(self) -> None:
        from runner.production_ops import REDACTED_CONNECTOR_SMOKE_VALUE, build_production_ops_packet

        packet = build_production_ops_packet(
            str(self.project),
            expected_head=HEAD,
            stable_runtime_dir=str(self.stable),
            backup_dir=str(self.backups),
            connector_smoke={"status": "ready", "last_observed_at": "not-a-timestamp"},
            command_runner=FakeCommandRunner(),
            preflight_runner=ready_preflight,
            now=NOW,
        )

        serialized = json.dumps(packet)
        assert "not-a-timestamp" not in serialized
        assert packet["status"] == "needs_attention"
        assert packet["connector_smoke_ready"] is False
        assert packet["checks"]["connector_smoke"]["reason_code"] == "CONNECTOR_SMOKE_STALE"
        assert packet["checks"]["connector_smoke"]["last_observed_at"] == REDACTED_CONNECTOR_SMOKE_VALUE
        assert packet["checks"]["connector_smoke"]["observed_at_valid"] is False
        assert packet["checks"]["connector_smoke"]["redacted"] is True
        assert packet["checks"]["secret_redaction"]["status"] == "ready"

    def test_backup_missing_needs_attention(self) -> None:
        from runner.production_ops import build_production_ops_packet

        empty_backups = self.tmp_path / "empty-backups"
        empty_backups.mkdir()
        packet = build_production_ops_packet(
            str(self.project),
            expected_head=HEAD,
            stable_runtime_dir=str(self.stable),
            backup_dir=str(empty_backups),
            connector_smoke={"status": "ready", "last_observed_at": "2026-07-07T00:00:00Z"},
            command_runner=FakeCommandRunner(),
            preflight_runner=ready_preflight,
            now=NOW,
        )

        assert packet["status"] == "needs_attention"
        assert packet["checks"]["backup_inventory"]["reason_code"] == "STABLE_BACKUP_MISSING"

    def test_secret_like_input_is_not_echoed_to_packet(self) -> None:
        from runner.production_ops import build_production_ops_packet

        packet = build_production_ops_packet(
            str(self.project),
            expected_head=HEAD,
            stable_runtime_dir=str(self.stable),
            backup_dir=str(self.backups),
            connector_smoke={
                "status": "ready",
                "last_observed_at": "2026-07-07T00:00:00Z",
                "access_token": "sk-not-a-real-token-value",
            },
            command_runner=FakeCommandRunner(),
            preflight_runner=ready_preflight,
            now=NOW,
        )

        serialized = json.dumps(packet)
        assert "sk-not-a-real-token-value" not in serialized
        assert packet["checks"]["secret_redaction"]["status"] == "ready"

    def test_secret_bearing_public_base_url_is_redacted_before_packet_emission(self) -> None:
        from runner.production_ops import REDACTED_PUBLIC_BASE_URL, build_production_ops_packet

        def fail_if_called(public_base_url: str, **kwargs: object) -> dict[str, object]:
            raise AssertionError(f"preflight should not receive rejected URL: {public_base_url} {kwargs}")

        packet = build_production_ops_packet(
            str(self.project),
            public_base_url="https://user:sk-not-a-real-token-value@example.com",
            expected_head=HEAD,
            stable_runtime_dir=str(self.stable),
            backup_dir=str(self.backups),
            connector_smoke={"status": "ready", "last_observed_at": "2026-07-07T00:00:00Z"},
            command_runner=FakeCommandRunner(),
            preflight_runner=fail_if_called,
            now=NOW,
        )

        serialized = json.dumps(packet)
        assert "sk-not-a-real-token-value" not in serialized
        assert "user:" not in serialized
        assert packet["public_base_url"] == REDACTED_PUBLIC_BASE_URL
        assert packet["status"] == "blocked"
        assert packet["checks"]["remote_https_mcp_preflight"]["reason_code"] == "PUBLIC_BASE_URL_REJECTED"
        assert packet["checks"]["secret_redaction"]["status"] == "ready"

    def test_secret_like_project_root_is_redacted_before_packet_emission(self) -> None:
        from runner.production_ops import REDACTED_PROJECT_ROOT, build_production_ops_packet

        secret_dir_name = "project-sk-not-a-real-token-value"
        secret_project = self.tmp_path / secret_dir_name
        secret_project.mkdir()

        packet = build_production_ops_packet(
            str(secret_project),
            expected_head=HEAD,
            stable_runtime_dir=str(self.stable),
            backup_dir=str(self.backups),
            connector_smoke={"status": "ready", "last_observed_at": "2026-07-07T00:00:00Z"},
            command_runner=FakeCommandRunner(),
            preflight_runner=ready_preflight,
            now=NOW,
        )

        serialized = json.dumps(packet)
        assert secret_dir_name not in serialized
        assert "sk-not-a-real-token-value" not in serialized
        assert packet["project_root"] == REDACTED_PROJECT_ROOT
        assert packet["status"] == "blocked"
        assert packet["checks"]["project_root"]["reason_code"] == "PROJECT_ROOT_REJECTED"
        assert packet["checks"]["secret_redaction"]["status"] == "ready"

    def test_secret_bearing_connector_smoke_observed_at_is_redacted_before_packet_emission(self) -> None:
        from runner.production_ops import REDACTED_CONNECTOR_SMOKE_VALUE, build_production_ops_packet

        packet = build_production_ops_packet(
            str(self.project),
            expected_head=HEAD,
            stable_runtime_dir=str(self.stable),
            backup_dir=str(self.backups),
            connector_smoke={
                "status": "ready",
                "last_observed_at": "sk-not-a-real-token-value",
            },
            command_runner=FakeCommandRunner(),
            preflight_runner=ready_preflight,
            now=NOW,
        )

        serialized = json.dumps(packet)
        assert "sk-not-a-real-token-value" not in serialized
        assert packet["status"] == "blocked"
        assert packet["connector_smoke_ready"] is False
        assert packet["checks"]["connector_smoke"]["reason_code"] == "CONNECTOR_SMOKE_REJECTED"
        assert packet["checks"]["connector_smoke"]["last_observed_at"] == REDACTED_CONNECTOR_SMOKE_VALUE
        assert packet["checks"]["secret_redaction"]["status"] == "ready"

    def test_bearer_connector_smoke_observed_at_is_redacted_before_packet_emission(self) -> None:
        from runner.production_ops import REDACTED_CONNECTOR_SMOKE_VALUE, build_production_ops_packet

        pasted_value = "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.signature"
        packet = build_production_ops_packet(
            str(self.project),
            expected_head=HEAD,
            stable_runtime_dir=str(self.stable),
            backup_dir=str(self.backups),
            connector_smoke={
                "status": "ready",
                "last_observed_at": pasted_value,
            },
            command_runner=FakeCommandRunner(),
            preflight_runner=ready_preflight,
            now=NOW,
        )

        serialized = json.dumps(packet)
        assert pasted_value not in serialized
        assert "Authorization: Bearer" not in serialized
        assert "eyJhbGciOiJIUzI1NiJ9" not in serialized
        assert packet["status"] == "blocked"
        assert packet["connector_smoke_ready"] is False
        assert packet["checks"]["connector_smoke"]["reason_code"] == "CONNECTOR_SMOKE_REJECTED"
        assert packet["checks"]["connector_smoke"]["last_observed_at"] == REDACTED_CONNECTOR_SMOKE_VALUE
        assert packet["checks"]["secret_redaction"]["status"] == "ready"

    def test_secret_bearing_connector_smoke_status_is_redacted_before_packet_emission(self) -> None:
        from runner.production_ops import REDACTED_CONNECTOR_SMOKE_VALUE, build_production_ops_packet

        packet = build_production_ops_packet(
            str(self.project),
            expected_head=HEAD,
            stable_runtime_dir=str(self.stable),
            backup_dir=str(self.backups),
            connector_smoke={
                "status": "password=not-a-real-secret",
                "last_observed_at": "2026-07-07T00:00:00Z",
            },
            command_runner=FakeCommandRunner(),
            preflight_runner=ready_preflight,
            now=NOW,
        )

        serialized = json.dumps(packet)
        assert "password=not-a-real-secret" not in serialized
        assert packet["status"] == "blocked"
        assert packet["checks"]["connector_smoke"]["reason_code"] == "CONNECTOR_SMOKE_REJECTED"
        assert packet["checks"]["connector_smoke"]["connector_status"] == REDACTED_CONNECTOR_SMOKE_VALUE
        assert packet["checks"]["connector_smoke"]["last_observed_at"] == "2026-07-07T00:00:00Z"
        assert packet["checks"]["secret_redaction"]["status"] == "ready"

    def test_bare_bearer_connector_smoke_status_is_redacted_before_packet_emission(self) -> None:
        from runner.production_ops import REDACTED_CONNECTOR_SMOKE_VALUE, build_production_ops_packet

        pasted_status = "Bearer abcdef0123456789opaque"
        packet = build_production_ops_packet(
            str(self.project),
            expected_head=HEAD,
            stable_runtime_dir=str(self.stable),
            backup_dir=str(self.backups),
            connector_smoke={
                "status": pasted_status,
                "last_observed_at": "2026-07-07T00:00:00Z",
            },
            command_runner=FakeCommandRunner(),
            preflight_runner=ready_preflight,
            now=NOW,
        )

        serialized = json.dumps(packet)
        assert pasted_status not in serialized
        assert "abcdef0123456789opaque" not in serialized
        assert packet["status"] == "blocked"
        assert packet["connector_smoke_ready"] is False
        assert packet["checks"]["connector_smoke"]["reason_code"] == "CONNECTOR_SMOKE_REJECTED"
        assert packet["checks"]["connector_smoke"]["connector_status"] == REDACTED_CONNECTOR_SMOKE_VALUE
        assert packet["checks"]["secret_redaction"]["status"] == "ready"

    def test_unknown_connector_smoke_status_is_redacted_without_blocking(self) -> None:
        from runner.production_ops import REDACTED_CONNECTOR_SMOKE_VALUE, build_production_ops_packet

        packet = build_production_ops_packet(
            str(self.project),
            expected_head=HEAD,
            stable_runtime_dir=str(self.stable),
            backup_dir=str(self.backups),
            connector_smoke={
                "status": "operator pasted a nonstandard status",
                "last_observed_at": "2026-07-07T00:00:00Z",
            },
            command_runner=FakeCommandRunner(),
            preflight_runner=ready_preflight,
            now=NOW,
        )

        serialized = json.dumps(packet)
        assert "operator pasted a nonstandard status" not in serialized
        assert packet["status"] == "needs_attention"
        assert packet["connector_smoke_ready"] is False
        assert packet["checks"]["connector_smoke"]["reason_code"] == "CONNECTOR_SMOKE_NOT_READY"
        assert packet["checks"]["connector_smoke"]["connector_status"] == REDACTED_CONNECTOR_SMOKE_VALUE
        assert packet["checks"]["connector_smoke"]["connector_status_valid"] is False
        assert packet["checks"]["connector_smoke"]["redacted"] is True

    def test_local_health_probe_curl_is_timeout_bounded(self) -> None:
        from runner.production_ops import LOCAL_HEALTH_PROBE_TIMEOUT_SECONDS, build_production_ops_packet

        runner = FakeCommandRunner()
        build_production_ops_packet(
            str(self.project),
            expected_head=HEAD,
            stable_runtime_dir=str(self.stable),
            backup_dir=str(self.backups),
            connector_smoke={"status": "ready", "last_observed_at": "2026-07-07T00:00:00Z"},
            command_runner=runner,
            preflight_runner=ready_preflight,
            now=NOW,
        )

        curl_calls = [call for call in runner.calls if call[:1] == ["curl"]]
        assert len(curl_calls) == 2
        for call in curl_calls:
            assert "--connect-timeout" in call
            assert "--max-time" in call
            assert call[call.index("--max-time") + 1] == str(int(LOCAL_HEALTH_PROBE_TIMEOUT_SECONDS))
        assert [call[-1] for call in curl_calls] == [
            "http://127.0.0.1:8801/api/healthz",
            "http://127.0.0.1:8766/healthz",
        ]

    def test_default_command_runner_times_out_curl_processes(self) -> None:
        from runner import production_ops

        captured: dict[str, object] = {}

        def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            captured["args"] = args
            captured["timeout"] = kwargs.get("timeout")
            return completed(args, "200")

        with patch.object(production_ops.subprocess, "run", side_effect=fake_run):
            result = production_ops._run_command(["curl", "-fsS", "http://127.0.0.1:8766/healthz"])

        assert result.returncode == 0
        assert captured["timeout"] == production_ops.LOCAL_HEALTH_PROBE_TIMEOUT_SECONDS + 1.0

    def test_status_write_path_rejects_repo_path(self) -> None:
        from runner.production_ops import validate_status_write_path

        with self.assertRaises(ValueError):
            validate_status_write_path(str(self.project / "last-status.json"), project_root=str(self.project))


if __name__ == "__main__":
    unittest.main()
