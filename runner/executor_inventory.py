import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runner.executor_registry import (
    SUPPORTED_EXECUTOR_PROVIDERS,
    get_executor_provider_info,
    get_executor_provider_display,
)
from runner.runner_settings import RunnerSettingsStore

INVENTORY_FILE_NAME = "executor-inventory.json"


@dataclass
class ExecutorProbeResult:
    provider: str
    display_name: str
    available: bool
    command: str
    command_path: str | None
    version: str | None
    models: list[dict[str, Any]]
    default_model: str | None
    cost_type: str
    capability_level: str | None
    probed_at: str
    error_code: str | None
    message: str | None
    model_probe_status: str = "unavailable"
    model_probe_message: str | None = None


def _probe_command(command: str, timeout_seconds: int = 5) -> tuple[bool, str | None, str | None, str | None]:
    command_path = shutil.which(command)
    if command_path is None:
        return False, None, None, "COMMAND_NOT_FOUND"
    version: str | None = None
    error_code: str | None = None
    try:
        proc = subprocess.run(
            [command, "--version"],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        raw = (proc.stdout or "").strip() or (proc.stderr or "").strip()
        if raw:
            version = raw[:500]
    except FileNotFoundError:
        return False, None, None, "COMMAND_NOT_FOUND"
    except subprocess.TimeoutExpired:
        version = None
        error_code = "VERSION_TIMEOUT"
    except Exception:
        version = None
        error_code = "VERSION_CHECK_FAILED"
    return True, command_path, version, error_code


def _probe_provider(provider: str, plan_data: dict[str, Any] | None) -> ExecutorProbeResult:
    info = get_executor_provider_info(provider)
    available, command_path, version, error_code = _probe_command(provider)
    message: str | None = None
    if not available:
        message = f"未找到 {info.display_name} 命令，请确认已安装。"
    default_model: str | None = None
    if plan_data:
        me = plan_data.get("model_execution") or {}
        provider_priority: tuple[str, ...]
        if provider == "codex":
            provider_priority = ("codex_model", "model", "model_name", "model_command")
        elif provider == "opencode":
            provider_priority = ("opencode_model", "model", "model_name", "model_command")
        else:
            provider_priority = ("pi_model", "model", "model_name", "model_command")
        for key in provider_priority:
            val = me.get(key) or plan_data.get(key)
            if isinstance(val, str) and val.strip():
                default_model = val.strip()
                break
    models, model_probe_status, model_probe_message = _probe_provider_models(provider)
    return ExecutorProbeResult(
        provider=provider,
        display_name=info.display_name,
        available=available,
        command=provider,
        command_path=command_path,
        version=version,
        models=models,
        default_model=default_model,
        cost_type="unknown",
        capability_level=None,
        probed_at=datetime.now(timezone.utc).astimezone().isoformat(),
        error_code=error_code,
        message=message,
        model_probe_status=model_probe_status,
        model_probe_message=model_probe_message,
    )


def _probe_codex_models() -> tuple[list[dict[str, Any]], str, str | None]:
    """Probe Codex CLI for available models from local config and cache."""
    config_dir = _codex_config_dir()
    models: list[dict[str, Any]] = []
    if not config_dir:
        return [], "unavailable", "未找到 Codex 配置目录。"

    # primary source: models_cache.json (contains all known models)
    cache_path = os.path.join(config_dir, "models_cache.json")
    if os.path.isfile(cache_path):
        try:
            raw = json.loads(Path(cache_path).read_text(encoding="utf-8"))
            cached = raw.get("models") if isinstance(raw, dict) else None
            if isinstance(cached, list):
                for m in cached:
                    slug = m.get("slug", "") if isinstance(m, dict) else ""
                    display = m.get("display_name", "") if isinstance(m, dict) else ""
                    if slug:
                        entry: dict[str, Any] = {
                            "name": slug,
                            "display_name": display or slug,
                            "available": True,
                            "source": "models_cache",
                        }
                        if isinstance(m, dict):
                            rl = m.get("supported_reasoning_levels")
                            if isinstance(rl, list):
                                entry["reasoning_levels"] = [
                                    r.get("effort") for r in rl if isinstance(r, dict) and r.get("effort")
                                ]
                            drl = m.get("default_reasoning_level")
                            if isinstance(drl, str) and drl:
                                entry["default_reasoning_level"] = drl
                        models.append(entry)
                if models:
                    return models, "detected", f"从 models_cache 发现 {len(models)} 个模型"
        except Exception:
            pass

    # fallback: read config.toml for the currently configured model
    config_path = os.path.join(config_dir, "config.toml")
    if os.path.isfile(config_path):
        current = _extract_toml_value(config_path, "model")
        if current:
            models.append({
                "name": current,
                "available": True,
                "source": "config_toml",
            })
            return models, "detected", f"从 config.toml 发现当前模型：{current}"

    return [], "unavailable", "未找到模型缓存或配置，请先运行 codex。"


def _probe_opencode_models() -> tuple[list[dict[str, Any]], str, str | None]:
    """Probe OpenCode CLI for available models, falling back to config file."""
    cli_models, cli_status, cli_message = _probe_opencode_models_cli()
    if cli_models:
        return cli_models, cli_status, cli_message

    config_path = _opencode_config_path()
    if not config_path or not os.path.isfile(config_path):
        return [], cli_status, cli_message or "未找到 OpenCode 配置文件。"

    models: list[dict[str, Any]] = []
    try:
        raw = json.loads(Path(config_path).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return [], "unavailable", "OpenCode 配置文件格式无效。"
        providers_config = raw.get("provider")
        if not isinstance(providers_config, dict):
            return [], "unavailable", "OpenCode 配置中未找到 provider 字段。"

        for provider_key, provider_config in providers_config.items():
            if not isinstance(provider_config, dict):
                continue
            provider_models = provider_config.get("models")
            if not isinstance(provider_models, dict):
                continue
            for model_id, model_config in provider_models.items():
                if not isinstance(model_config, dict):
                    continue
                name = model_config.get("name") or model_id
                entry: dict[str, Any] = {
                    "name": model_id,
                    "display_name": str(name),
                    "available": True,
                    "source": "opencode_config",
                    "provider": provider_key,
                }
                opts = model_config.get("options")
                if isinstance(opts, dict) and "reasoningEffort" in opts:
                    entry["default_reasoning_effort"] = opts["reasoningEffort"]
                variants = model_config.get("variants")
                if isinstance(variants, dict):
                    efforts = []
                    for vkey, vval in variants.items():
                        if isinstance(vval, dict) and "reasoningEffort" in vval:
                            efforts.append(vval["reasoningEffort"])
                    if efforts:
                        entry["reasoning_efforts"] = efforts
                models.append(entry)

        if models:
            return models, "detected", f"从 OpenCode 配置发现 {len(models)} 个模型"
        return [], "unavailable", "OpenCode 配置中未发现模型定义。"
    except json.JSONDecodeError:
        return [], "error", "OpenCode 配置文件 JSON 解析失败。"
    except Exception as e:
        return [], "error", f"读取 OpenCode 配置异常：{type(e).__name__}"


def _probe_pi_models() -> tuple[list[dict[str, Any]], str, str | None]:
    """Probe Pi CLI for available models via --help output."""
    pi_path = shutil.which("pi")
    if not pi_path:
        return [], "unavailable", "未找到 pi 命令。"

    try:
        proc = subprocess.run(
            [pi_path, "--help"],
            capture_output=True, text=True, timeout=5,
        )
        help_text = (proc.stdout or "") + "\n" + (proc.stderr or "")
        # Parse --model <pattern> line for hint of model discovery
        # Pi allows "provider/id" format; extract any known providers
        providers: set[str] = set()
        for line in help_text.splitlines():
            m = re.search(r"--provider\s+<name>\s+Provider name\s+\(default:\s+(\S+)\)", line, re.IGNORECASE)
            if m:
                providers.add(m.group(1))
        models: list[dict[str, Any]] = []
        if providers:
            models.append({
                "name": f"{list(providers)[0]}/*",
                "display_name": f"{list(providers)[0]} (使用 --model 指定)",
                "available": True,
                "source": "cli_help",
                "note": "指定 provider_id/model_id 格式，如 --model provider/model",
            })
            return models, "detected", f"从 pi --help 发现默认 provider: {list(providers)[0]}"

        # Even without provider extraction, we know pi supports --model
        models.append({
            "name": "<provider/model>",
            "display_name": "任意 AI provider/model",
            "available": True,
            "source": "cli_help",
            "note": "使用 pi --model <provider>/<model> 格式",
        })
        return models, "detected", "pi 支持 --model 参数；模型列表需登录后使用 pi 直接操作。"
    except subprocess.TimeoutExpired:
        return [], "unavailable", "pi --help 执行超时。"
    except Exception as e:
        return [], "error", f"探测 Pi 模型失败：{type(e).__name__}"


def _probe_opencode_models_cli() -> tuple[list[dict[str, Any]], str, str | None]:
    opencode_path = shutil.which("opencode")
    if not opencode_path:
        return [], "unavailable", "未找到 opencode 命令。"
    try:
        proc = subprocess.run(
            [opencode_path, "models"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        return [], "unavailable", "opencode models 执行超时。"
    except Exception as e:
        return [], "error", f"opencode models 执行异常：{type(e).__name__}"

    output = "\n".join(part for part in (proc.stdout, proc.stderr) if isinstance(part, str) and part)
    models: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_line in output.splitlines():
        name = raw_line.strip()
        if not name or name.startswith("#") or " " in name or "/" not in name:
            continue
        if name in seen:
            continue
        seen.add(name)
        provider_name, model_name = name.split("/", 1)
        models.append({
            "name": name,
            "display_name": name,
            "available": True,
            "source": "opencode_models_cli",
            "provider": provider_name,
            "model": model_name,
        })
    if models:
        return models, "detected", f"从 opencode models 发现 {len(models)} 个模型"
    if proc.returncode != 0:
        return [], "error", "opencode models 未返回可解析模型。"
    return [], "unavailable", "opencode models 未发现模型。"


def _probe_provider_models(provider: str) -> tuple[list[dict[str, Any]], str, str | None]:
    """Dispatch model probing to the right provider-specific function."""
    if provider == "codex":
        return _probe_codex_models()
    if provider == "opencode":
        return _probe_opencode_models()
    if provider == "pi":
        return _probe_pi_models()
    return [], "unsupported", f"provider {provider} 不支持模型探测。"


def _codex_config_dir() -> str | None:
    """Return Codex config directory path, or None."""
    candidates = [
        os.path.expanduser("~/.codex"),
        os.path.join(os.environ.get("XDG_CONFIG_HOME", ""), "codex") if os.environ.get("XDG_CONFIG_HOME") else None,
    ]
    for c in candidates:
        if c and os.path.isdir(c):
            return c
    return None


def _opencode_config_path() -> str | None:
    """Return OpenCode config file path, or None."""
    candidates = [
        os.path.expanduser("~/.config/opencode/opencode.json"),
        os.path.expanduser("~/.opencode/opencode.json"),
        os.path.join(os.environ.get("XDG_CONFIG_HOME", ""), "opencode", "opencode.json") if os.environ.get("XDG_CONFIG_HOME") else None,
    ]
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    return None


def _extract_toml_value(path: str, key: str) -> str | None:
    """Minimal TOML key=value extractor. Does not parse full TOML."""
    try:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith("["):
                continue
            m = re.match(rf'^{re.escape(key)}\s*=\s*["\']?(.*?)["\']?\s*(?:#.*)?$', stripped)
            if m:
                return m.group(1).strip()
    except Exception:
        pass
    return None


def _inventory_file_path(project_root: str) -> str:
    return resolve_project_runner_path(project_root, "runtime", INVENTORY_FILE_NAME)


def probe_executor_inventory(project_root: str) -> dict[str, Any]:
    plan_file = resolve_project_runner_path(project_root, "plan.json")
    plan_data: dict[str, Any] | None = None
    if os.path.isfile(plan_file):
        try:
            plan_data = json.loads(Path(plan_file).read_text(encoding="utf-8"))
        except Exception:
            plan_data = None

    providers: list[ExecutorProbeResult] = []
    warnings: list[str] = []
    for provider_key, info in SUPPORTED_EXECUTOR_PROVIDERS.items():
        if not info.enabled:
            continue
        result = _probe_provider(provider_key, plan_data)
        providers.append(result)

    settings = RunnerSettingsStore().load_for_project(
        project_root,
        resolve_project_runner_path(project_root, "plan.json"),
    )
    current_provider = settings.execution_provider

    current_available = False
    for p in providers:
        if p.provider == current_provider:
            current_available = p.available
            break

    generated_at = datetime.now(timezone.utc).astimezone().isoformat()
    inventory = {
        "ok": True,
        "project_root": project_root,
        "inventory_file": _inventory_file_path(project_root),
        "generated_at": generated_at,
        "providers": [asdict(p) for p in providers],
        "current_provider": current_provider,
        "current_provider_available": current_available,
        "warnings": warnings,
    }

    inv_path = _inventory_file_path(project_root)
    os.makedirs(os.path.dirname(inv_path), exist_ok=True)
    try:
        with open(inv_path, "w", encoding="utf-8") as f:
            json.dump(inventory, f, ensure_ascii=False, indent=2)
            f.write("\n")
    except OSError as e:
        return {
            "ok": False,
            "error_code": "INVENTORY_WRITE_FAILED",
            "message": f"写入 inventory 文件失败：{e}",
        }

    return inventory


def load_executor_inventory(project_root: str) -> dict[str, Any]:
    inv_path = _inventory_file_path(project_root)
    if not os.path.isfile(inv_path):
        return {
            "ok": False,
            "error_code": "INVENTORY_NOT_FOUND",
            "message": "尚未探测执行器，请先运行 probe-models。",
        }
    try:
        data = json.loads(Path(inv_path).read_text(encoding="utf-8"))
        return data
    except Exception as e:
        return {
            "ok": False,
            "error_code": "INVENTORY_READ_FAILED",
            "message": f"读取 inventory 文件失败：{e}",
        }


def get_executor_inventory_summary(project_root: str, current_provider: str) -> dict[str, Any]:
    inventory = load_executor_inventory(project_root)
    if not inventory.get("ok"):
        return {
            "inventory_available": False,
            "current_provider": current_provider,
            "current_provider_available": False,
            "probed_at": None,
            "message": "尚未探测执行器",
        }
    providers = inventory.get("providers", [])
    cur_available = False
    for p in providers:
        if isinstance(p, dict) and p.get("provider") == current_provider:
            cur_available = bool(p.get("available", False))
            break
    return {
        "inventory_available": True,
        "current_provider": current_provider,
        "current_provider_available": cur_available,
        "probed_at": inventory.get("generated_at"),
        "message": None,
    }
from runner.runner_paths import resolve_project_runner_path
