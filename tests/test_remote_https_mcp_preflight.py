from __future__ import annotations

import json

import pytest

from scripts.remote_https_mcp_preflight import (
    PREFLIGHT_USER_AGENT,
    PreflightError,
    build_endpoint_plan,
    fetch_json,
    normalize_public_base_url,
    run_preflight,
    validate_remote_payloads,
)
from scripts.runner_cli_env import is_local_http_url


def test_normalize_public_base_url_accepts_https_service_base() -> None:
    assert normalize_public_base_url(" https://mcp.example.com/ ") == "https://mcp.example.com"
    plan = build_endpoint_plan("https://mcp.example.com")
    assert plan.connector_url == "https://mcp.example.com/mcp"
    assert plan.protected_resource_metadata_url == "https://mcp.example.com/.well-known/oauth-protected-resource"


def test_normalize_public_base_url_rejects_remote_http_and_connector_url() -> None:
    with pytest.raises(PreflightError, match="https"):
        normalize_public_base_url("http://mcp.example.com")

    with pytest.raises(PreflightError, match="service base URL"):
        normalize_public_base_url("https://mcp.example.com/mcp")


def test_normalize_public_base_url_allows_only_loopback_http_when_requested() -> None:
    assert normalize_public_base_url("http://127.0.0.2:8765", allow_local_http=True) == "http://127.0.0.2:8765"
    assert normalize_public_base_url("http://[::1]:8765", allow_local_http=True) == "http://[::1]:8765"

    with pytest.raises(PreflightError, match="localhost"):
        normalize_public_base_url("http://127.0.0.1.example:8765", allow_local_http=True)

    assert is_local_http_url("http://127.0.0.1:8765") is True
    assert is_local_http_url("http://127.0.0.1.example:8765") is False


def test_run_preflight_no_network_reports_connector_urls() -> None:
    report = run_preflight("https://mcp.example.com/", no_network=True)
    assert report["ok"] is True
    assert report["network_check"] == "not_run"
    assert report["connector_url"] == "https://mcp.example.com/mcp"


def test_fetch_json_uses_explicit_preflight_user_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    class FakeResponse:
        status = 200

        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps({"ok": True}).encode("utf-8")

    def fake_urlopen(request: object, timeout: float) -> FakeResponse:
        captured["timeout"] = timeout
        captured["user_agent"] = request.get_header("User-agent")
        captured["accept"] = request.get_header("Accept")
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    status, payload = fetch_json("https://mcp.example.com/healthz", timeout_seconds=7)

    assert status == 200
    assert payload == {"ok": True}
    assert captured["timeout"] == 7
    assert captured["user_agent"] == PREFLIGHT_USER_AGENT
    assert captured["accept"] == "application/json"


def test_validate_remote_payloads_accepts_oauth_metadata_contract() -> None:
    plan = build_endpoint_plan("https://mcp.example.com")
    failures = validate_remote_payloads(
        plan,
        healthz=(200, {"ok": True, "service": "colameta-mcp", "auth_mode": "oauth"}),
        mcp=(
            200,
            {
                "ok": True,
                "auth_mode": "oauth",
                "protected_resource_metadata": "https://mcp.example.com/.well-known/oauth-protected-resource",
            },
        ),
        protected_resource=(
            200,
            {
                "resource": "https://mcp.example.com/mcp",
                "authorization_servers": ["https://mcp.example.com"],
                "bearer_methods_supported": ["header"],
            },
        ),
        authorization_server=(
            200,
            {
                "issuer": "https://mcp.example.com",
                "authorization_endpoint": "https://mcp.example.com/authorize",
                "token_endpoint": "https://mcp.example.com/token",
                "registration_endpoint": "https://mcp.example.com/register",
                "revocation_endpoint": "https://mcp.example.com/revoke",
                "grant_types_supported": ["authorization_code"],
                "code_challenge_methods_supported": ["S256"],
            },
        ),
    )

    assert failures == []


def test_validate_remote_payloads_requires_oauth_for_remote_chatgpt_mcp() -> None:
    plan = build_endpoint_plan("https://mcp.example.com")
    failures = validate_remote_payloads(
        plan,
        healthz=(200, {"ok": True, "service": "colameta-mcp", "auth_mode": "token"}),
        mcp=(200, {"ok": True, "auth_mode": "token"}),
        protected_resource=(404, {}),
        authorization_server=(404, {}),
    )

    assert "healthz auth_mode must be oauth for ChatGPT remote MCP." in failures
    assert "GET /mcp auth_mode must be oauth." in failures
