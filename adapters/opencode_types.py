"""Shared OpenCode error types and result structures."""

from dataclasses import dataclass
from typing import Any


class OpenCodeCliError(RuntimeError):
    def __init__(self, message: str, log_path: str | None = None):
        super().__init__(message)
        self.log_path = log_path


@dataclass
class OpenCodeRunResult:
    command: list[str]
    cwd: str
    prompt_file: str
    log_path: str
    started_at: str
    completed_at: str
    exit_code: int
    stdout: str
    stderr: str
    summary: str | None = None
    summary_path: str | None = None
    final_message_preview: str | None = None
    conversation_id: str | None = None
    session_id: str | None = None
    session_file: str | None = None
    attempted_resume: bool = False
    used_resume: bool = False
    resume_session_id_present: bool = False
    fallback_to_new_session: bool = False
    resume_failed_reason: str | None = None
    identity_source: str | None = None
    command_shape: str | None = None
    token_usage: dict[str, Any] | None = None
    terminal_reason: str | None = None
    provider_status: str | None = None
    provider_error_code: str | None = None
    provider_error_summary: str | None = None
