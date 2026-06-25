from __future__ import annotations

import json
import os
import secrets
from dataclasses import asdict, dataclass
from typing import Any

from runner._internal_utils import write_json_atomic
from runner.runner_paths import user_config_dir


DEFAULT_SCHEMA_VERSION = 1
DEFAULT_WEB_HOST = "127.0.0.1"
DEFAULT_WEB_PORT = 8799
DEFAULT_MCP_HOST = "127.0.0.1"
DEFAULT_MCP_PORT = 8765
DEFAULT_AUTH_MODE = "oauth"
AUTH_FILE_MODE = 0o600


@dataclass(frozen=True)
class RunnerGlobalConfig:
    schema_version: int
    public_base_url: str | None
    web_host: str
    web_port: int
    mcp_host: str
    mcp_port: int
    auth_mode: str


@dataclass(frozen=True)
class RunnerGlobalAuth:
    schema_version: int
    auth_token_configured: bool
    auth_token: str | None = None


class RunnerGlobalConfigStore:
    def __init__(self, config_dir: str | None = None):
        self._config_dir = self._resolve_config_dir(config_dir)

    def config_dir(self) -> str:
        return self._config_dir

    def config_path(self) -> str:
        return os.path.join(self._config_dir, "config.json")

    def auth_path(self) -> str:
        return os.path.join(self._config_dir, "auth.json")

    def default_config(self) -> dict[str, Any]:
        return asdict(
            RunnerGlobalConfig(
                schema_version=DEFAULT_SCHEMA_VERSION,
                public_base_url=None,
                web_host=DEFAULT_WEB_HOST,
                web_port=DEFAULT_WEB_PORT,
                mcp_host=DEFAULT_MCP_HOST,
                mcp_port=DEFAULT_MCP_PORT,
                auth_mode=DEFAULT_AUTH_MODE,
            )
        )

    def validate_config(self, config: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(config, dict):
            return self._error("INVALID_CONFIG", "config 必须是 JSON 对象。", action="validate_config")

        normalized = self.default_config()
        if "schema_version" in config:
            schema_version = config.get("schema_version")
            if not self._is_int(schema_version) or int(schema_version) != DEFAULT_SCHEMA_VERSION:
                return self._error("INVALID_SCHEMA_VERSION", "schema_version 必须是 1。", action="validate_config")

        public_base_url = config.get("public_base_url", normalized["public_base_url"])
        if public_base_url is None:
            normalized_public_base_url = None
        elif not isinstance(public_base_url, str):
            return self._error("INVALID_PUBLIC_BASE_URL", "public_base_url 必须是字符串或空值。", action="validate_config")
        else:
            normalized_public_base_url = self._normalize_optional_string(public_base_url)
        if normalized_public_base_url is not None and not self._is_http_url(normalized_public_base_url):
            return self._error("INVALID_PUBLIC_BASE_URL", "public_base_url 必须以 http:// 或 https:// 开头。", action="validate_config")
        normalized["public_base_url"] = normalized_public_base_url

        for key, default_value in (
            ("web_host", DEFAULT_WEB_HOST),
            ("mcp_host", DEFAULT_MCP_HOST),
        ):
            if key in config:
                value = config.get(key)
                if not isinstance(value, str) or not value.strip():
                    return self._error(f"INVALID_{key.upper()}", f"{key} 必须是非空字符串。", action="validate_config")
                normalized[key] = value.strip()
            else:
                normalized[key] = default_value

        for key, default_value in (
            ("web_port", DEFAULT_WEB_PORT),
            ("mcp_port", DEFAULT_MCP_PORT),
        ):
            if key in config:
                value = config.get(key)
                if not self._is_valid_port(value):
                    return self._error(f"INVALID_{key.upper()}", f"{key} 必须是 1 到 65535 的整数。", action="validate_config")
                normalized[key] = int(value)
            else:
                normalized[key] = default_value

        auth_mode = config.get("auth_mode", normalized["auth_mode"])
        if not isinstance(auth_mode, str) or auth_mode.strip().lower() not in {"none", "token", "oauth"}:
            return self._error("INVALID_AUTH_MODE", "auth_mode 只能是 none、token 或 oauth。", action="validate_config")
        normalized["auth_mode"] = auth_mode.strip().lower()

        return {
            "ok": True,
            "action": "validate_config",
            "config": normalized,
            "blockers": [],
        }

    def load_config(self) -> dict[str, Any]:
        path = self.config_path()
        if not os.path.isfile(path):
            return {
                "ok": True,
                "action": "load_config",
                "config_exists": False,
                "path": self.config_path(),
                "config": self.default_config(),
                "warnings": [],
                "blockers": [],
            }

        payload = self._read_json_file(path)
        if not payload["ok"]:
            payload["action"] = "load_config"
            payload["config_exists"] = True
            return payload
        data = payload["data"]
        validated = self.validate_config(data)
        if not validated["ok"]:
            validated.update({
                "action": "load_config",
                "path": path,
                "config_exists": True,
            })
            return validated
        return {
            "ok": True,
            "action": "load_config",
            "config_exists": True,
            "path": path,
            "config": validated["config"],
            "warnings": [],
            "blockers": [],
        }

    def save_config(self, config: dict[str, Any]) -> dict[str, Any]:
        path = self.config_path()
        validated = self.validate_config(config)
        if not validated["ok"]:
            validated.update({
                "action": "save_config",
                "path": path,
            })
            return validated

        payload = validated["config"]
        try:
            write_json_atomic(path, payload)
        except Exception as exc:
            return self._error("CONFIG_WRITE_FAILED", f"写入 config.json 失败：{exc}", action="save_config", path=path)

        return {
            "ok": True,
            "action": "save_config",
            "path": path,
            "config_exists": True,
            "config": payload,
            "warnings": [],
            "blockers": [],
        }

    def load_auth(self, include_secret: bool = False) -> dict[str, Any]:
        path = self.auth_path()
        if not os.path.isfile(path):
            return {
                "ok": True,
                "action": "load_auth",
                "auth_exists": False,
                "auth_token_configured": False,
                "path": self.auth_path(),
                "auth": self._public_auth_payload(False, None if include_secret else None),
                "warnings": [],
                "blockers": [],
            }

        payload = self._read_json_file(path)
        if not payload["ok"]:
            payload["action"] = "load_auth"
            payload["auth_exists"] = True
            return payload
        data = payload["data"]
        validated = self._validate_auth_payload(data)
        if not validated["ok"]:
            validated.update({
                "action": "load_auth",
                "path": path,
                "auth_exists": True,
            })
            return validated

        auth_token = validated["auth_token"] if include_secret else None
        auth_payload = self._public_auth_payload(True, auth_token if include_secret else None)
        if include_secret:
            auth_payload["auth_token"] = auth_token
        return {
            "ok": True,
            "action": "load_auth",
            "auth_exists": True,
            "auth_token_configured": True,
            "path": path,
            "auth": auth_payload,
            "warnings": [],
            "blockers": [],
        }

    def save_auth_token(self, token: str) -> dict[str, Any]:
        path = self.auth_path()
        normalized_token = self._normalize_required_string(token)
        if normalized_token is None:
            return self._error("INVALID_AUTH_TOKEN", "auth_token 必须是非空字符串。", action="save_auth_token", path=path)

        payload = {
            "schema_version": DEFAULT_SCHEMA_VERSION,
            "auth_token": normalized_token,
        }
        try:
            write_json_atomic(path, payload)
            self._chmod_600(path)
        except Exception as exc:
            return self._error("AUTH_WRITE_FAILED", f"写入 auth.json 失败：{exc}", action="save_auth_token", path=path)

        return {
            "ok": True,
            "action": "save_auth_token",
            "path": path,
            "auth_exists": True,
            "auth_token_configured": True,
            "warnings": [],
            "blockers": [],
        }

    def generate_auth_token(self) -> str:
        return f"mvr_{secrets.token_urlsafe(32)}"

    def needs_interactive_setup(
        self,
        config: dict[str, Any] | None = None,
        auth: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        raw_config = config if isinstance(config, dict) else None
        if config is None:
            config_result = self.load_config()
            if not config_result.get("ok"):
                return config_result
            config = config_result.get("config") if isinstance(config_result.get("config"), dict) else {}
            raw_config = {}
            if config_result.get("config_exists"):
                config_path = str(config_result.get("path") or self.config_path())
                raw_payload = self._read_json_file(config_path)
                if raw_payload.get("ok") and isinstance(raw_payload.get("data"), dict):
                    raw_config = raw_payload["data"]
        else:
            validated = self.validate_config(config)
            if not validated.get("ok"):
                return validated
            config = validated.get("config") if isinstance(validated.get("config"), dict) else {}

        if auth is None:
            auth_result = self.load_auth(include_secret=False)
            if not auth_result.get("ok"):
                return auth_result
            auth_token_configured = bool(auth_result.get("auth_token_configured"))
        else:
            auth_token_configured = bool(auth.get("auth_token_configured"))
            if not auth_token_configured:
                auth_token_configured = self._normalize_required_string(auth.get("auth_token")) is not None

        missing_fields: list[str] = []
        public_base_url = config.get("public_base_url")
        if not isinstance(public_base_url, str) or not public_base_url.strip():
            missing_fields.append("public_base_url")

        auth_mode = config.get("auth_mode")
        auth_mode_missing = raw_config is not None and (
            "auth_mode" not in raw_config
            or not isinstance(raw_config.get("auth_mode"), str)
            or not raw_config.get("auth_mode", "").strip()
        )
        if auth_mode_missing:
            missing_fields.append("auth_mode")
            normalized_auth_mode = None
        elif not isinstance(auth_mode, str) or auth_mode.strip().lower() not in {"none", "token", "oauth"}:
            missing_fields.append("auth_mode")
            normalized_auth_mode = None
        else:
            normalized_auth_mode = auth_mode.strip().lower()

        if normalized_auth_mode == "token" and not auth_token_configured:
            missing_fields.append("auth_token")

        return {
            "ok": True,
            "action": "needs_interactive_setup",
            "needs_setup": bool(missing_fields),
            "missing_fields": missing_fields,
            "auth_mode": normalized_auth_mode,
            "auth_token_configured": auth_token_configured,
            "warnings": [],
            "blockers": [],
        }

    def save_initial_setup(
        self,
        *,
        public_base_url: str,
        auth_mode: str,
        auth_token: str | None = None,
    ) -> dict[str, Any]:
        normalized_public_base_url = self._normalize_required_string(public_base_url)
        if normalized_public_base_url is None or not self._is_http_url(normalized_public_base_url):
            return self._error(
                "INVALID_PUBLIC_BASE_URL",
                "public_base_url 必须以 http:// 或 https:// 开头。",
                action="save_initial_setup",
                path=self.config_path(),
            )

        if not isinstance(auth_mode, str) or auth_mode.strip().lower() not in {"none", "token", "oauth"}:
            return self._error(
                "INVALID_AUTH_MODE",
                "auth_mode 只能是 none、token 或 oauth。",
                action="save_initial_setup",
                path=self.config_path(),
            )
        normalized_auth_mode = auth_mode.strip().lower()

        normalized_token = self._normalize_required_string(auth_token)
        if normalized_auth_mode == "token" and normalized_token is None:
            return self._error(
                "INVALID_AUTH_TOKEN",
                "auth_mode=token 时 auth_token 必须是非空字符串。",
                action="save_initial_setup",
                path=self.auth_path(),
            )

        config_payload = self.default_config()
        config_payload["public_base_url"] = normalized_public_base_url
        config_payload["auth_mode"] = normalized_auth_mode
        config_result = self.save_config(config_payload)
        if not config_result.get("ok"):
            config_result["action"] = "save_initial_setup"
            return config_result

        auth_result: dict[str, Any] | None = None
        if normalized_auth_mode == "token":
            auth_result = self.save_auth_token(str(normalized_token))
            if not auth_result.get("ok"):
                auth_result["action"] = "save_initial_setup"
                return auth_result

        return {
            "ok": True,
            "action": "save_initial_setup",
            "config_dir": self.config_dir(),
            "config_path": self.config_path(),
            "auth_path": self.auth_path(),
            "auth_mode": normalized_auth_mode,
            "public_base_url": normalized_public_base_url,
            "auth_token_configured": normalized_auth_mode == "token",
            "auth_saved": bool(auth_result and auth_result.get("ok")),
            "warnings": [],
            "blockers": [],
        }

    def inspect(self) -> dict[str, Any]:
        config_result = self.load_config()
        auth_result = self.load_auth(include_secret=False)
        blockers: list[str] = []
        warnings: list[str] = []
        ok = True

        if not config_result.get("ok", False):
            ok = False
            blockers.append(config_result.get("message", "config.json 无效。"))
        else:
            warnings.extend(self._normalize_message_list(config_result.get("warnings")))

        if not auth_result.get("ok", False):
            ok = False
            blockers.append(auth_result.get("message", "auth.json 无效。"))
        else:
            warnings.extend(self._normalize_message_list(auth_result.get("warnings")))

        config_payload = config_result.get("config") if config_result.get("ok") else self.default_config()
        auth_token_configured = bool(auth_result.get("auth_token_configured", False)) if auth_result.get("ok") else False

        return {
            "ok": ok,
            "action": "inspect_global_config",
            "config_dir": self.config_dir(),
            "config_exists": bool(config_result.get("config_exists", False)),
            "auth_exists": bool(auth_result.get("auth_exists", False)),
            "auth_token_configured": auth_token_configured,
            "config": config_payload,
            "warnings": warnings,
            "blockers": blockers,
        }

    def redacted_summary(self) -> dict[str, Any]:
        config_result = self.load_config()
        auth_result = self.load_auth(include_secret=False)
        blockers: list[str] = []
        ok = True
        if not config_result.get("ok", False):
            ok = False
            blockers.append(config_result.get("message", "config.json 无效。"))
        if not auth_result.get("ok", False):
            ok = False
            blockers.append(auth_result.get("message", "auth.json 无效。"))

        config_payload = config_result.get("config") if config_result.get("ok") else self.default_config()
        auth_token_configured = bool(auth_result.get("auth_token_configured", False)) if auth_result.get("ok") else False
        return {
            "ok": ok,
            "config_dir": self.config_dir(),
            "public_base_url": config_payload.get("public_base_url"),
            "auth_mode": config_payload.get("auth_mode"),
            "auth_token": "configured" if auth_token_configured else "missing",
            "warnings": [],
            "blockers": blockers,
        }

    def _validate_auth_payload(self, data: Any) -> dict[str, Any]:
        if not isinstance(data, dict):
            return self._error("INVALID_AUTH_SCHEMA", "auth.json 根节点必须是 JSON 对象。", action="load_auth", path=self.auth_path())
        schema_version = data.get("schema_version")
        if not self._is_int(schema_version) or int(schema_version) != DEFAULT_SCHEMA_VERSION:
            return self._error("INVALID_AUTH_SCHEMA_VERSION", "auth.json schema_version 必须是 1。", action="load_auth", path=self.auth_path())
        token = data.get("auth_token")
        normalized_token = self._normalize_required_string(token)
        if normalized_token is None:
            return self._error("INVALID_AUTH_TOKEN", "auth_token 必须是非空字符串。", action="load_auth", path=self.auth_path())
        return {
            "ok": True,
            "auth_token": normalized_token,
        }

    def _public_auth_payload(self, configured: bool, auth_token: str | None) -> dict[str, Any]:
        payload = RunnerGlobalAuth(
            schema_version=DEFAULT_SCHEMA_VERSION,
            auth_token_configured=configured,
            auth_token=auth_token if auth_token is not None else None,
        )
        result = asdict(payload)
        if auth_token is None:
            result.pop("auth_token", None)
        return result

    def _resolve_config_dir(self, config_dir: str | None) -> str:
        if isinstance(config_dir, str) and config_dir.strip():
            return os.path.abspath(os.path.expanduser(config_dir.strip()))
        return user_config_dir()

    def _chmod_600(self, path: str) -> None:
        if os.name != "posix":
            return
        try:
            os.chmod(path, AUTH_FILE_MODE)
        except OSError:
            pass

    def _read_json_file(self, path: str) -> dict[str, Any]:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as exc:
            return self._error("CONFIG_JSON_INVALID", f"JSON 解析失败：第 {exc.lineno} 行第 {exc.colno} 列，{exc.msg}", path=path)
        except FileNotFoundError:
            return self._error("CONFIG_FILE_NOT_FOUND", "配置文件不存在。", path=path)
        except Exception as exc:
            return self._error("CONFIG_READ_ERROR", f"读取配置失败：{exc}", path=path)

        if not isinstance(data, dict):
            return self._error("CONFIG_SCHEMA_INVALID", "配置根节点必须是 JSON 对象。", path=path)
        return {"ok": True, "data": data, "path": path}

    def _normalize_optional_string(self, value: Any) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        if not normalized:
            return None
        return normalized

    def _normalize_required_string(self, value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        if not normalized:
            return None
        return normalized

    def _is_http_url(self, value: str) -> bool:
        return value.startswith("http://") or value.startswith("https://")

    def _is_valid_port(self, value: Any) -> bool:
        if isinstance(value, bool) or not isinstance(value, int):
            return False
        return 1 <= value <= 65535

    def _is_int(self, value: Any) -> bool:
        return isinstance(value, int) and not isinstance(value, bool)

    def _normalize_message_list(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        result: list[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                result.append(item.strip())
        return result

    def _error(self, error_code: str, message: str, action: str = "runner_global_config", path: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "ok": False,
            "action": action,
            "error_code": error_code,
            "message": message,
            "warnings": [],
            "blockers": [message],
        }
        if path is not None:
            payload["path"] = path
        return payload
