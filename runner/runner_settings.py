import json
import os
import hashlib
from dataclasses import dataclass, field
from typing import Any

from runner._internal_utils import now_iso as _now_iso, write_json_atomic
from runner.executor_registry import (
    DEFAULT_EXECUTION_PROVIDER,
    is_supported_execution_provider,
)
from runner.runner_paths import PRIMARY_USER_CONFIG_DIRNAME, user_config_dir

_EXECUTOR_PROFILE_SOURCE = "manage_executor_config.set_default_profile_apply"
_PRIMARY_SETTINGS_FILE_NAME = "colameta-settings.json"
_LEGACY_SETTINGS_FILE_NAME = "runner-settings.json"
_SETTINGS_SCHEMA_VERSION = 1


class StaleSettingsError(RuntimeError):
    def __init__(self, *, path: str, expected_hash: str, actual_hash: str | None):
        self.path = path
        self.expected_hash = expected_hash
        self.actual_hash = actual_hash
        super().__init__(
            f"Settings file is stale: expected_hash={expected_hash}, actual_hash={actual_hash}, path={path}"
        )


@dataclass
class ExecutorProfile:
    provider: str | None = None
    model: str | None = None
    reasoning_effort: str | None = None
    source: str = _EXECUTOR_PROFILE_SOURCE
    updated_at: str | None = None

@dataclass
class RunnerSettings:
    execution_provider: str = DEFAULT_EXECUTION_PROVIDER
    executor_profile: ExecutorProfile | None = None


@dataclass
class ResolvedProjectSettings:
    settings: RunnerSettings
    provider_source: str = "default"
    profile_source: str | None = None
    provider_settings_file: str | None = None
    profile_settings_file: str | None = None


