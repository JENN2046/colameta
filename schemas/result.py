from dataclasses import dataclass, field
from typing import Literal, Optional
from schemas.command import CommandStatus

@dataclass
class ModelRunRequest:
    run_id: str
    version: str
    attempt: int
    mode: Literal["manual", "cli"]
    prompt: str
    prompt_file: str
    working_directory: str
    model_command: Optional[str] = None

@dataclass
class ModelRunResult:
    run_id: str
    version: str
    attempt: int
    mode: Literal["manual", "cli"]
    status: Literal["NOT_EXECUTED", "RUNNING", "DONE", "FAILED", "MANUAL_DONE"]
    exit_code: Optional[int] = None
    stdout: Optional[str] = None
    stderr: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    log_file: Optional[str] = None

@dataclass
class AcceptanceCommandResult:
    command: str
    status: CommandStatus
    exit_code: Optional[int]
    stdout: str
    stderr: str
    started_at: Optional[str]
    completed_at: Optional[str]
    duration_ms: Optional[int]
    cwd: Optional[str] = None
    original_command: Optional[str] = None
    executed_command: Optional[str] = None
    resolved_python: Optional[str] = None
    venv_bin_path: Optional[str] = None
    rewrite_warning: Optional[str] = None

@dataclass
class AcceptanceRunResult:
    run_id: str
    version: str
    attempt: int
    status: Literal["PASSED", "FAILED", "NOT_RUN"]
    commands: list[AcceptanceCommandResult]
    started_at: Optional[str] = None
    completed_at: Optional[str] = None

@dataclass
class ScopeCheckResult:
    status: Literal["PASSED", "FAILED", "NOT_CHECKED"]
    allowed_files: list[str] = field(default_factory=list)
    forbidden_files: list[str] = field(default_factory=list)
    raw_changed_files: list[str] = field(default_factory=list)
    ignored_runtime_files: list[str] = field(default_factory=list)
    scope_checked_files: list[str] = field(default_factory=list)
    outside_allowed_files: list[str] = field(default_factory=list)
    forbidden_changed_files: list[str] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    changed_outside_allowed_files: list[str] = field(default_factory=list)
    changed_forbidden_files: list[str] = field(default_factory=list)
    git_diff_name_only_output: Optional[str] = None
    git_diff_stat_output: Optional[str] = None

@dataclass
class VersionRunResult:
    run_id: str
    version: str
    attempt: int
    status: Literal["PASSED", "FAILED", "CANCELLED"]
    model_run: Optional[ModelRunResult]
    acceptance_run: Optional[AcceptanceRunResult]
    scope_check: ScopeCheckResult
    changed_files: list[str]
    audit_file: Optional[str]
    log_file: str
    started_at: str
    completed_at: str
    work_item_id: Optional[str] = None
    task_version: Optional[int] = None
    attempt_id: Optional[str] = None
