from dataclasses import dataclass
from typing import Literal
from schemas.result import AcceptanceCommandResult, ScopeCheckResult

@dataclass
class BuildAuditReport:
    audit_id: str
    project_name: str
    version: str
    version_name: str
    status: Literal[
        "ACCEPTANCE_FAILED",
        "SCOPE_VIOLATION",
        "MODEL_RUN_FAILED",
        "MAX_FIX_ATTEMPTS_REACHED",
        "UNKNOWN_FAILED"
    ]
    attempt: int
    max_attempts: int
    failed_commands: list[AcceptanceCommandResult]
    scope_check: ScopeCheckResult
    changed_files: list[str]
    current_prompt: str
    current_prompt_file: str
    copyable_audit_markdown: str
    created_at: str
