from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from runner.mcp_oauth import DEFAULT_SCOPES

try:
    import jwt
    from jwt import PyJWKClient
except Exception:  # pragma: no cover - exercised when optional dependency is missing.
    jwt = None
    PyJWKClient = None


DEFAULT_JWT_ALGORITHMS = ("RS256",)
DEFAULT_TOKEN_LEEWAY_SECONDS = 60


@dataclass(frozen=True)
class ExternalOAuthConfig:
    public_base_url: str
    issuer: str
    jwks_url: str
    audience: str | None = None
    scopes: tuple[str, ...] = DEFAULT_SCOPES
    algorithms: tuple[str, ...] = DEFAULT_JWT_ALGORITHMS
    token_leeway_seconds: int = DEFAULT_TOKEN_LEEWAY_SECONDS


class ExternalOAuthProvider:
    """Resource-server side verifier for JWT access tokens issued by an external IdP."""

    def __init__(self, config: ExternalOAuthConfig):
        self.public_base_url = config.public_base_url.rstrip("/")
        self.resource = f"{self.public_base_url}/mcp"
        self.issuer = config.issuer.strip()
        self.jwks_url = config.jwks_url.strip()
        self.audience = config.audience.strip() if isinstance(config.audience, str) and config.audience.strip() else None
        self.scopes = _normalize_sequence(config.scopes, DEFAULT_SCOPES)
        self.algorithms = _normalize_sequence(config.algorithms, DEFAULT_JWT_ALGORITHMS)
        self.token_leeway_seconds = max(int(config.token_leeway_seconds), 0)
        self._jwks_client = PyJWKClient(self.jwks_url) if PyJWKClient is not None else None

    def protected_resource_metadata(self) -> dict[str, Any]:
        return {
            "resource": self.resource,
            "authorization_servers": [self.issuer],
            "bearer_methods_supported": ["header"],
            "resource_name": "ColaMeta MCP",
            "scopes_supported": list(self.scopes),
        }

    def protected_resource_metadata_url(self) -> str:
        return f"{self.public_base_url}/.well-known/oauth-protected-resource"

    def validate_token(self, token: str) -> dict[str, Any] | None:
        if jwt is None or self._jwks_client is None:
            return None
        try:
            signing_key = self._jwks_client.get_signing_key_from_jwt(token)
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=list(self.algorithms),
                issuer=self.issuer,
                options={
                    "require": ["exp"],
                    "verify_aud": False,
                },
                leeway=self.token_leeway_seconds,
            )
        except Exception:
            return None
        if not isinstance(payload, dict):
            return None
        if not self._accepts_audience_or_resource(payload):
            return None
        return payload

    def validate_scope(self, token_payload: dict[str, Any], required_scope: str) -> bool:
        return required_scope in self.scopes and required_scope in _extract_scopes(token_payload)

    def _accepts_audience_or_resource(self, payload: dict[str, Any]) -> bool:
        expected_audience = self.audience or self.resource
        if _claim_contains(payload.get("aud"), expected_audience):
            return True
        return _claim_contains(payload.get("resource"), self.resource)


def _normalize_sequence(value: object, fallback: tuple[str, ...]) -> tuple[str, ...]:
    if isinstance(value, str):
        items = value.replace(",", " ").split()
    elif isinstance(value, (list, tuple, set)):
        items = [item for item in value if isinstance(item, str)]
    else:
        items = list(fallback)
    normalized = tuple(dict.fromkeys(item.strip() for item in items if item.strip()))
    return normalized or tuple(fallback)


def _claim_contains(claim: object, expected: str) -> bool:
    if isinstance(claim, str):
        return claim == expected
    if isinstance(claim, (list, tuple, set)):
        return any(isinstance(item, str) and item == expected for item in claim)
    return False


def _extract_scopes(payload: dict[str, Any]) -> set[str]:
    scopes: set[str] = set()
    for key in ("scope", "scp", "permissions"):
        value = payload.get(key)
        if isinstance(value, str):
            scopes.update(item for item in value.split() if item)
        elif isinstance(value, (list, tuple, set)):
            scopes.update(item for item in value if isinstance(item, str) and item)
    return scopes
