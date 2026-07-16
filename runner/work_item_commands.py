from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from runner.work_item_governance.errors import WorkItemGovernanceError
from runner.work_item_governance.principal import PrincipalContext
from runner.work_item_governance.request_context import (
    AuthenticatedTokenRequestProof,
    AuthoritativeCanaryRequestContext,
)
from runner.work_item_governance.service import WorkItemApplicationService


class WorkItemCommandGateway:
    """Transport-neutral composition entry point for Work Item commands."""

    def __init__(
        self,
        project_root: str | Path,
        *,
        service_factory: Callable[..., WorkItemApplicationService] = WorkItemApplicationService,
        enabled: bool | None = None,
        authoritative_transitions: bool | None = None,
        principal_context: PrincipalContext | None = None,
        authoritative_canary: bool = False,
        bounded_single_project_pilot: bool = False,
        authenticated_request_proof: AuthenticatedTokenRequestProof | None = None,
        request_context: AuthoritativeCanaryRequestContext | None = None,
    ) -> None:
        activation_composition = authoritative_canary or bounded_single_project_pilot
        if activation_composition and request_context is not None:
            raise WorkItemGovernanceError(
                "AUTHENTICATED_REQUEST_CONTEXT_REUSE",
                "Authoritative Canary request contexts must be minted inside one Gateway execution.",
            )
        self.project_root = str(Path(project_root).expanduser().resolve())
        self.principal_context = principal_context
        self.authoritative_canary = authoritative_canary
        self.bounded_single_project_pilot = bounded_single_project_pilot
        self.authenticated_request_proof = authenticated_request_proof
        self.service = service_factory(
            self.project_root,
            enabled=True if activation_composition else enabled,
            authoritative_transitions=authoritative_transitions,
            authoritative_canary=authoritative_canary,
            bounded_single_project_pilot=bounded_single_project_pilot,
            principal_context=principal_context,
            request_context=request_context,
        )

    def execute(self, name: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        value = dict(params or {})
        handlers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
            "preview_work_item_create": self._preview_create,
            "apply_work_item_create": self._apply_create,
            "get_work_item": self._get,
            "list_work_items": self._list,
            "get_work_item_timeline": self._timeline,
            "preview_legacy_work_item_import": self._preview_import,
            "apply_legacy_work_item_import": self._apply_import,
            "create_execution_attempt": lambda p: self.service.create_execution_attempt(self._command(p)),
            "bind_historical_execution_attempt": lambda p: self.service.bind_historical_execution_attempt(
                self._command(p)
            ),
            "get_execution_attempt_dispatch_authority": lambda p: (
                self.service.get_execution_attempt_dispatch_authority(
                    attempt_id=str(p.get("attempt_id") or ""),
                    work_item_id=str(p.get("work_item_id") or ""),
                    task_version=p.get("task_version"),
                )
            ),
            "complete_execution_attempt": lambda p: self.service.complete_execution_attempt(self._command(p)),
            "register_artifact_reference": lambda p: self.service.register_artifact_reference(self._command(p)),
            "add_task_version": lambda p: self.service.add_task_version(self._command(p)),
            "record_review_decision": lambda p: self.service.record_review_decision(
                self._command(p), principal_context=self.principal_context
            ),
            "preview_work_item_transition": self._preview_transition,
            "apply_work_item_transition": self._apply_transition,
            "apply_blocker": lambda p: self.service.apply_blocker(self._command(p)),
            "clear_blocker": lambda p: self.service.clear_blocker(self._command(p)),
            "create_delivery_receipt": lambda p: self.service.create_delivery_receipt(self._command(p)),
            "retry_delivery": lambda p: self.service.retry_delivery(self._command(p)),
            "acknowledge_delivery": lambda p: self.service.acknowledge_delivery(self._command(p)),
            "list_outbox_events": lambda p: self.service.list_outbox_events(
                status=p.get("status"), limit=p.get("limit", 100)
            ),
            "record_outbox_delivery_result": lambda p: self.service.record_outbox_delivery_result(self._command(p)),
            "recover_outbox_event": lambda p: self.service.recover_outbox_event(self._command(p)),
            "get_work_item_governance_status": lambda _p: self.service.status(),
        }
        handler = handlers.get(name)
        if handler is None:
            if self.authoritative_canary or self.bounded_single_project_pilot:
                self.authenticated_request_proof = None
            raise WorkItemGovernanceError(
                "WORK_ITEM_COMMAND_UNSUPPORTED",
                "Work Item application command is unsupported.",
                details={"command": name, "supported": sorted(handlers)},
            )
        guard = self.service.activation_guard
        try:
            if (self.authoritative_canary or self.bounded_single_project_pilot) and name != "get_work_item_governance_status":
                if guard is None:
                    raise WorkItemGovernanceError(
                        "ACTIVATION_LEASE_REQUIRED",
                        "Authoritative Canary commands require an Activation Lease guard.",
                    )
                if self.service.request_context is not None:
                    raise WorkItemGovernanceError(
                        "AUTHENTICATED_REQUEST_CONTEXT_REUSE",
                        "A cached Authoritative Canary request context cannot be reused.",
                    )
                self.service.request_context = guard.mint_request_context(
                    proof=self.authenticated_request_proof,
                    principal_context=self.principal_context,
                )
            return handler(value)
        finally:
            self.authenticated_request_proof = None
            request_context = self.service.request_context
            self.service.request_context = None
            if guard is not None:
                guard.retire_request_context(request_context)

    def execute_safe(self, name: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            return {"ok": True, "command": name, "data": self.execute(name, params)}
        except WorkItemGovernanceError as exc:
            return {"ok": False, "command": name, "error": exc.to_dict()}

    @staticmethod
    def _command(params: dict[str, Any]) -> dict[str, Any]:
        command = params.get("command")
        if command is None:
            return {key: value for key, value in params.items() if key not in {"ttl_seconds", "project_name"}}
        if not isinstance(command, dict):
            raise WorkItemGovernanceError("COMMAND_OBJECT_REQUIRED", "command must be an object.")
        return command

    def _preview_create(self, params: dict[str, Any]) -> dict[str, Any]:
        return self.service.preview_work_item_create(
            self._command(params), ttl_seconds=self._ttl(params)
        )

    def _apply_create(self, params: dict[str, Any]) -> dict[str, Any]:
        return self.service.apply_work_item_create(self._preview(params))

    def _get(self, params: dict[str, Any]) -> dict[str, Any]:
        return self.service.get_work_item(str(params.get("work_item_id") or ""))

    def _list(self, params: dict[str, Any]) -> dict[str, Any]:
        return self.service.list_work_items(
            state=params.get("state"),
            limit=params.get("limit", 50),
            after_created_at=params.get("after_created_at"),
        )

    def _timeline(self, params: dict[str, Any]) -> dict[str, Any]:
        return self.service.get_work_item_timeline(str(params.get("work_item_id") or ""))

    def _preview_import(self, params: dict[str, Any]) -> dict[str, Any]:
        return self.service.preview_legacy_work_item_import(
            self._command(params), ttl_seconds=self._ttl(params)
        )

    def _apply_import(self, params: dict[str, Any]) -> dict[str, Any]:
        return self.service.apply_legacy_work_item_import(self._preview(params))

    def _preview_transition(self, params: dict[str, Any]) -> dict[str, Any]:
        return self.service.preview_work_item_transition(
            self._command(params),
            ttl_seconds=self._ttl(params),
            principal_context=self.principal_context,
        )

    def _apply_transition(self, params: dict[str, Any]) -> dict[str, Any]:
        return self.service.apply_work_item_transition(
            self._preview(params),
            principal_context=self.principal_context,
        )

    @staticmethod
    def _ttl(params: dict[str, Any]) -> int:
        value = params.get("ttl_seconds", 300)
        return value if isinstance(value, int) and not isinstance(value, bool) else -1

    @staticmethod
    def _preview(params: dict[str, Any]) -> dict[str, Any]:
        preview = params.get("preview")
        if not isinstance(preview, dict):
            raise WorkItemGovernanceError("PREVIEW_REQUIRED", "Apply command requires preview.")
        return preview


def execute_work_item_command(
    project_root: str | Path,
    name: str,
    params: dict[str, Any] | None = None,
    *,
    enabled: bool | None = None,
    authoritative_transitions: bool | None = None,
    principal_context: PrincipalContext | None = None,
    authoritative_canary: bool = False,
    bounded_single_project_pilot: bool = False,
    authenticated_request_proof: AuthenticatedTokenRequestProof | None = None,
    request_context: AuthoritativeCanaryRequestContext | None = None,
) -> dict[str, Any]:
    return WorkItemCommandGateway(
        project_root,
        enabled=enabled,
        authoritative_transitions=authoritative_transitions,
        principal_context=principal_context,
        authoritative_canary=authoritative_canary,
        bounded_single_project_pilot=bounded_single_project_pilot,
        authenticated_request_proof=authenticated_request_proof,
        request_context=request_context,
    ).execute(name, params)
