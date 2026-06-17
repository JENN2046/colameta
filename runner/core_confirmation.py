from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


_CONFIRMATION_KNOWN_FIELDS: frozenset[str] = frozenset({
    "required", "prompt", "message", "label",
    "preview_id", "patch_id", "run_id", "workflow_id",
    "action", "tool", "params", "preview_ids",
})

_PREVIEW_RESULT_ID_FIELDS: frozenset[str] = frozenset({
    "preview_id", "patch_id", "run_id", "workflow_id", "preview_ids",
})


@dataclass
class ConfirmationFact:
    required: bool = True
    prompt: str | None = None
    message: str | None = None
    label: str | None = None
    preview_id: str | None = None
    patch_id: str | None = None
    run_id: str | None = None
    workflow_id: str | None = None
    action: str | None = None
    tool: str | None = None
    params: dict[str, Any] | None = None
    preview_ids: list[str] | None = None
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {}
        if self.metadata is not None:
            d.update(self.metadata)
        d["required"] = self.required
        if self.prompt is not None:
            d["prompt"] = self.prompt
        if self.message is not None:
            d["message"] = self.message
        if self.label is not None:
            d["label"] = self.label
        if self.preview_id is not None:
            d["preview_id"] = self.preview_id
        if self.patch_id is not None:
            d["patch_id"] = self.patch_id
        if self.run_id is not None:
            d["run_id"] = self.run_id
        if self.workflow_id is not None:
            d["workflow_id"] = self.workflow_id
        if self.action is not None:
            d["action"] = self.action
        if self.tool is not None:
            d["tool"] = self.tool
        if self.params is not None:
            d["params"] = self.params
        if self.preview_ids is not None:
            d["preview_ids"] = self.preview_ids
        return d


