from __future__ import annotations

from runner.product_readiness import (
    build_apps_connector_smoke_handoff_packet,
    build_chatgpt_connection_packet,
    build_product_readiness_packet,
)


def _ops_packet(*, status: str = "ready", connector_status: str = "ready") -> dict[str, object]:
    return {
        "ok": True,
        "source": "production_ops_beta_gate",
        "read_only": True,
        "side_effects": False,
        "project_root": "<redacted-project-root>",
        "public_base_url": "https://example.test",
        "observed_at": "2026-07-09T00:00:00Z",
        "status": status,
        "ops_check_ready": status == "ready",
        "connector_smoke_ready": connector_status == "ready",
        "beta_gate_ready": status == "ready" and connector_status == "ready",
        "checks": {
            "stable_runtime": {"status": "ready", "reason_codes": ["STABLE_RUNTIME_MATCHES_EXPECTED_HEAD"]},
            "stable_service": {"status": "ready", "reason_codes": ["STABLE_SERVICE_ACTIVE"]},
            "local_stable_health": {"status": "ready", "reason_codes": ["LOCAL_STABLE_HEALTH_READY"]},
            "remote_https_mcp_preflight": {"status": "ready", "reason_codes": ["REMOTE_PREFLIGHT_READY"]},
            "cloudflared_service": {"status": "ready", "reason_codes": ["CLOUDFLARED_SERVICE_ACTIVE"]},
            "connector_smoke": {"status": connector_status, "reason_codes": ["CONNECTOR_SMOKE_READY"]},
        },
        "reason_codes": [],
        "blocker_codes": [],
        "needs_attention_codes": [] if status == "ready" else ["CONNECTOR_SMOKE_MISSING"],
        "not_authorized_actions": ["restart_service", "stable_replacement"],
    }


def test_product_readiness_ready_packet_is_read_only() -> None:
    packet = build_product_readiness_packet(
        "/tmp/project",
        ops_packet_builder=lambda *args, **kwargs: _ops_packet(),
    )

    assert packet["status"] == "ready"
    assert packet["ready"] is True
    assert packet["read_only"] is True
    assert packet["side_effects"] is False
    assert packet["connector_url"] == "https://example.test/mcp"
    assert packet["chatgpt_app"]["main_entry"] == "render_commander_app"
    assert packet["chatgpt_app"]["full_loop_authority_tool"] == "get_full_loop_authority_status"
    assert packet["full_loop_authority"]["status"] == "disabled"
    assert packet["authority_boundary"]["does_not_authorize_commit_or_push"] is True


def test_product_readiness_picks_primary_blocker_and_runbook() -> None:
    ops = _ops_packet(status="blocked")
    ops["checks"]["remote_https_mcp_preflight"] = {
        "status": "blocked",
        "reason_codes": ["REMOTE_PREFLIGHT_DNS_NOT_PUBLIC"],
        "operator_hint": {
            "action": "fix_dns_proxy_path",
            "runbook": "docs/dns-proxy-tunnel-runbook.zh-CN.md",
            "summary": "DNS must resolve to public addresses.",
        },
    }
    ops["blocker_codes"] = ["REMOTE_PREFLIGHT_DNS_NOT_PUBLIC"]

    packet = build_product_readiness_packet(
        "/tmp/project",
        ops_packet_builder=lambda *args, **kwargs: ops,
    )

    assert packet["status"] == "blocked"
    assert packet["primary_blocker"]["check"] == "remote_https_mcp_preflight"
    assert packet["safe_next_action"]["action"] == "follow_runbook"
    assert packet["safe_next_action"]["runbook"] == "docs/dns-proxy-tunnel-runbook.zh-CN.md"


def test_product_readiness_routes_missing_connector_smoke_to_apps_tool() -> None:
    ops = _ops_packet(status="needs_attention", connector_status="missing")
    ops["checks"]["connector_smoke"] = {
        "status": "needs_attention",
        "reason_codes": ["CONNECTOR_SMOKE_MISSING"],
    }

    packet = build_product_readiness_packet(
        "/tmp/project",
        ops_packet_builder=lambda *args, **kwargs: ops,
    )

    assert packet["status"] == "needs_attention"
    assert packet["primary_blocker"]["check"] == "connector_smoke"
    assert packet["safe_next_action"]["tool"] == "get_apps_connector_smoke_packet"


def test_product_readiness_routes_stable_runtime_blocker_to_cadence_tool() -> None:
    ops = _ops_packet(status="blocked")
    ops["checks"]["stable_runtime"] = {
        "status": "blocked",
        "reason_codes": ["STABLE_RUNTIME_HEAD_MISMATCH"],
    }
    ops["blocker_codes"] = ["STABLE_RUNTIME_HEAD_MISMATCH"]

    packet = build_product_readiness_packet(
        "/tmp/project",
        ops_packet_builder=lambda *args, **kwargs: ops,
    )

    assert packet["status"] == "blocked"
    assert packet["primary_blocker"]["check"] == "stable_runtime"
    assert packet["safe_next_action"]["action"] == "inspect_stable_replacement_cadence"
    assert packet["safe_next_action"]["tool"] == "get_stable_replacement_cadence"
    assert packet["chatgpt_app"]["stable_replacement_cadence_tool"] == "get_stable_replacement_cadence"
    assert packet["authority_boundary"]["does_not_authorize_stable_replacement"] is True


def test_product_readiness_routes_local_stable_health_blocker_to_cadence_tool() -> None:
    ops = _ops_packet(status="blocked")
    ops["checks"]["local_stable_health"] = {
        "status": "blocked",
        "reason_codes": ["LOCAL_STABLE_RUNTIME_HEAD_UNVERIFIED"],
    }
    ops["blocker_codes"] = ["LOCAL_STABLE_RUNTIME_HEAD_UNVERIFIED"]

    packet = build_product_readiness_packet(
        "/tmp/project",
        ops_packet_builder=lambda *args, **kwargs: ops,
    )

    assert packet["status"] == "blocked"
    assert packet["primary_blocker"]["check"] == "local_stable_health"
    assert packet["safe_next_action"]["tool"] == "get_stable_replacement_cadence"


def test_chatgpt_connection_packet_is_a_read_only_handoff() -> None:
    packet = build_chatgpt_connection_packet(
        "/tmp/project",
        project_name="demo-project",
        ops_packet_builder=lambda *args, **kwargs: _ops_packet(),
    )

    assert packet["read_only"] is True
    assert packet["side_effects"] is False
    assert packet["recommended_sequence"][2]["tool"] == "get_product_readiness_status"
    assert packet["recommended_sequence"][2]["arguments"] == {"project_name": "demo-project"}


def test_apps_connector_smoke_handoff_points_to_external_smoke_tool() -> None:
    packet = build_apps_connector_smoke_handoff_packet(
        "/tmp/project",
        project_name="demo-project",
        ops_packet_builder=lambda *args, **kwargs: _ops_packet(status="needs_attention", connector_status="missing"),
    )

    assert packet["source"] == "apps_connector_smoke_handoff"
    assert packet["safe_next_action"]["tool"] == "get_apps_connector_smoke_packet"
    assert packet["operator_sequence"][1]["arguments"] == {"project_name": "demo-project"}
