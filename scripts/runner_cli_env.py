from __future__ import annotations

import getpass
import hashlib
import os
import re
import sys
from typing import Callable, Mapping, TextIO

from runner.runner_paths import resolve_project_runner_path


def resolve_path(path: str) -> str:
    return os.path.abspath(os.path.expanduser(path))


def project_config_key(project_path: str, *, resolve_path_func: Callable[[str], str]) -> str:
    normalized = resolve_path_func(project_path)
    basename = os.path.basename(normalized.rstrip(os.sep)) or "project"
    safe_basename = re.sub(r"[^A-Za-z0-9_.-]+", "-", basename).strip(".-") or "project"
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]
    return f"{safe_basename}-{digest}"


def project_config_dir(
    project_path: str,
    *,
    store_factory: Callable[[], object],
    resolve_path_func: Callable[[str], str],
) -> str:
    base_store = store_factory()
    return os.path.join(base_store.config_dir(), "projects", project_config_key(project_path, resolve_path_func=resolve_path_func))


def config_store_for_project(project_path: str | None = None, *, store_factory: Callable[[], object]):
    del project_path
    return store_factory()


def load_global_runner_config(
    command_name: str,
    *,
    include_auth_token: bool = True,
    project_path: str | None = None,
    config_store_for_project_func: Callable[[str | None], object],
    store_factory: Callable[[], object],
) -> dict[str, object]:
    store = config_store_for_project_func(project_path)
    config_result = store.load_config()
    if not config_result.get("ok"):
        message = str(config_result.get("message", "全局 Runner config.json 无效。"))
        raise ValueError(f"{command_name} 参数错误：全局 Runner config.json 无效：{message}")

    result: dict[str, object] = {
        "config_exists": bool(config_result.get("config_exists", False)),
        "web_host": None,
        "web_port": None,
        "mcp_host": None,
        "mcp_port": None,
        "auth_mode": None,
        "public_base_url": None,
        "auth_token": None,
        "oauth_token_ttl_seconds": None,
    }
    if result["config_exists"]:
        config = config_result.get("config", {})
        if not isinstance(config, dict):
            raise ValueError(f"{command_name} 参数错误：全局 Runner config.json 无效：配置必须是 JSON 对象。")
        result["web_host"] = config.get("web_host")
        result["web_port"] = config.get("web_port")
        result["mcp_host"] = config.get("mcp_host")
        result["mcp_port"] = config.get("mcp_port")
        result["auth_mode"] = config.get("auth_mode")
        result["public_base_url"] = config.get("public_base_url")
        result["oauth_token_ttl_seconds"] = config.get("oauth_token_ttl_seconds")

    if include_auth_token:
        auth_result = store.load_auth(include_secret=True)
        if not auth_result.get("ok"):
            message = str(auth_result.get("message", "全局 Runner auth.json 无效。"))
            raise ValueError(f"{command_name} 参数错误：全局 Runner auth.json 无效：{message}")
        if auth_result.get("auth_token_configured"):
            auth_payload = auth_result.get("auth", {})
            if isinstance(auth_payload, dict):
                auth_token = auth_payload.get("auth_token")
                if isinstance(auth_token, str) and auth_token.strip():
                    result["auth_token"] = auth_token

    return result


def load_global_runner_config_env(
    command_name: str,
    *,
    project_path: str | None = None,
    load_global_runner_config_func: Callable[..., dict[str, object]],
) -> dict[str, str]:
    global_config = load_global_runner_config_func(
        command_name,
        include_auth_token=True,
        project_path=project_path,
    )
    env: dict[str, str] = {}
    auth_mode = global_config.get("auth_mode")
    if isinstance(auth_mode, str) and auth_mode.strip():
        env["MVP_RUNNER_AUTH_MODE"] = auth_mode.strip()
    public_base_url = global_config.get("public_base_url")
    if isinstance(public_base_url, str) and public_base_url.strip():
        env["MVP_RUNNER_PUBLIC_BASE_URL"] = public_base_url.strip()
    auth_token = global_config.get("auth_token")
    if isinstance(auth_token, str) and auth_token.strip():
        env["MVP_RUNNER_AUTH_TOKEN"] = auth_token.strip()
    return env


def resolve_auth_mode(auth_mode: str | None, auth_token: str | None) -> str:
    return auth_mode or ("token" if auth_token else "none")


