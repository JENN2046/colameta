from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from runner.work_item_governance.errors import WorkItemGovernanceError


PRINCIPAL_KINDS = frozenset({"human", "service", "agent"})
AUTHENTICATION_METHODS = frozenset({"local_session", "oauth", "commander"})
WORK_ITEM_PERMISSIONS = frozenset(
    {
        "work_item.ready",
        "work_item.start_delivery",
        "work_item.submit",
        "work_item.accept",
        "work_item.cancel",
        "work_item.return_for_revision",
        "work_item.approve",
    }
)

DECISION_PERMISSION_BY_ACTION = {
    "approve": "work_item.approve",
    "approve_submission": "work_item.submit",
    "accept": "work_item.accept",
    "cancel": "work_item.cancel",
    "reject": "work_item.return_for_revision",
    "request_changes": "work_item.return_for_revision",
    "submit": "work_item.submit",
}

_TRUST_SEAL = object()


@dataclass(frozen=True)
class PrincipalContext:
    principal_id: str
    principal_kind: str
    authenticated_by: str
    granted_permissions: frozenset[str]
    session_ref: str | None
    display_name: str | None = None
    _trust_seal: object | None = None

    @property
    def trusted(self) -> bool:
        return self._trust_seal is _TRUST_SEAL

    def to_record(self) -> dict[str, Any]:
        return {
            "principal_id": self.principal_id,
            "principal_kind": self.principal_kind,
            "authenticated_by": self.authenticated_by,
            "granted_permissions": sorted(self.granted_permissions),
            "session_ref": self.session_ref,
        }

    def actor_record(self) -> dict[str, Any]:
        return {
            "id": self.principal_id,
            "kind": self.principal_kind,
            "display_name": self.display_name,
        }


def trusted_principal_context(
    *,
    principal_id: str,
    principal_kind: str,
    authenticated_by: str,
    granted_permissions: Iterable[str],
    session_ref: str | None,
    display_name: str | None = None,
) -> PrincipalContext:
    """Create an explicit trusted execution capability at a composition root.

    Ordinary command bodies cannot call this path: services accept only the
    opaque PrincipalContext object and never deserialize one from JSON.
    """

    normalized_id = _required_text(principal_id, "principal_id", 512)
    if principal_kind not in PRINCIPAL_KINDS:
        raise WorkItemGovernanceError("PRINCIPAL_KIND_INVALID", "Principal kind is unsupported.")
    if authenticated_by not in AUTHENTICATION_METHODS:
        raise WorkItemGovernanceError(
            "PRINCIPAL_AUTHENTICATION_INVALID",
            "Principal authentication method is unsupported.",
        )
    permissions = frozenset(granted_permissions)
    if not permissions or not permissions.issubset(WORK_ITEM_PERMISSIONS):
        raise WorkItemGovernanceError(
            "PRINCIPAL_PERMISSIONS_INVALID",
            "Principal permissions must be a non-empty Work Item permission set.",
            details={"unsupported": sorted(permissions - WORK_ITEM_PERMISSIONS)},
        )
    normalized_session = None if session_ref is None else _required_text(session_ref, "session_ref", 2048)
    normalized_display = None if display_name is None else _required_text(display_name, "display_name", 512)
    return PrincipalContext(
        principal_id=normalized_id,
        principal_kind=principal_kind,
        authenticated_by=authenticated_by,
        granted_permissions=permissions,
        session_ref=normalized_session,
        display_name=normalized_display,
        _trust_seal=_TRUST_SEAL,
    )


def authorize_principal(
    principal_context: PrincipalContext | None,
    permission: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    if not isinstance(principal_context, PrincipalContext) or not principal_context.trusted:
        raise WorkItemGovernanceError(
            "TRUSTED_PRINCIPAL_REQUIRED",
            "A trusted PrincipalContext from the authenticated control plane is required.",
            details={"required_permission": permission},
        )
    if permission not in principal_context.granted_permissions:
        raise WorkItemGovernanceError(
            "PRINCIPAL_PERMISSION_DENIED",
            "The authenticated Principal lacks the required Work Item permission.",
            details={
                "principal_id": principal_context.principal_id,
                "required_permission": permission,
            },
        )
    principal = principal_context.to_record()
    actor = principal_context.actor_record()
    authority_basis = {
        "authority": permission,
        "policy": "work_item_principal_policy.v1",
        "principal_id": principal_context.principal_id,
        "authenticated_by": principal_context.authenticated_by,
        "session_ref": principal_context.session_ref,
    }
    return principal, actor, authority_basis


def permission_for_decision(action: str) -> str:
    try:
        return DECISION_PERMISSION_BY_ACTION[action]
    except KeyError as exc:
        raise WorkItemGovernanceError(
            "DECISION_ACTION_INVALID",
            "Review Decision action is invalid.",
        ) from exc


def _required_text(value: Any, field: str, max_length: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > max_length:
        raise WorkItemGovernanceError(
            "PRINCIPAL_FIELD_INVALID",
            f"{field} must be a bounded non-empty string.",
            details={"field": field, "max_length": max_length},
        )
    return value.strip()
