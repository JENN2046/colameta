from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from runner.master_taskbook_registry import (
    MasterTaskbookRegistryError,
    load_master_taskbook_registry,
)


READ_STATUS_OK = "read_ok"
FORBIDDEN_READER_RESULT_FIELDS = frozenset(
    {
        "delivery_state",
        "accepted",
        "executor_authorization",
        "active_master_authority",
        "review_decision_outcome",
    }
)


class MasterTaskbookReaderError(ValueError):
    def __init__(self, error_code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.details = details or {}


def read_master_taskbook(
    project_root: str | Path,
    *,
    registry_path: str | Path | None = None,
    observed_git_head: str | None = None,
    expected_source_refs: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    root = Path(project_root).expanduser().resolve()
    try:
        registry = load_master_taskbook_registry(
            root,
            registry_path=registry_path,
            verify_master_hash=True,
            expected_source_refs=expected_source_refs,
        )
    except MasterTaskbookRegistryError as exc:
        raise MasterTaskbookReaderError(
            "REGISTRY_READ_FAILED",
            "Master Taskbook reader could not load a valid registry.",
            details={"upstream_error_code": exc.error_code, "upstream_details": exc.details},
        ) from exc

    record = registry["record"]
    master_path = Path(str(registry["master_taskbook_path"])).resolve()
    _ensure_inside_project(root, master_path, "master_taskbook_path")
    if not master_path.is_file():
        raise MasterTaskbookReaderError(
            "MASTER_TASKBOOK_MISSING",
            "Registered Master Taskbook path does not exist.",
            details={"master_taskbook_path": str(master_path)},
        )

    raw_bytes = master_path.read_bytes()
    raw_content_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    expected_sha256 = str(record["master_raw_snapshot_sha256"])
    if raw_content_sha256 != expected_sha256:
        raise MasterTaskbookReaderError(
            "MASTER_HASH_MISMATCH",
            "Registered Master Taskbook content hash changed before reader result construction.",
            details={"expected": expected_sha256, "actual": raw_content_sha256},
        )
    try:
        raw_content = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MasterTaskbookReaderError(
            "MASTER_TASKBOOK_NOT_UTF8",
            "Registered Master Taskbook must be readable as UTF-8 text.",
            details={"master_taskbook_path": str(master_path)},
        ) from exc

    result = {
        "registry_record_id": str(record["registry_record_id"]),
        "master_taskbook_path": str(record["master_taskbook_path"]),
        "resolved_master_taskbook_path": str(master_path),
        "path_within_repository": True,
        "raw_content_sha256": raw_content_sha256,
        "raw_content": raw_content,
        "observed_file_size_bytes": len(raw_bytes),
        "observed_git_head": (observed_git_head or str(record["observed_git_head"])).strip(),
        "registry_review_status_boundary": str(record["master_review_status"]),
        "read_status": READ_STATUS_OK,
        "failure_reason_or_none": None,
    }
    _assert_no_forbidden_result_fields(result)
    return result


def _ensure_inside_project(root: Path, path: Path, field: str) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise MasterTaskbookReaderError(
            "PATH_OUTSIDE_PROJECT",
            f"{field} must stay inside the project root.",
            details={"field": field, "path": str(path), "project_root": str(root)},
        ) from exc


def _assert_no_forbidden_result_fields(result: dict[str, Any]) -> None:
    forbidden = sorted(key for key in result if key in FORBIDDEN_READER_RESULT_FIELDS)
    if forbidden:
        raise MasterTaskbookReaderError(
            "FORBIDDEN_READER_RESULT_FIELD",
            "Reader result contains forbidden authority fields.",
            details={"forbidden_fields": forbidden},
        )