def extract_setup_relevant_options(args: list[str]) -> tuple[dict[str, object], set[str]]:
    values: dict[str, object] = {
        "auth_mode": None,
        "auth_token": None,
        "public_base_url": None,
        "oauth_token_ttl_seconds": 3600,
        "debug_actions": False,
    }
    explicit_fields: set[str] = set()
    idx = 2
    while idx < len(args):
        token = args[idx]
        if token in {"--auth-mode", "--auth-token", "--public-base-url", "--oauth-token-ttl-seconds"}:
            idx += 1
            if idx >= len(args):
                break
            if token == "--auth-mode":
                values["auth_mode"] = args[idx]
                explicit_fields.add("auth_mode")
            elif token == "--auth-token":
                values["auth_token"] = args[idx]
                explicit_fields.add("auth_token")
            elif token == "--public-base-url":
                values["public_base_url"] = args[idx]
                explicit_fields.add("public_base_url")
            elif token == "--oauth-token-ttl-seconds":
                try:
                    values["oauth_token_ttl_seconds"] = int(args[idx])
                except ValueError:
                    values["oauth_token_ttl_seconds"] = args[idx]
                explicit_fields.add("oauth_token_ttl_seconds")
        elif token == "--debug-actions":
            values["debug_actions"] = True
            explicit_fields.add("debug_actions")
        elif token in {"--host", "--port", "--web-host", "--web-port", "--mcp-host", "--mcp-port"}:
            idx += 1
        idx += 1
    return values, explicit_fields


def resolved_setup_config(
    command_name: str,
    args: list[str],
    *,
    project_path: str | None = None,
    extract_setup_relevant_options_func: Callable[[list[str]], tuple[dict[str, object], set[str]]],
    load_global_runner_config_func: Callable[..., dict[str, object]],
) -> dict[str, object]:
    values, explicit_fields = extract_setup_relevant_options_func(args)
    try:
        global_config = load_global_runner_config_func(
            command_name,
            include_auth_token=True,
            project_path=project_path,
        )
    except ValueError:
        if not explicit_fields.intersection({"auth_mode", "auth_token", "public_base_url"}):
            raise
        global_config = {"auth_mode": None, "auth_token": None, "public_base_url": None, "oauth_token_ttl_seconds": None}

    options = {
        "auth_mode": values["auth_mode"] if values["auth_mode"] is not None else global_config.get("auth_mode"),
        "auth_token": values["auth_token"] if values["auth_token"] is not None else global_config.get("auth_token"),
        "public_base_url": values["public_base_url"]
        if values["public_base_url"] is not None
        else global_config.get("public_base_url"),
        "oauth_token_ttl_seconds": values["oauth_token_ttl_seconds"]
        if "oauth_token_ttl_seconds" in explicit_fields
        else (global_config.get("oauth_token_ttl_seconds") or values["oauth_token_ttl_seconds"]),
        "debug_actions": values["debug_actions"],
    }

    auth_mode = options.get("auth_mode")
    auth_token = options.get("auth_token")
    public_base_url = options.get("public_base_url")
    normalized_auth_mode = auth_mode.strip().lower() if isinstance(auth_mode, str) and auth_mode.strip() else None
    normalized_auth_token = auth_token.strip() if isinstance(auth_token, str) and auth_token.strip() else None
    normalized_public_base_url = (
        public_base_url.strip() if isinstance(public_base_url, str) and public_base_url.strip() else None
    )
    if normalized_auth_mode is None and normalized_auth_token:
        normalized_auth_mode = "token"

    return {
        "auth_mode": normalized_auth_mode,
        "auth_token": normalized_auth_token,
        "public_base_url": normalized_public_base_url,
        "oauth_token_ttl_seconds": options.get("oauth_token_ttl_seconds"),
        "debug_actions": options.get("debug_actions", False),
    }


def prompt_initial_global_config(
    store,
    *,
    input_func=input,
    getpass_func=getpass.getpass,
    stderr: TextIO | None = None,
) -> dict[str, object]:
    target = stderr or sys.stderr
    print("首次启动需要配置 Runner 全局参数。", file=target)
    print("", file=target)
    print("ColaMeta 支持两种认证模式：", file=target)
    print("  token  — 用于 GPTs Actions 的 Bearer token 认证", file=target)
    print("  oauth  — 用于 MCP 的 OAuth 认证", file=target)
    print("  none   — 不启用认证（仅适合本地可信网络）", file=target)
    print("", file=target)

    public_base_url = input_func("public_base_url (http:// 或 https://): ").strip()
    if not public_base_url:
        return {
            "ok": False,
            "error_code": "PUBLIC_BASE_URL_REQUIRED",
            "message": "public_base_url 不能为空。",
        }

    auth_mode_raw = input_func("auth_mode [token/oauth/none]，默认 token: ").strip().lower()
    auth_mode = auth_mode_raw or "token"
    auth_token: str | None = None
    generated = False
    if auth_mode == "token":
        auth_token_input = getpass_func("Bearer token（留空自动生成）: ").strip()
        if auth_token_input:
            auth_token = auth_token_input
        else:
            auth_token = store.generate_auth_token()
            generated = True
    elif auth_mode == "none":
        print("警告：未启用认证，仅适合本地可信网络。", file=target)

    result = store.save_initial_setup(
        public_base_url=public_base_url,
        auth_mode=auth_mode,
        auth_token=auth_token,
    )
    if not result.get("ok"):
        return result

    print(f"Runner 全局配置已保存到 {store.config_dir()}", file=target)
    if generated and auth_token:
        print("", file=target)
        print("已生成 Bearer token，用于 GPTs Actions 认证；该值只显示一次。", file=target)
        print(f"Bearer token: {auth_token}", file=target)
    if auth_mode == "oauth":
        print("", file=target)
        print("MCP OAuth 认证已启用。OAuth token 将通过 MCPOAuthProvider 管理。", file=target)
    return result


