from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import scripts.remote_https_mcp_preflight as remote_preflight
from scripts.remote_https_mcp_preflight import (
    PREFLIGHT_USER_AGENT,
    PreflightError,
    build_endpoint_plan,
    fetch_json,
    main as preflight_main,
    normalize_public_base_url,
    run_preflight,
    validate_remote_payloads,
)
from scripts.runner_cli_env import is_local_http_url


HEAD = "a" * 40
STALE_HEAD = "b" * 40


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


def test_normalize_public_base_url_rejects_loopback_https() -> None:
    with pytest.raises(PreflightError, match="loopback"):
        normalize_public_base_url("https://127.0.0.1:8766")

    with pytest.raises(PreflightError, match="localhost"):
        normalize_public_base_url("https://localhost:8766")

    for url in ("https://127.1:8766", "https://2130706433:8766", "https://0x7f000001:8766"):
        with pytest.raises(PreflightError, match="non-public"):
            normalize_public_base_url(url)


def test_normalize_public_base_url_rejects_private_and_link_local_https_ip_literals() -> None:
    for url in (
        "https://192.168.1.10:8766",
        "https://10.0.0.5",
        "https://169.254.10.20",
        "https://[fc00::1]:8766",
        "https://192.168.1:8766",
        "https://0300.0250.0001.0001:8766",
    ):
        with pytest.raises(PreflightError, match="non-public"):
            normalize_public_base_url(url)

    assert normalize_public_base_url("https://8.8.8.8") == "https://8.8.8.8"


def test_normalize_public_base_url_rejects_local_only_dns_names() -> None:
    for url in (
        "https://colameta.local:8766",
        "https://colameta.local.",
        "https://api.localhost",
        "https://stable.home.arpa",
        "https://colameta",
        "https://colameta:8766",
    ):
        with pytest.raises(PreflightError, match="local-only DNS"):
            normalize_public_base_url(url)

    assert normalize_public_base_url("https://mcp.example.com.") == "https://mcp.example.com."


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

        def read(self, size: int = -1) -> bytes:
            captured["read_size"] = size
            return json.dumps({"ok": True}).encode("utf-8")

    def fake_open(request: object, timeout: float) -> FakeResponse:
        captured["timeout"] = timeout
        captured["user_agent"] = request.get_header("User-agent")
        captured["accept"] = request.get_header("Accept")
        return FakeResponse()

    monkeypatch.setattr(remote_preflight._NO_REDIRECT_OPENER, "open", fake_open)

    status, payload = fetch_json("https://mcp.example.com/healthz", timeout_seconds=7)

    assert status == 200
    assert payload == {"ok": True}
    assert captured["timeout"] == 7
    assert captured["user_agent"] == PREFLIGHT_USER_AGENT
    assert captured["accept"] == "application/json"
    assert captured["read_size"] == remote_preflight.MAX_PREFLIGHT_RESPONSE_BYTES + 1


def test_fetch_json_rejects_oversized_success_response(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        status = 200

        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self, size: int = -1) -> bytes:
            assert size == remote_preflight.MAX_PREFLIGHT_RESPONSE_BYTES + 1
            return b"{" + (b" " * remote_preflight.MAX_PREFLIGHT_RESPONSE_BYTES)

    def fake_open(request: object, timeout: float) -> FakeResponse:
        return FakeResponse()

    monkeypatch.setattr(remote_preflight._NO_REDIRECT_OPENER, "open", fake_open)

    with pytest.raises(PreflightError, match="response body exceeds"):
        fetch_json("https://mcp.example.com/healthz")


