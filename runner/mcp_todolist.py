import json
import os
import re
from datetime import datetime, timezone
from typing import Any

from runner._internal_utils import write_json_atomic
from runner.runner_paths import resolve_project_runner_dir, resolve_project_runner_rel_dir


class MCPTodoListError(Exception):
    def __init__(self, error_code: str, message: str):
        self.error_code = error_code
        self.message = message


class MCPTodoListManager:
    SCHEMA_VERSION = 1
    STATUS_PLANNED = "planned"
    STATUS_DONE = "done"
    VALID_STATUSES = {STATUS_PLANNED, STATUS_DONE}
    TODO_ID_PATTERN = re.compile(r"^todo-(\d{8})-(\d{3})$")

    def __init__(self, project_root: str):
        self.project_root = os.path.abspath(os.path.expanduser(project_root))
        runner_rel_dir = resolve_project_runner_rel_dir(self.project_root)
        self.runner_dir = resolve_project_runner_dir(self.project_root)
        self.todo_path = os.path.join(self.runner_dir, "todolist.json")
        self.todo_rel_path = f"{runner_rel_dir}/todolist.json"

    def read(self, include_done: bool = False) -> dict[str, Any]:
        if not os.path.isfile(self.todo_path):
            return {
                "ok": True,
                "action": "todo_read",
                "items": [],
                "item_count": 0,
                "total_item_count": 0,
                "planned_count": 0,
                "done_count": 0,
                "path": self.todo_rel_path,
            }

        data = self._load_todo_file()
        if isinstance(data, MCPTodoListError):
            return self._error_payload("todo_read", data.error_code, data.message)

        items = data["items"]
        planned_items = [item for item in items if item.get("status") != self.STATUS_DONE]
        done_items = [item for item in items if item.get("status") == self.STATUS_DONE]
        visible_items = items if include_done else planned_items
        return {
            "ok": True,
            "action": "todo_read",
            "schema_version": data["schema_version"],
            "items": visible_items,
            "item_count": len(visible_items),
            "total_item_count": len(items),
            "planned_count": len(planned_items),
            "done_count": len(done_items),
            "path": self.todo_rel_path,
        }

    def add(self, content: str, status: Any = None) -> dict[str, Any]:
        normalized_content = self._normalize_content(content)
        if normalized_content is None:
            return self._error_payload("todo_add", "INVALID_CONTENT", "content 必须是非空字符串。")

        normalized_status = self._normalize_add_status(status)
        if normalized_status is None:
            return self._error_payload("todo_add", "TODO_INVALID_STATUS", "status 只能是 planned 或 done。")

        if os.path.isfile(self.todo_path):
            data = self._load_todo_file()
            if isinstance(data, MCPTodoListError):
                return self._error_payload("todo_add", data.error_code, data.message)
        else:
            data = {"schema_version": self.SCHEMA_VERSION, "items": []}

        items = list(data["items"])
        item_id = self._generate_item_id(items)
        new_item = {
            "id": item_id,
            "content": normalized_content,
            "created_at": self._now_iso(),
            "status": normalized_status,
        }
        items.append(new_item)
        updated = {"schema_version": self.SCHEMA_VERSION, "items": items}
        try:
            write_json_atomic(self.todo_path, updated)
        except Exception as exc:
            return self._error_payload("todo_add", "TODO_WRITE_FAILED", f"写入 todolist 失败：{exc}")

        return {
            "ok": True,
            "action": "todo_add",
            "item": new_item,
            "item_count": len(items),
            "path": self.todo_rel_path,
        }

    def delete(self, item_id: str) -> dict[str, Any]:
        normalized_id = self._normalize_id(item_id)
        if normalized_id is None:
            return self._error_payload("todo_delete", "INVALID_ID", "id 必须是非空字符串。")

        if not os.path.isfile(self.todo_path):
            return self._error_payload("todo_delete", "TODO_FILE_NOT_FOUND", "todolist 文件不存在。")

        data = self._load_todo_file()
        if isinstance(data, MCPTodoListError):
            return self._error_payload("todo_delete", data.error_code, data.message)

        items = list(data["items"])
        deleted_index = None
        deleted_item: dict[str, Any] | None = None
        for index, item in enumerate(items):
            if isinstance(item, dict) and item.get("id") == normalized_id:
                deleted_index = index
                deleted_item = item
                break

        if deleted_index is None or deleted_item is None:
            return self._error_payload("todo_delete", "TODO_NOT_FOUND", "未找到对应 id 的待办。")

        del items[deleted_index]
        updated = {"schema_version": self.SCHEMA_VERSION, "items": items}
        try:
            write_json_atomic(self.todo_path, updated)
        except Exception as exc:
            return self._error_payload("todo_delete", "TODO_WRITE_FAILED", f"写入 todolist 失败：{exc}")

        return {
            "ok": True,
            "action": "todo_delete",
            "deleted_item": deleted_item,
            "item_count": len(items),
            "path": self.todo_rel_path,
        }

    def update(self, item_id: str, content: Any = None, status: Any = None) -> dict[str, Any]:
        normalized_id = self._normalize_id(item_id)
        if normalized_id is None:
            return self._error_payload("todo_update", "INVALID_ID", "id 必须是非空字符串。")

        content_provided = content is not None
        status_provided = status is not None
        if not content_provided and not status_provided:
            return self._error_payload("todo_update", "INVALID_UPDATE_REQUEST", "content 和 status 至少需要提供一个。")

        normalized_content = None
        if content_provided:
            normalized_content = self._normalize_content(content)
            if normalized_content is None:
                return self._error_payload("todo_update", "INVALID_CONTENT", "content 必须是非空字符串。")

        normalized_status = None
        if status_provided:
            normalized_status = self._normalize_required_status(status)
            if normalized_status is None:
                return self._error_payload("todo_update", "TODO_INVALID_STATUS", "status 只能是 planned 或 done。")

        if not os.path.isfile(self.todo_path):
            return self._error_payload("todo_update", "TODO_FILE_NOT_FOUND", "todolist 文件不存在。")

        data = self._load_todo_file()
        if isinstance(data, MCPTodoListError):
            return self._error_payload("todo_update", data.error_code, data.message)

        items = list(data["items"])
        updated_index = None
        updated_item: dict[str, Any] | None = None
        now = self._now_iso()
        for index, item in enumerate(items):
            if isinstance(item, dict) and item.get("id") == normalized_id:
                updated_index = index
                current_status = item.get("status", self.STATUS_PLANNED)
                updated_item = {
                    "id": item["id"],
                    "content": normalized_content if normalized_content is not None else item["content"],
                    "created_at": item["created_at"],
                    "status": normalized_status if normalized_status is not None else current_status,
                    "updated_at": now,
                }
                items[index] = updated_item
                break

        if updated_index is None or updated_item is None:
            return self._error_payload("todo_update", "TODO_NOT_FOUND", "未找到对应 id 的待办。")

        updated = {"schema_version": self.SCHEMA_VERSION, "items": items}
        try:
            write_json_atomic(self.todo_path, updated)
        except Exception as exc:
            return self._error_payload("todo_update", "TODO_WRITE_FAILED", f"写入 todolist 失败：{exc}")

        return {
            "ok": True,
            "action": "todo_update",
            "item": updated_item,
            "item_count": len(items),
            "path": self.todo_rel_path,
        }

    def _load_todo_file(self) -> dict[str, Any] | MCPTodoListError:
        try:
            with open(self.todo_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as exc:
            return MCPTodoListError("TODO_JSON_INVALID", f"todolist JSON 解析失败：第 {exc.lineno} 行第 {exc.colno} 列，{exc.msg}")
        except FileNotFoundError:
            return MCPTodoListError("TODO_FILE_NOT_FOUND", "todolist 文件不存在。")
        except Exception as exc:
            return MCPTodoListError("TODO_READ_ERROR", f"读取 todolist 失败：{exc}")

        if not isinstance(data, dict):
            return MCPTodoListError("TODO_SCHEMA_INVALID", "todolist 根节点必须是 JSON 对象。")

        schema_version = data.get("schema_version")
        items = data.get("items")
        if schema_version != self.SCHEMA_VERSION:
            return MCPTodoListError("TODO_SCHEMA_INVALID", "todolist schema_version 无效。")
        if not isinstance(items, list):
            return MCPTodoListError("TODO_SCHEMA_INVALID", "todolist items 必须是数组。")

        normalized_items: list[dict[str, Any]] = []
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                return MCPTodoListError("TODO_SCHEMA_INVALID", f"todolist items[{index}] 必须是对象。")
            item_id = item.get("id")
            content = item.get("content")
            created_at = item.get("created_at")
            updated_at = item.get("updated_at")
            status = item.get("status") if "status" in item else self.STATUS_PLANNED
            if not isinstance(item_id, str) or not item_id.strip():
                return MCPTodoListError("TODO_SCHEMA_INVALID", f"todolist items[{index}].id 无效。")
            if not isinstance(content, str) or not content.strip():
                return MCPTodoListError("TODO_SCHEMA_INVALID", f"todolist items[{index}].content 无效。")
            if not isinstance(created_at, str) or not created_at.strip():
                return MCPTodoListError("TODO_SCHEMA_INVALID", f"todolist items[{index}].created_at 无效。")
            normalized_status = self._normalize_required_status(status)
            if normalized_status is None:
                return MCPTodoListError("TODO_SCHEMA_INVALID", f"todolist items[{index}].status 无效。")
            normalized_item = {
                "id": item_id.strip(),
                "content": content.strip(),
                "created_at": created_at.strip(),
                "status": normalized_status,
            }
            if updated_at is not None:
                if not isinstance(updated_at, str) or not updated_at.strip():
                    return MCPTodoListError("TODO_SCHEMA_INVALID", f"todolist items[{index}].updated_at 无效。")
                normalized_item["updated_at"] = updated_at.strip()
            normalized_items.append(normalized_item)

        return {
            "schema_version": self.SCHEMA_VERSION,
            "items": normalized_items,
        }

    def _generate_item_id(self, items: list[dict[str, Any]]) -> str:
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        existing_ids = {
            str(item.get("id"))
            for item in items
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        max_suffix = 0
        for item_id in existing_ids:
            match = self.TODO_ID_PATTERN.match(item_id)
            if match and match.group(1) == today:
                max_suffix = max(max_suffix, int(match.group(2)))

        suffix = max_suffix + 1
        while True:
            candidate = f"todo-{today}-{suffix:03d}"
            if candidate not in existing_ids:
                return candidate
            suffix += 1

    def _normalize_content(self, content: Any) -> str | None:
        if not isinstance(content, str):
            return None
        normalized = content.strip()
        if not normalized:
            return None
        return normalized

    def _normalize_add_status(self, status: Any) -> str | None:
        if status is None:
            return self.STATUS_PLANNED
        if not isinstance(status, str):
            return None
        normalized = status.strip().lower()
        if not normalized:
            return self.STATUS_PLANNED
        if normalized in self.VALID_STATUSES:
            return normalized
        return None

    def _normalize_required_status(self, status: Any) -> str | None:
        if not isinstance(status, str):
            return None
        normalized = status.strip().lower()
        if normalized in self.VALID_STATUSES:
            return normalized
        return None

    def _normalize_id(self, item_id: Any) -> str | None:
        if not isinstance(item_id, str):
            return None
        normalized = item_id.strip()
        if not normalized:
            return None
        return normalized

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def _error_payload(self, action: str, error_code: str, message: str) -> dict[str, Any]:
        return {
            "ok": False,
            "action": action,
            "error_code": error_code,
            "message": message,
            "path": self.todo_rel_path,
        }
