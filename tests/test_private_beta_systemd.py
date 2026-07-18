from __future__ import annotations

from pathlib import Path


UNIT_DIR = Path("systemd/system")


def _read(name: str) -> str:
    return (UNIT_DIR / name).read_text(encoding="utf-8")


def test_private_beta_target_owns_the_complete_stack() -> None:
    target = _read("colameta-private-beta.target")

    assert "colameta-stable.service" in target
    assert "colameta-mcp-remote.service" in target
    assert "cloudflared-colameta-mcp-prod.service" in target
    assert "colameta-local-healthcheck.timer" in target
    assert "colameta-public-healthcheck.timer" in target
    assert "WantedBy=multi-user.target" in target


def test_long_running_services_have_restart_stop_and_log_boundaries() -> None:
    for name in (
        "colameta-stable.service",
        "colameta-mcp-remote.service",
        "cloudflared-colameta-mcp-prod.service",
    ):
        unit = _read(name)
        assert "Restart=always" in unit
        assert "TimeoutStopSec=30s" in unit
        assert "KillMode=mixed" in unit
        assert "NoNewPrivileges=true" in unit
        assert "LogNamespace=colameta" in unit
        assert "PartOf=colameta-private-beta.target" in unit


def test_cloudflared_is_ordered_without_stop_propagation_from_origin() -> None:
    unit = _read("cloudflared-colameta-mcp-prod.service")

    assert "After=network-online.target colameta-mcp-remote.service" in unit
    assert "Wants=network-online.target colameta-mcp-remote.service" in unit
    assert "Requires=colameta-mcp-remote.service" not in unit


def test_local_health_failure_has_rate_limited_recovery() -> None:
    health = _read("colameta-local-healthcheck.service")
    recovery = _read("colameta-stack-recover.service")

    assert "http://127.0.0.1:8801/" in health
    assert "http://127.0.0.1:8766/mcp" in health
    assert "http://127.0.0.1:8767/healthz" in health
    assert "OnFailure=colameta-stack-recover.service" in health
    assert "StartLimitIntervalSec=5min" in recovery
    assert "StartLimitBurst=3" in recovery
    assert "try-restart colameta-private-beta.target" in recovery


def test_public_health_reports_without_automatic_recovery() -> None:
    health = _read("colameta-public-healthcheck.service")

    assert "https://colameta-mcp.skmt617.top/healthz" in health
    assert "OnFailure=" not in health


def test_journal_namespace_has_bounded_rotation() -> None:
    config = _read("journald-colameta.conf")

    assert "SystemMaxUse=256M" in config
    assert "SystemMaxFileSize=32M" in config
    assert "MaxFileSec=1day" in config
    assert "MaxRetentionSec=14day" in config


def test_installer_keeps_the_target_as_the_only_boot_owner() -> None:
    installer = Path("scripts/install_private_beta_systemd.sh").read_text(
        encoding="utf-8"
    )

    assert "systemctl disable" in installer
    assert "cloudflared-colameta-mcp-prod.service" in installer
    assert "systemctl enable colameta-private-beta.target" in installer
