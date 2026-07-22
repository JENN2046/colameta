"""Bounded, in-memory continuation artifacts for oversized MCP results.

The store deliberately keeps artifacts process-local and short-lived.  A result
artifact is not a durable project record, preview, or authorization token; it
only lets an MCP client continue reading a result that was too large to return
in one tool response.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import secrets
import threading
from typing import Any, Callable


@dataclass(frozen=True)
class ResultArtifactHandle:
    artifact_id: str
    tool: str
    page_count: int
    content_sha256: str
    created_at: str
    expires_at: str


@dataclass(frozen=True)
class ResultArtifactPage:
    artifact_id: str
    tool: str
    page: int
    page_count: int
    page_char_start: int
    page_char_end: int
    content_sha256: str
    expires_at: str
    content: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "tool": self.tool,
            "page": self.page,
            "page_count": self.page_count,
            "page_char_start": self.page_char_start,
            "page_char_end": self.page_char_end,
            "content_sha256": self.content_sha256,
            "expires_at": self.expires_at,
            "content": self.content,
        }


@dataclass(frozen=True)
class _StoredResultArtifact:
    handle: ResultArtifactHandle
    expires_at: datetime
    content: str


class MCPResultArtifactStore:
    """Thread-safe, bounded storage for sanitized tool-result continuations."""

    def __init__(
        self,
        *,
        ttl_seconds: int = 900,
        page_chars: int = 12000,
        max_items: int = 64,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self._ttl_seconds = max(1, int(ttl_seconds))
        self._page_chars = max(1, int(page_chars))
        self._max_items = max(1, int(max_items))
        self._now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        self._items: dict[str, _StoredResultArtifact] = {}
        self._lock = threading.RLock()

    def put(self, *, tool: str, payload: dict[str, Any]) -> ResultArtifactHandle | None:
        """Store a JSON-serializable result and return an opaque read handle."""

        try:
            content = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        except (TypeError, ValueError):
            return None

        now = self._now()
        expires_at = now + timedelta(seconds=self._ttl_seconds)
        artifact_id = secrets.token_urlsafe(24)
        page_count = max(1, (len(content) + self._page_chars - 1) // self._page_chars)
        handle = ResultArtifactHandle(
            artifact_id=artifact_id,
            tool=str(tool or "unknown_tool"),
            page_count=page_count,
            content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            created_at=now.isoformat(),
            expires_at=expires_at.isoformat(),
        )
        stored = _StoredResultArtifact(
            handle=handle,
            expires_at=expires_at,
            content=content,
        )
        with self._lock:
            self._purge_expired_locked(now)
            self._items[artifact_id] = stored
            self._trim_locked()
        return handle

    def read_page(self, artifact_id: str, page: int = 1) -> ResultArtifactPage | None:
        if not isinstance(artifact_id, str) or not artifact_id:
            return None
        if not isinstance(page, int) or page < 1:
            return None
        now = self._now()
        with self._lock:
            self._purge_expired_locked(now)
            stored = self._items.get(artifact_id)
            if stored is None or page > stored.handle.page_count:
                return None
            start = (page - 1) * self._page_chars
            end = min(start + self._page_chars, len(stored.content))
            return ResultArtifactPage(
                artifact_id=stored.handle.artifact_id,
                tool=stored.handle.tool,
                page=page,
                page_count=stored.handle.page_count,
                page_char_start=start,
                page_char_end=end,
                content_sha256=stored.handle.content_sha256,
                expires_at=stored.handle.expires_at,
                content=stored.content[start:end],
            )

    def _now(self) -> datetime:
        now = self._now_fn()
        if now.tzinfo is None:
            return now.replace(tzinfo=timezone.utc)
        return now.astimezone(timezone.utc)

    def _purge_expired_locked(self, now: datetime) -> None:
        expired = [
            artifact_id
            for artifact_id, stored in self._items.items()
            if stored.expires_at <= now
        ]
        for artifact_id in expired:
            self._items.pop(artifact_id, None)

    def _trim_locked(self) -> None:
        overflow = len(self._items) - self._max_items
        if overflow <= 0:
            return
        oldest = sorted(
            self._items.values(),
            key=lambda stored: stored.handle.created_at,
        )[:overflow]
        for stored in oldest:
            self._items.pop(stored.handle.artifact_id, None)
