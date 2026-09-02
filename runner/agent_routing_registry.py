from __future__ import annotations

from typing import Any, Iterable


ROUTING_REGISTRY_SCHEMA_VERSION = "colameta.agent_tool_routing_registry.v1"
TOOL_TIER_PRIMARY = "PRIMARY"
TOOL_TIER_ADVANCED = "ADVANCED"
TOOL_TIER_LEGACY_OR_INTERNAL = "LEGACY_OR_INTERNAL"


PRIMARY_TOOLS = frozenset(
    {
        "list_registered_projects",
        "get_agent_consumer_contract",
        "get_service_entry_profile",
        "get_agent_operator_flow_packet",
        "analyze_project_state",
        "run_mcp_workflow",
        "review_manifest",
        "read_result_artifact",
        "manage_validation_run",
        "manage_git",
        "get_connector_runtime_health_status",
        "get_stage_parallel_next_action_packet",
        "get_work_item_governance_status",
        "get_stable_promotion_readiness",
    }
)


LEGACY_OR_INTERNAL_TOOLS = frozenset(
    {
        "get_runner_status",
        "get_plan_overview",
        "get_next_version_plan",
        "get_version_result",
        "get_project_doc_section",
        "get_plan_patch_status",
        "get_executor_session_status",
        "get_executor_continuation_preview",
        "get_executor_continuation_decision",
        "get_executor_resume_invocation_preview",
        "get_executor_inventory",
        "get_git_status",
        "get_git_diff",
        "get_git_log",
        "get_repo_overview",
        "get_source_file",
        "search_source",
        "preview_insert_version",
        "preview_update_version",
        "manage_plan_workflow",
        "todo_read",
        "todo_add",
        "todo_update",
        "todo_delete",
        "decision_read",
        "decision_add",
        "decision_update",
        "decision_delete",
        "list_workflow_runs",
        "get_workflow_run",
    }
)


DOMAIN_PRIMARY_TOOL: dict[str, str] = {
    "orientation": "analyze_project_state",
    "workflow": "run_mcp_workflow",
    "source": "analyze_project_state",
    "review": "review_manifest",
    "executor": "run_mcp_workflow",
    "validation": "manage_validation_run",
    "git": "manage_git",
    "planning": "run_mcp_workflow",
    "documentation": "run_mcp_workflow",
    "memory": "run_mcp_workflow",
    "connector": "get_connector_runtime_health_status",
    "product_release": "get_product_readiness_status",
    "stage_parallel": "get_stage_parallel_next_action_packet",
    "work_item_governance": "get_work_item_governance_status",
    "stable": "get_stable_promotion_readiness",
    "platform": "get_agent_operator_flow_packet",
}


PROFILE_GUIDANCE: dict[str, dict[str, Any]] = {
    "web_gpt_commander": {
        "preferred_first_entrypoint": "get_agent_operator_flow_packet",
        "primary_tools": [
            "list_registered_projects",
            "get_agent_operator_flow_packet",
            "analyze_project_state",
            "run_mcp_workflow",
            "review_manifest",
            "read_result_artifact",
            "manage_validation_run",
            "manage_git",
        ],
        "advanced_tools": ["get_stage_parallel_next_action_packet"],
        "tools_not_normally_recommended": sorted(LEGACY_OR_INTERNAL_TOOLS),
        "read_write_expectation": "read_or_preview_first; write requires the existing typed gate and confirmation",
    },
    "local_codex_commander": {
        "preferred_first_entrypoint": "get_agent_operator_flow_packet",
        "primary_tools": [
            "get_agent_operator_flow_packet",
            "analyze_project_state",
            "run_mcp_workflow",
            "manage_validation_run",
            "manage_git",
        ],
        "advanced_tools": [
            "manage_executor_workflow",
            "get_stage_parallel_next_action_packet",
            "get_work_item_governance_status",
        ],
        "tools_not_normally_recommended": sorted(LEGACY_OR_INTERNAL_TOOLS),
        "read_write_expectation": "local repository work remains bounded by workspace and existing MCP gates",
    },
    "planner_agent": {
        "preferred_first_entrypoint": "get_agent_operator_flow_packet",
        "primary_tools": ["get_agent_operator_flow_packet", "analyze_project_state", "run_mcp_workflow"],
        "advanced_tools": ["manage_runner_plan", "manage_plan_version"],
        "tools_not_normally_recommended": sorted(LEGACY_OR_INTERNAL_TOOLS),
        "read_write_expectation": "planning preview only unless a separate plan apply gate is satisfied",
    },
    "reviewer_agent": {
        "preferred_first_entrypoint": "get_agent_operator_flow_packet",
        "primary_tools": ["get_agent_operator_flow_packet", "analyze_project_state", "review_manifest"],
        "advanced_tools": ["manage_workflow_run", "list_executor_run_reports"],
        "tools_not_normally_recommended": sorted(LEGACY_OR_INTERNAL_TOOLS),
        "read_write_expectation": "review evidence only; no review decision or delivery authority",
    },
    "source_observer": {
        "preferred_first_entrypoint": "analyze_project_state",
        "primary_tools": ["analyze_project_state"],
        "advanced_tools": ["manage_files", "get_runtime_version_status"],
        "tools_not_normally_recommended": sorted(LEGACY_OR_INTERNAL_TOOLS),
        "read_write_expectation": "read only; no managed workflow adoption or state transition",
    },
}


