import os
import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from adapters.executor_process_supervisor import ExecutorProcessSupervisor
from runner.executor_events import ExecutorEventStore
from runner.git_diff_helper import (
    collect_business_git_diff_name_paths,
    is_root_runner_path,
    normalize_repo_path,
)
from runner.token_usage import normalize_token_usage


UUID_PATTERN = re.compile(
    r"(?i)^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
PREFIXED_UUID_PATTERN = re.compile(
    r"(?i)^(?:thread|session|sess|conversation|conv)[_.:-]"
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
PREFIXED_THREAD_NAME_PATTERN = re.compile(
    r"(?i)^(?:thread|session|sess|conversation|conv)[_.:-][a-z0-9][a-z0-9_.:-]{15,255}$"
)
TEXT_RESUME_HINT_PATTERN = re.compile(
    r"(?i)\bcodex(?:\s+exec)?\s+resume\s+([A-Za-z0-9_.:-]+)"
)


class CodexCliError(RuntimeError):
    def __init__(self, message: str, log_path: str | None = None):
        super().__init__(message)
        self.log_path = log_path


class CodexNotFoundError(CodexCliError):
    pass


class CodexUnauthorizedError(CodexCliError):
    pass


@dataclass
class CodexRunResult:
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
    no_business_diff: bool | None = None
    looks_like_prompt_generation: bool | None = None
    final_message_preview: str | None = None
    conversation_id: str | None = None
    attempted_resume: bool = False
    used_resume: bool = False
    resume_conversation_id_present: bool = False
    fallback_to_new_session: bool = False
    resume_failed_reason: str | None = None
    conversation_id_source: str | None = None
    command_shape: str | None = None
    token_usage: dict[str, Any] | None = None


class CodexCliAdapter:
    _ASK_FOR_APPROVAL_SUPPORT_CACHE: dict[str, bool] = {}

    def __init__(
        self,
        executable: str = "codex",
        sandbox_mode: str = "workspace-write",
        approval_policy: str = "never",
        model: str | None = None,
    ):
        self.executable = executable
        self.sandbox_mode = sandbox_mode
        self.approval_policy = approval_policy
        self.model = model.strip() if isinstance(model, str) and model.strip() else None

    def execute_prompt(
        self,
        *,
        project_root: str,
        logs_dir: str,
        version: str,
        attempt: int,
        prompt: str,
        prompt_file: str,
        summary_file: str,
        timeout_seconds: int = 3600,
        execution_mode: str = "normal",
        resume_conversation_id: str | None = None,
        run_id: str | None = None,
        event_context: dict[str, Any] | None = None,
    ) -> CodexRunResult:
        codex_path = shutil.which(self.executable)
        if not codex_path:
            raise CodexNotFoundError("未找到 codex 命令，请先安装并登录 Codex CLI。")

        self._business_diff_warning = None
        os.makedirs(logs_dir, exist_ok=True)
        safe_version = version.replace(os.sep, "-").replace("/", "-")
        attempted_resume = bool(resume_conversation_id)
        if attempted_resume and execution_mode == "fix":
            log_suffix = "-resume-fix-run-"
        elif attempted_resume:
            log_suffix = "-resume-run-"
        else:
            log_suffix = "-fix-run-" if execution_mode == "fix" else "-run-"
        log_path = os.path.join(logs_dir, f"{safe_version}-codex{log_suffix}{attempt}.log")

        supports_ask_for_approval = self._supports_ask_for_approval(codex_path)
        command_shape = "codex_exec_resume" if attempted_resume else "codex_exec_new"
        command = self._build_command(
            codex_path=codex_path,
            project_root=project_root,
            summary_file=summary_file,
            supports_ask_for_approval=supports_ask_for_approval,
            attempted_resume=attempted_resume,
            resume_conversation_id=resume_conversation_id,
        )

        started_at = self._now()
        stdout = ""
        stderr = ""
        exit_code = 1
        completed_at = started_at
        pre_business_diff_files = self._get_business_diff_files(project_root)
        post_business_diff_files = pre_business_diff_files
        codex_no_business_diff = None
        final_message = None
        final_message_preview = None
        codex_looks_like_prompt_generation = None
        execution_input = self._build_execution_input(
            prompt=prompt,
            execution_mode=execution_mode,
        )

        supervisor = ExecutorProcessSupervisor()
        event_store = ExecutorEventStore(project_root) if run_id else None
        try:
            proc_result = supervisor.run_process(
                command=command,
                cwd=project_root,
                input_text=execution_input,
                timeout_seconds=timeout_seconds,
                event_store=event_store,
                run_id=run_id,
                event_context=event_context,
            )
            stdout = proc_result.stdout
            stderr = proc_result.stderr
            exit_code = proc_result.returncode
            completed_at = self._now()
            if proc_result.timed_out:
                timeout_shape = command_shape + "_timeout"
                self._write_log(
                    log_path=log_path,
                    command=command,
                    codex_path=codex_path,
                    supports_ask_for_approval=supports_ask_for_approval,
                    cwd=project_root,
                    prompt_file=prompt_file,
                    execution_mode=execution_mode,
                    prompt_wrapped=True,
                    codex_warning=None,
                    business_diff_warning=self._business_diff_warning,
                    pre_business_diff_files=pre_business_diff_files,
                    post_business_diff_files=None,
                    codex_no_business_diff=None,
                    codex_looks_like_prompt_generation=None,
                    final_message_preview=None,
                    attempted_resume=attempted_resume,
                    used_resume=attempted_resume,
                    command_shape=timeout_shape,
                    started_at=started_at,
                    completed_at=completed_at,
                    stdout=stdout,
                    stderr=stderr,
                    exit_code=exit_code,
                )
                raise CodexCliError(f"Codex 执行超时，已写入日志：{log_path}", log_path=log_path)
        except CodexCliError:
            raise
        except Exception as exc:
            completed_at = self._now()
            error_shape = command_shape + "_error"
            self._write_log(
                log_path=log_path,
                command=command,
                codex_path=codex_path,
                supports_ask_for_approval=supports_ask_for_approval,
                cwd=project_root,
                prompt_file=prompt_file,
                execution_mode=execution_mode,
                prompt_wrapped=True,
                codex_warning=None,
                business_diff_warning=self._business_diff_warning,
                pre_business_diff_files=pre_business_diff_files,
                post_business_diff_files=None,
                codex_no_business_diff=None,
                codex_looks_like_prompt_generation=None,
                final_message_preview=None,
                attempted_resume=attempted_resume,
                used_resume=attempted_resume,
                command_shape=error_shape,
                started_at=started_at,
                completed_at=completed_at,
                stdout=stdout,
                stderr=stderr,
                exit_code=exit_code,
            )
            raise CodexCliError(f"Codex 执行失败，已写入日志：{log_path}", log_path=log_path) from exc

        post_business_diff_files = self._get_business_diff_files(project_root)
        codex_no_business_diff = self._normalized_path_set(pre_business_diff_files) == self._normalized_path_set(post_business_diff_files)
        final_message = self._extract_final_assistant_text(stdout)
        final_message_preview = self._truncate_summary(final_message or "", max_length=300) if final_message else None
        codex_looks_like_prompt_generation = self._looks_like_prompt_generation(final_message)
        codex_warning = self._detect_prompt_generation_warning(final_message)
        self._write_log(
            log_path=log_path,
            command=command,
            codex_path=codex_path,
            supports_ask_for_approval=supports_ask_for_approval,
            cwd=project_root,
            prompt_file=prompt_file,
            execution_mode=execution_mode,
            prompt_wrapped=True,
            codex_warning=codex_warning,
            business_diff_warning=self._business_diff_warning,
            pre_business_diff_files=pre_business_diff_files,
            post_business_diff_files=post_business_diff_files,
            codex_no_business_diff=codex_no_business_diff,
            codex_looks_like_prompt_generation=codex_looks_like_prompt_generation,
            final_message_preview=final_message_preview,
            attempted_resume=attempted_resume,
            used_resume=attempted_resume,
            command_shape=command_shape,
            started_at=started_at,
            completed_at=completed_at,
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
        )

        if exit_code != 0:
            if self._looks_unauthorized(stdout) or self._looks_unauthorized(stderr):
                raise CodexUnauthorizedError("codex 尚未登录或授权失效，请先在终端运行 codex 并完成登录。", log_path=log_path)
            raise CodexCliError(f"Codex 执行失败，已写入日志：{log_path}", log_path=log_path)

        if (
            execution_mode == "fix"
            and codex_no_business_diff is True
            and codex_looks_like_prompt_generation is True
        ):
            raise CodexCliError(
                "Codex 已退出但没有产生代码改动，且输出像是在生成提示词而不是执行修复。请检查修复提示词或改用 Pi 执行器。",
                log_path=log_path,
            )

        summary = self._load_codex_summary(summary_file, stdout, log_path)
        conversation_id = self._extract_resume_conversation_id(
            stderr,
            final_message,
            final_message_preview,
            summary,
            stdout,
        )
        conversation_id_source = "codex_resume_hint" if conversation_id else None
        if attempted_resume and not conversation_id:
            fallback_conversation_id = self._clean_resume_candidate(
                resume_conversation_id,
                source_kind="resume_input",
            )
            if fallback_conversation_id:
                conversation_id = fallback_conversation_id
                conversation_id_source = "resume_input_fallback"

        raw_token_usage = self._extract_token_usage_from_jsonl(stdout)
        token_usage = normalize_token_usage(
            raw_token_usage,
            source="turn.completed.usage",
            provider="codex",
        ) if raw_token_usage else normalize_token_usage(
            None,
            source="codex_cli",
            provider="codex",
        )

        return CodexRunResult(
            command=command,
            cwd=project_root,
            prompt_file=prompt_file,
            log_path=log_path,
            started_at=started_at,
            completed_at=completed_at,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            summary=summary,
            summary_path=summary_file,
            no_business_diff=codex_no_business_diff,
            looks_like_prompt_generation=codex_looks_like_prompt_generation,
            final_message_preview=final_message_preview,
            conversation_id=conversation_id,
            attempted_resume=attempted_resume,
            used_resume=attempted_resume,
            resume_conversation_id_present=attempted_resume,
            fallback_to_new_session=False,
            resume_failed_reason=None,
            conversation_id_source=conversation_id_source,
            command_shape=command_shape,
            token_usage=token_usage,
        )

    def _build_command(
        self,
        *,
        codex_path: str,
        project_root: str,
        summary_file: str,
        supports_ask_for_approval: bool,
        attempted_resume: bool,
        resume_conversation_id: str | None,
    ) -> list[str]:
        if attempted_resume:
            if not isinstance(resume_conversation_id, str) or not resume_conversation_id.strip():
                raise CodexCliError("resume_conversation_id 为空或空白字符串，无法继续。")
            command = [codex_path, "exec", "resume"]
            if self.model:
                command.extend(["--model", self.model])
            command.extend([
                "--json",
                "--output-last-message",
                summary_file,
                str(resume_conversation_id),
                "-",
            ])
            return command

        command = [codex_path, "exec"]
        if self.model:
            command.extend(["--model", self.model])
        command.extend([
            "--cd",
            project_root,
            "--json",
            "--sandbox",
            self.sandbox_mode,
        ])
        if supports_ask_for_approval:
            command.extend(["--ask-for-approval", self.approval_policy])
        command.extend([
            "--output-last-message",
            summary_file,
            "-",
        ])
        return command

    def _extract_resume_conversation_id(self, *texts: str | None) -> str | None:
        high_priority_texts: list[str] = []
        fallback_texts: list[str] = []
        for index, text in enumerate(texts):
            if not isinstance(text, str) or not text.strip():
                continue
            if index == len(texts) - 1:
                fallback_texts.append(text)
            else:
                high_priority_texts.append(text)

        candidates = self._extract_structured_resume_candidates(high_priority_texts)
        if candidates:
            return candidates[-1]

        fallback_candidates = self._extract_structured_resume_candidates(fallback_texts)
        if fallback_candidates:
            return fallback_candidates[-1]

        candidates = self._extract_text_resume_candidates(high_priority_texts)
        if candidates:
            return candidates[-1]

        fallback_candidates = self._extract_text_resume_candidates(fallback_texts)
        if fallback_candidates:
            return fallback_candidates[-1]
        return None

    def _extract_structured_resume_candidates(self, texts: list[str]) -> list[str]:
        candidates: list[str] = []
        for text in texts:
            candidates.extend(self._extract_jsonl_resume_candidates(text))
        return candidates

    def _extract_text_resume_candidates(self, texts: list[str]) -> list[str]:
        candidates: list[str] = []
        for text in texts:
            for match in TEXT_RESUME_HINT_PATTERN.finditer(text):
                raw_id = (match.group(1) or "").strip()
                cleaned_id = self._clean_resume_candidate(raw_id, source_kind="text")
                if cleaned_id:
                    candidates.append(cleaned_id)
        return candidates

    def _extract_jsonl_resume_candidates(self, text: str) -> list[str]:
        candidates: list[str] = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            event_type = str(payload.get("type", "")).lower()
            raw_id = None
            if event_type == "thread.started":
                raw_id = payload.get("thread_id")
            elif event_type == "session_configured":
                raw_id = payload.get("session_id")
            if raw_id is None:
                thread = payload.get("thread")
                if isinstance(thread, dict):
                    raw_id = thread.get("id")
            if raw_id is None:
                session = payload.get("session")
                if isinstance(session, dict):
                    raw_id = session.get("id")
            cleaned_id = self._clean_resume_candidate(raw_id, source_kind="structured")
            if cleaned_id:
                candidates.append(cleaned_id)
        return candidates

    def _clean_resume_candidate(self, raw_id: object, *, source_kind: str) -> str | None:
        if not isinstance(raw_id, str):
            return None
        cleaned_id = raw_id.strip().rstrip(".,;)]")
        if not self._is_valid_resume_candidate(cleaned_id, source_kind=source_kind):
            return None
        return cleaned_id

    def _is_valid_resume_candidate(self, candidate: str, *, source_kind: str) -> bool:
        if not isinstance(candidate, str):
            return False
        if len(candidate) < 8 or len(candidate) > 256:
            return False
        if candidate.endswith(":"):
            return False
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]*", candidate):
            return False
        if UUID_PATTERN.fullmatch(candidate):
            return True
        if PREFIXED_UUID_PATTERN.fullmatch(candidate):
            return True
        if source_kind in {"structured", "resume_input"} and self._looks_like_named_thread_identity(candidate):
            return True
        return False

    def _looks_like_named_thread_identity(self, candidate: str) -> bool:
        if not PREFIXED_THREAD_NAME_PATTERN.fullmatch(candidate):
            return False
        separator_match = re.search(r"[_.:-]", candidate)
        if separator_match is None:
            return False
        suffix = candidate[separator_match.end():]
        compact_suffix = re.sub(r"[^a-z0-9]", "", suffix.lower())
        if len(compact_suffix) < 16:
            return False
        return any(char.isdigit() for char in compact_suffix)

    def _write_log(
        self,
        *,
        log_path: str,
        command: list[str],
        codex_path: str,
        supports_ask_for_approval: bool,
        cwd: str,
        prompt_file: str,
        execution_mode: str,
        prompt_wrapped: bool,
        codex_warning: str | None,
        started_at: str,
        completed_at: str,
        stdout: str,
        stderr: str,
        exit_code: int,
        pre_business_diff_files: list[str] | None = None,
        post_business_diff_files: list[str] | None = None,
        codex_no_business_diff: bool | None = None,
        codex_looks_like_prompt_generation: bool | None = None,
        final_message_preview: str | None = None,
        attempted_resume: bool = False,
        used_resume: bool = False,
        command_shape: str | None = None,
        business_diff_warning: str | None = None,
    ) -> None:
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("# Codex CLI Execution Log\n")
            f.write(f"execution_mode: {execution_mode}\n")
            if command_shape:
                f.write(f"command_shape: {command_shape}\n")
            f.write(f"attempted_resume: {str(attempted_resume).lower()}\n")
            f.write(f"used_resume: {str(used_resume).lower()}\n")
            f.write(f"started_at: {started_at}\n")
            f.write(f"completed_at: {completed_at}\n")
            f.write(f"codex_path: {codex_path}\n")
            f.write(f"codex_supports_ask_for_approval: {str(supports_ask_for_approval).lower()}\n")
            f.write(f"command: {' '.join(command)}\n")
            f.write(f"cwd: {cwd}\n")
            f.write(f"prompt_file: {prompt_file}\n")
            f.write(f"wrapped_prompt_notice: {str(prompt_wrapped).lower()}\n")
            if codex_warning:
                f.write(f"codex_warning: {codex_warning}\n")
            if business_diff_warning:
                f.write(f"business_diff_warning: {business_diff_warning}\n")
            if pre_business_diff_files is not None:
                f.write(f"pre_business_diff_files: {json.dumps(pre_business_diff_files, ensure_ascii=False)}\n")
            if post_business_diff_files is not None:
                f.write(f"post_business_diff_files: {json.dumps(post_business_diff_files, ensure_ascii=False)}\n")
            if codex_no_business_diff is not None:
                f.write(f"codex_no_business_diff: {str(codex_no_business_diff).lower()}\n")
            if codex_looks_like_prompt_generation is not None:
                f.write(f"codex_looks_like_prompt_generation: {str(codex_looks_like_prompt_generation).lower()}\n")
            if final_message_preview:
                f.write(f"final_message_preview: {json.dumps(final_message_preview, ensure_ascii=False)}\n")
            f.write(f"exit_code: {exit_code}\n")
            f.write("\n## stdout\n")
            f.write(stdout)
            if stdout and not stdout.endswith("\n"):
                f.write("\n")
            f.write("\n## stderr\n")
            f.write(stderr)
            if stderr and not stderr.endswith("\n"):
                f.write("\n")

    def _supports_ask_for_approval(self, codex_path: str) -> bool:
        cached = self._ASK_FOR_APPROVAL_SUPPORT_CACHE.get(codex_path)
        if cached is not None:
            return cached

        supports = False
        try:
            help_result = subprocess.run(
                [codex_path, "exec", "--help"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
            )
            help_text = (help_result.stdout or "") + "\n" + (help_result.stderr or "")
            supports = "--ask-for-approval" in help_text
        except Exception:
            supports = False

        self._ASK_FOR_APPROVAL_SUPPORT_CACHE[codex_path] = supports
        return supports

    def _build_execution_input(self, *, prompt: str, execution_mode: str) -> str:
        mode_text = "fix" if execution_mode == "fix" else "normal"
        mode_instruction = (
            "This is a repair execution task. Apply the repair directly. Do not rewrite the repair prompt."
            if execution_mode == "fix"
            else "This is an implementation task. Implement the current version directly. Do not rewrite the implementation prompt."
        )
        return (
            "You are the code implementation agent for the current repository.\n\n"
            f"Execution mode: {mode_text}\n\n"
            "Important:\n"
            "- Do not generate another prompt.\n"
            "- Do not answer with a prompt template.\n"
            "- Do not only explain what should be done.\n"
            "- Directly inspect and modify files in the current working directory.\n"
            "- Follow the task below exactly.\n"
            "- Stay within the allowed files and constraints stated in the task.\n"
            "- After editing, run the verification commands requested by the task when possible.\n"
            "- Final answer must summarize changed files, command results, remaining work, known risks, and whether forbidden files were modified.\n\n"
            f"{mode_instruction}\n\n"
            "Task to execute:\n"
            f"{prompt}"
        )

    def _detect_prompt_generation_warning(self, final_message: str | None) -> str | None:
        if self._looks_like_prompt_generation(final_message):
            return "final message looks like prompt generation, not code execution"
        return None

    def _looks_like_prompt_generation(self, final_message: str | None) -> bool:
        if not final_message:
            return False
        lowered = final_message.lower()
        markers = [
            "使用下面这版修复提示词",
            "下面这版提示词",
            "下面是提示词",
            "修复提示词",
            "prompt template",
            "here is the prompt",
        ]
        for marker in markers:
            if marker in final_message or marker in lowered:
                return True
        return False

    def _get_business_diff_files(self, project_root: str) -> list[str]:
        try:
            return collect_business_git_diff_name_paths(project_root, timeout_seconds=15)
        except Exception as e:
            self._business_diff_warning = f"git_diff_failed:{e.__class__.__name__}:{str(e)[:200]}"
            return []

    def _normalize_repo_path(self, path: str) -> str:
        return normalize_repo_path(path)

    def _is_root_runner_runtime_path(self, path: str) -> bool:
        return is_root_runner_path(path)

    def _normalized_path_set(self, paths: Iterable[str] | None) -> set[str]:
        if not paths:
            return set()
        normalized_set: set[str] = set()
        for path in paths:
            normalized = self._normalize_repo_path(path)
            if normalized:
                normalized_set.add(normalized)
        return normalized_set

    def _looks_unauthorized(self, text: str) -> bool:
        if not text:
            return False
        lowered = text.lower()
        keywords = [
            "not logged in",
            "login required",
            "authentication",
            "unauthorized",
            "token",
            "api key",
        ]
        return any(k in lowered for k in keywords)

    def _load_codex_summary(self, summary_file: str, stdout: str, log_path: str) -> str:
        summary = self._read_summary_file(summary_file)
        if summary:
            return self._truncate_summary(summary)

        jsonl_summary = self._extract_final_assistant_text(stdout)
        if jsonl_summary:
            return self._truncate_summary(jsonl_summary)

        return f"Codex 已完成，但未返回可展示摘要。完整日志见：{log_path}"

    def _read_summary_file(self, summary_file: str) -> str | None:
        try:
            if not os.path.exists(summary_file):
                return None
            with open(summary_file, "r", encoding="utf-8") as f:
                text = f.read().strip()
            return text or None
        except Exception:
            return None

    def _extract_final_assistant_text(self, stdout: str) -> str | None:
        if not stdout:
            return None

        for line in reversed(stdout.splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue

            role = str(payload.get("role", "")).lower()
            event_type = str(payload.get("type", "")).lower()
            if role != "assistant" and "assistant" not in event_type and "final" not in event_type and "message" not in event_type:
                continue

            for key in ("text", "message", "content", "delta"):
                value = payload.get(key)
                extracted = self._extract_text_value(value)
                if extracted:
                    return extracted
        return None

    def _extract_token_usage_from_jsonl(self, stdout: str) -> dict[str, Any] | None:
        if not stdout:
            return None
        turn_completed_usage: dict[str, Any] | None = None
        latest_usage: dict[str, Any] | None = None
        for line in stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            event_type = str(payload.get("type", "")).lower()
            usage = payload.get("usage")
            if isinstance(usage, dict) and usage:
                latest_usage = usage
                if event_type == "turn.completed":
                    turn_completed_usage = usage
        if turn_completed_usage:
            return turn_completed_usage
        return latest_usage

    def _extract_text_value(self, value) -> str | None:
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return None
            if text.startswith("{") and text.endswith("}"):
                return None
            return text

        if isinstance(value, list):
            parts: list[str] = []
            for item in value:
                text = self._extract_text_value(item)
                if text:
                    parts.append(text)
            if parts:
                return "\n".join(parts).strip()
            return None

        if isinstance(value, dict):
            for key in ("text", "content", "message", "delta"):
                if key not in value:
                    continue
                text = self._extract_text_value(value.get(key))
                if text:
                    return text
        return None

    def _truncate_summary(self, text: str, max_length: int = 1200) -> str:
        stripped = text.strip()
        if len(stripped) <= max_length:
            return stripped
        return stripped[:max_length] + "\n...(已截断)"

    def _now(self) -> str:
        return datetime.now(timezone.utc).astimezone().isoformat()
