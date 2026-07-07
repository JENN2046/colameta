from __future__ import annotations

import argparse
import ipaddress
import json
import re
import socket
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse


class PreflightError(ValueError):
    pass


PREFLIGHT_USER_AGENT = "ColaMeta-Remote-MCP-Preflight/1.0"
MAX_PREFLIGHT_RESPONSE_BYTES = 64 * 1024
REMOTE_MCP_AUTH_MODES = {"oauth", "external-oauth"}
_HEX_HEAD_RE = re.compile(r"^[0-9a-fA-F]{7,128}$")
_FULL_HEX_HEAD_RE = re.compile(r"^[0-9a-fA-F]{40}$")
_NUMERIC_IPV4_PART_RE = re.compile(r"^(?:0[xX][0-9A-Fa-f]+|0[0-7]*|[0-9]+)$")
_LOCAL_ONLY_DNS_SUFFIXES = (
    ".local",
    ".localhost",
    ".localdomain",
    ".home.arpa",
    ".lan",
    ".home",
    ".internal",
    ".intranet",
)


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        raise PreflightError(f"{req.full_url} returned an HTTP redirect; remote preflight probes must not redirect.")


_NO_REDIRECT_OPENER = urllib.request.build_opener(_NoRedirectHandler)


@dataclass(frozen=True)
class EndpointPlan:
    public_base_url: str
    connector_url: str
    healthz_url: str
    protected_resource_metadata_url: str
    authorization_server_metadata_url: str


def normalize_public_base_url(value: str, *, allow_local_http: bool = False) -> str:
    base = value.strip().rstrip("/")
    if not base:
        raise PreflightError("public_base_url is required.")

    parsed = urlparse(base)
    if parsed.scheme not in {"https", "http"}:
        raise PreflightError("public_base_url must start with https://.")
    if not parsed.netloc or not parsed.hostname:
        raise PreflightError("public_base_url must include a host.")
    if parsed.username or parsed.password:
        raise PreflightError("public_base_url must not include userinfo.")
    if parsed.query or parsed.fragment:
        raise PreflightError("public_base_url must not include query or fragment.")
    if parsed.path.rstrip("/").endswith("/mcp"):
        raise PreflightError("public_base_url must be the service base URL, not the /mcp connector URL.")
    if parsed.scheme == "https" and _is_non_public_https_host(parsed.hostname):
        raise PreflightError(
            "remote MCP public_base_url must not use localhost, loopback, private, link-local, "
            "local-only DNS, or otherwise non-public hosts."
        )
    if parsed.scheme == "http" and not allow_local_http:
        raise PreflightError("remote MCP public_base_url must use https://.")
    if parsed.scheme == "http" and allow_local_http and not _is_loopback_host(parsed.hostname):
        raise PreflightError("http:// is allowed only for localhost preflight.")
    return base


def _is_loopback_host(hostname: str | None) -> bool:
    host = (hostname or "").strip().lower().rstrip(".")
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        numeric_ipv4 = _parse_numeric_ipv4_host(host)
        return bool(numeric_ipv4 and numeric_ipv4.is_loopback)


def _is_non_public_https_host(hostname: str | None) -> bool:
    host = (hostname or "").strip().lower().rstrip(".")
    if host == "localhost":
        return True
    try:
        return not ipaddress.ip_address(host).is_global
    except ValueError:
        numeric_ipv4 = _parse_numeric_ipv4_host(host)
        if numeric_ipv4 is not None:
            return not numeric_ipv4.is_global
        if _is_local_only_dns_name(host):
            return True
        return _hostname_resolves_to_non_global_addresses(host)


def _is_local_only_dns_name(host: str) -> bool:
    if not host:
        return False
    if "." not in host:
        return True
    return any(host.endswith(suffix) for suffix in _LOCAL_ONLY_DNS_SUFFIXES)


def _hostname_resolves_to_non_global_addresses(host: str) -> bool:
    try:
        addresses = _resolve_hostname_addresses(host)
    except OSError:
        return True
    return not addresses or any(not address.is_global for address in addresses)


