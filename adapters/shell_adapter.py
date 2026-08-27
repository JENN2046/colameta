import subprocess
import time
from typing import Optional
from dataclasses import dataclass

from runner.acceptance_command_policy import (
    acceptance_command_to_execution_plan,
    open_acceptance_executable,
    trusted_acceptance_environment,
    verify_acceptance_execution_plan,
)


@dataclass
class ShellResult:
    exit_code: int
    stdout: str
    stderr: str
    started_at: str
    completed_at: str
    duration_ms: int


class ShellAdapter:
    def run(
        self,
        command: str,
        cwd: Optional[str] = None,
        timeout_seconds: Optional[int] = None,
        env: Optional[dict[str, str]] = None,
        project_root: Optional[str] = None,
    ) -> ShellResult:
        import datetime
        started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        start_time = time.time()
        
        try:
            plan = acceptance_command_to_execution_plan(
                command,
                project_root=project_root or cwd or "",
            )
            verify_acceptance_execution_plan(plan)
            with open_acceptance_executable(plan) as opened:
                result = subprocess.run(
                    list(opened.argv),
                    executable=opened.proc_path,
                    pass_fds=opened.pass_fds,
                    cwd=plan.project_root,
                    shell=False,
                    capture_output=True,
                    text=True,
                    timeout=timeout_seconds,
                    env=trusted_acceptance_environment(env),
                )
            exit_code = result.returncode
            stdout = result.stdout
            stderr = result.stderr
        except subprocess.TimeoutExpired as e:
            exit_code = -1
            stdout = self._output_to_text(e.stdout)
            stderr = (
                f"Command timed out after {timeout_seconds} seconds.\n"
                + self._output_to_text(e.stderr)
            )
        except Exception as e:
            exit_code = -2
            stdout = ""
            code = getattr(e, "code", None)
            stderr = f"{code}: {e}" if code else str(e)
            
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

    def _output_to_text(self, value: object) -> str:
        if value is None:
            return ""
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return str(value)
