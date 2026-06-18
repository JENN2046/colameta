import json
import os
import shutil
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

from adapters.opencode_types import OpenCodeCliError
from runner.executor_events import ExecutorEventStore
from runner.git_diff_helper import (
    collect_git_diff_name_paths,
    filter_business_diff_paths,
)
from runner.sensitive_redaction import redact_sensitive_text
from runner.token_usage import normalize_token_usage


class OpenCodeServerError(OpenCodeCliError):
    def __init__(self, message: str, log_path: str | None = None):
        super().__init__(message)
        self.log_path = log_path


class OpenCodeServerNotFoundError(OpenCodeServerError):
    pass


class OpenCodeServerStartupError(OpenCodeServerError):
    pass


class OpenCodeServerUnauthorizedError(OpenCodeServerError):
    pass


class OpenCodeServerAPIError(OpenCodeServerError):
    def __init__(self, message: str, status_code: int = 0, log_path: str | None = None):
        super().__init__(message, log_path=log_path)
        self.status_code = status_code


class OpenCodeModelQuotaExhaustedError(OpenCodeServerAPIError):
    terminal_reason = "executor_model_quota_exhausted"
    error_code = "EXECUTOR_MODEL_QUOTA_EXHAUSTED"


class OpenCodeProviderTerminalError(OpenCodeServerAPIError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int = 0,
        log_path: str | None = None,
        error_code: str = "EXECUTOR_PROVIDER_ERROR",
        terminal_reason: str = "executor_provider_error",
        provider_status: str = "",
        evidence: dict[str, Any] | None = None,
    ):
        super().__init__(message, status_code=status_code, log_path=log_path)
        self.error_code = error_code
        self.terminal_reason = terminal_reason
        self.provider_status = provider_status
        self.evidence = evidence or {}


class OpenCodeProviderRetryError(OpenCodeProviderTerminalError):
    pass


class OpenCodeServerStalledError(OpenCodeProviderTerminalError):
    pass


class OpenCodeProjectMismatchError(OpenCodeServerError):
    pass


MODEL_QUOTA_EXHAUSTED_MESSAGE = "执行器模型额度或 token 配额已耗尽。请更换模型、等待额度恢复，或检查执行器账号和配置。"
OPENCODE_STALLED_MESSAGE = "OpenCode 长时间停在发送提示词阶段，未收到 provider response、message part 或业务进展，已终结为 stalled executor failure。"
MODEL_QUOTA_EXHAUSTED_MARKERS = (
    "model quota",
    "token quota",
    "quota exceeded",
    "insufficient quota",
    "insufficient credits",
    "insufficient credit",
    "out of credits",
    "usage limit",
    "rate limit",
    "too many requests",
    "resource exhausted",
    "resources exhausted",
    "free usage exceeded",
    "free_tier_limit",
    "free limit reached",
    "429",
)


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def _redact_sensitive_text(text: str) -> str:
    return redact_sensitive_text(text, replacement_token="<redacted>", preserve_token_prefix=True)


def _collect_git_diff_names(project_root: str) -> list[str]:
    return collect_git_diff_name_paths(project_root, timeout_seconds=10)


def _filter_business_diff(files: list[str]) -> list[str]:
    return filter_business_diff_paths(files)


def _write_log(
    *,
    log_path: str,
    port: int,
    cwd: str,
    prompt_file: str,
    execution_mode: str,
    started_at: str,
    completed_at: str,
    stdout: str,
    stderr: str,
    exit_code: int,
    attempted_resume: bool = False,
    used_resume: bool = False,
    command_shape: str | None = None,
    pre_business_diff_files: list[str] | None = None,
    post_business_diff_files: list[str] | None = None,
    no_business_diff: bool = False,
) -> None:
    redacted_stdout = _redact_sensitive_text(stdout)
    redacted_stderr = _redact_sensitive_text(stderr)
    with open(log_path, "w", encoding="utf-8") as f:
        f.write("# OpenCode Server Execution Log\n")
        f.write(f"execution_mode: {execution_mode}\n")
        if command_shape:
            f.write(f"command_shape: {command_shape}\n")
        f.write(f"attempted_resume: {str(attempted_resume).lower()}\n")
        f.write(f"used_resume: {str(used_resume).lower()}\n")
        f.write(f"started_at: {started_at}\n")
        f.write(f"completed_at: {completed_at}\n")
        f.write(f"server_port: {port}\n")
        f.write(f"cwd: {cwd}\n")
        f.write(f"prompt_file: {prompt_file}\n")
        f.write(f"exit_code: {exit_code}\n")
        f.write("\n## business diff diagnostics\n")
        f.write(f"pre_business_diff_files: {','.join(pre_business_diff_files) if pre_business_diff_files else '(none)'}\n")
        f.write(f"post_business_diff_files: {','.join(post_business_diff_files) if post_business_diff_files else '(none)'}\n")
        f.write(f"no_business_diff: {str(no_business_diff).lower()}\n")
        f.write("\n## stdout\n")
        f.write(redacted_stdout)
        if redacted_stdout and not redacted_stdout.endswith("\n"):
            f.write("\n")
        f.write("\n## stderr\n")
        f.write(redacted_stderr)
        if redacted_stderr and not redacted_stderr.endswith("\n"):
            f.write("\n")


