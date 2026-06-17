import json
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from runner.executor_inventory import load_executor_inventory, probe_executor_inventory, _inventory_file_path
from runner.executor_registry import SUPPORTED_EXECUTOR_PROVIDERS, is_supported_execution_provider
from runner.runner_settings import RunnerSettingsStore, ExecutorProfile, _now_iso, _sanitize_optional_str, _strip_sensitive_keys
from runner.runner_paths import resolve_project_runner_dir, resolve_project_runner_path


VALID_PROVIDERS = {"codex", "opencode", "pi"}
PREVIEWS_DIR = os.path.join("runtime", "executor-config-previews")
PREVIEW_TTL_SECONDS = 3600

# Legacy constant kept for backward compatibility (used by tests)
SENSITIVE_PATTERNS = ["token", "api_key", "bearer", "authorization", "secret"]


def _is_sensitive_key(key: str) -> bool:
    """Check if a dict key is likely to contain sensitive values."""
    if not isinstance(key, str):
        return False
    lower = key.lower()
    # Match literal substrings and camelCase variants like apiKey, bearerToken
    if "api_key" in lower or "apikey" in lower or "api-key" in lower:
        return True
    if "bearer" in lower or "token" in lower:
        return True
    if "authorization" in lower or "auth_token" in lower or "authtoken" in lower:
        return True
    if "secret" in lower:
        return True
    return False

SENSITIVE_TEXT_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"Bearer\s+\S+", re.IGNORECASE), "Bearer ***"),
    (re.compile(r"api_key=\S+", re.IGNORECASE), "api_key=[REDACTED]"),
    (re.compile(r"token=\S+", re.IGNORECASE), "token=[REDACTED]"),
    (re.compile(r"secret=\S+", re.IGNORECASE), "secret=[REDACTED]"),
    (re.compile(r"sk-\S+"), "[REDACTED]"),
    (re.compile(r"https://\S+@"), "https://***@"),
]


def _validate_preview_id(value: str) -> bool:
    if not isinstance(value, str):
        return False
    stripped = value.strip()
    length = len(stripped)
    if length < 8 or length > 64:
        return False
    return bool(re.fullmatch(r"[A-Za-z0-9_-]+", stripped))


def _redact_sensitive_text(text: str) -> str:
    if not isinstance(text, str):
        return str(text) if text is not None else ""
    result = text
    for pattern, replacement in SENSITIVE_TEXT_PATTERNS:
        result = pattern.sub(replacement, result)
    return result


def _redact_sensitive_values(data: Any) -> Any:
    if isinstance(data, dict):
        redacted = {}
        for k, v in data.items():
            if _is_sensitive_key(k):
                redacted[k] = "[REDACTED]"
            else:
                redacted[k] = _redact_sensitive_values(v)
        return redacted
    if isinstance(data, list):
        return [_redact_sensitive_values(item) for item in data]
    if isinstance(data, str):
        lower = data.lower()
        for pattern in SENSITIVE_PATTERNS:
            if pattern in lower:
                return "[REDACTED]"
        return data
    return data


