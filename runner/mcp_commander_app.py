"""Commander/ChatGPT product-domain methods outside the MCP transport root."""

from __future__ import annotations

import copy
import sys
from datetime import datetime, timezone
from typing import Any

from runner.commander_projections import CommanderProjectionService
from runner.commander_widget import commander_widget_html
from runner.executor_status import polling_guidance_for_profile
from runner.full_loop_authority import build_full_loop_authority_status
from runner.mcp_commander_public import (
    COMMANDER_CLIENT_EXPERIENCE_CONTRACT_VERSION,
    COMMANDER_EXPOSED_TOOLS,
    COMMANDER_LOCAL_CODEX_ADVANCED_TOOL_EXAMPLES,
    CommanderPublicProjector,
)
from runner.mcp_submission_evidence_revision import MCPSubmissionEvidenceRevisionManager
from runner.p1_release_evidence import P1ReleaseEvidenceManager, p1_release_evidence_input_schema
from runner.mcp_tool_catalog import _stage_parallel_preview_input_schema
from runner.product_console import (
    build_product_console_map,
    build_submission_evidence_activity_result,
    build_submission_evidence_fill_preview,
    record_product_console_action_result,
)
from runner.product_readiness import (
    build_chatgpt_connection_packet,
    build_product_readiness_packet,
)
from runner.release_submission_readiness import (
    build_release_submission_readiness,
    fill_submission_evidence_files,
    init_submission_evidence_scaffold,
    mark_submission_evidence_ready_fields,
)
from runner.runtime_observability import (
    build_apps_connector_closeout_packet,
    build_service_readiness_summary,
    get_connector_runtime_health_status,
)
from runner.stage_parallel_next_action import build_stage_parallel_next_action_packet


COMMANDER_APP_WIDGET_URI = "ui://colameta/commander/v1.html"
COMMANDER_APP_WIDGET_MIME_TYPE = "text/html;profile=mcp-app"
COMMANDER_APP_MANIFEST_VERSION = "colameta_commander_app.v1"
COMMANDER_APP_TITLE = "ColaMeta Commander"
COMMANDER_APP_SERVER_INSTRUCTIONS = (
    "ColaMeta Commander is the focused ChatGPT App surface for ColaMeta project work. "
    "It exposes exactly nine tools. Start with list_registered_projects, then use render_commander_app or analyze_project_state with a "
    "registered project_name. Use review_manifest for hash-bound independent review, "
    "read_result_artifact for a paged packaged-result continuation, run_mcp_workflow for planning and controlled changes, "
    "manage_validation_run for validation, and manage_git for reviewed Git operations. "
    "Use the typed review_manifest and read_result_artifact continuations; resources/read is optional protocol compatibility, never a required ChatGPT path. "
    "The complete catalog remains available only on the loopback advanced-mode endpoint. "
    "Treat status and preview outputs as evidence only; they do not authorize executor run, commit, push, "
    "stable service replacement, ReviewDecision, GateEvent, or Delivery accepted."
)


