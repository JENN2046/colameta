import json
import os
from datetime import datetime, timezone
from typing import Any

from runner.sensitive_redaction import redact_sensitive_text
from runner.work_item_governance.references import optional_work_item_reference_rejections


EVENT_TYPES = frozenset({
    "run_claimed",
    "worker_started",
    "executor_preparing",
    "executor_started",
    "executor_stdout",
    "executor_stderr",
    "executor_finished",
    "executor_failed",
    "executor_tool_event",
    "executor_command_started",
    "executor_command_finished",
    "git_diff_changed",
    "heartbeat",
    "validation_started",
    "validation_finished",
    "report_written",
    "run_completed",
    "run_failed",
    "run_orphaned",
})

def _redact_text(text: str) -> str:
    return redact_sensitive_text(text, replacement_token="***", preserve_token_prefix=False)


def _redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return _redact_text(value)
    if isinstance(value, dict):
        return {k: _redact_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    return value


def redact_event_data(data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict):
        return data
    SENSITIVE_KEYS = frozenset({"prompt_body", "stdout", "stderr", "command", "env", "bearer_token", "api_key", "secret"})
    shallow = dict(data)
    for key, value in list(shallow.items()):
        if key in SENSITIVE_KEYS:
            shallow[key] = _redact_value(value)
        elif isinstance(value, dict):
            shallow[key] = _redact_value(_deep_key_aware_redact(value))
        elif isinstance(value, list):
            shallow[key] = _redact_value(value)
    if "stdout_tail" in shallow:
        shallow["stdout_tail"] = _redact_text(str(shallow["stdout_tail"]))[:2000]
    if "stderr_tail" in shallow:
        shallow["stderr_tail"] = _redact_text(str(shallow["stderr_tail"]))[:2000]
    return shallow


def _deep_key_aware_redact(data: dict[str, Any]) -> dict[str, Any]:
    SENSITIVE_KEYS = frozenset({"prompt_body", "stdout", "stderr", "command", "env", "bearer_token", "api_key", "secret"})
    result: dict[str, Any] = {}
    for key, value in data.items():
        if key in SENSITIVE_KEYS:
            result[key] = _redact_value(value)
        elif isinstance(value, dict):
            result[key] = _deep_key_aware_redact(value)
        elif isinstance(value, list):
            result[key] = [_deep_key_aware_redact(v) if isinstance(v, dict) else _redact_value(v) for v in value]
        else:
            result[key] = _redact_value(value)
    return result


class ExecutorEventStore:
    SCHEMA_VERSION = "1.0"

    def __init__(self, project_root: str):
        self.project_root = os.path.abspath(os.path.expanduser(project_root))

    def _runs_dir(self) -> str:
        return resolve_project_runner_path(self.project_root, "runtime", "executor-runs")

    def _events_file(self, run_id: str) -> str:
        return os.path.join(self._runs_dir(), run_id, "events.jsonl")

    def append(self, run_id: str, event_type: str, data: dict[str, Any] | None = None, event_context: dict[str, Any] | None = None) -> None:
        if not isinstance(run_id, str) or not run_id.strip():
            return
        if event_type not in EVENT_TYPES:
            event_type = str(event_type)[:80]
        if data is None:
            data = {}
        redacted = redact_event_data(data)
        if event_context:
            record: dict[str, Any] = {
                "schema_version": self.SCHEMA_VERSION,
                "run_id": str(event_context.get("run_id", run_id)),
                "preview_id": str(event_context.get("preview_id", "")),
                "version": str(event_context.get("version", "")),
                "provider": str(event_context.get("provider", "")),
                "execution_mode": str(event_context.get("execution_mode", "")),
                "event_type": event_type,
                "phase": str(event_context.get("phase", "")),
                "level": str(event_context.get("level", "info")),
                "message": str(event_context.get("message", "")),
                "timestamp": datetime.now(timezone.utc).astimezone().isoformat(),
                "data": redacted,
            }
            work_item_binding = {
                field: event_context.get(field)
                for field in ("work_item_id", "task_version", "attempt_id", "artifact_refs")
                if field in event_context
            }
            if work_item_binding and not optional_work_item_reference_rejections(work_item_binding):
                record.update(work_item_binding)
        else:
            record = {
                "schema_version": self.SCHEMA_VERSION,
                "run_id": run_id,
                "preview_id": "",
                "version": "",
                "provider": "",
                "execution_mode": "",
                "event_type": event_type,
                "phase": "",
                "level": "info",
                "message": "",
                "timestamp": datetime.now(timezone.utc).astimezone().isoformat(),
                "data": redacted,
            }
        events_file = self._events_file(run_id)
        events_dir = os.path.dirname(events_file)
        os.makedirs(events_dir, exist_ok=True)
        try:
            with open(events_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            import logging
            logging.getLogger(__name__).exception("Failed to write executor event")

    def read(self, run_id: str, limit: int = 100) -> list[dict[str, Any]]:
        if not isinstance(run_id, str) or not run_id.strip():
            return []
        events_file = self._events_file(run_id)
        if not os.path.isfile(events_file):
            return []
        events: list[dict[str, Any]] = []
        try:
            with open(events_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        raw = json.loads(line)
                        events.append(self._normalize_record(raw))
                    except json.JSONDecodeError:
                        continue
        except Exception:
            return []
        return events[-limit:]

    @staticmethod
    def _normalize_record(raw: dict[str, Any]) -> dict[str, Any]:
        if "schema_version" in raw:
            return raw
        ts = raw.get("ts", "")
        evt = raw.get("event", "")
        data_raw = raw.get("data", {})
        if not isinstance(data_raw, dict):
            data_raw = {}
        return {
            "schema_version": "0.9",
            "run_id": str(data_raw.get("run_id", "")),
            "preview_id": str(data_raw.get("preview_id", "")),
            "version": str(data_raw.get("version", "")),
            "provider": str(data_raw.get("provider", "")),
            "execution_mode": str(data_raw.get("execution_mode", "")),
            "event_type": str(evt),
            "phase": "",
            "level": "info",
            "message": "",
            "timestamp": str(ts),
            "data": data_raw,
        }

    def has_events(self, run_id: str) -> bool:
        if not isinstance(run_id, str) or not run_id.strip():
            return False
        return os.path.isfile(self._events_file(run_id))

    def run_dir(self, run_id: str) -> str:
        return os.path.join(self._runs_dir(), run_id)
from runner.runner_paths import resolve_project_runner_path
