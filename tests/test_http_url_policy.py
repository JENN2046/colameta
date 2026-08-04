from __future__ import annotations

import ast
import threading
import urllib.request
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import pytest

from runner.http_url_policy import (
    HTTPRedirectPolicy,
    HTTPURLPolicyError,
    _build_restricted_opener,
    open_http_url,
)


class _Response:
    status = 200

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        return False

    def read(self) -> bytes:
        return b"{}"


class _LocalHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - http.server API
        if self.path == "/redirect-file":
            self.send_response(302)
            self.send_header("Location", "file:///etc/passwd")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok": true}')

    def log_message(self, format: str, *args: object) -> None:
        return


@contextmanager
def _local_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _LocalHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def _open_with_fake_transport(url: str, *, timeout: float | None = 3) -> dict[str, object]:
    observed: dict[str, object] = {}

    def fake_open(self: urllib.request.OpenerDirector, request: object, timeout: object = None) -> _Response:
        observed["request"] = request
        observed["timeout"] = timeout
        return _Response()

    with patch.object(urllib.request.OpenerDirector, "open", fake_open):
        with open_http_url(
            url,
            timeout=timeout,
            allowed_schemes={"http", "https"},
            redirect_policy=HTTPRedirectPolicy(),
        ):
            pass
    return observed


def _redirect_handler():
    opener = _build_restricted_opener(
        allowed_schemes=frozenset({"http", "https"}),
        redirect_policy=HTTPRedirectPolicy(),
        host_policy=None,
    )
    return next(handler for handler in opener.handlers if hasattr(handler, "redirect_request"))


def test_allows_http_and_https_before_transport() -> None:
    for url in ("http://example.test/healthz", "https://example.test/healthz"):
        observed = _open_with_fake_transport(url)
        assert isinstance(observed["request"], urllib.request.Request)


def test_http_happy_path_uses_restricted_opener() -> None:
    with _local_server() as base_url:
        with open_http_url(
            f"{base_url}/healthz",
            timeout=2,
            allowed_schemes={"http"},
            redirect_policy=HTTPRedirectPolicy(),
        ) as response:
            assert response.status == 200
            assert response.read() == b'{"ok": true}'


@pytest.mark.parametrize(
    "url",
    (
        "file:///etc/passwd",
        "file://localhost/etc/passwd",
        "ftp://example.test/file",
        "data:text/plain,test",
        "gopher://example.test/",
        "custom://example.test/",
        "example.test/path",
        "/path",
    ),
)
def test_rejects_non_http_initial_urls_before_handler(url: str) -> None:
    with patch.object(urllib.request.OpenerDirector, "open", side_effect=AssertionError("transport called")):
        with pytest.raises(HTTPURLPolicyError):
            open_http_url(
                url,
                timeout=2,
                allowed_schemes={"http", "https"},
                redirect_policy=HTTPRedirectPolicy(),
            )


@pytest.mark.parametrize("target", ("file:///etc/passwd", "ftp://example.test/file", "data:text/plain,test"))
def test_redirect_to_non_http_scheme_is_rejected(target: str) -> None:
    handler = _redirect_handler()
    request = urllib.request.Request("http://example.test/start")

    with pytest.raises(HTTPURLPolicyError):
        handler.redirect_request(request, object(), 302, "Found", {}, target)


def test_https_redirect_downgrade_is_rejected() -> None:
    handler = _redirect_handler()
    request = urllib.request.Request("https://example.test/start")

    with pytest.raises(HTTPURLPolicyError, match="downgrade"):
        handler.redirect_request(request, object(), 302, "Found", {}, "http://example.test/next")


def test_cross_host_redirect_is_rejected() -> None:
    handler = _redirect_handler()
    request = urllib.request.Request("http://example.test/start")

    with pytest.raises(HTTPURLPolicyError, match="cross-host"):
        handler.redirect_request(request, object(), 302, "Found", {}, "http://other.test/next")


def test_real_redirect_is_revalidated() -> None:
    with _local_server() as base_url:
        with pytest.raises(HTTPURLPolicyError):
            with open_http_url(
                f"{base_url}/redirect-file",
                timeout=2,
                allowed_schemes={"http"},
                redirect_policy=HTTPRedirectPolicy(),
            ):
                pass


def test_request_method_headers_and_data_are_preserved_on_redirect() -> None:
    handler = _redirect_handler()
    request = urllib.request.Request(
        "http://example.test/start",
        data=b"payload",
        headers={"X-Test": "preserved", "Content-Type": "application/json"},
        method="PATCH",
    )
    request.add_unredirected_header("Authorization", "Bearer test")

    redirected = handler.redirect_request(request, object(), 307, "Temporary Redirect", {}, "/next")

    assert redirected.get_method() == "PATCH"
    assert redirected.data == b"payload"
    assert redirected.get_header("X-test") == "preserved"
    assert redirected.get_header("Content-type") == "application/json"
    assert redirected.get_header("Authorization") == "Bearer test"
    assert redirected.origin_req_host == request.origin_req_host


def test_timeout_is_passed_to_local_opener() -> None:
    observed = _open_with_fake_transport("http://example.test/healthz", timeout=7.5)
    assert observed["timeout"] == 7.5


def test_does_not_install_global_opener() -> None:
    with patch.object(urllib.request, "install_opener", side_effect=AssertionError("global opener changed")):
        _open_with_fake_transport("http://example.test/healthz")


def test_restricted_opener_has_no_file_or_ftp_handlers() -> None:
    opener = _build_restricted_opener(
        allowed_schemes=frozenset({"http", "https"}),
        redirect_policy=HTTPRedirectPolicy(),
        host_policy=None,
    )
    handler_names = {type(handler).__name__ for handler in opener.handlers}
    assert "FileHandler" not in handler_names
    assert "FTPHandler" not in handler_names
    assert "CacheFTPHandler" not in handler_names
    assert "HTTPHandler" in handler_names
    assert "HTTPSHandler" in handler_names


def test_all_six_production_call_sites_use_the_shared_policy() -> None:
    root = Path(__file__).resolve().parents[1]
    files = (
        root / "adapters/opencode_server_adapter.py",
        root / "runner/mcp_server.py",
        root / "runner/web_console.py",
        root / "scripts/runner_cli.py",
    )
    urlopen_calls = []
    policy_calls = []
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        source = path.read_text(encoding="utf-8")
        assert "open_http_url" in source
        for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Attribute) and node.func.attr == "urlopen":
                        urlopen_calls.append((path.name, node.lineno))
                    if isinstance(node.func, ast.Name) and node.func.id == "open_http_url":
                        policy_calls.append((path.name, node.lineno))

    assert urlopen_calls == []
    assert len(policy_calls) == 6
