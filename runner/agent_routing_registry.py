from __future__ import annotations

from typing import Any, Iterable


ROUTING_REGISTRY_SCHEMA_VERSION = "colameta.agent_tool_routing_registry.v1"
TOOL_TIER_PRIMARY = "PRIMARY"
TOOL_TIER_ADVANCED = "ADVANCED"
TOOL_TIER_LEGACY_OR_INTERNAL = "LEGACY_OR_INTERNAL"


# These managed surfaces have a fixed server-side policy despite their generic
# ``manage_`` names. Keep the projection aligned with the audited catalog
# actions and MCP scope policy before applying the naming fallback below.
_FIXED_SIDE_EFFECT_LEVELS = {
    "manage_workflow_run": "READ_ONLY",
    "manage_plan_workflow": "PREVIEW",
    "get_executor_continuation_preview": "READ_ONLY",
    "get_executor_resume_invocation_preview": "READ_ONLY",
    "get_stage_parallel_executor_group_preview": "READ_ONLY",
    "get_stage_parallel_merge_preview": "READ_ONLY",
    "get_stage_parallel_plan_preview": "READ_ONLY",
    "get_stage_parallel_run_preview": "READ_ONLY",
    "get_stage_parallel_worktree_assignment_preview": "READ_ONLY",
    "get_submission_evidence_fill_preview": "READ_ONLY",
}


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
    "runtime": "get_runtime_version_status",
    "unclassified": "analyze_project_state",
}


# Exact, audited ownership for the current public catalog.  Tool names are an
# API, so guessing their domain from substrings is both unnecessary and prone
# to misrouting (for example ``get_runtime_version_status`` used to be treated
# as planning merely because it contains "version").  Unknown future tools are
# deliberately visible as ``unclassified`` until this registry is reviewed.
DOMAIN_TOOLS: dict[str, frozenset[str]] = {
    "orientation": frozenset({
        "list_registered_projects", "get_agent_consumer_contract",
        "get_service_entry_profile", "get_agent_operator_flow_packet",
        "get_web_gpt_service_entrypoint", "get_commander_app_manifest",
        "render_commander_app", "get_project_identity",
        "get_runner_execution_standards", "get_runner_status",
        "get_runner_workbench_context", "analyze_project_state",
    }),
    "connector": frozenset({
        "get_apps_connector_smoke_packet", "get_connector_runtime_health_status",
    }),
    "runtime": frozenset({"get_runtime_version_status"}),
    "product_release": frozenset({
        "get_product_readiness_status", "get_chatgpt_app_readiness",
        "get_product_console_map", "get_release_submission_readiness",
        "get_submission_evidence_fill_preview", "get_submission_evidence_auto_draft",
        "manage_submission_evidence_revision", "manage_p1_release_evidence",
        "init_submission_evidence", "fill_submission_evidence_files",
        "mark_submission_evidence_ready_fields", "record_product_console_action_result",
        "register_artifact_reference", "retry_delivery", "acknowledge_delivery",
    }),
    "workflow": frozenset({
        "get_full_loop_authority_status", "manage_workflow_run",
        "manage_prompt_file", "run_mcp_workflow", "list_workflow_runs",
        "get_workflow_run",
    }),
    "stable": frozenset({
        "get_stable_replacement_cadence", "get_stable_promotion_readiness",
        "manage_stable_promotion_evidence",
    }),
    "stage_parallel": frozenset({
        "get_stage_parallel_plan_preview", "get_stage_parallel_run_preview",
        "get_stage_parallel_worktree_assignment_preview",
        "get_stage_parallel_next_action_packet",
        "get_stage_parallel_executor_group_preview",
        "get_stage_parallel_executor_results_packet",
        "get_stage_parallel_group_status", "get_stage_parallel_merge_preview",
        "get_stage_parallel_closeout_packet", "manage_stage_parallel_worktrees",
        "manage_stage_parallel_shard_inputs", "manage_stage_parallel_executor_group",
        "manage_stage_parallel_executor_runs", "manage_stage_parallel_merges",
    }),
    "planning": frozenset({
        "get_plan_standards_report", "manage_runner_plan", "manage_plan_version",
        "add_task_version", "manage_plan_workflow", "get_version_result",
        "get_next_version_plan", "get_plan_overview", "preview_insert_version",
        "preview_update_version", "get_plan_patch_status",
    }),
    "review": frozenset({
        "get_review_context", "review_manifest", "read_result_artifact",
    }),
    "source": frozenset({
        "manage_project_patch", "manage_files", "get_repo_overview",
        "get_source_file", "search_source",
    }),
    "documentation": frozenset({"manage_project_docs", "get_project_doc_section"}),
    "git": frozenset({
        "manage_git", "manage_git_commit", "manage_git_remote",
        "manage_git_history", "get_git_status", "get_git_log", "get_git_diff",
    }),
    "memory": frozenset({
        "manage_project_memory", "manage_runner_record", "todo_read", "todo_add",
        "todo_update", "todo_delete", "decision_read", "decision_add",
        "decision_update", "decision_delete",
    }),
    "executor": frozenset({
        "get_executor_session_status", "get_executor_continuation_preview",
        "get_executor_continuation_decision", "get_executor_resume_invocation_preview",
        "get_executor_inventory", "list_executor_run_reports",
        "get_executor_run_report", "inspect_executor_activity",
        "manage_executor_config", "manage_executor_workflow",
    }),
    "validation": frozenset({"manage_validation_run"}),
    "work_item_governance": frozenset({
        "get_work_item_governance_status", "get_work_item", "list_work_items",
        "get_work_item_timeline", "list_outbox_events",
        "get_execution_attempt_dispatch_authority", "preview_work_item_create",
        "preview_legacy_work_item_import", "preview_work_item_transition",
        "apply_work_item_create", "apply_legacy_work_item_import",
        "create_execution_attempt", "bind_historical_execution_attempt",
        "complete_execution_attempt", "record_review_decision",
        "apply_work_item_transition", "apply_blocker", "clear_blocker",
        "create_delivery_receipt", "record_outbox_delivery_result",
        "recover_outbox_event",
    }),
}