def _resolve_hostname_addresses(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for family, _, _, _, sockaddr in socket.getaddrinfo(host, None, socket.AF_UNSPEC, socket.SOCK_STREAM):
        if family not in {socket.AF_INET, socket.AF_INET6}:
            continue
        raw_address = str(sockaddr[0]).split("%", 1)[0]
        try:
            addresses.append(ipaddress.ip_address(raw_address))
        except ValueError:
            continue
    return addresses


def _parse_numeric_ipv4_host(host: str) -> ipaddress.IPv4Address | None:
    parts = host.split(".")
    if not parts or len(parts) > 4 or any(not part for part in parts):
        return None
    if not all(_NUMERIC_IPV4_PART_RE.match(part) for part in parts):
        return None
    try:
        numbers = [_parse_numeric_ipv4_part(part) for part in parts]
    except ValueError:
        return None

    if len(numbers) == 1:
        value = numbers[0]
        if value > 0xFFFFFFFF:
            return None
    elif len(numbers) == 2:
        if numbers[0] > 0xFF or numbers[1] > 0xFFFFFF:
            return None
        value = (numbers[0] << 24) | numbers[1]
    elif len(numbers) == 3:
        if numbers[0] > 0xFF or numbers[1] > 0xFF or numbers[2] > 0xFFFF:
            return None
        value = (numbers[0] << 24) | (numbers[1] << 16) | numbers[2]
    else:
        if any(number > 0xFF for number in numbers):
            return None
        value = (numbers[0] << 24) | (numbers[1] << 16) | (numbers[2] << 8) | numbers[3]
    return ipaddress.IPv4Address(value)


def _parse_numeric_ipv4_part(part: str) -> int:
    lowered = part.lower()
    if lowered.startswith("0x"):
        return int(lowered, 16)
    if len(lowered) > 1 and lowered.startswith("0"):
        return int(lowered, 8)
    return int(lowered, 10)


def build_endpoint_plan(public_base_url: str) -> EndpointPlan:
    base = public_base_url.rstrip("/")
    return EndpointPlan(
        public_base_url=base,
        connector_url=f"{base}/mcp",
        healthz_url=f"{base}/healthz",
        protected_resource_metadata_url=f"{base}/.well-known/oauth-protected-resource",
        authorization_server_metadata_url=f"{base}/.well-known/oauth-authorization-server",
    )


def fetch_json(url: str, *, timeout_seconds: float = 5.0) -> tuple[int, dict[str, Any]]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": PREFLIGHT_USER_AGENT,
        },
        method="GET",
    )
    try:
        with _NO_REDIRECT_OPENER.open(request, timeout=timeout_seconds) as response:
            _validate_final_response_url(url, _response_final_url(response, url))
            raw = _read_limited_response_body(response, url).decode("utf-8")
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise PreflightError(f"{url} did not return a JSON object.")
            return int(response.status), payload
    except urllib.error.HTTPError as exc:
        _validate_final_response_url(url, _response_final_url(exc, getattr(exc, "url", url)))
        raw = _read_limited_response_body(exc, url).decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"raw": raw[:500]}
        if not isinstance(payload, dict):
            payload = {"raw": str(payload)[:500]}
        return int(exc.code), payload


def _response_final_url(response: Any, fallback: str) -> str:
    geturl = getattr(response, "geturl", None)
    if callable(geturl):
        return str(geturl())
    return fallback


def _read_limited_response_body(response: Any, url: str) -> bytes:
    raw = response.read(MAX_PREFLIGHT_RESPONSE_BYTES + 1)
    if len(raw) > MAX_PREFLIGHT_RESPONSE_BYTES:
        raise PreflightError(f"{url} response body exceeds {MAX_PREFLIGHT_RESPONSE_BYTES} bytes.")
    return raw


def _validate_final_response_url(request_url: str, final_url: str) -> None:
    if not final_url:
        raise PreflightError(f"{request_url} did not report a final response URL.")
    expected = urlparse(request_url)
    actual = urlparse(final_url)
    if (
        actual.scheme != expected.scheme
        or (actual.hostname or "").lower().rstrip(".") != (expected.hostname or "").lower().rstrip(".")
        or actual.port != expected.port
        or actual.path.rstrip("/") != expected.path.rstrip("/")
        or actual.query
        or actual.fragment
    ):
        raise PreflightError(f"{request_url} redirected to an off-base preflight URL.")


