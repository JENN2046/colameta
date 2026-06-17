import os
from datetime import datetime, timezone
from typing import Any

from runner.state_mutation_gateway import StateMutationGateway


class CommitStateUpdateService:
    def __init__(self, project_root: str):
        self.project_root = os.path.abspath(os.path.expanduser(project_root))

    def record_commit_metadata(
        self,
        commit_hash: str,
        commit_message: str,
        committed_files: list[str],
        version: str | None = None,
    ) -> dict[str, Any]:
        state_file = resolve_project_runner_path(self.project_root, "state.json")
        if not os.path.isfile(state_file):
            return {
                "ok": True,
                "skipped": True,
                "reason": "runner_state_missing",
                "state_file": state_file,
            }

        from runner.state_store import StateStore

        store = StateStore()
        try:
            state = store.load_state(state_file)
        except Exception:
            return {
                "ok": True,
                "skipped": True,
                "reason": "state_load_failed",
                "state_file": state_file,
            }

        target_runtime = None
        target_version: str | None = None
        requested_version = version.strip() if isinstance(version, str) and version.strip() else None

        if requested_version:
            for runtime in state.versions:
                if runtime.version == requested_version:
                    target_runtime = runtime
                    target_version = runtime.version
                    break
            if target_runtime is None:
                return {
                    "ok": True,
                    "skipped": True,
                    "reason": "version_not_found",
                    "state_file": state_file,
                    "version": requested_version,
                }
        else:
            if not state.current_version:
                return {
                    "ok": True,
                    "skipped": True,
                    "reason": "no_current_version",
                    "state_file": state_file,
                }

            current_index = state.current_version_index
            if not isinstance(current_index, int) or not (0 <= current_index < len(state.versions)):
                return {
                    "ok": True,
                    "skipped": True,
                    "reason": "no_current_version",
                    "state_file": state_file,
                }
            target_runtime = state.versions[current_index]
            target_version = state.current_version

        committed_at = datetime.now(timezone.utc).astimezone().isoformat()
        baseline_updated_at = state.updated_at
        target_runtime.commit_hash = commit_hash
        target_runtime.committed_at = committed_at
        target_runtime.commit_message = commit_message
        target_runtime.commit_files = list(committed_files)
        if hasattr(target_runtime, "status") and target_runtime.status == "NOT_STARTED":
            target_runtime.status = "PASSED"
        state.updated_at = datetime.now(timezone.utc).astimezone().isoformat()

        try:
            StateMutationGateway().save(state, state_file, expected_updated_at=baseline_updated_at)
        except Exception:
            return {
                "ok": False,
                "skipped": True,
                "reason": "state_save_failed",
                "state_file": state_file,
            }

        return {
            "ok": True,
            "skipped": False,
            "state_file": state_file,
            "version": target_version,
        }
from runner.runner_paths import resolve_project_runner_path