def maybe_interactive_global_config_setup(
    args: list[str],
    *,
    mode: str,
    stdin,
    stderr: TextIO,
    input_func,
    getpass_func,
    resolve_path_func: Callable[[str], str],
    resolved_setup_config_func: Callable[[str, list[str], str | None], dict[str, object]],
    config_store_for_project_func: Callable[[str | None], object],
    prompt_initial_global_config_func: Callable[..., dict[str, object]],
) -> int | None:
    command_name = "mcp-http-server" if mode == "source-only" else "serve"
    project_path = resolve_path_func(args[1]) if len(args) > 1 else None
    try:
        resolved = resolved_setup_config_func(command_name, args, project_path)
    except ValueError as exc:
        print(str(exc), file=stderr)
        return 1

    store = config_store_for_project_func(project_path)
    config_for_check: dict[str, object] = {
        "schema_version": 1,
        "web_host": "127.0.0.1",
        "web_port": 8799,
        "mcp_host": "127.0.0.1",
        "mcp_port": 8765,
    }
    if resolved.get("public_base_url") is not None:
        config_for_check["public_base_url"] = resolved.get("public_base_url")
    if resolved.get("auth_mode") is not None:
        config_for_check["auth_mode"] = resolved.get("auth_mode")
    auth_for_check = {"auth_token_configured": bool(resolved.get("auth_token"))}
    setup_status = store.needs_interactive_setup(config=config_for_check, auth=auth_for_check)
    if not setup_status.get("ok"):
        print(str(setup_status.get("message") or "Runner 全局配置检查失败。"), file=stderr)
        return 1
    if not setup_status.get("needs_setup"):
        return None

    missing = ", ".join(str(item) for item in setup_status.get("missing_fields", []))
    if not stdin.isatty():
        print(f"{mode} 启动缺少必要配置：{missing}。", file=stderr)
        print("可使用 --public-base-url / --auth-mode / --auth-token，或预先写入 ~/.config/colameta/ 全局配置。", file=stderr)
        return 1

    setup_result = prompt_initial_global_config_func(
        store,
        input_func=input_func,
        getpass_func=getpass_func,
        stderr=stderr,
    )
    if not setup_result.get("ok"):
        print(str(setup_result.get("message") or "Runner 全局配置初始化失败。"), file=stderr)
        return 1
    return None


def read_runtime_public_base_url(project_path: str, *, path_module=os.path) -> str | None:
    runtime_file = resolve_project_runner_path(project_path, "runtime", "public-base-url.txt")
    if not path_module.isfile(runtime_file):
        return None
    try:
        with open(runtime_file, "r", encoding="utf-8") as handle:
            for line in handle:
                value = line.strip()
                if value:
                    return value
    except Exception:
        return None
    return None


def resolve_public_base_url(
    project_path: str,
    cli_value: str | None,
    *,
    config_store_for_project_func: Callable[[str | None], object],
    store_factory: Callable[[], object],
    read_runtime_public_base_url_func: Callable[[str], str | None],
) -> tuple[str | None, str]:
    if isinstance(cli_value, str) and cli_value.strip():
        return cli_value.strip(), "CLI argument"
    try:
        store = config_store_for_project_func(project_path)
        config_result = store.load_config()
        config_source = "project config"
        if not config_result.get("ok"):
            message = str(config_result.get("message", "Runner config.json 无效。"))
            raise ValueError(f"默认入口参数错误：Runner config.json 无效：{message}")
        config = config_result.get("config", {})
        if isinstance(config, dict):
            global_value = config.get("public_base_url")
            if isinstance(global_value, str) and global_value.strip():
                return global_value.strip(), config_source
        elif config is not None:
            raise ValueError("默认入口参数错误：项目 Runner config.json 无效：配置必须是 JSON 对象。")
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"默认入口参数错误：读取项目 Runner 配置失败：{exc}") from exc
    runtime_value = read_runtime_public_base_url_func(project_path)
    if runtime_value:
        return runtime_value, "runtime file"
    return None, "missing"


def normalize_public_base_url(url: str) -> str:
    return url.strip().rstrip("/")


def is_local_http_url(url: str) -> bool:
    return url.startswith("http://127.0.0.1") or url.startswith("http://localhost")


def resolve_debug_actions(cli_has_flag: bool) -> bool:
    return cli_has_flag
