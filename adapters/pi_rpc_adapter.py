import json
import os
import queue
import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from runner.executor_events import ExecutorEventStore


class PiRpcError(RuntimeError):
    def __init__(self, message: str, log_path: str | None = None):
        super().__init__(message)
        self.log_path = log_path


class PiNotFoundError(PiRpcError):
    pass


class PiUnauthorizedError(PiRpcError):
    pass


@dataclass
class PiRpcRunResult:
    command: list[str]
    cwd: str
    prompt_file: str
    log_path: str
    session_file_path: str
    started_at: str
    completed_at: str
    exit_code: int | None
    session_id: str | None = None
    session_file: str | None = None
    stdout_lines: list[str] = field(default_factory=list)
    stderr: str = ""
    summary: str | None = None
    summary_path: str | None = None
    token_usage: dict[str, Any] | None = None


class PiRpcAdapter:
    def __init__(self, executable: str = "pi", model: str | None = None):
        self.executable = executable
        self.model = model.strip() if isinstance(model, str) and model.strip() else None

    def execute_prompt(
        self,
        *,
        project_root: str,
        logs_dir: str,
        runner_dir: str,
        version: str,
        attempt: int,
        prompt: str,
        prompt_file: str,
        timeout_seconds: int = 3600,
        execution_mode: str = "normal",
        run_id: str | None = None,
        event_context: dict[str, Any] | None = None,
    ) -> PiRpcRunResult:
        pi_path = shutil.which(self.executable)
        if not pi_path:
            raise PiNotFoundError("未找到 pi 命令，请先安装 @mariozechner/pi-coding-agent。")

        os.makedirs(logs_dir, exist_ok=True)
        session_dir = os.path.join(runner_dir, "pi-sessions")
        os.makedirs(session_dir, exist_ok=True)
        safe_version = version.replace(os.sep, "-").replace("/", "-")
        log_suffix = "-fix-run-" if execution_mode == "fix" else "-run-"
        log_path = os.path.join(logs_dir, f"{safe_version}-pi{log_suffix}{attempt}.log")
        session_file_path = os.path.join(runner_dir, "pi-session.json")
        command = [pi_path, "--mode", "rpc", "--session-dir", session_dir]
        if self.model:
            command.extend(["--model", self.model])
        started_at = self._now()

        stdout_lines: list[str] = []
        stderr_chunks: list[str] = []
        responses: dict[str, dict[str, Any]] = {}
        events: list[dict[str, Any]] = []
        event_queue: queue.Queue[dict[str, Any]] = queue.Queue()
        condition = threading.Condition()
        process: subprocess.Popen[str] | None = None
        session_id = None
        session_file = None
        completed_at = started_at
        exit_code = None
        summary_text = None
        event_store = ExecutorEventStore(project_root) if run_id else None
        has_events = event_store is not None and bool(run_id)
        timed_out = False
        completed_successfully = False
        failure_event_emitted = False

        try:
            process = subprocess.Popen(
                command,
                cwd=project_root,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )

            if not process.stdin or not process.stdout or not process.stderr:
                raise PiRpcError("pi RPC 管道初始化失败。", log_path=log_path)

            if has_events:
                event_store.append(
                    run_id, "executor_started",
                    {"command": list(command), "cwd": project_root},
                    event_context,
                )

            def _store_aware_read_stdout():
                self._read_stdout(
                    process.stdout,
                    stdout_lines,
                    responses,
                    events,
                    event_queue,
                    condition,
                    event_store=event_store,
                    run_id=run_id,
                    event_context=event_context,
                )

            def _store_aware_read_stderr():
                self._read_stderr(
                    process.stderr,
                    stderr_chunks,
                    event_store=event_store,
                    run_id=run_id,
                    event_context=event_context,
                )

            stdout_thread = threading.Thread(target=_store_aware_read_stdout, daemon=True)
            stderr_thread = threading.Thread(target=_store_aware_read_stderr, daemon=True)
            stdout_thread.start()
            stderr_thread.start()

            state = self._send_and_wait(process, responses, condition, {"type": "get_state"}, "get_state")
            session_id, session_file = self._write_session_file(session_file_path, state.get("data"), started_at)

            self._send_and_wait(process, responses, condition, {"type": "prompt", "message": prompt}, "prompt")
            agent_end_seen = self._wait_for_agent_end(
                process,
                event_queue,
                timeout_seconds,
                log_path,
                event_store=event_store,
                run_id=run_id,
                event_context=event_context,
            )
            if not agent_end_seen:
                timed_out = True
                raise PiRpcError("pi 执行超时。", log_path=log_path)

            final_state = self._send_and_wait(process, responses, condition, {"type": "get_state"}, "get_state")
            final_session_id, final_session_file = self._write_session_file(session_file_path, final_state.get("data"), started_at)
            session_id = final_session_id or session_id
            session_file = final_session_file or session_file
            summary_text = self._extract_summary_from_events(events)
            if not summary_text:
                summary_text = f"执行器已完成，未返回可展示摘要。完整日志见：{log_path}"
            else:
                summary_text = self._truncate_summary(summary_text)
            completed_at = self._now()
            completed_successfully = True
        except PiRpcError as exc:
            completed_at = self._now()
            if exc.log_path is None:
                exc.log_path = log_path
            if has_events:
                event_store.append(
                    run_id,
                    "executor_failed",
                    {"returncode": -1, "error": str(exc), "timed_out": timed_out},
                    event_context,
                )
                failure_event_emitted = True
            raise
        except Exception as exc:
            completed_at = self._now()
            message = str(exc)
            if self._looks_unauthorized(message) or self._looks_unauthorized("".join(stderr_chunks)):
                if has_events:
                    event_store.append(
                        run_id,
                        "executor_failed",
                        {"returncode": -1, "error": "unauthorized", "timed_out": False},
                        event_context,
                    )
                    failure_event_emitted = True
                raise PiUnauthorizedError("pi 尚未登录或授权失效，请先在终端运行 pi 并完成登录。", log_path=log_path) from exc
            if has_events:
                event_store.append(
                    run_id,
                    "executor_failed",
                    {"returncode": -1, "error": str(exc), "timed_out": False},
                    event_context,
                )
                failure_event_emitted = True
            raise PiRpcError(message, log_path=log_path) from exc
        finally:
            if process is not None:
                exit_code = self._stop_process(process)
                completed_at = self._now()
                if has_events and (completed_successfully or not failure_event_emitted):
                    evt_type = "executor_finished" if completed_successfully and not timed_out else "executor_failed"
                    event_store.append(
                        run_id,
                        evt_type,
                        {
                            "returncode": exit_code,
                            "elapsed_seconds": round(
                                (datetime.now(timezone.utc).astimezone() - datetime.fromisoformat(started_at)).total_seconds(),
                                2,
                            ),
                            "timed_out": timed_out,
                        },
                        event_context,
                    )
                self._write_log(
                    log_path=log_path,
                    command=command,
                    cwd=project_root,
                    prompt_file=prompt_file,
                    started_at=started_at,
                    completed_at=completed_at,
                    exit_code=exit_code,
                    session_id=session_id,
                    session_file=session_file,
                    stdout_lines=stdout_lines,
                    stderr="".join(stderr_chunks),
                    execution_mode=execution_mode,
                )

        return PiRpcRunResult(
            command=command,
            cwd=project_root,
            prompt_file=prompt_file,
            log_path=log_path,
            session_file_path=session_file_path,
            started_at=started_at,
            completed_at=completed_at,
            exit_code=exit_code,
            session_id=session_id,
            session_file=session_file,
            stdout_lines=stdout_lines,
            stderr="".join(stderr_chunks),
            summary=summary_text,
            summary_path=None,
        )

    def _read_stdout(
        self,
        stream,
        stdout_lines: list[str],
        responses: dict[str, dict[str, Any]],
        events: list[dict[str, Any]],
        event_queue: queue.Queue[dict[str, Any]],
        condition: threading.Condition,
        event_store: ExecutorEventStore | None = None,
        run_id: str | None = None,
        event_context: dict[str, Any] | None = None,
    ) -> None:
        for raw_line in stream:
            line = raw_line.rstrip("\n")
            if line.endswith("\r"):
                line = line[:-1]
            stdout_lines.append(line)
            if event_store and run_id:
                try:
                    data = json.loads(line)
                    if isinstance(data, dict) and data.get("type") in ("tool_use", "tool_call", "extension_event"):
                        event_store.append(run_id, "executor_tool_event", {"event": data}, event_context)
                    else:
                        event_store.append(run_id, "executor_stdout", {"stdout": line}, event_context)
                except json.JSONDecodeError:
                    event_store.append(run_id, "executor_stdout", {"stdout": line}, event_context)
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            with condition:
                if data.get("type") == "response" and data.get("id"):
                    responses[data["id"]] = data
                    condition.notify_all()
                else:
                    events.append(data)
                    event_queue.put(data)
                    condition.notify_all()

    def _read_stderr(
        self,
        stream,
        stderr_chunks: list[str],
        event_store: ExecutorEventStore | None = None,
        run_id: str | None = None,
        event_context: dict[str, Any] | None = None,
    ) -> None:
        for chunk in stream:
            stderr_chunks.append(chunk)
            if event_store and run_id and chunk.strip():
                event_store.append(run_id, "executor_stderr", {"stderr": chunk}, event_context)

    def _send_and_wait(
        self,
        process: subprocess.Popen[str],
        responses: dict[str, dict[str, Any]],
        condition: threading.Condition,
        command: dict[str, Any],
        label: str,
    ) -> dict[str, Any]:
        if not process.stdin:
            raise PiRpcError("pi RPC stdin 不可用。")
        request_id = f"mvp-runner-{uuid.uuid4()}"
        payload = {"id": request_id, **command}
        process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        process.stdin.flush()

        deadline = time.monotonic() + 30
        with condition:
            while request_id not in responses:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise PiRpcError(f"等待 pi RPC 响应超时：{label}")
                condition.wait(timeout=remaining)

        response = responses[request_id]
        if not response.get("success"):
            error_message = response.get("error") or f"pi RPC 命令失败：{label}"
            if self._looks_unauthorized(error_message):
                raise PiUnauthorizedError("pi 尚未登录或授权失效，请先在终端运行 pi 并完成登录。")
            raise PiRpcError(error_message)
        return response

    def _wait_for_agent_end(
        self,
        process: subprocess.Popen[str],
        event_queue: queue.Queue[dict[str, Any]],
        timeout_seconds: int,
        log_path: str,
        event_store: ExecutorEventStore | None = None,
        run_id: str | None = None,
        event_context: dict[str, Any] | None = None,
    ) -> bool:
        deadline = time.monotonic() + timeout_seconds
        last_heartbeat = time.monotonic()
        while time.monotonic() < deadline:
            if process.poll() is not None:
                if process.returncode == 0:
                    raise PiRpcError(
                        "Pi 已退出但未返回 agent_end，执行结果无法确认。请查看日志并可手动按 V 验收。",
                        log_path=log_path,
                    )
                raise PiRpcError(f"pi 进程提前退出，退出码：{process.returncode}", log_path=log_path)
            now = time.monotonic()
            if event_store and run_id and now - last_heartbeat >= 30.0:
                event_store.append(
                    run_id, "heartbeat",
                    {"elapsed_seconds": round(now - (deadline - timeout_seconds), 2)},
                    event_context,
                )
                last_heartbeat = now
            try:
                event = event_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            if event.get("type") == "agent_end":
                return True
            if event.get("type") == "extension_error":
                raise PiRpcError(str(event.get("error") or "pi extension error"), log_path=log_path)
            if self._event_has_auth_error(event):
                raise PiUnauthorizedError("pi 尚未登录或授权失效，请先在终端运行 pi 并完成登录。", log_path=log_path)
        return False

    def _stop_process(self, process: subprocess.Popen[str]) -> int | None:
        if process.stdin and not process.stdin.closed:
            try:
                process.stdin.close()
            except OSError:
                pass
        try:
            return process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.terminate()
        try:
            return process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            return process.wait(timeout=5)

    def _write_session_file(self, path: str, data: Any, timestamp: str) -> tuple[str | None, str | None]:
        if not isinstance(data, dict):
            return None, None
        session_id = data.get("sessionId")
        session_file = data.get("sessionFile")
        payload = {
            "updated_at": timestamp,
            "session_id": session_id,
            "session_file": session_file,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.write("\n")
        return session_id, session_file

    def _write_log(
        self,
        *,
        log_path: str,
        command: list[str],
        cwd: str,
        prompt_file: str,
        started_at: str,
        completed_at: str,
        exit_code: int | None,
        session_id: str | None,
        session_file: str | None,
        stdout_lines: list[str],
        stderr: str,
        execution_mode: str = "normal",
    ) -> None:
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("# Pi RPC Execution Log\n")
            f.write(f"execution_mode: {execution_mode}\n")
            f.write(f"started_at: {started_at}\n")
            f.write(f"completed_at: {completed_at}\n")
            f.write(f"command: {' '.join(command)}\n")
            f.write(f"cwd: {cwd}\n")
            f.write(f"prompt_file: {prompt_file}\n")
            f.write(f"exit_code: {exit_code}\n")
            f.write(f"session_id: {session_id or ''}\n")
            f.write(f"session_file: {session_file or ''}\n")
            f.write("\n## stdout/events\n")
            for line in stdout_lines:
                f.write(line + "\n")
            f.write("\n## stderr\n")
            f.write(stderr or "")

    def _event_has_auth_error(self, event: dict[str, Any]) -> bool:
        return self._looks_unauthorized(json.dumps(event, ensure_ascii=False))

    def _looks_unauthorized(self, text: str) -> bool:
        lowered = text.lower()
        patterns = (
            "unauthorized",
            "not logged in",
            "authorization",
            "authentication",
            "auth failed",
            "invalid api key",
            "api key",
            "401",
            "403",
        )
        return any(pattern in lowered for pattern in patterns)

    def _extract_summary_from_events(self, events: list[dict[str, Any]]) -> str | None:
        for event in reversed(events):
            if not self._is_assistant_like_event(event):
                continue
            for key in ("text", "message", "content", "delta"):
                text = self._extract_summary_text(event.get(key))
                if text:
                    return text
        return None

    def _is_assistant_like_event(self, event: dict[str, Any]) -> bool:
        event_type = str(event.get("type", "")).lower()
        role = str(event.get("role", "")).lower()
        if role == "assistant":
            return True
        keywords = ("assistant", "final", "message")
        return any(keyword in event_type for keyword in keywords)

    def _extract_summary_text(self, value: Any) -> str | None:
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
                text = self._extract_summary_text(item)
                if text:
                    parts.append(text)
            if parts:
                return "\n".join(parts).strip()
            return None

        if isinstance(value, dict):
            role = str(value.get("role", "")).lower()
            if role and role != "assistant":
                return None
            for key in ("text", "content", "message", "delta"):
                if key not in value:
                    continue
                text = self._extract_summary_text(value.get(key))
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
