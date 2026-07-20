from __future__ import annotations

import contextlib
import contextvars
import hashlib
import json
from typing import Any, Iterator


_CURRENT_ARTIFACT_BINDING: contextvars.ContextVar[tuple[str, str] | None] = (
    contextvars.ContextVar("colameta_operator_artifact_binding", default=None)
)


def canonical_artifact_digest(payload: object) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@contextlib.contextmanager
def operator_artifact_binding_scope(preview_id: str, digest: str) -> Iterator[None]:
    token = _CURRENT_ARTIFACT_BINDING.set((preview_id, digest))
    try:
        yield
    finally:
        _CURRENT_ARTIFACT_BINDING.reset(token)


def bound_artifact_error(preview_id: str, payload: Any) -> str | None:
    binding = _CURRENT_ARTIFACT_BINDING.get()
    if binding is None:
        return None
    expected_id, expected_digest = binding
    if preview_id != expected_id:
        return "OPERATOR_PREVIEW_CHANGED"
    try:
        actual_digest = canonical_artifact_digest(payload)
    except (TypeError, ValueError):
        return "OPERATOR_PREVIEW_CHANGED"
    if actual_digest != expected_digest:
        return "OPERATOR_PREVIEW_CHANGED"
    return None