def validate_remote_payloads(
    plan: EndpointPlan,
    *,
    healthz: tuple[int, dict[str, Any]],
    mcp: tuple[int, dict[str, Any]],
    protected_resource: tuple[int, dict[str, Any]],
    authorization_server: tuple[int, dict[str, Any]],
    expected_head: str | None = None,
) -> list[str]:
    failures: list[str] = []
    health_status, health_payload = healthz
    if health_status != 200 or health_payload.get("ok") is not True:
        failures.append("healthz must return HTTP 200 with ok=true.")
    if health_payload.get("service") != "colameta-mcp":
        failures.append("healthz service must be colameta-mcp.")
    health_auth_mode = health_payload.get("auth_mode")
    if health_auth_mode not in REMOTE_MCP_AUTH_MODES:
        failures.append("healthz auth_mode must be oauth or external-oauth for ChatGPT remote MCP.")
    if expected_head:
        failures.extend(_validate_health_runtime(health_payload, expected_head))

    mcp_status, mcp_payload = mcp
    if mcp_status != 200 or mcp_payload.get("ok") is not True:
        failures.append("GET /mcp must return HTTP 200 with ok=true readiness metadata.")
    mcp_auth_mode = mcp_payload.get("auth_mode")
    if mcp_auth_mode not in REMOTE_MCP_AUTH_MODES:
        failures.append("GET /mcp auth_mode must be oauth or external-oauth.")
    if mcp_payload.get("protected_resource_metadata") != plan.protected_resource_metadata_url:
        failures.append("GET /mcp must advertise the protected resource metadata URL.")
    auth_mode = mcp_auth_mode if mcp_auth_mode in REMOTE_MCP_AUTH_MODES else health_auth_mode

    resource_status, resource_payload = protected_resource
    if resource_status != 200:
        failures.append("protected resource metadata must return HTTP 200.")
    if resource_payload.get("resource") != plan.connector_url:
        failures.append("protected resource metadata resource must equal the /mcp connector URL.")
    authorization_servers = resource_payload.get("authorization_servers")
    if not isinstance(authorization_servers, list) or not authorization_servers:
        failures.append("protected resource metadata must list at least one authorization server.")
    elif auth_mode == "oauth" and plan.public_base_url not in authorization_servers:
        failures.append("protected resource metadata must list the public base URL as an authorization server.")
    elif auth_mode == "external-oauth":
        failures.extend(_validate_external_oauth_authorization_servers(plan, authorization_servers))
    if "header" not in (resource_payload.get("bearer_methods_supported") or []):
        failures.append("protected resource metadata must support bearer tokens in the header.")

    auth_status, auth_payload = authorization_server
    if auth_mode == "external-oauth":
        if auth_status != 404 or auth_payload.get("error_code") != "EXTERNAL_AUTH_SERVER":
            failures.append("external-oauth must delegate local authorization server metadata to the external IdP.")
        return failures

    if auth_status != 200:
        failures.append("authorization server metadata must return HTTP 200.")
    if auth_payload.get("issuer") != plan.public_base_url:
        failures.append("authorization server issuer must equal public_base_url.")
    required_endpoints = {
        "authorization_endpoint": f"{plan.public_base_url}/authorize",
        "token_endpoint": f"{plan.public_base_url}/token",
        "registration_endpoint": f"{plan.public_base_url}/register",
        "revocation_endpoint": f"{plan.public_base_url}/revoke",
    }
    for key, expected in required_endpoints.items():
        if auth_payload.get(key) != expected:
            failures.append(f"authorization server {key} must equal {expected}.")
    if "authorization_code" not in (auth_payload.get("grant_types_supported") or []):
        failures.append("authorization server must support authorization_code grant.")
    if "S256" not in (auth_payload.get("code_challenge_methods_supported") or []):
        failures.append("authorization server must support PKCE S256.")
    return failures


def _validate_external_oauth_authorization_servers(plan: EndpointPlan, authorization_servers: list[Any]) -> list[str]:
    failures: list[str] = []
    accepted = 0
    for item in authorization_servers:
        if not isinstance(item, str):
            failures.append("external-oauth authorization servers must be HTTPS URL strings.")
            continue
        try:
            normalized = normalize_public_base_url(item)
        except PreflightError as exc:
            failures.append(f"external-oauth authorization server must be a public HTTPS URL: {exc}")
            continue
        if normalized == plan.public_base_url:
            failures.append("external-oauth authorization server must not be the MCP public_base_url.")
            continue
        accepted += 1
    if accepted == 0:
        failures.append("external-oauth protected resource metadata must list a public external authorization server.")
    return failures


def run_preflight(
    public_base_url: str,
    *,
    allow_local_http: bool = False,
    no_network: bool = False,
    timeout_seconds: float = 5.0,
    expected_head: str | None = None,
) -> dict[str, Any]:
    normalized = normalize_public_base_url(public_base_url, allow_local_http=allow_local_http)
    expected_runtime_head = _clean_expected_head(expected_head)
    plan = build_endpoint_plan(normalized)
    report: dict[str, Any] = {
        "ok": True,
        "public_base_url": plan.public_base_url,
        "connector_url": plan.connector_url,
        "healthz_url": plan.healthz_url,
        "protected_resource_metadata_url": plan.protected_resource_metadata_url,
        "authorization_server_metadata_url": plan.authorization_server_metadata_url,
        "network_check": "not_run" if no_network else "run",
        "expected_runtime_head": expected_runtime_head,
        "failures": [],
    }
    if no_network:
        return report

    payloads = {
        "healthz": fetch_json(plan.healthz_url, timeout_seconds=timeout_seconds),
        "mcp": fetch_json(plan.connector_url, timeout_seconds=timeout_seconds),
        "protected_resource": fetch_json(plan.protected_resource_metadata_url, timeout_seconds=timeout_seconds),
        "authorization_server": fetch_json(plan.authorization_server_metadata_url, timeout_seconds=timeout_seconds),
    }
    failures = validate_remote_payloads(
        plan,
        healthz=payloads["healthz"],
        mcp=payloads["mcp"],
        protected_resource=payloads["protected_resource"],
        authorization_server=payloads["authorization_server"],
        expected_head=expected_runtime_head,
    )
    report["responses"] = {
        key: {"status": status, "keys": sorted(payload.keys())}
        for key, (status, payload) in payloads.items()
    }
    report["healthz_runtime"] = _health_runtime_evidence(payloads["healthz"][1])
    report["failures"] = failures
    report["ok"] = not failures
    return report


