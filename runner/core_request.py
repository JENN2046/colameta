from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any


_WRITE_ACTION_NAMES = frozenset({
    "apply", "run", "commit", "revert",
    "apply_all", "run_once", "commit_confirm",
})


def _is_write_action_name(action_name: str) -> bool:
    return action_name in _WRITE_ACTION_NAMES


@dataclass
class CoreRequest:
    request_id: str
    entrypoint: str
    intent_type: str
    target_scope: dict[str, Any] | None = None
    confirmation_id: str | None = None
    executor_preference: str | None = None
    file_scope: list[str] | None = None
    read_only: bool = True
    write_intent: bool = False
    risk_profile: dict[str, Any] | None = None
    user_intent_raw: str | None = None
    client_context: dict[str, Any] | None = None
    raw_payload: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "request_id": self.request_id,
            "entrypoint": self.entrypoint,
            "intent_type": self.intent_type,
        }
        if self.target_scope is not None:
            d["target_scope"] = self.target_scope
        if self.confirmation_id is not None:
            d["confirmation_id"] = self.confirmation_id
        if self.executor_preference is not None:
            d["executor_preference"] = self.executor_preference
        if self.file_scope is not None:
            d["file_scope"] = list(self.file_scope)
        d["read_only"] = self.read_only
        d["write_intent"] = self.write_intent
        if self.risk_profile is not None:
            d["risk_profile"] = self.risk_profile
        if self.user_intent_raw is not None:
            d["user_intent_raw"] = self.user_intent_raw
        if self.client_context is not None:
            d["client_context"] = self.client_context
        if self.raw_payload is not None:
            d["raw_payload"] = self.raw_payload
        return d

    @classmethod
    def from_web_action(
        cls,
        next_action: dict[str, Any],
        *,
        client_context: dict[str, Any] | None = None,
        raw_payload: dict[str, Any] | None = None,
    ) -> CoreRequest:
        action_name = (next_action.get("action") or "").lower()
        params: dict[str, Any] = (next_action.get("params") or {}) or {}
        tool = next_action.get("tool", "")

        has_workflow = bool(params.get("workflow"))
        is_inspect = "inspect" in action_name or "inspect" in tool
        is_preview = "preview" in action_name or "preview" in tool

        if has_workflow:
            intent_type = "workflow"
        elif is_inspect:
            intent_type = "inspect"
        elif is_preview:
            intent_type = "preview"
        else:
            intent_type = "query"

        is_write_action = _is_write_action_name(action_name)

        target_scope: dict[str, Any] = {
            "action": action_name,
            "tool": tool,
            "params": dict(params),
        }
        if params.get("workflow"):
            target_scope["workflow"] = params["workflow"]
        if params.get("phase"):
            target_scope["phase"] = params["phase"]

        risk_profile: dict[str, Any] = {
            "risk_level": next_action.get("risk_level", "info"),
            "requires_confirmation": bool(next_action.get("requires_confirmation")),
        }

        return cls(
            request_id=f"web-v2-{uuid.uuid4().hex[:12]}",
            entrypoint="web_v2",
            intent_type=intent_type,
            target_scope=target_scope,
            read_only=not is_write_action,
            write_intent=is_write_action,
            risk_profile=risk_profile,
            user_intent_raw=next_action.get("label") or next_action.get("reason") or "",
            client_context={
                **(client_context or {}),
                "source_action": dict(next_action),
            },
            raw_payload=raw_payload,
        )

    @classmethod
    def from_tool_payload(
        cls,
        payload: dict[str, Any],
        *,
        entrypoint: str = "mcp",
        client_context: dict[str, Any] | None = None,
        raw_payload: dict[str, Any] | None = None,
    ) -> CoreRequest:
        intent_type = (payload.get("intent_type") or "").strip().lower()
        if not intent_type:
            intent_type = "query"

        is_write = intent_type in ("workflow",)

        target_scope: dict[str, Any] = {"params": dict(payload.get("params") or {})}
        workflow = payload.get("workflow")
        if workflow:
            target_scope["workflow"] = workflow
        phase = payload.get("phase")
        if phase:
            target_scope["phase"] = phase

        return cls(
            request_id=f"{entrypoint}-{uuid.uuid4().hex[:12]}",
            entrypoint=entrypoint,
            intent_type=intent_type,
            target_scope=target_scope,
            read_only=not is_write,
            write_intent=is_write,
            client_context=client_context,
            raw_payload=raw_payload,
        )
