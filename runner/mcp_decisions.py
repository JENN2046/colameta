import json
import os
import re
from datetime import datetime, timezone
from typing import Any

from runner._internal_utils import write_json_atomic
from runner.runner_paths import resolve_project_runner_dir, resolve_project_runner_rel_dir


class MCPDecisionRecordsError(Exception):
    def __init__(self, error_code: str, message: str):
        self.error_code = error_code
        self.message = message


class MCPDecisionRecordsManager:
    SCHEMA_VERSION = 1
    STATUS_ACTIVE = "active"
    STATUS_SUPERSEDED = "superseded"
    STATUS_REJECTED = "rejected"
    VALID_STATUSES = {STATUS_ACTIVE, STATUS_SUPERSEDED, STATUS_REJECTED}
    DECISION_ID_PATTERN = re.compile(r"^decision-(\d{8})-(\d{3})$")

    def __init__(self, project_root: str):
        self.project_root = os.path.abspath(os.path.expanduser(project_root))
        runner_rel_dir = resolve_project_runner_rel_dir(self.project_root)
        self.runner_dir = resolve_project_runner_dir(self.project_root)
        self.decisions_path = os.path.join(self.runner_dir, "decisions.json")
        self.decisions_rel_path = f"{runner_rel_dir}/decisions.json"

    def read(self) -> dict[str, Any]:
        if not os.path.isfile(self.decisions_path):
            return {
                "ok": True,
                "action": "decision_read",
                "schema_version": self.SCHEMA_VERSION,
                "decisions": [],
                "decision_count": 0,
                "path": self.decisions_rel_path,
            }

        data = self._load_decisions_file()
        if isinstance(data, MCPDecisionRecordsError):
            return self._error_payload("decision_read", data.error_code, data.message)

        return {
            "ok": True,
            "action": "decision_read",
            "schema_version": data["schema_version"],
            "decisions": data["decisions"],
            "decision_count": len(data["decisions"]),
            "path": self.decisions_rel_path,
        }

    def add(
        self,
        title: Any,
        decision: Any,
        reason: Any,
        related_versions: Any = None,
        status: Any = None,
    ) -> dict[str, Any]:
        normalized_title = self._normalize_required_text(title)
        if normalized_title is None:
            return self._error_payload("decision_add", "INVALID_TITLE", "title 必须是非空字符串。")

        normalized_decision = self._normalize_required_text(decision)
        if normalized_decision is None:
            return self._error_payload("decision_add", "INVALID_DECISION", "decision 必须是非空字符串。")

        normalized_reason = self._normalize_required_text(reason)
        if normalized_reason is None:
            return self._error_payload("decision_add", "INVALID_REASON", "reason 必须是非空字符串。")

        normalized_related_versions = self._normalize_related_versions(related_versions)
        if normalized_related_versions is None:
            return self._error_payload(
                "decision_add",
                "DECISION_INVALID_RELATED_VERSIONS",
                "related_versions 必须是字符串数组。",
            )

        normalized_status = self._normalize_add_status(status)
        if normalized_status is None:
            return self._error_payload(
                "decision_add",
                "DECISION_INVALID_STATUS",
                "status 只能是 active、superseded 或 rejected。",
            )

        if os.path.isfile(self.decisions_path):
            data = self._load_decisions_file()
            if isinstance(data, MCPDecisionRecordsError):
                return self._error_payload("decision_add", data.error_code, data.message)
        else:
            data = {"schema_version": self.SCHEMA_VERSION, "decisions": []}

        decisions = list(data["decisions"])
        decision_id = self._generate_decision_id(decisions)
        new_decision = {
            "id": decision_id,
            "title": normalized_title,
            "decision": normalized_decision,
            "reason": normalized_reason,
            "related_versions": normalized_related_versions,
            "status": normalized_status,
            "created_at": self._now_iso(),
        }
        decisions.append(new_decision)
        updated = {"schema_version": self.SCHEMA_VERSION, "decisions": decisions}
        try:
            write_json_atomic(self.decisions_path, updated)
        except Exception as exc:
            return self._error_payload("decision_add", "DECISION_WRITE_FAILED", f"写入 decisions 失败：{exc}")

        return {
            "ok": True,
            "action": "decision_add",
            "decision_record": new_decision,
            "decision_count": len(decisions),
            "path": self.decisions_rel_path,
        }

    def update(self, decision_id: Any, **changes: Any) -> dict[str, Any]:
        normalized_id = self._normalize_id(decision_id)
        if normalized_id is None:
            return self._error_payload("decision_update", "INVALID_ID", "id 必须是非空字符串。")

        allowed_fields = {"title", "decision", "reason", "related_versions", "status"}
        provided_fields = [field for field in allowed_fields if field in changes]
        if not provided_fields:
            return self._error_payload(
                "decision_update",
                "INVALID_UPDATE_REQUEST",
                "title、decision、reason、related_versions、status 至少需要提供一个。",
            )

        normalized_changes: dict[str, Any] = {}
        if "title" in changes:
            normalized_title = self._normalize_required_text(changes.get("title"))
            if normalized_title is None:
                return self._error_payload("decision_update", "INVALID_TITLE", "title 必须是非空字符串。")
            normalized_changes["title"] = normalized_title
        if "decision" in changes:
            normalized_decision = self._normalize_required_text(changes.get("decision"))
            if normalized_decision is None:
                return self._error_payload("decision_update", "INVALID_DECISION", "decision 必须是非空字符串。")
            normalized_changes["decision"] = normalized_decision
        if "reason" in changes:
            normalized_reason = self._normalize_required_text(changes.get("reason"))
            if normalized_reason is None:
                return self._error_payload("decision_update", "INVALID_REASON", "reason 必须是非空字符串。")
            normalized_changes["reason"] = normalized_reason
        if "related_versions" in changes:
            normalized_related_versions = self._normalize_related_versions(changes.get("related_versions"))
            if normalized_related_versions is None:
                return self._error_payload(
                    "decision_update",
                    "DECISION_INVALID_RELATED_VERSIONS",
                    "related_versions 必须是字符串数组。",
                )
            normalized_changes["related_versions"] = normalized_related_versions
        if "status" in changes:
            normalized_status = self._normalize_required_status(changes.get("status"))
            if normalized_status is None:
                return self._error_payload(
                    "decision_update",
                    "DECISION_INVALID_STATUS",
                    "status 只能是 active、superseded 或 rejected。",
                )
            normalized_changes["status"] = normalized_status

        if not os.path.isfile(self.decisions_path):
            return self._error_payload("decision_update", "DECISIONS_FILE_NOT_FOUND", "decisions 文件不存在。")

        data = self._load_decisions_file()
        if isinstance(data, MCPDecisionRecordsError):
            return self._error_payload("decision_update", data.error_code, data.message)

        decisions = list(data["decisions"])
        updated_record: dict[str, Any] | None = None
        now = self._now_iso()
        for index, item in enumerate(decisions):
            if isinstance(item, dict) and item.get("id") == normalized_id:
                updated_record = {
                    "id": item["id"],
                    "title": normalized_changes.get("title", item["title"]),
                    "decision": normalized_changes.get("decision", item["decision"]),
                    "reason": normalized_changes.get("reason", item["reason"]),
                    "related_versions": normalized_changes.get("related_versions", item["related_versions"]),
                    "status": normalized_changes.get("status", item["status"]),
                    "created_at": item["created_at"],
                    "updated_at": now,
                }
                decisions[index] = updated_record
                break

        if updated_record is None:
            return self._error_payload("decision_update", "DECISION_NOT_FOUND", "未找到对应 id 的决策记录。")

        updated = {"schema_version": self.SCHEMA_VERSION, "decisions": decisions}
        try:
            write_json_atomic(self.decisions_path, updated)
        except Exception as exc:
            return self._error_payload("decision_update", "DECISION_WRITE_FAILED", f"写入 decisions 失败：{exc}")

        return {
            "ok": True,
            "action": "decision_update",
            "decision_record": updated_record,
            "decision_count": len(decisions),
            "path": self.decisions_rel_path,
        }

    def delete(self, decision_id: Any) -> dict[str, Any]:
        normalized_id = self._normalize_id(decision_id)
        if normalized_id is None:
            return self._error_payload("decision_delete", "INVALID_ID", "id 必须是非空字符串。")

        if not os.path.isfile(self.decisions_path):
            return self._error_payload("decision_delete", "DECISIONS_FILE_NOT_FOUND", "decisions 文件不存在。")

        data = self._load_decisions_file()
        if isinstance(data, MCPDecisionRecordsError):
            return self._error_payload("decision_delete", data.error_code, data.message)

        decisions = list(data["decisions"])
        deleted_index = None
        deleted_record: dict[str, Any] | None = None
        for index, item in enumerate(decisions):
            if isinstance(item, dict) and item.get("id") == normalized_id:
                deleted_index = index
                deleted_record = item
                break

        if deleted_index is None or deleted_record is None:
            return self._error_payload("decision_delete", "DECISION_NOT_FOUND", "未找到对应 id 的决策记录。")

        del decisions[deleted_index]
        updated = {"schema_version": self.SCHEMA_VERSION, "decisions": decisions}
        try:
            write_json_atomic(self.decisions_path, updated)
        except Exception as exc:
            return self._error_payload("decision_delete", "DECISION_WRITE_FAILED", f"写入 decisions 失败：{exc}")

        return {
            "ok": True,
            "action": "decision_delete",
            "deleted_record": deleted_record,
            "decision_count": len(decisions),
            "path": self.decisions_rel_path,
        }

    def _load_decisions_file(self) -> dict[str, Any] | MCPDecisionRecordsError:
        try:
            with open(self.decisions_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as exc:
            return MCPDecisionRecordsError(
                "DECISIONS_JSON_INVALID",
                f"decisions JSON 解析失败：第 {exc.lineno} 行第 {exc.colno} 列，{exc.msg}",
            )
        except FileNotFoundError:
            return MCPDecisionRecordsError("DECISIONS_FILE_NOT_FOUND", "decisions 文件不存在。")
        except Exception as exc:
            return MCPDecisionRecordsError("DECISIONS_READ_ERROR", f"读取 decisions 失败：{exc}")

        if not isinstance(data, dict):
            return MCPDecisionRecordsError("DECISIONS_SCHEMA_INVALID", "decisions 根节点必须是 JSON 对象。")

        schema_version = data.get("schema_version")
        decisions = data.get("decisions")
        if schema_version != self.SCHEMA_VERSION:
            return MCPDecisionRecordsError("DECISIONS_SCHEMA_INVALID", "decisions schema_version 无效。")
        if not isinstance(decisions, list):
            return MCPDecisionRecordsError("DECISIONS_SCHEMA_INVALID", "decisions 必须是数组。")

        normalized_decisions: list[dict[str, Any]] = []
        for index, item in enumerate(decisions):
            if not isinstance(item, dict):
                return MCPDecisionRecordsError("DECISIONS_SCHEMA_INVALID", f"decisions[{index}] 必须是对象。")
            decision_id = self._normalize_id(item.get("id"))
            title = self._normalize_required_text(item.get("title"))
            decision = self._normalize_required_text(item.get("decision"))
            reason = self._normalize_required_text(item.get("reason"))
            related_versions = self._normalize_related_versions(item.get("related_versions"))
            status = self._normalize_required_status(item.get("status"))
            created_at = self._normalize_required_text(item.get("created_at"))
            updated_at = item.get("updated_at")

            if decision_id is None:
                return MCPDecisionRecordsError("DECISIONS_SCHEMA_INVALID", f"decisions[{index}].id 无效。")
            if title is None:
                return MCPDecisionRecordsError("DECISIONS_SCHEMA_INVALID", f"decisions[{index}].title 无效。")
            if decision is None:
                return MCPDecisionRecordsError("DECISIONS_SCHEMA_INVALID", f"decisions[{index}].decision 无效。")
            if reason is None:
                return MCPDecisionRecordsError("DECISIONS_SCHEMA_INVALID", f"decisions[{index}].reason 无效。")
            if related_versions is None:
                return MCPDecisionRecordsError(
                    "DECISIONS_SCHEMA_INVALID",
                    f"decisions[{index}].related_versions 无效。",
                )
            if status is None:
                return MCPDecisionRecordsError("DECISIONS_SCHEMA_INVALID", f"decisions[{index}].status 无效。")
            if created_at is None:
                return MCPDecisionRecordsError("DECISIONS_SCHEMA_INVALID", f"decisions[{index}].created_at 无效。")

            normalized_item = {
                "id": decision_id,
                "title": title,
                "decision": decision,
                "reason": reason,
                "related_versions": related_versions,
                "status": status,
                "created_at": created_at,
            }
            if updated_at is not None:
                normalized_updated_at = self._normalize_required_text(updated_at)
                if normalized_updated_at is None:
                    return MCPDecisionRecordsError(
                        "DECISIONS_SCHEMA_INVALID",
                        f"decisions[{index}].updated_at 无效。",
                    )
                normalized_item["updated_at"] = normalized_updated_at
            normalized_decisions.append(normalized_item)

        return {
            "schema_version": self.SCHEMA_VERSION,
            "decisions": normalized_decisions,
        }

    def _generate_decision_id(self, decisions: list[dict[str, Any]]) -> str:
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        existing_ids = {
            str(item.get("id"))
            for item in decisions
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        max_suffix = 0
        for decision_id in existing_ids:
            match = self.DECISION_ID_PATTERN.match(decision_id)
            if match and match.group(1) == today:
                max_suffix = max(max_suffix, int(match.group(2)))

        suffix = max_suffix + 1
        while True:
            candidate = f"decision-{today}-{suffix:03d}"
            if candidate not in existing_ids:
                return candidate
            suffix += 1

    def _normalize_required_text(self, value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        if not normalized:
            return None
        return normalized

    def _normalize_related_versions(self, value: Any) -> list[str] | None:
        if value is None:
            return []
        if not isinstance(value, list):
            return None
        normalized_versions: list[str] = []
        for item in value:
            if not isinstance(item, str):
                return None
            normalized_item = item.strip()
            if not normalized_item:
                return None
            if normalized_item not in normalized_versions:
                normalized_versions.append(normalized_item)
        return normalized_versions

    def _normalize_add_status(self, status: Any) -> str | None:
        if status is None:
            return self.STATUS_ACTIVE
        return self._normalize_required_status(status)

    def _normalize_required_status(self, status: Any) -> str | None:
        if not isinstance(status, str):
            return None
        normalized = status.strip().lower()
        if normalized in self.VALID_STATUSES:
            return normalized
        return None

    def _normalize_id(self, decision_id: Any) -> str | None:
        if not isinstance(decision_id, str):
            return None
        normalized = decision_id.strip()
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
            "path": self.decisions_rel_path,
        }
