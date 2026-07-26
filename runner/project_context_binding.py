"""Shared, bounded project-context bindings for confirmation-gated work.

The MCP surface has several operations that deliberately stop at a preview and
later perform a side effect.  A preview identifier alone is not enough to
explain whether it still names the same checkout.  This module owns the small,
non-sensitive set of facts every public confirmation boundary can re-check:

``project_name``, ``branch``, ``head``, ``runner_plan``,
``current_version``, ``review_unit``, and ``workflow_intent``.

It never returns raw Runner state, filesystem paths, credentials, or file
contents.  The file helpers below are deliberately no-follow and bounded so a
context read cannot become a general local-state read primitive.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from typing import Any, Iterable

from runner.project_identity import build_project_identity
from runner.runner_paths import (
    resolve_project_runner_path,
    resolve_project_runner_plan_path,
)


PROJECT_CONTEXT_BINDING_SCHEMA_VERSION = "colameta.project_context_binding.v1"
PROJECT_CONTEXT_BINDING_MAX_PLAN_BYTES = 2_000_000
PROJECT_CONTEXT_BINDING_MAX_STATE_BYTES = 512_000

BASE_CONTEXT_BINDING_FIELDS: tuple[str, ...] = (
    "project_name",
    "branch",
    "head",
    "runner_plan",
    "current_version",
)
OPERATION_CONTEXT_BINDING_FIELDS: tuple[str, ...] = (
    *BASE_CONTEXT_BINDING_FIELDS,
    "review_unit",
    "workflow_intent",
)


class ProjectContextBindingError(ValueError):
    """A public, non-sensitive context-binding failure."""

    def __init__(
        self,
        error_code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.details = details or {}


def collect_project_context_binding(
    project_root: str,
    *,
    project_name: str | None = None,
    review_unit: str | None = None,
    workflow_intent: str | None = None,
) -> dict[str, Any]:
    """Collect the exact public facts which identify one project checkout.

    ``review_unit`` and ``workflow_intent`` are optional so the same collector
    can serve both the manifest-read contract (base fields only) and operation
    confirmation contracts (all seven fields).
    """

    normalized_root = os.path.realpath(os.path.abspath(os.path.expanduser(project_root)))
    identity = build_project_identity(normalized_root)
    resolved_project_name = (
        project_name.strip()
        if isinstance(project_name, str) and project_name.strip()
        else str(identity.get("project_name") or "").strip()
    )
    plan_path = resolve_project_runner_plan_path(normalized_root)
    plan_digest = _sha256_regular_file(
        plan_path,
        max_bytes=PROJECT_CONTEXT_BINDING_MAX_PLAN_BYTES,
    )
    plan_present = plan_digest is not None
    binding: dict[str, Any] = {
        "project_name": resolved_project_name,
        "branch": _optional_text(identity.get("git_branch")),
        "head": _optional_text(identity.get("git_head")),
        "runner_plan": {
            "mode": "managed" if plan_present else "source-only",
            "plan_sha256": plan_digest,
        },
        "current_version": _bounded_current_version(normalized_root) if plan_present else None,
    }
    if review_unit is not None:
        binding["review_unit"] = _required_operation_text(review_unit, "review_unit", 160)
    if workflow_intent is not None:
        binding["workflow_intent"] = _required_operation_text(
            workflow_intent,
            "workflow_intent",
            160,
        )
    return binding


def require_operation_context_binding(
    value: Any,
    *,
    project_root: str,
    project_name: str | None,
    review_unit: str,
    workflow_intent: str,
) -> dict[str, Any]:
    """Fail closed unless a supplied operation binding names this checkout.

    The expected operation identity is server-owned.  A caller can copy the
    binding returned by a preview, but cannot reuse it for another kind of
    operation or a different review unit.
    """

    expected = _normalize_operation_binding(
        value,
        expected_review_unit=review_unit,
        expected_workflow_intent=workflow_intent,
    )
    actual = collect_project_context_binding(
        project_root,
        project_name=project_name,
        review_unit=review_unit,
        workflow_intent=workflow_intent,
    )
    unavailable = [
        field
        for field in ("project_name", "branch", "head")
        if not isinstance(actual.get(field), str) or not str(actual.get(field)).strip()
    ]
    if unavailable:
        raise ProjectContextBindingError(
            "CONTEXT_BINDING_UNAVAILABLE",
            "当前项目缺少建立确认性操作上下文所需的事实，已停止执行。",
            {"unavailable_fields": unavailable},
        )
    mismatches = context_binding_mismatches(
        expected,
        actual,
        fields=OPERATION_CONTEXT_BINDING_FIELDS,
    )
    if mismatches:
        raise ProjectContextBindingError(
            "CONTEXT_BINDING_MISMATCH",
            "确认性操作的项目上下文已变化或不属于该操作，已停止执行。",
            {"mismatches": mismatches},
        )
    return actual


def context_binding_mismatches(
    expected: dict[str, Any],
    actual: dict[str, Any],
    *,
    fields: Iterable[str] = BASE_CONTEXT_BINDING_FIELDS,
) -> list[dict[str, Any]]:
    """Return public mismatch facts without exposing local paths or content."""

    return [
        {
            "field": field,
            "expected": expected.get(field),
            "actual": actual.get(field),
        }
        for field in fields
        if expected.get(field) != actual.get(field)
    ]


def context_binding_sha256(value: dict[str, Any]) -> str:
    """Return a stable digest for logs and receipts without storing the value."""

    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _normalize_operation_binding(
    value: Any,
    *,
    expected_review_unit: str,
    expected_workflow_intent: str,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProjectContextBindingError(
            "CONTEXT_BINDING_MISMATCH",
            "确认性操作必须原样携带 preview 返回的 context_binding。",
            {"missing_fields": list(OPERATION_CONTEXT_BINDING_FIELDS)},
        )
    missing = [field for field in OPERATION_CONTEXT_BINDING_FIELDS if field not in value]
    unexpected = sorted(set(value) - set(OPERATION_CONTEXT_BINDING_FIELDS))
    if missing or unexpected:
        details: dict[str, Any] = {}
        if missing:
            details["missing_fields"] = missing
        if unexpected:
            details["unexpected_fields"] = unexpected
        raise ProjectContextBindingError(
            "CONTEXT_BINDING_MISMATCH",
            "context_binding 必须精确包含确认性操作的全部绑定字段。",
            details,
        )

    project_name = _required_operation_text(value.get("project_name"), "project_name", 128)
    branch = _required_operation_text(value.get("branch"), "branch", 255)
    head = _required_operation_text(value.get("head"), "head", 128).lower()
    if len(head) < 40 or any(char not in "0123456789abcdef" for char in head):
        raise ProjectContextBindingError(
            "CONTEXT_BINDING_MISMATCH",
            "context_binding.head 必须是完整 Git commit SHA。",
            {"field": "head"},
        )
    runner_plan = _normalize_runner_plan(value.get("runner_plan"))
    current_version_value = value.get("current_version")
    current_version = (
        _required_operation_text(current_version_value, "current_version", 128)
        if current_version_value is not None
        else None
    )
    review_unit = _required_operation_text(value.get("review_unit"), "review_unit", 160)
    workflow_intent = _required_operation_text(
        value.get("workflow_intent"),
        "workflow_intent",
        160,
    )
    normalized = {
        "project_name": project_name,
        "branch": branch,
        "head": head,
        "runner_plan": runner_plan,
        "current_version": current_version,
        "review_unit": review_unit,
        "workflow_intent": workflow_intent,
    }
    expected_identity = {
        "review_unit": _required_operation_text(expected_review_unit, "review_unit", 160),
        "workflow_intent": _required_operation_text(
            expected_workflow_intent,
            "workflow_intent",
            160,
        ),
    }
    identity_mismatches = context_binding_mismatches(
        expected_identity,
        normalized,
        fields=("review_unit", "workflow_intent"),
    )
    if identity_mismatches:
        raise ProjectContextBindingError(
            "CONTEXT_BINDING_MISMATCH",
            "context_binding 不能复用于另一个 workflow 或操作单元。",
            {"mismatches": identity_mismatches},
        )
    return normalized


def _normalize_runner_plan(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"mode", "plan_sha256"}:
        raise ProjectContextBindingError(
            "CONTEXT_BINDING_MISMATCH",
            "context_binding.runner_plan 必须精确包含 mode 与 plan_sha256。",
            {"field": "runner_plan"},
        )
    mode = value.get("mode")
    plan_sha256 = value.get("plan_sha256")
    if mode not in {"managed", "source-only"}:
        raise ProjectContextBindingError(
            "CONTEXT_BINDING_MISMATCH",
            "context_binding.runner_plan.mode 必须是 managed 或 source-only。",
            {"field": "runner_plan.mode"},
        )
    if plan_sha256 is None:
        if mode != "source-only":
            raise ProjectContextBindingError(
                "CONTEXT_BINDING_MISMATCH",
                "managed runner_plan 必须携带 plan_sha256。",
                {"field": "runner_plan.plan_sha256"},
            )
        return {"mode": mode, "plan_sha256": None}
    if not isinstance(plan_sha256, str):
        raise ProjectContextBindingError(
            "CONTEXT_BINDING_MISMATCH",
            "context_binding.runner_plan.plan_sha256 必须是 SHA-256 摘要。",
            {"field": "runner_plan.plan_sha256"},
        )
    digest = plan_sha256.strip().lower()
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ProjectContextBindingError(
            "CONTEXT_BINDING_MISMATCH",
            "context_binding.runner_plan.plan_sha256 必须是 SHA-256 摘要。",
            {"field": "runner_plan.plan_sha256"},
        )
    return {"mode": mode, "plan_sha256": digest}


def _required_operation_text(value: Any, field: str, max_chars: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > max_chars:
        raise ProjectContextBindingError(
            "CONTEXT_BINDING_MISMATCH",
            f"context_binding.{field} 必须是非空且长度受限的字符串。",
            {"field": field},
        )
    text = value.strip()
    if any(ord(char) < 32 for char in text):
        raise ProjectContextBindingError(
            "CONTEXT_BINDING_MISMATCH",
            f"context_binding.{field} 不能包含控制字符。",
            {"field": field},
        )
    return text


def _optional_text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _sha256_regular_file(path: str, *, max_bytes: int) -> str | None:
    raw = _read_regular_file_bytes(path, max_bytes=max_bytes)
    return hashlib.sha256(raw).hexdigest() if raw is not None else None


def _bounded_current_version(project_root: str) -> str | None:
    state_path = resolve_project_runner_path(project_root, "state.json")
    raw = _read_regular_file_bytes(
        state_path,
        max_bytes=PROJECT_CONTEXT_BINDING_MAX_STATE_BYTES,
    )
    if raw is None:
        return None
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    value = payload.get("current_version") if isinstance(payload, dict) else None
    return _optional_text(value)


def _read_regular_file_bytes(path: str, *, max_bytes: int) -> bytes | None:
    try:
        info = os.lstat(path)
        if (
            stat.S_ISLNK(info.st_mode)
            or not stat.S_ISREG(info.st_mode)
            or info.st_size > max_bytes
        ):
            return None
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(path, flags)
        with os.fdopen(fd, "rb") as handle:
            opened = os.fstat(handle.fileno())
            if not stat.S_ISREG(opened.st_mode) or opened.st_size > max_bytes:
                return None
            raw = handle.read(max_bytes + 1)
        return raw if len(raw) <= max_bytes else None
    except OSError:
        return None
