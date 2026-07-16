from dataclasses import dataclass, field
from typing import Literal, Optional

@dataclass
class ModelExecutionConfig:
    mode: Literal["manual", "cli"] = "manual"
    model_command: Optional[str] = None
    prompt_input_mode: Literal["stdin", "argument", "file"] = "stdin"
    timeout_seconds: int = 1800
    stream_output: bool = True
    provider: Optional[str] = None
    model: Optional[str] = None
    model_name: Optional[str] = None
    pi_model: Optional[str] = None
    codex_model: Optional[str] = None
    opencode_model: Optional[str] = None

@dataclass
class RunnerPolicy:
    auto_continue_on_pass: bool = False
    max_fix_attempts_per_version: int = 3
    require_clean_worktree: bool = True
    stop_on_acceptance_failure: bool = True
    stop_on_scope_violation: bool = True


@dataclass
class ReviewPolicy:
    enabled: bool = False
    mode: str = "manual_gate"
    after_versions: list[str] = field(default_factory=list)

@dataclass
class CommitPolicy:
    enabled: bool = False
    mode: str = "manual_gate"
    after_acceptance_pass: bool = True
    require_clean_scope: bool = True
    include_runner_runtime_files: bool = False
    require_confirm: bool = True
    require_commit_before_continue: bool = False

@dataclass
class AcceptanceCommand:
    command: str
    cwd: Optional[str] = None
    timeout_seconds: int = 600
    continue_on_failure: bool = False

@dataclass
class VersionExecutionProfile:
    provider: Optional[str] = None
    model: Optional[str] = None
    model_name: Optional[str] = None
    pi_model: Optional[str] = None
    codex_model: Optional[str] = None
    opencode_model: Optional[str] = None
    lane: Optional[str] = None
    capability_level: Optional[str] = None
    notes: Optional[str] = None


@dataclass
class BuildVersion:
    version: str
    name: str
    description: Optional[str]
    prompt_file: str
    enabled: bool
    context_files: list[str] = field(default_factory=list)
    allowed_files: list[str] = field(default_factory=list)
    forbidden_files: list[str] = field(default_factory=list)
    acceptance_commands: list[AcceptanceCommand] = field(default_factory=list)
    manual_acceptance: list[str] = field(default_factory=list)
    out_of_scope: list[str] = field(default_factory=list)
    execution: Optional[VersionExecutionProfile] = None
    allow_no_changes: bool = False
    required_changed_files: list[str] = field(default_factory=list)
    work_item_id: Optional[str] = None
    task_version: Optional[int] = None
    attempt_id: Optional[str] = None

@dataclass
class BuildRunnerPlan:
    project_name: str
    plan_version: str
    project_root: str
    model_execution: ModelExecutionConfig
    runner_policy: RunnerPolicy
    versions: list[BuildVersion]
    review_policy: ReviewPolicy = field(default_factory=ReviewPolicy)
    commit_policy: CommitPolicy = field(default_factory=CommitPolicy)
    default_acceptance_commands: list[AcceptanceCommand] = field(default_factory=list)
    logs_dir: str = ".mvp-runner/logs"
    runtime_dir: str = ".mvp-runner/runtime"
    rules_file: str = ".mvp-runner/rules.md"
    state_file: str = ".mvp-runner/state.json"
    work_item_id: Optional[str] = None
    task_version: Optional[int] = None
    attempt_id: Optional[str] = None
