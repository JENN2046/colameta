from __future__ import annotations

import json
import subprocess
import tarfile
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


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
        cat_file_ok: bool = True,
    ) -> None:
        self.head = head
        self.systemd_active = systemd_active
        self.systemd_output = systemd_output
        self.curl_ok = curl_ok
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
            return completed(args, "200" if self.curl_ok else "", 0 if self.curl_ok else 22)
        return completed(args, "")


def ready_preflight(public_base_url: str, **kwargs: object) -> dict[str, object]:
    no_network = bool(kwargs.get("no_network"))
    return {
        "ok": True,
        "public_base_url": public_base_url,
        "connector_url": f"{public_base_url}/mcp",
        "network_check": "not_run" if no_network else "run",
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

    def test_status_write_path_rejects_repo_path(self) -> None:
        from runner.production_ops import validate_status_write_path

        with self.assertRaises(ValueError):
            validate_status_write_path(str(self.project / "last-status.json"), project_root=str(self.project))


if __name__ == "__main__":
    unittest.main()
