import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Any

from runner.executor_events import ExecutorEventStore


_HEARTBEAT_INTERVAL = 30.0
_TERMINATE_WAIT = 5.0
_KILL_WAIT = 5.0


@dataclass
class ExecutorProcessResult:
    stdout: str = ""
    stderr: str = ""
    returncode: int = -1
    elapsed_seconds: float = 0.0
    timed_out: bool = False


class ExecutorProcessSupervisor:
    def run_process(
        self,
        command: list[str],
        cwd: str,
        input_text: str | None = None,
        timeout_seconds: int = 3600,
        event_store: ExecutorEventStore | None = None,
        run_id: str | None = None,
        event_context: dict[str, Any] | None = None,
        heartbeat_interval: float = _HEARTBEAT_INTERVAL,
        display_command: list[str] | None = None,
    ) -> ExecutorProcessResult:
        started_at = time.monotonic()
        has_events = event_store is not None and bool(run_id)

        if has_events:
            event_command = display_command if display_command is not None else list(command)
            event_store.append(
                run_id, "executor_started",
                {"command": event_command, "cwd": cwd},
                event_context,
            )

        proc = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        stdout_lines: list[str] = []
        stderr_lines: list[str] = []
        def _reader(stream, lines, event_type):
            try:
                for raw_line in iter(stream.readline, ""):
                    lines.append(raw_line)
                    if has_events:
                        event_store.append(
                            run_id, event_type,
                            {"stdout" if event_type == "executor_stdout" else "stderr": raw_line},
                            event_context,
                        )
            finally:
                stream.close()

        stdout_thread = threading.Thread(
            target=_reader,
            args=(proc.stdout, stdout_lines, "executor_stdout"),
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=_reader,
            args=(proc.stderr, stderr_lines, "executor_stderr"),
            daemon=True,
        )

        stdout_thread.start()
        stderr_thread.start()

        if input_text:
            try:
                proc.stdin.write(input_text)
            finally:
                proc.stdin.close()
        else:
            proc.stdin.close()

        deadline = time.monotonic() + timeout_seconds
        last_heartbeat = time.monotonic()
        timed_out = False

        while time.monotonic() < deadline:
            if proc.poll() is not None:
                break
            time.sleep(0.1)
            now = time.monotonic()
            if has_events and now - last_heartbeat >= heartbeat_interval:
                event_store.append(
                    run_id, "heartbeat",
                    {"elapsed_seconds": round(now - started_at, 2)},
                    event_context,
                )
                last_heartbeat = now
        else:
            timed_out = True
            proc.terminate()
            try:
                proc.wait(timeout=_TERMINATE_WAIT)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=_KILL_WAIT)

        proc.wait()
        stdout_thread.join(timeout=5)
        stderr_thread.join(timeout=5)

        stdout = "".join(stdout_lines)
        stderr = "".join(stderr_lines)
        returncode = proc.returncode if proc.returncode is not None else -1
        elapsed = time.monotonic() - started_at

        if has_events:
            event_type = "executor_finished" if returncode == 0 and not timed_out else "executor_failed"
            event_store.append(
                run_id, event_type,
                {
                    "returncode": returncode,
                    "elapsed_seconds": round(elapsed, 2),
                    "timed_out": timed_out,
                    "stdout_preview": stdout[-500:] if stdout else "",
                    "stderr_preview": stderr[-500:] if stderr else "",
                },
                event_context,
            )

        return ExecutorProcessResult(
            stdout=stdout,
            stderr=stderr,
            returncode=returncode,
            elapsed_seconds=round(elapsed, 2),
            timed_out=timed_out,
        )
