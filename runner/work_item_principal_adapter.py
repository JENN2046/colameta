from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import os
from typing import Any, Iterator

from runner.work_item_governance.principal import (
    PRINCIPAL_KINDS,
    PrincipalContext,
    trusted_principal_context,
)
from runner.work_item_governance.errors import WorkItemGovernanceError
from runner.work_item_governance.request_context import (
    AuthenticatedTokenRequestProof,
    _issue_authenticated_token_request_proof,
)


_CURRENT_PRINCIPAL: ContextVar[PrincipalContext | None] = ContextVar(
    "colameta_work_item_principal",
    default=None,
)
_CURRENT_TOKEN_REQUEST_PROOF: ContextVar[AuthenticatedTokenRequestProof | None] = ContextVar(
    "colameta_work_item_token_request_proof",
    default=None,
)


def current_work_item_principal() -> PrincipalContext | None:
    return _CURRENT_PRINCIPAL.get()


def current_authenticated_token_request_proof() -> AuthenticatedTokenRequestProof | None:
    return _CURRENT_TOKEN_REQUEST_PROOF.get()


@contextmanager
def work_item_authenticated_request_scope(
    auth_context: dict[str, Any] | None,
) -> Iterator[AuthenticatedTokenRequestProof | None]:
    proof = (
        _issue_authenticated_token_request_proof()
        if isinstance(auth_context, dict) and auth_context.get("mode") == "token"
        else None
    )
    token = _CURRENT_TOKEN_REQUEST_PROOF.set(proof)
    try:
        yield proof
    finally:
        _CURRENT_TOKEN_REQUEST_PROOF.reset(token)


@contextmanager
def work_item_principal_scope(auth_context: dict[str, Any] | None) -> Iterator[PrincipalContext | None]:
    principal = principal_from_auth_context(auth_context)
    token = _CURRENT_PRINCIPAL.set(principal)
    try:
        yield principal
    finally:
        _CURRENT_PRINCIPAL.reset(token)


def principal_from_auth_context(auth_context: dict[str, Any] | None) -> PrincipalContext | None:
    if not isinstance(auth_context, dict):
        return local_principal_from_environment()
    injected = auth_context.get("principal_context")
    if isinstance(injected, PrincipalContext) and injected.trusted:
        return injected

    mode = auth_context.get("mode")
    if mode in {None, "none", "token", "local-session"}:
        return local_principal_from_environment()
    if mode not in {"oauth", "external-oauth", "cloud-relay"}:
        return None
    claims = auth_context.get("token") if mode in {"oauth", "external-oauth"} else auth_context
    if not isinstance(claims, dict):
        return None
    permissions = _work_item_permissions(claims.get("work_item_permissions"))
    if not permissions:
        return None
    principal_id = claims.get("sub") or claims.get("principal_id")
    if not isinstance(principal_id, str) or not principal_id.strip():
        return None
    principal_kind = claims.get("principal_kind", "human" if mode != "cloud-relay" else "agent")
    if principal_kind not in PRINCIPAL_KINDS:
        return None
    session_ref = claims.get("sid") or claims.get("jti") or claims.get("session_ref")
    if session_ref is not None and not isinstance(session_ref, str):
        return None
    display_name = claims.get("name")
    if display_name is not None and not isinstance(display_name, str):
        display_name = None
    try:
        return trusted_principal_context(
            principal_id=principal_id,
            principal_kind=principal_kind,
            authenticated_by="commander" if mode == "cloud-relay" else "oauth",
            granted_permissions=permissions,
            session_ref=session_ref,
            display_name=display_name,
        )
    except WorkItemGovernanceError:
        return None


def local_principal_from_environment() -> PrincipalContext | None:
    """Issue a local-session Principal only from operator-owned process config."""
    principal_id = os.environ.get("COLAMETA_WORK_ITEM_PRINCIPAL_ID", "").strip()
    permissions = _work_item_permissions(
        os.environ.get("COLAMETA_WORK_ITEM_PERMISSIONS", "")
    )
    if not principal_id or not permissions:
        return None
    principal_kind = os.environ.get("COLAMETA_WORK_ITEM_PRINCIPAL_KIND", "human").strip()
    session_ref = os.environ.get("COLAMETA_WORK_ITEM_SESSION_REF", "").strip() or None
    display_name = os.environ.get("COLAMETA_WORK_ITEM_PRINCIPAL_DISPLAY_NAME", "").strip() or None
    try:
        return trusted_principal_context(
            principal_id=principal_id,
            principal_kind=principal_kind,
            authenticated_by="local_session",
            granted_permissions=permissions,
            session_ref=session_ref,
            display_name=display_name,
        )
    except WorkItemGovernanceError:
        return None


def _work_item_permissions(value: Any) -> list[str]:
    if isinstance(value, str):
        return [item for item in value.replace(",", " ").split() if item]
    if isinstance(value, (list, tuple, set)):
        return [item for item in value if isinstance(item, str) and item]
    return []