def _as_optional_str(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    return None


def _as_optional_dict(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return dict(value)
    return None


def _as_optional_list(value: Any) -> list[str] | None:
    if isinstance(value, list):
        return [str(v) for v in value if isinstance(v, (str,))]
    return None


def normalize_confirmation_fact(value: Any) -> ConfirmationFact | None:
    if not isinstance(value, dict):
        return None
    metadata: dict[str, Any] = {}
    fact_kw: dict[str, Any] = {}
    for k, v in value.items():
        if k in _CONFIRMATION_KNOWN_FIELDS:
            fact_kw[k] = v
        else:
            metadata[k] = v
    required = bool(fact_kw.get("required", True))
    prompt = _as_optional_str(fact_kw.get("prompt"))
    message = _as_optional_str(fact_kw.get("message"))
    label = _as_optional_str(fact_kw.get("label"))
    preview_id = _as_optional_str(fact_kw.get("preview_id"))
    patch_id = _as_optional_str(fact_kw.get("patch_id"))
    run_id = _as_optional_str(fact_kw.get("run_id"))
    workflow_id = _as_optional_str(fact_kw.get("workflow_id"))
    action = _as_optional_str(fact_kw.get("action"))
    tool = _as_optional_str(fact_kw.get("tool"))
    params = _as_optional_dict(fact_kw.get("params"))
    preview_ids = _as_optional_list(fact_kw.get("preview_ids"))
    return ConfirmationFact(
        required=required,
        prompt=prompt,
        message=message,
        label=label,
        preview_id=preview_id,
        patch_id=patch_id,
        run_id=run_id,
        workflow_id=workflow_id,
        action=action,
        tool=tool,
        params=params,
        preview_ids=preview_ids,
        metadata=metadata if metadata else None,
    )


def confirmation_fact_from_preview_result(result: Any) -> ConfirmationFact | None:
    if not isinstance(result, dict):
        return None
    known = _CONFIRMATION_KNOWN_FIELDS | {"requires_confirmation"}
    has_any = any(k in result for k in _PREVIEW_RESULT_ID_FIELDS)
    has_confirmation = isinstance(result.get("confirmation"), dict)
    has_requires = result.get("requires_confirmation") is True
    if not has_any and not has_confirmation and not has_requires:
        return None
    if has_confirmation:
        return normalize_confirmation_fact(result["confirmation"])
    preview_id = _as_optional_str(result.get("preview_id"))
    patch_id = _as_optional_str(result.get("patch_id"))
    run_id = _as_optional_str(result.get("run_id"))
    workflow_id = _as_optional_str(result.get("workflow_id"))
    preview_ids = _as_optional_list(result.get("preview_ids"))
    metadata: dict[str, Any] = {}
    for k, v in result.items():
        if k not in known:
            metadata[k] = v
    return ConfirmationFact(
        required=True,
        preview_id=preview_id,
        patch_id=patch_id,
        run_id=run_id,
        workflow_id=workflow_id,
        preview_ids=preview_ids,
        metadata=metadata if metadata else None,
    )


def confirmation_fact_from_next_action(action: Any) -> ConfirmationFact | None:
    if not isinstance(action, dict):
        return None
    if not action.get("requires_confirmation"):
        return None
    metadata: dict[str, Any] = {}
    fact_kw: dict[str, Any] = {}
    known = _CONFIRMATION_KNOWN_FIELDS | {"requires_confirmation"}
    for k, v in action.items():
        if k in known:
            fact_kw[k] = v
        else:
            metadata[k] = v
    required = bool(fact_kw.get("required", True))
    prompt = _as_optional_str(fact_kw.get("prompt"))
    message = _as_optional_str(fact_kw.get("message"))
    label = _as_optional_str(fact_kw.get("label"))
    preview_id = _as_optional_str(fact_kw.get("preview_id"))
    patch_id = _as_optional_str(fact_kw.get("patch_id"))
    run_id = _as_optional_str(fact_kw.get("run_id"))
    workflow_id = _as_optional_str(fact_kw.get("workflow_id"))
    action_val = _as_optional_str(fact_kw.get("action"))
    tool = _as_optional_str(fact_kw.get("tool"))
    params = _as_optional_dict(fact_kw.get("params"))
    preview_ids = _as_optional_list(fact_kw.get("preview_ids"))
    return ConfirmationFact(
        required=required,
        prompt=prompt,
        message=message,
        label=label,
        preview_id=preview_id,
        patch_id=patch_id,
        run_id=run_id,
        workflow_id=workflow_id,
        action=action_val,
        tool=tool,
        params=params,
        preview_ids=preview_ids,
        metadata=metadata if metadata else None,
    )


def confirmation_fact_from_store(
    store: Any,
    preview_id: str,
) -> ConfirmationFact | None:
    """Read-boundary helper: normalize a stored artifact to ConfirmationFact.

    Accepts any object with a ``read(preview_id) -> dict | None`` method
    (duck-typed, no direct import of ConfirmationStore).
    """
    payload = store.read(preview_id)
    if not isinstance(payload, dict):
        return None
    return confirmation_fact_from_preview_artifact(payload)


def confirmation_status_fact(
    store: Any,
    preview_id: str,
) -> dict[str, Any]:
    """Read-boundary helper: enrich store status with ConfirmationFact data.

    Accepts any object with ``status(preview_id) -> dict`` and
    ``read(preview_id) -> dict | None`` methods (duck-typed).
    """
    status = store.status(preview_id)
    if not isinstance(status, dict):
        return {"ok": False, "error_code": "INVALID_STORE"}
    if not status.get("ok") or not status.get("exists"):
        return dict(status)
    fact = confirmation_fact_from_store(store, preview_id)
    if fact is not None:
        result = dict(status)
        result["confirmation"] = fact.to_dict()
        return result
    return dict(status)


def confirmation_apply_guard(
    store: Any,
    preview_id: str,
    *,
    project_root: str | None = None,
    payload: Any | None = None,
) -> dict[str, Any]:
    """Pure read-only apply guard that validates a stored preview artifact.

    Accepts any object with ``read(preview_id) -> dict | None`` and
    ``is_expired(payload) -> bool`` methods (duck-typed, no hard import of
    ConfirmationStore). Callers that already read the preview can pass
    ``payload`` to avoid a second store read.

    Returns dict with keys:
        ok                 — bool
        payload            — dict | None  (artifact data when ok=True)
        confirmation       — dict | None  (ConfirmationFact.to_dict() when ok=True)
        error_code         — str | None   (PREVIEW_NOT_FOUND / PROJECT_MISMATCH / PREVIEW_EXPIRED)
        preview_id         — str          (stripped preview_id for caller convenience)

    Does NOT delete, write, or mutate artifacts. Preserves existing store
    semantics for read, project validation, and expiry.
    """
    preview_id = preview_id.strip()

    if payload is None:
        payload = store.read(preview_id)
    if not isinstance(payload, dict):
        return {
            "ok": False, "payload": None, "confirmation": None,
            "error_code": "PREVIEW_NOT_FOUND", "preview_id": preview_id,
        }

    if project_root is not None:
        if payload.get("project_root") != project_root:
            return {
                "ok": False, "payload": payload, "confirmation": None,
                "error_code": "PROJECT_MISMATCH", "preview_id": preview_id,
            }

    if store.is_expired(payload):
        return {
            "ok": False, "payload": payload, "confirmation": None,
            "error_code": "PREVIEW_EXPIRED", "preview_id": preview_id,
        }

    fact = confirmation_fact_from_preview_artifact(payload)
    return {
        "ok": True, "payload": payload,
        "confirmation": fact.to_dict() if fact is not None else None,
        "error_code": None, "preview_id": preview_id,
    }


def confirmation_guard_reports_expired_before_mismatch(guard: dict[str, Any], is_expired: Any) -> bool:
    """Return True when a caller must preserve legacy expired-first ordering.

    ``confirmation_apply_guard`` checks project mismatch before expiry.  A few
    legacy apply/run paths historically returned PREVIEW_EXPIRED before project
    mismatch when both conditions were true.  Keep that compatibility shim
    explicit and shared instead of duplicating inline conditionals.
    """
    if guard.get("error_code") != "PROJECT_MISMATCH":
        return False
    payload = guard.get("payload")
    if not isinstance(payload, dict) or not callable(is_expired):
        return False
    return bool(is_expired(payload))


def confirmation_fact_from_preview_artifact(artifact: Any) -> ConfirmationFact | None:
    if not isinstance(artifact, dict):
        return None
    preview_id = _as_optional_str(artifact.get("preview_id"))
    if not preview_id:
        return None
    known = _CONFIRMATION_KNOWN_FIELDS | {"artifact_kind", "requires_confirmation",
                                           "created_at", "expires_at", "project_root",
                                           "content"}
    metadata: dict[str, Any] = {}
    for k, v in artifact.items():
        if k not in known:
            metadata[k] = v
    return ConfirmationFact(
        required=True,
        preview_id=preview_id,
        patch_id=_as_optional_str(artifact.get("patch_id")),
        run_id=_as_optional_str(artifact.get("run_id")),
        workflow_id=_as_optional_str(artifact.get("workflow_id")),
        action=_as_optional_str(artifact.get("action")),
        tool=_as_optional_str(artifact.get("tool")),
        params=_as_optional_dict(artifact.get("params")),
        preview_ids=_as_optional_list(artifact.get("preview_ids")),
        metadata=metadata if metadata else None,
    )


def confirmation_fact_from_commit_preview(preview: Any) -> ConfirmationFact | None:
    """Normalize a Git commit preview record to ConfirmationFact.

    Git commit previews keep their own preview file format. This adapter
    preserves the preview identifier and message while carrying the rest of
    the record as metadata for read-only confirmation coverage.
    """
    if not isinstance(preview, dict):
        return None
    preview_id = _as_optional_str(preview.get("preview_id"))
    if not preview_id:
        return None
    metadata: dict[str, Any] = {}
    for k, v in preview.items():
        if k not in {"preview_id", "message"}:
            metadata[k] = v
    return ConfirmationFact(
        required=True,
        preview_id=preview_id,
        message=_as_optional_str(preview.get("message")),
        metadata=metadata if metadata else None,
    )


def _parse_commit_preview_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except Exception:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def confirmation_git_commit_preview_guard(
    preview: Any,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Read-only guard for Git commit preview records.

    Returns a structured result with the normalized confirmation fact when the
    preview is usable, and preserves the existing Git commit error codes for
    invalid, committed, or expired preview records.
    """
    if not isinstance(preview, dict):
        return {
            "ok": False,
            "confirmation": None,
            "error_code": "PREVIEW_INVALID",
            "message": "预览文件格式无效。",
            "preview_id": None,
        }

    preview_fact = confirmation_fact_from_commit_preview(preview)
    preview_id = preview_fact.preview_id if preview_fact is not None else _as_optional_str(preview.get("preview_id"))
    if preview.get("committed_at"):
        return {
            "ok": False,
            "confirmation": preview_fact.to_dict() if preview_fact is not None else None,
            "error_code": "PREVIEW_ALREADY_COMMITTED",
            "message": "该 preview 已完成提交。",
            "preview_id": preview_id,
            "commit_hash": preview.get("commit_hash"),
        }

    expires_at = _parse_commit_preview_time(preview.get("expires_at"))
    current_time = now or datetime.now(timezone.utc)
    if expires_at is None or expires_at <= current_time:
        return {
            "ok": False,
            "confirmation": preview_fact.to_dict() if preview_fact is not None else None,
            "error_code": "PREVIEW_EXPIRED",
            "message": "preview 已过期，请重新创建。",
            "preview_id": preview_id,
        }

    return {
        "ok": True,
        "confirmation": preview_fact.to_dict() if preview_fact is not None else None,
        "error_code": None,
        "message": None,
        "preview_id": preview_id,
    }
