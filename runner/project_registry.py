from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import tempfile
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from runner._internal_utils import now_iso as _now_iso
from runner.runner_paths import (
    resolve_project_runner_dir,
    user_config_dir,
)
from runner.runner_settings import RunnerSettingsStore, project_profile_key
from runner.plan_reload_workflow import PlanReloadService
from runner.state_mutation_gateway import StateMutationGateway


DEFAULT_SCHEMA_VERSION = 1
REGISTRY_FILE_NAME = "project-registry.json"
PROJECT_MODE_SOURCE_ONLY = "source-only"
PROJECT_MODE_MANAGED = "managed"
PROJECT_MODES = {PROJECT_MODE_SOURCE_ONLY, PROJECT_MODE_MANAGED}
_PROJECT_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_PROJECT_ID_PATTERN = re.compile(r"^prj_[0-9a-f]{16}$")
_PLAN_PATH_FIELDS = {
    "project_root",
    "workspace",
    "workspace_path",
    "logs_dir",
    "runtime_dir",
    "state_file",
    "rules_file",
    "prompts_dir",
    "backup_dir",
    "plan_file",
}


@dataclass(frozen=True)
class ProjectRegistryRecord:
    project_id: str
    project_name: str
    project_root: str
    project_mode: str
    display_name: str
    updated_at: str
    last_selected_at: str | None = None


def _is_sensitive_key(key: str) -> bool:
    lower = key.lower()
    return any(
        marker in lower
        for marker in (
            "api_key",
            "apikey",
            "api-key",
            "authorization",
            "auth_token",
            "authtoken",
            "bearer",
            "secret",
            "token",
        )
    )


