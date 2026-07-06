from __future__ import annotations

import json
import time

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt import PyJWKClient
from jwt.algorithms import RSAAlgorithm

from runner.mcp_external_oauth import ExternalOAuthConfig, ExternalOAuthProvider


ISSUER = "https://idp.example.com/"
PUBLIC_BASE_URL = "https://colameta-mcp.example.com"
RESOURCE = f"{PUBLIC_BASE_URL}/mcp"
AUDIENCE = "https://colameta-api.example.com"
JWKS_URL = f"{ISSUER}.well-known/jwks.json"
KEY_ID = "test-key"


def _key_and_jwks() -> tuple[object, dict[str, object]]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(RSAAlgorithm.to_jwk(private_key.public_key()))
    jwk.update({"kid": KEY_ID, "use": "sig", "alg": "RS256"})
    return private_key, {"keys": [jwk]}


def _provider(
    monkeypatch,
    *,
    audience: str | None = AUDIENCE,
    scopes: tuple[str, ...] = ("mcp:read", "mcp:preview", "mcp:commit", "mcp:plan"),
) -> tuple[ExternalOAuthProvider, object]:
    private_key, jwks = _key_and_jwks()
    monkeypatch.setattr(PyJWKClient, "fetch_data", lambda self: jwks)
    provider = ExternalOAuthProvider(
        ExternalOAuthConfig(
            public_base_url=PUBLIC_BASE_URL,
            issuer=ISSUER,
            jwks_url=JWKS_URL,
            audience=audience,
            scopes=scopes,
            token_leeway_seconds=0,
        )
    )
    return provider, private_key


def _token(private_key: object, **overrides: object) -> str:
    now = int(time.time())
    payload: dict[str, object] = {
        "iss": ISSUER,
        "sub": "user-1",
        "aud": AUDIENCE,
        "iat": now,
        "nbf": now - 1,
        "exp": now + 600,
        "scope": "mcp:read mcp:preview",
    }
    remove = overrides.pop("_remove", ())
    payload.update(overrides)
    for key in remove if isinstance(remove, tuple) else ():
        payload.pop(str(key), None)
    return jwt.encode(payload, private_key, algorithm="RS256", headers={"kid": KEY_ID})


def test_external_oauth_validates_jwks_issuer_audience_and_scope(monkeypatch) -> None:
    provider, private_key = _provider(monkeypatch)

    payload = provider.validate_token(_token(private_key))

    assert payload is not None
    assert payload["sub"] == "user-1"
    assert provider.validate_scope(payload, "mcp:read") is True
    assert provider.validate_scope(payload, "mcp:commit") is False


def test_external_oauth_rejects_wrong_issuer(monkeypatch) -> None:
    provider, private_key = _provider(monkeypatch)

    assert provider.validate_token(_token(private_key, iss="https://other-idp.example.com/")) is None


def test_external_oauth_rejects_wrong_audience_and_resource(monkeypatch) -> None:
    provider, private_key = _provider(monkeypatch)

    assert provider.validate_token(_token(private_key, aud="https://other-api.example.com", resource="https://other")) is None


def test_external_oauth_accepts_resource_claim_when_audience_uses_resource(monkeypatch) -> None:
    provider, private_key = _provider(monkeypatch, audience=None)

    payload = provider.validate_token(_token(private_key, aud="https://other-api.example.com", resource=RESOURCE))

    assert payload is not None
    assert payload["resource"] == RESOURCE


def test_external_oauth_rejects_expired_or_exp_missing_token(monkeypatch) -> None:
    provider, private_key = _provider(monkeypatch)
    now = int(time.time())

    assert provider.validate_token(_token(private_key, exp=now - 1)) is None
    assert provider.validate_token(_token(private_key, _remove=("exp",))) is None


def test_external_oauth_scope_claim_variants(monkeypatch) -> None:
    provider, private_key = _provider(monkeypatch)

    payload = provider.validate_token(
        _token(private_key, _remove=("scope",), scp=["mcp:read"], permissions=["mcp:commit"])
    )

    assert payload is not None
    assert provider.validate_scope(payload, "mcp:read") is True
    assert provider.validate_scope(payload, "mcp:commit") is True
    assert provider.validate_scope(payload, "mcp:plan") is False


def test_external_oauth_configured_scopes_are_server_side_allowlist(monkeypatch) -> None:
    provider, private_key = _provider(monkeypatch, scopes=("mcp:read", "mcp:preview"))

    payload = provider.validate_token(
        _token(private_key, _remove=("scope",), scp=["mcp:read"], permissions=["mcp:commit"])
    )

    assert payload is not None
    assert provider.validate_scope(payload, "mcp:read") is True
    assert provider.validate_scope(payload, "mcp:commit") is False
    assert provider.protected_resource_metadata()["scopes_supported"] == ["mcp:read", "mcp:preview"]


def test_external_oauth_protected_resource_metadata_points_to_external_issuer(monkeypatch) -> None:
    provider, _private_key = _provider(monkeypatch)

    metadata = provider.protected_resource_metadata()

    assert metadata["resource"] == RESOURCE
    assert metadata["authorization_servers"] == [ISSUER]
    assert metadata["bearer_methods_supported"] == ["header"]
    assert "mcp:read" in metadata["scopes_supported"]
    assert provider.protected_resource_metadata_url() == f"{PUBLIC_BASE_URL}/.well-known/oauth-protected-resource"