_TOOL_DOMAIN: dict[str, str] = {}
for _domain, _tool_names in DOMAIN_TOOLS.items():
    for _tool_name in _tool_names:
        if _tool_name in _TOOL_DOMAIN:
            raise RuntimeError(f"duplicate routing domain for {_tool_name}")
        _TOOL_DOMAIN[_tool_name] = _domain

_WRITE_OR_TRANSITION_TOOLS = frozenset({
    "todo_add",
    "todo_update",
    "todo_delete",
    "decision_add",
    "decision_update",
    "decision_delete",
    "recover_outbox_event",
})


PROFILE_GUIDANCE: dict[str, dict[str, Any]] = {
    "web_gpt_commander": {
        "preferred_first_entrypoint": "analyze_project_state",
        "primary_tools": [
            "list_registered_projects",
            "analyze_project_state",
            "run_mcp_workflow",
            "review_manifest",
            "read_result_artifact",
            "manage_validation_run",
            "manage_git",
        ],
        "advanced_tools": [],
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
        "advanced_tools": [
            "get_repo_overview",
            "get_source_file",
            "search_source",
            "get_runtime_version_status",
        ],
        "tools_not_normally_recommended": sorted(
            LEGACY_OR_INTERNAL_TOOLS
            - {"get_repo_overview", "get_source_file", "search_source"}
        ),
        "read_write_expectation": "read only; no managed workflow adoption or state transition",
    },
}


def _domain_for_tool(tool_name: str) -> str:
    return _TOOL_DOMAIN.get(tool_name, "unclassified")


def _tier_for_tool(tool_name: str) -> str:
    if tool_name in PRIMARY_TOOLS:
        return TOOL_TIER_PRIMARY
    if tool_name in LEGACY_OR_INTERNAL_TOOLS:
        return TOOL_TIER_LEGACY_OR_INTERNAL
    return TOOL_TIER_ADVANCED


def _side_effect_level(tool_name: str) -> str:
    fixed_level = _FIXED_SIDE_EFFECT_LEVELS.get(tool_name)
    if fixed_level is not None:
        return fixed_level
    if tool_name == "run_mcp_workflow" or tool_name.startswith("manage_"):
        return "DYNAMIC_BY_ACTION"
    if tool_name.startswith("preview_") or "_preview" in tool_name:
        return "PREVIEW"
    if tool_name in _WRITE_OR_TRANSITION_TOOLS or tool_name.startswith(
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