def test_fetch_json_rejects_oversized_error_response(monkeypatch: pytest.MonkeyPatch) -> None:
    body = b"{" + (b" " * remote_preflight.MAX_PREFLIGHT_RESPONSE_BYTES)

    class FakeErrorBody:
        def read(self, size: int = -1) -> bytes:
            assert size == remote_preflight.MAX_PREFLIGHT_RESPONSE_BYTES + 1
            return body

        def close(self) -> None:
            return None

    error = remote_preflight.urllib.error.HTTPError(
        "https://mcp.example.com/.well-known/oauth-authorization-server",
        404,
        "not found",
        {},
        FakeErrorBody(),
    )

    def fake_open(request: object, timeout: float) -> object:
        raise error

    monkeypatch.setattr(remote_preflight._NO_REDIRECT_OPENER, "open", fake_open)

    with pytest.raises(PreflightError, match="response body exceeds"):
        fetch_json("https://mcp.example.com/.well-known/oauth-authorization-server")


def test_fetch_json_accepts_bounded_error_response(monkeypatch: pytest.MonkeyPatch) -> None:
    body = json.dumps({"error_code": "EXTERNAL_AUTH_SERVER"}).encode("utf-8")

    class FakeErrorBody:
        def read(self, size: int = -1) -> bytes:
            assert size == remote_preflight.MAX_PREFLIGHT_RESPONSE_BYTES + 1
            return body

        def close(self) -> None:
            return None

    error = remote_preflight.urllib.error.HTTPError(
        "https://mcp.example.com/.well-known/oauth-authorization-server",
        404,
        "not found",
        {},
        FakeErrorBody(),
    )

    def fake_open(request: object, timeout: float) -> object:
        raise error

    monkeypatch.setattr(remote_preflight._NO_REDIRECT_OPENER, "open", fake_open)

    status, payload = fetch_json("https://mcp.example.com/.well-known/oauth-authorization-server")

    assert status == 404
    assert payload == {"error_code": "EXTERNAL_AUTH_SERVER"}


def test_fetch_json_disables_redirects_before_following_location() -> None:
    paths_seen: list[str] = []

    class RedirectHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            return

        def do_GET(self) -> None:
            paths_seen.append(self.path)
            if self.path == "/healthz":
                host, port = self.server.server_address
                self.send_response(302)
                self.send_header("Location", f"http://{host}:{port}/private")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True}).encode("utf-8"))

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), RedirectHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = httpd.server_address
        with pytest.raises(PreflightError, match="must not redirect"):
            fetch_json(f"http://{host}:{port}/healthz")
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=2)

    assert paths_seen == ["/healthz"]


