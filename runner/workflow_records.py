import hashlib
import json
import os
import re
import tempfile
import uuid
from datetime import datetime, timezone
from typing import Any

from runner.runner_paths import resolve_project_runner_path

WORKFLOWS_SUBDIR = os.path.join("runtime", "workflows")
WORKFLOW_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_\-]{1,64}$")

SENSITIVE_FIELD_KEYS = {
    "old_text", "new_text", "patch_text", "spec_json", "plan_json",
    "prompt", "first_version_prompt", "markdown", "content", "report",
    "new_content", "section_content",
}


def _sha256_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _generate_workflow_id() -> str:
    return uuid.uuid4().hex[:16]


def _validate_workflow_id(workflow_id: str) -> None:
    if not isinstance(workflow_id, str) or not workflow_id.strip():
        raise ValueError("workflow_id must be a non-empty string")
    if not WORKFLOW_ID_PATTERN.fullmatch(workflow_id):
        raise ValueError(f"workflow_id contains unsafe characters: {workflow_id!r}")
    if ".." in workflow_id:
        raise ValueError("workflow_id must not contain '..'")
    if "/" in workflow_id or "\\" in workflow_id:
        raise ValueError("workflow_id must not contain path separators")


def _atomic_write(filepath: str, data: dict[str, Any]) -> None:
    dirpath = os.path.dirname(filepath)
    os.makedirs(dirpath, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(suffix=".tmp", dir=dirpath, prefix="wf_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, filepath)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
        raise


def _read_json_safe(filepath: str) -> dict[str, Any] | None:
    try:
        if not os.path.isfile(filepath):
            return None
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _is_safe_workflow_path(workflows_dir: str, candidate: str) -> bool:
    root = os.path.realpath(workflows_dir)
    target = os.path.realpath(candidate)
    return target == root or target.startswith(root + os.sep)


def _deep_sanitize_summary(summary: Any) -> Any:
    if isinstance(summary, dict):
        result: dict[str, Any] = {}
        for key, val in summary.items():
            if key in SENSITIVE_FIELD_KEYS and isinstance(val, str) and val:
                result[key] = {
                    "present": True,
                    "length": len(val),
                    "sha256": _sha256_of(val),
                    "kind": key,
                }
            elif isinstance(val, (dict, list)):
                result[key] = _deep_sanitize_summary(val)
            else:
                result[key] = val
        return result
    if isinstance(summary, list):
        return [_deep_sanitize_summary(item) for item in summary]
    return summary


def _sanitize_record(record: dict[str, Any]) -> dict[str, Any]:
    steps_raw = record.get("steps", [])
    sanitized_steps: list[dict[str, Any]] = []
    for step in steps_raw:
        if isinstance(step, dict):
            s = dict(step)
            if "inputs_summary" in s:
                s["inputs_summary"] = _deep_sanitize_summary(s["inputs_summary"])
            if "outputs_summary" in s:
                s["outputs_summary"] = _deep_sanitize_summary(s["outputs_summary"])
            sanitized_steps.append(s)
        else:
            sanitized_steps.append(step)

    safe = {
        "workflow_id": record.get("workflow_id", ""),
        "workflow_name": record.get("workflow_name", ""),
        "created_at": record.get("created_at", ""),
        "updated_at": record.get("updated_at", ""),
        "finished_at": record.get("finished_at"),
        "status": record.get("status", ""),
        "risk_level": record.get("risk_level", "info"),
        "tool_name": record.get("tool_name", ""),
        "project_root": record.get("project_root", ""),
        "git_head_before": record.get("git_head_before"),
        "git_head_after": record.get("git_head_after"),
        "inputs_summary": _deep_sanitize_summary(record.get("inputs_summary", {})),
        "outputs_summary": _deep_sanitize_summary(record.get("outputs_summary", {})),
        "changed_files": record.get("changed_files", []),
        "diff_hash": record.get("diff_hash"),
        "stop_reason": record.get("stop_reason"),
        "warnings": record.get("warnings", []),
        "blockers": record.get("blockers", []),
        "preview_ids": record.get("preview_ids", []),
        "steps": sanitized_steps,
    }
    return safe


def _summarize_run(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "workflow_id": record.get("workflow_id", ""),
        "workflow_name": record.get("workflow_name", ""),
        "created_at": record.get("created_at", ""),
        "updated_at": record.get("updated_at", ""),
        "finished_at": record.get("finished_at"),
        "status": record.get("status", ""),
        "risk_level": record.get("risk_level", "info"),
        "tool_name": record.get("tool_name", ""),
        "stop_reason": record.get("stop_reason"),
        "preview_ids": record.get("preview_ids", []),
        "changed_files_count": len(record.get("changed_files", [])),
        "step_count": len(record.get("steps", [])),
    }


class WorkflowRecordStore:
    def __init__(self, project_root: str):
        self.project_root = os.path.abspath(os.path.expanduser(project_root))
        self.workflows_dir = resolve_project_runner_path(self.project_root, WORKFLOWS_SUBDIR)

    def _workflow_path(self, workflow_id: str) -> str:
        _validate_workflow_id(workflow_id)
        return os.path.join(self.workflows_dir, f"{workflow_id}.json")

    def create_run(
        self,
        workflow_name: str,
        tool_name: str,
        action: str,
        inputs_summary: dict[str, Any] | None = None,
        risk_level: str = "info",
    ) -> dict[str, Any]:
        workflow_id = _generate_workflow_id()
        now = _now_iso()
        step_id = uuid.uuid4().hex[:12]

        step = {
            "step_id": step_id,
            "started_at": now,
            "finished_at": now,
            "tool_name": tool_name,
            "action": action,
            "status": "running",
            "risk_level": risk_level,
            "inputs_summary": inputs_summary or {},
            "outputs_summary": {},
            "changed_files": [],
            "diff_hash": None,
            "preview_ids": [],
            "warnings": [],
            "blockers": [],
            "error_code": None,
            "stop_reason": None,
        }

        record: dict[str, Any] = {
            "workflow_id": workflow_id,
            "workflow_name": workflow_name,
            "created_at": now,
            "updated_at": now,
            "finished_at": None,
            "status": "running",
            "risk_level": risk_level,
            "steps": [step],
            "inputs_summary": inputs_summary or {},
            "outputs_summary": {},
            "changed_files": [],
            "diff_hash": None,
            "stop_reason": None,
            "warnings": [],
            "blockers": [],
            "preview_ids": [],
            "tool_name": tool_name,
            "project_root": self.project_root,
            "git_head_before": None,
            "git_head_after": None,
        }

        try:
            filepath = self._workflow_path(workflow_id)
            _atomic_write(filepath, record)
        except Exception as e:
            return {"ok": False, "error": str(e), "workflow_id": workflow_id}

        return {"ok": True, "workflow_id": workflow_id, "run": record, "step_id": step_id}

    def append_step(
        self,
        workflow_id: str,
        step: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            _validate_workflow_id(workflow_id)
        except ValueError as e:
            return {"ok": False, "error": str(e)}

        filepath = self._workflow_path(workflow_id)
        if not _is_safe_workflow_path(self.workflows_dir, filepath):
            return {"ok": False, "error": "path traversal detected"}

        record = _read_json_safe(filepath)
        if record is None:
            return {"ok": False, "error": "workflow not found"}

        steps = record.get("steps", [])
        steps.append(step)
        record["steps"] = steps
        record["updated_at"] = _now_iso()

        preview_ids = record.get("preview_ids", [])
        step_preview_ids = step.get("preview_ids", [])
        for pid in step_preview_ids:
            if pid not in preview_ids:
                preview_ids.append(pid)
        record["preview_ids"] = preview_ids

        step_changed = step.get("changed_files", [])
        if step_changed:
            existing_changed = record.get("changed_files", [])
            for f in step_changed:
                if f not in existing_changed:
                    existing_changed.append(f)
            record["changed_files"] = existing_changed

        step_diff = step.get("diff_hash")
        if step_diff:
            record["diff_hash"] = step_diff

        try:
            _atomic_write(filepath, record)
        except Exception as e:
            return {"ok": False, "error": str(e)}

        return {"ok": True, "workflow_id": workflow_id, "run": record}

    def finish_run(
        self,
        workflow_id: str,
        status: str,
        outputs_summary: dict[str, Any] | None = None,
        stop_reason: str | None = None,
        warnings: list[str] | None = None,
        blockers: list[str] | None = None,
        step_outputs_summary: dict[str, Any] | None = None,
        step_changed_files: list[str] | None = None,
        step_diff_hash: str | None = None,
        step_preview_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        try:
            _validate_workflow_id(workflow_id)
        except ValueError as e:
            return {"ok": False, "error": str(e)}

        filepath = self._workflow_path(workflow_id)
        if not _is_safe_workflow_path(self.workflows_dir, filepath):
            return {"ok": False, "error": "path traversal detected"}

        record = _read_json_safe(filepath)
        if record is None:
            return {"ok": False, "error": "workflow not found"}

        now = _now_iso()
        record["status"] = status
        record["finished_at"] = now
        record["updated_at"] = now
        if outputs_summary is not None:
            record["outputs_summary"] = outputs_summary
        if stop_reason is not None:
            record["stop_reason"] = stop_reason
        if warnings is not None:
            record["warnings"] = warnings
        if blockers is not None:
            record["blockers"] = blockers

        steps = record.get("steps", [])
        if steps:
            steps[-1]["status"] = status
            steps[-1]["finished_at"] = now
            if stop_reason:
                steps[-1]["stop_reason"] = stop_reason
            if step_outputs_summary is not None:
                steps[-1]["outputs_summary"] = step_outputs_summary
            if step_changed_files is not None:
                steps[-1]["changed_files"] = step_changed_files
            if step_diff_hash is not None:
                steps[-1]["diff_hash"] = step_diff_hash
            if step_preview_ids is not None:
                steps[-1]["preview_ids"] = step_preview_ids
            record["steps"] = steps

        if step_preview_ids:
            existing_pids = record.get("preview_ids", [])
            for pid in step_preview_ids:
                if pid not in existing_pids:
                    existing_pids.append(pid)
            record["preview_ids"] = existing_pids

        if step_changed_files:
            existing_files = record.get("changed_files", [])
            for f in step_changed_files:
                if f not in existing_files:
                    existing_files.append(f)
            record["changed_files"] = existing_files

        if step_diff_hash:
            record["diff_hash"] = step_diff_hash

        try:
            _atomic_write(filepath, record)
        except Exception as e:
            return {"ok": False, "error": str(e)}

        return {"ok": True, "workflow_id": workflow_id, "run": record}

    def find_run_by_preview_id(self, preview_id: str) -> dict[str, Any] | None:
        if not isinstance(preview_id, str) or not preview_id.strip():
            return None
        if not os.path.isdir(self.workflows_dir):
            return None
        try:
            for fname in os.listdir(self.workflows_dir):
                if not fname.endswith(".json"):
                    continue
                filepath = os.path.join(self.workflows_dir, fname)
                if not os.path.isfile(filepath):
                    continue
                if not _is_safe_workflow_path(self.workflows_dir, filepath):
                    continue
                record = _read_json_safe(filepath)
                if record is None:
                    continue
                preview_ids = record.get("preview_ids", [])
                if preview_id in preview_ids:
                    return record
        except Exception:
            pass
        return None

    def list_runs(
        self,
        limit: int = 20,
        workflow_name: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(limit, int) or limit < 1:
            limit = 20
        limit = min(limit, 100)

        warnings: list[str] = []
        runs: list[dict[str, Any]] = []

        if not os.path.isdir(self.workflows_dir):
            return {"ok": True, "runs": [], "warnings": warnings}

        try:
            entries = sorted(
                os.listdir(self.workflows_dir),
                reverse=True,
            )
        except Exception as e:
            return {"ok": True, "runs": [], "warnings": [f"cannot list workflows: {e}"]}

        for fname in entries:
            if not fname.endswith(".json"):
                continue
            if len(runs) >= limit:
                break
            filepath = os.path.join(self.workflows_dir, fname)
            if not os.path.isfile(filepath):
                continue
            if not _is_safe_workflow_path(self.workflows_dir, filepath):
                continue
            record = _read_json_safe(filepath)
            if record is None:
                warnings.append(f"skipping corrupted workflow file: {fname}")
                continue

            if workflow_name is not None:
                if record.get("workflow_name") != workflow_name:
                    continue
            if status is not None:
                if record.get("status") != status:
                    continue

            runs.append(_summarize_run(record))

        return {"ok": True, "runs": runs, "warnings": warnings if warnings else None}

    def get_run(self, workflow_id: str) -> dict[str, Any]:
        try:
            _validate_workflow_id(workflow_id)
        except ValueError as e:
            return {"ok": False, "error_code": "INVALID_WORKFLOW_ID", "message": str(e)}

        filepath = self._workflow_path(workflow_id)
        if not _is_safe_workflow_path(self.workflows_dir, filepath):
            return {"ok": False, "error_code": "PATH_TRAVERSAL", "message": "path traversal detected"}

        record = _read_json_safe(filepath)
        if record is None:
            return {"ok": False, "error_code": "WORKFLOW_NOT_FOUND", "message": f"workflow not found: {workflow_id}"}

        return {"ok": True, "run": _sanitize_record(record)}