def _sanitize_optional_str(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned if cleaned else None


def _is_sensitive_key(key: str) -> bool:
    """Check if a dict key is likely to contain sensitive values."""
    if not isinstance(key, str):
        return False
    lower = key.lower()
    if "api_key" in lower or "apikey" in lower or "api-key" in lower:
        return True
    if "bearer" in lower or "token" in lower:
        return True
    if "authorization" in lower or "auth_token" in lower or "authtoken" in lower:
        return True
    if "secret" in lower:
        return True
    return False


def _strip_sensitive_keys(data: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of dict with sensitive keys removed."""
    return {k: v for k, v in data.items() if not _is_sensitive_key(k)}


def normalize_project_root(project_root: str) -> str:
    return os.path.realpath(os.path.abspath(os.path.expanduser(project_root)))


def project_profile_key(project_root: str) -> str:
    normalized_root = normalize_project_root(project_root)
    digest = hashlib.sha256(normalized_root.encode("utf-8")).hexdigest()
    return digest[:16]


_normalize_project_root = normalize_project_root
_project_profile_key = project_profile_key


class RunnerSettingsStore:
    def __init__(self):
        self.last_warning: str | None = None

    def default(self) -> RunnerSettings:
        return RunnerSettings(
            execution_provider=DEFAULT_EXECUTION_PROVIDER,
            executor_profile=None,
        )

    def load(self, path: str, plan_file_path: str | None = None) -> RunnerSettings:
        self.last_warning = None
        if not os.path.exists(path):
            plan_provider = self._load_provider_from_plan(plan_file_path)
            if plan_provider:
                return RunnerSettings(execution_provider=plan_provider)
            return self.default()

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            provider = data.get("execution_provider")
            if not is_supported_execution_provider(provider):
                provider = DEFAULT_EXECUTION_PROVIDER
            else:
                provider = provider.strip().lower()
            profile_raw = data.get("executor_profile")
            profile = self._parse_profile(profile_raw) if isinstance(profile_raw, dict) else None
            return RunnerSettings(
                execution_provider=provider,
                executor_profile=profile,
            )
        except Exception:
            pass

        self.last_warning = "执行器设置无效，已使用默认执行器 codex。"
        return self.default()

    def load_profile(self, path: str) -> ExecutorProfile | None:
        """Load only the executor_profile from settings, returning None if missing."""
        if not os.path.isfile(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            profile_raw = data.get("executor_profile")
            if isinstance(profile_raw, dict):
                return self._parse_profile(profile_raw)
        except Exception:
            pass
        return None

    def load_for_project(self, project_root: str, plan_file_path: str | None = None) -> RunnerSettings:
        return self.resolve_for_project(project_root, plan_file_path).settings

    def load_profile_for_project(self, project_root: str) -> ExecutorProfile | None:
        return self.resolve_for_project(project_root).settings.executor_profile

    def resolve_for_project(
        self,
        project_root: str,
        plan_file_path: str | None = None,
    ) -> ResolvedProjectSettings:
        normalized_root = normalize_project_root(project_root)
        if plan_file_path is None:
            plan_file_path = resolve_project_runner_plan_path(normalized_root)

        resolved = ResolvedProjectSettings(settings=self.default())
        plan_provider = self._load_provider_from_plan(plan_file_path)
        if plan_provider:
            resolved.settings.execution_provider = plan_provider
            resolved.provider_source = "plan"

        runner_dir = resolve_project_runner_dir(normalized_root)
        candidate_path = os.path.join(runner_dir, _LEGACY_SETTINGS_FILE_NAME)
        payload = self._read_json_dict(candidate_path)
        if isinstance(payload, dict):
            self._apply_settings_payload(
                resolved=resolved,
                payload=payload,
                source_name="project_settings",
                settings_file=candidate_path,
            )

        user_settings_path = self.user_settings_path()
        user_payload = self._read_json_dict(user_settings_path)
        if isinstance(user_payload, dict):
            self._apply_settings_payload(
                resolved=resolved,
                payload=user_payload,
                source_name="user_settings_global",
                settings_file=user_settings_path,
            )
            project_payload = self._extract_user_project_payload(user_payload, normalized_root)
            if isinstance(project_payload, dict):
                self._apply_settings_payload(
                    resolved=resolved,
                    payload=project_payload,
                    source_name="user_settings_project",
                    settings_file=user_settings_path,
                )

        return resolved

    def user_settings_path(self, config_dir: str | None = None) -> str:
        if isinstance(config_dir, str) and config_dir.strip():
            root = os.path.abspath(os.path.expanduser(config_dir.strip()))
        else:
            root = user_config_dir()
        return os.path.join(root, _PRIMARY_SETTINGS_FILE_NAME)

    def settings_file_hash(self, path: str) -> str | None:
        if not os.path.isfile(path):
            return None
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _check_expected_hash(self, path: str, expected_hash: str | None) -> None:
        if expected_hash is None:
            return
        actual_hash = self.settings_file_hash(path)
        if actual_hash != expected_hash:
            raise StaleSettingsError(path=path, expected_hash=expected_hash, actual_hash=actual_hash)

    def save_profile(self, path: str, profile: ExecutorProfile, *, expected_hash: str | None = None) -> dict[str, Any]:
        """Save executor profile into runner-settings.json, preserving existing fields."""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self._check_expected_hash(path, expected_hash)
        existing: dict[str, Any] = {}
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
                existing = _strip_sensitive_keys(existing)
            except Exception:
                existing = {}
        existing = _strip_sensitive_keys(existing)

        profile_dict: dict[str, Any] = {}
        if profile.provider is not None:
            profile_dict["provider"] = profile.provider
        if profile.model is not None:
            profile_dict["model"] = profile.model
        if profile.reasoning_effort is not None:
            profile_dict["reasoning_effort"] = profile.reasoning_effort
        profile_dict["source"] = profile.source or _EXECUTOR_PROFILE_SOURCE
        profile_dict["updated_at"] = profile.updated_at or _now_iso()

        # Ensure execution_provider consistency with profile provider
        existing["execution_provider"] = profile.provider or existing.get("execution_provider", DEFAULT_EXECUTION_PROVIDER)
        existing["executor_profile"] = profile_dict

        write_json_atomic(path, existing)

        return {
            "execution_provider": existing["execution_provider"],
            "executor_profile": profile_dict,
        }

    def save_profile_for_project(
        self,
        project_root: str,
        profile: ExecutorProfile,
        *,
        expected_hash: str | None = None,
    ) -> dict[str, Any]:
        settings = RunnerSettings(
            execution_provider=profile.provider or DEFAULT_EXECUTION_PROVIDER,
            executor_profile=profile,
        )
        return self.save_settings_for_project(project_root, settings, expected_hash=expected_hash)

    def _parse_profile(self, data: dict[str, Any]) -> ExecutorProfile:
        return ExecutorProfile(
            provider=_sanitize_optional_str(data.get("provider")),
            model=_sanitize_optional_str(data.get("model")),
            reasoning_effort=_sanitize_optional_str(data.get("reasoning_effort")),
            source=_sanitize_optional_str(data.get("source")) or _EXECUTOR_PROFILE_SOURCE,
            updated_at=_sanitize_optional_str(data.get("updated_at")),
        )

    def save(self, path: str, settings: RunnerSettings, *, expected_hash: str | None = None) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        payload = {
            "execution_provider": settings.execution_provider,
        }
        if settings.executor_profile is not None:
            profile_dict: dict[str, Any] = {}
            ep = settings.executor_profile
            if ep.provider is not None:
                profile_dict["provider"] = ep.provider
            if ep.model is not None:
                profile_dict["model"] = ep.model
            if ep.reasoning_effort is not None:
                profile_dict["reasoning_effort"] = ep.reasoning_effort
            profile_dict["source"] = ep.source or _EXECUTOR_PROFILE_SOURCE
            profile_dict["updated_at"] = ep.updated_at or _now_iso()
            payload["executor_profile"] = profile_dict
        self._check_expected_hash(path, expected_hash)
        write_json_atomic(path, payload)

    def save_settings_for_project(self, project_root: str, settings: RunnerSettings, *, expected_hash: str | None = None) -> dict[str, Any]:
        settings_path = self.user_settings_path()
        self._check_expected_hash(settings_path, expected_hash)
        payload = self._read_json_dict(settings_path)
        if not isinstance(payload, dict):
            payload = {}
        payload = _strip_sensitive_keys(payload)
        payload["schema_version"] = _SETTINGS_SCHEMA_VERSION

        project_profiles = payload.get("project_profiles")
        if not isinstance(project_profiles, dict):
            project_profiles = {}

        project_key = project_profile_key(project_root)
        normalized_root = normalize_project_root(project_root)
        entry = project_profiles.get(project_key)
        if not isinstance(entry, dict):
            entry = {}
        entry = _strip_sensitive_keys(entry)
        entry["project_root"] = normalized_root
        entry["execution_provider"] = settings.execution_provider or DEFAULT_EXECUTION_PROVIDER

        if settings.executor_profile is not None:
            entry["executor_profile"] = self._profile_to_dict(settings.executor_profile)
        else:
            entry.pop("executor_profile", None)

        project_profiles[project_key] = entry
        payload["project_profiles"] = project_profiles

        write_json_atomic(settings_path, payload)

        return {
            "settings_file": settings_path,
            "project_key": project_key,
            "execution_provider": entry["execution_provider"],
            "executor_profile": entry.get("executor_profile"),
        }

    def migrate_project_profile(
        self,
        settings_path: str,
        old_roots: list[str],
        new_root: str,
        *,
        expected_hash: str | None = None,
    ) -> dict[str, Any]:
        self._check_expected_hash(settings_path, expected_hash)
        payload = self._read_json_dict(settings_path)
        if not isinstance(payload, dict):
            return {"ok": False, "error_code": "SETTINGS_NOT_FOUND", "message": "colameta-settings.json 无法读取或不存在。"}

        profiles = payload.get("project_profiles")
        if not isinstance(profiles, dict):
            return {"ok": True, "updated": False, "reason": "no_project_profiles"}
        old_keys = [project_profile_key(root) for root in old_roots]
        new_key = project_profile_key(new_root)

        key_change = None
        for old_key in old_keys:
            if old_key in profiles and old_key != new_key:
                key_change = {"from": old_key, "to": new_key}
                break
        if key_change is None:
            return {"ok": True, "updated": False, "reason": "no_migration_needed"}

        if new_key in profiles and new_key != key_change["from"]:
            return {"ok": False, "error_code": "PROFILE_KEY_CONFLICT", "message": "用户设置中已存在 new_project_root 的项目 profile。"}

        old_key = key_change["from"]
        profile = profiles.pop(old_key, None)
        if isinstance(profile, dict):
            profile["project_root"] = normalize_project_root(new_root)
            profiles[new_key] = profile

        payload["project_profiles"] = profiles
        write_json_atomic(settings_path, payload)
        return {"ok": True, "updated": True, "profile_key_change": key_change, "project_root": new_root}

    def _profile_to_dict(self, profile: ExecutorProfile) -> dict[str, Any]:
        profile_dict: dict[str, Any] = {}
        if profile.provider is not None:
            profile_dict["provider"] = profile.provider
        if profile.model is not None:
            profile_dict["model"] = profile.model
        if profile.reasoning_effort is not None:
            profile_dict["reasoning_effort"] = profile.reasoning_effort
        profile_dict["source"] = profile.source or _EXECUTOR_PROFILE_SOURCE
        profile_dict["updated_at"] = profile.updated_at or _now_iso()
        return profile_dict

    def _read_json_dict(self, path: str) -> dict[str, Any] | None:
        if not os.path.isfile(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return None
        return data if isinstance(data, dict) else None

    def _apply_settings_payload(
        self,
        *,
        resolved: ResolvedProjectSettings,
        payload: dict[str, Any],
        source_name: str,
        settings_file: str,
    ) -> None:
        provider = payload.get("execution_provider")
        parsed_profile = None
        profile_raw = payload.get("executor_profile")
        if isinstance(profile_raw, dict):
            parsed_profile = self._parse_profile(profile_raw)

        if is_supported_execution_provider(provider):
            resolved.settings.execution_provider = str(provider).strip().lower()
            resolved.provider_source = source_name
            resolved.provider_settings_file = settings_file
        elif parsed_profile is not None and parsed_profile.provider and is_supported_execution_provider(parsed_profile.provider):
            resolved.settings.execution_provider = parsed_profile.provider.strip().lower()
            resolved.provider_source = source_name
            resolved.provider_settings_file = settings_file

        if parsed_profile is not None:
            resolved.settings.executor_profile = parsed_profile
            resolved.profile_source = source_name
            resolved.profile_settings_file = settings_file

    def _extract_user_project_payload(
        self,
        payload: dict[str, Any],
        project_root: str,
    ) -> dict[str, Any] | None:
        project_profiles = payload.get("project_profiles")
        if not isinstance(project_profiles, dict):
            return None
        project_key = project_profile_key(project_root)
        entry = project_profiles.get(project_key)
        return entry if isinstance(entry, dict) else None

    def _load_provider_from_plan(self, plan_file_path: str | None) -> str | None:
        if not plan_file_path or not os.path.exists(plan_file_path):
            return None

        try:
            with open(plan_file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return None

        provider_raw: Any = data.get("execution_provider")
        if is_supported_execution_provider(provider_raw):
            return str(provider_raw).strip().lower()

        model_execution = data.get("model_execution")
        if isinstance(model_execution, dict):
            candidate = model_execution.get("execution_provider") or model_execution.get("provider")
            if is_supported_execution_provider(candidate):
                return str(candidate).strip().lower()

        return None
from runner.runner_paths import resolve_project_runner_dir, resolve_project_runner_plan_path
