from dataclasses import dataclass
from typing import Any, Literal, Optional

RunnerStatus = Literal[
    "CREATED",
    "PLAN_LOADED",
    "READY",
    "PROMPT_READY",
    "WAITING_MODEL_DONE",
    "RUNNING_ACCEPTANCE",
    "VERSION_PASSED",
    "NEXT_VERSION_READY",
    "AUDIT_READY",
    "WAITING_MANUAL_FIX_PROMPT",
    "FIX_PROMPT_READY",
    "WAITING_FIX_MODEL_DONE",
    "RUNNING_FIX_ACCEPTANCE",
    "COMPLETED",
    "BLOCKED_BY_ACCEPTANCE_FAILURE",
    "BLOCKED_BY_SCOPE_VIOLATION",
    "BLOCKED_BY_MODEL_FAILURE",
    "BLOCKED_BY_DIRTY_WORKTREE",
    "BLOCKED_BY_INVALID_PLAN",
    "BLOCKED_BY_MAX_FIX_ATTEMPTS",
    "FAILED",
    "CANCELLED",
]

VersionStatus = Literal[
    "NOT_STARTED",
    "PROMPT_READY",
    "WAITING_MODEL_DONE",
    "ACCEPTANCE_RUNNING",
    "PASSED",
    "FAILED_BLOCKED",
    "FIX_WAITING",
    "FIX_PROMPT_READY",
    "FIX_WAITING_MODEL_DONE",
    "FIX_ACCEPTANCE_RUNNING",
    "BLOCKED",
    "CANCELLED",
]

@dataclass
class BuildVersionRuntimeState:
    version: str
    name: str
    status: VersionStatus
    attempt: int = 0
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    last_run_id: Optional[str] = None
    last_prompt_file: Optional[str] = None
    last_audit_file: Optional[str] = None
    commit_hash: Optional[str] = None
    committed_at: Optional[str] = None
    commit_message: Optional[str] = None
    commit_files: Optional[list[str]] = None
    metadata: Optional[dict[str, Any]] = None
    note: Optional[str] = None

@dataclass
class RunnerError:
    code: str
    message: str
    detail: Optional[str] = None

@dataclass
class BuildRunnerState:
    project_name: str
    status: RunnerStatus
    current_version: Optional[str]
    current_version_index: int
    attempt: int
    max_fix_attempts_per_version: int
    versions: list[BuildVersionRuntimeState]
    started_at: Optional[str] = None
    updated_at: Optional[str] = None
    completed_at: Optional[str] = None
    last_prompt_file: Optional[str] = None
    last_generated_prompt_file: Optional[str] = None
    last_audit_file: Optional[str] = None
    last_log_file: Optional[str] = None
    last_error: Optional[RunnerError] = None
