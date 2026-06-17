import os
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone


class CodexReviewError(RuntimeError):
    def __init__(self, message: str, log_path: str | None = None):
        super().__init__(message)
        self.log_path = log_path


class CodexReviewNotFoundError(CodexReviewError):
    pass


@dataclass
class CodexReviewRunResult:
    command: list[str]
    cwd: str
    log_path: str
    summary_file: str
    started_at: str
    completed_at: str
    exit_code: int
    stdout: str
    stderr: str


class CodexReviewAdapter:
    _ASK_FOR_APPROVAL_SUPPORT_CACHE: dict[str, bool] = {}

    def __init__(
        self,
        executable: str = "codex",
        sandbox_mode: str = "read-only",
        approval_policy: str = "never",
    ):
        self.executable = executable
        self.sandbox_mode = sandbox_mode
        self.approval_policy = approval_policy

    def execute_review(
        self,
        *,
        project_root: str,
        prompt: str,
        summary_file: str,
        log_path: str,
        timeout_seconds: int = 1800,
    ) -> CodexReviewRunResult:
        codex_path = shutil.which(self.executable)
        if not codex_path:
            raise CodexReviewNotFoundError("未找到 codex 命令，请先安装并登录 Codex CLI。")

        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        os.makedirs(os.path.dirname(summary_file), exist_ok=True)

        supports_ask_for_approval = self._supports_ask_for_approval(codex_path)
        command = [
            codex_path,
            "exec",
            "--cd",
            project_root,
            "--json",
            "--sandbox",
            self.sandbox_mode,
        ]
        if supports_ask_for_approval:
            command.extend(["--ask-for-approval", self.approval_policy])
        command.extend([
            "--output-last-message",
            summary_file,
            "-",
        ])

        started_at = self._now()
        stdout = ""
        stderr = ""
        exit_code = 1
        completed_at = started_at

        try:
            result = subprocess.run(
                command,
                input=prompt,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                cwd=project_root,
                timeout=timeout_seconds,
            )
            stdout = result.stdout or ""
            stderr = result.stderr or ""
            exit_code = result.returncode
            completed_at = self._now()
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout or ""
            stderr = exc.stderr or ""
            exit_code = -1
            completed_at = self._now()
            self._write_log(
                log_path=log_path,
                command=command,
                codex_path=codex_path,
                supports_ask_for_approval=supports_ask_for_approval,
                cwd=project_root,
                started_at=started_at,
                completed_at=completed_at,
                stdout=stdout,
                stderr=stderr,
                exit_code=exit_code,
                summary_file=summary_file,
            )
            raise CodexReviewError(f"Codex 阶段审查失败，已写入日志：{log_path}", log_path=log_path) from exc
        except Exception as exc:
            completed_at = self._now()
            self._write_log(
                log_path=log_path,
                command=command,
                codex_path=codex_path,
                supports_ask_for_approval=supports_ask_for_approval,
                cwd=project_root,
                started_at=started_at,
                completed_at=completed_at,
                stdout=stdout,
                stderr=stderr,
                exit_code=exit_code,
                summary_file=summary_file,
            )
            raise CodexReviewError(f"Codex 阶段审查失败，已写入日志：{log_path}", log_path=log_path) from exc

        self._write_log(
            log_path=log_path,
            command=command,
            codex_path=codex_path,
            supports_ask_for_approval=supports_ask_for_approval,
            cwd=project_root,
            started_at=started_at,
            completed_at=completed_at,
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
            summary_file=summary_file,
        )

        if exit_code != 0:
            raise CodexReviewError(f"Codex 阶段审查失败，已写入日志：{log_path}", log_path=log_path)

        return CodexReviewRunResult(
            command=command,
            cwd=project_root,
            log_path=log_path,
            summary_file=summary_file,
            started_at=started_at,
            completed_at=completed_at,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
        )

    def _write_log(
        self,
        *,
        log_path: str,
        command: list[str],
        codex_path: str,
        supports_ask_for_approval: bool,
        cwd: str,
        started_at: str,
        completed_at: str,
        stdout: str,
        stderr: str,
        exit_code: int,
        summary_file: str,
    ) -> None:
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("# Codex Stage Review Log\n")
            f.write(f"started_at: {started_at}\n")
            f.write(f"completed_at: {completed_at}\n")
            f.write(f"codex_path: {codex_path}\n")
            f.write(f"codex_supports_ask_for_approval: {str(supports_ask_for_approval).lower()}\n")
            f.write(f"command: {' '.join(command)}\n")
            f.write(f"cwd: {cwd}\n")
            f.write(f"summary_file: {summary_file}\n")
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

    def _now(self) -> str:
        return datetime.now(timezone.utc).astimezone().isoformat()
