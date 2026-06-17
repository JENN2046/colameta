"""Shared preview artifact primitive for MCP tool managers.

Provides read/write/status/guard/expiry/project-match for preview artifacts
used by MCP tool managers. Duck-type compatible with ConfirmationStore
for ``confirmation_apply_guard`` and ``confirmation_fact_from_store``
via ``read()`` and ``is_expired()`` methods.
"""

from typing import Any

from runner.confirmation_store import ConfirmationStore
from runner.core_confirmation import confirmation_apply_guard, confirmation_status_fact


class PreviewArtifact:
    """Shared preview artifact service.

    Wraps ConfirmationStore for id generation, persistence, expiry,
    project validation, and status with confirmation enrichment.
    """

    def __init__(self, project_root: str, relative_dir: str, ttl_seconds: int = 1800):
        self._store = ConfirmationStore(project_root, relative_dir, ttl_seconds)

    def create_id(self, prefix: str = "") -> str:
        return self._store.create_id(prefix)

    def now_iso(self) -> str:
        return self._store.now_iso()

    def expires_at(self) -> str:
        return self._store.expires_at()

    def write(self, preview_id: str, payload: dict[str, Any]) -> None:
        self._store.write(preview_id, payload)

    def read(self, preview_id: str) -> dict[str, Any] | None:
        return self._store.read(preview_id)

    def is_expired(self, payload: dict[str, Any]) -> bool:
        return self._store.is_expired(payload)

    def delete(self, preview_id: str) -> bool:
        return self._store.delete(preview_id)

    def validate_project(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        return self._store.validate_project(payload)

    def validate_not_expired(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        return self._store.validate_not_expired(payload)

    def guard(
        self,
        preview_id: str,
        *,
        project_root: str | None = None,
        payload: Any | None = None,
    ) -> dict[str, Any]:
        """Return shared apply guard facts for a preview artifact."""
        return confirmation_apply_guard(self, preview_id, project_root=project_root, payload=payload)

    def status(self, preview_id: str) -> dict[str, Any]:
        """Return status dict enriched with confirmation data."""
        return confirmation_status_fact(self._store, preview_id)
