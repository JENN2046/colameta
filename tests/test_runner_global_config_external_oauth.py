from __future__ import annotations

from runner.runner_global_config import RunnerGlobalConfigStore


def test_external_oauth_config_requires_issuer_and_jwks_url(tmp_path) -> None:
    store = RunnerGlobalConfigStore(config_dir=str(tmp_path))

    result = store.validate_config(
        {
            "public_base_url": "https://mcp.example.com",
            "auth_mode": "external-oauth",
        }
    )

    assert result["ok"] is False
    assert result["error_code"] == "INVALID_OAUTH_ISSUER"


def test_external_oauth_config_accepts_non_secret_idp_metadata(tmp_path) -> None:
    store = RunnerGlobalConfigStore(config_dir=str(tmp_path))

    result = store.validate_config(
        {
            "public_base_url": "https://mcp.example.com",
            "auth_mode": "external-oauth",
            "oauth_issuer": "https://idp.example.com/",
            "oauth_jwks_url": "https://idp.example.com/.well-known/jwks.json",
            "oauth_audience": "https://mcp.example.com/mcp",
            "oauth_scopes": "mcp:read,mcp:preview",
            "oauth_algorithms": "RS256",
            "oauth_token_leeway_seconds": 30,
        }
    )

    assert result["ok"] is True
    config = result["config"]
    assert config["auth_mode"] == "external-oauth"
    assert config["oauth_issuer"] == "https://idp.example.com/"
    assert config["oauth_jwks_url"] == "https://idp.example.com/.well-known/jwks.json"
    assert config["oauth_token_leeway_seconds"] == 30
