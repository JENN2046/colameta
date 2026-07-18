from __future__ import annotations

from pathlib import Path


UNIT_DIR = Path("systemd/system")


def _read(name: str) -> str:
    return (UNIT_DIR / name).read_text(encoding="utf-8")


def test_private_beta_target_owns_the_complete_stack() -> None:
    target = _read("colameta-private-beta.target")

    assert "colameta-stable.service" in target
    assert "colameta-mcp-remote.service" in target
    assert "colameta-mcp-advanced.service" in target
    assert "cloudflared-colameta-mcp-prod.service" in target
    assert "colameta-tunnel-client.service" in target
    assert "colameta-local-healthcheck.timer" in target
    assert "colameta-public-healthcheck.timer" in target
    assert "colameta-managed-tunnel-healthcheck.timer" in target
    assert "WantedBy=multi-user.target" in target


def test_long_running_services_have_restart_stop_and_log_boundaries() -> None:
    for name in (
        "colameta-stable.service",
        "colameta-mcp-remote.service",
        "colameta-mcp-advanced.service",
        "cloudflared-colameta-mcp-prod.service",
        "colameta-tunnel-client.service",
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
    assert "http://127.0.0.1:8768/mcp" in health
    assert (
        "After=colameta-stable.service colameta-mcp-remote.service "
        "colameta-mcp-advanced.service"
    ) in health
    assert "OnFailure=colameta-stack-recover.service" in health
    assert "StartLimitIntervalSec=5min" in recovery
    assert "StartLimitBurst=3" in recovery
    assert "try-restart colameta-private-beta.target" in recovery


def test_public_health_reports_without_automatic_recovery() -> None:
    health = _read("colameta-public-healthcheck.service")

    assert "https://colameta-mcp.skmt617.top/healthz" in health
    assert "OnFailure=" not in health


def test_managed_tunnel_health_reports_without_restarting_the_stack() -> None:
    health = _read("colameta-managed-tunnel-healthcheck.service")

    assert "http://127.0.0.1:8080/healthz" in health
    assert "http://127.0.0.1:8080/readyz" in health
    assert "OnFailure=" not in health


def test_managed_tunnel_uses_existing_safe_launcher_and_bounded_logs() -> None:
    unit = _read("colameta-tunnel-client.service")
    logrotate = Path("systemd/logrotate/colameta-tunnel-client").read_text(
        encoding="utf-8"
    )

    assert "colameta_tunnel_client_service.sh check" in unit
    assert "colameta_tunnel_client_service.sh start" in unit
    assert "Restart=always" in unit
    assert "rotate 14" in logrotate
    assert "maxsize 10M" in logrotate


def test_default_services_use_commander_and_advanced_stays_loopback_normal() -> None:
    stable = _read("colameta-stable.service")
    remote = _read("colameta-mcp-remote.service")
    advanced = _read("colameta-mcp-advanced.service")

    assert "Environment=MCP_EXPOSURE_PROFILE=commander" in stable
    assert "Environment=MCP_EXPOSURE_PROFILE=commander" in remote
    assert "--oauth-scopes mcp:read,mcp:preview --no-register-selected" in remote
    assert "mcp:commit" not in remote
    assert "mcp:plan" not in remote
    assert "Environment=MCP_EXPOSURE_PROFILE=normal" in advanced
    assert "--mcp-host 127.0.0.1 --mcp-port 8768" in advanced
    assert "--auth-mode none" in advanced


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
    assert "colameta-tunnel-client.service" in installer
    assert "colameta-mcp-advanced.service" in installer
    assert '"$backup_dir/logrotate-colameta-tunnel-client"' in installer
    assert "/etc/logrotate.d/colameta-tunnel-client" in installer
    assert "systemctl enable colameta-private-beta.target" in installer