class MCPCommanderAppMixin:
    def _commander_app_dependency(self, name: str, fallback: Any) -> Any:
        """Resolve a product dependency through the owning server module.

        The Commander domain moved out of ``mcp_server`` without changing the
        long-standing dependency-injection seam used by integrations and
        focused tests. The owning concrete server remains the override point;
        a standalone mixin consumer uses the local fallback.
        """
        owner_module = sys.modules.get(type(self).__module__)
        candidate = getattr(owner_module, name, None) if owner_module is not None else None
        return candidate if candidate is not None else fallback

    def _commander_widget_resource_meta(self) -> dict[str, Any]:
        return {
            "ui": {
                "prefersBorder": True,
                "csp": {
                    "connectDomains": [],
                    "resourceDomains": [],
                },
            },
            "openai/widgetDescription": (
                "ColaMeta Commander shows local service facts, connector health, "
                "profile-aware entries, preview-first workflow routes, and explicit authorization gates."
            ),
            "openai/widgetPrefersBorder": True,
            "openai/widgetCSP": {
                "connect_domains": [],
                "resource_domains": [],
            },
        }

    def _commander_widget_html(self) -> str:
        return MCPCommanderAppMixin._commander_app_dependency(
            self,
            "commander_widget_html",
            commander_widget_html,
        )()

    def _commander_public_projector(self) -> CommanderPublicProjector:
        return self._commander_app_dependency("CommanderPublicProjector", CommanderPublicProjector)(self.project_root)

    def _commander_public_sanitize(self, value: Any, *, compact: bool) -> Any:
        return self._commander_public_projector().sanitize(value, compact=compact)

    def _client_experience_partition(self) -> dict[str, Any]:
        """Describe the deliberately different ChatGPT and Local Codex surfaces.

        This is an advanced/local contract reader, not another public
        Commander tool.  Keeping the public tool inventory as a literal tuple
        avoids a second source of truth while giving local operators a concrete
        compatibility boundary to test.
        """

        return {
            "schema_version": COMMANDER_CLIENT_EXPERIENCE_CONTRACT_VERSION,
            "shared_invariants": {
                "canonical_state_semantics_shared": True,
                "scope_semantics_shared": True,
                "context_binding_semantics_shared": True,
                "authority_boundaries_shared": True,
                "stable_replacement_requires_separate_authorization": True,
            },
            "chatgpt_commander": {
                "mcp_exposure_profile": "commander",
                "visible_tool_count": len(COMMANDER_EXPOSED_TOOLS),
                "visible_tools": list(COMMANDER_EXPOSED_TOOLS),
                "default_payload_policy": "compact_public_projection",
                "typed_read_continuations": [
                    {
                        "tool": "review_manifest",
                        "phases": ["inspect", "read", "verify"],
                        "purpose": "hash-bound declared-subject review",
                    },
                    {
                        "tool": "read_result_artifact",
                        "purpose": "paged packaged-result recovery",
                    },
                ],
                "resources_read": {
                    "required": False,
                    "role": "optional_standard_mcp_compatibility_only",
                    "supported_primary_path": "typed_tool_continuations",
                },
                "does_not_expose_local_advanced_tools": True,
            },
            "local_codex_loopback": {
                "mcp_exposure_profile": "normal",
                "default_payload_policy": "rich_local_diagnostics",
                "advanced_tool_examples": list(COMMANDER_LOCAL_CODEX_ADVANCED_TOOL_EXAMPLES),
                "capability_families": [
                    "executor configuration and controlled execution",
                    "deep local file and workflow diagnostics",
                    "advanced migration and handoff context",
                ],
                "not_exposed_in_chatgpt_commander": True,
            },
        }

    def _commander_app_input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "project_name": {
                    "type": "string",
                    "description": "必填。服务模式下指定已登记 project_name。",
                },
                "profile_id": {
                    "type": "string",
                    "enum": [
                        "web_gpt_commander",
                        "local_codex_commander",
                        "planner_agent",
                        "reviewer_agent",
                        "source_observer",
                    ],
                    "description": "可选。指定 Commander 内嵌 agent flow 所属 persona；默认 web_gpt_commander。",
                },
                "provider": {
                    "type": "string",
                    "enum": ["pi", "codex", "opencode"],
                    "description": "可选。绑定 Commander continuation snapshot 的执行器；默认 codex。",
                },
                "tunnel_client": self._sanitized_connector_evidence_schema(
                    "可选。调用方提供的 sanitized tunnel-client 状态，只采信 status/reason_code/evidence_source/last_observed_at。"
                ),
                "control_plane": self._sanitized_connector_evidence_schema(
                    "可选。调用方提供的 sanitized tunnel control-plane 状态，只采信 status/reason_code/evidence_source/last_observed_at。"
                ),
            },
            "required": [],
            "additionalProperties": False,
        }

    def _full_loop_authority_input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "project_name": {
                    "type": "string",
                    "description": "必填。服务模式下指定已登记 project_name。",
                },
                "enable_full_loop": {
                    "type": "boolean",
                    "description": "可选。显式请求检查完整闭环控制项；默认 false。",
                },
                "confirmation_mode": {
                    "type": "string",
                    "enum": ["preview_confirm", "preview-confirm"],
                    "description": "可选。完整闭环必须使用 preview_confirm。",
                },
                "operator_confirmation_ref": {
                    "type": "string",
                    "description": "可选。外部确认引用；返回中只报告是否存在，不回显原文。",
                },
                "allow_executor_run": {"type": "boolean"},
                "allow_validation_run": {"type": "boolean"},
                "allow_local_commit": {"type": "boolean"},
                "allow_remote_push": {"type": "boolean"},
                "allow_stable_replacement": {"type": "boolean"},
            },
            "required": [],
            "additionalProperties": False,
        }

    def _release_submission_input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "project_name": {
                    "type": "string",
                    "description": "必填。服务模式下指定已登记 project_name。",
                },
                "app_name": {"type": "string"},
                "app_description": {"type": "string"},
                "company_url": {"type": "string"},
                "privacy_policy_url": {"type": "string"},
                "logo_ready": {"type": "boolean"},
                "screenshots_ready": {"type": "boolean"},
                "test_prompts_ready": {"type": "boolean"},
                "test_responses_ready": {"type": "boolean"},
                "localization_ready": {"type": "boolean"},
                "mcp_tool_info_ready": {"type": "boolean"},
                "app_management_permissions_confirmed": {"type": "boolean"},
                "security_review_ready": {"type": "boolean"},
                "metadata_snapshot_reviewed": {"type": "boolean"},
                "submission_confirmations_ready": {"type": "boolean"},
                "submission_materials": {
                    "type": "object",
                    "description": "可选。结构化 release/submission materials manifest；不会读取本机文件路径。",
                    "properties": {
                        "schema_version": {"type": "string"},
                        "app_name": {"type": "string"},
                        "app_description": {"type": "string"},
                        "company_url": {"type": "string"},
                        "privacy_policy_url": {"type": "string"},
                        "logo_ready": {"type": "boolean"},
                        "screenshots_ready": {"type": "boolean"},
                        "test_prompts_ready": {"type": "boolean"},
                        "test_responses_ready": {"type": "boolean"},
                        "localization_ready": {"type": "boolean"},
                        "mcp_tool_info_ready": {"type": "boolean"},
                        "app_management_permissions_confirmed": {"type": "boolean"},
                        "security_review_ready": {"type": "boolean"},
                        "metadata_snapshot_reviewed": {"type": "boolean"},
                        "submission_confirmations_ready": {"type": "boolean"},
                        "evidence": {"type": "object", "additionalProperties": True},
                        "notes": {"type": "string"},
                    },
                    "additionalProperties": True,
                },
                "work_item_id": {
                    "type": "string",
                    "description": "可选。通过 App Submission Application Command 引用现有 Work Item。",
                },
            },
            "required": [],
            "additionalProperties": False,
        }

    def _submission_evidence_fill_preview_input_schema(self) -> dict[str, Any]:
        evidence_keys = [
            "logo",
            "screenshots",
            "test_prompts",
            "test_responses",
            "localization",
            "mcp_tool_info",
            "app_management_permissions",
            "security_review",
            "metadata_snapshot",
            "submission_confirmations",
        ]
        return {
            "type": "object",
            "properties": {
                "project_name": {
                    "type": "string",
                    "description": "必填。服务模式下指定已登记 project_name。",
                },
                "selected_keys": {
                    "type": "array",
                    "description": "可选。只为选中的 evidence key 生成 fill payload 预览；不写文件。",
                    "items": {"type": "string", "enum": evidence_keys},
                },
            },
            "required": [],
            "additionalProperties": False,
        }

    def _submission_evidence_auto_draft_input_schema(self) -> dict[str, Any]:
        auto_keys = ["mcp_tool_info", "security_review", "metadata_snapshot"]
        return {
            "type": "object",
            "properties": {
                "project_name": {
                    "type": "string",
                    "description": "必填。服务模式下指定已登记 project_name。",
                },
                "selected_keys": {
                    "type": "array",
                    "description": "可选。只为可自动预填的 evidence key 生成草稿；不写文件。",
                    "items": {"type": "string", "enum": auto_keys},
                },
            },
            "required": [],
            "additionalProperties": False,
        }

    def _submission_evidence_revision_input_schema(self) -> dict[str, Any]:
        evidence_keys = [
            "logo",
            "screenshots",
            "test_prompts",
            "test_responses",
            "localization",
            "mcp_tool_info",
            "app_management_permissions",
            "security_review",
            "metadata_snapshot",
            "submission_confirmations",
        ]
        return {
            "type": "object",
            "properties": {
                "project_name": {
                    "type": "string",
                    "description": "服务模式下指定已登记 managed project_name。",
                },
                "action": {
                    "type": "string",
                    "enum": ["preview", "apply", "status", "discard"],
                    "description": "preview 校验并绑定修订；apply 使用 preview_id 落盘；status/discard 管理短时工件。",
                },
                "key": {
                    "type": "string",
                    "enum": evidence_keys,
                    "description": "preview 必填。manifest 中的 evidence key。",
                },
                "ref": {
                    "type": "string",
                    "description": "preview 必填。必须是该 key 在 manifest 中已绑定且当前 review_required 的 docs/submission/*.md。",
                },
                "content": {
                    "type": "string",
                    "description": "preview/apply 必填。apply 必须重新提交与 preview digest 完全一致的 replacement Markdown；结果和 preview 工件都不保存正文。",
                },
                "preview_id": {
                    "type": "string",
                    "description": "apply/status/discard 必填。来自 preview 的 preview_id。",
                },
            },
            "required": ["action"],
            "additionalProperties": False,
        }

    def _p1_release_evidence_input_schema(self) -> dict[str, Any]:
        """Local-only operator receipt schema; never part of the nine-tool App."""
        return p1_release_evidence_input_schema()

    def _init_submission_evidence_input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "project_name": {
                    "type": "string",
                    "description": "必填。服务模式下指定已登记 project_name。",
                },
                "app_name": {"type": "string"},
                "app_description": {"type": "string"},
                "company_url": {"type": "string"},
                "privacy_policy_url": {"type": "string"},
            },
            "required": [],
            "additionalProperties": False,
        }

    def _fill_submission_evidence_input_schema(self) -> dict[str, Any]:
        evidence_keys = [
            "logo",
            "screenshots",
            "test_prompts",
            "test_responses",
            "localization",
            "mcp_tool_info",
            "app_management_permissions",
            "security_review",
            "metadata_snapshot",
            "submission_confirmations",
        ]
        return {
            "type": "object",
            "properties": {
                "project_name": {
                    "type": "string",
                    "description": "必填。服务模式下指定已登记 project_name。",
                },
                "entries": {
                    "type": "array",
                    "description": "要写入的 evidence 条目。内容由操作者提供；文件会被限制在 docs/submission/*.md。",
                    "items": {
                        "type": "object",
                        "properties": {
                            "key": {"type": "string", "enum": evidence_keys},
                            "filename": {
                                "type": "string",
                                "description": "可选。文件名或 docs/submission/*.md 相对路径；不接受 .todo.md。",
                            },
                            "content": {"type": "string"},
                        },
                        "required": ["key", "content"],
                        "additionalProperties": False,
                    },
                },
                "mark_ready": {
                    "type": "boolean",
                    "description": "显式为 true 时，才把对应 manifest ready 字段标记为 true。",
                },
            },
            "required": ["entries"],
            "additionalProperties": False,
        }

    def _mark_submission_evidence_ready_input_schema(self) -> dict[str, Any]:
        evidence_keys = [
            "logo",
            "screenshots",
            "test_prompts",
            "test_responses",
            "localization",
            "mcp_tool_info",
            "app_management_permissions",
            "security_review",
            "metadata_snapshot",
            "submission_confirmations",
        ]
        return {
            "type": "object",
            "properties": {
                "project_name": {
                    "type": "string",
                    "description": "必填。服务模式下指定已登记 project_name。",
                },
                "keys": {
                    "type": "array",
                    "description": "已由人工审查、且 evidence 引用存在非 .todo 文件的 key。",
                    "items": {"type": "string", "enum": evidence_keys},
                    "minItems": 1,
                },
                "review_confirmation": {
                    "type": "string",
                    "description": "必须为 human_reviewed，表示操作者已人工确认这些 evidence 可标 ready。",
                    "enum": ["human_reviewed"],
                },
            },
            "required": ["keys", "review_confirmation"],
            "additionalProperties": False,
        }

    def _product_console_action_result_input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "project_name": {
                    "type": "string",
                    "description": "必填。服务模式下指定已登记 managed project_name。",
                },
                "action_id": {
                    "type": "string",
                    "description": "推荐动作的 action_id；用于把结果重新附着到 Product Console action card。",
                },
                "tool": {
                    "type": "string",
                    "description": "被调用的 MCP tool 名称。",
                },
                "mode": {
                    "type": "string",
                    "enum": ["read", "preview", "commit"],
                    "description": "动作模式；默认 read。",
                },
                "status": {
                    "type": "string",
                    "enum": ["pending", "updated", "requested", "blocked", "failed"],
                    "description": "最近一次动作结果状态。",
                },
                "message": {
                    "type": "string",
                    "description": "短操作摘要；服务端会 redaction 和截断，不应传 raw tool output。",
                },
                "result_ok": {
                    "type": "boolean",
                    "description": "可选。原始工具结果是否成功；不存储 raw result。",
                },
                "action_fingerprint": {
                    "type": "string",
                    "description": "可选。Product Console action_fingerprint；用于识别旧结果是否仍匹配当前动作参数和结果契约。",
                },
            },
            "required": ["status"],
            "additionalProperties": False,
        }

    def _agent_operator_flow_input_schema(self) -> dict[str, Any]:
        stage_schema = self._commander_app_dependency(
            "_stage_parallel_preview_input_schema",
            _stage_parallel_preview_input_schema,
        )()
        properties = {
            "project_name": {
                "type": "string",
                "description": "必填。服务模式下指定已登记 project_name。",
            },
            "profile_id": {
                "type": "string",
                "enum": [
                    "web_gpt_commander",
                    "local_codex_commander",
                    "planner_agent",
                    "reviewer_agent",
                    "source_observer",
                ],
                "description": "可选。调用方 agent profile；默认 web_gpt_commander。",
            },
            "task_mode": {
                "type": "string",
                "enum": [
                    "auto",
                    "ordinary_task",
                    "parallel_stage",
                    "planning",
                    "review",
                    "source_observation",
                    "connector_smoke",
                    "readiness",
                ],
                "description": "可选。希望 ColaMeta 压缩的使用流程；默认 auto。",
            },
            "task_brief": {
                "type": "string",
                "description": "可选。当前任务一句话摘要；用于生成 thin governed loop draft seed，不作为执行授权。",
            },
            "include_advanced_context": {
                "type": "boolean",
                "description": "可选。是否返回高级上下文摘要；默认 true。",
            },
            "tunnel_client": self._sanitized_connector_evidence_schema(
                "可选。调用方提供的 sanitized tunnel-client 状态，只采信 status/reason_code/evidence_source/last_observed_at。"
            ),
            "control_plane": self._sanitized_connector_evidence_schema(
                "可选。调用方提供的 sanitized tunnel control-plane 状态，只采信 status/reason_code/evidence_source/last_observed_at。"
            ),
        }
        for key in ("stage_id", "provider", "base_branch", "max_parallel_tasks", "task_intents"):
            properties[key] = stage_schema["properties"][key]
        return {
            "type": "object",
            "properties": properties,
            "required": [],
            "additionalProperties": False,
        }

    def _service_entry_profiles(self) -> list[dict[str, Any]]:
        def project_args(**extra: Any) -> dict[str, Any]:
            return {"project_name": "<registered project_name>", **extra}

        profiles = [
            {
                "profile_id": "web_gpt_commander",
                "display_name": "Web GPT Commander",
                "consumer_kind": "web_gpt",
                "default_authority": "read_only_evidence_until_commander_authorization",
                "first_reads": [
                    {"tool": "list_registered_projects", "arguments": {}},
                    {"tool": "get_agent_consumer_contract", "arguments": {}},
                    {"tool": "get_agent_operator_flow_packet", "arguments": project_args(profile_id="web_gpt_commander")},
                    {"tool": "get_web_gpt_service_entrypoint", "arguments": project_args()},
                    {"tool": "render_commander_app", "arguments": project_args()},
                    {"tool": "get_stable_replacement_cadence", "arguments": project_args()},
                    {"tool": "get_stable_promotion_readiness", "arguments": project_args()},
                    {"tool": "get_stage_parallel_plan_preview", "arguments": project_args()},
                    {"tool": "get_stage_parallel_run_preview", "arguments": project_args()},
                    {"tool": "get_stage_parallel_worktree_assignment_preview", "arguments": project_args()},
                    {"tool": "get_stage_parallel_next_action_packet", "arguments": project_args()},
                    {"tool": "manage_stage_parallel_shard_inputs", "arguments": {**project_args(), "action": "preview"}},
                    {"tool": "get_stage_parallel_executor_group_preview", "arguments": project_args()},
                    {"tool": "manage_stage_parallel_executor_runs", "arguments": {**project_args(), "action": "preview"}},
                    {"tool": "get_stage_parallel_executor_results_packet", "arguments": project_args()},
                    {"tool": "get_stage_parallel_group_status", "arguments": project_args()},
                    {"tool": "get_stage_parallel_merge_preview", "arguments": project_args()},
                    {"tool": "manage_stage_parallel_merges", "arguments": {**project_args(), "action": "preview"}},
                    {"tool": "get_stage_parallel_closeout_packet", "arguments": project_args()},
                    {"tool": "get_apps_connector_smoke_packet", "arguments": project_args()},
                    {"tool": "get_connector_runtime_health_status", "arguments": project_args()},
                    {"tool": "analyze_project_state", "arguments": project_args()},
                ],
                "primary_workflow": "thin_governed_loop_preview",
                "next_payload_rule": (
                    "Use draft first. For M0-M2 local work, require codex_execution_packet.packet_status=ready, then copy "
                    "codex_execution_packet.copy_paste_codex_prompt to local Codex; "
                    "send next_request_payload only when formal evidence preview is needed."
                ),
                "write_boundary": "Requires exact Commander authorization for write/run/push/stable promotion.",
            },
            {
                "profile_id": "local_codex_commander",
                "display_name": "Local Codex Commander",
                "consumer_kind": "local_codex",
                "default_authority": "local_repo_work_with_project_boundaries",
                "first_reads": [
                    {"tool": "list_registered_projects", "arguments": {}},
                    {"tool": "get_agent_consumer_contract", "arguments": {}},
                    {"tool": "get_agent_operator_flow_packet", "arguments": project_args(profile_id="local_codex_commander")},
                    {"tool": "analyze_project_state", "arguments": project_args()},
                    {"tool": "get_connector_runtime_health_status", "arguments": project_args()},
                    {"tool": "get_stage_parallel_group_status", "arguments": project_args()},
                    {"tool": "manage_workflow_run", "arguments": project_args(action="list", limit=10)},
                    {"tool": "list_executor_run_reports", "arguments": project_args(limit=10)},
                ],
                "primary_workflow": "thin_governed_loop_preview plus local code/test loop",
                "next_payload_rule": "Use MCP for routing/evidence; keep code edits inside the local repo boundary.",
                "write_boundary": "Local repo writes follow workspace rules; MCP read-only outputs do not authorize Delivery State changes.",
            },
            {
                "profile_id": "reviewer_agent",
                "display_name": "Reviewer Agent",
                "consumer_kind": "reviewer",
                "default_authority": "review_only",
                "first_reads": [
                    {"tool": "list_registered_projects", "arguments": {}},
                    {"tool": "get_agent_consumer_contract", "arguments": {}},
                    {"tool": "get_agent_operator_flow_packet", "arguments": project_args(profile_id="reviewer_agent")},
                    {"tool": "analyze_project_state", "arguments": project_args()},
                    {"tool": "manage_workflow_run", "arguments": project_args(action="list", limit=20)},
                    {"tool": "list_executor_run_reports", "arguments": project_args(limit=20)},
                ],
                "primary_workflow": "evidence_review",
                "next_payload_rule": "Report findings as review evidence only.",
                "write_boundary": "Does not create ReviewDecision, GateEvent, or accepted Delivery State.",
            },
            {
                "profile_id": "planner_agent",
                "display_name": "Planner Agent",
                "consumer_kind": "planner",
                "default_authority": "plan_preview_only",
                "first_reads": [
                    {"tool": "list_registered_projects", "arguments": {}},
                    {"tool": "get_agent_consumer_contract", "arguments": {}},
                    {"tool": "get_agent_operator_flow_packet", "arguments": project_args(profile_id="planner_agent")},
                    {"tool": "get_web_gpt_service_entrypoint", "arguments": project_args()},
                    {
                        "tool": "run_mcp_workflow",
                        "arguments": project_args(
                            workflow="thin_governed_loop_preview",
                            phase="preview",
                            input_mode="draft",
                        ),
                    },
                ],
                "primary_workflow": "thin_governed_loop_preview",
                "next_payload_rule": "Produce draft/provided input payloads; do not dispatch execution.",
                "write_boundary": "Planning preview is not executor authority or review acceptance.",
            },
            {
                "profile_id": "source_observer",
                "display_name": "Source Observer",
                "consumer_kind": "source_observer",
                "default_authority": "source_read_only",
                "first_reads": [
                    {"tool": "list_registered_projects", "arguments": {}},
                    {"tool": "get_agent_consumer_contract", "arguments": {}},
                    {"tool": "get_agent_operator_flow_packet", "arguments": project_args(profile_id="source_observer")},
                    {"tool": "analyze_project_state", "arguments": project_args()},
                    {"tool": "get_runtime_version_status", "arguments": project_args()},
                ],
                "primary_workflow": "source_observation",
                "next_payload_rule": "Use source facts for orientation; managed workflows may be unavailable for source-only projects.",
                "write_boundary": "No managed workflow adoption, execution, or state transition.",
            },
        ]
        for profile in profiles:
            profile_id = str(profile.get("profile_id") or "")
            profile["executor_status_polling_guidance"] = self._commander_app_dependency(
                "polling_guidance_for_profile",
                polling_guidance_for_profile,
            )(profile_id)
        return profiles

    def _tool_get_service_entry_profile(self, params: dict[str, Any]) -> dict[str, Any]:
        profile_id, selected, profiles = self._select_service_entry_profile(params)
        first_reads = selected.get("first_reads", [])
        return {
            "ok": True,
            "read_only": True,
            "side_effects": False,
            "profile_id": profile_id,
            "default_profile_id": "web_gpt_commander",
            "available_profile_ids": [item["profile_id"] for item in profiles],
            "selected_profile": selected,
            "recommended_next_reads": first_reads,
            "authority": selected.get("default_authority"),
            "write_boundary": selected.get("write_boundary"),
            "tool_surface_guidance": self._tool_surface_guidance_for_actions(first_reads),
        }

    def _tool_get_agent_operator_flow_packet(
        self,
        params: dict[str, Any],
        *,
        embedded_in_commander_manifest: bool = False,
    ) -> dict[str, Any]:
        profile_id, selected_profile, profiles = self._select_service_entry_profile(params)
        project_root, project_record = self._resolve_read_only_project_context(params)
        project_name = self._project_name_for_context(project_root, project_record, params)
        project_args = {"project_name": project_name}
        tunnel_client = self._connector_external_evidence_param(params, "tunnel_client")
        control_plane = self._connector_external_evidence_param(params, "control_plane")
        local_service = self._connector_runtime_local_service_evidence(project_root)
        runtime_status = self._runtime_version_status_for_project(project_root, local_service=local_service)
        connector_health = self._commander_app_dependency(
            "get_connector_runtime_health_status",
            get_connector_runtime_health_status,
        )(
            runtime_status=runtime_status,
            local_service=local_service,
            tunnel_client=tunnel_client,
            control_plane=control_plane,
        )
        readiness = self._commander_app_dependency(
            "build_service_readiness_summary",
            build_service_readiness_summary,
        )(
            runtime_status=runtime_status,
            connector_health=connector_health,
            project_name=project_name,
        )
        apps_connector_closeout = self._commander_app_dependency(
            "build_apps_connector_closeout_packet",
            build_apps_connector_closeout_packet,
        )(
            project_name=project_name,
            connector_health=connector_health,
        )
        product_console_map = self._commander_app_dependency(
            "build_product_console_map",
            build_product_console_map,
        )(
            project_root,
            project_name=project_name,
            readiness_packet=self._agent_flow_projected_product_readiness(readiness),
        )
        product_console_completion = (
            product_console_map.get("completion_surface")
            if isinstance(product_console_map.get("completion_surface"), dict)
            else {}
        )
        stable_cadence = self._stable_replacement_hint(project_root, runtime_status)
        requested_mode = self._normalize_agent_task_mode(params.get("task_mode"))
        task_brief = params.get("task_brief") if isinstance(params.get("task_brief"), str) else ""
        flow_mode = self._resolve_agent_flow_mode(
            requested_mode=requested_mode,
            consumer_kind=str(selected_profile.get("consumer_kind") or ""),
            task_brief=task_brief,
        )
        primary_next_action, embedded_packets = self._agent_flow_primary_next_action(
            params=params,
            project_args=project_args,
            project_root=project_root,
            project_name=project_name,
            profile_id=profile_id,
            consumer_kind=str(selected_profile.get("consumer_kind") or ""),
            flow_mode=flow_mode,
            task_brief=task_brief,
            readiness=readiness,
            apps_connector_closeout=apps_connector_closeout,
            product_console_completion=product_console_completion,
            embedded_in_commander_manifest=embedded_in_commander_manifest,
        )
        token_recovery = apps_connector_closeout.get("token_expired_recovery")
        if not isinstance(token_recovery, dict):
            token_recovery = {}
        include_advanced_context = params.get("include_advanced_context") is not False
        advanced_actions = self._agent_flow_advanced_actions(
            project_args=project_args,
            profile_id=profile_id,
            consumer_kind=str(selected_profile.get("consumer_kind") or ""),
            flow_mode=flow_mode,
            task_brief=task_brief,
        )
        forbidden_workflows = self._agent_flow_forbidden_workflows(
            profile_id=profile_id,
            consumer_kind=str(selected_profile.get("consumer_kind") or ""),
        )
        tool_surface_guidance = self._tool_surface_guidance_for_actions(
            [primary_next_action, *advanced_actions]
        )
        current_state = {
            "project_name": project_name,
            "profile_id": profile_id,
            "consumer_kind": selected_profile.get("consumer_kind"),
            "requested_task_mode": requested_mode,
            "resolved_flow_mode": flow_mode,
            "readiness": {
                "status": readiness.get("status"),
                "primary_blocker": readiness.get("primary_blocker"),
                "safe_next_actions": readiness.get("safe_next_actions"),
            },
            "runtime": {
                "project_checkout_head": runtime_status.get("project_checkout_head"),
                "loaded_runtime_head": runtime_status.get("loaded_runtime_head"),
                "runtime_loaded_code_stale": runtime_status.get("runtime_loaded_code_stale"),
                "reload_needed_for_verification": runtime_status.get("reload_needed_for_verification"),
                "reload_awareness_reason": runtime_status.get("reload_awareness_reason"),
            },
            "connector": {
                "overall_status": connector_health.get("overall_status"),
                "local_service_status": (
                    connector_health.get("local_service", {}).get("status")
                    if isinstance(connector_health.get("local_service"), dict)
                    else None
                ),
                "external_connector_status": (
                    connector_health.get("external_connector", {}).get("status")
                    if isinstance(connector_health.get("external_connector"), dict)
                    else None
                ),
                "operator_closeout": (
                    connector_health.get("operator_closeout", {}).get("status")
                    if isinstance(connector_health.get("operator_closeout"), dict)
                    else None
                ),
                "evidence_gap_count": (
                    connector_health.get("operator_closeout", {}).get("evidence_gap_count")
                    if isinstance(connector_health.get("operator_closeout"), dict)
                    else None
                ),
            },
            "apps_connector": {
                "status": apps_connector_closeout.get("status"),
                "next_action": apps_connector_closeout.get("next_action"),
                "token_expired_code": token_recovery.get("token_expired_code") or "token_expired",
            },
            "product_console": self._agent_flow_product_console_state(product_console_completion),
            "stable_cadence": {
                "relationship": stable_cadence.get("relationship"),
                "stable_replacement_not_required": stable_cadence.get("stable_replacement_not_required"),
                "recommended_cadence": stable_cadence.get("recommended_cadence"),
                "exact_authorization_required": stable_cadence.get("exact_authorization_required"),
                "dev_batch_summary": stable_cadence.get("dev_batch_summary"),
                "batch_review_summary": stable_cadence.get("batch_review_summary"),
            },
        }
        result: dict[str, Any] = {
            "ok": True,
            "source": "agent_operator_flow_packet",
            "scope": "mcp:read",
            "read_only": True,
            "side_effects": False,
            "flow_packet_version": "agent_operator_flow.v1",
            "project_name": project_name,
            "profile_id": profile_id,
            "selected_profile": selected_profile,
            "current_state": current_state,
            "primary_next_action": primary_next_action,
            "persona_safe_next_tool": primary_next_action.get("tool"),
            "requires_confirmation_before_preview": bool(
                primary_next_action.get("requires_confirmation_before_preview")
            ),
            "requires_confirmation_before_write_or_run": True,
            "forbidden_workflows": forbidden_workflows,
            "copyable_tool_call": primary_next_action.get("copyable_tool_call"),
            "advanced_actions": advanced_actions,
            "tool_surface_guidance": tool_surface_guidance,
            "flow_usage_rule": {
                "start_here": True,
                "execute_only_one_primary_action_then_reassess": True,
                "smart_agents_should_use_advanced_context_before_escalating": True,
                "do_not_infer_missing_authority_from_this_packet": True,
                "if_tool_not_visible_use_tool_search_or_http_mcp_fallback": True,
            },
            "authority_boundary": {
                "flow_packet_is_read_only": True,
                "does_not_create_preview_artifact": True,
                "does_not_start_executor": True,
                "does_not_merge": True,
                "does_not_commit": True,
                "does_not_push": True,
                "does_not_replace_stable": True,
                "does_not_write_delivery_accepted": True,
                "does_not_create_review_decision": True,
                "does_not_create_gate_event": True,
                "does_not_read_tokens_or_cookies": True,
                "does_not_read_tunnel_client_config": True,
                "does_not_read_raw_logs": True,
            },
        }
        if include_advanced_context:
            result["advanced_context"] = {
                "available_profile_ids": [item["profile_id"] for item in profiles],
                "profile_first_reads": selected_profile.get("first_reads", []),
                "embedded_read_only_packets": embedded_packets,
                "product_console_completion_surface": product_console_completion,
                "service_entry_profiles_version": "service_entry_profiles.v1",
                "project_identity": self._project_identity_for_root(project_root),
            }
            if isinstance(project_record, dict):
                result["advanced_context"]["project_record"] = project_record
        return result

    @staticmethod
    def _resolve_agent_flow_mode(*, requested_mode: str, consumer_kind: str, task_brief: str) -> str:
        if requested_mode != "auto":
            return requested_mode
        if consumer_kind == "planner":
            return "planning"
        if consumer_kind == "reviewer":
            return "review"
        if consumer_kind == "source_observer":
            return "source_observation"
        if task_brief.strip():
            return "ordinary_task"
        return "readiness"

    def _agent_flow_primary_next_action(
        self,
        *,
        params: dict[str, Any],
        project_args: dict[str, Any],
        project_root: str,
        project_name: str,
        profile_id: str,
        consumer_kind: str,
        flow_mode: str,
        task_brief: str,
        readiness: dict[str, Any],
        apps_connector_closeout: dict[str, Any],
        product_console_completion: dict[str, Any],
        embedded_in_commander_manifest: bool = False,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        embedded_packets: dict[str, Any] = {}
        if flow_mode == "parallel_stage":
            stage_packet = self._commander_app_dependency(
                "build_stage_parallel_next_action_packet",
                build_stage_parallel_next_action_packet,
            )(**self._stage_parallel_builder_args(params))
            embedded_packets["stage_parallel_next_action_packet"] = stage_packet
            nested_call = stage_packet.get("copyable_tool_call") if isinstance(stage_packet.get("copyable_tool_call"), dict) else {}
            tool = str(nested_call.get("tool") or "get_stage_parallel_next_action_packet")
            arguments = nested_call.get("arguments") if isinstance(nested_call.get("arguments"), dict) else dict(project_args)
            next_action = stage_packet.get("next_action") if isinstance(stage_packet.get("next_action"), dict) else {}
            return self._agent_flow_action(
                action_id=f"parallel_stage_{stage_packet.get('phase') or 'next_action'}",
                label="Follow stage parallel next action",
                tool=tool,
                arguments=arguments,
                reason=str(next_action.get("reason") or "Use stage parallel state to choose the next safe gate."),
                expected_output="Next stage-parallel packet, preview artifact, executor result packet, or blocker evidence.",
                derived_from="get_stage_parallel_next_action_packet",
                requires_confirmation=bool(next_action.get("requires_confirmation")),
            ), embedded_packets

        if flow_mode == "connector_smoke":
            return self._agent_flow_action(
                action_id="apps_connector_smoke",
                label="Read Apps connector smoke packet",
                tool="get_apps_connector_smoke_packet",
                arguments=dict(project_args),
                reason="Connector closeout needs the Apps project-list and sanitized connector health handoff in one read-only packet.",
                expected_output="Apps connector reachability, project list check, connector closeout call, and token_expired recovery guidance.",
            ), embedded_packets

        if flow_mode == "review":
            return self._agent_flow_action(
                action_id="review_recent_evidence",
                label="Read recent workflow and executor evidence",
                tool="manage_workflow_run",
                arguments={**project_args, "action": "list", "limit": 20},
                reason="Reviewer agents should gather workflow evidence first and report findings without creating ReviewDecision or GateEvent.",
                expected_output="Recent controlled workflow records for review orientation.",
            ), embedded_packets

        if flow_mode == "source_observation":
            return self._agent_flow_action(
                action_id="inspect_project_state",
                label="Inspect project state",
                tool="analyze_project_state",
                arguments=dict(project_args),
                reason="Source observers need project facts and recommended reads before suggesting or changing anything.",
                expected_output="Project mode, Git state, Runner status, executor/report summary, and safe recommended reads.",
            ), embedded_packets

        if flow_mode in {"ordinary_task", "planning"}:
            draft_seed: dict[str, Any] = {
                "task_tier": "M0-M2",
            }
            if task_brief.strip():
                draft_seed["goal"] = task_brief.strip()
                draft_seed["objective"] = task_brief.strip()
            return self._agent_flow_action(
                action_id="thin_governed_loop_draft",
                label="Create thin governed loop draft packet",
                tool="run_mcp_workflow",
                arguments={
                    **project_args,
                    "workflow": "thin_governed_loop_preview",
                    "phase": "preview",
                    "input_mode": "draft",
                    "draft_seed": draft_seed,
                },
                reason=(
                    "Planner/Web GPT/Local Codex can use the returned codex_execution_packet for bounded local work; "
                    "this call itself is read-only evidence and does not dispatch execution."
                ),
                expected_output="codex_execution_packet plus allowed files, validation commands, and authority boundary.",
            ), embedded_packets

        readiness_status = str(readiness.get("status") or "")
        if readiness_status and readiness_status != "ready":
            safe_actions = readiness.get("safe_next_actions") if isinstance(readiness.get("safe_next_actions"), list) else []
            if safe_actions:
                first = safe_actions[0] if isinstance(safe_actions[0], dict) else {}
                tool = str(first.get("tool") or "get_commander_app_manifest")
                arguments = first.get("arguments") if isinstance(first.get("arguments"), dict) else dict(project_args)
                if tool in {"get_commander_app_manifest", "get_agent_operator_flow_packet", "render_commander_app"}:
                    arguments = {**arguments, "profile_id": profile_id}
                return self._agent_flow_action(
                    action_id="readiness_safe_next_action",
                    label=str(first.get("label") or "Follow readiness safe next action"),
                    tool=tool,
                    arguments=arguments,
                    reason=str(first.get("why") or first.get("reason") or "Readiness is not ready; follow the first safe read-only action."),
                    expected_output="Updated service readiness evidence or a clear blocker.",
                    derived_from="service_readiness_summary",
                ), embedded_packets
        if apps_connector_closeout.get("status") != "ready" and consumer_kind == "web_gpt":
            return self._agent_flow_action(
                action_id="apps_connector_smoke",
                label="Read Apps connector smoke packet",
                tool="get_apps_connector_smoke_packet",
                arguments=dict(project_args),
                reason="Web GPT should verify Apps connector reachability and connector closeout before coordinating external handoff.",
                expected_output="Apps connector project-list check and connector closeout packet.",
            ), embedded_packets
        product_console_next = self._agent_flow_product_console_next_action(
            project_args=project_args,
            profile_id=profile_id,
            product_console_completion=product_console_completion,
        )
        if product_console_next is not None:
            return product_console_next, embedded_packets
        if embedded_in_commander_manifest:
            return self._agent_flow_action(
                action_id="continue_with_requested_work",
                label="Continue with the requested work",
                tool="run_mcp_workflow",
                arguments={
                    **project_args,
                    "workflow": "thin_governed_loop_preview",
                    "phase": "preview",
                    "input_mode": "draft",
                    "draft_seed": {"task_tier": "M0-M2"},
                },
                reason=(
                    "Commander readiness and closeout are complete; continue through the bounded read-only task packet "
                    "instead of refreshing the manifest recursively."
                ),
                expected_output="codex_execution_packet plus bounded task scope and validation guidance.",
            ), embedded_packets
        return self._agent_flow_action(
            action_id="read_commander_manifest",
            label="Read Commander manifest",
            tool="get_commander_app_manifest",
            arguments={**project_args, "profile_id": profile_id},
            reason="No task-specific mode was selected; read the commander manifest for the current dashboard and safe next actions.",
            expected_output="Readiness, connector, runtime, profile entries, and preview-first workflow actions.",
        ), embedded_packets

    def _agent_flow_product_console_next_action(
        self,
        *,
        project_args: dict[str, Any],
        profile_id: str,
        product_console_completion: dict[str, Any],
    ) -> dict[str, Any] | None:
        if product_console_completion.get("ready") is True:
            return None
        queue = product_console_completion.get("followup_queue")
        if not isinstance(queue, dict):
            return None
        next_item = queue.get("next_item")
        if not isinstance(next_item, dict):
            return None
        primary = next_item.get("primary_action") if isinstance(next_item.get("primary_action"), dict) else {}
        tool = str(primary.get("tool") or next_item.get("primary_tool") or "get_product_console_map")
        arguments = primary.get("arguments") if isinstance(primary.get("arguments"), dict) else dict(project_args)
        if tool in {"get_commander_app_manifest", "get_agent_operator_flow_packet", "render_commander_app"}:
            arguments = {**arguments, "profile_id": profile_id}
        if tool == "get_product_console_map":
            arguments = {**project_args, **arguments}
        return self._agent_flow_action(
            action_id=f"product_console_closeout_{next_item.get('item_id') or 'followup'}",
            label=str(next_item.get("label") or "Follow Product Console closeout"),
            tool=tool,
            arguments=arguments,
            reason=str(primary.get("why") or next_item.get("empty_state") or "Product Console closeout still has follow-up items."),
            expected_output="Updated Product Console completion surface, recorded action result, or explicit closeout blocker.",
            derived_from="product_console_closeout_followup_queue",
        )

    @staticmethod
    def _agent_flow_projected_product_readiness(readiness: dict[str, Any]) -> dict[str, Any]:
        safe_actions = readiness.get("safe_next_actions") if isinstance(readiness.get("safe_next_actions"), list) else []
        safe_next_action = safe_actions[0] if safe_actions and isinstance(safe_actions[0], dict) else {}
        status = str(readiness.get("status") or "unknown")
        return {
            "ok": True,
            "source": "service_readiness_summary_projection",
            "read_only": True,
            "side_effects": False,
            "status": status,
            "ready": status == "ready",
            "primary_blocker": readiness.get("primary_blocker"),
            "safe_next_action": safe_next_action,
            "authority_boundary": {
                "projection_is_read_only": True,
                "does_not_run_ops_check": True,
                "does_not_run_remote_preflight": True,
            },
        }

    @staticmethod
    def _agent_flow_product_console_state(product_console_completion: dict[str, Any]) -> dict[str, Any]:
        queue = product_console_completion.get("followup_queue")
        if not isinstance(queue, dict):
            queue = {}
        next_item = queue.get("next_item")
        if not isinstance(next_item, dict):
            next_item = {}
        return {
            "completion_status": product_console_completion.get("status"),
            "ready": product_console_completion.get("ready"),
            "gap_count": product_console_completion.get("gap_count"),
            "blocker_codes": product_console_completion.get("blocker_codes"),
            "needs_attention_codes": product_console_completion.get("needs_attention_codes"),
            "followup_queue": {
                "source": queue.get("source"),
                "status": queue.get("status"),
                "total_count": queue.get("total_count"),
                "next_item_id": next_item.get("item_id"),
                "next_primary_tool": next_item.get("primary_tool"),
                "next_required_scope": next_item.get("required_scope"),
                "next_gate_level": next_item.get("gate_level"),
            },
        }

    def _agent_flow_action(
        self,
        *,
        action_id: str,
        label: str,
        tool: str,
        arguments: dict[str, Any],
        reason: str,
        expected_output: str,
        derived_from: str | None = None,
        requires_confirmation: bool = False,
    ) -> dict[str, Any]:
        scope = self._required_scope_for_tool(tool, arguments)
        gate_level = self._agent_flow_gate_level(tool=tool, arguments=arguments, scope=scope)
        requires_preview_confirmation = bool(requires_confirmation or scope == "mcp:preview")
        requires_write_or_run_confirmation = bool(scope != "mcp:read")
        return {
            "action_id": action_id,
            "label": label,
            "tool": tool,
            "arguments": arguments,
            "required_scope": scope,
            "gate_level": gate_level,
            "reason": reason,
            "expected_output": expected_output,
            "derived_from": derived_from,
            "requires_confirmation_before_preview": requires_preview_confirmation,
            "requires_confirmation_before_write_or_run": requires_write_or_run_confirmation,
            "requires_confirmation_before_execution": bool(
                requires_preview_confirmation or requires_write_or_run_confirmation
            ),
            "copyable_tool_call": {
                "tool": tool,
                "arguments": arguments,
            },
        }

    @staticmethod
    def _agent_flow_gate_level(*, tool: str, arguments: dict[str, Any], scope: str) -> str:
        if scope == "mcp:read":
            if tool == "run_mcp_workflow":
                return "read_only_workflow_packet"
            return "read_only"
        if scope == "mcp:preview":
            action = arguments.get("action") if isinstance(arguments, dict) else None
            if action == "preview":
                return "preview_artifact"
            return "preview_gate"
        if scope == "mcp:commit":
            return "explicit_apply_or_run_required"
        return scope

    def _agent_flow_advanced_actions(
        self,
        *,
        project_args: dict[str, Any],
        profile_id: str,
        consumer_kind: str,
        flow_mode: str,
        task_brief: str,
    ) -> list[dict[str, Any]]:
        draft_seed: dict[str, Any] = {"task_tier": "M0-M2"}
        if task_brief.strip():
            draft_seed["goal"] = task_brief.strip()
            draft_seed["objective"] = task_brief.strip()
        profile_contract = {
            "label": "Profile contract",
            "tool": "get_service_entry_profile",
            "arguments": {"profile_id": profile_id},
            "gate_level": "read_only",
        }
        project_state = {
            "label": "Project state",
            "tool": "analyze_project_state",
            "arguments": dict(project_args),
            "gate_level": "read_only",
        }
        runtime_status = {
            "label": "Runtime status",
            "tool": "get_runtime_version_status",
            "arguments": dict(project_args),
            "gate_level": "read_only",
        }
        thin_loop_draft = {
            "label": "Thin loop draft",
            "tool": "run_mcp_workflow",
            "arguments": {
                **project_args,
                "workflow": "thin_governed_loop_preview",
                "phase": "preview",
                "input_mode": "draft",
                "draft_seed": draft_seed,
            },
            "gate_level": "read_only_workflow_packet",
        }
        stage_parallel_next_action = {
            "label": "Stage parallel next action",
            "tool": "get_stage_parallel_next_action_packet",
            "arguments": dict(project_args),
            "gate_level": "read_only",
        }
        recent_workflow_records = {
            "label": "Recent workflow records",
            "tool": "manage_workflow_run",
            "arguments": {**project_args, "action": "list", "limit": 10},
            "gate_level": "read_only",
        }
        executor_reports = {
            "label": "Executor reports",
            "tool": "list_executor_run_reports",
            "arguments": {**project_args, "limit": 10},
            "gate_level": "read_only",
        }
        apps_connector_smoke = {
            "label": "Apps connector smoke",
            "tool": "get_apps_connector_smoke_packet",
            "arguments": dict(project_args),
            "gate_level": "read_only",
        }
        stable_cadence = {
            "label": "Stable cadence",
            "tool": "get_stable_replacement_cadence",
            "arguments": dict(project_args),
            "gate_level": "read_only",
        }

        if consumer_kind == "source_observer":
            return [profile_contract, project_state, runtime_status, apps_connector_smoke]
        if consumer_kind == "reviewer":
            return [profile_contract, project_state, recent_workflow_records, apps_connector_smoke]
        if consumer_kind == "planner":
            return [
                profile_contract,
                project_state,
                thin_loop_draft,
                stage_parallel_next_action,
                recent_workflow_records,
                apps_connector_smoke,
            ]
        if consumer_kind == "local_codex":
            return [
                profile_contract,
                project_state,
                thin_loop_draft,
                stage_parallel_next_action,
                recent_workflow_records,
                executor_reports,
                apps_connector_smoke,
            ]
        return [
            profile_contract,
            project_state,
            runtime_status,
            thin_loop_draft,
            stage_parallel_next_action,
            recent_workflow_records,
            executor_reports,
            apps_connector_smoke,
            stable_cadence,
        ]

    @staticmethod
    def _agent_flow_forbidden_workflows(*, profile_id: str, consumer_kind: str) -> list[str]:
        common = [
            "stable_replacement_without_exact_authorization",
            "delivery_accepted_write",
            "review_decision_write",
            "gate_event_write",
            "token_cookie_credential_access",
            "raw_tunnel_log_or_config_read",
        ]
        by_consumer = {
            "web_gpt": [
                "executor_run_without_current_authorization",
                "commit_or_push_without_current_authorization",
            ],
            "local_codex": [
                "executor_run_without_preview_or_current_authorization",
            ],
            "planner": [
                "executor_run",
                "commit_or_push",
            ],
            "reviewer": [
                "source_write",
                "executor_run",
                "commit_or_push",
                "stable_replacement",
            ],
            "source_observer": [
                "source_write",
                "managed_workflow_apply",
                "executor_run",
                "commit_or_push",
                "stable_replacement",
            ],
        }
        selected = by_consumer.get(consumer_kind, [])
        return [*selected, *common]

    def _tool_get_agent_consumer_contract(self, _: dict[str, Any]) -> dict[str, Any]:
        visible_tools = self._visible_tool_names()
        return {
            "ok": True,
            "read_only": True,
            "side_effects": False,
            "contract_version": "agent_consumer_contract.v1",
            "scope": "mcp:read",
            "service_mode": bool(self.service_mode),
            "mcp_exposure_profile": self.mcp_exposure_profile,
            "visible_tool_count": len(visible_tools),
            "outer_tool_result_envelope": {
                "success_required_fields": ["ok", "tool", "data"],
                "success_shape": {
                    "ok": True,
                    "tool": "<tool_name>",
                    "data": "<tool-specific payload>",
                },
                "error_required_fields": ["ok", "tool", "error_code", "message", "details"],
                "error_shape": {
                    "ok": False,
                    "tool": "<tool_name>",
                    "error_code": "<machine_readable_code>",
                    "message": "<human_readable_message>",
                    "details": "<structured object>",
                },
                "large_result_shape": {
                    "ok": "<original ok>",
                    "tool": "<tool_name>",
                    "packaged": True,
                    "package_mode": "manifest",
                    "summary": "<compact summary>",
                    "omitted_fields": ["data"],
                    "recommended_next_reads": "<follow-up reads>",
                },
            },
            "data_payload_recommendation": {
                "standard_success_fields": ["ok", "read_only", "side_effects"],
                "meaning": {
                    "ok": "Payload-level success flag when the payload can independently report success.",
                    "read_only": "True means the tool only read evidence or produced a preview.",
                    "side_effects": "False means the payload declares no state mutation.",
                },
                "compatibility_note": (
                    "Older payloads may omit payload-level ok/read_only/side_effects; "
                    "agents must first trust the outer envelope and then use payload fields when present."
                ),
            },
            "project_routing_contract": {
                "service_mode_project_tools_require_project_name": bool(self.service_mode),
                "do_not_send_project_root_when_project_name_is_used": True,
                "discover_projects_first": "list_registered_projects",
                "missing_project_name_error_code": "PROJECT_NAME_REQUIRED",
                "invalid_project_name_error_code": "INVALID_PROJECT_NAME",
                "project_root_override_error_code": "PROJECT_ROOT_OVERRIDE_NOT_ALLOWED",
                "source_only_managed_workflow_error_code": "PROJECT_MODE_UNSUPPORTED",
            },
            "chatgpt_apps_contract": {
                "app_name": COMMANDER_APP_TITLE,
                "archetype": "interactive-decoupled",
                "data_tool": "get_commander_app_manifest",
                "render_tool": "render_commander_app",
                "widget_resource_uri": COMMANDER_APP_WIDGET_URI,
                "resource_methods": ["resources/list", "resources/read"],
                "render_tool_meta": ["ui.resourceUri", "openai/outputTemplate"],
                "widget_only_meta_is_not_part_of_structured_content": True,
            },
            "client_experience_partition": self._client_experience_partition(),
            "authority_boundary": {
                "read_only_tools_do_not_authorize_executor_dispatch": True,
                "read_only_tools_do_not_create_review_decision": True,
                "read_only_tools_do_not_emit_gate_event": True,
                "read_only_tools_do_not_write_delivery_state": True,
                "stable_promotion_requires_external_commander_authorization": True,
            },
            "recommended_first_reads": [
                {"tool": "list_registered_projects", "why": "Discover allowed project_name values."},
                {"tool": "get_agent_consumer_contract", "why": "Load this consumer contract."},
                {"tool": "get_service_entry_profile", "why": "Select a consumer-specific entry profile."},
                {"tool": "get_agent_operator_flow_packet", "why": "Get one role-aware primary next action before choosing lower-level tools."},
                {"tool": "get_web_gpt_service_entrypoint", "why": "Read guided service entry flow."},
                {"tool": "render_commander_app", "why": "Open the ChatGPT Apps Commander panel with project_name."},
                {"tool": "get_commander_app_manifest", "why": "Read the same Commander App contract without rendering UI."},
                {"tool": "get_apps_connector_smoke_packet", "why": "Run the Apps connector project-list and connector-closeout smoke checklist."},
                {"tool": "get_stable_replacement_cadence", "why": "Read whether dev/stable drift should be batched instead of promoted immediately."},
                {"tool": "get_stable_promotion_readiness", "why": "Check runtime/project readiness with project_name."},
                {"tool": "get_stage_parallel_plan_preview", "why": "Preview stage-level parallel task sharding without starting executors."},
                {"tool": "get_stage_parallel_run_preview", "why": "Preview isolated parallel run orchestration without creating worktrees or executor previews."},
                {"tool": "get_stage_parallel_worktree_assignment_preview", "why": "Check deterministic worktree and branch assignments without creating them."},
                {"tool": "get_stage_parallel_next_action_packet", "why": "Read the current stage parallel state and get the single recommended next tool call."},
                {"tool": "manage_stage_parallel_shard_inputs", "why": "Preview shard-specific runner input materialization after isolated worktrees exist."},
                {"tool": "get_stage_parallel_executor_group_preview", "why": "Preview executor group requests without creating previews or starting runs."},
                {"tool": "manage_stage_parallel_executor_runs", "why": "Preview the executor run group after run_once_preview artifacts exist; apply starts isolated executor runs only."},
                {"tool": "get_stage_parallel_executor_results_packet", "why": "Read structured parallel executor claim/report summaries without raw logs."},
                {"tool": "get_stage_parallel_group_status", "why": "Read planned or provided shard result status before merge preview."},
                {"tool": "get_stage_parallel_merge_preview", "why": "Preview merge order and validation gates after shard results pass."},
                {"tool": "manage_stage_parallel_merges", "why": "Preview the controlled local merge gate; apply performs local git merge only."},
                {"tool": "get_stage_parallel_closeout_packet", "why": "Prepare the stage parallel closeout packet for human review."},
                {"tool": "get_connector_runtime_health_status", "why": "Check local/runtime/external connector closeout with project_name."},
                {"tool": "analyze_project_state", "why": "Inspect project facts with project_name."},
            ],
            "service_entry_profiles_version": "service_entry_profiles.v1",
            "service_entry_profiles": self._service_entry_profiles(),
            "thin_loop_consumer_rule": {
                "draft_mode": "Call run_mcp_workflow with input_mode=draft and draft_seed.",
                "m0_m2_direct_mode": "When result.codex_execution_packet.packet_status is ready, use result.codex_execution_packet.copy_paste_codex_prompt as the local Codex task packet; provided preview is optional.",
                "provided_mode": "Use result.next_request_payload only when formal thin-loop evidence preview is needed.",
                "authority": "thin_governed_loop_preview remains read-only preparation/evidence and does not authorize acceptance, executor dispatch, commit, or push.",
            },
        }

    def _tool_get_web_gpt_service_entrypoint(self, params: dict[str, Any]) -> dict[str, Any]:
        visible_names = self._visible_tool_names()
        project_identity: dict[str, Any] | None = None
        project_name = params.get("project_name")
        if project_name is not None:
            project_root, project_record = self._resolve_read_only_project_context(params)
            project_identity = self._project_identity_for_root(project_root)
            project_identity["project"] = project_record

        registered_projects = self._web_gpt_registered_project_summary()
        return {
            "ok": True,
            "read_only": True,
            "side_effects": False,
            "service_profile": {
                "service_name": "ColaMeta MCP",
                "mode": "service" if self.service_mode else "project",
                "mcp_exposure_profile": self.mcp_exposure_profile,
                "project_name_required_for_project_tools": bool(self.service_mode),
                "project_hint": self.project_hint,
                "visible_tool_count": len(visible_names),
            },
            "project_identity": project_identity,
            "registered_projects": registered_projects,
            "service_entry_profiles_version": "service_entry_profiles.v1",
            "service_entry_profiles": self._service_entry_profiles(),
            "entry_sequence": [
                {
                    "step": "discover_projects",
                    "tool": "list_registered_projects",
                    "arguments": {},
                    "why": "服务模式下先确认可用 project_name；不要猜项目目录。",
                },
                {
                    "step": "read_agent_consumer_contract",
                    "tool": "get_agent_consumer_contract",
                    "arguments": {},
                    "why": "确认统一 envelope、project_name 路由、只读边界和错误处理规则。",
                },
                {
                    "step": "select_service_entry_profile",
                    "tool": "get_service_entry_profile",
                    "arguments": {"profile_id": "web_gpt_commander"},
                    "why": "按当前消费者角色读取最小进入路径，不把其他 agent 的路径混进来。",
                },
                {
                    "step": "read_agent_operator_flow_packet",
                    "tool": "get_agent_operator_flow_packet",
                    "arguments": {"project_name": "<registered project_name>", "profile_id": "web_gpt_commander"},
                    "why": "先读取一个 role-aware primary_next_action，再决定是否进入底层高级工具链。",
                },
                {
                    "step": "render_commander_app",
                    "tool": "render_commander_app",
                    "arguments": {"project_name": "<registered project_name>", "profile_id": "web_gpt_commander"},
                    "why": "打开 ChatGPT Apps Commander 面板，统一展示服务事实、connector health、profiles 和授权闸门。",
                },
                {
                    "step": "inspect_stable_replacement_cadence",
                    "tool": "get_stable_replacement_cadence",
                    "arguments": {"project_name": "<registered project_name>"},
                    "why": "确认 dev ahead stable 是正常批次状态，不把普通 drift 当成稳定替换请求。",
                },
                {
                    "step": "inspect_stage_parallel_plan_preview",
                    "tool": "get_stage_parallel_plan_preview",
                    "arguments": {"project_name": "<registered project_name>"},
                    "why": "预览阶段级并行任务拆分和文件边界，不启动 executor。",
                },
                {
                    "step": "inspect_stage_parallel_run_preview",
                    "tool": "get_stage_parallel_run_preview",
                    "arguments": {"project_name": "<registered project_name>"},
                    "why": "预览隔离 worktree/branch 和未来 executor preview request，不创建执行器 preview。",
                },
                {
                    "step": "inspect_stage_parallel_worktree_assignment_preview",
                    "tool": "get_stage_parallel_worktree_assignment_preview",
                    "arguments": {"project_name": "<registered project_name>"},
                    "why": "检查每个 shard 的 worktree path 和 branch 是否可分配，但不创建。",
                },
                {
                    "step": "inspect_stage_parallel_next_action_packet",
                    "tool": "get_stage_parallel_next_action_packet",
                    "arguments": {"project_name": "<registered project_name>"},
                    "why": "读取当前并行阶段状态，获得唯一 recommended next tool call；这个 packet 不创建 preview artifact。",
                },
                {
                    "step": "preview_stage_parallel_shard_inputs",
                    "tool": "manage_stage_parallel_shard_inputs",
                    "arguments": {"project_name": "<registered project_name>", "action": "preview"},
                    "why": "隔离 worktree 已存在后，预览每个 shard 的 runner input materialization；apply 只写 runtime plan/state/prompt overlay。",
                },
                {
                    "step": "inspect_stage_parallel_executor_group_preview",
                    "tool": "get_stage_parallel_executor_group_preview",
                    "arguments": {"project_name": "<registered project_name>"},
                    "why": "预览 future executor preview group，不创建 preview，也不启动 executor。",
                },
                {
                    "step": "preview_stage_parallel_executor_runs",
                    "tool": "manage_stage_parallel_executor_runs",
                    "arguments": {"project_name": "<registered project_name>", "action": "preview"},
                    "why": "executor preview artifacts 已存在后，预览并行 executor run group；apply 才会启动隔离 worktree executor。",
                },
                {
                    "step": "inspect_stage_parallel_executor_results_packet",
                    "tool": "get_stage_parallel_executor_results_packet",
                    "arguments": {"project_name": "<registered project_name>"},
                    "why": "读取 structured executor claim/report 摘要，生成 sanitized executor_results；不读 raw logs。",
                },
                {
                    "step": "inspect_stage_parallel_group_status",
                    "tool": "get_stage_parallel_group_status",
                    "arguments": {"project_name": "<registered project_name>"},
                    "why": "读取 planned 或 sanitized executor result 状态，判断是否可进入 merge preview。",
                },
                {
                    "step": "inspect_stage_parallel_merge_preview",
                    "tool": "get_stage_parallel_merge_preview",
                    "arguments": {"project_name": "<registered project_name>"},
                    "why": "结果齐备后预览 merge order 和 validation gates，不执行 merge。",
                },
                {
                    "step": "preview_stage_parallel_merge_apply",
                    "tool": "manage_stage_parallel_merges",
                    "arguments": {"project_name": "<registered project_name>", "action": "preview"},
                    "why": "merge preview ready 后生成受控 merge apply preview；apply 才会执行本地 git merge。",
                },
                {
                    "step": "inspect_stage_parallel_closeout_packet",
                    "tool": "get_stage_parallel_closeout_packet",
                    "arguments": {"project_name": "<registered project_name>"},
                    "why": "生成人审 closeout packet；不写 Delivery accepted / ReviewDecision / GateEvent。",
                },
                {
                    "step": "inspect_stable_promotion_readiness",
                    "tool": "get_stable_promotion_readiness",
                    "arguments": {"project_name": "<registered project_name>"},
                    "why": "确认当前服务是否只是 dev 试用、可进入稳定晋升审查，还是仍有本地阻断。",
                },
                {
                    "step": "inspect_apps_connector_smoke",
                    "tool": "get_apps_connector_smoke_packet",
                    "arguments": {"project_name": "<registered project_name>"},
                    "why": "确认 Apps connector 可达、项目列表命中、connector closeout 调用形状和 token_expired 处理边界。",
                },
                {
                    "step": "inspect_connector_runtime_health",
                    "tool": "get_connector_runtime_health_status",
                    "arguments": {"project_name": "<registered project_name>"},
                    "why": "确认 local Web/MCP、runtime freshness、external connector/tunnel evidence 是否闭合。",
                },
                {
                    "step": "inspect_project_state",
                    "tool": "analyze_project_state",
                    "arguments": {"project_name": "<registered project_name>"},
                    "why": "开工前确认 Git、Runner、Executor、报告和阻断。",
                },
                {
                    "step": "inspect_recent_evidence",
                    "tool": "manage_workflow_run",
                    "arguments": {"action": "list", "project_name": "<registered project_name>", "limit": 10},
                    "why": "查看最近受控操作记录；列表按 created_at 新到旧排序。",
                },
            ],
            "recommended_flows": {
                "thin_governed_loop_input_draft": {
                    "tool": "run_mcp_workflow",
                    "draft_arguments": {
                        "workflow": "thin_governed_loop_preview",
                        "phase": "preview",
                        "project_name": "<registered project_name>",
                        "input_mode": "draft",
                        "draft_seed": {
                            "goal": "<natural-language objective>",
                            "task_tier": "M0-M2",
                            "allowed_files": ["<project-relative path>"],
                            "context_files": ["<optional context path>"],
                            "validation_commands": ["<validation command>"],
                            "review_decision_value": "NEEDS_FIX",
                            "reviewer_notes": "<optional reviewer note>",
                        },
                    },
                    "next_step": (
                        "For M0-M2 low-risk tasks, require result.codex_execution_packet.packet_status=ready, "
                        "then copy result.codex_execution_packet.copy_paste_codex_prompt to local Codex. "
                        "Use result.next_request_payload only when formal evidence preview is needed."
                    ),
                    "direct_codex_packet_field": "result.codex_execution_packet",
                    "provided_arguments": {
                        "workflow": "thin_governed_loop_preview",
                        "phase": "preview",
                        "project_name": "<same registered project_name>",
                        "input_mode": "provided",
                        "thin_loop_inputs": "<generated_input_bundle>",
                    },
                    "authority": "read_only_evidence_not_execution_or_acceptance_authority",
                },
                "validation": {
                    "tool": "manage_validation_run",
                    "preview_arguments": {
                        "action": "preview",
                        "scope": "target_files",
                        "project_name": "<registered project_name>",
                        "target_files": ["<project-relative path>"],
                    },
                    "run_arguments": {
                        "action": "run",
                        "project_name": "<same registered project_name>",
                        "preview_id": "<preview_id from preview>",
                    },
                    "status_arguments": {
                        "action": "status",
                        "project_name": "<same registered project_name>",
                        "run_id": "<run_id from run>",
                    },
                },
            },
            "safety_boundary": {
                "does_not_authorize_stable_promotion": True,
                "does_not_authorize_executor_run": True,
                "does_not_authorize_commit_or_push": True,
                "does_not_create_review_decision": True,
                "does_not_emit_gate_event": True,
                "does_not_write_delivery_state": True,
                "requires_explicit_commander_authorization_for": [
                    "stable service replacement",
                    "push",
                    "executor run",
                    "route transition",
                    "release/deploy",
                ],
            },
            "web_gpt_handoff_prompt": (
                "Start by calling list_registered_projects, get_agent_consumer_contract, "
                "get_service_entry_profile with profile_id=web_gpt_commander, get_agent_operator_flow_packet, then "
                "get_web_gpt_service_entrypoint, render_commander_app, get_stable_promotion_readiness, and "
                "analyze_project_state with the selected project_name. "
                "For thin governed loop work, "
                "use run_mcp_workflow input_mode=draft, then for M0-M2 local work require "
                "result.codex_execution_packet.packet_status=ready before copying "
                "result.codex_execution_packet.copy_paste_codex_prompt to local Codex. "
                "Use result.next_request_payload only when formal evidence preview is needed. "
                "Treat all outputs as evidence unless Commander explicitly authorizes a write, run, "
                "push, or stable promotion."
            ),
            "visible_tool_names": visible_names,
        }

    def _tool_get_commander_app_manifest(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._commander_app_manifest(params)

    def _tool_get_product_readiness_status(self, params: dict[str, Any]) -> dict[str, Any]:
        project_root, project_record = self._resolve_read_only_project_context(params)
        project_name = (
            self._project_name_for_context(project_root, project_record, params)
            if params.get("project_name") is not None or project_record is not None
            else None
        )
        if project_name:
            return self._commander_app_dependency(
                "build_product_readiness_packet",
                build_product_readiness_packet,
            )(project_root, project_name=project_name)
        return self._commander_app_dependency(
            "build_product_readiness_packet",
            build_product_readiness_packet,
        )(project_root)

    def _tool_get_chatgpt_app_readiness(self, params: dict[str, Any]) -> dict[str, Any]:
        project_root, project_record = self._resolve_read_only_project_context(params)
        project_name = self._project_name_for_context(project_root, project_record, params)
        return self._commander_app_dependency(
            "build_chatgpt_connection_packet",
            build_chatgpt_connection_packet,
        )(project_root, project_name=project_name)

    def _tool_get_full_loop_authority_status(self, params: dict[str, Any]) -> dict[str, Any]:
        project_root, _ = self._resolve_read_only_project_context(params)
        return self._commander_app_dependency(
            "build_full_loop_authority_status",
            build_full_loop_authority_status,
        )(
            project_root,
            enable_full_loop=bool(params.get("enable_full_loop")),
            confirmation_mode=params.get("confirmation_mode") if isinstance(params.get("confirmation_mode"), str) else None,
            allow_executor_run=bool(params.get("allow_executor_run")),
            allow_validation_run=bool(params.get("allow_validation_run")),
            allow_local_commit=bool(params.get("allow_local_commit")),
            allow_remote_push=bool(params.get("allow_remote_push")),
            allow_stable_replacement=bool(params.get("allow_stable_replacement")),
            operator_confirmation_ref=(
                params.get("operator_confirmation_ref") if isinstance(params.get("operator_confirmation_ref"), str) else None
            ),
        )

    def _tool_get_product_console_map(self, params: dict[str, Any]) -> dict[str, Any]:
        project_root, project_record = self._resolve_read_only_project_context(params)
        project_name = self._project_name_for_context(project_root, project_record, params)
        readiness = self._commander_app_dependency(
            "build_product_readiness_packet",
            build_product_readiness_packet,
        )(project_root, project_name=project_name)
        safe_next_action = readiness.get("safe_next_action") if isinstance(readiness.get("safe_next_action"), dict) else {}
        stable_promotion = (
            self._build_stable_promotion_readiness_packet(project_root, project_name)
            if safe_next_action.get("tool") == "get_stable_promotion_readiness"
            else None
        )
        return self._commander_app_dependency(
            "build_product_console_map",
            build_product_console_map,
        )(
            project_root,
            project_name=project_name,
            readiness_packet=readiness,
            stable_promotion_readiness=stable_promotion,
        )

    def _tool_get_submission_evidence_fill_preview(self, params: dict[str, Any]) -> dict[str, Any]:
        project_root, project_record = self._resolve_read_only_project_context(params)
        project_name = self._project_name_for_context(project_root, project_record, params)
        selected_keys = params.get("selected_keys")
        return self._commander_app_dependency(
            "build_submission_evidence_fill_preview",
            build_submission_evidence_fill_preview,
        )(
            project_root,
            project_name=project_name,
            selected_keys=selected_keys if isinstance(selected_keys, list) else None,
        )

    def _tool_get_submission_evidence_auto_draft(self, params: dict[str, Any]) -> dict[str, Any]:
        project_root, project_record = self._resolve_read_only_project_context(params)
        project_name = self._project_name_for_context(project_root, project_record, params)
        selected_keys = self._selected_auto_submission_evidence_keys(params.get("selected_keys"))
        local_service = self._connector_runtime_local_service_evidence(project_root)
        runtime_status = self._runtime_version_status_for_project(project_root, local_service=local_service)
        connector_health = self._commander_app_dependency(
            "get_connector_runtime_health_status",
            get_connector_runtime_health_status,
        )(
            runtime_status=runtime_status,
            local_service=local_service,
        )
        visible_tool_defs = self._filter_tools_by_exposure_profile(self.tool_defs)
        tool_scope_map = {
            tool.name: self._submission_evidence_scope_label(tool.name)
            for tool in visible_tool_defs
        }
        context = {
            "project_name": project_name,
            "project_root": project_root,
            "runtime_status": runtime_status,
            "connector_health": connector_health,
            "visible_tool_defs": visible_tool_defs,
            "tool_scope_map": tool_scope_map,
            "mcp_exposure_profile": self.mcp_exposure_profile,
            "service_mode": self.service_mode,
        }
        entries = [
            self._submission_evidence_auto_entry(key, context)
            for key in selected_keys
        ]
        entries = [entry for entry in entries if isinstance(entry, dict)]
        return {
            "ok": True,
            "source": "submission_evidence_auto_draft",
            "schema_version": "submission_evidence_auto_draft.v1",
            "read_only": True,
            "side_effects": False,
            "project_root": project_root,
            "project_name": project_name,
            "status": "draft_ready" if entries else "no_supported_keys",
            "selected_keys": selected_keys,
            "generated_keys": [entry["key"] for entry in entries],
            "unsupported_keys": [],
            "draft_entries": entries,
            "copyable_tool_call": {
                "tool": "fill_submission_evidence_files",
                "arguments": {
                    "project_name": project_name,
                    "entries": [entry["copyable_entry_shape"] for entry in entries],
                    "mark_ready": False,
                },
                "required_scope": "mcp:commit",
                "requires_explicit_operator_review": True,
            },
            "operator_instructions": [
                "Review and edit every generated evidence draft before writing files.",
                "Keep mark_ready=false until a human reviewer confirms the evidence is final.",
                "Run get_release_submission_readiness after filling files.",
            ],
            "authority_boundary": {
                "read_only": True,
                "side_effects": False,
                "does_not_write_files": True,
                "does_not_mark_ready_fields": True,
                "does_not_create_openai_app_draft": True,
                "does_not_submit_app_for_review": True,
                "does_not_publish_app": True,
                "does_not_read_tokens_or_cookies": True,
                "does_not_read_raw_logs": True,
            },
        }

    def _tool_manage_submission_evidence_revision(self, params: dict[str, Any]) -> dict[str, Any]:
        if params.get("project_name") is not None:
            return self._route_project_name_tool(
                "manage_submission_evidence_revision",
                params,
                require_managed=True,
            )
        action = str(params.get("action") or "").strip()
        result = self._commander_app_dependency(
            "MCPSubmissionEvidenceRevisionManager",
            MCPSubmissionEvidenceRevisionManager,
        )(self.project_root).handle(action, params)
        self._record_workflow_if_needed("manage_submission_evidence_revision", action, params, result)
        return result

    def _tool_manage_p1_release_evidence(self, params: dict[str, Any]) -> dict[str, Any]:
        """Persist only a preview-bound local P1 evidence receipt.

        This route intentionally remains normal/loopback-only through the
        catalog profile filter.  It has no stable-replacement operation.
        """
        if params.get("project_name") is not None:
            return self._route_project_name_tool(
                "manage_p1_release_evidence",
                params,
                require_managed=True,
            )
        action = str(params.get("action") or "").strip()
        result = self._commander_app_dependency(
            "P1ReleaseEvidenceManager",
            P1ReleaseEvidenceManager,
        )(self.project_root).handle(action, params)
        self._record_workflow_if_needed("manage_p1_release_evidence", action, params, result)
        return result

    def _selected_auto_submission_evidence_keys(self, raw_selected: Any) -> list[str]:
        supported = ["mcp_tool_info", "security_review", "metadata_snapshot"]
        if not isinstance(raw_selected, list):
            return supported
        selected = [
            str(item).strip()
            for item in raw_selected
            if isinstance(item, str) and str(item).strip() in supported
        ]
        return selected or supported

    def _submission_evidence_auto_entry(self, key: str, context: dict[str, Any]) -> dict[str, Any] | None:
        filename_by_key = {
            "mcp_tool_info": "mcp-tool-info.md",
            "security_review": "security-review.md",
            "metadata_snapshot": "metadata-snapshot.md",
        }
        content_builders = {
            "mcp_tool_info": self._auto_mcp_tool_info_evidence,
            "security_review": self._auto_security_review_evidence,
            "metadata_snapshot": self._auto_metadata_snapshot_evidence,
        }
        builder = content_builders.get(key)
        if builder is None:
            return None
        filename = filename_by_key[key]
        content = builder(context)
        return {
            "key": key,
            "filename": filename,
            "content_length": len(content),
            "copyable_entry_shape": {
                "key": key,
                "filename": filename,
                "content": content,
            },
        }

    @staticmethod
    def _submission_evidence_value(value: Any) -> str:
        if value is True:
            return "true"
        if value is False:
            return "false"
        if value is None:
            return "unknown"
        return str(value)

    def _tool_init_submission_evidence(self, params: dict[str, Any]) -> dict[str, Any]:
        if params.get("project_name") is not None:
            return self._route_project_name_tool("init_submission_evidence", params, require_managed=True)
        result = self._commander_app_dependency(
            "init_submission_evidence_scaffold",
            init_submission_evidence_scaffold,
        )(
            self.project_root,
            app_name=str(params.get("app_name") or "ColaMeta"),
            app_description=str(params.get("app_description") or "Project console for local AI engineering workflows."),
            company_url=str(params.get("company_url") or "https://example.com"),
            privacy_policy_url=str(params.get("privacy_policy_url") or "https://example.com/privacy"),
        )
        self._record_workflow_if_needed("init_submission_evidence", "apply", params, result)
        return result

    def _tool_fill_submission_evidence_files(self, params: dict[str, Any]) -> dict[str, Any]:
        if params.get("project_name") is not None:
            return self._route_project_name_tool("fill_submission_evidence_files", params, require_managed=True)
        entries = params.get("entries")
        result = self._commander_app_dependency(
            "fill_submission_evidence_files",
            fill_submission_evidence_files,
        )(
            self.project_root,
            entries=entries if isinstance(entries, list) else [],
            mark_ready=bool(params.get("mark_ready")),
        )
        self._record_workflow_if_needed("fill_submission_evidence_files", "apply", params, result)
        return result

    def _tool_mark_submission_evidence_ready_fields(self, params: dict[str, Any]) -> dict[str, Any]:
        if params.get("project_name") is not None:
            return self._route_project_name_tool("mark_submission_evidence_ready_fields", params, require_managed=True)
        keys = params.get("keys")
        result = self._commander_app_dependency(
            "mark_submission_evidence_ready_fields",
            mark_submission_evidence_ready_fields,
        )(
            self.project_root,
            keys=keys if isinstance(keys, list) else [],
            review_confirmation=str(params.get("review_confirmation") or ""),
        )
        self._record_workflow_if_needed("mark_submission_evidence_ready_fields", "apply", params, result)
        return result

    def _tool_render_commander_app(self, params: dict[str, Any]) -> dict[str, Any]:
        manifest = self._commander_app_manifest(params)
        manifest["_meta"] = {
            "ui": {
                "resourceUri": COMMANDER_APP_WIDGET_URI,
                "visibility": ["model", "app"],
            },
            "openai/outputTemplate": COMMANDER_APP_WIDGET_URI,
            "commander_app": {
                "manifest_version": COMMANDER_APP_MANIFEST_VERSION,
                "widget_resource_uri": COMMANDER_APP_WIDGET_URI,
                "project_name": manifest.get("project_name"),
                "profile_id": (
                    manifest.get("agent_operator_flow_profile", {}).get("profile_id")
                    if isinstance(manifest.get("agent_operator_flow_profile"), dict)
                    else None
                ),
            },
        }
        return manifest

    def _tool_get_apps_connector_smoke_packet(self, params: dict[str, Any]) -> dict[str, Any]:
        project_root, project_record = self._resolve_read_only_project_context(params)
        tunnel_client = self._connector_external_evidence_param(params, "tunnel_client")
        control_plane = self._connector_external_evidence_param(params, "control_plane")
        local_service = self._connector_runtime_local_service_evidence(project_root)
        runtime_status = self._runtime_version_status_for_project(project_root, local_service=local_service)
        connector_health = self._commander_app_dependency(
            "get_connector_runtime_health_status",
            get_connector_runtime_health_status,
        )(
            runtime_status=runtime_status,
            local_service=local_service,
            tunnel_client=tunnel_client,
            control_plane=control_plane,
        )
        project_name = self._project_name_for_context(project_root, project_record, params)
        apps_connector_closeout = self._commander_app_dependency(
            "build_apps_connector_closeout_packet",
            build_apps_connector_closeout_packet,
        )(
            project_name=project_name,
            connector_health=connector_health,
        )
        release_submission_evidence = self._apps_connector_release_submission_evidence(
            project_root=project_root,
            project_name=project_name,
            connector_health=connector_health,
            apps_connector_closeout=apps_connector_closeout,
        )
        apps_connector_closeout = {
            **apps_connector_closeout,
            "release_submission_evidence": release_submission_evidence,
        }
        return {
            "ok": True,
            "source": "apps_connector_smoke_packet",
            "scope": "mcp:read",
            "read_only": True,
            "side_effects": False,
            "project_name": project_name,
            "apps_connector_closeout": apps_connector_closeout,
            "release_submission_evidence": release_submission_evidence,
            "connector_runtime_health": connector_health,
            "runtime": {
                "project_checkout_head": runtime_status.get("project_checkout_head"),
                "loaded_runtime_head": runtime_status.get("loaded_runtime_head"),
                "runtime_loaded_code_stale": runtime_status.get("runtime_loaded_code_stale"),
                "reload_needed_for_verification": runtime_status.get("reload_needed_for_verification"),
                "reload_awareness_reason": runtime_status.get("reload_awareness_reason"),
            },
            "stable_replacement_hint": self._stable_replacement_hint(project_root, runtime_status),
            "operator_sequence": [
                apps_connector_closeout["project_list_check"],
                apps_connector_closeout["preferred_smoke_tool"],
                apps_connector_closeout["connector_closeout_check"],
            ],
            "token_expired_recovery": apps_connector_closeout["token_expired_recovery"],
            "metadata_refresh_guidance": apps_connector_closeout["metadata_refresh_guidance"],
            "authority_boundary": {
                "read_only": True,
                "does_not_read_tokens_or_cookies": True,
                "does_not_read_browser_login_state": True,
                "does_not_read_tunnel_client_config": True,
                "does_not_read_raw_logs": True,
                "does_not_restart_tunnel_client": True,
                "does_not_modify_proxy_or_auth_config": True,
                "does_not_authorize_executor_run": True,
                "does_not_authorize_commit_or_push": True,
                "does_not_authorize_stable_replacement": True,
            },
        }

    def _commander_app_manifest(self, params: dict[str, Any]) -> dict[str, Any]:
        project_root, project_record = self._resolve_read_only_project_context(params)
        continuation_provider = str(params.get("provider") or "codex").strip().lower()
        if continuation_provider not in {"pi", "codex", "opencode"}:
            continuation_provider = "codex"
        continuation_snapshot = self._collect_continuation_snapshot_for_project(
            project_root,
            continuation_provider,
        )
        continuation_projection = continuation_snapshot.project(continuation_provider)
        tunnel_client = self._connector_external_evidence_param(params, "tunnel_client")
        control_plane = self._connector_external_evidence_param(params, "control_plane")
        local_service = self._connector_runtime_local_service_evidence(project_root)
        runtime_status = self._runtime_version_status_for_project(project_root, local_service=local_service)
        connector_health = self._commander_app_dependency(
            "get_connector_runtime_health_status",
            get_connector_runtime_health_status,
        )(
            runtime_status=runtime_status,
            local_service=local_service,
            tunnel_client=tunnel_client,
            control_plane=control_plane,
        )
        connector_summary = copy.deepcopy(connector_health)
        local_service_summary = connector_summary.get("local_service")
        external_connector_summary = connector_summary.get("external_connector")
        operator_closeout = connector_summary.get("operator_closeout")
        if isinstance(local_service_summary, dict):
            connector_summary["local_service_status"] = local_service_summary.get("status")
        if isinstance(external_connector_summary, dict):
            connector_summary["external_connector_status"] = external_connector_summary.get("status")
        if isinstance(operator_closeout, dict):
            connector_summary["operator_closeout_status"] = operator_closeout.get("status")

        project_identity = self._project_identity_for_root(project_root)
        if isinstance(project_record, dict):
            project_identity["project"] = project_record
        project_name = self._project_name_for_context(project_root, project_record, params)

        project_args = {"project_name": project_name}
        flow_profile_id, flow_profile, profiles = self._select_service_entry_profile(params)
        visible_names = self._visible_tool_names()
        readiness = self._commander_app_dependency(
            "build_service_readiness_summary",
            build_service_readiness_summary,
        )(
            runtime_status=runtime_status,
            connector_health=connector_health,
            project_name=project_name,
        )
        apps_connector_closeout = self._commander_app_dependency(
            "build_apps_connector_closeout_packet",
            build_apps_connector_closeout_packet,
        )(
            project_name=project_name,
            connector_health=connector_health,
        )
        release_submission_evidence = self._apps_connector_release_submission_evidence(
            project_root=project_root,
            project_name=project_name,
            connector_health=connector_health,
            apps_connector_closeout=apps_connector_closeout,
            compact_progress=True,
        )
        apps_connector_closeout = {
            **apps_connector_closeout,
            "release_submission_evidence": release_submission_evidence,
        }
        domain_projections = self._commander_app_dependency(
            "CommanderProjectionService",
            CommanderProjectionService,
        )(
            project_root,
            service_operations_reader=lambda: {
                "source": "connector_runtime_health_projection",
                "overall_status": connector_summary.get("overall_status"),
                "local_service_status": connector_summary.get("local_service_status"),
                "external_connector_status": connector_summary.get("external_connector_status"),
                "operator_closeout_status": connector_summary.get("operator_closeout_status"),
            },
            app_submission_reader=lambda: {
                "source": release_submission_evidence.get("source"),
                "status": release_submission_evidence.get("status"),
                "ready": release_submission_evidence.get("ready") is True,
                "blocker_codes": copy.deepcopy(release_submission_evidence.get("blocker_codes") or []),
                "needs_attention_codes": copy.deepcopy(
                    release_submission_evidence.get("needs_attention_codes") or []
                ),
                "safe_next_action": copy.deepcopy(release_submission_evidence.get("safe_next_action")),
            },
        ).project()["sections"]
        canonical_continuation_decision = continuation_projection[
            "canonical_continuation_decision"
        ]
        app_status = str(connector_summary.get("overall_status") or "unknown")
        readiness_status = str(readiness.get("status") or app_status)
        runtime_label = "runtime_current" if runtime_status.get("reload_needed_for_verification") is False else "runtime_needs_verification"
        runtime_summary = {
            "project_checkout_head": runtime_status.get("project_checkout_head"),
            "loaded_runtime_head": runtime_status.get("loaded_runtime_head"),
            "runtime_loaded_code_stale": runtime_status.get("runtime_loaded_code_stale"),
            "reload_needed_for_verification": runtime_status.get("reload_needed_for_verification"),
            "reload_awareness_reason": runtime_status.get("reload_awareness_reason"),
            "restart_needed_state": runtime_status.get("restart_needed_state"),
            "restart_needed_reason": runtime_status.get("restart_needed_reason"),
            "details_tool": "get_runtime_version_status",
            "details_arguments": project_args,
        }
        flow_args = {
            "profile_id": flow_profile_id,
            "include_advanced_context": False,
        }
        if self.service_mode or params.get("project_name") is not None:
            flow_args.update(project_args)
        if tunnel_client is not None:
            flow_args["tunnel_client"] = tunnel_client
        if control_plane is not None:
            flow_args["control_plane"] = control_plane
        agent_operator_flow = self._tool_get_agent_operator_flow_packet(
            flow_args,
            embedded_in_commander_manifest=True,
        )
        flow_profile_summary = {
            "profile_id": flow_profile_id,
            "display_name": flow_profile.get("display_name"),
            "consumer_kind": flow_profile.get("consumer_kind"),
            "default_authority": flow_profile.get("default_authority"),
            "write_boundary": flow_profile.get("write_boundary"),
        }
        return {
            "ok": True,
            "read_only": True,
            "side_effects": False,
            "app_manifest_version": COMMANDER_APP_MANIFEST_VERSION,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "project_name": project_name,
            "app": {
                "name": COMMANDER_APP_TITLE,
                "status_line": f"{readiness_status} | {runtime_label}",
                "archetype": "interactive-decoupled",
                "widget_resource_uri": COMMANDER_APP_WIDGET_URI,
                "widget_mime_type": COMMANDER_APP_WIDGET_MIME_TYPE,
                "data_tool": "get_commander_app_manifest",
                "render_tool": "render_commander_app",
                "resource_methods": ["resources/list", "resources/read"],
                "embedded_flow_profile_id": flow_profile_id,
            },
            "service_profile": {
                "service_name": "ColaMeta MCP",
                "mode": "service" if self.service_mode else "project",
                "mcp_exposure_profile": self.mcp_exposure_profile,
                "project_name_required_for_project_tools": bool(self.service_mode),
                "project_hint": self.project_hint,
                "visible_tool_count": len(visible_names),
            },
            "project_identity": project_identity,
            "readiness": readiness,
            "agent_operator_flow_profile": flow_profile_summary,
            "agent_operator_flow": agent_operator_flow,
            "apps_connector_closeout": apps_connector_closeout,
            "runtime": runtime_summary,
            "connector": connector_summary,
            "canonical_continuation_decision": canonical_continuation_decision,
            "continuation_snapshot": continuation_snapshot.public_view(
                continuation_provider
            ),
            "domain_projections": domain_projections,
            "registered_projects": self._web_gpt_registered_project_summary(),
            "profiles": profiles,
            "initial_reads": [
                {"tool": "list_registered_projects", "arguments": {}},
                {"tool": "get_agent_consumer_contract", "arguments": {}},
                {"tool": "get_service_entry_profile", "arguments": {"profile_id": flow_profile_id}},
                {"tool": "get_agent_operator_flow_packet", "arguments": {**project_args, "profile_id": flow_profile_id}},
                {"tool": "render_commander_app", "arguments": {**project_args, "profile_id": flow_profile_id}},
                {"tool": "get_stable_replacement_cadence", "arguments": project_args},
                {"tool": "get_stage_parallel_plan_preview", "arguments": project_args},
                {"tool": "get_stage_parallel_run_preview", "arguments": project_args},
                {"tool": "get_stage_parallel_worktree_assignment_preview", "arguments": project_args},
                {"tool": "get_stage_parallel_next_action_packet", "arguments": project_args},
                {"tool": "manage_stage_parallel_shard_inputs", "arguments": {**project_args, "action": "preview"}},
                {"tool": "get_stage_parallel_executor_group_preview", "arguments": project_args},
                {"tool": "manage_stage_parallel_executor_runs", "arguments": {**project_args, "action": "preview"}},
                {"tool": "get_stage_parallel_executor_results_packet", "arguments": project_args},
                {"tool": "get_stage_parallel_group_status", "arguments": project_args},
                {"tool": "get_stage_parallel_merge_preview", "arguments": project_args},
                {"tool": "manage_stage_parallel_merges", "arguments": {**project_args, "action": "preview"}},
                {"tool": "get_stage_parallel_closeout_packet", "arguments": project_args},
                {"tool": "get_apps_connector_smoke_packet", "arguments": project_args},
                {"tool": "get_submission_evidence_auto_draft", "arguments": project_args},
                {"tool": "get_submission_evidence_fill_preview", "arguments": project_args},
                {"tool": "get_connector_runtime_health_status", "arguments": project_args},
                {"tool": "analyze_project_state", "arguments": project_args},
            ],
            "commander_panel": {
                "primary_sections": [
                    "agent_operator_flow",
                    "work_item_governance",
                    "service_readiness",
                    "apps_connector_closeout",
                    "release_submission_evidence",
                    "service_facts",
                    "runtime_freshness",
                    "connector_health",
                    "profile_aware_entries",
                    "preview_first_workflows",
                    "authorization_gates",
                ],
                "read_actions": [
                    {"tool": "get_commander_app_manifest", "arguments": {**project_args, "profile_id": flow_profile_id}},
                    {"tool": "get_agent_operator_flow_packet", "arguments": {**project_args, "profile_id": flow_profile_id}},
                    {"tool": "get_product_console_map", "arguments": project_args},
                    {"tool": "get_release_submission_readiness", "arguments": project_args},
                    {"tool": "get_submission_evidence_auto_draft", "arguments": project_args},
                    {"tool": "get_submission_evidence_fill_preview", "arguments": project_args},
                    {"tool": "get_apps_connector_smoke_packet", "arguments": project_args},
                    {"tool": "get_stable_replacement_cadence", "arguments": project_args},
                    {"tool": "get_stage_parallel_plan_preview", "arguments": project_args},
                    {"tool": "get_stage_parallel_run_preview", "arguments": project_args},
                    {"tool": "get_stage_parallel_worktree_assignment_preview", "arguments": project_args},
                    {"tool": "get_stage_parallel_next_action_packet", "arguments": project_args},
                    {"tool": "manage_stage_parallel_shard_inputs", "arguments": {**project_args, "action": "preview"}},
                    {"tool": "get_stage_parallel_executor_group_preview", "arguments": project_args},
                    {"tool": "manage_stage_parallel_executor_runs", "arguments": {**project_args, "action": "preview"}},
                    {"tool": "get_stage_parallel_executor_results_packet", "arguments": project_args},
                    {"tool": "get_stage_parallel_group_status", "arguments": project_args},
                    {"tool": "get_stage_parallel_merge_preview", "arguments": project_args},
                    {"tool": "manage_stage_parallel_merges", "arguments": {**project_args, "action": "preview"}},
                    {"tool": "get_stage_parallel_closeout_packet", "arguments": project_args},
                    {"tool": "get_runtime_version_status", "arguments": project_args},
                    {"tool": "get_connector_runtime_health_status", "arguments": project_args},
                    apps_connector_closeout["connector_closeout_check"],
                    {"tool": "analyze_project_state", "arguments": project_args},
                ],
                "preview_first_actions": [
                    {
                        "tool": "run_mcp_workflow",
                        "arguments": {
                            **project_args,
                            "workflow": "thin_governed_loop_preview",
                            "phase": "preview",
                            "input_mode": "draft",
                        },
                    },
                    {
                        "tool": "manage_validation_run",
                        "arguments": {
                            **project_args,
                            "action": "preview",
                            "scope": "target_files",
                        },
                    },
                    {
                        "tool": "manage_stage_parallel_worktrees",
                        "arguments": {
                            **project_args,
                            "action": "preview",
                            "stage_id": "stage_parallel_automation",
                        },
                    },
                    {
                        "tool": "manage_stage_parallel_executor_group",
                        "arguments": {
                            **project_args,
                            "action": "preview",
                            "stage_id": "stage_parallel_automation",
                        },
                    },
                    {
                        "tool": "manage_stage_parallel_executor_runs",
                        "arguments": {
                            **project_args,
                            "action": "preview",
                            "stage_id": "stage_parallel_automation",
                        },
                    },
                    {
                        "tool": "manage_stage_parallel_merges",
                        "arguments": {
                            **project_args,
                            "action": "preview",
                            "stage_id": "stage_parallel_automation",
                        },
                    },
                    {
                        "tool": "manage_executor_workflow",
                        "arguments": {
                            **project_args,
                            "action": "run_once_preview",
                            "provider": "codex",
                            "profile_id": "local_codex_commander",
                        },
                    },
                ],
            },
            "preview_first_workflows": {
                "thin_governed_loop": (
                    "draft -> local Codex codex_execution_packet for M0-M2; "
                    "provided next_request_payload only for formal evidence preview"
                ),
                "validation": "preview -> explicit authorization -> run -> status",
                "executor": "run_once_preview -> explicit authorization -> run_once -> status -> get_executor_run_report",
                "gate_review_request": "inspect -> preview -> explicit authorization -> apply -> status; apply reuses the signed Work Item Gate preview",
            },
            "authority_boundary": {
                "read_only_tools_do_not_authorize_executor_dispatch": True,
                "read_only_tools_do_not_create_review_decision": True,
                "read_only_tools_do_not_emit_gate_event": True,
                "read_only_tools_do_not_write_delivery_state": True,
                "does_not_authorize_stable_promotion": True,
                "does_not_authorize_executor_run": True,
                "does_not_authorize_commit_or_push": True,
                "requires_explicit_commander_authorization_for": [
                    "executor run",
                    "commit",
                    "push",
                    "stable service replacement",
                    "ReviewDecision",
                    "GateEvent",
                    "Delivery accepted",
                ],
            },
            "connector_recovery": {
                "healthy_path": [
                    "call list_registered_projects",
                    "call render_commander_app with project_name and profile_id",
                    "provide sanitized tunnel_client/control_plane evidence when available",
                    "if Apps connector returns token_expired, reconnect the Apps connector session",
                ],
                "apps_connector_closeout": self._apps_connector_recovery_closeout_summary(apps_connector_closeout),
                "accepted_external_evidence_fields": ["status", "reason_code", "evidence_source", "last_observed_at"],
                "forbidden_evidence": ["token", "cookie", "credential", "raw_log", "provider_raw_response", "browser_login_state"],
            },
            "docs_alignment": {
                "tools": "one-job read tools plus a render tool",
                "ui": "MCP Apps bridge iframe resource",
                "resource_uri": COMMANDER_APP_WIDGET_URI,
            },
            "visible_tool_names": visible_names,
        }

    def _web_gpt_registered_project_summary(self) -> list[dict[str, Any]]:
        try:
            projects = self.project_registry.list_projects().get("projects", [])
        except Exception:
            projects = []
        summary: list[dict[str, Any]] = []
        if not isinstance(projects, list):
            return summary
        for project in projects:
            if not isinstance(project, dict):
                continue
            name = project.get("project_name")
            root = project.get("project_root") or project.get("path")
            if not isinstance(name, str) or not name.strip():
                continue
            item = {
                "project_name": name.strip(),
                "project_root": root if isinstance(root, str) else "",
                "project_mode": project.get("project_mode"),
                "runner_managed": bool(project.get("runner_managed")),
                "last_selected": bool(project.get("last_selected")),
            }
            summary.append(item)
        return summary[:20]

    def _apps_connector_release_submission_evidence(
        self,
        *,
        project_root: str,
        project_name: str,
        connector_health: dict[str, Any],
        apps_connector_closeout: dict[str, Any],
        compact_progress: bool = False,
    ) -> dict[str, Any]:
        connector_ready = apps_connector_closeout.get("status") == "ready"
        overall_status = str(connector_health.get("overall_status") or "unknown")
        ready = connector_ready and overall_status == "healthy"
        readiness_packet: dict[str, Any] = {
            "ready": ready,
            "status": "ready" if ready else "needs_attention",
            "public_base_url": None,
            "connector_url": None,
            "primary_blocker": None
            if ready
            else {
                "component": "apps_connector_closeout",
                "reason_code": "APPS_CONNECTOR_CLOSEOUT_NOT_READY",
                "status": apps_connector_closeout.get("status"),
                "overall_status": overall_status,
            },
            "ops_check": {
                "ops_check_ready": ready,
                "connector_smoke_ready": connector_ready,
                "beta_gate_ready": ready,
            },
        }
        release_submission = self._commander_app_dependency(
            "build_release_submission_readiness",
            build_release_submission_readiness,
        )(
            project_root,
            project_name=project_name,
            readiness_packet=readiness_packet,
        )
        evidence_progress = release_submission.get("submission_evidence_progress")
        if compact_progress:
            evidence_progress = self._compact_submission_evidence_progress(evidence_progress)
        submission_activity = self._commander_app_dependency(
            "build_submission_evidence_activity_result",
            build_submission_evidence_activity_result,
        )(project_root)
        return {
            "ok": True,
            "source": "release_submission_evidence_closeout",
            "schema_version": "release_submission_evidence_closeout.v1",
            "tool": "get_release_submission_readiness",
            "arguments": {"project_name": project_name},
            "read_only": True,
            "side_effects": False,
            "status": release_submission.get("status"),
            "ready": release_submission.get("ready") is True,
            "evidence_progress": evidence_progress,
            "submission_evidence_activity": submission_activity,
            "safe_next_action": release_submission.get("safe_next_action"),
            "blocker_codes": release_submission.get("blocker_codes") or [],
            "needs_attention_codes": release_submission.get("needs_attention_codes") or [],
            "authority_boundary": {
                "read_only": True,
                "does_not_submit_app_for_review": True,
                "does_not_publish_app": True,
                "does_not_call_openai_dashboard_or_api": True,
                "does_not_read_tokens_or_cookies": True,
                "does_not_authorize_executor_run": True,
                "does_not_authorize_commit_or_push": True,
                "does_not_authorize_stable_replacement": True,
            },
        }

    def _apps_connector_recovery_closeout_summary(self, apps_connector_closeout: dict[str, Any]) -> dict[str, Any]:
        recovery_summary = dict(apps_connector_closeout)
        recovery_summary.pop("release_submission_evidence", None)
        return recovery_summary

    def _compact_submission_evidence_progress(self, progress: Any) -> dict[str, Any] | None:
        if not isinstance(progress, dict):
            return None
        rows = progress.get("rows")
        compact_rows: list[dict[str, Any]] = []
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                next_action = row.get("next_action") if isinstance(row.get("next_action"), dict) else {}
                compact_next_action = {
                    key: next_action.get(key)
                    for key in ("action", "tool", "mark_ready")
                    if next_action.get(key) not in (None, "")
                }
                compact_rows.append(
                    {
                        "key": row.get("key"),
                        "ready_field": row.get("ready_field"),
                        "ready": row.get("ready") is True,
                        "status": row.get("status"),
                        "refs": row.get("refs") if isinstance(row.get("refs"), list) else [],
                        "default_path": row.get("default_path"),
                        "next_action": compact_next_action or None,
                    }
                )
        return {
            "source": progress.get("source"),
            "schema_version": progress.get("schema_version"),
            "status": progress.get("status"),
            "complete_count": progress.get("complete_count"),
            "total_count": progress.get("total_count"),
            "counts": progress.get("counts") if isinstance(progress.get("counts"), dict) else {},
            "rows": compact_rows,
            "manifest_available": progress.get("manifest_available"),
            "read_only": progress.get("read_only") is True,
            "side_effects": progress.get("side_effects") is True,
            "compact": True,
        }