def test_fetch_json_rejects_redirected_final_url(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        status = 200

        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def geturl(self) -> str:
            return "http://127.0.0.1:8766/healthz"

        def read(self, size: int = -1) -> bytes:
            return json.dumps({"ok": True}).encode("utf-8")

    def fake_open(request: object, timeout: float) -> FakeResponse:
        return FakeResponse()

    monkeypatch.setattr(remote_preflight._NO_REDIRECT_OPENER, "open", fake_open)

    with pytest.raises(PreflightError, match="redirected to an off-base"):
        fetch_json("https://mcp.example.com/healthz")


def test_fetch_json_rejects_same_scheme_off_base_redirect(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        status = 200

        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def geturl(self) -> str:
            return "https://other.example.com/healthz"

        def read(self, size: int = -1) -> bytes:
            return json.dumps({"ok": True}).encode("utf-8")

    def fake_open(request: object, timeout: float) -> FakeResponse:
        return FakeResponse()

    monkeypatch.setattr(remote_preflight._NO_REDIRECT_OPENER, "open", fake_open)

    with pytest.raises(PreflightError, match="redirected to an off-base"):
        fetch_json("https://mcp.example.com/healthz")


def test_run_preflight_rejects_malformed_explicit_expected_head() -> None:
    with pytest.raises(PreflightError, match="expected_head"):
        run_preflight("https://mcp.example.com", no_network=True, expected_head="abc123")


def test_main_rejects_malformed_explicit_expected_head(capsys: pytest.CaptureFixture[str]) -> None:
    code = preflight_main(["https://mcp.example.com", "--no-network", "--expected-head", "abc123"])

    output = json.loads(capsys.readouterr().out)
    assert code == 2
    assert output["ok"] is False
    assert output["failures"] == ["expected_head must be a full 40-character commit SHA."]


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


def test_validate_remote_payloads_accepts_expected_public_healthz_runtime() -> None:
    plan = build_endpoint_plan("https://mcp.example.com")
    failures = validate_remote_payloads(
        plan,
        healthz=(
            200,
            {
                "ok": True,
                "service": "colameta-mcp",
                "auth_mode": "oauth",
                "loaded_runtime_head": HEAD,
                "runtime_loaded_code_stale": False,
                "reload_needed_for_verification": False,
                "installed_package_project_source_clean": True,
                "installed_package_source_cleanliness_status": "clean",
            },
        ),
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
        expected_head=HEAD,
    )

    assert failures == []


def test_validate_remote_payloads_rejects_stale_public_healthz_runtime() -> None:
    plan = build_endpoint_plan("https://mcp.example.com")
    failures = validate_remote_payloads(
        plan,
        healthz=(
            200,
            {
                "ok": True,
                "service": "colameta-mcp",
                "auth_mode": "oauth",
                "loaded_runtime_head": STALE_HEAD,
                "runtime_loaded_code_stale": False,
                "reload_needed_for_verification": False,
                "installed_package_project_source_clean": True,
                "installed_package_source_cleanliness_status": "clean",
            },
        ),
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
        expected_head=HEAD,
    )

    assert "healthz runtime provenance must prove the public MCP endpoint is serving expected_head." in failures


def test_validate_remote_payloads_accepts_package_fallback_without_loaded_head() -> None:
    plan = build_endpoint_plan("https://mcp.example.com")
    failures = validate_remote_payloads(
        plan,
        healthz=(
            200,
            {
                "ok": True,
                "service": "colameta-mcp",
                "auth_mode": "oauth",
                "loaded_runtime_head": None,
                "runtime_project_checkout_head": HEAD,
                "runtime_loaded_code_stale": False,
                "reload_needed_for_verification": False,
                "installed_package_matches_project_checkout": True,
                "installed_package_verification_status": "match",
                "installed_package_project_source_clean": True,
                "installed_package_source_cleanliness_status": "clean",
            },
        ),
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
        expected_head=HEAD,
    )

    assert failures == []


def test_validate_remote_payloads_rejects_stale_loaded_head_before_package_fallback() -> None:
    plan = build_endpoint_plan("https://mcp.example.com")
    failures = validate_remote_payloads(
        plan,
        healthz=(
            200,
            {
                "ok": True,
                "service": "colameta-mcp",
                "auth_mode": "oauth",
                "loaded_runtime_head": STALE_HEAD,
                "runtime_project_checkout_head": HEAD,
                "runtime_loaded_code_stale": False,
                "reload_needed_for_verification": False,
                "installed_package_matches_project_checkout": True,
                "installed_package_verification_status": "match",
                "installed_package_project_source_clean": True,
                "installed_package_source_cleanliness_status": "clean",
            },
        ),
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
        expected_head=HEAD,
    )

    assert "healthz runtime provenance must prove the public MCP endpoint is serving expected_head." in failures


def test_validate_remote_payloads_rejects_dirty_public_healthz_runtime() -> None:
    plan = build_endpoint_plan("https://mcp.example.com")
    failures = validate_remote_payloads(
        plan,
        healthz=(
            200,
            {
                "ok": True,
                "service": "colameta-mcp",
                "auth_mode": "oauth",
                "loaded_runtime_head": HEAD,
                "runtime_loaded_code_stale": False,
                "reload_needed_for_verification": False,
                "installed_package_project_source_clean": False,
                "installed_package_source_cleanliness_status": "dirty",
            },
        ),
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
        expected_head=HEAD,
    )

    assert "healthz runtime provenance must prove the public MCP endpoint is serving expected_head." in failures


def test_validate_remote_payloads_accepts_external_oauth_resource_server_contract() -> None:
    plan = build_endpoint_plan("https://mcp.example.com")
    failures = validate_remote_payloads(
        plan,
        healthz=(200, {"ok": True, "service": "colameta-mcp", "auth_mode": "external-oauth"}),
        mcp=(
            200,
            {
                "ok": True,
                "auth_mode": "external-oauth",
                "protected_resource_metadata": "https://mcp.example.com/.well-known/oauth-protected-resource",
            },
        ),
        protected_resource=(
            200,
            {
                "resource": "https://mcp.example.com/mcp",
                "authorization_servers": ["https://idp.example.com/"],
                "bearer_methods_supported": ["header"],
            },
        ),
        authorization_server=(
            404,
            {
                "ok": False,
                "error_code": "EXTERNAL_AUTH_SERVER",
            },
        ),
    )

    assert failures == []


@pytest.mark.parametrize(
    "authorization_server",
    [
        "https://localhost/",
        "https://127.0.0.1/",
        "https://192.168.1.10/",
        "https://colameta.local/",
        "https://colameta/",
    ],
)
def test_validate_remote_payloads_rejects_non_public_external_oauth_authorization_server(
    authorization_server: str,
) -> None:
    plan = build_endpoint_plan("https://mcp.example.com")
    failures = validate_remote_payloads(
        plan,
        healthz=(200, {"ok": True, "service": "colameta-mcp", "auth_mode": "external-oauth"}),
        mcp=(
            200,
            {
                "ok": True,
                "auth_mode": "external-oauth",
                "protected_resource_metadata": "https://mcp.example.com/.well-known/oauth-protected-resource",
            },
        ),
        protected_resource=(
            200,
            {
                "resource": "https://mcp.example.com/mcp",
                "authorization_servers": ["https://idp.example.com/", authorization_server],
                "bearer_methods_supported": ["header"],
            },
        ),
        authorization_server=(
            404,
            {
                "ok": False,
                "error_code": "EXTERNAL_AUTH_SERVER",
            },
        ),
    )

    assert any("external-oauth authorization server must be a public HTTPS URL" in item for item in failures)


def test_validate_remote_payloads_rejects_mcp_base_url_as_external_oauth_authorization_server() -> None:
    plan = build_endpoint_plan("https://mcp.example.com")
    failures = validate_remote_payloads(
        plan,
        healthz=(200, {"ok": True, "service": "colameta-mcp", "auth_mode": "external-oauth"}),
        mcp=(
            200,
            {
                "ok": True,
                "auth_mode": "external-oauth",
                "protected_resource_metadata": "https://mcp.example.com/.well-known/oauth-protected-resource",
            },
        ),
        protected_resource=(
            200,
            {
                "resource": "https://mcp.example.com/mcp",
                "authorization_servers": ["https://mcp.example.com/"],
                "bearer_methods_supported": ["header"],
            },
        ),
        authorization_server=(
            404,
            {
                "ok": False,
                "error_code": "EXTERNAL_AUTH_SERVER",
            },
        ),
    )

    assert "external-oauth authorization server must not be the MCP public_base_url." in failures
    assert "external-oauth protected resource metadata must list a public external authorization server." in failures


def test_validate_remote_payloads_requires_oauth_for_remote_chatgpt_mcp() -> None:
    plan = build_endpoint_plan("https://mcp.example.com")
    failures = validate_remote_payloads(
        plan,
        healthz=(200, {"ok": True, "service": "colameta-mcp", "auth_mode": "token"}),
        mcp=(200, {"ok": True, "auth_mode": "token"}),
        protected_resource=(404, {}),
        authorization_server=(404, {}),
    )

    assert "healthz auth_mode must be oauth or external-oauth for ChatGPT remote MCP." in failures
    assert "GET /mcp auth_mode must be oauth or external-oauth." in failures
