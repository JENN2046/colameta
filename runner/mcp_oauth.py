import base64
import hashlib
import html
import json
import os
import secrets
import time
from dataclasses import dataclass
from threading import Lock
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from runner.runner_paths import resolve_project_runner_path, resolve_user_config_dir

DEFAULT_SCOPES = ("mcp:read", "mcp:preview", "mcp:commit", "mcp:plan")


def default_server_oauth_store_file() -> str:
    return os.path.join(resolve_user_config_dir(), "server", "oauth-store.json")


@dataclass
class OAuthClient:
    client_id: str
    client_name: str
    redirect_uris: list[str]
    scope: str
    client_id_issued_at: int


@dataclass
class AuthorizationCode:
    code: str
    client_id: str
    redirect_uri: str
    code_challenge: str
    code_challenge_method: str
    scope: str
    expires_at: int
    created_at: int


@dataclass
class AccessToken:
    token: str
    client_id: str
    scope: str
    expires_at: int
    created_at: int


class MCPOAuthStore:
    def __init__(self, project_root: str, store_file: str | None = None):
        if store_file is not None:
            self.store_file = os.path.abspath(os.path.expanduser(store_file))
        else:
            runtime_dir = resolve_project_runner_path(project_root, "runtime")
            self.store_file = os.path.join(runtime_dir, "oauth-store.json")
        self._lock = Lock()

    def load(self) -> dict[str, Any]:
        with self._lock:
            return self._load_unlocked()

    def save(self, data: dict[str, Any]) -> None:
        with self._lock:
            self._save_unlocked(data)

    def cleanup_expired(self) -> None:
        now = int(time.time())
        with self._lock:
            data = self._load_unlocked()
            changed = False
            codes = data.get("authorization_codes")
            if isinstance(codes, dict):
                filtered_codes = {
                    key: value
                    for key, value in codes.items()
                    if isinstance(value, dict) and int(value.get("expires_at") or 0) > now
                }
                if len(filtered_codes) != len(codes):
                    data["authorization_codes"] = filtered_codes
                    changed = True
            tokens = data.get("access_tokens")
            if isinstance(tokens, dict):
                filtered_tokens = {
                    key: value
                    for key, value in tokens.items()
                    if isinstance(value, dict) and int(value.get("expires_at") or 0) > now
                }
                if len(filtered_tokens) != len(tokens):
                    data["access_tokens"] = filtered_tokens
                    changed = True
            if changed:
                self._save_unlocked(data)

    def register_client(self, client: OAuthClient) -> None:
        with self._lock:
            data = self._load_unlocked()
            data["clients"][client.client_id] = {
                "client_id": client.client_id,
                "client_name": client.client_name,
                "redirect_uris": client.redirect_uris,
                "scope": client.scope,
                "client_id_issued_at": client.client_id_issued_at,
            }
            self._save_unlocked(data)

    def get_client(self, client_id: str) -> dict[str, Any] | None:
        data = self.load()
        client = data.get("clients", {}).get(client_id)
        return client if isinstance(client, dict) else None

    def create_authorization_code(self, code: AuthorizationCode) -> None:
        with self._lock:
            data = self._load_unlocked()
            data["authorization_codes"][code.code] = {
                "code": code.code,
                "client_id": code.client_id,
                "redirect_uri": code.redirect_uri,
                "code_challenge": code.code_challenge,
                "code_challenge_method": code.code_challenge_method,
                "scope": code.scope,
                "expires_at": code.expires_at,
                "created_at": code.created_at,
            }
            self._save_unlocked(data)

    def pop_authorization_code(self, code: str) -> dict[str, Any] | None:
        with self._lock:
            data = self._load_unlocked()
            codes = data.get("authorization_codes", {})
            payload = codes.pop(code, None) if isinstance(codes, dict) else None
            self._save_unlocked(data)
        return payload if isinstance(payload, dict) else None

    def create_access_token(self, token: AccessToken) -> None:
        with self._lock:
            data = self._load_unlocked()
            data["access_tokens"][token.token] = {
                "token": token.token,
                "client_id": token.client_id,
                "scope": token.scope,
                "expires_at": token.expires_at,
                "created_at": token.created_at,
            }
            self._save_unlocked(data)

    def validate_token(self, token: str) -> dict[str, Any] | None:
        data = self.load()
        if token in data.get("revoked_tokens", {}):
            return None
        payload = data.get("access_tokens", {}).get(token)
        if not isinstance(payload, dict):
            return None
        if int(payload.get("expires_at") or 0) <= int(time.time()):
            return None
        return payload

    def revoke_token(self, token: str) -> None:
        with self._lock:
            data = self._load_unlocked()
            if isinstance(data.get("access_tokens"), dict):
                data["access_tokens"].pop(token, None)
            data["revoked_tokens"][token] = {"revoked_at": int(time.time())}
            self._save_unlocked(data)

    def _load_unlocked(self) -> dict[str, Any]:
        if not os.path.exists(self.store_file):
            return self._empty_store()
        try:
            with open(self.store_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return self._empty_store()
        if not isinstance(data, dict):
            return self._empty_store()
        for key in ("clients", "authorization_codes", "access_tokens", "revoked_tokens"):
            if not isinstance(data.get(key), dict):
                data[key] = {}
        data.setdefault("created_at", self._timestamp())
        data["updated_at"] = self._timestamp()
        return data

    def _save_unlocked(self, data: dict[str, Any]) -> None:
        os.makedirs(os.path.dirname(self.store_file), exist_ok=True)
        now = self._timestamp()
        data.setdefault("created_at", now)
        data["updated_at"] = now
        with open(self.store_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.write("\n")

    def _empty_store(self) -> dict[str, Any]:
        now = self._timestamp()
        return {
            "clients": {},
            "authorization_codes": {},
            "access_tokens": {},
            "revoked_tokens": {},
            "created_at": now,
            "updated_at": now,
        }

    def _timestamp(self) -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class MCPOAuthProvider:
    def __init__(
        self,
        project_root: str,
        public_base_url: str,
        token_ttl_seconds: int = 3600,
        store_file: str | None = None,
    ):
        self.project_root = os.path.abspath(os.path.expanduser(project_root))
        self.public_base_url = public_base_url.rstrip("/")
        self.token_ttl_seconds = token_ttl_seconds
        self.code_ttl_seconds = 300
        if store_file is not None:
            self.store = MCPOAuthStore(self.project_root, store_file=store_file)
        else:
            self.store = MCPOAuthStore(self.project_root)

    def protected_resource_metadata(self) -> dict[str, Any]:
        return {
            "resource": f"{self.public_base_url}/mcp",
            "authorization_servers": [self.public_base_url],
            "bearer_methods_supported": ["header"],
            "resource_name": "MVP Runner MCP",
        }

    def authorization_server_metadata(self) -> dict[str, Any]:
        return {
            "issuer": self.public_base_url,
            "authorization_endpoint": f"{self.public_base_url}/authorize",
            "token_endpoint": f"{self.public_base_url}/token",
            "registration_endpoint": f"{self.public_base_url}/register",
            "revocation_endpoint": f"{self.public_base_url}/revoke",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none"],
            "scopes_supported": list(DEFAULT_SCOPES),
        }

    def register_client(self, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        redirect_uris = payload.get("redirect_uris")
        if not isinstance(redirect_uris, list) or not redirect_uris:
            return self._oauth_error(400, "invalid_request", "redirect_uris must be a non-empty array.")
        normalized_redirects: list[str] = []
        for uri in redirect_uris:
            if not isinstance(uri, str) or not uri.startswith(("http://", "https://")):
                return self._oauth_error(400, "invalid_request", "redirect_uri must start with http:// or https://.")
            normalized_redirects.append(uri)

        requested_scope = payload.get("scope")
        scope_result = self._normalize_scope(requested_scope)
        if scope_result is None:
            return self._oauth_error(400, "invalid_scope", "scope is not allowed.")

        now = int(time.time())
        client_name = payload.get("client_name")
        client = OAuthClient(
            client_id=secrets.token_urlsafe(32),
            client_name=client_name if isinstance(client_name, str) and client_name else "MVP Runner MCP Client",
            redirect_uris=normalized_redirects,
            scope=scope_result,
            client_id_issued_at=now,
        )
        self.store.register_client(client)
        return 201, {
            "client_id": client.client_id,
            "client_id_issued_at": client.client_id_issued_at,
            "client_name": client.client_name,
            "redirect_uris": client.redirect_uris,
            "grant_types": ["authorization_code"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
            "scope": client.scope,
        }

    def authorize(self, query: dict[str, list[str]]) -> dict[str, Any]:
        params = {key: values[-1] for key, values in query.items() if values}
        client_id = params.get("client_id", "")
        redirect_uri = params.get("redirect_uri", "")
        state = params.get("state", "")

        client = self.store.get_client(client_id)
        if client is None:
            return self._html_response(400, "OAuth 授权失败", "client_id 无效。")
        if redirect_uri not in client.get("redirect_uris", []):
            return self._html_response(400, "OAuth 授权失败", "redirect_uri 未注册。")
        if params.get("response_type") != "code":
            return self._html_response(400, "OAuth 授权失败", "response_type 必须是 code。")
        code_challenge = params.get("code_challenge", "")
        if not code_challenge or params.get("code_challenge_method") != "S256":
            return self._html_response(400, "OAuth 授权失败", "PKCE 必须使用 S256。")
        scope = self._normalize_scope(params.get("scope") or client.get("scope"))
        if scope is None:
            return self._redirect_with_query(redirect_uri, {"error": "invalid_scope", "state": state})
        client_scopes = set(str(client.get("scope") or "").split())
        if any(item not in client_scopes for item in scope.split()):
            return self._redirect_with_query(redirect_uri, {"error": "invalid_scope", "state": state})

        if params.get("deny") == "1":
            return self._redirect_with_query(redirect_uri, {"error": "access_denied", "state": state})

        if params.get("approve") != "1":
            return self._authorization_page(params, client, scope)

        now = int(time.time())
        code = secrets.token_urlsafe(32)
        self.store.create_authorization_code(
            AuthorizationCode(
                code=code,
                client_id=client_id,
                redirect_uri=redirect_uri,
                code_challenge=code_challenge,
                code_challenge_method="S256",
                scope=scope,
                expires_at=now + self.code_ttl_seconds,
                created_at=now,
            )
        )
        return self._redirect_with_query(redirect_uri, {"code": code, "state": state})

    def exchange_token(self, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        if payload.get("grant_type") != "authorization_code":
            return self._oauth_error(400, "unsupported_grant_type", "grant_type must be authorization_code.")
        code_value = payload.get("code")
        client_id = payload.get("client_id")
        redirect_uri = payload.get("redirect_uri")
        code_verifier = payload.get("code_verifier")
        if not all(isinstance(value, str) and value for value in (code_value, client_id, redirect_uri, code_verifier)):
            return self._oauth_error(400, "invalid_request", "code, client_id, redirect_uri and code_verifier are required.")

        code = self.store.pop_authorization_code(code_value)
        if code is None:
            return self._oauth_error(400, "invalid_grant", "authorization code is invalid.")
        if int(code.get("expires_at") or 0) <= int(time.time()):
            return self._oauth_error(400, "invalid_grant", "authorization code expired.")
        if code.get("client_id") != client_id or code.get("redirect_uri") != redirect_uri:
            return self._oauth_error(400, "invalid_grant", "authorization code does not match the client.")
        if code.get("code_challenge_method") != "S256":
            return self._oauth_error(400, "invalid_grant", "unsupported PKCE method.")
        expected = str(code.get("code_challenge") or "")
        actual = self._s256_challenge(code_verifier)
        if not secrets.compare_digest(expected, actual):
            return self._oauth_error(400, "invalid_grant", "PKCE verification failed.")

        now = int(time.time())
        access_token = secrets.token_urlsafe(48)
        token = AccessToken(
            token=access_token,
            client_id=client_id,
            scope=str(code.get("scope") or " ".join(DEFAULT_SCOPES)),
            expires_at=now + self.token_ttl_seconds,
            created_at=now,
        )
        self.store.create_access_token(token)
        return 200, {
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": self.token_ttl_seconds,
            "scope": token.scope,
        }

    def revoke_token(self, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        token = payload.get("token")
        if isinstance(token, str) and token:
            self.store.revoke_token(token)
        return 200, {"ok": True}

    def validate_token(self, token: str) -> dict[str, Any] | None:
        self.store.cleanup_expired()
        return self.store.validate_token(token)

    def validate_scope(self, token_payload: dict[str, Any], required_scope: str) -> bool:
        scope = token_payload.get("scope")
        scopes = set(scope.split()) if isinstance(scope, str) else set()
        return required_scope in scopes

    def _authorization_page(self, params: dict[str, str], client: dict[str, Any], scope: str) -> dict[str, Any]:
        approve_params = dict(params)
        approve_params["approve"] = "1"
        deny_params = dict(params)
        deny_params["deny"] = "1"
        approve_url = f"/authorize?{urlencode(approve_params)}"
        deny_url = f"/authorize?{urlencode(deny_params)}"
        client_name = html.escape(str(client.get("client_name") or "MVP Runner MCP Client"))
        scope_text = html.escape(scope)

        body = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>MVP Runner MCP 授权</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f7f3ea; color: #201a13; margin: 0; }}
    main {{ max-width: 680px; margin: 10vh auto; background: #fffaf0; border: 1px solid #e8dcc9; border-radius: 24px; padding: 32px; box-shadow: 0 24px 70px rgba(68, 48, 22, 0.14); }}
    h1 {{ margin: 0 0 16px; font-size: 28px; }}
    p {{ line-height: 1.6; }}
    .meta {{ background: #f1e7d6; border-radius: 16px; padding: 16px; margin: 18px 0; word-break: break-word; }}
    .actions {{ display: flex; gap: 12px; margin-top: 24px; }}
    a {{ color: #5f3b12; }}
    .allow {{ background: #201a13; color: #fffaf0; padding: 12px 18px; border-radius: 999px; text-decoration: none; border: none; font-size: 16px; cursor: pointer; }}
    .deny {{ padding: 12px 18px; }}
  </style>
</head>
<body>
  <main>
    <h1>MVP Runner MCP 授权</h1>
    <p>客户端 <strong>{client_name}</strong> 请求访问 MCP 接口。</p>
    <div class="meta">
      <div><strong>权限：</strong>{scope_text}</div>
    </div>
    <p>授权后客户端可以读取 Runner 状态，并在获得 preview/commit 权限时执行受控预览与提交流程。</p>
    <div class="actions">
      <form action="/authorize" method="GET" style="display:inline">"""

        for key, value in params.items():
            if key in ("approve", "deny"):
                continue
            body += f'<input type="hidden" name="{html.escape(key)}" value="{html.escape(value)}">\n'

        body += f"""<button class="allow" type="submit" name="approve" value="1">Allow</button>
      </form>
      <a class="deny" href="{html.escape(deny_url)}">Deny</a>
    </div>
  </main>
</body>
</html>"""
        return {"kind": "html", "status": 200, "body": body}

    def _html_response(self, status: int, title: str, message: str) -> dict[str, Any]:
        body = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>{html.escape(title)}</title></head>
<body><h1>{html.escape(title)}</h1><p>{html.escape(message)}</p></body></html>"""
        return {"kind": "html", "status": status, "body": body}

    def _redirect_with_query(self, redirect_uri: str, values: dict[str, str]) -> dict[str, Any]:
        parsed = urlparse(redirect_uri)
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        for key, value in values.items():
            if value:
                query[key] = value
        location = urlunparse(parsed._replace(query=urlencode(query)))
        return {"kind": "redirect", "status": 302, "location": location}

    def _normalize_scope(self, scope: Any) -> str | None:
        if scope is None or scope == "":
            return " ".join(DEFAULT_SCOPES)
        if not isinstance(scope, str):
            return None
        requested = [item for item in scope.split() if item]
        if not requested:
            return " ".join(DEFAULT_SCOPES)
        allowed = set(DEFAULT_SCOPES)
        if any(item not in allowed for item in requested):
            return None
        return " ".join(requested)

    def _s256_challenge(self, code_verifier: str) -> str:
        digest = hashlib.sha256(code_verifier.encode("utf-8")).digest()
        return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")

    def _oauth_error(self, status: int, error: str, description: str) -> tuple[int, dict[str, Any]]:
        return status, {"error": error, "error_description": description}
