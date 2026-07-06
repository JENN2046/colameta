from __future__ import annotations

from pathlib import Path


def test_ops_check_systemd_service_collects_status_without_alert_exit_mode() -> None:
    service = Path("systemd/user/colameta-ops-check.service").read_text(encoding="utf-8")

    assert "ops-check" in service
    assert "--write-status" in service
    assert "--fail-on-not-ready" not in service
    assert "NoNewPrivileges=true" in service


def test_ops_check_timer_runs_periodic_collection() -> None:
    timer = Path("systemd/user/colameta-ops-check.timer").read_text(encoding="utf-8")

    assert "OnUnitActiveSec=15min" in timer
    assert "Persistent=true" in timer
