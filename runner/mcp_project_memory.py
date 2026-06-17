import os
import tempfile
from datetime import datetime, timezone
from typing import Any

from runner.runner_paths import resolve_project_runner_dir, resolve_project_runner_rel_dir


class MCPProjectMemoryError(Exception):
    def __init__(self, error_code: str, message: str):
        self.error_code = error_code
        self.message = message


class MCPProjectMemoryManager:
    """Manage project-level long-lived GPTs memory stored as a markdown document."""

    DEFAULT_MAX_CHARS = 30000
    HARD_MAX_CHARS = 120000
    MEMORY_FILENAME = "memory.md"
    LEGACY_CONTEXT_FILENAME = "project-context.md"

    def __init__(self, project_root: str):
        self.project_root = os.path.abspath(os.path.expanduser(project_root))
        runner_rel_dir = resolve_project_runner_rel_dir(self.project_root)
        self.runner_dir = resolve_project_runner_dir(self.project_root)
        self.context_path = os.path.join(self.runner_dir, self.MEMORY_FILENAME)
        self.legacy_context_path = os.path.join(self.runner_dir, self.LEGACY_CONTEXT_FILENAME)
        self.context_rel_path = f"{runner_rel_dir}/{self.MEMORY_FILENAME}"

    def read(self, max_chars: Any = None) -> dict[str, Any]:
        normalized_max_chars = self._normalize_max_chars(max_chars)
        if normalized_max_chars is None:
            return self._error_payload(
                "memory_read",
                "MEMORY_INVALID_MAX_CHARS",
                "max_chars 必须是正整数。",
            )
        ensure_result = self._ensure_memory_file()
        if not ensure_result.get("ok"):
            return ensure_result
        try:
            with open(self.context_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as exc:
            return self._error_payload(
                "memory_read",
                "MEMORY_READ_ERROR",
                f"读取 memory 失败：{exc}",
            )
        truncated = len(content) > normalized_max_chars
        visible_content = content[:normalized_max_chars] if truncated else content
        return {
            "ok": True,
            "action": "memory_read",
            "exists": True,
            "created": ensure_result.get("created", False),
            "migrated_from": ensure_result.get("migrated_from"),
            "content": visible_content,
            "content_chars": len(content),
            "returned_chars": len(visible_content),
            "truncated": truncated,
            "path": self.context_rel_path,
        }

    def add(self, content: Any) -> dict[str, Any]:
        normalized_content = self._normalize_content(content)
        if normalized_content is None:
            return self._error_payload(
                "memory_add",
                "INVALID_CONTENT",
                "content 必须是非空字符串。",
            )
        ensure_result = self._ensure_memory_file()
        if not ensure_result.get("ok"):
            return ensure_result
        try:
            with open(self.context_path, "r", encoding="utf-8") as f:
                existing_content = f.read()
        except Exception as exc:
            return self._error_payload("memory_add", "MEMORY_READ_ERROR", f"读取 memory 失败：{exc}")
        if existing_content.strip():
            return self._error_payload(
                "memory_add",
                "MEMORY_ALREADY_EXISTS",
                "memory 已存在；请使用 update。",
            )
        return self._write_context("memory_add", normalized_content)

    def update(self, content: Any) -> dict[str, Any]:
        normalized_content = self._normalize_content(content)
        if normalized_content is None:
            return self._error_payload(
                "memory_update",
                "INVALID_CONTENT",
                "content 必须是非空字符串。",
            )
        return self._write_context("memory_update", normalized_content)

    def delete(self) -> dict[str, Any]:
        target_path = self.context_path
        if not os.path.isfile(target_path) and os.path.isfile(self.legacy_context_path):
            target_path = self.legacy_context_path
        if not os.path.isfile(target_path):
            return self._error_payload(
                "memory_delete",
                "MEMORY_FILE_NOT_FOUND",
                "memory 文件不存在。",
            )
        try:
            with open(target_path, "r", encoding="utf-8") as f:
                deleted_content = f.read()
            os.remove(target_path)
        except Exception as exc:
            return self._error_payload(
                "memory_delete",
                "MEMORY_DELETE_FAILED",
                f"删除 memory 失败：{exc}",
            )
        return {
            "ok": True,
            "action": "memory_delete",
            "deleted_content_chars": len(deleted_content),
            "path": self.context_rel_path,
        }

    def _ensure_memory_file(self) -> dict[str, Any]:
        try:
            os.makedirs(os.path.dirname(self.context_path), exist_ok=True)
            if os.path.isfile(self.context_path):
                return {"ok": True, "created": False, "migrated_from": None}
            if os.path.isfile(self.legacy_context_path):
                os.replace(self.legacy_context_path, self.context_path)
                return {"ok": True, "created": False, "migrated_from": self.LEGACY_CONTEXT_FILENAME}
            with open(self.context_path, "w", encoding="utf-8") as f:
                f.write("")
            return {"ok": True, "created": True, "migrated_from": None}
        except Exception as exc:
            return self._error_payload("memory_read", "MEMORY_CREATE_FAILED", f"创建 memory 失败：{exc}")

    def _write_context(self, action: str, content: str) -> dict[str, Any]:
        payload = content.rstrip() + "\n"
        try:
            os.makedirs(os.path.dirname(self.context_path), exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(
                prefix=".tmp-memory-",
                suffix=".md",
                dir=os.path.dirname(self.context_path),
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(payload)
                os.replace(tmp_path, self.context_path)
            except Exception:
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
                raise
        except Exception as exc:
            return self._error_payload(action, "MEMORY_WRITE_FAILED", f"写入 memory 失败：{exc}")
        return {
            "ok": True,
            "action": action,
            "content_chars": len(payload),
            "updated_at": self._now_iso(),
            "path": self.context_rel_path,
        }

    def _normalize_content(self, content: Any) -> str | None:
        if not isinstance(content, str):
            return None
        normalized = content.strip()
        if not normalized:
            return None
        return normalized

    def _normalize_max_chars(self, max_chars: Any) -> int | None:
        if max_chars is None:
            return self.DEFAULT_MAX_CHARS
        if isinstance(max_chars, bool):
            return None
        try:
            value = int(max_chars)
        except (TypeError, ValueError):
            return None
        if value <= 0:
            return None
        return min(value, self.HARD_MAX_CHARS)

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def _error_payload(self, action: str, error_code: str, message: str) -> dict[str, Any]:
        return {
            "ok": False,
            "action": action,
            "error_code": error_code,
            "message": message,
            "path": self.context_rel_path,
        }
