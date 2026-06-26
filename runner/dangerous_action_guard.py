from __future__ import annotations

import hashlib
import json
import secrets
import time
from dataclasses import asdict, dataclass
from typing import Any, Callable


def _json_stable(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def payload_digest(payload: dict[str, Any] | None) -> str:
    clean_payload = dict(payload or {})
    clean_payload.pop("confirmation_id", None)
    return hashlib.sha256(_json_stable(clean_payload).encode("utf-8")).hexdigest()


@dataclass
class DangerousActionPreview:
    confirmation_id: str
    action_type: str
    surface: str
    route: str
    risk_class: str
    project_root: str | None
    project_id: str | None
    project_name: str | None
    current_head: str | None
    state_signature: str | None
    registry_signature: str | None
    payload_digest: str
    target_summary: dict[str, Any]
    created_at: float
    expires_at: float
    used: bool
    display_summary: dict[str, Any]


class DangerousActionGuard:
    def __init__(
        self,
        *,
        ttl_seconds: int = 300,
        now: Callable[[], float] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.ttl_seconds = ttl_seconds
        self._now = now or time.time
        self._id_factory = id_factory or (lambda: secrets.token_urlsafe(32))
        self._previews: dict[str, DangerousActionPreview] = {}

    def create_preview(
        self,
        *,
        action_type: str,
        surface: str,
        route: str,
        risk_class: str,
        project_root: str | None,
        project_id: str | None = None,
        project_name: str | None = None,
        current_head: str | None = None,
        state_signature: str | None = None,
        registry_signature: str | None = None,
        payload: dict[str, Any] | None = None,
        target_summary: dict[str, Any] | None = None,
        display_summary: dict[str, Any] | None = None,
    ) -> DangerousActionPreview:
        now_ts = self._now()
        confirmation_id = self._id_factory()
        preview = DangerousActionPreview(
            confirmation_id=confirmation_id,
            action_type=action_type,
            surface=surface,
            route=route,
            risk_class=risk_class,
            project_root=project_root,
            project_id=project_id,
            project_name=project_name,
            current_head=current_head,
            state_signature=state_signature,
            registry_signature=registry_signature,
            payload_digest=payload_digest(payload),
            target_summary=target_summary or {},
            created_at=now_ts,
            expires_at=now_ts + self.ttl_seconds,
            used=False,
            display_summary=display_summary or {},
        )
        self._previews[confirmation_id] = preview
        return preview

    def preview_response(self, preview: DangerousActionPreview) -> dict[str, Any]:
        return {
            "ok": True,
            "action_type": preview.action_type,
            "surface": preview.surface,
            "route": preview.route,
            "risk_class": preview.risk_class,
            "target_summary": preview.target_summary,
            "display_summary": preview.display_summary,
            "confirmation_id": preview.confirmation_id,
            "confirmation_id_present": True,
            "expires_at": preview.expires_at,
            "one_use": True,
        }

    def confirm(
        self,
        *,
        confirmation_id: Any,
        action_type: str,
        surface: str,
        route: str,
        project_root: str | None,
        current_head: str | None = None,
        state_signature: str | None = None,
        registry_signature: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not isinstance(confirmation_id, str) or not confirmation_id.strip():
            return self._reject("DANGEROUS_CONFIRMATION_REQUIRED", "Dangerous action confirmation is required.")
        preview = self._previews.get(confirmation_id)
        if preview is None:
            return self._reject("DANGEROUS_CONFIRMATION_NOT_FOUND", "Dangerous action confirmation was not found.")
        if preview.used:
            return self._reject("DANGEROUS_CONFIRMATION_REUSED", "Dangerous action confirmation was already used.")
        if self._now() > preview.expires_at:
            preview.used = True
            return self._reject("DANGEROUS_CONFIRMATION_EXPIRED", "Dangerous action confirmation expired.")
        if preview.action_type != action_type:
            return self._reject("DANGEROUS_CONFIRMATION_ACTION_MISMATCH", "Dangerous action confirmation action mismatch.")
        if preview.surface != surface:
            return self._reject("DANGEROUS_CONFIRMATION_SURFACE_MISMATCH", "Dangerous action confirmation surface mismatch.")
        if preview.route != route:
            return self._reject("DANGEROUS_CONFIRMATION_ROUTE_MISMATCH", "Dangerous action confirmation route mismatch.")
        if (preview.project_root or "") != (project_root or ""):
            return self._reject("DANGEROUS_CONFIRMATION_PROJECT_MISMATCH", "Dangerous action confirmation project mismatch.")
        if (preview.current_head or "") != (current_head or ""):
            return self._reject("DANGEROUS_CONFIRMATION_HEAD_MISMATCH", "Dangerous action confirmation HEAD mismatch.")
        if (preview.state_signature or "") != (state_signature or ""):
            return self._reject("DANGEROUS_CONFIRMATION_STATE_MISMATCH", "Dangerous action confirmation state mismatch.")
        if (preview.registry_signature or "") != (registry_signature or ""):
            return self._reject("DANGEROUS_CONFIRMATION_REGISTRY_MISMATCH", "Dangerous action confirmation registry mismatch.")
        if preview.payload_digest != payload_digest(payload):
            return self._reject("DANGEROUS_CONFIRMATION_PAYLOAD_MISMATCH", "Dangerous action confirmation payload mismatch.")
        preview.used = True
        return {
            "ok": True,
            "receipt": self.receipt_for(preview),
        }

    def receipt_for(self, preview: DangerousActionPreview) -> dict[str, Any]:
        rollback_guidance = "Review the action result and reverse the specific registry, project identity, or settings change if needed."
        if isinstance(preview.display_summary, dict):
            display_rollback = preview.display_summary.get("rollback_guidance")
            if isinstance(display_rollback, str) and display_rollback.strip():
                rollback_guidance = display_rollback.strip()
        return {
            "action_type": preview.action_type,
            "surface": preview.surface,
            "route": preview.route,
            "risk_class": preview.risk_class,
            "project_summary": {
                "project_id": preview.project_id,
                "project_name": preview.project_name,
                "project_root": preview.project_root,
            },
            "current_head": preview.current_head or "",
            "target_summary": preview.target_summary,
            "confirmation_validated": True,
            "confirmation_id": "REDACTED",
            "rollback_guidance": rollback_guidance,
        }

    def preview_snapshot(self, confirmation_id: str) -> dict[str, Any] | None:
        preview = self._previews.get(confirmation_id)
        return asdict(preview) if preview is not None else None

    @staticmethod
    def _reject(error_code: str, message: str) -> dict[str, Any]:
        return {
            "ok": False,
            "error_code": error_code,
            "message": message,
        }
