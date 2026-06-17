import json
import os
from pathlib import Path
from typing import Any

from runner.workspace import ProjectWorkspace
from runner.plan_loader import PlanLoader
from runner.state_machine import RunnerStateMachine
from runner.state_mutation_gateway import StateMutationGateway
from runner.state_store import StateStore


class ContinueNextVersionService:
    def __init__(self, project_root: str):
        self.project_root = os.path.abspath(os.path.expanduser(project_root))

    def continue_next_version(self) -> dict[str, Any]:
        workspace = ProjectWorkspace.from_project_path(self.project_root)
        workspace.ensure_directories()
        loader = PlanLoader()
        plan = loader.load_plan(workspace.plan_file)
        plan.project_root = workspace.workspace_root
        plan.logs_dir = workspace.logs_dir
        plan.runtime_dir = workspace.runtime_dir
        plan.state_file = workspace.state_file
        if not os.path.isabs(plan.rules_file):
            plan.rules_file = workspace.rules_file
        loader.validate_plan(plan)
        store = StateStore()
        state = store.load_state(workspace.state_file)
        machine = RunnerStateMachine(plan, state)
        machine.reopen_completed_state_if_pending()
        machine.normalize_passed_current_version_status()

        if state.status != "VERSION_PASSED":
            return {
                "ok": False,
                "action": "continue_next_version",
                "error_code": "CONTINUE_BLOCKED",
                "message": "当前版本尚未通过，不能进入下一版本。",
            }

        current_runtime = self._current_version_runtime(state)
        commit_policy = getattr(plan, "commit_policy", None)
        if (
            state.status == "VERSION_PASSED"
            and commit_policy
            and getattr(commit_policy, "enabled", False)
            and getattr(commit_policy, "require_commit_before_continue", False)
            and current_runtime
            and not current_runtime.commit_hash
        ):
            return {
                "ok": False,
                "action": "continue_next_version",
                "error_code": "COMMIT_REQUIRED",
                "message": "当前版本已通过但未提交，请先提交。",
            }

        if (
            state.status == "VERSION_PASSED"
            and self._is_version_review_checkpoint(plan, state.current_version)
            and not self._is_version_reviewed(state.current_version)
        ):
            return {
                "ok": False,
                "action": "continue_next_version",
                "error_code": "REVIEW_REQUIRED",
                "message": "当前版本是审查节点，需先完成阶段审查。",
            }

        baseline_updated_at = state.updated_at

        try:
            machine.continue_next_version()
        except Exception as e:
            return {
                "ok": False,
                "action": "continue_next_version",
                "error_code": "CONTINUE_BLOCKED",
                "message": str(e),
            }
        StateMutationGateway().save(state, workspace.state_file, expected_updated_at=baseline_updated_at)

        if state.status == "COMPLETED":
            msg = "所有版本已完成。"
        else:
            msg = f"已进入下一版本：{state.current_version}"

        return {
            "ok": True,
            "action": "continue_next_version",
            "message": msg,
            "current_version": state.current_version,
            "current_version_index": state.current_version_index,
            "runner_status": state.status,
            "state_file": workspace.state_file,
        }

    def _current_version_runtime(self, state: Any):
        if not state or not state.current_version:
            return None
        current_index = state.current_version_index
        if not isinstance(current_index, int) or not (0 <= current_index < len(state.versions)):
            return None
        return state.versions[current_index]

    def _is_version_review_checkpoint(self, plan: Any, version: str | None) -> bool:
        if not version:
            return False
        policy = getattr(plan, "review_policy", None)
        if not policy:
            return False
        if not getattr(policy, "enabled", False):
            return False
        return version in (getattr(policy, "after_versions", []) or [])

    def _is_version_reviewed(self, version: str | None) -> bool:
        if not version:
            return False
        review_file = resolve_project_runner_path(self.project_root, "review-state.json")
        try:
            data = json.loads(Path(review_file).read_text(encoding="utf-8"))
        except Exception:
            return False
        reviewed_version = data.get("last_reviewed_version")
        review_file_path = data.get("last_review_file")
        if reviewed_version != version:
            return False
        if not isinstance(review_file_path, str) or not review_file_path:
            return False
        return os.path.exists(review_file_path)
from runner.runner_paths import resolve_project_runner_path
