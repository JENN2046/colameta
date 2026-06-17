import json
import os
from typing import Any, Dict, Optional
from datetime import datetime, timezone
from schemas.plan import BuildRunnerPlan
from schemas.state import BuildRunnerState, BuildVersionRuntimeState, RunnerError

class StateStore:
    def load_state(self, path: str) -> BuildRunnerState:
        if not os.path.exists(path):
            raise FileNotFoundError(f"状态文件不存在: {path}")
        
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        return self._parse_state(data)

    def save_state(self, state: BuildRunnerState, path: str) -> None:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self._serialize_state(state), f, indent=2, ensure_ascii=False)

    def initialize_state(self, plan: BuildRunnerPlan) -> BuildRunnerState:
        now = datetime.now(timezone.utc).astimezone().isoformat()

        versions_state = []
        current_version = None
        current_version_index = 0
        for index, version in enumerate(plan.versions):
            versions_state.append(BuildVersionRuntimeState(
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
                metadata=None,
                note=None,
            ))
            if version.enabled and current_version is None:
                current_version = version.version
                current_version_index = index

        return BuildRunnerState(
            project_name=plan.project_name,
            status="READY",
            current_version=current_version,
            current_version_index=current_version_index,
            attempt=1,
            max_fix_attempts_per_version=plan.runner_policy.max_fix_attempts_per_version,
            versions=versions_state,
            started_at=now,
            updated_at=now,
            completed_at=None,
            last_prompt_file=None,
            last_generated_prompt_file=None,
            last_audit_file=None,
            last_log_file=None,
            last_error=None
        )

    def _parse_state(self, data: Dict[str, Any]) -> BuildRunnerState:
        versions = []
        for v_data in data.get("versions", []):
            versions.append(BuildVersionRuntimeState(
                version=v_data.get("version", ""),
                name=v_data.get("name", ""),
                status=v_data.get("status", "NOT_STARTED"),
                attempt=v_data.get("attempt", 0),
                started_at=v_data.get("started_at"),
                completed_at=v_data.get("completed_at"),
                last_run_id=v_data.get("last_run_id"),
                last_prompt_file=v_data.get("last_prompt_file"),
                last_audit_file=v_data.get("last_audit_file"),
                commit_hash=v_data.get("commit_hash"),
                committed_at=v_data.get("committed_at"),
                commit_message=v_data.get("commit_message"),
                commit_files=v_data.get("commit_files"),
                metadata=v_data.get("metadata") if isinstance(v_data.get("metadata"), dict) else None,
                note=v_data.get("note"),
            ))
            
        error_data = data.get("last_error")
        last_error = None
        if error_data:
            last_error = RunnerError(
                code=error_data.get("code", ""),
                message=error_data.get("message", ""),
                detail=error_data.get("detail")
            )

        return BuildRunnerState(
            project_name=data.get("project_name", ""),
            status=data.get("status", "READY"),
            current_version=data.get("current_version"),
            current_version_index=data.get("current_version_index", 0),
            attempt=data.get("attempt", 1),
            max_fix_attempts_per_version=data.get("max_fix_attempts_per_version", 3),
            versions=versions,
            started_at=data.get("started_at"),
            updated_at=data.get("updated_at"),
            completed_at=data.get("completed_at"),
            last_prompt_file=data.get("last_prompt_file"),
            last_generated_prompt_file=data.get("last_generated_prompt_file"),
            last_audit_file=data.get("last_audit_file"),
            last_log_file=data.get("last_log_file"),
            last_error=last_error
        )
        
    def _serialize_state(self, state: BuildRunnerState) -> Dict[str, Any]:
        versions_data = []
        for v in state.versions:
            versions_data.append({
                "version": v.version,
                "name": v.name,
                "status": v.status,
                "attempt": v.attempt,
                "started_at": v.started_at,
                "completed_at": v.completed_at,
                "last_run_id": v.last_run_id,
                "last_prompt_file": v.last_prompt_file,
                "last_audit_file": v.last_audit_file,
                "commit_hash": v.commit_hash,
                "committed_at": v.committed_at,
                "commit_message": v.commit_message,
                "commit_files": v.commit_files,
                "metadata": v.metadata,
                "note": v.note,
            })
            
        error_data = None
        if state.last_error:
            error_data = {
                "code": state.last_error.code,
                "message": state.last_error.message,
                "detail": state.last_error.detail
            }
            
        return {
            "project_name": state.project_name,
            "status": state.status,
            "current_version": state.current_version,
            "current_version_index": state.current_version_index,
            "attempt": state.attempt,
            "max_fix_attempts_per_version": state.max_fix_attempts_per_version,
            "versions": versions_data,
            "started_at": state.started_at,
            "updated_at": state.updated_at,
            "completed_at": state.completed_at,
            "last_prompt_file": state.last_prompt_file,
            "last_generated_prompt_file": state.last_generated_prompt_file,
            "last_audit_file": state.last_audit_file,
            "last_log_file": state.last_log_file,
            "last_error": error_data
        }