def _truncate_summary(text: str, max_length: int = 1200) -> str:
    stripped = text.strip()
    if len(stripped) <= max_length:
        return stripped
    return stripped[:max_length] + "\n...(已截断)"


def _http_request(
    url: str,
    method: str = "GET",
    data: dict | None = None,
    timeout: int = 30,
) -> tuple[int, str]:
    headers = {"Content-Type": "application/json"}
    body = json.dumps(data).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace") if e.fp else ""
        return e.code, error_body
    except (TimeoutError, socket.timeout, urllib.error.URLError, OSError) as e:
        return 599, f"request_failed:{e.__class__.__name__}"


def _append_live_event(
    event_store: ExecutorEventStore | None,
    run_id: str | None,
    event_type: str,
    data: dict[str, Any] | None = None,
    event_context: dict[str, Any] | None = None,
    *,
    phase: str = "",
    message: str = "",
    level: str = "info",
) -> None:
    if event_store is None or not run_id:
        return
    ctx = dict(event_context or {})
    ctx["run_id"] = str(ctx.get("run_id") or run_id)
    if phase:
        ctx["phase"] = phase
    if message:
        ctx["message"] = message
    ctx["level"] = str(ctx.get("level") or level)
    event_store.append(run_id, event_type, data=data or {}, event_context=ctx)


def _extract_message_text(response_body: str) -> str:
    try:
        data = json.loads(response_body)
    except (json.JSONDecodeError, ValueError):
        return response_body
    if not isinstance(data, dict):
        return response_body
    parts = data.get("parts")
    if isinstance(parts, list):
        text_parts: list[str] = []
        for p in parts:
            if isinstance(p, dict) and p.get("type") == "text":
                text = p.get("text", "")
                if isinstance(text, str) and text.strip():
                    text_parts.append(text)
        if text_parts:
            return "\n".join(text_parts)
    info = data.get("info")
    if isinstance(info, dict):
        for key in ("text", "message", "content"):
            val = info.get(key)
            if isinstance(val, str) and val.strip():
                return val
    if len(response_body) > 1000:
        return response_body[:1000] + "\n...(已截断)"
    return response_body


def _looks_model_quota_exhausted(*texts: str | None) -> bool:
    combined = "\n".join(
        _redact_sensitive_text(text)
        for text in texts
        if isinstance(text, str) and text.strip()
    ).lower()
    if not combined:
        return False
    return any(marker in combined for marker in MODEL_QUOTA_EXHAUSTED_MARKERS)


