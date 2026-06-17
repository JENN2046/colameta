import json
import os
from datetime import datetime, timezone
from typing import Any

from runner.workspace import ProjectWorkspace
from runner.plan_loader import PlanLoader
from runner.state_mutation_gateway import StateMutationGateway
from runner.state_store import StateStore

_PLAN_IDENTITY_PATH_FIELDS = frozenset({
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
})


class PlanReloadService:
    def __init__(self, project_root: str):
        self.project_root = os.path.abspath(os.path.expanduser(project_root))

    @staticmethod
    def _replace_root_in_string(value: str, old_roots: list[str], new_root: str) -> str:
        for old_root in sorted(old_roots, key=len, reverse=True):
            if value == old_root or value.startswith(old_root + os.sep):
                return new_root + value[len(old_root):]
        return value

    @staticmethod
    def migrate_plan_identity(
        plan_path: str,
        new_project_name: str,
        new_project_root: str,
        old_project_roots: list[str],
    ) -> dict[str, Any]:
        try:
            with open(plan_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            return {"ok": False, "error_code": "PLAN_READ_FAILED", "message": str(e)}
        if not isinstance(data, dict):
            return {"ok": False, "error_code": "PLAN_NOT_OBJECT", "message": "plan.json 顶层必须是 JSON object。"}

        changed_fields: list[str] = []
        if data.get("project_name") != new_project_name:
            data["project_name"] = new_project_name
            changed_fields.append("project_name")
        for key in sorted(_PLAN_IDENTITY_PATH_FIELDS):
            value = data.get(key)
            if isinstance(value, str):
                updated = PlanReloadService._replace_root_in_string(value, old_project_roots, new_project_root)
                if updated != value:
                    data[key] = updated
                    changed_fields.append(key)
        if not changed_fields:
            return {"ok": True, "updated": False, "changed_fields": []}

        tmp_path = f"{plan_path}.tmp-identity-migrate"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp_path, plan_path)
        return {"ok": True, "updated": True, "changed_fields": changed_fields}

    def reload_plan(self) -> dict[str, Any]:
        workspace = ProjectWorkspace.from_project_path(self.project_root)
        workspace.ensure_directories()
        path_sync = self._sync_plan_file_paths(workspace)
        loader = PlanLoader()
        try:
            plan = loader.load_plan(workspace.plan_file)
        except Exception as e:
            return {
                "ok": False,
                "action": "reload_plan",
                "error_code": "PLAN_LOAD_FAILED",
                "message": str(e),
            }
        plan.project_root = workspace.workspace_root
        plan.logs_dir = workspace.logs_dir
        plan.runtime_dir = workspace.runtime_dir
        plan.state_file = workspace.state_file
        if not os.path.isabs(plan.rules_file):
            plan.rules_file = workspace.rules_file
        try:
            loader.validate_plan(plan)
        except Exception as e:
            return {
                "ok": False,
                "action": "reload_plan",
                "error_code": "PLAN_VALIDATION_FAILED",
                "message": str(e),
            }
        store = StateStore()
        try:
            state = store.load_state(workspace.state_file)
        except Exception as e:
            return {
                "ok": False,
                "action": "reload_plan",
                "error_code": "STATE_LOAD_FAILED",
                "message": str(e),
            }

        state_file_baseline_updated_at = state.updated_at
        warnings = self._reconcile_state_with_reloaded_plan(plan, state)
        state.updated_at = datetime.now(timezone.utc).astimezone().isoformat()
        StateMutationGateway().save(state, workspace.state_file, expected_updated_at=state_file_baseline_updated_at)

        return {
            "ok": True,
            "action": "reload_plan",
            "message": "计划已重载。",
            "current_version": state.current_version,
            "current_version_index": state.current_version_index,
            "synced_version_count": len(state.versions),
            "runner_status": state.status,
            "state_file": workspace.state_file,
            "path_sync": path_sync,
            "warnings": warnings,
        }

    def _reconcile_state_with_reloaded_plan(self, plan: Any, state: Any) -> list[str]:
        # PlanReloadService is the owner exception for plan/state alignment during reload.
        # This is not normal version-flow mutation.
        # Normal version-flow mutation belongs to RunnerStateMachine.
        # Do not extract this into a shared helper unless there is a new explicit owner contract.
        warnings: list[str] = []

        # Fix current_version if it no longer exists in plan
        if state.current_version:
            exists = any(v.version == state.current_version for v in plan.versions)
            if not exists:
                index = state.current_version_index
                if isinstance(index, int) and 0 <= index < len(plan.versions):
                    repaired_from = state.current_version
                    repaired_to = plan.versions[index].version
                    state.current_version = repaired_to
                    warnings.append(
                        f"state.current_version {repaired_from} 不在 plan 中，已按 current_version_index={index} 修正为 {repaired_to}。"
                    )
                else:
                    repaired_from = state.current_version
                    state.current_version = None
                    state.current_version_index = 0
                    warnings.append(
                        f"state.current_version {repaired_from} 不在 plan 中，且 current_version_index 不可用，已清除并将按 plan 重新选择当前版本。"
                    )

        # Rebuild state.versions aligned to plan.versions
        state_map = {item.version: item for item in state.versions}
        synced = []
        for version in plan.versions:
            runtime = state_map.get(version.version)
            if runtime is None:
                from schemas.state import BuildVersionRuntimeState

                runtime = BuildVersionRuntimeState(
                    version=version.version,
                    name=version.name,
                    status="NOT_STARTED",
                    attempt=0,
                    started_at=None,
                    completed_at=None,
                    last_run_id=None,
                    last_prompt_file=None,
                    last_audit_file=None,
                    commit_hash=None,
                    committed_at=None,
                    commit_message=None,
                    commit_files=None,
                )
            else:
                runtime.name = version.name
            synced.append(runtime)
        state.versions = synced

        # Reopen COMPLETED if pending enabled versions exist
        self._reopen_completed_state_if_pending(plan, state)

        # Select current_version / current_version_index
        if state.current_version:
            for idx, v in enumerate(plan.versions):
                if v.version == state.current_version:
                    state.current_version_index = idx
                    break
        else:
            for idx, v in enumerate(plan.versions):
                if v.enabled:
                    state.current_version = v.version
                    state.current_version_index = idx
                    break

        return warnings

    @staticmethod
    def _reopen_completed_state_if_pending(plan: Any, state: Any) -> bool:
        if state.status != "COMPLETED":
            return False
        current_index = state.current_version_index
        if not isinstance(current_index, int) or current_index < 0:
            return False
        runtimes = state.versions or []
        if current_index >= len(runtimes):
            return False
        current_runtime = runtimes[current_index]
        if current_runtime.status != "PASSED":
            return False
        for index in range(current_index + 1, len(plan.versions)):
            if plan.versions[index].enabled:
                state.status = "VERSION_PASSED"
                state.completed_at = None
                return True
        return False

    def _sync_plan_file_paths(self, workspace: ProjectWorkspace) -> dict[str, Any]:
        try:
            with open(workspace.plan_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return {"updated": False, "reason": "plan_read_failed"}
        if not isinstance(data, dict):
            return {"updated": False, "reason": "plan_not_object"}

        expected = {
            "project_root": workspace.workspace_root,
            "logs_dir": workspace.logs_dir,
            "runtime_dir": workspace.runtime_dir,
            "state_file": workspace.state_file,
        }
        changed_fields: list[str] = []
        for key, value in expected.items():
            if data.get(key) != value:
                data[key] = value
                changed_fields.append(key)
        rules_file = data.get("rules_file")
        if isinstance(rules_file, str) and os.path.isabs(rules_file) and rules_file != workspace.rules_file:
            data["rules_file"] = workspace.rules_file
            changed_fields.append("rules_file")

        if not changed_fields:
            return {"updated": False, "changed_fields": []}
        tmp_path = f"{workspace.plan_file}.tmp-path-sync"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp_path, workspace.plan_file)
        return {"updated": True, "changed_fields": changed_fields}