class MCPExecutorConfigManager:
    def __init__(self, project_root: str):
        self.project_root = os.path.abspath(os.path.expanduser(project_root))
        self._previews_root = resolve_project_runner_path(self.project_root, PREVIEWS_DIR)

    def handle(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        handlers = {
            "inspect_inventory": self._inspect_inventory,
            "probe_models_preview": self._probe_models_preview,
            "probe_models_apply": self._probe_models_apply,
            "set_default_profile_preview": self._set_default_profile_preview,
            "set_default_profile_apply": self._set_default_profile_apply,
        }
        handler = handlers.get(action)
        if handler is None:
            return {
                "ok": False,
                "error_code": "UNKNOWN_ACTION",
                "message": "不支持的 action。支持：inspect_inventory、probe_models_preview、probe_models_apply、set_default_profile_preview、set_default_profile_apply。",
            }
        return handler(params)

    def _validate_provider(self, provider_raw: Any) -> tuple[str | None, str | None]:
        if provider_raw is None:
            return None, None
        if not isinstance(provider_raw, str) or not provider_raw.strip():
            return None, None
        norm = provider_raw.strip().lower()
        if norm not in VALID_PROVIDERS:
            return None, "INVALID_PROVIDER"
        return norm, None

    def _safe_inventory_summary(self, inventory: dict[str, Any] | None, provider: str | None) -> dict[str, Any]:
        if inventory is None:
            return {"inventory_exists": False}
        providers_raw = inventory.get("providers", [])
        if not isinstance(providers_raw, list):
            providers_raw = []
        filtered = providers_raw
        if provider:
            filtered = [p for p in filtered if isinstance(p, dict) and p.get("provider") == provider]
        safe_redacted = _redact_sensitive_values(filtered)
        models_summary = []
        for p in safe_redacted:
            if isinstance(p, dict):
                entry: dict[str, Any] = {
                    "provider": p.get("provider"),
                    "available": p.get("available", False),
                    "default_model": p.get("default_model"),
                    "model_count": len(p.get("models") or []),
                    "model_probe_status": p.get("model_probe_status", "unavailable"),
                    "model_probe_message": p.get("model_probe_message"),
                }
                raw_models = p.get("models") or []
                if isinstance(raw_models, list) and raw_models:
                    # Expose model name + display_name safely; redact paths
                    entry["models"] = [
                        {
                            "name": m.get("name") if isinstance(m, dict) else str(m),
                            "display_name": m.get("display_name") if isinstance(m, dict) else None,
                            "available": bool(m.get("available", True)) if isinstance(m, dict) else True,
                            "source": m.get("source") if isinstance(m, dict) else None,
                        }
                        for m in raw_models if isinstance(m, dict)
                    ]
                models_summary.append(entry)
        return {
            "inventory_exists": True,
            "providers": [p.get("provider") for p in filtered if isinstance(p, dict)],
            "default_provider": inventory.get("current_provider"),
            "models_summary": models_summary,
            "updated_at": inventory.get("generated_at"),
        }

    def _find_missing_providers(self, inventory: dict[str, Any] | None) -> list[str]:
        if inventory is None:
            return list(VALID_PROVIDERS)
        existing = set()
        for p in (inventory.get("providers") or []):
            if isinstance(p, dict):
                existing.add(p.get("provider"))
        return [p for p in sorted(VALID_PROVIDERS) if p not in existing]

    def _inspect_inventory(self, params: dict[str, Any]) -> dict[str, Any]:
        provider_raw = params.get("provider")
        provider, error = self._validate_provider(provider_raw)
        if error:
            return {
                "ok": False, "action": "inspect_inventory",
                "error_code": "INVALID_PROVIDER",
                "message": f"provider 必须是 codex、opencode 或 pi，收到：{provider_raw}",
            }

        inventory = load_executor_inventory(self.project_root)
        resolved_settings = RunnerSettingsStore().resolve_for_project(self.project_root)
        current_profile = self._load_current_profile()
        inventory_exists = inventory.get("ok", False)
        if not inventory_exists:
            return {
                "ok": True,
                "action": "inspect_inventory",
                "inventory_exists": False,
                "error_code": "INVENTORY_NOT_FOUND",
                "message": "尚未探测执行器，请先运行 probe-models。",
                "providers": [],
                "models_summary": [],
                "default_provider": resolved_settings.settings.execution_provider,
                "current_profile": current_profile,
                "missing_providers": self._find_missing_providers(None),
                "next_actions": [
                    {
                        "tool": "manage_executor_config", "action": "probe_models_preview",
                        "params": {"action": "probe_models_preview"},
                        "reason": "先运行 probe-models 预览",
                        "requires_confirmation": True,
                    },
                ],
            }

        inv_data = self._safe_inventory_summary(inventory, provider)
        return {
            "ok": True,
            "action": "inspect_inventory",
            "inventory_exists": True,
            "providers": inv_data["providers"],
            "default_provider": resolved_settings.settings.execution_provider,
            "current_profile": current_profile,
            "models_summary": inv_data["models_summary"],
            "missing_providers": self._find_missing_providers(inventory),
            "updated_at": inv_data.get("updated_at"),
            "next_actions": [],
        }

    def _probe_models_preview(self, params: dict[str, Any]) -> dict[str, Any]:
        provider_raw = params.get("provider")
        provider, error = self._validate_provider(provider_raw)
        if error:
            return {
                "ok": False, "action": "probe_models_preview",
                "error_code": "INVALID_PROVIDER",
                "message": f"provider 必须是 codex、opencode 或 pi，收到：{provider_raw}",
            }

        inventory = load_executor_inventory(self.project_root)
        inv_ok = inventory.get("ok", False)
        inv_data = inventory if inv_ok else None
        inv_summary = self._safe_inventory_summary(inv_data, provider)

        blockers: list[str] = []
        warnings: list[str] = []
        if not os.path.isdir(os.path.join(self.project_root, ".git")):
            blockers.append("NOT_A_GIT_REPOSITORY")
        runner_dir = resolve_project_runner_dir(self.project_root)
        if not os.path.isdir(runner_dir):
            blockers.append("NOT_RUNNER_MANAGED")

        providers_to_probe = [provider] if provider else list(VALID_PROVIDERS)

        preview_id = uuid.uuid4().hex[:12]
        now = datetime.now(timezone.utc)
        created_at = now.isoformat()
        expires_at = (now + timedelta(seconds=PREVIEW_TTL_SECONDS)).isoformat()

        inventory_hash = ""
        if inv_ok:
            inv_path = _inventory_file_path(self.project_root)
            try:
                inventory_hash = str(os.path.getmtime(inv_path))
            except Exception:
                pass

        can_apply = len(blockers) == 0

        artifact = {
            "preview_id": preview_id,
            "artifact_kind": "probe_models",
            "project_root": self.project_root,
            "provider": provider,
            "providers_to_probe": providers_to_probe,
            "inventory_hash": inventory_hash,
            "inventory_exists": inv_ok,
            "blockers": blockers,
            "warnings": warnings,
            "created_at": created_at,
            "expires_at": expires_at,
        }
        self._write_preview_artifact(preview_id, artifact)

        return {
            "ok": True,
            "action": "probe_models_preview",
            "preview_id": preview_id,
            "provider": provider,
            "providers_to_probe": providers_to_probe,
            "inventory_exists": inv_summary["inventory_exists"],
            "current_inventory_summary": inv_summary,
            "command_summary": f"probe-models (refresh all providers; filter summary to {provider})" if provider else "probe-models",
            "can_apply": can_apply,
            "blockers": blockers,
            "warnings": warnings,
            "created_at": created_at,
            "expires_at": expires_at,
            "message": (
                f"probe_models_preview 已生成。使用 preview_id={preview_id} 调用 "
                "manage_executor_config action=probe_models_apply 执行探测。"
            ) if can_apply else "当前存在阻断项，无法执行 probe-models。",
            "next_actions": [
                {
                    "tool": "manage_executor_config",
                    "action": "probe_models_apply",
                    "params": {"action": "probe_models_apply", "preview_id": preview_id},
                    "reason": "使用 preview_id 执行受控 probe-models。",
                    "requires_confirmation": True,
                },
            ] if can_apply else [],
        }

    def _probe_models_apply(self, params: dict[str, Any]) -> dict[str, Any]:
        preview_id = params.get("preview_id")
        if not isinstance(preview_id, str) or not preview_id.strip():
            return {
                "ok": False, "action": "probe_models_apply",
                "error_code": "INVALID_PREVIEW_ID",
                "message": "probe_models_apply 需要非空 preview_id。",
            }
        preview_id = preview_id.strip()
        if not _validate_preview_id(preview_id):
            return {
                "ok": False, "action": "probe_models_apply",
                "error_code": "INVALID_PREVIEW_ID",
                "message": f"preview_id 格式无效：{preview_id}，只允许字母、数字、下划线、短横线（8-64 字符）。",
            }

        provider_raw = params.get("provider")
        provider, error = self._validate_provider(provider_raw)
        if error:
            return {
                "ok": False, "action": "probe_models_apply",
                "error_code": "INVALID_PROVIDER",
                "message": f"provider 必须是 codex、opencode 或 pi，收到：{provider_raw}",
            }

        artifact = self._read_preview_artifact(preview_id)
        if artifact is None:
            return {
                "ok": False, "action": "probe_models_apply",
                "error_code": "PREVIEW_NOT_FOUND",
                "message": f"preview_id={preview_id} 不存在或已过期。请重新调用 probe_models_preview。",
            }

        if artifact.get("artifact_kind") != "probe_models":
            return {
                "ok": False, "action": "probe_models_apply",
                "error_code": "PREVIEW_KIND_MISMATCH",
                "message": "preview_id 不是 probe_models_preview 生成的 artifact。",
            }

        now_iso = datetime.now(timezone.utc).isoformat()
        if now_iso > str(artifact.get("expires_at", "")):
            self._delete_preview_artifact(preview_id)
            return {
                "ok": False, "action": "probe_models_apply",
                "error_code": "PREVIEW_EXPIRED",
                "message": "preview_id 已过期，请重新生成 probe_models_preview。",
            }

        if artifact.get("project_root") != self.project_root:
            return {
                "ok": False, "action": "probe_models_apply",
                "error_code": "PREVIEW_PROJECT_MISMATCH",
                "message": "preview 绑定的项目根路径与当前项目不一致。",
            }

        artifact_provider = artifact.get("provider")
        if artifact_provider is not None and provider is not None and artifact_provider != provider:
            return {
                "ok": False, "action": "probe_models_apply",
                "error_code": "PREVIEW_PROVIDER_MISMATCH",
                "message": "preview 与请求的 provider 不一致。",
            }

        blockers = artifact.get("blockers", [])
        if blockers:
            return {
                "ok": False, "action": "probe_models_apply",
                "error_code": "PREVIEW_BLOCKED",
                "message": "preview 存在阻断项，无法 apply。",
                "blockers": blockers,
            }

        try:
            result = probe_executor_inventory(self.project_root)
        except Exception as exc:
            safe_exc = _redact_sensitive_text(str(exc))
            return {
                "ok": False, "action": "probe_models_apply",
                "error_code": "PROBE_MODELS_FAILED",
                "message": f"probe-models 执行失败：{safe_exc}"[:500],
                "output_summary": f"[REDACTED: probe execution error: {type(exc).__name__}]",
            }

        if not result.get("ok"):
            error_code = result.get("error_code", "PROBE_MODELS_FAILED")
            raw_message = str(result.get("message", "probe-models 执行返回失败状态"))
            safe_message = _redact_sensitive_text(raw_message[:500])
            return {
                "ok": False, "action": "probe_models_apply",
                "error_code": error_code,
                "message": safe_message,
                "output_summary": f"[REDACTED: probe returned {error_code}]",
                "inventory_exists": False,
                "providers": [],
                "models_summary": [],
            }

        inventory = load_executor_inventory(self.project_root)
        inv_data = self._safe_inventory_summary(inventory if inventory.get("ok") else None, provider)

        self._delete_preview_artifact(preview_id)

        providers_to_probe = artifact.get("providers_to_probe", [provider] if provider else list(VALID_PROVIDERS))

        next_actions = []
        if provider:
            next_actions.append({
                "tool": "manage_executor_workflow",
                "action": "preflight",
                "params": {"action": "preflight", "provider": provider},
                "reason": f"inventory 已就绪，下一步执行 preflight 检查 {provider} 可用性。",
                "requires_confirmation": False,
            })
        else:
            for p in providers_to_probe:
                next_actions.append({
                    "tool": "manage_executor_workflow",
                    "action": "preflight",
                    "params": {"action": "preflight", "provider": p},
                    "reason": f"inventory 已就绪，下一步执行 preflight 检查 {p} 可用性。",
                    "requires_confirmation": False,
                })

        return {
            "ok": True,
            "action": "probe_models_apply",
            "provider": provider,
            "inventory_exists": inv_data.get("inventory_exists", False),
            "providers": inv_data.get("providers", []),
            "models_summary": inv_data.get("models_summary", []),
            "updated_at": inv_data.get("updated_at"),
            "output_summary": f"probe-models (refresh all providers; filter summary to {provider})" if provider else "probe-models completed",
            "next_actions": next_actions,
            "message": "probe-models 执行完成。",
        }

    def _write_preview_artifact(self, preview_id: str, artifact: dict[str, Any]) -> None:
        os.makedirs(self._previews_root, exist_ok=True)
        path = os.path.join(self._previews_root, f"{preview_id}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(artifact, f, ensure_ascii=False, indent=2)
            f.write("\n")

    def _read_preview_artifact(self, preview_id: str) -> dict[str, Any] | None:
        if not _validate_preview_id(preview_id):
            return None
        path = os.path.join(self._previews_root, f"{preview_id}.json")
        if not os.path.isfile(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def _delete_preview_artifact(self, preview_id: str) -> None:
        if not _validate_preview_id(preview_id):
            return
        path = os.path.join(self._previews_root, f"{preview_id}.json")
        try:
            if os.path.isfile(path):
                os.remove(path)
        except Exception:
            pass

    def _load_current_profile(self) -> dict[str, Any] | None:
        """Load current executor profile from effective project settings."""
        resolved = RunnerSettingsStore().resolve_for_project(self.project_root)
        profile = resolved.settings.executor_profile
        if profile is None:
            return None
        d: dict[str, Any] = {}
        if profile.provider is not None:
            d["provider"] = profile.provider
        if profile.model is not None:
            d["model"] = profile.model
        if profile.reasoning_effort is not None:
            d["reasoning_effort"] = profile.reasoning_effort
        d["source"] = profile.source
        d["updated_at"] = profile.updated_at
        if resolved.profile_settings_file:
            d["settings_file"] = resolved.profile_settings_file
        if resolved.profile_source:
            d["settings_scope"] = resolved.profile_source
        return d

    def _check_inventory_model_match(
        self,
        provider: str,
        model: str | None,
    ) -> tuple[str, list[str]]:
        """Check if provider/model exists in inventory. Returns (match_status, warnings)."""
        inventory = load_executor_inventory(self.project_root)
        if not inventory.get("ok"):
            return "unavailable", ["尚未探测执行器 inventory，模型匹配检查跳过。"]
        providers_raw = inventory.get("providers", [])
        if not isinstance(providers_raw, list):
            return "unavailable", ["inventory 格式无效。"]

        provider_data = None
        for p in providers_raw:
            if isinstance(p, dict) and p.get("provider") == provider:
                provider_data = p
                break

        if provider_data is None:
            return "unknown", [f"执行器 {provider} 不在 inventory 中（可能未安装或未探测）。"]

        if not model:
            return "provider_only", []

        models_list = provider_data.get("models", [])
        if not isinstance(models_list, list):
            return "provider_only", ["无法验证模型匹配（inventory 中无模型列表）。"]

        model_names = set()
        for m in models_list:
            if isinstance(m, dict):
                name = m.get("name") or m.get("slug") or m.get("id")
                if isinstance(name, str) and name:
                    model_names.add(name)

        if model in model_names:
            return "matched", []

        return "provider_only", [f"模型 '{model}' 不在 inventory 记录中（可能为自定义模型，设置仍可进行）。"]

    def _set_default_profile_preview(self, params: dict[str, Any]) -> dict[str, Any]:
        provider_raw = params.get("provider")
        provider, error = self._validate_provider(provider_raw)
        if error:
            return {
                "ok": False, "action": "set_default_profile_preview",
                "error_code": "INVALID_PROVIDER",
                "message": f"provider 必须是 codex、opencode 或 pi，收到：{provider_raw}",
            }

        model = _sanitize_optional_str(params.get("model"))
        reasoning_effort = _sanitize_optional_str(params.get("reasoning_effort"))

        warnings: list[str] = []
        blockers: list[str] = []

        runner_dir = resolve_project_runner_dir(self.project_root)
        if not os.path.isdir(runner_dir):
            blockers.append("NOT_RUNNER_MANAGED")

        inventory_match, inv_warnings = self._check_inventory_model_match(provider, model)
        warnings.extend(inv_warnings)

        current_profile = self._load_current_profile()

        proposed_profile: dict[str, Any] = {
            "provider": provider,
        }
        if model is not None:
            proposed_profile["model"] = model
        if reasoning_effort is not None:
            proposed_profile["reasoning_effort"] = reasoning_effort

        preview_id = uuid.uuid4().hex[:12]
        now = datetime.now(timezone.utc)
        created_at = now.isoformat()
        expires_at = (now + timedelta(seconds=PREVIEW_TTL_SECONDS)).isoformat()

        artifact = {
            "preview_id": preview_id,
            "artifact_kind": "set_default_profile",
            "project_root": self.project_root,
            "provider": provider,
            "model": model,
            "reasoning_effort": reasoning_effort,
            "blockers": blockers,
            "warnings": warnings,
            "created_at": created_at,
            "expires_at": expires_at,
        }
        self._write_preview_artifact(preview_id, artifact)

        can_apply = len(blockers) == 0

        return {
            "ok": True,
            "action": "set_default_profile_preview",
            "preview_id": preview_id,
            "current_profile": current_profile,
            "proposed_profile": proposed_profile,
            "inventory_match": inventory_match,
            "can_apply": can_apply,
            "blockers": blockers,
            "warnings": warnings,
            "created_at": created_at,
            "expires_at": expires_at,
            "message": (
                f"set_default_profile_preview 已生成。使用 preview_id={preview_id} 调用 "
                "manage_executor_config action=set_default_profile_apply 应用。"
            ) if can_apply else "当前存在阻断项，无法设置默认执行器配置。",
            "next_actions": [
                {
                    "tool": "manage_executor_config",
                    "action": "set_default_profile_apply",
                    "params": {"action": "set_default_profile_apply", "preview_id": preview_id},
                    "reason": "确认并写入 project-local 默认执行器配置。",
                    "requires_confirmation": True,
                },
            ] if can_apply else [],
        }

    def _set_default_profile_apply(self, params: dict[str, Any]) -> dict[str, Any]:
        preview_id = params.get("preview_id")
        if not isinstance(preview_id, str) or not preview_id.strip():
            return {
                "ok": False, "action": "set_default_profile_apply",
                "error_code": "INVALID_PREVIEW_ID",
                "message": "set_default_profile_apply 需要非空 preview_id。",
            }
        preview_id = preview_id.strip()
        if not _validate_preview_id(preview_id):
            return {
                "ok": False, "action": "set_default_profile_apply",
                "error_code": "INVALID_PREVIEW_ID",
                "message": f"preview_id 格式无效：{preview_id}，只允许字母、数字、下划线、短横线（8-64 字符）。",
            }

        artifact = self._read_preview_artifact(preview_id)
        if artifact is None:
            return {
                "ok": False, "action": "set_default_profile_apply",
                "error_code": "PREVIEW_NOT_FOUND",
                "message": f"preview_id={preview_id} 不存在或已过期。请重新调用 set_default_profile_preview。",
            }

        if artifact.get("artifact_kind") != "set_default_profile":
            return {
                "ok": False, "action": "set_default_profile_apply",
                "error_code": "PREVIEW_KIND_MISMATCH",
                "message": "preview_id 不是 set_default_profile_preview 生成的 artifact。",
            }

        now_iso = datetime.now(timezone.utc).isoformat()
        if now_iso > str(artifact.get("expires_at", "")):
            self._delete_preview_artifact(preview_id)
            return {
                "ok": False, "action": "set_default_profile_apply",
                "error_code": "PREVIEW_EXPIRED",
                "message": "preview_id 已过期，请重新生成 set_default_profile_preview。",
            }

        if artifact.get("project_root") != self.project_root:
            return {
                "ok": False, "action": "set_default_profile_apply",
                "error_code": "PREVIEW_PROJECT_MISMATCH",
                "message": "preview 绑定的项目根路径与当前项目不一致。",
            }

        blockers = artifact.get("blockers", [])
        if blockers:
            return {
                "ok": False, "action": "set_default_profile_apply",
                "error_code": "PREVIEW_BLOCKED",
                "message": "preview 存在阻断项，无法 apply。",
                "blockers": blockers,
            }

        provider = str(artifact.get("provider", ""))
        model = artifact.get("model") or None
        reasoning_effort = artifact.get("reasoning_effort") or None

        if not is_supported_execution_provider(provider):
            return {
                "ok": False, "action": "set_default_profile_apply",
                "error_code": "INVALID_PROVIDER",
                "message": f"provider '{provider}' 不是受支持的执行器。",
            }

        previous_profile = self._load_current_profile()

        profile = ExecutorProfile(
            provider=provider,
            model=model,
            reasoning_effort=reasoning_effort,
            source="manage_executor_config.set_default_profile_apply",
            updated_at=now_iso,
        )

        try:
            saved = RunnerSettingsStore().save_profile_for_project(self.project_root, profile)
        except Exception as exc:
            return {
                "ok": False, "action": "set_default_profile_apply",
                "error_code": "SETTINGS_WRITE_FAILED",
                "message": f"写入 colameta-settings.json 失败：{exc}",
            }

        self._delete_preview_artifact(preview_id)

        applied_profile: dict[str, Any] = {
            "provider": provider,
        }
        if model is not None:
            applied_profile["model"] = model
        if reasoning_effort is not None:
            applied_profile["reasoning_effort"] = reasoning_effort
        applied_profile["source"] = "manage_executor_config.set_default_profile_apply"
        applied_profile["updated_at"] = now_iso

        changed = previous_profile != applied_profile

        return {
            "ok": True,
            "action": "set_default_profile_apply",
            "applied_profile": applied_profile,
            "previous_profile": previous_profile,
            "changed": changed,
            "settings_file": saved.get("settings_file"),
            "warnings": [],
            "message": "用户级 ColaMeta 默认执行器配置已写入。",
        }