class OpenCodeServerAdapter:
    def __init__(
        self,
        executable: str = "opencode",
        model: str | None = None,
        startup_timeout: int = 60,
        health_check_interval: float = 1.0,
        prompt_status_poll_interval: float = 2.0,
        prompt_stall_timeout: int = 180,
    ):
        self.executable = executable
        self.model = model.strip() if isinstance(model, str) and model.strip() else None
        self.startup_timeout = startup_timeout
        self.health_check_interval = health_check_interval
        self.prompt_status_poll_interval = max(0.2, float(prompt_status_poll_interval))
        self.prompt_stall_timeout = max(5, int(prompt_stall_timeout))

    def _start_server(self, project_root: str, logs_dir: str) -> tuple[int, subprocess.Popen, str]:
        opencode_path = shutil.which(self.executable)
        if not opencode_path:
            raise OpenCodeServerNotFoundError("未找到 opencode 命令，请先安装。")

        port = _find_free_port()
        os.makedirs(logs_dir, exist_ok=True)
        server_log = os.path.join(logs_dir, "opencode-server.log")

        proc = subprocess.Popen(
            [opencode_path, "serve", "--port", str(port)],
            stdout=open(server_log, "a", encoding="utf-8"),
            stderr=subprocess.STDOUT,
            cwd=project_root,
        )

        return port, proc, server_log

    def _wait_for_health(self, port: int, timeout: int | None = None) -> None:
        deadline = time.time() + (timeout or self.startup_timeout)
        last_error = ""
        while time.time() < deadline:
            try:
                status, body = _http_request(f"http://127.0.0.1:{port}/global/health", timeout=5)
                if status == 200:
                    try:
                        data = json.loads(body)
                        health_error = data.get("error")
                        if health_error:
                            last_error = str(health_error)
                        elif data.get("healthy") is True:
                            return
                    except (json.JSONDecodeError, ValueError):
                        pass
            except (urllib.error.URLError, ConnectionRefusedError, OSError) as e:
                last_error = str(e)
            time.sleep(self.health_check_interval)
        raise OpenCodeServerStartupError(
            f"OpenCode server 启动超时（{self.startup_timeout}s），最后错误：{last_error}"
        )

    def _verify_project_context(self, port: int, project_root: str) -> dict[str, Any]:
        abs_project = os.path.abspath(project_root)

        status, body = _http_request(f"http://127.0.0.1:{port}/path", timeout=10)
        if status == 200:
            try:
                data = json.loads(body)
                server_path = data.get("path") or ""
                if server_path:
                    server_abs = os.path.abspath(server_path)
                    if server_abs != abs_project:
                        raise OpenCodeProjectMismatchError(
                            f"服务器工作目录不匹配：期望 {abs_project}，实际 {server_abs}"
                        )
                    return {"verified": True, "source": "/path", "path": server_abs}
            except (json.JSONDecodeError, ValueError):
                pass

        status2, body2 = _http_request(f"http://127.0.0.1:{port}/project/current", timeout=10)
        if status2 == 200:
            try:
                data2 = json.loads(body2)
                server_path = data2.get("path") or data2.get("root") or data2.get("directory") or ""
                if server_path:
                    server_abs = os.path.abspath(server_path)
                    if server_abs != abs_project:
                        raise OpenCodeProjectMismatchError(
                            f"服务器项目路径不匹配：期望 {abs_project}，实际 {server_abs}"
                        )
                    return {"verified": True, "source": "/project/current", "path": server_abs}
            except (json.JSONDecodeError, ValueError):
                pass
        return {
            "verified": False,
            "source": "unavailable",
            "path": "",
            "warning": f"OpenCode server 未暴露可确认项目目录；Runner 已在 cwd={abs_project} 启动 server，继续执行。",
        }

    def _create_session(
        self,
        port: int,
        prompt: str,
        resume_session_id: str | None = None,
    ) -> dict:
        if resume_session_id:
            session_data = self._try_resume_session(port, resume_session_id)
            if session_data:
                return session_data

        title = prompt[:200] if prompt else "Runner session"
        url = f"http://127.0.0.1:{port}/session"
        payload = {"title": title}
        status, body = _http_request(url, method="POST", data=payload, timeout=30)
        if status == 201 or status == 200:
            data = json.loads(body) if body else {}
            session_id = data.get("id") or data.get("session_id") or ""
            return {
                "session_id": session_id,
                "conversation_id": session_id,
                "created": True,
                "resumed": False,
            }
        raise OpenCodeServerAPIError(
            f"创建会话失败（HTTP {status}）：{body[:500]}",
            status_code=status,
        )

    def _try_resume_session(self, port: int, session_id: str) -> dict | None:
        try:
            status, body = _http_request(
                f"http://127.0.0.1:{port}/session/{session_id}",
                timeout=10,
            )
            if status == 200:
                return {
                    "session_id": session_id,
                    "conversation_id": session_id,
                    "created": False,
                    "resumed": True,
                }
        except Exception:
            pass
        return None

    def _extract_step_finish_tokens_from_body(
        self, body: str
    ) -> tuple[dict[str, Any] | None, str | None]:
        try:
            data = json.loads(body)
        except (json.JSONDecodeError, ValueError):
            return None, None
        if not isinstance(data, dict):
            return None, None
        message_id = data.get("id")
        if not isinstance(message_id, str) or not message_id:
            info = data.get("info")
            message_id = info.get("id") if isinstance(info, dict) else None
        if not isinstance(message_id, str) or not message_id:
            message_id = None
        parts = data.get("parts")
        if not isinstance(parts, list):
            return None, message_id
        latest_tokens: dict[str, Any] | None = None
        for part in parts:
            if not isinstance(part, dict):
                continue
            if part.get("type") != "step-finish":
                continue
            tokens = part.get("tokens")
            if isinstance(tokens, dict) and tokens:
                latest_tokens = tokens
        return latest_tokens, message_id

    @staticmethod
    def _step_finish_tokens_to_usage(tokens: dict[str, Any]) -> dict[str, Any]:
        usage: dict[str, Any] = {}
        if isinstance(tokens.get("input"), (int, float)):
            usage["input_tokens"] = int(tokens["input"])
        if isinstance(tokens.get("output"), (int, float)):
            usage["output_tokens"] = int(tokens["output"])
        if isinstance(tokens.get("reasoning"), (int, float)):
            usage["reasoning_output_tokens"] = int(tokens["reasoning"])
        if isinstance(tokens.get("total"), (int, float)):
            usage["total_tokens"] = int(tokens["total"])
        cache = tokens.get("cache")
        if isinstance(cache, dict):
            if isinstance(cache.get("read"), (int, float)):
                usage["cache_read_tokens"] = int(cache["read"])
            if isinstance(cache.get("write"), (int, float)):
                usage["cache_write_tokens"] = int(cache["write"])
        return usage

    def _fetch_message_detail(
        self, port: int, session_id: str, message_id: str, timeout_seconds: int = 5
    ) -> dict[str, Any] | None:
        url = f"http://127.0.0.1:{port}/session/{session_id}/message/{message_id}"
        status, body = _http_request(url, method="GET", timeout=timeout_seconds)
        if status != 200:
            return None
        step_finish_tokens, _ = self._extract_step_finish_tokens_from_body(body)
        if step_finish_tokens:
            return self._step_finish_tokens_to_usage(step_finish_tokens)
        return None

    def _fetch_json_endpoint(self, port: int, path: str, timeout_seconds: int = 2) -> tuple[int, dict[str, Any] | list[Any] | None, str]:
        status, body = _http_request(f"http://127.0.0.1:{port}{path}", method="GET", timeout=timeout_seconds)
        try:
            data = json.loads(body) if body else None
        except (json.JSONDecodeError, ValueError):
            data = None
        return status, data, body

    def _fetch_server_events(self, port: int, timeout_seconds: int = 1) -> list[dict[str, Any]]:
        status, body = _http_request(f"http://127.0.0.1:{port}/event", method="GET", timeout=timeout_seconds)
        if status != 200 or not body:
            return []
        events: list[dict[str, Any]] = []
        current_event = ""
        for raw_line in body.splitlines():
            line = raw_line.strip()
            if not line:
                current_event = ""
                continue
            if line.startswith("event:"):
                current_event = line.split(":", 1)[1].strip()
                continue
            if not line.startswith("data:"):
                continue
            payload = line.split(":", 1)[1].strip()
            try:
                data = json.loads(payload)
            except (json.JSONDecodeError, ValueError):
                data = {"raw": payload}
            if isinstance(data, dict):
                if current_event and "event" not in data and "type" not in data:
                    data["event"] = current_event
                events.append(data)
        return events

    def _extract_error_texts(self, value: Any) -> list[str]:
        texts: list[str] = []
        if isinstance(value, str):
            if value.strip():
                texts.append(value.strip())
            return texts
        if isinstance(value, list):
            for item in value:
                texts.extend(self._extract_error_texts(item))
            return texts
        if not isinstance(value, dict):
            return texts

        for key, item in value.items():
            key_text = str(key)
            if key_text == "parts":
                continue
            if key_text == "action" and isinstance(item, dict):
                for action_key in ("reason", "title", "message", "label"):
                    action_value = item.get(action_key)
                    if isinstance(action_value, str) and action_value.strip():
                        texts.append(action_value.strip())
                texts.extend(self._extract_error_texts(item))
                continue
            if key_text in {"error", "errors"}:
                texts.extend(self._extract_error_texts(item))
                continue
            if key_text in {
                "message", "responseBody", "body", "detail", "reason", "statusText",
            }:
                if isinstance(item, str) and item.strip():
                    texts.append(item.strip())
                elif isinstance(item, dict):
                    texts.extend(self._extract_error_texts(item))
                continue
            if key_text in {"status_code", "statusCode"}:
                if isinstance(item, str) and item.strip():
                    texts.append(item.strip())
                elif isinstance(item, (int, float)):
                    texts.append(str(int(item)))
                continue
            if key_text in {"type", "status", "state"}:
                if isinstance(item, str) and item.strip().lower() in {"retry", "error", "failed", "failure"}:
                    texts.append(item.strip())
                continue
            if isinstance(item, (dict, list)):
                texts.extend(self._extract_error_texts(item))

        parts = value.get("parts")
        if isinstance(parts, list):
            for part in parts:
                if not isinstance(part, dict):
                    continue
                part_type = str(part.get("type") or "").lower()
                if "error" in part_type or "retry" in part_type:
                    texts.extend(self._extract_error_texts(part))
        return texts

    def _extract_response_header_keys(self, value: Any) -> list[str]:
        if isinstance(value, list):
            for item in value:
                keys = self._extract_response_header_keys(item)
                if keys:
                    return keys
            return []
        if not isinstance(value, dict):
            return []
        headers = value.get("responseHeaders")
        if isinstance(headers, dict):
            return sorted(str(key) for key in headers.keys() if isinstance(key, str))
        for item in value.values():
            keys = self._extract_response_header_keys(item)
            if keys:
                return keys
        return []

    def _extract_terminal_evidence(
        self,
        *,
        source: str,
        status_code: int,
        data: Any,
        body: str = "",
    ) -> dict[str, Any] | None:
        provider_status = ""
        if isinstance(data, dict):
            raw_status = data.get("status") or data.get("state")
            if isinstance(raw_status, str):
                provider_status = raw_status.strip().lower()
        error_texts = self._extract_error_texts(data)
        if body and status_code >= 400:
            error_texts.append(body[:1000])
        combined = "\n".join(error_texts)
        combined_lower = combined.lower()
        response_header_keys = self._extract_response_header_keys(data)
        if _looks_model_quota_exhausted(combined, provider_status):
            return {
                "source": source,
                "error_code": "EXECUTOR_MODEL_QUOTA_EXHAUSTED",
                "terminal_reason": "executor_model_quota_exhausted",
                "provider_status": provider_status or ("http_%s" % status_code if status_code else ""),
                "message": MODEL_QUOTA_EXHAUSTED_MESSAGE,
                "summary": MODEL_QUOTA_EXHAUSTED_MESSAGE,
                "status_code": status_code,
                "response_headers_present": bool(response_header_keys),
                "response_header_keys": response_header_keys,
            }
        if provider_status == "retry" or "retry" in combined_lower:
            return {
                "source": source,
                "error_code": "EXECUTOR_PROVIDER_RETRY",
                "terminal_reason": "executor_provider_retry",
                "provider_status": "retry",
                "message": "OpenCode server 进入 retry 状态，未产生可验收输出，已终结执行器运行。",
                "summary": "retry",
                "status_code": status_code,
            }
        if error_texts or provider_status in {"error", "failed", "failure"} or (status_code >= 400 and bool(body.strip())):
            summary = _truncate_summary(_redact_sensitive_text(combined or body or provider_status), max_length=500)
            return {
                "source": source,
                "error_code": "EXECUTOR_PROVIDER_ERROR",
                "terminal_reason": "executor_provider_error",
                "provider_status": provider_status or ("http_%s" % status_code if status_code else ""),
                "message": f"OpenCode server 返回 provider error：{summary}",
                "summary": summary,
                "status_code": status_code,
                "response_headers_present": bool(response_header_keys),
                "response_header_keys": response_header_keys,
            }
        return None

    def _collect_prompt_wait_facts(
        self,
        port: int,
        session_id: str,
    ) -> dict[str, Any]:
        facts: dict[str, Any] = {
            "status": {},
            "session": {},
            "events": [],
            "terminal_evidence": None,
            "meaningful_progress": False,
        }
        status_code, status_data, status_body = self._fetch_json_endpoint(port, "/session/status", timeout_seconds=2)
        if isinstance(status_data, dict):
            facts["status"] = status_data
            facts["meaningful_progress"] = True
        evidence = self._extract_terminal_evidence(
            source="/session/status",
            status_code=status_code,
            data=status_data,
            body=status_body,
        )
        if evidence:
            facts["terminal_evidence"] = evidence
            return facts

        sess_code, sess_data, sess_body = self._fetch_json_endpoint(port, f"/session/{session_id}", timeout_seconds=2)
        if isinstance(sess_data, dict):
            facts["session"] = sess_data
            if sess_data.get("error") or sess_data.get("status"):
                facts["meaningful_progress"] = True
        evidence = self._extract_terminal_evidence(
            source=f"/session/{session_id}",
            status_code=sess_code,
            data=sess_data,
            body=sess_body,
        )
        if evidence:
            facts["terminal_evidence"] = evidence
            return facts

        events = self._fetch_server_events(port, timeout_seconds=1)
        facts["events"] = events[-10:]
        for event in events[-10:]:
            event_type = str(event.get("type") or event.get("event") or "").lower()
            if event_type and event_type != "heartbeat":
                facts["meaningful_progress"] = True
            evidence = self._extract_terminal_evidence(
                source="/event",
                status_code=200,
                data=event,
                body="",
            )
            if evidence:
                facts["terminal_evidence"] = evidence
                return facts
            if "retry" in event_type:
                facts["terminal_evidence"] = {
                    "source": "/event",
                    "error_code": "EXECUTOR_PROVIDER_RETRY",
                    "terminal_reason": "executor_provider_retry",
                    "provider_status": "retry",
                    "message": "OpenCode server event 显示 retry，未产生可验收输出，已终结执行器运行。",
                    "summary": "retry",
                    "status_code": 200,
                }
                return facts
        return facts

    def _raise_terminal_evidence(self, evidence: dict[str, Any]) -> None:
        error_code = str(evidence.get("error_code") or "EXECUTOR_PROVIDER_ERROR")
        if error_code == "EXECUTOR_MODEL_QUOTA_EXHAUSTED":
            raise OpenCodeModelQuotaExhaustedError(
                MODEL_QUOTA_EXHAUSTED_MESSAGE,
                status_code=int(evidence.get("status_code") or 0),
            )
        cls: type[OpenCodeProviderTerminalError]
        if error_code == "EXECUTOR_PROVIDER_RETRY":
            cls = OpenCodeProviderRetryError
        else:
            cls = OpenCodeProviderTerminalError
        raise cls(
            str(evidence.get("message") or "OpenCode server 返回 provider terminal error。"),
            status_code=int(evidence.get("status_code") or 0),
            error_code=error_code,
            terminal_reason=str(evidence.get("terminal_reason") or "executor_provider_error"),
            provider_status=str(evidence.get("provider_status") or ""),
            evidence=evidence,
        )

    def _send_prompt_to_session(
        self,
        port: int,
        session_id: str,
        prompt: str,
        timeout_seconds: int,
        event_store: ExecutorEventStore | None = None,
        run_id: str | None = None,
        event_context: dict[str, Any] | None = None,
    ) -> tuple[str, str, int, dict[str, Any] | None, str | None]:
        url = f"http://127.0.0.1:{port}/session/{session_id}/message"
        payload = {
            "parts": [
                {"type": "text", "text": prompt},
            ],
        }
        model_payload = self._model_payload()
        if model_payload:
            payload["model"] = model_payload
        response_box: dict[str, Any] = {}

        def _post_message() -> None:
            response_box["response"] = _http_request(url, method="POST", data=payload, timeout=timeout_seconds)

        post_thread = threading.Thread(target=_post_message, daemon=True)
        post_thread.start()
        deadline = time.time() + max(1, int(timeout_seconds))
        last_business_progress_at = time.time()
        last_fact_signature = ""
        while post_thread.is_alive():
            now = time.time()
            if now >= deadline:
                raise OpenCodeServerStalledError(
                    "OpenCode prompt send timed out before server returned a message response.",
                    status_code=599,
                    error_code="EXECUTOR_STALLED",
                    terminal_reason="executor_stalled_without_provider_error",
                    provider_status="timeout",
                    evidence={"source": "prompt_send_timeout"},
                )
            facts = self._collect_prompt_wait_facts(port, session_id)
            evidence = facts.get("terminal_evidence")
            if isinstance(evidence, dict):
                _append_live_event(
                    event_store, run_id, "executor_tool_event",
                    {"stage": "provider_terminal_evidence", **evidence},
                    event_context,
                    phase="server",
                    message="OpenCode provider terminal evidence",
                    level="error",
                )
                self._raise_terminal_evidence(evidence)
            fact_signature = json.dumps({
                "status": facts.get("status"),
                "session": facts.get("session"),
                "events": facts.get("events"),
            }, sort_keys=True, ensure_ascii=False, default=str)[:1000]
            if facts.get("meaningful_progress") and fact_signature and fact_signature != last_fact_signature:
                last_fact_signature = fact_signature
                last_business_progress_at = now
                _append_live_event(
                    event_store, run_id, "executor_tool_event",
                    {
                        "stage": "server_wait_fact",
                        "session_status": facts.get("status"),
                        "session": facts.get("session"),
                        "event_count": len(facts.get("events") or []),
                    },
                    event_context,
                    phase="server",
                    message="OpenCode server wait fact observed",
                )
            if now - last_business_progress_at >= self.prompt_stall_timeout:
                evidence = {
                    "source": "prompt_send_monitor",
                    "error_code": "EXECUTOR_STALLED",
                    "terminal_reason": "executor_stalled_without_provider_error",
                    "provider_status": "stalled",
                    "message": OPENCODE_STALLED_MESSAGE,
                    "summary": "prompt_send_started_without_response_or_message_part",
                    "status_code": 599,
                }
                _append_live_event(
                    event_store, run_id, "executor_tool_event",
                    {"stage": "prompt_send_stalled", **evidence},
                    event_context,
                    phase="server",
                    message="OpenCode prompt send stalled",
                    level="error",
                )
                raise OpenCodeServerStalledError(
                    OPENCODE_STALLED_MESSAGE,
                    status_code=599,
                    error_code="EXECUTOR_STALLED",
                    terminal_reason="executor_stalled_without_provider_error",
                    provider_status="stalled",
                    evidence=evidence,
                )
            post_thread.join(timeout=min(self.prompt_status_poll_interval, max(0.1, deadline - now)))

        status, body = response_box.get("response", (599, "request_failed:missing_response"))
        if status == 200 or status == 201:
            result_text = _extract_message_text(body)
            step_finish_tokens, message_id = self._extract_step_finish_tokens_from_body(body)
            server_usage = (
                self._step_finish_tokens_to_usage(step_finish_tokens)
                if step_finish_tokens
                else None
            )
            if _looks_model_quota_exhausted(result_text, body):
                raise OpenCodeModelQuotaExhaustedError(
                    MODEL_QUOTA_EXHAUSTED_MESSAGE,
                    status_code=status,
                )
            try:
                body_data = json.loads(body) if body and body.strip().startswith(("{", "[")) else {"message": result_text}
            except (json.JSONDecodeError, ValueError):
                body_data = {"message": result_text}
            body_evidence = self._extract_terminal_evidence(
                source="/session/:id/message response",
                status_code=status,
                data=body_data,
                body=body,
            )
            if body_evidence:
                self._raise_terminal_evidence(body_evidence)
            return result_text, "", 0, server_usage, message_id
        evidence = self._extract_terminal_evidence(
            source="/session/:id/message response",
            status_code=status,
            data=None,
            body=body,
        )
        if evidence:
            self._raise_terminal_evidence(evidence)
        raise OpenCodeServerAPIError(
            f"发送提示词失败（HTTP {status}）：{body[:500]}",
            status_code=status,
        )

    def _model_payload(self) -> dict[str, str] | None:
        if not self.model:
            return None
        provider, sep, model_id = self.model.partition("/")
        if sep and provider.strip() and model_id.strip():
            return {"providerID": provider.strip(), "modelID": model_id.strip()}
        return {"providerID": "opencode", "modelID": self.model}

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
        resume_session_id: str | None = None,
        run_id: str | None = None,
        event_context: dict[str, Any] | None = None,
    ) -> "OpenCodeRunResult":
        from adapters.opencode_types import OpenCodeRunResult

        event_store = ExecutorEventStore(project_root) if run_id else None
        _append_live_event(
            event_store, run_id, "executor_command_started",
            {"command": [self.executable, "serve"], "cwd": project_root},
            event_context,
            phase="server",
            message="OpenCode server starting",
        )

        proc = None
        try:
            port, proc, server_log = self._start_server(project_root, logs_dir)
        except Exception as e:
            _append_live_event(
                event_store, run_id, "executor_failed",
                {"error_class": e.__class__.__name__, "message": str(e)},
                event_context,
                phase="server",
                message="OpenCode server failed to start",
                level="error",
            )
            raise

        try:
            self._wait_for_health(port)
            _append_live_event(
                event_store, run_id, "executor_tool_event",
                {"stage": "server_healthy", "port": port, "server_log": server_log},
                event_context,
                phase="server",
                message="OpenCode server healthy",
            )
            project_context = self._verify_project_context(port, project_root)
            if project_context.get("verified"):
                _append_live_event(
                    event_store, run_id, "executor_tool_event",
                    {"stage": "project_verified", **project_context},
                    event_context,
                    phase="server",
                    message="OpenCode project context verified",
                )
            else:
                _append_live_event(
                    event_store, run_id, "executor_tool_event",
                    {"stage": "project_unverified", **project_context},
                    event_context,
                    phase="server",
                    message="OpenCode project context not verifiable; continuing with Runner cwd",
                    level="warn",
                )
        except Exception as e:
            _append_live_event(
                event_store, run_id, "executor_failed",
                {"error_class": e.__class__.__name__, "message": str(e), "server_log": server_log},
                event_context,
                phase="server",
                message="OpenCode server preparation failed",
                level="error",
            )
            self._terminate_server(proc)
            raise

        safe_version = version.replace(os.sep, "-").replace("/", "-")
        attempted_resume = bool(resume_session_id)
        if attempted_resume and execution_mode == "fix":
            log_suffix = "-resume-fix-run-"
        elif attempted_resume:
            log_suffix = "-resume-run-"
        else:
            log_suffix = "-fix-run-" if execution_mode == "fix" else "-run-"
        log_path = os.path.join(logs_dir, f"{safe_version}-opencode-server{log_suffix}{attempt}.log")
        command_shape = "opencode_server_session" if attempted_resume else "opencode_server_new"

        pre_business_diff_files = _filter_business_diff(_collect_git_diff_names(project_root))
        started_at = _now()
        stdout = ""
        stderr_text = ""
        exit_code = 1
        session_id = None
        conversation_id = None
        used_resume = False
        fallback_to_new_session = False
        resume_failed_reason = None
        raw_server_usage: dict[str, Any] | None = None
        detail_server_usage: dict[str, Any] | None = None
        message_id: str | None = None

        try:
            session_data = self._create_session(port, prompt, resume_session_id=resume_session_id)
            session_id = session_data.get("session_id")
            conversation_id = session_data.get("conversation_id")
            used_resume = bool(session_data.get("resumed"))
            fallback_to_new_session = bool(attempted_resume and session_data.get("created") and not session_data.get("resumed"))
            _append_live_event(
                event_store, run_id, "executor_tool_event",
                {
                    "stage": "session_ready",
                    "session_id_present": bool(session_id),
                    "used_resume": used_resume,
                    "fallback_to_new_session": fallback_to_new_session,
                },
                event_context,
                phase="server",
                message="OpenCode session ready",
            )

            if session_id:
                _append_live_event(
                    event_store, run_id, "executor_tool_event",
                    {"stage": "prompt_send_started", "session_id_present": True},
                    event_context,
                    phase="server",
                    message="OpenCode prompt send started",
                )
                result_text, stderr_text, exit_code, raw_server_usage, message_id = (
                    self._send_prompt_to_session(
                        port, session_id, prompt, timeout_seconds,
                        event_store=event_store,
                        run_id=run_id,
                        event_context=event_context,
                    )
                )
                stdout = result_text
                _append_live_event(
                    event_store, run_id, "executor_tool_event",
                    {"stage": "prompt_response_received", "exit_code": exit_code},
                    event_context,
                    phase="server",
                    message="OpenCode response received",
                )
                if message_id and session_id:
                    _append_live_event(
                        event_store, run_id, "executor_tool_event",
                        {"stage": "token_capture_started", "message_id_present": True},
                        event_context,
                        phase="server",
                        message="OpenCode token capture started",
                    )
                    detail_server_usage = self._fetch_message_detail(port, session_id, message_id)
                    _append_live_event(
                        event_store, run_id, "executor_tool_event",
                        {"stage": "token_capture_finished", "token_usage_available": bool(detail_server_usage)},
                        event_context,
                        phase="server",
                        message="OpenCode token capture finished",
                    )
            completed_at = _now()
        except OpenCodeServerAPIError as e:
            completed_at = _now()
            stderr_text = str(e)
            exit_code = 1
            post_diff = _filter_business_diff(_collect_git_diff_names(project_root))
            nbd = set(pre_business_diff_files or []) == set(post_diff or [])
            _write_log(
                log_path=log_path, port=port, cwd=project_root,
                prompt_file=prompt_file, execution_mode=execution_mode,
                started_at=started_at, completed_at=completed_at,
                stdout=stdout, stderr=stderr_text, exit_code=exit_code,
                attempted_resume=attempted_resume, used_resume=used_resume,
                command_shape=command_shape,
                pre_business_diff_files=pre_business_diff_files,
                post_business_diff_files=post_diff, no_business_diff=nbd,
            )
            _append_live_event(
                event_store, run_id, "executor_failed",
                {"error_class": e.__class__.__name__, "message": str(e), "log_path": log_path},
                event_context,
                phase="server",
                message="OpenCode server API failed",
                level="error",
            )
            self._terminate_server(proc)
            if isinstance(e, OpenCodeModelQuotaExhaustedError):
                raise OpenCodeModelQuotaExhaustedError(
                    MODEL_QUOTA_EXHAUSTED_MESSAGE,
                    status_code=e.status_code,
                    log_path=log_path,
                ) from e
            if isinstance(e, OpenCodeProviderTerminalError):
                raise e.__class__(
                    str(e),
                    status_code=e.status_code,
                    log_path=log_path,
                    error_code=getattr(e, "error_code", "EXECUTOR_PROVIDER_ERROR"),
                    terminal_reason=getattr(e, "terminal_reason", "executor_provider_error"),
                    provider_status=getattr(e, "provider_status", ""),
                    evidence=getattr(e, "evidence", {}),
                ) from e
            raise OpenCodeServerError(f"OpenCode 服务器执行失败，已写入日志：{log_path}", log_path=log_path) from e
        except Exception as e:
            completed_at = _now()
            stderr_text = str(e)
            exit_code = 1
            post_diff = _filter_business_diff(_collect_git_diff_names(project_root))
            nbd = set(pre_business_diff_files or []) == set(post_diff or [])
            _write_log(
                log_path=log_path, port=port, cwd=project_root,
                prompt_file=prompt_file, execution_mode=execution_mode,
                started_at=started_at, completed_at=completed_at,
                stdout=stdout, stderr=stderr_text, exit_code=exit_code,
                attempted_resume=attempted_resume, used_resume=used_resume,
                command_shape=command_shape,
                pre_business_diff_files=pre_business_diff_files,
                post_business_diff_files=post_diff, no_business_diff=nbd,
            )
            _append_live_event(
                event_store, run_id, "executor_failed",
                {"error_class": e.__class__.__name__, "message": str(e), "log_path": log_path},
                event_context,
                phase="server",
                message="OpenCode server execution failed",
                level="error",
            )
            self._terminate_server(proc)
            raise OpenCodeServerError(f"OpenCode 服务器执行失败，已写入日志：{log_path}", log_path=log_path) from e
        finally:
            self._terminate_server(proc)

        if used_resume:
            command_shape = "opencode_server_session"
        elif fallback_to_new_session:
            command_shape = "opencode_server_resume_fallback_new"
        else:
            command_shape = "opencode_server_new"
        post_business_diff_files = _filter_business_diff(_collect_git_diff_names(project_root))
        no_business_diff = set(pre_business_diff_files or []) == set(post_business_diff_files or [])
        _write_log(
            log_path=log_path, port=port, cwd=project_root,
            prompt_file=prompt_file, execution_mode=execution_mode,
            started_at=started_at, completed_at=completed_at,
            stdout=stdout, stderr=stderr_text, exit_code=exit_code,
            attempted_resume=attempted_resume, used_resume=used_resume,
            command_shape=command_shape,
            pre_business_diff_files=pre_business_diff_files,
            post_business_diff_files=post_business_diff_files, no_business_diff=no_business_diff,
        )
        _append_live_event(
            event_store, run_id, "executor_command_finished",
            {
                "exit_code": exit_code,
                "session_id_present": bool(session_id),
                "conversation_id_present": bool(conversation_id),
                "log_path": log_path,
            },
            event_context,
            phase="server",
            message="OpenCode server execution finished",
            level="info" if exit_code == 0 else "error",
        )

        full_report_text = stdout.strip() if isinstance(stdout, str) and stdout.strip() else f"OpenCode 服务器已完成，完整日志见：{log_path}"
        redacted_full_report_text = _redact_sensitive_text(full_report_text)
        summary = _truncate_summary(redacted_full_report_text, max_length=1200)
        summary_write_error: str | None = None
        if summary_file:
            try:
                os.makedirs(os.path.dirname(summary_file), exist_ok=True)
                with open(summary_file, "w", encoding="utf-8") as f:
                    f.write(redacted_full_report_text)
            except Exception as sw_exc:
                summary_write_error = f"summary_write_failed:{sw_exc.__class__.__name__}:{str(sw_exc)[:300]}"
                _append_live_event(
                    event_store, run_id, "executor_tool_event",
                    {"stage": "summary_write_error", "error": summary_write_error},
                    event_context,
                    phase="server",
                    message=summary_write_error,
                    level="warn",
                )

        final_message_preview = _truncate_summary(redacted_full_report_text, max_length=300)
        has_identity = bool(session_id or conversation_id)
        if attempted_resume:
            identity_source = "opencode_output_evidence" if has_identity else "resume_input_unverified"
        elif has_identity:
            identity_source = "opencode_hint"
        else:
            identity_source = None

        if detail_server_usage:
            token_usage = normalize_token_usage(
                detail_server_usage,
                source="opencode_server_step_finish_messages",
                provider="opencode",
            )
        elif raw_server_usage:
            token_usage = normalize_token_usage(
                raw_server_usage,
                source="opencode_server_step_finish_response",
                provider="opencode",
            )
        else:
            token_usage = normalize_token_usage(
                None,
                source="opencode_server_unavailable",
                provider="opencode",
            )
            token_usage["unavailable_reason"] = "missing_step_finish_tokens"

        result = OpenCodeRunResult(
            command=[self.executable, "serve", "--port", str(port)],
            cwd=project_root, prompt_file=prompt_file,
            log_path=log_path, started_at=started_at, completed_at=completed_at,
            exit_code=exit_code, stdout=stdout, stderr=stderr_text,
            summary=summary, summary_path=summary_file,
            final_message_preview=final_message_preview,
            conversation_id=conversation_id,
            session_id=session_id,
            session_file=None,
            attempted_resume=attempted_resume,
            used_resume=used_resume,
            resume_session_id_present=attempted_resume,
            fallback_to_new_session=fallback_to_new_session,
            resume_failed_reason=resume_failed_reason,
            identity_source=identity_source,
            command_shape=command_shape,
            token_usage=token_usage,
        )
        setattr(result, "full_report_text", full_report_text)
        if summary_write_error:
            setattr(result, "summary_write_error", summary_write_error)
        return result

    def _terminate_server(self, proc: subprocess.Popen | None) -> None:
        if proc is None:
            return
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
                proc.wait(timeout=3)
            except Exception:
                pass
