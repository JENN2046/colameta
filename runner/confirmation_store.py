import json
import os
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_PREVIEW_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def _iso_to_timestamp(iso_str: str) -> float:
    if iso_str.endswith("Z"):
        iso_str = iso_str[:-1] + "+00:00"
    return datetime.fromisoformat(iso_str).timestamp()


class ConfirmationStore:
    def __init__(self, project_root: str, relative_dir: str, ttl_seconds: int):
        self.project_root = os.path.abspath(os.path.expanduser(project_root))
        self.relative_dir = relative_dir
        self.ttl_seconds = ttl_seconds
        self.root = Path(self.project_root) / relative_dir
        self.root.mkdir(parents=True, exist_ok=True)

    def create_id(self, prefix: str = "") -> str:
        raw_id = uuid.uuid4().hex[:16]
        return f"{prefix}{raw_id}" if prefix else raw_id

    def now_iso(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def expires_at(self) -> str:
        expires_ts = datetime.now(timezone.utc).timestamp() + self.ttl_seconds
        return datetime.fromtimestamp(expires_ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def write(self, preview_id: str, payload: dict[str, Any]) -> None:
        path = self._path(preview_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def read(self, preview_id: str) -> dict[str, Any] | None:
        path = self._safe_path(preview_id)
        if path is None or not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def delete(self, preview_id: str) -> bool:
        path = self._safe_path(preview_id)
        if path is None:
            return False
        try:
            if path.is_file():
                path.unlink()
                return True
        except Exception:
            return False
        return False

    def status(self, preview_id: str) -> dict[str, Any]:
        path = self._safe_path(preview_id)
        if path is None:
            return {"ok": False, "error_code": "INVALID_PREVIEW_ID", "message": "preview_id 非法。"}
        payload = self.read(preview_id)
        if payload is None:
            return {"ok": True, "preview_id": preview_id, "exists": False, "expired": False}
        return {
            "ok": True,
            "preview_id": preview_id,
            "exists": True,
            "expired": self.is_expired(payload),
            "expires_at": payload.get("expires_at", ""),
            "created_at": payload.get("created_at", ""),
        }

    def is_expired(self, payload: dict[str, Any]) -> bool:
        expires_str = payload.get("expires_at", "")
        if not isinstance(expires_str, str) or not expires_str:
            return False
        try:
            return time.time() > _iso_to_timestamp(expires_str)
        except Exception:
            return False

    def validate_project(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        if payload.get("project_root") != self.project_root:
            return {
                "ok": False,
                "error_code": "PROJECT_MISMATCH",
                "message": "preview 与当前项目不匹配。",
            }
        return None

    def validate_not_expired(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        if self.is_expired(payload):
            return {"ok": False, "error_code": "PREVIEW_EXPIRED", "message": "preview 已过期。"}
        return None

    def _path(self, preview_id: str) -> Path:
        path = self._safe_path(preview_id)
        if path is None:
            raise ValueError("invalid preview_id")
        return path

    def _safe_path(self, preview_id: str) -> Path | None:
        if not isinstance(preview_id, str) or not preview_id or not _PREVIEW_ID_RE.match(preview_id):
            return None
        path = (self.root / f"{preview_id}.json").resolve()
        root = self.root.resolve()
        try:
            path.relative_to(root)
        except ValueError:
            return None
        return path
