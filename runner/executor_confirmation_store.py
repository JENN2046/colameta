import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from runner.preview_artifact import PreviewArtifact


class ExecutorConfirmationStore:
    """执行器 workflow preview 的兼容包装层。"""

    def __init__(self, project_root: str, relative_dir: str, ttl_seconds: int):
        self.project_root = os.path.abspath(os.path.expanduser(project_root))
        self.ttl_seconds = int(ttl_seconds)
        self._store = PreviewArtifact(self.project_root, relative_dir, self.ttl_seconds)

    def create_id(self, prefix: str) -> str:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        return f"{prefix}_{ts}_{uuid.uuid4().hex[:8]}"

    def now_iso(self) -> str:
        return datetime.now(timezone.utc).astimezone().isoformat()

    def expires_at(self, add_seconds: int | None = None) -> str:
        seconds = self.ttl_seconds if add_seconds is None else int(add_seconds)
        return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).astimezone().isoformat()

    def write(self, preview_id: str, payload: dict[str, Any]) -> None:
        self._store.write(preview_id, payload)

    def write_artifact(self, preview_id: str, payload: dict[str, Any]) -> None:
        self.write(preview_id, payload)

    def read(self, preview_id: str) -> dict[str, Any] | None:
        data = self._store.read(preview_id)
        return data if isinstance(data, dict) else None

    def read_artifact(self, preview_id: str) -> dict[str, Any] | None:
        return self.read(preview_id)

    def delete(self, preview_id: str) -> bool:
        return self._store.delete(preview_id)

    def delete_artifact(self, preview_id: str) -> bool:
        return self.delete(preview_id)

    def status(self, preview_id: str) -> dict[str, Any]:
        return self._store.status(preview_id)

    def guard(self, preview_id: str, *, payload: Any | None = None) -> dict[str, Any]:
        return self._store.guard(preview_id, project_root=self.project_root, payload=payload)

    def is_expired(self, payload: dict[str, Any]) -> bool:
        return self._store.is_expired(payload)

    def validate_project(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        return self._store.validate_project(payload)

    def validate_not_expired(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        return self._store.validate_not_expired(payload)

    def validate_artifact_kind(self, payload: dict[str, Any], expected: str) -> dict[str, Any]:
        actual = str(payload.get("artifact_kind") or "")
        if actual != expected:
            return {
                "ok": False,
                "error_code": "PREVIEW_KIND_MISMATCH",
                "message": "preview_id 类型不匹配。",
            }
        return {"ok": True}

    def validate_provider(self, payload: dict[str, Any], provider: str) -> dict[str, Any]:
        actual = str(payload.get("provider") or "")
        if actual != provider:
            return {
                "ok": False,
                "error_code": "PROVIDER_MISMATCH",
                "message": f"provider 不匹配。preview 中记录的是 {actual}，但请求的是 {provider}。",
            }
        return {"ok": True}

    def validate_execution_mode(self, payload: dict[str, Any], execution_mode: str) -> dict[str, Any]:
        actual = str(payload.get("execution_mode") or "run")
        if actual != execution_mode:
            return {
                "ok": False,
                "error_code": "EXECUTION_MODE_MISMATCH",
                "message": f"execution_mode 不匹配。preview 中记录的是 {actual}，但请求的是 {execution_mode}。",
            }
        return {"ok": True}
