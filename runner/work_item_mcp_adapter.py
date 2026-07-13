from __future__ import annotations

from pathlib import Path
from typing import Any

from runner.work_item_commands import WorkItemCommandGateway
from runner.work_item_governance.activation import AUTHORITATIVE_CANARY_TOOLS
from runner.work_item_governance.principal import PrincipalContext
from runner.work_item_governance.pilot import PILOT_TOOLS
from runner.work_item_governance.request_context import AuthenticatedTokenRequestProof


WORK_ITEM_READ_TOOLS = (
    "get_work_item_governance_status",
    "get_work_item",
    "list_work_items",
    "get_work_item_timeline",
    "list_outbox_events",
    "get_execution_attempt_dispatch_authority",
)
WORK_ITEM_PREVIEW_TOOLS = (
    "preview_work_item_create",
    "preview_legacy_work_item_import",
    "preview_work_item_transition",
)
WORK_ITEM_APPLY_TOOLS = (
    "apply_work_item_create",
    "apply_legacy_work_item_import",
    "add_task_version",
    "create_execution_attempt",
    "bind_historical_execution_attempt",
    "complete_execution_attempt",
    "register_artifact_reference",
    "record_review_decision",
    "apply_work_item_transition",
    "apply_blocker",
    "clear_blocker",
    "create_delivery_receipt",
    "retry_delivery",
    "acknowledge_delivery",
    "record_outbox_delivery_result",
    "recover_outbox_event",
)
WORK_ITEM_MCP_TOOLS = WORK_ITEM_READ_TOOLS + WORK_ITEM_PREVIEW_TOOLS + WORK_ITEM_APPLY_TOOLS
AUTHORITATIVE_CANARY_MCP_TOOLS = AUTHORITATIVE_CANARY_TOOLS
BOUNDED_PILOT_MCP_TOOLS = PILOT_TOOLS


def execute_work_item_mcp_command(
    project_root: str | Path,
    name: str,
    params: dict[str, Any],
    *,
    principal_context: PrincipalContext | None = None,
    authoritative_canary: bool = False,
    bounded_single_project_pilot: bool = False,
    authenticated_request_proof: AuthenticatedTokenRequestProof | None = None,
) -> dict[str, Any]:
    return WorkItemCommandGateway(
        project_root,
        principal_context=principal_context,
        authoritative_transitions=(
            True if authoritative_canary or bounded_single_project_pilot else None
        ),
        authoritative_canary=authoritative_canary,
        bounded_single_project_pilot=bounded_single_project_pilot,
        authenticated_request_proof=authenticated_request_proof,
    ).execute(name, params)


def work_item_mcp_tool_specs(
    project_hint: str,
    *,
    authoritative_canary: bool = False,
    bounded_single_project_pilot: bool = False,
) -> list[dict[str, Any]]:
    restricted = authoritative_canary or bounded_single_project_pilot
    project_property = {} if restricted else {
        "project_name": {
            "type": "string",
            "description": "服务模式必填。按已登记 project_name 路由；不接受任意 project_root。",
        }
    }

    def schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {**project_property, **properties},
            "required": required,
            "additionalProperties": False,
        }

    read_schemas = {
        "get_work_item_governance_status": schema({}, []),
        "get_work_item": schema({"work_item_id": {"type": "string"}}, ["work_item_id"]),
        "get_work_item_timeline": schema({"work_item_id": {"type": "string"}}, ["work_item_id"]),
        "list_work_items": schema(
            {
                "state": {
                    "type": "string",
                    "enum": ["proposed", "ready", "in_delivery", "submitted", "accepted", "cancelled"],
                },
                "limit": {"type": "integer", "minimum": 1, "maximum": 200},
                "after_created_at": {"type": "string"},
            },
            [],
        ),
        "list_outbox_events": schema(
            {
                "status": {
                    "type": "string",
                    "enum": ["pending", "retry_scheduled", "delivered", "failed", "manual_recovery"],
                },
                "limit": {"type": "integer", "minimum": 1, "maximum": 500},
            },
            [],
        ),
        "get_execution_attempt_dispatch_authority": schema(
            {
                "work_item_id": {"type": "string"},
                "task_version": {"type": "integer", "minimum": 1},
                "attempt_id": {"type": "string"},
            },
            ["work_item_id", "task_version", "attempt_id"],
        ),
    }
    preview_schema = schema(
        {
            "command": {"type": "object", "additionalProperties": True},
            "ttl_seconds": {"type": "integer", "minimum": 1, "maximum": 900},
        },
        ["command"],
    )
    apply_schema = schema(
        {"preview": {"type": "object", "additionalProperties": True}},
        ["preview"],
    )
    command_schema = schema(
        {"command": {"type": "object", "additionalProperties": True}},
        ["command"],
    )

    specs: list[dict[str, Any]] = []
    names = (
        BOUNDED_PILOT_MCP_TOOLS
        if bounded_single_project_pilot
        else (AUTHORITATIVE_CANARY_MCP_TOOLS if authoritative_canary else WORK_ITEM_MCP_TOOLS)
    )
    for name in names:
        if name in read_schemas:
            input_schema = read_schemas[name]
            scope = "mcp:read"
            annotations = {
                "readOnlyHint": True,
                "destructiveHint": False,
                "openWorldHint": False,
                "idempotentHint": True,
            }
        elif name in WORK_ITEM_PREVIEW_TOOLS:
            input_schema = preview_schema
            scope = "mcp:preview"
            annotations = {
                "readOnlyHint": False,
                "destructiveHint": False,
                "openWorldHint": False,
                "idempotentHint": False,
            }
        elif name in {
            "apply_work_item_create",
            "apply_legacy_work_item_import",
            "apply_work_item_transition",
        }:
            input_schema = apply_schema
            scope = "mcp:commit"
            annotations = {
                "readOnlyHint": False,
                "destructiveHint": False,
                "openWorldHint": False,
                "idempotentHint": True,
            }
        else:
            input_schema = command_schema
            scope = "mcp:commit"
            annotations = {
                "readOnlyHint": False,
                "destructiveHint": False,
                "openWorldHint": False,
                "idempotentHint": True,
            }
        specs.append(
            {
                "name": name,
                "title": name.replace("_", " ").title(),
                "description": (
                    f"[{project_hint}] Work Item Governance application command `{name}`. "
                    f"scope={scope}. Work Item state is changed only by apply_work_item_transition; "
                    "Runner/connector/stable/product facts never directly accept delivery."
                ),
                "input_schema": input_schema,
                "annotations": annotations,
            }
        )
    return specs