def _validate_health_runtime(health_payload: dict[str, Any], expected_head: str) -> list[str]:
    if _health_runtime_matches_expected(health_payload, expected_head):
        return []
    return ["healthz runtime provenance must prove the public MCP endpoint is serving expected_head."]


def _health_runtime_matches_expected(health: dict[str, Any], expected_head: str) -> bool:
    loaded_runtime_head = _reported_loaded_runtime_head(health.get("loaded_runtime_head"))
    if loaded_runtime_head is not None:
        return (
            loaded_runtime_head == expected_head
            and _health_runtime_reload_verified(health)
            and _health_runtime_source_clean(health)
        )
    return (
        _clean_head(health.get("runtime_project_checkout_head") or health.get("project_checkout_head")) == expected_head
        and _health_runtime_reload_verified(health)
        and _health_runtime_source_clean(health)
        and health.get("installed_package_matches_project_checkout") is True
        and health.get("installed_package_verification_status") == "match"
    )


def _reported_loaded_runtime_head(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return _clean_head(value) or ""


def _health_runtime_reload_verified(health: dict[str, Any]) -> bool:
    return health.get("runtime_loaded_code_stale") is False and health.get("reload_needed_for_verification") is False


def _health_runtime_source_clean(health: dict[str, Any]) -> bool:
    return (
        health.get("installed_package_project_source_clean") is True
        and health.get("installed_package_source_cleanliness_status") == "clean"
    )


def _health_runtime_evidence(health: dict[str, Any]) -> dict[str, Any]:
    return {
        "loaded_runtime_head": _clean_head(health.get("loaded_runtime_head")),
        "runtime_project_checkout_head": _clean_head(
            health.get("runtime_project_checkout_head") or health.get("project_checkout_head")
        ),
        "runtime_loaded_code_stale": health.get("runtime_loaded_code_stale")
        if isinstance(health.get("runtime_loaded_code_stale"), bool)
        else None,
        "reload_needed_for_verification": health.get("reload_needed_for_verification")
        if isinstance(health.get("reload_needed_for_verification"), bool)
        else None,
        "installed_package_matches_project_checkout": health.get("installed_package_matches_project_checkout")
        if isinstance(health.get("installed_package_matches_project_checkout"), bool)
        else None,
        "installed_package_verification_status": health.get("installed_package_verification_status")
        if isinstance(health.get("installed_package_verification_status"), str)
        else None,
        "installed_package_project_source_clean": health.get("installed_package_project_source_clean")
        if isinstance(health.get("installed_package_project_source_clean"), bool)
        else None,
        "installed_package_source_cleanliness_status": health.get("installed_package_source_cleanliness_status")
        if isinstance(health.get("installed_package_source_cleanliness_status"), str)
        else None,
    }


def _clean_head(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if _HEX_HEAD_RE.match(candidate):
        return candidate
    return None


def _clean_expected_head(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not _FULL_HEX_HEAD_RE.match(value.strip()):
        raise PreflightError("expected_head must be a full 40-character commit SHA.")
    return value.strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Preflight a ColaMeta HTTPS remote MCP endpoint.")
    parser.add_argument("public_base_url", help="Service base URL, for example https://mcp.example.com")
    parser.add_argument("--allow-local-http", action="store_true", help="Allow http://localhost for local dry runs.")
    parser.add_argument("--no-network", action="store_true", help="Validate URL shape only; do not call endpoints.")
    parser.add_argument("--timeout", type=float, default=5.0, help="Per-request timeout in seconds.")
    parser.add_argument("--expected-head", help="Expected runtime Git commit served by public /healthz.")
    args = parser.parse_args(argv)

    try:
        report = run_preflight(
            args.public_base_url,
            allow_local_http=args.allow_local_http,
            no_network=args.no_network,
            timeout_seconds=args.timeout,
            expected_head=args.expected_head,
        )
    except Exception as exc:
        report = {"ok": False, "failures": [str(exc)]}
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 2

    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
