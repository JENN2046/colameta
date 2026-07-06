from __future__ import annotations

import argparse
import ipaddress
import json
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse


class PreflightError(ValueError):
    pass


PREFLIGHT_USER_AGENT = "ColaMeta-Remote-MCP-Preflight/1.0"
REMOTE_MCP_AUTH_MODES = {"oauth", "external-oauth"}


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
        return False


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
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise PreflightError(f"{url} did not return a JSON object.")
            return int(response.status), payload
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"raw": raw[:500]}
        if not isinstance(payload, dict):
            payload = {"raw": str(payload)[:500]}
        return int(exc.code), payload


def validate_remote_payloads(
    plan: EndpointPlan,
    *,
    healthz: tuple[int, dict[str, Any]],
    mcp: tuple[int, dict[str, Any]],
    protected_resource: tuple[int, dict[str, Any]],
    authorization_server: tuple[int, dict[str, Any]],
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
    elif auth_mode == "external-oauth" and not any(
        isinstance(item, str) and item.startswith("https://") for item in authorization_servers
    ):
        failures.append("external-oauth protected resource metadata must list an HTTPS authorization server.")
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


def run_preflight(
    public_base_url: str,
    *,
    allow_local_http: bool = False,
    no_network: bool = False,
    timeout_seconds: float = 5.0,
) -> dict[str, Any]:
    normalized = normalize_public_base_url(public_base_url, allow_local_http=allow_local_http)
    plan = build_endpoint_plan(normalized)
    report: dict[str, Any] = {
        "ok": True,
        "public_base_url": plan.public_base_url,
        "connector_url": plan.connector_url,
        "healthz_url": plan.healthz_url,
        "protected_resource_metadata_url": plan.protected_resource_metadata_url,
        "authorization_server_metadata_url": plan.authorization_server_metadata_url,
        "network_check": "not_run" if no_network else "run",
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
    )
    report["responses"] = {
        key: {"status": status, "keys": sorted(payload.keys())}
        for key, (status, payload) in payloads.items()
    }
    report["failures"] = failures
    report["ok"] = not failures
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Preflight a ColaMeta HTTPS remote MCP endpoint.")
    parser.add_argument("public_base_url", help="Service base URL, for example https://mcp.example.com")
    parser.add_argument("--allow-local-http", action="store_true", help="Allow http://localhost for local dry runs.")
    parser.add_argument("--no-network", action="store_true", help="Validate URL shape only; do not call endpoints.")
    parser.add_argument("--timeout", type=float, default=5.0, help="Per-request timeout in seconds.")
    args = parser.parse_args(argv)

    try:
        report = run_preflight(
            args.public_base_url,
            allow_local_http=args.allow_local_http,
            no_network=args.no_network,
            timeout_seconds=args.timeout,
        )
    except Exception as exc:
        report = {"ok": False, "failures": [str(exc)]}
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 2

    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
