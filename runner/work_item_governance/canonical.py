from __future__ import annotations

import hashlib
import json
import os
from typing import Any

from runner.work_item_governance.contracts import MAX_JSON_BYTES
from runner.work_item_governance.errors import WorkItemGovernanceError


def canonical_json(value: Any, *, max_bytes: int = MAX_JSON_BYTES) -> str:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise WorkItemGovernanceError(
            "JSON_NOT_CANONICALIZABLE",
            "Payload must be finite, JSON-serializable data.",
            details={"reason": str(exc)},
        ) from exc
    size = len(encoded.encode("utf-8"))
    if size > max_bytes:
        raise WorkItemGovernanceError(
            "JSON_TOO_LARGE",
            "Canonical JSON exceeds the allowed size.",
            details={"max_bytes": max_bytes, "actual_bytes": size},
        )
    return encoded


def canonical_sha256(value: Any, *, max_bytes: int = MAX_JSON_BYTES) -> str:
    return hashlib.sha256(canonical_json(value, max_bytes=max_bytes).encode("utf-8")).hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: str | os.PathLike[str]) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
