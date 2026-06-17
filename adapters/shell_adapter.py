import subprocess
import time
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
            result = subprocess.run(
                command,
                cwd=cwd,
                shell=True,
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
            stdout = e.stdout.decode('utf-8', errors='replace') if e.stdout else ""
            stderr = f"Command timed out after {timeout_seconds} seconds.\n" + (e.stderr.decode('utf-8', errors='replace') if e.stderr else "")
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
