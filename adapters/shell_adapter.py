import subprocess
import time
import shlex
import os
from typing import Optional
from dataclasses import dataclass

@dataclass
class ShellResult:
    exit_code: int
    stdout: str
    stderr: str
    started_at: str
    completed_at: str
    duration_ms: int

class ShellAdapter:
    _SHELL_META_PATTERNS = ("&&", "||", ";", "|", ">", "<", "`", "$(", "${", "\n", "\r")
    _ALLOWED_EXECUTABLES = frozenset(
        {
            "python",
            "python3",
            "pytest",
            "git",
            "make",
            "tox",
            "nox",
            "ruff",
            "mypy",
            "pyright",
            "node",
            "npm",
            "npx",
            "pnpm",
            "yarn",
            "uv",
            "go",
            "cargo",
        }
    )

    def run(
        self,
        command: str,
        cwd: Optional[str] = None,
        timeout_seconds: Optional[int] = None,
        env: Optional[dict[str, str]] = None,
    ) -> ShellResult:
        import datetime
        started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        start_time = time.time()
        
        try:
            argv = self._command_to_argv(command)
            result = subprocess.run(
                argv,
                cwd=cwd,
                shell=False,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                env=env,
            )
            exit_code = result.returncode
            stdout = result.stdout
            stderr = result.stderr
        except subprocess.TimeoutExpired as e:
            exit_code = -1
            stdout = self._output_to_text(e.stdout)
            stderr = f"Command timed out after {timeout_seconds} seconds.\n" + self._output_to_text(e.stderr)
        except Exception as e:
            exit_code = -2
            stdout = ""
            stderr = str(e)
            
        end_time = time.time()
        completed_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        duration_ms = int((end_time - start_time) * 1000)
        
        return ShellResult(
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=duration_ms
        )

    def _command_to_argv(self, command: str) -> list[str]:
        if not isinstance(command, str) or not command.strip():
            raise ValueError("Command must be a non-empty string.")
        if any(pattern in command for pattern in self._SHELL_META_PATTERNS):
            raise ValueError("Shell operators are not allowed in acceptance commands.")
        argv = shlex.split(command, posix=True)
        if not argv:
            raise ValueError("Command must contain an executable.")
        executable = os.path.basename(argv[0])
        if executable not in self._ALLOWED_EXECUTABLES:
            raise ValueError(f"Executable is not allowed for acceptance commands: {executable}")
        return argv

    def _output_to_text(self, value: object) -> str:
        if value is None:
            return ""
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return str(value)
