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


def test_cloudflared_is_ordered_without_stop_propagation_and_auto_negotiates_transport() -> None:
    unit = _read("cloudflared-colameta-mcp-prod.service")

    assert "After=network-online.target colameta-mcp-remote.service" in unit
    assert "Wants=network-online.target colameta-mcp-remote.service" in unit
    assert "Requires=colameta-mcp-remote.service" not in unit
    assert "--protocol auto" in unit
    assert "--protocol quic" not in unit
    assert "--protocol http2" not in unit
    assert "BindReadOnlyPaths=" not in unit
    assert "edge-hosts" not in unit
    assert "/etc/hosts" not in unit


def test_cloudflared_runbook_targets_the_system_manager() -> None:
    runbook = Path("docs/dns-proxy-tunnel-runbook.zh-CN.md").read_text(
        encoding="utf-8"
    )

    assert "sudo systemctl restart cloudflared-colameta-mcp-prod.service" in runbook
    assert "sudo systemctl status cloudflared-colameta-mcp-prod.service" in runbook
    assert "systemctl --user restart cloudflared-colameta-mcp-prod.service" not in runbook
    assert "systemctl --user status cloudflared-colameta-mcp-prod.service" not in runbook


def test_cloudflared_credentials_refresh_is_scoped_reversible_and_secret_safe() -> None:
    script = Path("scripts/refresh_cloudflared_tunnel_credentials.sh").read_text(
        encoding="utf-8"
    )

    assert "set +x" in script
    assert "umask 077" in script
    assert '[[ "$(id -un)" == "jenn" ]]' in script
    assert 'credentials_dir_expected="/home/jenn/.cloudflared"' in script
    assert '[[ -f "$credentials_file" && ! -L "$credentials_file" ]]' in script
    assert 'tunnel token \\' in script
    assert '--cred-file "$fresh_credentials"' in script
    assert ">/dev/null 2>&1" in script
    assert 'cp --preserve=mode,timestamps "$credentials_file" "$backup_credentials"' in script
    assert 'mv -- "$fresh_credentials" "$credentials_file"' in script
    assert 'sudo systemctl stop "$service_name"' in script
    assert 'sudo systemctl start "$service_name"' in script
    assert "remote_https_mcp_preflight.py" in script
    assert "service install" not in script


def test_cloudflared_readiness_failure_restores_backup_before_reporting() -> None:
    script = Path("scripts/refresh_cloudflared_tunnel_credentials.sh").read_text(
        encoding="utf-8"
    )

    helper_start = script.index("rollback_applied_credentials()")
    helper_end = script.index("\n}\n\ncleanup()", helper_start)
    helper = script[helper_start:helper_end]
    assert 'credential_state" == "applied_unvalidated"' in helper
    assert 'sudo systemctl stop "$service_name"' in helper
    assert (
        'cp --preserve=mode,timestamps "$backup_credentials" "$rollback_credentials"'
        in helper
    )
    assert 'mv -- "$rollback_credentials" "$credentials_file"' in helper
    assert 'sudo systemctl start "$service_name"' in helper
    assert helper.index('sudo systemctl start "$service_name"') < helper.index(
        'service_stopped="no"'
    )

    branch_start = script.index('if [[ "$ready_http" != "200" ]]; then')
    branch_end = script.index(
        '\nif ! "$python_bin" "$preflight_script"', branch_start
    )
    readiness_failure = script[branch_start:branch_end]
    assert "rollback_applied_credentials" in readiness_failure
    assert 'fail "applied_not_ready_rollback_restart_failed"' in readiness_failure
    assert (
        readiness_failure.index("rollback_applied_credentials")
        < readiness_failure.index('fail "applied_not_ready"')
    )


def test_cloudflared_interrupts_roll_back_until_validation_is_committed() -> None:
    script = Path("scripts/refresh_cloudflared_tunnel_credentials.sh").read_text(
        encoding="utf-8"
    )

    cleanup_start = script.index("cleanup()")
    cleanup_end = script.index("\n}\n\ntrap cleanup EXIT", cleanup_start)
    cleanup = script[cleanup_start:cleanup_end]
    assert 'trap \'\' HUP INT TERM' in cleanup
    assert 'credential_state" == "applied_unvalidated"' in cleanup
    assert "rollback_applied_credentials" in cleanup
    assert "trap 'exit 130' HUP INT TERM" in script

    replace_position = script.index('mv -- "$fresh_credentials" "$credentials_file"')
    pending_position = script.rindex(
        'credential_state="applied_unvalidated"', 0, replace_position
    )
    validation_position = script.index(
        'credential_state="validated"', replace_position
    )
    public_preflight_position = script.index(
        '"$python_bin" "$preflight_script" "$public_base_url"', replace_position
    )
    success_position = script.index(
        "printf 'credential_refresh=ok", public_preflight_position
    )
    preflight_failure_rollback = script.index(
        "rollback_applied_credentials", public_preflight_position
    )
    assert pending_position < replace_position < public_preflight_position
    assert public_preflight_position < preflight_failure_rollback
    assert public_preflight_position < validation_position < success_position


def test_cloudflared_inactive_service_rolls_back_before_public_preflight() -> None:
    script = Path("scripts/refresh_cloudflared_tunnel_credentials.sh").read_text(
        encoding="utf-8"
    )

    service_probe = script.index(
        'if sudo systemctl is-active --quiet "$service_name"'
    )
    service_report = script.index(
        "printf 'service_active=%s", service_probe
    )
    readiness_end = script.index(
        'if [[ "$ready_http" != "200" ]]; then', service_report
    )
    public_preflight = script.index(
        'if ! "$python_bin" "$preflight_script" "$public_base_url"', readiness_end
    )
    active_check = script.index(
        'if [[ "$service_active" != "yes" ]]', readiness_end
    )
    inactive_rollback = script.index(
        "rollback_applied_credentials", active_check, public_preflight
    )
    inactive_failure = script.index(
        'fail "applied_service_inactive"', inactive_rollback, public_preflight
    )
    assert (
        service_probe
        < service_report
        < readiness_end
        < active_check
        < inactive_rollback
        < inactive_failure
        < public_preflight
    )


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