class ProjectRegistry:
    def __init__(
        self,
        registry_path: str | None = None,
        config_dir: str | None = None,
        user_settings_path: str | None = None,
    ):
        self._registry_path = self._resolve_registry_path(registry_path, config_dir)
        self._user_settings_path = (
            os.path.abspath(os.path.expanduser(user_settings_path))
            if isinstance(user_settings_path, str) and user_settings_path.strip()
            else RunnerSettingsStore().user_settings_path()
        )
        self._identity_previews: dict[str, dict[str, Any]] = {}

    def registry_path(self) -> str:
        return self._registry_path

    def normalize_project_root(self, project_root: str) -> str:
        if not isinstance(project_root, str) or not project_root.strip():
            raise ValueError("project_root must be a non-empty local path.")
        raw = project_root.strip()
        if "\x00" in raw:
            raise ValueError("project_root contains an invalid character.")
        if "://" in raw:
            raise ValueError("project_root must be a local path.")
        return os.path.realpath(os.path.abspath(os.path.expanduser(raw)))

    def validate_project_name(self, project_name: str) -> str:
        if not isinstance(project_name, str):
            raise ValueError("project_name must be a non-empty registry key.")
        clean_name = project_name.strip()
        if not clean_name:
            raise ValueError("project_name must be a non-empty registry key.")
        if clean_name in {".", ".."}:
            raise ValueError("project_name contains a reserved value.")
        if not _PROJECT_NAME_PATTERN.fullmatch(clean_name):
            raise ValueError("project_name 仅支持字母、数字、点、下划线和中横线，且必须以字母或数字开头。")
        return clean_name

    def validate_project_mode(self, project_mode: str) -> str:
        if not isinstance(project_mode, str):
            raise ValueError("project_mode must be source-only or managed.")
        clean_mode = project_mode.strip().lower()
        if clean_mode not in PROJECT_MODES:
            raise ValueError("project_mode must be source-only or managed.")
        return clean_mode

    def is_runner_managed_project(self, project_root: str) -> bool:
        root = self.normalize_project_root(project_root)
        runner_dir = resolve_project_runner_dir(root)
        return os.path.isfile(os.path.join(runner_dir, "plan.json")) or os.path.isfile(
            os.path.join(runner_dir, "state.json")
        )

    def infer_project_mode(self, project_root: str) -> str:
        root = self.normalize_project_root(project_root)
        return PROJECT_MODE_MANAGED if self.is_runner_managed_project(root) else PROJECT_MODE_SOURCE_ONLY

    def validate_existing_local_project(self, project_root: str) -> str:
        root = self.normalize_project_root(project_root)
        if not os.path.isdir(root):
            raise ValueError(f"project_root does not exist: {root}")
        return root

    def validate_switch_target(self, project_root: str) -> str:
        root = self.validate_existing_local_project(project_root)
        if not self.is_runner_managed_project(root):
            raise ValueError("project_root is not a Runner-managed project.")
        return root

    def list_projects(self) -> dict[str, Any]:
        payload = self._load_payload()
        records = self._records_from_payload(payload)
        return {
            "ok": True,
            "registry_path": self._registry_path,
            "projects": [asdict(record) for record in records],
            "project_count": len(records),
        }

    def get_project(self, project_root: str) -> dict[str, Any]:
        root = self.normalize_project_root(project_root)
        records = self._records_from_payload(self._load_payload())
        target = next((record for record in records if record.project_root == root), None)
        if target is None:
            return {"ok": False, "error_code": "PROJECT_NOT_REGISTERED", "message": "项目尚未登记。"}
        return {"ok": True, "registry_path": self._registry_path, "project": asdict(target)}

    def get_project_by_name(self, project_name: str) -> dict[str, Any]:
        wanted_name = self.validate_project_name(project_name)
        records = self._records_from_payload(self._load_payload())
        target = next((record for record in records if record.project_name == wanted_name), None)
        if target is None:
            return {"ok": False, "error_code": "PROJECT_NOT_REGISTERED", "message": "项目尚未登记。"}
        return {"ok": True, "registry_path": self._registry_path, "project": asdict(target)}

    def resolve_project_name(self, project_name: str) -> dict[str, Any]:
        try:
            lookup = self.get_project_by_name(project_name)
        except ValueError as exc:
            return {"ok": False, "error_code": "INVALID_PROJECT_NAME", "message": str(exc)}
        if not lookup.get("ok"):
            return lookup
        project = lookup.get("project")
        if not isinstance(project, dict):
            return {"ok": False, "error_code": "PROJECT_NOT_REGISTERED", "message": "项目尚未登记。"}
        try:
            self.validate_existing_local_project(str(project.get("project_root") or ""))
        except ValueError as exc:
            return {
                "ok": False,
                "error_code": "PROJECT_UNAVAILABLE",
                "message": str(exc),
                "project": project,
            }
        return lookup

    def resolve_managed_project_name(self, project_name: str) -> dict[str, Any]:
        lookup = self.resolve_project_name(project_name)
        if not lookup.get("ok"):
            return lookup
        project = lookup.get("project")
        if not isinstance(project, dict):
            return {"ok": False, "error_code": "PROJECT_NOT_REGISTERED", "message": "项目尚未登记。"}
        project_mode = str(project.get("project_mode") or "").strip().lower()
        if project_mode != PROJECT_MODE_MANAGED:
            return {
                "ok": False,
                "error_code": "PROJECT_MODE_UNSUPPORTED",
                "message": "当前操作需要 managed 项目。source-only 项目仅支持只读 project_name 路由。",
                "project": project,
            }
        return lookup

    def register_project(
        self,
        project_root: str,
        *,
        project_name: str | None = None,
        project_mode: str | None = None,
        display_name: str | None = None,
        last_selected: bool = False,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        root = self.validate_existing_local_project(project_root)
        now = _now_iso()
        payload = self._load_payload()
        records = {record.project_root: record for record in self._records_from_payload(payload)}
        existing = records.get(root)
        requested_mode = self.validate_project_mode(project_mode) if project_mode is not None else None
        inferred_display = self._clean_label(display_name) or self._read_plan_project_name(root) or os.path.basename(root)
        clean_name = self._resolve_project_name(
            requested_name=project_name,
            display_name=inferred_display,
            fallback_root=root,
            existing=existing,
            records=records,
        )
        plan_project_name = self._read_plan_project_name(root)
        warning = None
        if plan_project_name is not None and plan_project_name != clean_name:
            warning = (
                f"registry.project_name 已修正为 plan.json 的 project_name（{plan_project_name}），"
                f"传入的 project_name（{clean_name}）不是 canonical source。"
            )
            clean_name = plan_project_name
        clean_display = self._clean_label(display_name)
        if clean_display is None and existing is not None:
            clean_display = self._clean_label(existing.display_name)
        if clean_display is None:
            clean_display = inferred_display
        clean_display = self._clean_label(clean_display) or clean_name
        clean_mode = requested_mode or self.infer_project_mode(root)
        last_selected_at = now if last_selected else (existing.last_selected_at if existing else None)
        project_id = existing.project_id if existing is not None else self._project_id(root)
        record = ProjectRegistryRecord(
            project_id=project_id,
            project_name=clean_name,
            project_root=root,
            project_mode=clean_mode,
            display_name=clean_display,
            updated_at=now,
            last_selected_at=last_selected_at,
        )
        records[root] = record
        sanitized_extra = self._strip_sensitive_extra(extra or {})
        new_payload: dict[str, Any] = {
            "schema_version": DEFAULT_SCHEMA_VERSION,
            "projects": [asdict(item) for item in sorted(records.values(), key=lambda item: item.display_name.lower())],
        }
        if sanitized_extra:
            new_payload["metadata"] = sanitized_extra
        self._write_payload(new_payload)
        result = {
            "ok": True,
            "registry_path": self._registry_path,
            "project": asdict(record),
            "project_count": len(records),
        }
        if warning:
            result["warning"] = warning
        return result

    def preview_project_identity_migration(
        self,
        *,
        project_id: str | None = None,
        current_project_root: str | None = None,
        new_project_name: str,
        new_display_name: str | None = None,
        new_project_root: str,
    ) -> dict[str, Any]:
        blockers: list[str] = []
        warnings: list[str] = []
        conflicts: list[dict[str, str]] = []
        changes: list[dict[str, Any]] = []

        try:
            clean_name = self.validate_project_name(new_project_name)
        except ValueError as exc:
            clean_name = ""
            blockers.append(str(exc))
        clean_display = self._clean_label(new_display_name) or clean_name
        if not clean_display:
            blockers.append("display_name 必须为非空文本，或使用有效的 project_name。")

        try:
            target_root = self.normalize_project_root(new_project_root)
        except ValueError as exc:
            target_root = ""
            blockers.append(str(exc))

        records = self._records_from_payload(self._load_payload())
        target = self._find_identity_target(
            records,
            project_id=project_id,
            current_project_root=current_project_root,
        )
        if target is None:
            blockers.append("目标项目未在 registry 中登记。")

        if target_root:
            if not os.path.isdir(target_root):
                blockers.append(f"new_project_root 不存在：{target_root}")
            elif not self._is_git_repository(target_root):
                blockers.append("new_project_root 不是 Git repository。")
            elif not self.is_runner_managed_project(target_root):
                blockers.append("new_project_root 不是 Runner-managed 项目。")

        if target is not None and clean_name:
            name_conflict = next(
                (
                    record
                    for record in records
                    if record.project_id != target.project_id and record.project_name == clean_name
                ),
                None,
            )
            if name_conflict is not None:
                conflicts.append({"field": "project_name", "project_id": name_conflict.project_id})
                blockers.append(f"project_name 已被其他登记项目使用：{clean_name}")
        if target is not None and target_root:
            root_conflict = next(
                (
                    record
                    for record in records
                    if record.project_id != target.project_id and record.project_root == target_root
                ),
                None,
            )
            if root_conflict is not None:
                conflicts.append({"field": "project_root", "project_id": root_conflict.project_id})
                blockers.append("new_project_root 已被其他登记项目使用。")

        plan_path = (
            os.path.join(resolve_project_runner_dir(target_root), "plan.json")
            if target_root
            else ""
        )
        state_path = (
            os.path.join(resolve_project_runner_dir(target_root), "state.json")
            if target_root
            else ""
        )
        plan, plan_error = self._read_required_json(plan_path, "plan.json")
        state, state_error = self._read_optional_json(state_path, "state.json")
        if plan_error:
            blockers.append(plan_error)
        if state_error:
            blockers.append(state_error)

        old_roots: list[str] = []
        if target is not None:
            old_roots.append(target.project_root)
        if isinstance(plan, dict):
            plan_root = plan.get("project_root")
            if isinstance(plan_root, str) and plan_root.strip():
                old_roots.append(plan_root.strip())
                try:
                    old_roots.append(self.normalize_project_root(plan_root))
                except ValueError:
                    warnings.append("plan 顶层 project_root 无法规范化，将按原文本匹配。")
        old_roots = list(
            dict.fromkeys(
                root
                for root in old_roots
                if root and root != target_root
            )
        )
        old_name = target.project_name if target is not None else ""

        plan_updates: dict[str, dict[str, str]] = {}
        historical_references: list[dict[str, Any]] = []
        if isinstance(plan, dict) and target_root:
            if plan.get("project_name") != clean_name:
                plan_updates["project_name"] = {
                    "from": str(plan.get("project_name") or ""),
                    "to": clean_name,
                }
            for key in sorted(_PLAN_PATH_FIELDS):
                value = plan.get(key)
                updated = self._replace_root_string(value, old_roots, target_root)
                if isinstance(value, str) and updated != value:
                    plan_updates[key] = {"from": value, "to": updated}
            historical_references = self._find_historical_plan_references(plan, old_roots)
            if historical_references:
                warnings.append("历史 prompt_file 或 acceptance command 仍引用旧工作区，本次迁移保留这些历史记录。")

        state_root_matches = self._count_value_matches(state, old_roots)
        state_name_matches = self._count_exact_matches(state, old_name)
        if state_root_matches or state_name_matches:
            warnings.append("state 中存在旧项目身份引用，apply 将更新以避免 project_mismatch。")

        settings, settings_error = self._read_optional_json(
            self._user_settings_path,
            "colameta-settings.json",
        )
        if settings_error:
            blockers.append(settings_error)
        settings_change = self._build_settings_migration_summary(
            settings,
            old_roots=old_roots,
            new_root=target_root,
        )
        settings_conflict = settings_change.get("conflict")
        if settings_conflict:
            conflicts.append({"field": "user_settings_project_profile", "project_id": str(project_id or "")})
            blockers.append(str(settings_conflict))

        if target is not None:
            registry_fields = {}
            for field, old_value, new_value in (
                ("project_name", target.project_name, clean_name),
                ("display_name", target.display_name, clean_display),
                ("project_root", target.project_root, target_root),
            ):
                if old_value != new_value:
                    registry_fields[field] = {"from": old_value, "to": new_value}
            if registry_fields:
                changes.append({"target": "registry", "fields": registry_fields})
        if plan_updates:
            changes.append({"target": "plan", "path": plan_path, "fields": plan_updates})
        if state_root_matches or state_name_matches:
            changes.append(
                {
                    "target": "state",
                    "path": state_path,
                    "old_project_root_matches": state_root_matches,
                    "old_project_name_matches": state_name_matches,
                }
            )
        if settings_change.get("needed"):
            changes.append(
                {
                    "target": "user_settings",
                    "path": self._user_settings_path,
                    "profile_key_change": settings_change.get("profile_key_change"),
                    "project_root_change": settings_change.get("project_root_change"),
                }
            )

        if blockers or target is None or not isinstance(plan, dict):
            return {
                "ok": False,
                "action": "project_identity_preview",
                "blockers": blockers,
                "warnings": warnings,
                "conflicts": conflicts,
                "changes": changes,
                "historical_references": historical_references,
            }

        preview_id = f"project-identity-{uuid.uuid4().hex}"
        preview = {
            "preview_id": preview_id,
            "project_id": target.project_id,
            "old_project_name": old_name,
            "old_project_roots": old_roots,
            "registry_identity": {
                "project_name": target.project_name,
                "display_name": target.display_name,
                "project_root": target.project_root,
            },
            "plan_identity": {
                key: plan.get(key)
                for key in sorted({"project_name", *_PLAN_PATH_FIELDS})
                if key in plan
            },
            "new_project_name": clean_name,
            "new_display_name": clean_display,
            "new_project_root": target_root,
            "plan_path": plan_path,
            "state_path": state_path,
            "settings_path": self._user_settings_path,
            "changes": changes,
            "warnings": warnings,
            "historical_references": historical_references,
        }
        self._identity_previews[preview_id] = preview
        return {
            "ok": True,
            "action": "project_identity_preview",
            "preview_id": preview_id,
            "project_id": target.project_id,
            "blockers": [],
            "warnings": warnings,
            "conflicts": conflicts,
            "changes": changes,
            "historical_references": historical_references,
        }

    def apply_project_identity_migration(self, preview_id: str) -> dict[str, Any]:
        preview = self._identity_previews.get(str(preview_id or "").strip())
        if not isinstance(preview, dict):
            return {
                "ok": False,
                "action": "project_identity_apply",
                "error_code": "PREVIEW_NOT_FOUND",
                "message": "找不到可应用的项目身份迁移预览。",
            }

        payload = self._load_payload()
        records = self._records_from_payload(payload)
        target = next(
            (record for record in records if record.project_id == preview["project_id"]),
            None,
        )
        if target is None:
            return {
                "ok": False,
                "action": "project_identity_apply",
                "error_code": "PROJECT_NOT_REGISTERED",
                "message": f"registry 中的目标 project_id 已不存在：{preview['project_id']}。",
            }

        preview_registry_identity = preview.get("registry_identity")
        if isinstance(preview_registry_identity, dict):
            for field in ("project_name", "display_name", "project_root"):
                old_value = preview_registry_identity.get(field)
                current_value = getattr(target, field)
                if current_value != old_value:
                    return {
                        "ok": False,
                        "action": "project_identity_apply",
                        "error_code": "PREVIEW_STALE",
                        "message": (
                            f"registry 项目字段 {field} 在 preview 后发生危险变化："
                            f"{old_value!r} -> {current_value!r}。"
                        ),
                    }

        name_conflict = next(
            (
                record
                for record in records
                if record.project_id != target.project_id
                and record.project_name == preview["new_project_name"]
            ),
            None,
        )
        if name_conflict is not None:
            return {
                "ok": False,
                "action": "project_identity_apply",
                "error_code": "PROJECT_NAME_CONFLICT",
                "message": (
                    "registry.project_name 在 preview 后产生冲突："
                    f"{preview['new_project_name']} 已被 project_id={name_conflict.project_id} 使用。"
                ),
            }

        root_conflict = next(
            (
                record
                for record in records
                if record.project_id != target.project_id
                and record.project_root == preview["new_project_root"]
            ),
            None,
        )
        if root_conflict is not None:
            return {
                "ok": False,
                "action": "project_identity_apply",
                "error_code": "PROJECT_ROOT_CONFLICT",
                "message": (
                    "registry.project_root 在 preview 后产生冲突："
                    f"{preview['new_project_root']} 已被 project_id={root_conflict.project_id} 使用。"
                ),
            }

        new_root = preview["new_project_root"]
        if not os.path.isdir(new_root):
            return {
                "ok": False,
                "action": "project_identity_apply",
                "error_code": "PROJECT_ROOT_UNAVAILABLE",
                "message": f"new_project_root 在 preview 后变为不可用：{new_root} 不存在。",
            }
        if not self._is_git_repository(new_root):
            return {
                "ok": False,
                "action": "project_identity_apply",
                "error_code": "PROJECT_ROOT_UNAVAILABLE",
                "message": f"new_project_root 在 preview 后变为不可用：{new_root} 不是 Git repository。",
            }
        if not self.is_runner_managed_project(new_root):
            return {
                "ok": False,
                "action": "project_identity_apply",
                "error_code": "PROJECT_ROOT_UNAVAILABLE",
                "message": f"new_project_root 在 preview 后变为不可用：{new_root} 不是 Runner-managed 项目。",
            }

        plan, plan_error = self._read_required_json(preview["plan_path"], "plan.json")
        state, state_error = self._read_optional_json(preview["state_path"], "state.json")
        settings, settings_error = self._read_optional_json(
            preview["settings_path"],
            "colameta-settings.json",
        )
        if plan_error or not isinstance(plan, dict):
            return {
                "ok": False,
                "action": "project_identity_apply",
                "error_code": "MIGRATION_INPUT_INVALID",
                "message": f"迁移目标 plan.json 无法读取：{plan_error or '顶层必须是 JSON object。'}",
            }
        if state_error:
            return {
                "ok": False,
                "action": "project_identity_apply",
                "error_code": "MIGRATION_INPUT_INVALID",
                "message": f"迁移目标 state.json 无法读取：{state_error}",
            }
        if settings_error:
            return {
                "ok": False,
                "action": "project_identity_apply",
                "error_code": "MIGRATION_INPUT_INVALID",
                "message": f"用户设置 colameta-settings.json 无法读取：{settings_error}",
            }

        preview_plan_identity = preview.get("plan_identity")
        if isinstance(preview_plan_identity, dict):
            for field, old_value in preview_plan_identity.items():
                current_value = plan.get(field)
                if current_value != old_value:
                    return {
                        "ok": False,
                        "action": "project_identity_apply",
                        "error_code": "PREVIEW_STALE",
                        "message": (
                            f"plan.json 顶层字段 {field} 在 preview 后发生危险变化："
                            f"{old_value!r} -> {current_value!r}。"
                        ),
                    }

        settings_change = self._build_settings_migration_summary(
            settings,
            old_roots=preview["old_project_roots"],
            new_root=new_root,
        )
        if settings_change.get("conflict"):
            return {
                "ok": False,
                "action": "project_identity_apply",
                "error_code": "USER_SETTINGS_CONFLICT",
                "message": f"用户设置 project_profiles 在 preview 后产生冲突：{settings_change['conflict']}",
            }

        now = _now_iso()
        updated_record = ProjectRegistryRecord(
            project_id=target.project_id,
            project_name=preview["new_project_name"],
            display_name=preview["new_display_name"],
            project_root=preview["new_project_root"],
            project_mode=target.project_mode,
            updated_at=now,
            last_selected_at=target.last_selected_at,
        )
        updated_records = [
            updated_record if record.project_id == target.project_id else record
            for record in records
        ]
        registry_payload = {
            "schema_version": DEFAULT_SCHEMA_VERSION,
            "projects": [
                asdict(record)
                for record in sorted(updated_records, key=lambda item: item.display_name.lower())
            ],
        }
        if payload.get("metadata"):
            registry_payload["metadata"] = payload["metadata"]

        plan_result = PlanReloadService.migrate_plan_identity(
            plan_path=preview["plan_path"],
            new_project_name=preview["new_project_name"],
            new_project_root=preview["new_project_root"],
            old_project_roots=preview["old_project_roots"],
        )
        if not plan_result.get("ok"):
            return {
                "ok": False,
                "action": "project_identity_apply",
                "error_code": "PLAN_MIGRATION_FAILED",
                "message": f"plan.json 身份迁移失败：{plan_result.get('message') or plan_result.get('error_code', 'unknown')}",
            }

        if isinstance(state, dict):
            migrated_state = self._replace_identity_values(
                state,
                old_roots=preview["old_project_roots"],
                new_root=preview["new_project_root"],
                old_name=preview["old_project_name"],
                new_name=preview["new_project_name"],
            )
            StateMutationGateway().save_raw(migrated_state, preview["state_path"])

        if isinstance(settings, dict):
            migrate_result = RunnerSettingsStore().migrate_project_profile(
                settings_path=preview["settings_path"],
                old_roots=preview["old_project_roots"],
                new_root=preview["new_project_root"],
            )
            if not migrate_result.get("ok"):
                return {
                    "ok": False,
                    "action": "project_identity_apply",
                    "error_code": "SETTINGS_MIGRATION_FAILED",
                    "message": f"用户设置身份迁移失败：{migrate_result.get('message') or migrate_result.get('error_code', 'unknown')}",
                }

        self._write_payload(registry_payload)
        self._identity_previews.pop(preview_id, None)
        return {
            "ok": True,
            "action": "project_identity_apply",
            "preview_id": preview_id,
            "project_id": updated_record.project_id,
            "project": asdict(updated_record),
            "changed_targets": [item["target"] for item in preview["changes"]],
            "warnings": preview["warnings"],
            "message": "项目身份迁移已完成。请刷新页面；项目路径变化时请重启或重新选择项目。",
            "requires_refresh": True,
            "requires_restart_or_reselect": target.project_root != updated_record.project_root,
        }

    def select_project(
        self,
        *,
        project_id: str | None = None,
        project_name: str | None = None,
        project_root: str | None = None,
    ) -> dict[str, Any]:
        payload = self._load_payload()
        records = self._records_from_payload(payload)
        target: ProjectRegistryRecord | None = None
        if isinstance(project_id, str) and project_id.strip():
            wanted_id = project_id.strip()
            target = next((record for record in records if record.project_id == wanted_id), None)
        elif isinstance(project_name, str) and project_name.strip():
            try:
                wanted_name = self.validate_project_name(project_name)
                target = next((record for record in records if record.project_name == wanted_name), None)
            except ValueError:
                target = None
        elif isinstance(project_root, str) and project_root.strip():
            wanted_root = self.normalize_project_root(project_root)
            target = next((record for record in records if record.project_root == wanted_root), None)

        if target is None:
            return {
                "ok": False,
                "error_code": "PROJECT_NOT_REGISTERED",
                "message": "只能切换到已登记的 Runner 项目。",
            }

        try:
            root = self.validate_switch_target(target.project_root)
        except ValueError as exc:
            return {
                "ok": False,
                "error_code": "PROJECT_UNAVAILABLE",
                "message": str(exc),
                "project": asdict(target),
            }

        return self.register_project(
            root,
            project_name=None,
            project_mode=target.project_mode,
            display_name=target.display_name,
            last_selected=True,
        )

    def _resolve_registry_path(self, registry_path: str | None, config_dir: str | None) -> str:
        if isinstance(registry_path, str) and registry_path.strip():
            return os.path.abspath(os.path.expanduser(registry_path.strip()))
        if isinstance(config_dir, str) and config_dir.strip():
            root = os.path.abspath(os.path.expanduser(config_dir.strip()))
        else:
            root = user_config_dir()
        return os.path.join(root, REGISTRY_FILE_NAME)

    def _project_id(self, project_root: str) -> str:
        digest = hashlib.sha256(project_root.encode("utf-8")).hexdigest()[:16]
        return f"prj_{digest}"

    def _load_payload(self) -> dict[str, Any]:
        path = Path(self._registry_path)
        if not path.is_file():
            return {"schema_version": DEFAULT_SCHEMA_VERSION, "projects": []}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {"schema_version": DEFAULT_SCHEMA_VERSION, "projects": []}
        if not isinstance(data, dict):
            return {"schema_version": DEFAULT_SCHEMA_VERSION, "projects": []}
        projects = data.get("projects")
        if not isinstance(projects, list):
            data["projects"] = []
        return data

    def _records_from_payload(self, payload: dict[str, Any]) -> list[ProjectRegistryRecord]:
        records: dict[str, ProjectRegistryRecord] = {}
        for item in payload.get("projects", []):
            if not isinstance(item, dict):
                continue
            root_raw = item.get("project_root")
            try:
                root = self.normalize_project_root(root_raw)
            except ValueError:
                continue
            raw_mode = self._clean_label(item.get("project_mode"))
            project_mode = raw_mode if raw_mode in PROJECT_MODES else self.infer_project_mode(root)
            project_name = self._clean_label(item.get("project_name")) or self._project_name_from_label(os.path.basename(root)) or os.path.basename(root)
            display_name = self._clean_label(item.get("display_name")) or project_name
            updated_at = self._clean_label(item.get("updated_at")) or _now_iso()
            last_selected_at = self._clean_label(item.get("last_selected_at"))
            stored_project_id = self._clean_label(item.get("project_id"))
            project_id = (
                stored_project_id
                if stored_project_id and _PROJECT_ID_PATTERN.fullmatch(stored_project_id)
                else self._project_id(root)
            )
            records[root] = ProjectRegistryRecord(
                project_id=project_id,
                project_name=project_name,
                project_root=root,
                project_mode=project_mode,
                display_name=display_name,
                updated_at=updated_at,
                last_selected_at=last_selected_at,
            )
        return sorted(records.values(), key=lambda item: item.display_name.lower())

    def _write_payload(self, payload: dict[str, Any]) -> None:
        directory = os.path.dirname(self._registry_path)
        os.makedirs(directory, exist_ok=True)
        lock_path = self._registry_path + ".lock"
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            fd, tmp_path = tempfile.mkstemp(prefix=".tmp-project-registry-", suffix=".json", dir=directory)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(payload, f, ensure_ascii=False, indent=2)
                    f.write("\n")
                os.replace(tmp_path, self._registry_path)
            except Exception:
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
                raise
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)

    def _clean_label(self, value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        cleaned = value.strip()
        if not cleaned:
            return None
        return cleaned[:200]

    def _read_plan_project_name(self, project_root: str) -> str | None:
        plan_file = os.path.join(resolve_project_runner_dir(project_root), "plan.json")
        if not os.path.isfile(plan_file):
            return None
        try:
            data = json.loads(Path(plan_file).read_text(encoding="utf-8"))
        except Exception:
            return None
        if not isinstance(data, dict):
            return None
        return self._clean_label(data.get("project_name"))

    def _project_name_from_label(self, value: Any) -> str | None:
        label = self._clean_label(value)
        if label is None:
            return None
        normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", label).strip(".-_")
        if not normalized:
            return None
        if normalized in {".", ".."}:
            return None
        normalized = normalized[:64]
        if not normalized:
            return None
        if not normalized[0].isalnum():
            normalized = f"p{normalized}"[:64]
        return normalized

    def _dedupe_project_name(
        self,
        base_name: str,
        *,
        project_root: str,
        records: dict[str, ProjectRegistryRecord],
        existing: ProjectRegistryRecord | None,
    ) -> str:
        if existing is not None and existing.project_root == project_root and existing.project_name == base_name:
            return base_name
        seen = {
            record.project_name
            for root, record in records.items()
            if root != project_root
        }
        if base_name not in seen:
            return base_name
        suffix = self._project_id(project_root)[4:10]
        candidate = f"{base_name[: max(1, 64 - len(suffix) - 1)]}-{suffix}"
        if candidate not in seen:
            return candidate
        for index in range(2, 1000):
            indexed = f"{base_name[: max(1, 64 - len(str(index)) - 1)]}-{index}"
            if indexed not in seen:
                return indexed
        raise ValueError("unable to allocate a unique project_name for registry record.")

    def _resolve_project_name(
        self,
        *,
        requested_name: str | None,
        display_name: str,
        fallback_root: str,
        existing: ProjectRegistryRecord | None,
        records: dict[str, ProjectRegistryRecord],
    ) -> str:
        if requested_name is not None:
            clean_name = self.validate_project_name(requested_name)
            duplicate = next(
                (
                    record for root, record in records.items()
                    if root != fallback_root and record.project_name == clean_name
                ),
                None,
            )
            if duplicate is not None:
                raise ValueError(f"project_name already registered: {clean_name}")
            return clean_name
        if existing is not None and self._clean_label(existing.project_name) and not self._read_plan_project_name(fallback_root):
            return existing.project_name
        base_name = (
            self._project_name_from_label(display_name)
            or self._project_name_from_label(os.path.basename(fallback_root))
            or self._project_id(fallback_root)
        )
        return self._dedupe_project_name(
            base_name,
            project_root=fallback_root,
            records=records,
            existing=existing,
        )

    def unregister_project(
        self,
        *,
        project_id: str | None = None,
        project_name: str | None = None,
        project_root: str | None = None,
    ) -> dict[str, Any]:
        payload = self._load_payload()
        records = {record.project_root: record for record in self._records_from_payload(payload)}
        target: ProjectRegistryRecord | None = None
        if isinstance(project_id, str) and project_id.strip():
            target = next((r for r in records.values() if r.project_id == project_id.strip()), None)
        elif isinstance(project_name, str) and project_name.strip():
            try:
                wanted_name = self.validate_project_name(project_name)
                target = next((r for r in records.values() if r.project_name == wanted_name), None)
            except ValueError:
                target = None
        elif isinstance(project_root, str) and project_root.strip():
            try:
                root = self.normalize_project_root(project_root)
                target = records.get(root)
            except ValueError:
                pass
        if target is None:
            return {
                "ok": False,
                "error_code": "PROJECT_NOT_REGISTERED",
                "message": "该项目未在登记列表中。",
            }
        del records[target.project_root]
        new_payload: dict[str, Any] = {
            "schema_version": DEFAULT_SCHEMA_VERSION,
            "projects": [asdict(item) for item in sorted(records.values(), key=lambda item: item.display_name.lower())],
        }
        extra = payload.get("metadata")
        if extra:
            new_payload["metadata"] = extra
        self._write_payload(new_payload)
        return {
            "ok": True,
            "action": "unregister_project",
            "removed_project": asdict(target),
            "removed_count": 1,
            "project_count": len(records),
            "message": f"已从登记列表中移除项目「{target.display_name}」，磁盘文件未改动。",
        }

    def _temp_dir_candidates(self) -> list[str]:
        candidates: list[str] = []
        try:
            sys_temp = os.path.realpath(tempfile.gettempdir())
            if sys_temp:
                candidates.append(sys_temp)
        except Exception:
            pass
        for p in ("/tmp", "/private/tmp"):
            try:
                real = os.path.realpath(p)
                if real not in candidates:
                    candidates.append(real)
            except Exception:
                pass
        return candidates

    def is_temp_path(self, project_root: str) -> bool:
        try:
            real = os.path.realpath(project_root)
        except Exception:
            return False
        basename = os.path.basename(real)
        if not basename.startswith("tmp"):
            return False
        for tmp in self._temp_dir_candidates():
            if real.startswith(tmp + "/") or real == tmp:
                return True
        return False

    def prune_unavailable_projects(self, *, preserve_project_root: str | None = None) -> dict[str, Any]:
        payload = self._load_payload()
        records = list(self._records_from_payload(payload))
        preserved_root = ""
        if isinstance(preserve_project_root, str) and preserve_project_root.strip():
            try:
                preserved_root = self.normalize_project_root(preserve_project_root)
            except ValueError:
                preserved_root = ""
        kept: list[ProjectRegistryRecord] = []
        removed_count = 0
        for record in records:
            if preserved_root and record.project_root == preserved_root:
                kept.append(record)
            elif os.path.isdir(record.project_root):
                kept.append(record)
            else:
                removed_count += 1
        new_payload: dict[str, Any] = {
            "schema_version": DEFAULT_SCHEMA_VERSION,
            "projects": [asdict(item) for item in sorted(kept, key=lambda item: item.display_name.lower())],
        }
        extra = payload.get("metadata")
        if extra:
            new_payload["metadata"] = extra
        self._write_payload(new_payload)
        return {
            "ok": True,
            "action": "prune_unavailable_projects",
            "removed_count": removed_count,
            "project_count": len(kept),
            "message": f"已清理 {removed_count} 个不可用的项目登记记录，磁盘文件未改动。",
        }

    def prune_temporary_projects(self, *, preserve_project_root: str | None = None) -> dict[str, Any]:
        payload = self._load_payload()
        records = list(self._records_from_payload(payload))
        preserved_root = ""
        if isinstance(preserve_project_root, str) and preserve_project_root.strip():
            try:
                preserved_root = self.normalize_project_root(preserve_project_root)
            except ValueError:
                preserved_root = ""
        kept: list[ProjectRegistryRecord] = []
        removed_count = 0
        for record in records:
            if preserved_root and record.project_root == preserved_root:
                kept.append(record)
            elif self.is_temp_path(record.project_root):
                removed_count += 1
            else:
                kept.append(record)
        new_payload: dict[str, Any] = {
            "schema_version": DEFAULT_SCHEMA_VERSION,
            "projects": [asdict(item) for item in sorted(kept, key=lambda item: item.display_name.lower())],
        }
        extra = payload.get("metadata")
        if extra:
            new_payload["metadata"] = extra
        self._write_payload(new_payload)
        return {
            "ok": True,
            "action": "prune_temporary_projects",
            "removed_count": removed_count,
            "project_count": len(kept),
            "message": f"已清理 {removed_count} 个临时项目的登记记录，磁盘文件未改动。",
        }

    def _strip_sensitive_extra(self, extra: dict[str, Any]) -> dict[str, Any]:
        clean: dict[str, Any] = {}
        for key, value in extra.items():
            if not isinstance(key, str) or _is_sensitive_key(key):
                continue
            if isinstance(value, (str, int, float, bool)) or value is None:
                clean[key] = value
        return clean

    def _find_identity_target(
        self,
        records: list[ProjectRegistryRecord],
        *,
        project_id: str | None,
        current_project_root: str | None,
    ) -> ProjectRegistryRecord | None:
        if isinstance(project_id, str) and project_id.strip():
            wanted = project_id.strip()
            return next((record for record in records if record.project_id == wanted), None)
        if isinstance(current_project_root, str) and current_project_root.strip():
            try:
                wanted_root = self.normalize_project_root(current_project_root)
            except ValueError:
                return None
            return next((record for record in records if record.project_root == wanted_root), None)
        return None

    def _is_git_repository(self, project_root: str) -> bool:
        git_path = os.path.join(project_root, ".git")
        return os.path.isdir(git_path) or os.path.isfile(git_path)

    def _read_required_json(self, path: str, label: str) -> tuple[dict[str, Any] | None, str | None]:
        if not path or not os.path.isfile(path):
            return None, f"{label} 不存在。"
        return self._read_optional_json(path, label)

    def _read_optional_json(self, path: str, label: str) -> tuple[dict[str, Any] | None, str | None]:
        if not path or not os.path.isfile(path):
            return None, None
        try:
            value = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None, f"{label} 无法解析为 JSON。"
        if not isinstance(value, dict):
            return None, f"{label} 顶层必须是 JSON object。"
        return value, None

    def _replace_root_string(self, value: Any, old_roots: list[str], new_root: str) -> Any:
        if not isinstance(value, str):
            return value
        for old_root in sorted(old_roots, key=len, reverse=True):
            if value == old_root or value.startswith(old_root + os.sep):
                return new_root + value[len(old_root):]
        return value

    def _find_historical_plan_references(
        self,
        plan: dict[str, Any],
        old_roots: list[str],
    ) -> list[dict[str, Any]]:
        references: list[dict[str, Any]] = []
        versions = plan.get("versions")
        if not isinstance(versions, list):
            return references
        for version in versions:
            if not isinstance(version, dict):
                continue
            fields: list[str] = []
            prompt_file = version.get("prompt_file")
            if isinstance(prompt_file, str) and self._count_value_matches(prompt_file, old_roots):
                fields.append("prompt_file")
            commands = version.get("acceptance_commands")
            if self._count_value_matches(commands, old_roots):
                fields.append("acceptance_commands")
            if fields:
                references.append(
                    {
                        "version": str(version.get("version") or ""),
                        "fields": fields,
                    }
                )
        return references

    def _count_value_matches(self, value: Any, roots: list[str]) -> int:
        if isinstance(value, str):
            return sum(value.count(root) for root in roots)
        if isinstance(value, list):
            return sum(self._count_value_matches(item, roots) for item in value)
        if isinstance(value, dict):
            return sum(self._count_value_matches(item, roots) for item in value.values())
        return 0

    def _count_exact_matches(self, value: Any, wanted: str) -> int:
        if not wanted:
            return 0
        if isinstance(value, str):
            return int(value == wanted)
        if isinstance(value, list):
            return sum(self._count_exact_matches(item, wanted) for item in value)
        if isinstance(value, dict):
            return sum(self._count_exact_matches(item, wanted) for item in value.values())
        return 0

    def _build_settings_migration_summary(
        self,
        settings: dict[str, Any] | None,
        *,
        old_roots: list[str],
        new_root: str,
    ) -> dict[str, Any]:
        if not isinstance(settings, dict):
            return {"needed": False}
        profiles = settings.get("project_profiles")
        if not isinstance(profiles, dict):
            return {"needed": False}
        old_keys = [project_profile_key(root) for root in old_roots]
        new_key = project_profile_key(new_root)
        source_keys = [
            key
            for key, profile in profiles.items()
            if (key != new_key and key in old_keys)
            or (
                isinstance(profile, dict)
                and isinstance(profile.get("project_root"), str)
                and self._replace_root_string(profile["project_root"], old_roots, new_root)
                != profile["project_root"]
            )
        ]
        if not source_keys:
            return {"needed": False}
        if new_key in profiles and new_key not in source_keys:
            return {
                "needed": True,
                "conflict": "用户设置中已存在 new_project_root 的项目 profile。",
            }
        return {
            "needed": True,
            "profile_key_change": {"from": source_keys[0], "to": new_key},
            "project_root_change": {"to": new_root},
        }

    def _replace_identity_values(
        self,
        value: Any,
        *,
        old_roots: list[str],
        new_root: str,
        old_name: str,
        new_name: str,
    ) -> Any:
        if isinstance(value, str):
            replaced = self._replace_root_string(value, old_roots, new_root)
            return new_name if replaced == old_name else replaced
        if isinstance(value, list):
            return [
                self._replace_identity_values(
                    item,
                    old_roots=old_roots,
                    new_root=new_root,
                    old_name=old_name,
                    new_name=new_name,
                )
                for item in value
            ]
        if isinstance(value, dict):
            return {
                key: self._replace_identity_values(
                    item,
                    old_roots=old_roots,
                    new_root=new_root,
                    old_name=old_name,
                    new_name=new_name,
                )
                for key, item in value.items()
            }
        return value

    def _strip_sensitive_recursive(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: self._strip_sensitive_recursive(item)
                for key, item in value.items()
                if isinstance(key, str) and not _is_sensitive_key(key)
            }
        if isinstance(value, list):
            return [self._strip_sensitive_recursive(item) for item in value]
        return value

    def _atomic_json_transaction(self, writes: dict[str, dict[str, Any]]) -> None:
        staged: dict[str, str] = {}
        originals: dict[str, bytes | None] = {}
        replaced: list[str] = []
        try:
            for path, payload in writes.items():
                directory = os.path.dirname(path)
                os.makedirs(directory, exist_ok=True)
                originals[path] = Path(path).read_bytes() if os.path.isfile(path) else None
                fd, tmp_path = tempfile.mkstemp(prefix=".tmp-project-identity-", suffix=".json", dir=directory)
                with os.fdopen(fd, "w", encoding="utf-8") as file_obj:
                    json.dump(payload, file_obj, ensure_ascii=False, indent=2)
                    file_obj.write("\n")
                    file_obj.flush()
                    os.fsync(file_obj.fileno())
                staged[path] = tmp_path
            for path, tmp_path in staged.items():
                os.replace(tmp_path, path)
                replaced.append(path)
        except Exception:
            for path in reversed(replaced):
                original = originals[path]
                if original is None:
                    try:
                        os.remove(path)
                    except OSError:
                        pass
                else:
                    fd, rollback_path = tempfile.mkstemp(
                        prefix=".tmp-project-identity-rollback-",
                        dir=os.path.dirname(path),
                    )
                    with os.fdopen(fd, "wb") as file_obj:
                        file_obj.write(original)
                        file_obj.flush()
                        os.fsync(file_obj.fileno())
                    os.replace(rollback_path, path)
            raise
        finally:
            for tmp_path in staged.values():
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