def _domain_for_tool(tool_name: str) -> str:
    if "stage_parallel" in tool_name:
        return "stage_parallel"
    if "stable" in tool_name or "managed_runtime_closeout" in tool_name:
        return "stable"
    if any(
        marker in tool_name
        for marker in (
            "work_item",
            "execution_attempt",
            "review_decision",
            "blocker",
            "outbox",
            "delivery_receipt",
        )
    ):
        return "work_item_governance"
    if "connector" in tool_name or "runtime_health" in tool_name:
        return "connector"
    if any(marker in tool_name for marker in ("product", "submission", "release")):
        return "product_release"
    if "validation" in tool_name:
        return "validation"
    if "executor" in tool_name or "run_report" in tool_name:
        return "executor"
    if "git" in tool_name or tool_name in {"project_delivery_preview", "github_delivery"}:
        return "git"
    if "review_manifest" in tool_name or "result_artifact" in tool_name:
        return "review"
    if "plan" in tool_name or "version" in tool_name:
        return "planning"
    if "doc" in tool_name:
        return "documentation"
    if any(marker in tool_name for marker in ("memory", "todo", "decision", "runner_record")):
        return "memory"
    if any(marker in tool_name for marker in ("source", "repo_overview", "manage_files")):
        return "source"
    if "workflow" in tool_name or "prompt" in tool_name:
        return "workflow"
    if tool_name in {
        "list_registered_projects",
        "get_agent_consumer_contract",
        "get_service_entry_profile",
        "get_agent_operator_flow_packet",
        "get_commander_app_manifest",
        "render_commander_app",
        "get_web_gpt_service_entrypoint",
        "get_project_identity",
        "get_runner_workbench_context",
        "analyze_project_state",
    }:
        return "orientation"
    return "platform"


def _tier_for_tool(tool_name: str) -> str:
    if tool_name in PRIMARY_TOOLS:
        return TOOL_TIER_PRIMARY
    if tool_name in LEGACY_OR_INTERNAL_TOOLS:
        return TOOL_TIER_LEGACY_OR_INTERNAL
    return TOOL_TIER_ADVANCED


def _side_effect_level(tool_name: str) -> str:
    if tool_name == "run_mcp_workflow" or tool_name.startswith("manage_"):
        return "DYNAMIC_BY_ACTION"
    if tool_name.startswith("preview_") or "_preview" in tool_name:
        return "PREVIEW"
    if tool_name.startswith(
        (
            "apply_",
            "create_",
            "complete_",
            "register_",
            "record_",
            "clear_",
            "retry_",
            "acknowledge_",
            "fill_",
            "mark_",
            "init_",
            "bind_",
            "add_",
        )
    ):
        return "WRITE_OR_TRANSITION"
    return "READ_ONLY"


def tool_routing_metadata(tool_name: str) -> dict[str, Any]:
    domain = _domain_for_tool(tool_name)
    tier = _tier_for_tool(tool_name)
    recommended_profiles = [
        profile_id
        for profile_id, guidance in PROFILE_GUIDANCE.items()
        if tool_name in guidance["primary_tools"] or tool_name in guidance["advanced_tools"]
    ]
    return {
        "tool": tool_name,
        "domain": domain,
        "classification": tier,
        "canonical_primary_tool": DOMAIN_PRIMARY_TOOL[domain],
        "recommended_profiles": recommended_profiles,
        "side_effect_level": _side_effect_level(tool_name),
        "classification_is_navigation_only": True,
    }


def profile_guidance(profile_id: str | None) -> dict[str, Any]:
    if profile_id not in PROFILE_GUIDANCE:
        return {
            "profile_id": profile_id,
            "status": "PROFILE_UNRESOLVED",
            "preferred_first_entrypoint": "analyze_project_state",
            "primary_tools": ["analyze_project_state", "run_mcp_workflow"],
            "advanced_tools": [],
            "tools_not_normally_recommended": sorted(LEGACY_OR_INTERNAL_TOOLS),
            "read_write_expectation": "read or preview only until the caller profile is resolved",
            "guidance_is_navigation_only": True,
            "does_not_grant_tool_authority": True,
        }
    normalized = profile_id
    return {
        "profile_id": normalized,
        **PROFILE_GUIDANCE[normalized],
        "guidance_is_navigation_only": True,
        "does_not_grant_tool_authority": True,
    }


def build_capability_routing_registry(tool_names: Iterable[str]) -> dict[str, Any]:
    ordered_names = list(dict.fromkeys(name for name in tool_names if isinstance(name, str) and name))
    tools = [tool_routing_metadata(name) for name in ordered_names]
    domains: dict[str, dict[str, Any]] = {}
    for item in tools:
        domain = item["domain"]
        bucket = domains.setdefault(
            domain,
            {
                "domain": domain,
                "canonical_primary_tool": DOMAIN_PRIMARY_TOOL[domain],
                "primary_tools": [],
                "advanced_tools": [],
                "legacy_or_internal_tools": [],
            },
        )
        key = {
            TOOL_TIER_PRIMARY: "primary_tools",
            TOOL_TIER_ADVANCED: "advanced_tools",
            TOOL_TIER_LEGACY_OR_INTERNAL: "legacy_or_internal_tools",
        }[item["classification"]]
        bucket[key].append(item["tool"])
    return {
        "schema_version": ROUTING_REGISTRY_SCHEMA_VERSION,
        "tool_count": len(tools),
        "tools": tools,
        "domains": [domains[key] for key in sorted(domains)],
        "profiles": [profile_guidance(profile_id) for profile_id in PROFILE_GUIDANCE],
        "physical_profile_tool_filtering": "RETAINED",
        "registry_is_navigation_only": True,
        "registry_does_not_grant_authority": True,
    }
