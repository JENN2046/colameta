"""Declarative MCP tool catalog kept outside the transport composition root."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from runner.mcp_gate_review_workflow import (
    GATE_REVIEW_MAX_BINDING_ID_CHARS,
    GATE_REVIEW_MAX_BINDING_IDS_PER_FIELD,
)
from runner.project_context_binding import OPERATION_CONTEXT_BINDING_FIELDS
from runner.review_manifest import (
    REVIEW_MANIFEST_SCHEMA_VERSION,
    REVIEW_MANIFEST_WORKFLOW_INTENT,
)

def _operation_context_binding_input_schema() -> dict[str, Any]:
    """Return the exact caller-owned context contract for confirmation calls."""

    return {
        "type": "object",
        "description": (
            "确认性操作必填。原样回传同一 workflow 的 inspect/preview 返回的 "
            "context_binding；服务会在副作用前重新核对项目、分支、HEAD、Runner plan、"
            "current_version、review_unit 与 workflow_intent。"
        ),
        "properties": {
            "project_name": {"type": "string", "minLength": 1, "maxLength": 128},
            "branch": {"type": "string", "minLength": 1, "maxLength": 255},
            "head": {"type": "string", "pattern": "^[0-9a-fA-F]{40,128}$"},
            "runner_plan": {
                "type": "object",
                "properties": {
                    "mode": {"type": "string", "enum": ["managed", "source-only"]},
                    "plan_sha256": {"type": ["string", "null"], "pattern": "^[0-9a-fA-F]{64}$"},
                },
                "required": ["mode", "plan_sha256"],
                "additionalProperties": False,
            },
            "current_version": {"type": ["string", "null"], "maxLength": 128},
            "review_unit": {"type": "string", "minLength": 1, "maxLength": 160},
            "workflow_intent": {"type": "string", "minLength": 1, "maxLength": 160},
        },
        "required": list(OPERATION_CONTEXT_BINDING_FIELDS),
        "additionalProperties": False,
    }


def _stage_7_9_context_input_schema() -> dict[str, Any]:
    """Return the exact read-journey context without implying a write gate."""

    schema = _operation_context_binding_input_schema()
    schema["description"] = (
        "stage_7_9_preview 的 preview 必填。原样回传该 workflow inspect 返回的 "
        "stage_7_9_context；服务会重新核对 project、branch、HEAD、Runner plan、"
        "current_version 与固定 Stage 7--9 journey identity。它是只读 handoff 绑定，"
        "不授权任何 apply、run、commit 或执行器。"
    )
    return schema

def _stage_parallel_preview_input_schema(*, include_executor_results: bool = False) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "project_name": {
            "type": "string",
            "description": "可选。按已登记 project_name 路由读取目标项目；服务模式下必须显式提供。",
        },
        "stage_id": {
            "type": "string",
            "description": "可选。要规划的阶段 ID；不传时使用 stage_parallel_automation。",
        },
        "provider": {
            "type": "string",
            "enum": ["codex", "opencode", "pi"],
            "description": "可选。未来 executor preview 的 provider 偏好。默认 codex。",
        },
        "base_branch": {
            "type": "string",
            "description": "可选。未来隔离 worktree 的基准分支名。默认 main。",
        },
        "max_parallel_tasks": {
            "type": "integer",
            "minimum": 1,
            "maximum": 8,
            "description": "可选。最多纳入多少个候选 task shard。默认 3，最大 8。",
        },
        "task_intents": {
            "type": "array",
            "description": "可选。候选任务意图；只用于只读并行编排预览。",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "task_id": {"type": "string"},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "allowed_files": {"type": "array", "items": {"type": "string"}},
                    "surfaces": {"type": "array", "items": {"type": "string"}},
                    "risk_level": {
                        "type": "string",
                        "enum": ["none", "low", "moderate", "high", "blocked"],
                    },
                },
                "required": ["title"],
            },
        },
    }
    if include_executor_results:
        properties["executor_results"] = {
            "type": "array",
            "description": "可选。调用方提供的 sanitized executor result 摘要；不读取 raw logs。",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "task_id": {"type": "string"},
                    "status": {
                        "type": "string",
                        "enum": ["planned", "running", "succeeded", "failed", "blocked", "unknown"],
                    },
                    "validation_status": {
                        "type": "string",
                        "enum": ["not_run", "running", "passed", "failed", "blocked", "unknown"],
                    },
                    "head": {"type": "string"},
                    "changed_files": {"type": "array", "items": {"type": "string"}},
                    "summary": {"type": "string"},
                },
                "required": ["task_id", "status"],
            },
        }
    return {
        "type": "object",
        "properties": properties,
        "required": [],
        "additionalProperties": False,
    }

def _manage_stage_parallel_worktrees_input_schema() -> dict[str, Any]:
    schema = _stage_parallel_preview_input_schema()
    properties = dict(schema["properties"])
    properties["action"] = {
        "type": "string",
        "enum": ["preview", "apply", "status", "discard"],
        "description": "preview 生成受控 worktree apply preview；apply 用 preview_id 创建 worktree；status/discard 读取或废弃 preview。",
    }
    properties["preview_id"] = {
        "type": "string",
        "description": "apply/status/discard 必填。来自 preview 的 preview_id。",
    }
    properties["reason"] = {
        "type": "string",
        "description": "preview 可选。记录创建并行 worktree preview 的原因。",
    }
    return {
        "type": "object",
        "properties": properties,
        "required": ["action"],
        "additionalProperties": False,
    }

def _manage_stage_parallel_executor_group_input_schema() -> dict[str, Any]:
    schema = _stage_parallel_preview_input_schema()
    properties = dict(schema["properties"])
    properties["action"] = {
        "type": "string",
        "enum": ["preview", "apply", "status", "discard"],
        "description": "preview 校验已创建 worktree 并生成 group preview；apply 用 preview_id 批量创建 executor run_once_preview artifacts。",
    }
    properties["preview_id"] = {
        "type": "string",
        "description": "apply/status/discard 必填。来自 preview 的 preview_id。",
    }
    properties["reason"] = {
        "type": "string",
        "description": "preview 可选。记录创建 executor preview group 的原因。",
    }
    return {
        "type": "object",
        "properties": properties,
        "required": ["action"],
        "additionalProperties": False,
    }

def _manage_stage_parallel_shard_inputs_input_schema() -> dict[str, Any]:
    schema = _stage_parallel_preview_input_schema()
    properties = dict(schema["properties"])
    properties["action"] = {
        "type": "string",
        "enum": ["preview", "apply", "status", "discard"],
        "description": "preview 校验已创建 worktree 并生成 shard input preview；apply 用 preview_id 写入每个 shard 的 runtime plan/state/prompt overlay。",
    }
    properties["preview_id"] = {
        "type": "string",
        "description": "apply/status/discard 必填。来自 preview 的 preview_id。",
    }
    properties["reason"] = {
        "type": "string",
        "description": "preview 可选。记录写入 shard runner input 的原因。",
    }
    return {
        "type": "object",
        "properties": properties,
        "required": ["action"],
        "additionalProperties": False,
    }

def _manage_stage_parallel_executor_runs_input_schema() -> dict[str, Any]:
    schema = _stage_parallel_preview_input_schema()
    properties = dict(schema["properties"])
    properties["action"] = {
        "type": "string",
        "enum": ["preview", "apply", "status", "discard"],
        "description": "preview 校验已创建 executor preview artifacts 并生成 run group preview；apply 用 preview_id 启动隔离 worktree executor runs。",
    }
    properties["preview_id"] = {
        "type": "string",
        "description": "apply/status/discard 必填。来自 preview 的 preview_id。",
    }
    properties["reason"] = {
        "type": "string",
        "description": "preview 可选。记录启动并行 executor run group 的原因。",
    }
    return {
        "type": "object",
        "properties": properties,
        "required": ["action"],
        "additionalProperties": False,
    }

def _manage_stage_parallel_merges_input_schema() -> dict[str, Any]:
    schema = _stage_parallel_preview_input_schema(include_executor_results=True)
    properties = dict(schema["properties"])
    properties["action"] = {
        "type": "string",
        "enum": ["preview", "apply", "status", "discard"],
        "description": "preview 生成受控 stage parallel merge apply preview；apply 用 preview_id 顺序执行本地 git merge。",
    }
    properties["preview_id"] = {
        "type": "string",
        "description": "apply/status/discard 必填。来自 preview 的 preview_id。",
    }
    properties["reason"] = {
        "type": "string",
        "description": "preview 可选。记录执行并行 merge gate 的原因。",
    }
    return {
        "type": "object",
        "properties": properties,
        "required": ["action"],
        "additionalProperties": False,
    }

@dataclass
class MCPToolDef:
    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    title: str | None = None
    annotations: dict[str, Any] | None = None
    meta: dict[str, Any] | None = None

_CHATGPT_SUBMISSION_TOOL_ANNOTATIONS: dict[str, dict[str, bool]] = {
    **{
        name: {
            "readOnlyHint": True,
            "openWorldHint": False,
            "destructiveHint": False,
        }
        for name in (
            "list_registered_projects",
            "get_agent_consumer_contract",
            "get_service_entry_profile",
            "get_web_gpt_service_entrypoint",
            "get_stable_promotion_readiness",
            "get_runtime_version_status",
            "get_connector_runtime_health_status",
            "get_plan_standards_report",
            "get_runner_execution_standards",
            "manage_workflow_run",
            "list_executor_run_reports",
            "get_executor_run_report",
            "inspect_executor_activity",
            "analyze_project_state",
        )
    },
    "manage_git": {
        "readOnlyHint": False,
        "openWorldHint": True,
        "destructiveHint": True,
    },
    **{
        name: {
            "readOnlyHint": False,
            "openWorldHint": False,
            "destructiveHint": True,
        }
        for name in (
            "manage_runner_plan",
            "manage_project_memory",
            "manage_plan_version",
            "manage_project_docs",
            "manage_prompt_file",
            "manage_files",
            "run_mcp_workflow",
            "manage_executor_config",
            "manage_executor_workflow",
        )
    },
    "manage_validation_run": {
        "readOnlyHint": False,
        "openWorldHint": False,
        "destructiveHint": False,
    },
}

def apply_chatgpt_submission_tool_annotations(tool_defs: list[MCPToolDef]) -> None:
    for tool in tool_defs:
        explicit = _CHATGPT_SUBMISSION_TOOL_ANNOTATIONS.get(tool.name)
        if explicit is None:
            continue
        annotations = dict(tool.annotations or {})
        annotations.update(explicit)
        tool.annotations = annotations


def build_mcp_tool_definitions(
    owner: Any,
    common_output_schema: dict[str, Any],
    *,
    commander_widget_uri: str,
) -> list[MCPToolDef]:
    commander_app_input_schema = owner._commander_app_input_schema()
    full_loop_authority_input_schema = owner._full_loop_authority_input_schema()
    release_submission_input_schema = owner._release_submission_input_schema()
    submission_evidence_fill_preview_input_schema = owner._submission_evidence_fill_preview_input_schema()
    submission_evidence_auto_draft_input_schema = owner._submission_evidence_auto_draft_input_schema()
    submission_evidence_revision_input_schema = owner._submission_evidence_revision_input_schema()
    p1_release_evidence_input_schema = owner._p1_release_evidence_input_schema()
    init_submission_evidence_input_schema = owner._init_submission_evidence_input_schema()
    fill_submission_evidence_input_schema = owner._fill_submission_evidence_input_schema()
    mark_submission_evidence_ready_input_schema = owner._mark_submission_evidence_ready_input_schema()
    product_console_action_result_input_schema = owner._product_console_action_result_input_schema()

    return [
        MCPToolDef(
            name="list_registered_projects",
            description=f"[{owner.project_hint}] 列出本地 registry 中已登记项目。只接受本地 allowlist 项目，不解析任意 project_root。",
            input_schema={
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
            output_schema=common_output_schema,
        ),
        MCPToolDef(
            name="get_agent_consumer_contract",
            description=(
                f"[{owner.project_hint}] 读取 Agent 消费者契约。"
                "说明 MCP tool 成功/失败 envelope、project_name 路由规则、只读/副作用字段、packaged 大结果和权限边界。scope=mcp:read。"
            ),
            input_schema={
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
            output_schema=common_output_schema,
        ),
        MCPToolDef(
            name="get_service_entry_profile",
            description=(
                f"[{owner.project_hint}] 按 profile_id 读取服务入口画像。"
                "用于网页 GPT、本地 Codex、Reviewer、Planner、Source Observer 等 agent 选择自己的最小进入路径。scope=mcp:read。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "profile_id": {
                        "type": "string",
                        "description": "可选。为空时返回默认 web_gpt_commander 和可选 profile 列表。",
                    }
                },
                "required": [],
                "additionalProperties": False,
            },
            output_schema=common_output_schema,
        ),
        MCPToolDef(
            name="get_agent_operator_flow_packet",
            title="Get Agent Operator Flow Packet",
            description=(
                f"[{owner.project_hint}] 面向任意 agent profile 的只读操作流程 packet。"
                "按 profile_id、task_mode 和当前项目事实给出一个 primary_next_action、简短原因、gate level 和 advanced context。"
                "它不创建 preview artifact、不启动 executor、不 merge、不 commit、不 push、不替换 stable。scope=mcp:read。"
            ),
            input_schema=owner._agent_operator_flow_input_schema(),
            output_schema=common_output_schema,
            annotations={
                "readOnlyHint": True,
                "destructiveHint": False,
                "openWorldHint": False,
                "idempotentHint": True,
            },
        ),
        MCPToolDef(
            name="get_web_gpt_service_entrypoint",
            description=(
                f"[{owner.project_hint}] 网页端 GPT 使用 ColaMeta 服务的只读入口卡片。"
                "返回推荐首调用顺序、project_name 路由规则、薄治理闭环 draft/provided 用法、权限边界和稳定晋升注意事项。scope=mcp:read。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "project_name": {
                        "type": "string",
                        "description": "可选。若已知目标项目，可返回该项目的只读 identity 摘要；服务模式下仍不执行项目动作。",
                    }
                },
                "required": [],
                "additionalProperties": False,
            },
            output_schema=common_output_schema,
        ),
        MCPToolDef(
            name="get_commander_app_manifest",
            title="Get Commander App Manifest",
            description=(
                f"[{owner.project_hint}] ChatGPT Apps 侧 ColaMeta Commander App 的只读 manifest。"
                "汇总项目身份、runtime、connector health、profile-aware 入口、preview-first 工作流和授权闸门。"
                "只接受 sanitized tunnel/control-plane evidence；不读取 token、cookie、配置或 raw logs。scope=mcp:read。"
            ),
            input_schema=commander_app_input_schema,
            output_schema=common_output_schema,
            annotations={
                "readOnlyHint": True,
                "destructiveHint": False,
                "openWorldHint": False,
                "idempotentHint": True,
            },
        ),
        MCPToolDef(
            name="get_product_readiness_status",
            title="Get Product Readiness Status",
            description=(
                f"[{owner.project_hint}] ColaMeta 作为公开 Beta 产品入口的只读 readiness packet。"
                "聚合 ops-check、stable runtime、remote preflight、cloudflared 和 Apps connector smoke 状态，"
                "输出 primary_blocker 和 safe_next_action；不重启服务、不修改 DNS/tunnel、不授权 executor run、commit、push 或 stable replacement。scope=mcp:read。"
            ),
            input_schema=commander_app_input_schema,
            output_schema=common_output_schema,
            annotations={
                "readOnlyHint": True,
                "destructiveHint": False,
                "openWorldHint": False,
                "idempotentHint": True,
            },
        ),
        MCPToolDef(
            name="get_chatgpt_app_readiness",
            title="Get ChatGPT App Readiness",
            description=(
                f"[{owner.project_hint}] ChatGPT App 连接前的只读产品 readiness 和推荐工具顺序。"
                "返回 connector URL、recommended_sequence 和 readiness 摘要；只作为外部 connector closeout 证据，不授权写入或服务替换。scope=mcp:read。"
            ),
            input_schema=commander_app_input_schema,
            output_schema=common_output_schema,
            annotations={
                "readOnlyHint": True,
                "destructiveHint": False,
                "openWorldHint": False,
                "idempotentHint": True,
            },
        ),
        MCPToolDef(
            name="get_full_loop_authority_status",
            title="Get Full Loop Authority Status",
            description=(
                f"[{owner.project_hint}] Controlled Full Loop 的只读授权状态面。"
                "默认 disabled/read-preview-only；即使显式请求完整闭环，也只验证 preview-confirm、operator confirmation ref "
                "和 executor/validation/commit/push gate 是否齐备，不启动 executor、不跑验证、不 commit、不 push、不替换 stable。scope=mcp:read。"
            ),
            input_schema=full_loop_authority_input_schema,
            output_schema=common_output_schema,
            annotations={
                "readOnlyHint": True,
                "destructiveHint": False,
                "openWorldHint": False,
                "idempotentHint": True,
            },
        ),
        MCPToolDef(
            name="get_product_console_map",
            title="Get Product Console Map",
            description=(
                f"[{owner.project_hint}] ColaMeta 项目操作台的只读能力地图。"
                "返回连接/readiness、计划审查、Controlled Full Loop、stable/release 的入口、工具、scope、状态和推荐首动作；"
                "不启动 executor、不跑验证、不 commit、不 push、不替换 stable、不发布。scope=mcp:read。"
            ),
            input_schema=commander_app_input_schema,
            output_schema=common_output_schema,
            annotations={
                "readOnlyHint": True,
                "destructiveHint": False,
                "openWorldHint": False,
                "idempotentHint": True,
            },
        ),
        MCPToolDef(
            name="get_release_submission_readiness",
            title="Get Release Submission Readiness",
            description=(
                f"[{owner.project_hint}] ChatGPT App release/submission 的只读准备状态。"
                "检查 public MCP/readiness、Apps connector smoke、提交表单材料、测试证据、权限声明、隐私安全和 metadata snapshot；"
                "不创建 OpenAI app draft、不提交 review、不发布、不读取 token/cookie/provider config。scope=mcp:read。"
            ),
            input_schema=release_submission_input_schema,
            output_schema=common_output_schema,
            annotations={
                "readOnlyHint": True,
                "destructiveHint": False,
                "openWorldHint": False,
                "idempotentHint": True,
            },
        ),
        MCPToolDef(
            name="get_submission_evidence_fill_preview",
            title="Get Submission Evidence Fill Preview",
            description=(
                f"[{owner.project_hint}] 只读生成 ChatGPT App submission evidence 填写 payload 预览。"
                "从当前 release/submission evidence bundle 生成 fill_submission_evidence_files 的 copyable arguments；"
                "不写文件、不标 ready、不创建 OpenAI app draft、不提交 review、不发布。scope=mcp:read。"
            ),
            input_schema=submission_evidence_fill_preview_input_schema,
            output_schema=common_output_schema,
            annotations={
                "readOnlyHint": True,
                "destructiveHint": False,
                "openWorldHint": False,
                "idempotentHint": True,
            },
        ),
        MCPToolDef(
            name="get_submission_evidence_auto_draft",
            title="Get Submission Evidence Auto Draft",
            description=(
                f"[{owner.project_hint}] 只读生成可由当前 MCP/Commander 事实预填的 submission evidence 草稿。"
                "覆盖 mcp_tool_info、security_review、metadata_snapshot；返回 fill_submission_evidence_files 的 copyable arguments；"
                "不写文件、不标 ready、不创建 OpenAI app draft、不提交 review、不发布。scope=mcp:read。"
            ),
            input_schema=submission_evidence_auto_draft_input_schema,
            output_schema=common_output_schema,
            annotations={
                "readOnlyHint": True,
                "destructiveHint": False,
                "openWorldHint": False,
                "idempotentHint": True,
            },
        ),
        MCPToolDef(
            name="manage_submission_evidence_revision",
            title="Manage Submission Evidence Revision",
            description=(
                f"[{owner.project_hint}] 对 manifest 已绑定、明确标为 unfinished 的 docs/submission/*.md evidence 执行受控修订。"
                "preview 校验 replacement 正文、required sections、当前文件/manifest 摘要并创建短时工件；"
                "apply 要求 preview_id 和同一 replacement 正文，校验 proposed digest 与基线后原子替换 evidence 并保持 ready=false；"
                "结果不回传 evidence 正文，不提交 OpenAI review、不发布。"
                "scope: status=mcp:read, preview/discard=mcp:preview, apply=mcp:commit。"
            ),
            input_schema=submission_evidence_revision_input_schema,
            output_schema=common_output_schema,
            annotations={
                "readOnlyHint": False,
                "destructiveHint": True,
                "openWorldHint": False,
                "idempotentHint": False,
            },
        ),
        MCPToolDef(
            name="manage_p1_release_evidence",
            title="Manage P1 Release Evidence",
            description=(
                f"[{owner.project_hint}] 仅供本地/loopback operator 把 P1 release 的五类结构化观察收敛为 preview-bound runtime receipt。"
                "外部 ChatGPT、Connector/OAuth 与 runtime 观察被明确标为 operator-attested；不接受 raw transcript、token、cookie、URL 或日志。"
                "apply 需要 preview_id 和显式 confirm_release_evidence=true，仅写 ignored runtime receipt；它不授权 stable replacement、不会替换 stable、不会 commit/push 或修改 Connector/OAuth。"
                "scope: inspect/status=mcp:read, preview/discard=mcp:preview, apply=mcp:commit。"
            ),
            input_schema=p1_release_evidence_input_schema,
            output_schema=common_output_schema,
            annotations={
                "readOnlyHint": False,
                "destructiveHint": False,
                "openWorldHint": False,
                "idempotentHint": False,
            },
        ),
        MCPToolDef(
            name="init_submission_evidence",
            title="Initialize Submission Evidence",
            description=(
                f"[{owner.project_hint}] 初始化 ChatGPT App release/submission 的本地 evidence scaffold。"
                "创建 docs/chatgpt-app-submission-materials.json 和 docs/submission/*.todo.md 占位文件；"
                "不覆盖已有文件、不提交 OpenAI review、不发布、不读取 token/cookie/provider config。scope=mcp:commit。"
            ),
            input_schema=init_submission_evidence_input_schema,
            output_schema=common_output_schema,
            annotations={
                "readOnlyHint": False,
                "destructiveHint": False,
                "openWorldHint": False,
                "idempotentHint": True,
            },
        ),
        MCPToolDef(
            name="fill_submission_evidence_files",
            title="Fill Submission Evidence Files",
            description=(
                f"[{owner.project_hint}] 写入操作者提供的 ChatGPT App submission evidence 文本。"
                "仅创建 docs/submission/*.md，更新 docs/chatgpt-app-submission-materials.json 的 evidence 引用；"
                "默认不标 ready，不覆盖已有真实文件，不读取 token/cookie/provider config。scope=mcp:commit。"
            ),
            input_schema=fill_submission_evidence_input_schema,
            output_schema=common_output_schema,
            annotations={
                "readOnlyHint": False,
                "destructiveHint": False,
                "openWorldHint": False,
                "idempotentHint": True,
            },
        ),
        MCPToolDef(
            name="mark_submission_evidence_ready_fields",
            title="Mark Submission Evidence Ready Fields",
            description=(
                f"[{owner.project_hint}] 在人工审查后标记 ChatGPT App submission evidence ready 字段。"
                "只更新 docs/chatgpt-app-submission-materials.json 中已存在、非 .todo evidence 对应的 ready flag；"
                "要求 review_confirmation=human_reviewed；不写 evidence 正文、不提交 OpenAI review、不发布。scope=mcp:commit。"
            ),
            input_schema=mark_submission_evidence_ready_input_schema,
            output_schema=common_output_schema,
            annotations={
                "readOnlyHint": False,
                "destructiveHint": False,
                "openWorldHint": False,
                "idempotentHint": True,
            },
        ),
        MCPToolDef(
            name="record_product_console_action_result",
            title="Record Product Console Action Result",
            description=(
                f"[{owner.project_hint}] 记录 Product Console 推荐动作的短结果摘要，供后续 console map 和 Commander 卡片读取。"
                "只写 .colameta/runtime/product-console-action-results.json；不保存 raw tool output、不执行动作、"
                "不提交 OpenAI review、不发布、不替换 stable。scope=mcp:commit。"
            ),
            input_schema=product_console_action_result_input_schema,
            output_schema=common_output_schema,
            annotations={
                "readOnlyHint": False,
                "destructiveHint": False,
                "openWorldHint": False,
                "idempotentHint": True,
            },
        ),
        MCPToolDef(
            name="render_commander_app",
            title="Render Commander App",
            description=(
                f"[{owner.project_hint}] 渲染 ChatGPT Apps iframe 版 ColaMeta Commander 面板。"
                "返回 Commander manifest，并通过 MCP Apps resource URI 绑定 widget。"
                "面板只展示事实、只读调用和 preview-first 入口；不授权 executor run、commit、push 或 stable replacement。scope=mcp:read。"
            ),
            input_schema=commander_app_input_schema,
            output_schema=common_output_schema,
            annotations={
                "readOnlyHint": True,
                "destructiveHint": False,
                "openWorldHint": False,
                "idempotentHint": True,
            },
            meta={
                "ui": {
                    "resourceUri": commander_widget_uri,
                    "visibility": ["model", "app"],
                },
                "openai/outputTemplate": commander_widget_uri,
                "openai/toolInvocation/invoking": "Opening ColaMeta Commander",
                "openai/toolInvocation/invoked": "ColaMeta Commander ready",
            },
        ),
        MCPToolDef(
            name="get_apps_connector_smoke_packet",
            title="Get Apps Connector Smoke Packet",
            description=(
                f"[{owner.project_hint}] ChatGPT Apps connector 只读 smoke packet。"
                "返回 list_registered_projects 检查、connector closeout 调用、token_expired 处理边界和稳定替换 drift 提示。"
                "只接受 sanitized tunnel/control-plane evidence；不读取 token、cookie、browser login state、配置或 raw logs。scope=mcp:read。"
            ),
            input_schema=commander_app_input_schema,
            output_schema=common_output_schema,
            annotations={
                "readOnlyHint": True,
                "destructiveHint": False,
                "openWorldHint": False,
                "idempotentHint": True,
            },
        ),
        MCPToolDef(
            name="get_stable_replacement_cadence",
            title="Get Stable Replacement Cadence",
            description=(
                f"[{owner.project_hint}] 稳定服务替换节奏只读卡片。"
                "当 dev HEAD 与 stable HEAD 不一致时，默认返回 dev_ahead_stable、"
                "stable_replacement_not_required 和 batch_when_ready；"
                "不把普通产品化 drift 升级成替换授权请求。scope=mcp:read。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "project_name": {
                        "type": "string",
                        "description": "可选。按已登记 project_name 路由读取目标项目的 stable replacement cadence；服务模式下必须显式提供。",
                    }
                },
                "required": [],
                "additionalProperties": False,
            },
            output_schema=common_output_schema,
            annotations={
                "readOnlyHint": True,
                "destructiveHint": False,
                "openWorldHint": False,
                "idempotentHint": True,
            },
        ),
        MCPToolDef(
            name="get_stable_promotion_readiness",
            title="Get Stable Promotion Readiness",
            description=(
                f"[{owner.project_hint}] 稳定服务晋升只读预检卡片。"
                "汇总运行中代码新鲜度、Git clean、MCP 入口能力、registry、稳定运行目录来源和晋升阻断项。"
                "它只输出 evidence，不授权重启、替换稳定服务、push、executor run、route transition、release 或 deploy。scope=mcp:read。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "project_name": {
                        "type": "string",
                        "description": "可选。按已登记 project_name 路由读取目标项目稳定晋升预检；服务模式下必须显式提供。",
                    },
                    "work_item_id": {
                        "type": "string",
                        "description": "可选。把预检绑定到最终 Acceptance Gate 的冻结证据清单。",
                    },
                },
                "required": [],
                "additionalProperties": False,
            },
            output_schema=common_output_schema,
        ),
        MCPToolDef(
            name="manage_stable_promotion_evidence",
            title="Manage Stable Promotion Evidence",
            description=(
                f"[{owner.project_hint}] 为精确 Git candidate HEAD 生成、预览、持久化并验证 artifact manifest receipt。"
                "preview 只写短期 runtime preview；apply 仅写 .colameta runtime evidence，且要求 HEAD、origin/main、clean worktree "
                "与 preview 保持一致。它不替换或重启 stable service，不修改 Git，不 push，不 release/deploy。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["inspect", "status", "preview", "apply", "discard"],
                        "description": "inspect/status 只读；preview 生成受控预览；apply 持久化精确 HEAD manifest receipt；discard 丢弃预览。",
                    },
                    "project_name": {
                        "type": "string",
                        "description": "可选。服务模式下按已登记 project_name 路由；服务模式必须提供。",
                    },
                    "candidate_head": {
                        "type": "string",
                        "description": "preview/status 可选。精确候选 commit；省略时使用当前 HEAD。",
                    },
                    "work_item_id": {
                        "type": "string",
                        "description": "可选。验证 candidate 是否属于最终 Acceptance Gate 的冻结证据清单。",
                    },
                    "preview_id": {
                        "type": "string",
                        "description": "apply/discard 必填。来自 preview 的 preview_id。",
                    },
                },
                "required": ["action"],
                "additionalProperties": False,
            },
            output_schema=common_output_schema,
            annotations={
                "readOnlyHint": False,
                "destructiveHint": False,
                "openWorldHint": False,
                "idempotentHint": False,
            },
        ),
        MCPToolDef(
            name="get_stage_parallel_plan_preview",
            title="Get Stage Parallel Plan Preview",
            description=(
                f"[{owner.project_hint}] 阶段并行自动化只读规划卡片。"
                "把 stage 或 task_intents 拆成候选 task_shards，标出 allowed_files overlap、surface、风险和下一步。"
                "它不创建 executor preview、不启动 executor、不创建 branch/worktree、不 merge、不 commit、不 push、不替换 stable。scope=mcp:read。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "project_name": {
                        "type": "string",
                        "description": "可选。按已登记 project_name 路由读取目标项目；服务模式下必须显式提供。",
                    },
                    "stage_id": {
                        "type": "string",
                        "description": "可选。要规划的阶段 ID；不传时使用 stage_parallel_automation。",
                    },
                    "max_parallel_tasks": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 8,
                        "description": "可选。最多纳入多少个候选 task shard。默认 3，最大 8。",
                    },
                    "task_intents": {
                        "type": "array",
                        "description": "可选。候选任务意图；只用于只读拆分预览。",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "task_id": {"type": "string"},
                                "title": {"type": "string"},
                                "description": {"type": "string"},
                                "allowed_files": {"type": "array", "items": {"type": "string"}},
                                "surfaces": {"type": "array", "items": {"type": "string"}},
                                "risk_level": {
                                    "type": "string",
                                    "enum": ["none", "low", "moderate", "high", "blocked"],
                                },
                            },
                            "required": ["title"],
                        },
                    },
                },
                "required": [],
                "additionalProperties": False,
            },
            output_schema=common_output_schema,
            annotations={
                "readOnlyHint": True,
                "destructiveHint": False,
                "openWorldHint": False,
                "idempotentHint": True,
            },
        ),
        MCPToolDef(
            name="get_stage_parallel_run_preview",
            title="Get Stage Parallel Run Preview",
            description=(
                f"[{owner.project_hint}] 阶段并行运行只读预览卡片。"
                "基于 stage/task_intents 输出 parallel_group_id、每个 shard 的隔离 worktree/branch 建议和未来 executor preview request。"
                "它不创建 executor preview、不启动 executor、不创建 branch/worktree、不 merge、不 commit、不 push、不替换 stable。scope=mcp:read。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "project_name": {
                        "type": "string",
                        "description": "可选。按已登记 project_name 路由读取目标项目；服务模式下必须显式提供。",
                    },
                    "stage_id": {
                        "type": "string",
                        "description": "可选。要规划的阶段 ID；不传时使用 stage_parallel_automation。",
                    },
                    "provider": {
                        "type": "string",
                        "enum": ["codex", "opencode", "pi"],
                        "description": "可选。未来 executor preview 的 provider 偏好。默认 codex。",
                    },
                    "base_branch": {
                        "type": "string",
                        "description": "可选。未来隔离 worktree 的基准分支名。默认 main。",
                    },
                    "max_parallel_tasks": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 8,
                        "description": "可选。最多纳入多少个候选 task shard。默认 3，最大 8。",
                    },
                    "task_intents": {
                        "type": "array",
                        "description": "可选。候选任务意图；只用于只读运行预览。",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "task_id": {"type": "string"},
                                "title": {"type": "string"},
                                "description": {"type": "string"},
                                "allowed_files": {"type": "array", "items": {"type": "string"}},
                                "surfaces": {"type": "array", "items": {"type": "string"}},
                                "risk_level": {
                                    "type": "string",
                                    "enum": ["none", "low", "moderate", "high", "blocked"],
                                },
                            },
                            "required": ["title"],
                        },
                    },
                },
                "required": [],
                "additionalProperties": False,
            },
            output_schema=common_output_schema,
            annotations={
                "readOnlyHint": True,
                "destructiveHint": False,
                "openWorldHint": False,
                "idempotentHint": True,
            },
        ),
        MCPToolDef(
            name="get_stage_parallel_worktree_assignment_preview",
            title="Get Stage Parallel Worktree Assignment Preview",
            description=(
                f"[{owner.project_hint}] 阶段并行 worktree 分配只读预览卡片。"
                "检查每个 shard 的 deterministic worktree path 和 branch name 是否可分配。"
                "它不创建 branch/worktree、不创建 executor preview、不启动 executor、不 merge、不 commit、不 push、不替换 stable。scope=mcp:read。"
            ),
            input_schema=_stage_parallel_preview_input_schema(),
            output_schema=common_output_schema,
            annotations={
                "readOnlyHint": True,
                "destructiveHint": False,
                "openWorldHint": False,
                "idempotentHint": True,
            },
        ),
        MCPToolDef(
            name="get_stage_parallel_next_action_packet",
            title="Get Stage Parallel Next Action Packet",
            description=(
                f"[{owner.project_hint}] 阶段并行下一步只读 packet。"
                "根据当前 worktree、shard input、executor preview、run claim/report metadata 给出唯一 recommended next tool。"
                "它不创建 preview artifact、不写 shard input、不启动 executor、不 merge、不 commit、不 push、不替换 stable。scope=mcp:read。"
            ),
            input_schema=_stage_parallel_preview_input_schema(),
            output_schema=common_output_schema,
            annotations={
                "readOnlyHint": True,
                "destructiveHint": False,
                "openWorldHint": False,
                "idempotentHint": True,
            },
        ),
        MCPToolDef(
            name="get_stage_parallel_executor_group_preview",
            title="Get Stage Parallel Executor Group Preview",
            description=(
                f"[{owner.project_hint}] 阶段并行 executor group 只读预览卡片。"
                "基于 worktree assignment 预览每个 shard 的未来 executor preview request。"
                "它不创建 executor preview、不启动 executor、不创建 branch/worktree、不 merge、不 commit、不 push、不替换 stable。scope=mcp:read。"
            ),
            input_schema=_stage_parallel_preview_input_schema(),
            output_schema=common_output_schema,
            annotations={
                "readOnlyHint": True,
                "destructiveHint": False,
                "openWorldHint": False,
                "idempotentHint": True,
            },
        ),
        MCPToolDef(
            name="get_stage_parallel_executor_results_packet",
            title="Get Stage Parallel Executor Results Packet",
            description=(
                f"[{owner.project_hint}] 阶段并行 executor results 只读 packet。"
                "扫描隔离 worktree 的 structured preview/claim/report metadata，生成 sanitized executor_results。"
                "它不读 raw logs、不启动 executor、不 merge、不 commit、不 push、不替换 stable。scope=mcp:read。"
            ),
            input_schema=_stage_parallel_preview_input_schema(),
            output_schema=common_output_schema,
            annotations={
                "readOnlyHint": True,
                "destructiveHint": False,
                "openWorldHint": False,
                "idempotentHint": True,
            },
        ),
        MCPToolDef(
            name="get_stage_parallel_group_status",
            title="Get Stage Parallel Group Status",
            description=(
                f"[{owner.project_hint}] 阶段并行 group status 只读卡片。"
                "汇总 planned 或调用方提供的 sanitized executor result 摘要，判断是否 merge_ready。"
                "它不读取 raw logs、不启动 executor、不 merge、不 commit、不 push、不替换 stable。scope=mcp:read。"
            ),
            input_schema=_stage_parallel_preview_input_schema(include_executor_results=True),
            output_schema=common_output_schema,
            annotations={
                "readOnlyHint": True,
                "destructiveHint": False,
                "openWorldHint": False,
                "idempotentHint": True,
            },
        ),
        MCPToolDef(
            name="get_stage_parallel_merge_preview",
            title="Get Stage Parallel Merge Preview",
            description=(
                f"[{owner.project_hint}] 阶段并行 merge 只读预览卡片。"
                "当所有 shard succeeded 且 validation passed 时，生成 merge order 和验证命令预览。"
                "它不执行 merge、不 commit、不 push、不替换 stable。scope=mcp:read。"
            ),
            input_schema=_stage_parallel_preview_input_schema(include_executor_results=True),
            output_schema=common_output_schema,
            annotations={
                "readOnlyHint": True,
                "destructiveHint": False,
                "openWorldHint": False,
                "idempotentHint": True,
            },
        ),
        MCPToolDef(
            name="get_stage_parallel_closeout_packet",
            title="Get Stage Parallel Closeout Packet",
            description=(
                f"[{owner.project_hint}] 阶段并行 closeout 只读 packet。"
                "汇总 worktree assignment、executor group、group status 和 merge preview 的人审材料。"
                "它不写 Delivery accepted、不创建 ReviewDecision/GateEvent、不 merge、不 commit、不 push、不替换 stable。scope=mcp:read。"
            ),
            input_schema=_stage_parallel_preview_input_schema(include_executor_results=True),
            output_schema=common_output_schema,
            annotations={
                "readOnlyHint": True,
                "destructiveHint": False,
                "openWorldHint": False,
                "idempotentHint": True,
            },
        ),
        MCPToolDef(
            name="manage_stage_parallel_worktrees",
            title="Manage Stage Parallel Worktrees",
            description=(
                f"[{owner.project_hint}] 阶段并行隔离 git worktree 受控工具。"
                "preview 会生成 preview_id 并校验 base HEAD、dirty state、worktree path 和 branch；"
                "apply 只使用 preview_id 创建隔离 worktree。"
                "它不启动 executor、不创建 executor preview、不 merge、不 commit、不 push、不替换 stable。"
                "scope：status=mcp:read，preview/discard=mcp:preview，apply=mcp:commit。"
            ),
            input_schema=_manage_stage_parallel_worktrees_input_schema(),
            output_schema=common_output_schema,
            annotations={
                "readOnlyHint": False,
                "destructiveHint": False,
                "openWorldHint": False,
                "idempotentHint": False,
            },
        ),
        MCPToolDef(
            name="manage_stage_parallel_shard_inputs",
            title="Manage Stage Parallel Shard Inputs",
            description=(
                f"[{owner.project_hint}] 阶段并行 shard runner input 受控工具。"
                "preview 会校验每个 isolated worktree 已存在、branch/head 匹配且干净；"
                "apply 只在每个 worktree 的 .colameta/runtime 内写入 shard-specific plan/state/prompt overlay。"
                "它不创建 executor preview、不启动 executor、不 merge、不 commit、不 push、不替换 stable。"
                "scope：status=mcp:read，preview/discard=mcp:preview，apply=mcp:commit。"
            ),
            input_schema=_manage_stage_parallel_shard_inputs_input_schema(),
            output_schema=common_output_schema,
            annotations={
                "readOnlyHint": False,
                "destructiveHint": False,
                "openWorldHint": False,
                "idempotentHint": False,
            },
        ),
        MCPToolDef(
            name="manage_stage_parallel_executor_group",
            title="Manage Stage Parallel Executor Group",
            description=(
                f"[{owner.project_hint}] 阶段并行 executor preview group 受控工具。"
                "preview 会校验每个 isolated worktree 已存在、branch/head 匹配且 executor preflight 可通过；"
                "apply 只在每个 worktree 内创建 manage_executor_workflow run_once_preview artifact。"
                "它不启动 executor、不 merge、不 commit、不 push、不替换 stable。"
                "scope：status=mcp:read，preview/discard=mcp:preview，apply=mcp:commit。"
            ),
            input_schema=_manage_stage_parallel_executor_group_input_schema(),
            output_schema=common_output_schema,
            annotations={
                "readOnlyHint": False,
                "destructiveHint": False,
                "openWorldHint": False,
                "idempotentHint": False,
            },
        ),
        MCPToolDef(
            name="manage_stage_parallel_executor_runs",
            title="Manage Stage Parallel Executor Runs",
            description=(
                f"[{owner.project_hint}] 阶段并行 executor run group 受控工具。"
                "preview 会校验每个 isolated worktree 已有未消费、未过期且匹配当前 branch/head/provider 的 run_once_preview；"
                "apply 使用 preview_id 启动每个 worktree 内的 manage_executor_workflow run_once。"
                "它不 merge、不 commit main、不 push、不替换 stable。"
                "scope：status=mcp:read，preview/discard=mcp:preview，apply=mcp:commit。"
            ),
            input_schema=_manage_stage_parallel_executor_runs_input_schema(),
            output_schema=common_output_schema,
            annotations={
                "readOnlyHint": False,
                "destructiveHint": False,
                "openWorldHint": False,
                "idempotentHint": False,
            },
        ),
        MCPToolDef(
            name="manage_stage_parallel_merges",
            title="Manage Stage Parallel Merges",
            description=(
                f"[{owner.project_hint}] 阶段并行 merge 受控工具。"
                "preview 会校验 sanitized executor_results、target branch/head、source branch/head 和 clean target worktree；"
                "apply 使用 preview_id 顺序执行本地 git merge --no-ff。"
                "它不 push、不替换 stable、不写 Delivery accepted、不创建 ReviewDecision/GateEvent。"
                "scope：status=mcp:read，preview/discard=mcp:preview，apply=mcp:commit。"
            ),
            input_schema=_manage_stage_parallel_merges_input_schema(),
            output_schema=common_output_schema,
            annotations={
                "readOnlyHint": False,
                "destructiveHint": False,
                "openWorldHint": False,
                "idempotentHint": False,
            },
        ),
        MCPToolDef(
            name="get_project_identity",
            description=f"[{owner.project_hint}] 读取当前 MCP 绑定项目的身份标识，可用于在多项目 MCP 间确认上下文。",
            input_schema={
                "type": "object",
                "properties": {
                    "project_name": {
                        "type": "string",
                        "description": "可选。按已登记 project_name 路由读取目标项目身份。",
                    }
                },
                "required": [],
                "additionalProperties": False,
            },
            output_schema=common_output_schema,
        ),
        MCPToolDef(
            name="get_runtime_version_status",
            description=f"[{owner.project_hint}] Read-only runtime/version metadata for the running ColaMeta process and current project checkout. Reports process start time, loaded runtime HEAD, current checkout HEAD, branch/project root, and whether restart/reload appears needed. This tool never restarts, reloads, kills, applies, fetches, pulls, pushes, tags, or releases.",
            input_schema={
                "type": "object",
                "properties": {
                    "project_name": {
                        "type": "string",
                        "description": "可选。按已登记 project_name 路由读取目标项目 checkout HEAD；服务模式下必须显式提供。",
                    }
                },
                "required": [],
                "additionalProperties": False,
            },
            output_schema=common_output_schema,
        ),
        MCPToolDef(
            name="get_connector_runtime_health_status",
            description=(
                f"[{owner.project_hint}] Read-only connector/runtime closeout card. "
                "Combines runtime freshness, local Web/MCP service evidence, and optional sanitized tunnel_client/control_plane status. "
                "It does not read tunnel/proxy/provider config, secrets, tokens, cookies, logs, private memory, or raw provider responses, "
                "and it does not modify service/network state."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "project_name": {
                        "type": "string",
                        "description": "可选。按已登记 project_name 路由读取目标项目；服务模式下必须显式提供。",
                    },
                    "tunnel_client": {
                        "type": "object",
                        "description": "可选。调用方提供的 sanitized tunnel-client 状态，只采信 status/reason_code/evidence_source/last_observed_at。",
                        "properties": {
                            "status": {"type": "string"},
                            "reason_code": {"type": "string"},
                            "evidence_source": {"type": "string"},
                            "last_observed_at": {"type": "string"},
                        },
                        "additionalProperties": False,
                    },
                    "control_plane": {
                        "type": "object",
                        "description": "可选。调用方提供的 sanitized tunnel control-plane 状态，只采信 status/reason_code/evidence_source/last_observed_at。",
                        "properties": {
                            "status": {"type": "string"},
                            "reason_code": {"type": "string"},
                            "evidence_source": {"type": "string"},
                            "last_observed_at": {"type": "string"},
                        },
                        "additionalProperties": False,
                    },
                },
                "required": [],
                "additionalProperties": False,
            },
            output_schema=common_output_schema,
        ),
        MCPToolDef(
            name="get_plan_standards_report",
            description="Read a structured lint report for the current Runner plan before generating or updating plan patches. If blocking_issue_count > 0, do not call preview_insert_version or preview_update_version except to fix those plan issues.",
            input_schema={
                "type": "object",
                "properties": {
                    "project_name": {
                        "type": "string",
                        "description": "可选。按已登记 managed project_name 路由读取目标项目 plan 标准报告。",
                    },
                },
                "required": [],
                "additionalProperties": False,
            },
            output_schema=common_output_schema,
        ),
        MCPToolDef(
            name="get_runner_execution_standards",
            description="Read Runner execution standards before generating initial plans, plan.json, plan patches, prompts, fix prompts, diff reviews, or low-cost executor instructions. Includes bootstrap_plan, strict plan_format, and acceptance_commands rules.",
            input_schema={
                "type": "object",
                "properties": {
                    "section": {
                        "type": "string",
                        "description": "Optional section name (bootstrap_plan, plan_format, version_prompt, fix_prompt, plan_patch, diff_review, execution_branch, commit_review, low_cost_executor, executor_selection_strategy). Defaults to all.",
                    }
                },
                "required": [],
                "additionalProperties": False,
            },
            output_schema=common_output_schema,
        ),
        MCPToolDef(
            name="get_runner_status",
            description=f"[{owner.project_hint}] 读取 Runner 当前状态",
            input_schema={
                "type": "object",
                "properties": {
                    "project_name": {
                        "type": "string",
                        "description": "可选。按已登记 project_name 路由读取目标项目状态。",
                    }
                },
                "required": [],
                "additionalProperties": False,
            },
            output_schema=common_output_schema,
        ),
        MCPToolDef(
            name="get_executor_session_status",
            description="Read the current project-scoped executor session manifest. This is read-only and does not resume, reset, or modify executor sessions.",
            input_schema={
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
            output_schema=common_output_schema,
        ),
        MCPToolDef(
            name="get_executor_continuation_preview",
            description="Read a read-only continuation preview for the current project executor session. This does not resume, reset, modify files, or call any executor.",
            input_schema={
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
            output_schema=common_output_schema,
        ),
        MCPToolDef(
            name="get_executor_continuation_decision",
            description="Read a read-only continuation decision for the requested executor provider. This does not resume, reset, modify files, or call any executor.",
            input_schema={
                "type": "object",
                "properties": {
                    "provider": {
                        "type": "string",
                        "enum": ["pi", "codex", "opencode"],
                        "description": "Executor provider to evaluate continuation decision.",
                    }
                },
                "required": ["provider"],
                "additionalProperties": False,
            },
            output_schema=common_output_schema,
        ),
        MCPToolDef(
            name="get_executor_resume_invocation_preview",
            description="Read a read-only provider-specific resume invocation preview for the requested executor provider. This does not resume, reset, modify files, or call any executor.",
            input_schema={
                "type": "object",
                "properties": {
                    "provider": {
                        "type": "string",
                        "enum": ["pi", "codex", "opencode"],
                        "description": "Executor provider to inspect invocation preview.",
                    }
                },
                "required": ["provider"],
                "additionalProperties": False,
            },
            output_schema=common_output_schema,
        ),
        MCPToolDef(
            name="get_review_context",
            description=f"[{owner.project_hint}] Read a bundled review context for validating recent changes before telling the user whether a version can be committed. This is read-only and never stages, resets, cleans, or commits.",
            input_schema={
                "type": "object",
                "properties": {
                    "max_diff_chars": {
                        "type": "integer",
                        "description": "Maximum characters for git diff. Defaults to 60000 and is capped at 120000.",
                    },
                    "include_log": {
                        "type": "boolean",
                        "description": "Whether to include recent git log. Defaults to true.",
                    },
                    "log_limit": {
                        "type": "integer",
                        "description": "Recent commit count when include_log is true. Defaults to 5 and is capped at 20.",
                    },
                    "include_repo_overview": {
                        "type": "boolean",
                        "description": "Whether to include repo overview/file tree. Defaults to false.",
                    },
                    "max_files": {
                        "type": "integer",
                        "description": "Maximum file entries for repo overview when included. Defaults to 200 and is capped at 500.",
                    },
                    "project_name": {
                        "type": "string",
                        "description": "可选。按已登记 managed project_name 路由读取目标项目 review context。",
                    },
                },
                "required": [],
                "additionalProperties": False,
            },
            output_schema=common_output_schema,
        ),
        MCPToolDef(
            name="get_runner_workbench_context",
            description=f"[{owner.project_hint}] Read a bundled workbench context for quickly understanding Runner status, plan state, executor continuation, and git status. Partial failures are returned per section.",
            input_schema={
                "type": "object",
                "properties": {
                    "include_runner_state": {
                        "type": "boolean",
                        "description": "Whether to include runner status, current version result, next plan, and plan overview. Defaults to true.",
                    },
                    "include_executor": {
                        "type": "boolean",
                        "description": "Whether to include executor session and continuation preview. Defaults to true.",
                    },
                    "include_git_status": {
                        "type": "boolean",
                        "description": "Whether to include git status. Defaults to true.",
                    },
                    "provider": {
                        "type": "string",
                        "enum": ["pi", "codex", "opencode"],
                        "description": "Optional provider for continuation decision and resume invocation preview.",
                    },
                },
                "required": [],
                "additionalProperties": False,
            },
            output_schema=common_output_schema,
        ),
        MCPToolDef(
            name="manage_git",
            description=(
                f"[{owner.project_hint}] 统一 Git 工具。"
                "通过 action 路由到受控 Git 子操作。"
                "支持 project_name 路由到已登记 managed 项目。"
                "此工具不会执行任意 Git 命令，不会绕过 preview 审批。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "status",
                            "diff",
                            "review_context",
                            "topic_branch_preview",
                            "topic_branch_apply",
                            "commit_readiness",
                            "commit_message",
                            "commit_preview",
                            "commit_apply",
                            "push_status",
                            "push_preview",
                            "push_apply",
                            "pull_status",
                            "pull_preview",
                            "pull_apply",
                            "history_log",
                            "history_show",
                            "diff_commits",
                            "restore_file_preview",
                            "restore_file_apply",
                            "revert_preview",
                            "revert_apply",
                        ],
                        "description": "Git domain action. Routes to existing Git capability.",
                    },
                    "project_name": {
                        "type": "string",
                        "description": "可选。按已登记 managed project_name 路由目标项目。",
                    },
                    "context_binding": _operation_context_binding_input_schema(),
                    "preview_id": {
                        "type": "string",
                        "description": "apply 类 action 必填。来自对应 preview 的 preview_id。",
                    },
                    "preview_digest": {
                        "type": "string",
                        "description": (
                            "对应 preview 返回的精确 digest；"
                            "topic_branch_apply 必填。"
                        ),
                    },
                    "branch_name": {
                        "type": "string",
                        "description": "topic_branch_preview 的 delivery-safe codex/* target branch。",
                    },
                    "message": {
                        "type": "string",
                        "description": "commit_preview/commit_apply 的提交信息。",
                    },
                    "commit": {
                        "type": "string",
                        "description": "history_show/restore_file_preview/revert_preview 的 commit ref。",
                    },
                    "base": {
                        "type": "string",
                        "description": "diff_commits 的基础 commit。",
                    },
                    "head": {
                        "type": "string",
                        "description": "diff_commits 的目标 commit。",
                    },
                    "file": {
                        "type": "string",
                        "description": "restore_file_preview/diff_commits 的文件路径。",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "history_log 返回 commit 数量。默认 12，最大 50。",
                    },
                    "max_chars": {
                        "type": "integer",
                        "description": "diff/history_show/diff_commits/revert_preview 的 diff 字符限制。默认 40000，最大 80000。",
                    },
                    "include_diff_summary": {
                        "type": "boolean",
                        "description": "commit_readiness/commit_message 是否包含 diff 摘要。默认 true。",
                    },
                    "max_diff_chars": {
                        "type": "integer",
                        "description": "commit_readiness/commit_message 的 diff 字符限制。默认 40000，最大 80000。",
                    },
                    "style": {
                        "type": "string",
                        "enum": ["conventional", "runner_version", "concise"],
                        "description": "commit_message 可选。commit message 风格倾向。默认 runner_version。",
                    },
                    "scope_hint": {
                        "type": "string",
                        "description": "commit_message 可选。版本号或 scope 提示。",
                    },
                    "include_files": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "可选。commit_readiness/commit_message 指定的文件子集。",
                    },
                    "exclude_files": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "可选。commit_readiness/commit_message 排除的文件。",
                    },
                    "include_patch": {
                        "type": "boolean",
                        "description": "history_show 是否包含 patch。默认 true。",
                    },
                    "include_log": {
                        "type": "boolean",
                        "description": "review_context 是否包含 git log。默认 true。",
                    },
                    "log_limit": {
                        "type": "integer",
                        "description": "review_context 的 log 数量。默认 5，最大 20。",
                    },
                    "include_repo_overview": {
                        "type": "boolean",
                        "description": "review_context 是否包含 repo overview。默认 false。",
                    },
                    "max_files": {
                        "type": "integer",
                        "description": "review_context 的 repo overview 最大文件数。默认 200，最大 500。",
                    },
                    "reason": {
                        "type": "string",
                        "description": "可选。preview 类动作的理由说明。",
                    },
                    "scan_limit": {
                        "type": "integer",
                        "description": "reconcile_git_history_preview 可选。扫描最近 N 个 commit，默认 20，最大 100。",
                    },
                },
                "required": ["action"],
                "additionalProperties": False,
            },
            output_schema=common_output_schema,
        ),
        MCPToolDef(
            name="manage_git_commit",
            description=f"[{owner.project_hint}] Manage a controlled git commit flow with readiness, suggest_commit_message, commit_workflow_preview, preview, and commit actions. 支持按已登记 managed project_name 路由目标项目。This tool never runs arbitrary shell, never exposes arbitrary git commands, and never stages all files at once.",
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["readiness", "suggest_commit_message", "commit_workflow_preview", "preview", "commit"],
                        "description": "Commit workflow action.",
                    },
                    "message": {
                        "type": "string",
                        "description": "Commit message for preview, commit_workflow_preview, or commit. Required for preview; optional for commit if matching preview message is stored.",
                    },
                    "preview_id": {
                        "type": "string",
                        "description": "Preview id returned by action=preview or commit_workflow_preview. Required for action=commit.",
                    },
                    "include_diff_summary": {
                        "type": "boolean",
                        "description": "Whether readiness/preview should include a bounded diff summary. Defaults to true.",
                    },
                    "max_diff_chars": {
                        "type": "integer",
                        "description": "Maximum diff characters to include in readiness/preview. Defaults to 40000 and is capped at 80000.",
                    },
                    "style": {
                        "type": "string",
                        "enum": ["conventional", "runner_version", "concise"],
                        "description": "suggest_commit_message 可选。commit message 风格倾向。默认 runner_version。",
                    },
                    "scope_hint": {
                        "type": "string",
                        "description": "suggest_commit_message 可选。版本号或 scope 提示，例如 v1.73。",
                    },
                    "include_files": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "可选，仅用于 readiness/suggest_commit_message/commit_workflow_preview/preview。指定要提交的文件子集。",
                    },
                    "exclude_files": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "可选，仅用于 readiness/suggest_commit_message/commit_workflow_preview/preview。用于从选择结果中排除文件。",
                    },
                    "project_name": {
                        "type": "string",
                        "description": "可选。按已登记 managed project_name 路由 readiness、suggest_commit_message、commit_workflow_preview、preview、commit。",
                    },
                    "context_binding": _operation_context_binding_input_schema(),
                },
                "required": ["action"],
                "additionalProperties": False,
            },
            output_schema=common_output_schema,
        ),
        MCPToolDef(
            name="manage_git_remote",
            description=f"[{owner.project_hint}] 受控 Git remote 工具。支持 push、fetch preview/apply 与 fast-forward pull preview/apply。project_name 当前支持已登记 managed 项目的 push_status、push_preview、push_apply。",
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "push_status",
                            "push_preview",
                            "push_apply",
                            "fetch_preview",
                            "fetch_apply",
                            "pull_status",
                            "pull_preview",
                            "pull_apply",
                        ],
                        "description": "Git remote action.",
                    },
                    "preview_id": {
                        "type": "string",
                        "description": "apply 类 action 必填。来自对应 preview 的 preview_id。",
                    },
                    "reason": {
                        "type": "string",
                        "description": "可选。预览原因说明。",
                    },
                    "project_name": {
                        "type": "string",
                        "description": "可选。按已登记 managed project_name 路由 push_status、push_preview、push_apply。",
                    },
                },
                "required": ["action"],
                "additionalProperties": False,
            },
            output_schema=common_output_schema,
        ),
        MCPToolDef(
            name="manage_runner_plan",
            description=f"[{owner.project_hint}] Manage controlled Runner plan onboarding for the bound source project with inspect, preview, and apply actions. bootstrap_preview project_name is the new plan name, not a registry routing key. This never writes arbitrary files and does not use paste-plan UI.",
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["inspect", "bootstrap_preview", "import_preview", "apply"],
                        "description": "Runner plan management action.",
                    },
                    "project_name": {
                        "type": "string",
                        "description": "bootstrap_preview 必填。新建 plan.json 的 project_name；仅用于命名当前绑定 source 项目，不按 registry 路由。",
                    },
                    "plan_json": {
                        "type": "string",
                        "description": "Full plan JSON string for import_preview. Intended for MCP/ChatGPT structured import, not Web paste UI.",
                    },
                    "preview_id": {
                        "type": "string",
                        "description": "Preview id returned by bootstrap_preview or import_preview. Required for apply.",
                    },
                    "allow_overwrite": {
                        "type": "boolean",
                        "description": "Whether apply can overwrite an existing .colameta/plan.json. Defaults to false.",
                    },
                },
                "required": ["action"],
                "additionalProperties": False,
            },
            output_schema=common_output_schema,
        ),
        MCPToolDef(
            name="manage_project_memory",
            description=f"[{owner.project_hint}] 统一项目记忆工具。支持 record_type=memory|todo|decision 与 action=read|add|update|delete。memory 记录 GPTs 长期记忆，todo 记录后续事项，decision 记录已确认决策。支持 project_name 路由到已登记 managed 项目。",
            input_schema={
                "type": "object",
                "properties": {
                    "record_type": {
                        "type": "string",
                        "enum": ["memory", "todo", "decision"],
                        "description": "记忆类型。memory=GPTs 长期记忆；todo=后续事项；decision=已确认决策。",
                    },
                    "action": {
                        "type": "string",
                        "enum": ["read", "add", "update", "delete"],
                        "description": "记忆操作。",
                    },
                    "project_name": {
                        "type": "string",
                        "description": "可选。按已登记 managed project_name 路由到目标项目记忆。",
                    },
                    "id": {
                        "type": "string",
                        "description": "todo/decision update/delete 必填；memory 不使用。",
                    },
                    "include_done": {
                        "type": "boolean",
                        "default": False,
                        "description": "仅 todo read 有意义。是否包含 done 条目。",
                    },
                    "content": {
                        "type": "string",
                        "description": "todo add/update 的内容；memory add/update 的完整 Markdown 内容。",
                    },
                    "max_chars": {
                        "type": "integer",
                        "description": "仅 memory read 有意义。返回内容字符上限，默认 30000，最大 120000。",
                    },
                    "status": {
                        "type": "string",
                        "description": "todo 或 decision 的状态。具体允许值由底层记录类型校验。",
                    },
                    "title": {
                        "type": "string",
                        "description": "decision add/update 的标题。",
                    },
                    "decision": {
                        "type": "string",
                        "description": "decision add/update 的决策内容。",
                    },
                    "reason": {
                        "type": "string",
                        "description": "decision add/update 的原因。",
                    },
                    "related_versions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "decision add/update 的相关版本列表。",
                    },
                },
                "required": ["record_type", "action"],
                "additionalProperties": False,
            },
            output_schema=common_output_schema,
        ),
        MCPToolDef(
            name="manage_runner_record",
            description=f"[{owner.project_hint}] 统一项目记录工具。支持 record_type=todo|decision 与 action=read|add|update|delete，内部复用现有 todo/decision 实现与校验。支持 project_name 路由到已登记 managed 项目。",
            input_schema={
                "type": "object",
                "properties": {
                    "record_type": {
                        "type": "string",
                        "enum": ["todo", "decision"],
                        "description": "记录类型。",
                    },
                    "action": {
                        "type": "string",
                        "enum": ["read", "add", "update", "delete"],
                        "description": "记录操作。",
                    },
                    "project_name": {
                        "type": "string",
                        "description": "可选。按已登记 managed project_name 路由到目标项目记录。",
                    },
                    "id": {
                        "type": "string",
                        "description": "update/delete 必填；todo/decision 记录 id。",
                    },
                    "include_done": {
                        "type": "boolean",
                        "default": False,
                        "description": "仅 todo read 有意义。是否包含 done 条目。",
                    },
                    "content": {
                        "type": "string",
                        "description": "todo add/update 的内容。",
                    },
                    "status": {
                        "type": "string",
                        "description": "todo 或 decision 的状态。具体允许值由底层记录类型校验。",
                    },
                    "title": {
                        "type": "string",
                        "description": "decision add/update 的标题。",
                    },
                    "decision": {
                        "type": "string",
                        "description": "decision add/update 的决策内容。",
                    },
                    "reason": {
                        "type": "string",
                        "description": "decision add/update 的原因。",
                    },
                    "related_versions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "decision add/update 的相关版本列表。",
                    },
                },
                "required": ["record_type", "action"],
                "additionalProperties": False,
            },
            output_schema=common_output_schema,
        ),
        MCPToolDef(
            name="manage_workflow_run",
            description=f"[{owner.project_hint}] 统一 workflow run 查询工具。支持 action=list|get，内部复用现有 workflow record 列表与详情读取实现。支持 project_name 路由到已登记 managed 项目。scope=mcp:read。",
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "get"],
                        "description": "查询操作。",
                    },
                    "workflow_id": {
                        "type": "string",
                        "description": "action=get 必填；workflow_id。",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "action=list 可选。最大返回条数。默认 20，最大 100。",
                    },
                    "workflow_name": {
                        "type": "string",
                        "description": "action=list 可选。按 workflow_name 筛选。",
                    },
                    "status": {
                        "type": "string",
                        "description": "action=list 可选。按 status 筛选（running/succeeded/failed/partial/unsupported）。",
                    },
                    "project_name": {
                        "type": "string",
                        "description": "可选。按已登记 managed project_name 路由读取目标项目 workflow records。",
                    },
                },
                "required": ["action"],
                "additionalProperties": False,
            },
            output_schema=common_output_schema,
        ),
        MCPToolDef(
            name="todo_read",
            description=f"[{owner.project_hint}] 读取 .colameta/todolist.json，可选只看 planned 项或包含 done 项。支持 project_name 路由到已登记 managed 项目。",
            input_schema={
                "type": "object",
                "properties": {
                    "include_done": {
                        "type": "boolean",
                        "default": False,
                        "description": "是否包含 done 条目。默认只返回 planned 条目。",
                    },
                    "project_name": {
                        "type": "string",
                        "description": "可选。按已登记 managed project_name 路由读取目标项目 todolist。",
                    },
                },
                "required": [],
                "additionalProperties": False,
            },
            output_schema=common_output_schema,
        ),
        MCPToolDef(
            name="todo_add",
            description=f"[{owner.project_hint}] 追加一条需求备忘录，可选指定 status。支持 project_name 路由到已登记 managed 项目。",
            input_schema={
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "需求压缩描述。",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["planned", "done"],
                        "description": "条目状态。默认 planned。",
                    },
                    "project_name": {
                        "type": "string",
                        "description": "可选。按已登记 managed project_name 路由写入目标项目 todolist。",
                    },
                },
                "required": ["content"],
                "additionalProperties": False,
            },
            output_schema=common_output_schema,
        ),
        MCPToolDef(
            name="todo_update",
            description=f"[{owner.project_hint}] 按 id 更新一条需求备忘录内容或状态，保留原 id 和 created_at。支持 project_name 路由到已登记 managed 项目。",
            input_schema={
                "type": "object",
                "properties": {
                    "id": {
                        "type": "string",
                        "description": "todo id。",
                    },
                    "content": {
                        "type": "string",
                        "description": "更新后的需求压缩描述。",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["planned", "done"],
                        "description": "更新后的条目状态。",
                    },
                    "project_name": {
                        "type": "string",
                        "description": "可选。按已登记 managed project_name 路由更新目标项目 todolist。",
                    },
                },
                "required": ["id"],
                "additionalProperties": False,
            },
            output_schema=common_output_schema,
        ),
        MCPToolDef(
            name="todo_delete",
            description=f"[{owner.project_hint}] 按 id 删除一条需求备忘录。支持 project_name 路由到已登记 managed 项目。",
            input_schema={
                "type": "object",
                "properties": {
                    "id": {
                        "type": "string",
                        "description": "todo id。",
                    },
                    "project_name": {
                        "type": "string",
                        "description": "可选。按已登记 managed project_name 路由删除目标项目 todolist。",
                    },
                },
                "required": ["id"],
                "additionalProperties": False,
            },
            output_schema=common_output_schema,
        ),
        MCPToolDef(
            name="decision_read",
            description=f"[{owner.project_hint}] 读取 .colameta/decisions.json，返回已记录的产品或架构决策。支持 project_name 路由到已登记 managed 项目。",
            input_schema={
                "type": "object",
                "properties": {
                    "project_name": {
                        "type": "string",
                        "description": "可选。按已登记 managed project_name 路由读取目标项目 decisions。",
                    },
                },
                "required": [],
                "additionalProperties": False,
            },
            output_schema=common_output_schema,
        ),
        MCPToolDef(
            name="decision_add",
            description=f"[{owner.project_hint}] 追加一条已接受的产品或架构决策记录。支持 project_name 路由到已登记 managed 项目。",
            input_schema={
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "决策标题。",
                    },
                    "decision": {
                        "type": "string",
                        "description": "决策内容。",
                    },
                    "reason": {
                        "type": "string",
                        "description": "决策原因。",
                    },
                    "related_versions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "相关版本列表。",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["active", "superseded", "rejected"],
                        "description": "决策状态。默认 active。",
                    },
                    "project_name": {
                        "type": "string",
                        "description": "可选。按已登记 managed project_name 路由写入目标项目 decisions。",
                    },
                },
                "required": ["title", "decision", "reason"],
                "additionalProperties": False,
            },
            output_schema=common_output_schema,
        ),
        MCPToolDef(
            name="decision_update",
            description=f"[{owner.project_hint}] 按 id 更新决策记录内容、原因、相关版本或状态。支持 project_name 路由到已登记 managed 项目。",
            input_schema={
                "type": "object",
                "properties": {
                    "id": {
                        "type": "string",
                        "description": "decision id。",
                    },
                    "title": {
                        "type": "string",
                        "description": "更新后的决策标题。",
                    },
                    "decision": {
                        "type": "string",
                        "description": "更新后的决策内容。",
                    },
                    "reason": {
                        "type": "string",
                        "description": "更新后的决策原因。",
                    },
                    "related_versions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "更新后的相关版本列表。",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["active", "superseded", "rejected"],
                        "description": "更新后的决策状态。",
                    },
                    "project_name": {
                        "type": "string",
                        "description": "可选。按已登记 managed project_name 路由更新目标项目 decisions。",
                    },
                },
                "required": ["id"],
                "additionalProperties": False,
            },
            output_schema=common_output_schema,
        ),
        MCPToolDef(
            name="decision_delete",
            description=f"[{owner.project_hint}] 按 id 删除一条决策记录。支持 project_name 路由到已登记 managed 项目。",
            input_schema={
                "type": "object",
                "properties": {
                    "id": {
                        "type": "string",
                        "description": "decision id。",
                    },
                    "project_name": {
                        "type": "string",
                        "description": "可选。按已登记 managed project_name 路由删除目标项目 decisions。",
                    },
                },
                "required": ["id"],
                "additionalProperties": False,
            },
            output_schema=common_output_schema,
        ),
        MCPToolDef(
            name="manage_plan_version",
            description=f"[{owner.project_hint}] 结构化 Runner plan 版本管理工具。支持 inspect、insert/update/repair preview、insert_from_prompt_file_preview、apply_preview_status、apply_preview、reload_plan、continue_next_version。reload_plan/continue_next_version 会同步 state.json。project_name 支持已登记 managed 项目的 preview、status、apply_preview、reload_plan、continue_next_version 路由。",
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["inspect", "insert_preview", "update_preview", "repair_preview", "apply_preview_status", "insert_from_prompt_file_preview", "apply_preview", "reload_plan", "continue_next_version"],
                        "description": "Plan version 管理操作。reload_plan 会重载 plan 并同步 state.json；continue_next_version 会在当前版本通过后推进到下一版本；apply_preview 受控应用 plan patch。",
                    },
                    "patch_id": {
                        "type": "string",
                        "description": "apply_preview_status 或 apply_preview 操作需要的 patch_id。",
                    },
                    "insert_after": {
                        "type": "string",
                        "description": "insert_preview 操作需要。在此版本后插入新版本。",
                    },
                    "version": {
                        "type": "string",
                        "description": "insert_preview（新版本号）或 update_preview（目标版本号）或 repair_preview（可选版本过滤）。",
                    },
                    "name": {
                        "type": "string",
                        "description": "insert_preview 必填。版本显示名称。",
                    },
                    "description": {
                        "type": "string",
                        "description": "insert_preview 必填。版本描述。",
                    },
                    "prompt": {
                        "type": "string",
                        "description": "insert_preview 必填。版本 prompt 内容。update_preview 可选更新 prompt。",
                    },
                    "allowed_files": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "insert_preview 必填。版本允许修改的文件模式列表。不能为空。",
                    },
                    "acceptance_commands": {
                        "type": "array",
                        "items": {
                            "oneOf": [
                                {"type": "string"},
                                {"type": "object",
                                 "properties": {
                                     "command": {"type": "string"},
                                     "timeout_seconds": {"type": "integer"},
                                     "continue_on_failure": {"type": "boolean"},
                                 },
                                 "required": ["command"],
                                 "additionalProperties": False,
                                },
                            ],
                        },
                        "description": "insert_preview 必填。版本验收命令列表。可以是 string 或 object（command/timeout_seconds/continue_on_failure）。不允许空列表。",
                    },
                    "manual_acceptance": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "可选。手动验收检查项列表。",
                    },
                    "out_of_scope": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "可选。此版本不包含的范围说明列表。",
                    },
                    "context_files": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "可选。版本上下文文件模式列表。",
                    },
                    "forbidden_files": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "可选。版本禁止修改的文件模式列表。",
                    },
                    "allow_no_changes": {
                        "type": "boolean",
                        "description": "可选。read-only/audit 版本设置为 true 后，可在验收通过且无 allowed_files diff 时通过。默认 false 仍阻断无变更。",
                    },
                    "execution": {
                        "type": "object",
                        "description": "可选。版本执行器配置。provider 必须是 pi/codex/opencode。",
                        "properties": {
                            "provider": {
                                "type": "string",
                                "enum": ["pi", "codex", "opencode"],
                                "description": "执行器 provider。",
                            },
                        },
                        "additionalProperties": True,
                    },
                    "prompt_file": {
                        "type": "string",
                        "description": "insert_preview 可选。覆盖默认 prompt 文件名。insert_from_prompt_file_preview 必填。prompt 文件相对路径，仅文件名，例如 v1.84.54.md。",
                    },
                    "repair_kinds": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": ["acceptance_command_shape", "invalid_provider", "missing_optional_safety_fields", "prompt_file_safety"],
                        },
                        "description": "repair_preview 可选。指定需要修复的种类；不传时自动检测所有可修复项。",
                    },
                    "dry_run": {
                        "type": "boolean",
                        "description": "repair_preview 可选。是否只做检查不生成 patch。默认 true。",
                    },
                    "project_name": {
                        "type": "string",
                        "description": "可选。按已登记 managed project_name 路由所有支持动作：insert_preview、update_preview、repair_preview、apply_preview_status、insert_from_prompt_file_preview、apply_preview、reload_plan、continue_next_version。",
                    },
                },
                "required": ["action"],
                "additionalProperties": False,
            },
            output_schema=common_output_schema,
        ),
        MCPToolDef(
            name="manage_project_patch",
            description=f"[{owner.project_hint}] 通用小范围非文档文件的受控 patch 工具（源码、脚本、配置、测试数据）。README.md、AGENTS.md、docs/*.md 请优先使用 manage_project_docs。只有用户明确给出 exact old_text/new_text 或非文档通用 patch 时，才用本工具。scope：status=mcp:read，preview=mcp:preview，apply=mcp:commit。",
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["preview", "apply", "status"],
                        "description": "Patch 操作。preview 预览改动（不写文件），apply 应用 preview（写文件），status 查询 preview 状态。",
                    },
                    "preview_id": {
                        "type": "string",
                        "description": "apply 或 status 操作需要的 preview_id。",
                    },
                    "file": {
                        "type": "string",
                        "description": "精确替换模式的相对文件路径。",
                    },
                    "old_text": {
                        "type": "string",
                        "description": "精确替换模式的旧文本。必须在文件中唯一。",
                    },
                    "new_text": {
                        "type": "string",
                        "description": "精确替换模式的新文本。可以为空字符串。",
                    },
                    "patch_text": {
                        "type": "string",
                        "description": "unified diff 模式的 patch 文本。",
                    },
                    "reason": {
                        "type": "string",
                        "description": "可选。patch 理由说明。",
                    },
                    "max_files": {
                        "type": "integer",
                        "description": "可选。最大文件数。默认 5，最大 5。",
                    },
                    "max_diff_chars": {
                        "type": "integer",
                        "description": "可选。最大 diff 字符数。默认 20000，最大 20000。",
                    },
                    "project_name": {
                        "type": "string",
                        "description": "可选。按已登记 managed project_name 路由所有操作。",
                    },
                },
                "required": ["action"],
                "additionalProperties": False,
            },
            output_schema=common_output_schema,
        ),
        MCPToolDef(
            name="manage_git_history",
            description=f"[{owner.project_hint}] 受控 Git 历史管理工具。支持 log（查看历史）、show（查看 commit 详情）、diff_commits（对比 commit）、reconcile_git_history_preview（扫描 direct version 候选）、restore_file_preview（恢复文件预览）、restore_file_apply（恢复文件）、revert_preview（撤销预览）、revert_apply（受控撤销应用，必须使用 revert_preview 返回的 preview_id，不自动 commit，冲突时不自动解决）。不提供 reset/clean/push/merge/rebase。scope：log/show/diff_commits=mcp:read，reconcile_git_history_preview/restore_file_preview/revert_preview=mcp:preview，restore_file_apply/revert_apply=mcp:commit。",
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["log", "show", "diff_commits", "reconcile_git_history_preview", "restore_file_preview", "restore_file_apply", "revert_preview", "revert_apply"],
                        "description": "Git history 操作。",
                    },
                    "commit": {
                        "type": "string",
                        "description": "show、restore_file_preview、revert_preview 使用的 commit ref。",
                    },
                    "base": {
                        "type": "string",
                        "description": "diff_commits 的基础 commit。",
                    },
                    "head": {
                        "type": "string",
                        "description": "diff_commits 的目标 commit。",
                    },
                    "file": {
                        "type": "string",
                        "description": "restore_file_preview 必填的相对文件路径；diff_commits 可选过滤文件。",
                    },
                    "preview_id": {
                        "type": "string",
                        "description": "restore_file_apply/revert_apply 使用的 preview_id。",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "log 返回 commit 数量。默认 12，最大 50。",
                    },
                    "max_chars": {
                        "type": "integer",
                        "description": "show/diff_commits/revert_preview 的 diff 字符限制。默认 40000，最大 80000。",
                    },
                    "include_patch": {
                        "type": "boolean",
                        "description": "show 是否包含 patch。默认 true。",
                    },
                    "reason": {
                        "type": "string",
                        "description": "可选。preview 类动作的理由说明。",
                    },
                    "scan_limit": {
                        "type": "integer",
                        "description": "reconcile_git_history_preview 可选。扫描最近 N 个 commit，默认 20，最大 100。",
                    },
                    "project_name": {
                        "type": "string",
                        "description": "可选。按已登记 managed project_name 路由所有操作。",
                    },
                },
                "required": ["action"],
                "additionalProperties": False,
            },
            output_schema=common_output_schema,
        ),
        MCPToolDef(
            name="manage_plan_workflow",
            description=f"[{owner.project_hint}] [已弃用/legacy] 受控 Plan Workflow 自动化工具。此工具仅用于兼容旧流程，新流程请使用 manage_runner_plan（source-only 纳管）或 manage_plan_version（版本管理）。支持 source_onboarding_preview（从源码项目自动生成 onboarding 预览）、plan_repair_preview（lint 修复预览）、plan_extend_preview（扩展新版本预览）。project_name 当前仅支持已登记 managed 项目的 plan_repair_preview、plan_extend_preview。scope=mcp:preview。",
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["source_onboarding_preview", "plan_repair_preview", "plan_extend_preview"],
                        "description": "Plan workflow action。",
                    },
                    "dry_run": {
                        "type": "boolean",
                        "description": "source_onboarding_preview 和 plan_repair_preview 支持 dry_run=true 只做分析不生成 patch。",
                    },
                    "max_files": {
                        "type": "integer",
                        "description": "source_onboarding_preview 可选。仓库文件树最大文件数。默认 300，最大 500。",
                    },
                    "version": {
                        "type": "string",
                        "description": "plan_repair_preview 可选版本过滤；plan_extend_preview 新版本号。",
                    },
                    "repair_kinds": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": ["acceptance_command_shape", "invalid_provider", "missing_optional_safety_fields", "prompt_file_safety"],
                        },
                        "description": "plan_repair_preview 可选。指定修复种类。",
                    },
                    "insert_after": {
                        "type": "string",
                        "description": "plan_extend_preview 可选。在此版本后插入。",
                    },
                    "name": {
                        "type": "string",
                        "description": "plan_extend_preview 可选。版本名称。",
                    },
                    "description": {
                        "type": "string",
                        "description": "plan_extend_preview 可选。版本描述。",
                    },
                    "prompt": {
                        "type": "string",
                        "description": "plan_extend_preview 可选。版本 prompt。不传则自动生成。",
                    },
                    "project_name": {
                        "type": "string",
                        "description": "source_onboarding_preview 单项目模式下可选，覆盖项目名称。不传则自动推断。project_name 路由模式下仅支持已登记 managed 项目的 plan_repair_preview、plan_extend_preview。",
                    },
                    "goal": {
                        "type": "string",
                        "description": "source_onboarding_preview 可选。覆盖项目目标。不传则自动推断。",
                    },
                    "first_version": {
                        "type": "string",
                        "description": "source_onboarding_preview 可选。首版本号。默认 v1.0。",
                    },
                    "first_version_name": {
                        "type": "string",
                        "description": "source_onboarding_preview 可选。首版本显示名称。默认 Adopt existing project into Runner。",
                    },
                    "target_version": {
                        "type": "string",
                        "description": "manage_plan_workflow 可选。目标版本号，用于 plan_repair_preview。",
                    },
                    "reason": {
                        "type": "string",
                        "description": "manage_plan_workflow 可选。操作理由说明，进入 workflow record。",
                    },
                },
                "required": ["action"],
                "additionalProperties": False,
            },
            output_schema=common_output_schema,
        ),
        MCPToolDef(
            name="manage_project_docs",
            description=f"[{owner.project_hint}] 文档语义层工具。创建或修改 README.md、AGENTS.md、docs/*.md 时优先使用。支持 index、search、read_section、update_section_preview、append_section_preview（支持创建新文件）、sync_docs_preview、apply。底层复用 manage_project_patch。scope：index/search/read_section=mcp:read，preview 类=mcp:preview，apply=mcp:commit。",
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["index", "search", "read_section", "update_section_preview", "append_section_preview", "sync_docs_preview", "apply"],
                        "description": "Docs management action。",
                    },
                    "project_name": {
                        "type": "string",
                        "description": "可选。按已登记 managed project_name 路由文档索引、读取、搜索、预览和 apply。",
                    },
                    "file": {
                        "type": "string",
                        "description": "read_section/update_section_preview/append_section_preview 使用的文件路径。只允许 README.md、AGENTS.md、docs/*.md。",
                    },
                    "heading": {
                        "type": "string",
                        "description": "read_section/update_section_preview 使用的 Markdown heading。",
                    },
                    "query": {
                        "type": "string",
                        "description": "search 使用的搜索关键词。",
                    },
                    "new_content": {
                        "type": "string",
                        "description": "update_section_preview 使用的 section body 新内容（不含 heading 行）。",
                    },
                    "section_heading": {
                        "type": "string",
                        "description": "append_section_preview 使用的新 section heading。",
                    },
                    "section_content": {
                        "type": "string",
                        "description": "append_section_preview 使用的新 section 内容。",
                    },
                    "after_heading": {
                        "type": "string",
                        "description": "append_section_preview 可选。指定在此 heading section 后追加。",
                    },
                    "stale_terms": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "sync_docs_preview 可选。自定义过时术语列表。",
                    },
                    "preview_id": {
                        "type": "string",
                        "description": "apply 使用的 preview_id。",
                    },
                    "max_chars": {
                        "type": "integer",
                        "description": "read/index/search 输出字符限制。默认 12000，最大 30000。",
                    },
                    "max_files": {
                        "type": "integer",
                        "description": "index/search/sync_docs_preview 最大文件数。默认 50，最大 100。",
                    },
                    "reason": {
                        "type": "string",
                        "description": "可选。操作理由，进入 workflow record 和底层 patch reason。",
                    },
                },
                "required": ["action"],
                "additionalProperties": False,
            },
            output_schema=common_output_schema,
        ),
        MCPToolDef(
            name="manage_prompt_file",
            description=(
                f"[{owner.project_hint}] 受控提示词文件保存工具。"
                "支持 preview（预览）、apply（应用 preview 写入文件）、status（查询 preview 状态）、discard（废弃 preview artifact）。"
                "文件写入 .colameta/prompts/{version}.md。"
                "不运行执行器、不提交 Git、不修改 Runner plan。"
                "project_name 支持已登记 managed 项目的 preview、apply、status、discard。"
                "scope：status=mcp:read，preview=mcp:preview，discard=mcp:preview，apply=mcp:commit。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["preview", "apply", "status", "discard"],
                        "description": "Prompt file management action. discard 废弃 preview artifact，不写文件。",
                    },
                    "version": {
                        "type": "string",
                        "description": "preview 必填。版本号，用于生成文件名 .colameta/prompts/{version}.md。",
                    },
                    "content": {
                        "type": "string",
                        "description": "preview 必填。提示词正文。",
                    },
                    "preview_id": {
                        "type": "string",
                        "description": "apply/status/discard 必填。来自 preview 的 preview_id。",
                    },
                    "overwrite": {
                        "type": "boolean",
                        "description": "preview 可选。是否允许覆盖已有文件。默认 false。",
                    },
                    "reason": {
                        "type": "string",
                        "description": "preview 可选。操作理由。",
                    },
                    "max_preview_chars": {
                        "type": "integer",
                        "description": "preview 可选。content_preview 截断字符数。默认 200，最小 1，最大 5000。",
                    },
                    "allowed_files": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "preview 可选。自动写入 prompt front matter 的 allowed_files。",
                    },
                    "acceptance_commands": {
                        "type": "array",
                        "items": {
                            "oneOf": [
                                {"type": "string"},
                                {
                                    "type": "object",
                                    "properties": {
                                        "command": {"type": "string"},
                                        "timeout_seconds": {"type": "integer"},
                                        "continue_on_failure": {"type": "boolean"},
                                    },
                                    "required": ["command"],
                                    "additionalProperties": False,
                                },
                            ],
                        },
                        "description": "preview 可选。自动写入 prompt front matter 的 acceptance_commands。",
                    },
                    "allow_no_changes": {
                        "type": "boolean",
                        "description": "preview 可选。自动写入 prompt front matter；read-only/audit 版本可在验收通过且无 allowed_files diff 时通过。",
                    },
                    "execution": {
                        "type": "object",
                        "properties": {
                            "provider": {
                                "type": "string",
                                "enum": ["pi", "codex", "opencode"],
                                "description": "执行器 provider。",
                            },
                        },
                        "additionalProperties": False,
                        "description": "preview 可选。自动写入 prompt front matter 的 execution 配置。",
                    },
                    "project_name": {
                        "type": "string",
                        "description": "可选。按已登记 managed project_name 路由 prompt preview/apply/status/discard。",
                    },
                },
                "required": ["action"],
                "additionalProperties": False,
            },
            output_schema=common_output_schema,
        ),
        MCPToolDef(
            name="get_version_result",
            description="读取指定版本或当前版本结果",
            input_schema={
                "type": "object",
                "properties": {
                    "version": {
                        "type": "string",
                        "description": "Version to inspect. Omit this field to inspect the current version.",
                    }
                },
                "required": [],
                "additionalProperties": False,
            },
            output_schema=common_output_schema,
        ),
        MCPToolDef(
            name="get_next_version_plan",
            description="读取下一版本计划",
            input_schema={
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
            output_schema=common_output_schema,
        ),
        MCPToolDef(
            name="get_plan_overview",
            description=f"[{owner.project_hint}] 读取计划概览",
            input_schema={
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
            output_schema=common_output_schema,
        ),
        MCPToolDef(
            name="get_project_doc_section",
            description="读取项目白名单文档中指定 heading 的段落内容。",
            input_schema={
                "type": "object",
                "properties": {
                    "file": {
                        "type": "string",
                        "description": "Relative project document path, for example docs/Prompt.md.",
                    },
                    "heading": {
                        "type": "string",
                        "description": "Markdown heading or version label to extract, for example v1.1.",
                    },
                    "max_chars": {
                        "type": "integer",
                        "description": "Maximum characters to return. Defaults to 12000. Maximum 30000.",
                    },
                },
                "required": ["file", "heading"],
                "additionalProperties": False,
            },
            output_schema=common_output_schema,
        ),
        MCPToolDef(
            name="preview_insert_version",
            description="Preview insertion of a new version into the Runner plan. The spec_json string must be a JSON object with fields: insert_after, version, name, description, prompt, allowed_files, acceptance_commands, and optional manual_acceptance, out_of_scope, context_files. This only creates a pending patch and does not modify plan.json.",
            input_schema={
                "type": "object",
                "properties": {
                    "spec_json": {
                        "type": "string",
                        "description": "JSON string for the version insertion spec. It must include insert_after, version, name, description, prompt, allowed_files, and acceptance_commands.",
                    }
                },
                "required": ["spec_json"],
                "additionalProperties": False,
            },
            output_schema=common_output_schema,
        ),
        MCPToolDef(
            name="preview_update_version",
            description="Preview update of an existing Runner version. The spec_json string must be a JSON object with version and at least one update field such as prompt, description, allowed_files, acceptance_commands, manual_acceptance, out_of_scope, context_files, or execution. This only creates a pending patch and does not modify plan.json.",
            input_schema={
                "type": "object",
                "properties": {
                    "spec_json": {
                        "type": "string",
                        "description": "JSON string for the version update spec. It must include version and at least one update field such as prompt, description, allowed_files, acceptance_commands, manual_acceptance, out_of_scope, context_files, or execution.",
                    }
                },
                "required": ["spec_json"],
                "additionalProperties": False,
            },
            output_schema=common_output_schema,
        ),
        MCPToolDef(
            name="get_plan_patch_status",
            description="查询 patch 状态",
            input_schema={
                "type": "object",
                "properties": {"patch_id": {"type": "string"}},
                "required": ["patch_id"],
                "additionalProperties": False,
            },
            output_schema=common_output_schema,
        ),
        MCPToolDef(
            name="get_repo_overview",
            description=f"[{owner.project_hint}] 读取受控仓库概览，包括 git 状态、最近提交和安全过滤后的文件树。",
            input_schema={
                "type": "object",
                "properties": {
                    "project_name": {
                        "type": "string",
                        "description": "可选。按已登记 project_name 路由读取目标项目仓库概览。",
                    },
                    "max_depth": {
                        "type": "integer",
                        "description": "Maximum file tree depth. Defaults to 3.",
                    },
                    "max_files": {
                        "type": "integer",
                        "description": "Maximum number of file tree entries. Defaults to 300.",
                    },
                },
                "required": [],
                "additionalProperties": False,
            },
            output_schema=common_output_schema,
        ),
        MCPToolDef(
            name="get_git_status",
            description=f"[{owner.project_hint}] 读取 git status --short。",
            input_schema={
                "type": "object",
                "properties": {
                    "project_name": {
                        "type": "string",
                        "description": "可选。按已登记 project_name 路由读取目标项目 git 状态。",
                    }
                },
                "required": [],
                "additionalProperties": False,
            },
            output_schema=common_output_schema,
        ),
        MCPToolDef(
            name="get_git_log",
            description="读取当前 MCP 绑定项目的最近提交记录，支持按 project_name 路由。",
            input_schema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Maximum commits to return. Defaults to 12 and is capped at 50.",
                    },
                    "project_name": {
                        "type": "string",
                        "description": "可选。按已登记 project_name 路由读取目标项目提交记录。",
                    },
                },
                "required": [],
                "additionalProperties": False,
            },
            output_schema=common_output_schema,
        ),
        MCPToolDef(
            name="get_source_file",
            description="读取当前 MCP 绑定项目白名单源码文件的全文或指定行范围。",
            input_schema={
                "type": "object",
                "properties": {
                    "project_name": {
                        "type": "string",
                        "description": "可选。按已登记 project_name 路由读取目标项目源码文件。",
                    },
                    "file": {
                        "type": "string",
                        "description": "Relative source file path, for example runner/web_console.py.",
                    },
                    "max_chars": {
                        "type": "integer",
                        "description": "Maximum characters to return. Defaults to 30000 and is capped at 100000.",
                    },
                    "start_line": {
                        "type": "integer",
                        "description": "Optional 1-based start line.",
                    },
                    "end_line": {
                        "type": "integer",
                        "description": "Optional 1-based end line.",
                    },
                },
                "required": ["file"],
                "additionalProperties": False,
            },
            output_schema=common_output_schema,
        ),
        MCPToolDef(
            name="search_source",
            description="在当前 MCP 绑定项目的白名单源码文件中搜索关键词。",
            input_schema={
                "type": "object",
                "properties": {
                    "project_name": {
                        "type": "string",
                        "description": "可选。按已登记 project_name 路由搜索目标项目源码。",
                    },
                    "query": {
                        "type": "string",
                        "description": "Search query, 1 to 120 characters.",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum results to return. Defaults to 30 and is capped at 100.",
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            output_schema=common_output_schema,
        ),
        MCPToolDef(
            name="manage_files",
            description=f"[{owner.project_hint}] 统一项目文件搜索、读取与受控编辑工具。action=search 按关键词搜索白名单项目文件；action=read 读取指定文件内容；action=create/edit/delete 受控文件生命周期操作（委托 MCPProjectPatchManager），均需 phase=preview|apply|status。scope：search/read/status=mcp:read，preview=mcp:preview，apply=mcp:commit。",
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["search", "read", "create", "edit", "delete"],
                        "description": "文件操作。search=搜索，read=读取，create=创建，edit=编辑，delete=删除。create/edit/delete 需要 phase=preview|apply|status。",
                    },
                    "phase": {
                        "type": "string",
                        "enum": ["preview", "apply", "status"],
                        "description": "action=create/edit/delete 必填。preview 预览改动（不写文件），apply 应用 preview（写文件），status 查询 preview 状态。",
                    },
                    "project_name": {
                        "type": "string",
                        "description": "可选。按已登记 project_name 路由到目标项目。",
                    },
                    "query": {
                        "type": "string",
                        "description": "action=search 必填。搜索关键词，1 到 120 字符。",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "action=search 可选。最大返回条数。默认 30，最大 100。",
                    },
                    "file": {
                        "type": "string",
                        "description": "action=read 或 action=create/edit/delete 必填。相对文件路径，例如 runner/web_console.py。",
                    },
                    "max_chars": {
                        "type": "integer",
                        "description": "action=read 可选。最大返回字符数。默认 30000，最大 100000；大结果会返回安全分页续读建议。",
                    },
                    "start_line": {
                        "type": "integer",
                        "description": "action=read 可选。1-based 起始行号。",
                    },
                    "end_line": {
                        "type": "integer",
                        "description": "action=read 可选。1-based 结束行号。",
                    },
                    "old_text": {
                        "type": "string",
                        "description": "action=edit phase=preview 精确替换模式的旧文本。必须在文件中唯一。",
                    },
                    "new_text": {
                        "type": "string",
                        "description": "action=create/edit phase=preview 精确替换模式的新文本。create 时写入完整文件内容，edit 时替换 old_text。可以为空字符串。",
                    },
                    "patch_text": {
                        "type": "string",
                        "description": "action=edit phase=preview unified diff 模式的 patch 文本。",
                    },
                    "preview_id": {
                        "type": "string",
                        "description": "action=create/edit/delete phase=apply 或 phase=status 需要。来自 preview 操作返回的 preview_id。",
                    },
                    "reason": {
                        "type": "string",
                        "description": "action=create/edit/delete 可选。改动理由说明。",
                    },
                    "max_files": {
                        "type": "integer",
                        "description": "action=edit phase=preview 可选。最大文件数。默认 5，最大 5。",
                    },
                    "max_diff_chars": {
                        "type": "integer",
                        "description": "action=create/edit/delete phase=preview 可选。最大 diff 字符数。默认 20000，最大 20000。",
                    },
                },
                "required": ["action"],
                "additionalProperties": False,
            },
            output_schema=common_output_schema,
        ),
        MCPToolDef(
            name="get_git_diff",
            description=f"[{owner.project_hint}] 读取 git diff，用于审查工作区改动。只返回白名单源码文件的 diff，过滤虚拟环境、本地运行态和敏感文件。",
            input_schema={
                "type": "object",
                "properties": {
                    "mode": {
                        "type": "string",
                        "enum": ["diff", "summary", "file", "files", "page"],
                        "description": "可选。diff=默认聚合，summary=只返回 diff map，file=单文件，files=指定文件集合，page=单文件分页。",
                    },
                    "file": {
                        "type": "string",
                        "description": "可选。file/page 模式读取单个白名单源码文件 diff。",
                    },
                    "include_files": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "可选。files 模式读取指定文件集合。",
                    },
                    "offset": {
                        "type": "integer",
                        "description": "可选。file/page 模式分页偏移量，默认 0。",
                    },
                    "max_chars": {
                        "type": "integer",
                        "description": "最大字符数。默认 60000，最大 120000。",
                    },
                    "cached": {
                        "type": "boolean",
                        "description": "是否使用 --cached 查看暂存区 diff。默认 false。",
                    },
                    "project_name": {
                        "type": "string",
                        "description": "可选。按已登记 project_name 路由读取目标项目 diff。多项目环境建议显式指定。",
                    },
                },
                "required": [],
                "additionalProperties": False,
            },
            output_schema=common_output_schema,
        ),
        MCPToolDef(
            name="get_executor_inventory",
            description=f"[{owner.project_hint}] 读取本地已保存的执行器 inventory，不触发探测，不执行任何命令。需要先通过 CLI probe-models 探测。",
            input_schema={
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
            output_schema=common_output_schema,
        ),
        MCPToolDef(
            name="list_executor_run_reports",
            description=f"[{owner.project_hint}] 列出执行器完成报告。每次执行器执行完成后会自动保存结构化报告。支持按已登记 managed project_name 路由读取目标项目报告。只读，scope=mcp:read。",
            input_schema={
                "type": "object",
                "properties": {
                    "project_name": {
                        "type": "string",
                        "description": "可选。按已登记 managed project_name 路由读取目标项目报告列表。",
                    },
                    "version": {
                        "type": "string",
                        "description": "可选版本过滤。",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "最大返回数。默认 10，最大 50。",
                    },
                },
                "required": [],
                "additionalProperties": False,
            },
            output_schema=common_output_schema,
        ),
        MCPToolDef(
            name="get_executor_run_report",
            description=f"[{owner.project_hint}] 读取执行器完成报告的详细内容。支持按已登记 managed project_name 路由读取目标项目报告。只读，scope=mcp:read。",
            input_schema={
                "type": "object",
                "properties": {
                    "project_name": {
                        "type": "string",
                        "description": "可选。按已登记 managed project_name 路由读取目标项目报告详情。",
                    },
                    "version": {
                        "type": "string",
                        "description": "可选版本。简化 latest=true 时可不传。",
                    },
                    "report_id": {
                        "type": "string",
                        "description": "可选报告 ID，由 list_executor_run_reports 返回。",
                    },
                    "latest": {
                        "type": "boolean",
                        "description": "是否返回最新报告。默认 true。",
                    },
                    "include_markdown": {
                        "type": "boolean",
                        "description": "是否包含 markdown 内容。默认 true。",
                    },
                    "max_markdown_chars": {
                        "type": "integer",
                        "description": "最大 markdown 字符数。默认 30000，最大 60000。",
                    },
                },
                "required": [],
                "additionalProperties": False,
            },
            output_schema=common_output_schema,
        ),
        MCPToolDef(
            name="inspect_executor_activity",
            description=f"[{owner.project_hint}] 只读执行器状态/报告查询工具。支持 action：run_status（按 run_id 或 preview_id 查询运行状态）、latest_run_status（返回最近一次运行状态，没有记录时返回 found=false）、list_reports（列出执行器报告，支持 version 过滤和 limit）、get_report（读取指定 report 详情）、get_audit_summary（返回审计包只读摘要，不触发 recheck）。支持按已登记 managed project_name 路由读取目标项目。所有 action 都是只读不操作，scope=mcp:read。",
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["run_status", "latest_run_status", "list_reports", "get_report", "get_audit_summary"],
                        "description": "只读查询 action。",
                    },
                    "project_name": {
                        "type": "string",
                        "description": "可选。按已登记 managed project_name 路由读取目标项目执行器状态或报告。",
                    },
                    "run_id": {
                        "type": "string",
                        "description": "run_status 可选。执行器运行 ID。",
                    },
                    "preview_id": {
                        "type": "string",
                        "description": "run_status 可选。preview ID。",
                    },
                    "version": {
                        "type": "string",
                        "description": "list_reports/get_report/get_audit_summary 可选。版本过滤。",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "list_reports 可选。最大返回数。默认 10，最大 50。",
                    },
                    "report_id": {
                        "type": "string",
                        "description": "get_report 可选。指定 report_id。",
                    },
                    "latest": {
                        "type": "boolean",
                        "description": "get_report 可选。是否返回最新报告。默认 true。",
                    },
                    "include_markdown": {
                        "type": "boolean",
                        "description": "get_report 可选。是否包含 markdown 内容。默认 true。",
                    },
                    "max_report_chars": {
                        "type": "integer",
                        "description": "get_report 可选。最大字符数。默认 30000，最大 60000。",
                    },
                    "section": {
                        "type": "string",
                        "enum": ["summary", "lineage", "scope", "report_excerpt"],
                        "description": "get_audit_summary 可选。审计包 section。默认 summary。",
                    },
                },
                "required": ["action"],
                "additionalProperties": False,
            },
            output_schema=common_output_schema,
        ),
        MCPToolDef(
            name="analyze_project_state",
            description=f"[{owner.project_hint}] 只读项目状态分析工具。一次性返回项目身份、模式、Git、Runner、计划、执行器和报告的聚合状态，以及推荐下一步操作和阻断/警告。适合 ChatGPT 开始工作时先调用此工具全面了解项目状态，而不是手动串多个底层工具。scope=mcp:read。",
            input_schema={
                "type": "object",
                "properties": {
                    "project_name": {
                        "type": "string",
                        "description": "可选。按已登记 project_name 路由读取目标项目分析结果。",
                    },
                    "include_repo_overview": {
                        "type": "boolean",
                        "description": "是否包含仓库概览文件树。默认 false。",
                    },
                    "include_reports": {
                        "type": "boolean",
                        "description": "是否包含执行器运行报告列表。默认 true。",
                    },
                    "provider": {
                        "type": "string",
                        "enum": ["pi", "codex", "opencode"],
                        "description": "可选执行器 provider，用于评估 continuation 决策。",
                    },
                    "max_files": {
                        "type": "integer",
                        "description": "仓库概览文件树最大文件数。默认 200，最大 500。",
                    },
                },
                "required": [],
                "additionalProperties": False,
            },
            output_schema=common_output_schema,
        ),
        MCPToolDef(
            name="run_mcp_workflow",
            description=(
                f"[{owner.project_hint}] Bounded Workflow Runner 统一入口。"
                "减少工具选择压力，将常用流程收敛为一个高层入口。"
                "auto_preview（v1.75）：自动分析 goal 并选择 bounded workflow，串联多个 read/preview 步骤，"
                "在 apply/commit/executor-run 边界停止。推荐 ChatGPT 首选入口。"
                "prompt_to_plan（v1.84.58）：串联 prompt 文件保存、plan insert preview、plan patch apply，"
                "停在 executor preflight/run_once_preview 边界。"
                "thin_governed_loop_preview：Stage 0-6 薄治理闭环只读预览，"
                "可接收 external taskbook / execution envelope / local receipt / review feedback 对象，"
                "draft 模式会直接返回 M0-M2 本地 Codex 可执行包 codex_execution_packet，"
                "不产生执行、ReviewDecision、GateEvent 或 Delivery State 变更。"
                "project_delivery_preview：验证已 ACCEPT 的 Thin Loop handoff，并只读投影当前 Git delivery facts 与首个安全动作。"
                "github_delivery：对已同步的 codex/* branch 执行 Draft PR admission，并只读观察 exact-head CI/review/base readiness；最终 merge authority 保持 external。"
                "stage_7_9_preview：把 Stage 7 drift evidence、Stage 8 PLAN_ADJUST preview 与 Stage 9 "
                "continue-readiness report 组合为一条 hash/context-bound 的只读旅程；它只指出下一项人工决策，"
                "不 apply plan、不 continue、不启动 executor。"
                "review_manifest：把独立审查输入严格绑定到 project/branch/HEAD/Runner plan/current version/"
                "review unit/intent 与 subject SHA-256；ChatGPT 通过 typed read 分页读取，标准资源读取仅供支持它的 MCP 客户端使用，绝不开放任意文件读取。"
                "result_artifact：通过同一 artifact_id 的只读分页读取已打包工具结果；不开放任意资源或项目文件读取。"
                "gate_review_request：复用 Work Item Gate 后端执行 inspect/status/preview/apply，"
                "apply 必须回传完整签名预览、精确绑定参数并显式确认。"
                "支持 workflow：auto_preview、project_status、source_onboarding、plan_update、"
                "small_project_patch、docs_update、git_commit、git_restore_file、git_revert、git_undo_version、agent_dispatch、prompt_to_plan、thin_governed_loop_preview、project_delivery_preview、github_delivery、stage_7_9_preview、current_facts、review_manifest、gate_review_request、operator_batch。"
                "写入类默认停 preview；prompt_to_plan/run 只有在显式确认绑定 preview 后才启动 executor。"
                "operator_batch execute 只执行已由 canonical manifest、artifact digest 和一次性 ticket 绑定的受控步骤；"
                "不允许 push、发布、stable replacement 或未列入 allowlist 的操作。"
                "commit 只确认已有受控预览(preview_id)，不执行任意 shell，不 git add .，不绕过 preview。"
                "没有匹配的 stored preview_id 不能创建 commit。"
                "git_revert 不自动 commit。"
                "scope 按 workflow/phase 动态映射。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "workflow": {
                        "type": "string",
                        "enum": [
                            "auto_preview", "project_status", "source_onboarding",
                            "plan_update", "small_project_patch", "docs_update",
                            "git_commit", "git_restore_file", "git_revert", "git_undo_version",
                            "agent_dispatch", "prompt_to_plan", "thin_governed_loop_preview", "project_delivery_preview", "github_delivery", "stage_7_9_preview", "current_facts",
                            "review_manifest", "result_artifact", "gate_review_request", "operator_batch",
                        ],
                        "description": "要执行的工作流。auto_preview 是 v1.75 首选高层入口，自动分析 goal 并选择 bounded workflow。prompt_to_plan 是 v1.84.58 prompt 文件到 plan apply 链路入口。thin_governed_loop_preview 是 Stage 0-6 只读薄治理闭环预览。project_delivery_preview 验证同进程中已 ACCEPT 的 Thin Loop，并只读返回 Git delivery facts 与一个安全下一动作。stage_7_9_preview 是 Stage 7 drift evidence → Stage 8 PLAN_ADJUST preview → Stage 9 continue-readiness 的 hash/context-bound 只读 journey；只生成 next-human-decision，不 apply、不 continue、不启动 executor。current_facts 从 canonical_project_state 生成脱敏、可分页的当前事实 snapshot；inspect 只读，preview → context-bound apply 才能写入固定 runtime archive。review_manifest 建立哈希和上下文绑定的独立审查读取会话。result_artifact 只读取 packaged response 已返回的短期 opaque artifact 分页；它是旧客户端的兼容入口，ChatGPT 优先使用 read_result_artifact。gate_review_request 是复用 Work Item Gate 的受控 Gate review 入口。",
                    },
                    "phase": {
                        "type": "string",
                        "enum": ["inspect", "read", "verify", "preview", "apply", "plan_preview", "plan_apply", "apply_all", "run_preview", "run", "commit", "execute", "status", "pr_status", "pr_preview", "pr_apply", "merge_status"],
                        "description": "工作流阶段。inspect/read/status/verify 只读；stage_7_9_preview 只支持 inspect（返回冻结 taskbook/hash/input template 与 stage_7_9_context）和 preview（必须回传该 context 与三段 Stage 输入，输出只读 next-human-decision），其他 phase 一律拒绝；current_facts 的 inspect 创建可恢复 artifact，preview 不写入，apply 必须同时携带同一 preview_id 和匹配 context_binding 才能写入固定 `.colameta/reports/current-facts/` runtime archive；review_manifest 的 inspect 建立受控阅读会话，read 仅返回一个已声明 subject 的已绑定页并重新核对上下文和该 subject hash，verify 重新核对当前上下文和所有 subject hash；result_artifact 只支持 read，按已有 artifact_id 和 artifact_page 返回一页并保留同一 SHA-256/expiry 合同；preview/run_preview/plan_preview 只生成预览；普通 apply/commit/run/plan_apply/apply_all 只确认受控预览 ID。operator_batch execute 可执行一次性 ticket 中绑定的受控 manifest，但不允许 push、发布或 stable replacement。prompt_to_plan 推荐主流程：preview → apply_all → run_preview → run。旧 phase apply/plan_preview/plan_apply 仍保留兼容。apply_all 一键完成 prompt 保存 + plan 登记。run_preview 生成执行器运行预览，不运行执行器。run 使用 run_preview 返回的 preview_id 执行一次执行器。",
                    },
                    "preview_id": {
                        "type": "string",
                        "description": "apply/commit/run 阶段必填。prompt_to_plan apply_all 使用 prompt preview_id（来自 prompt_to_plan preview）；prompt_to_plan run 使用 executor run_once_preview 返回的 preview_id；current_facts apply 使用 current_facts preview 返回的 preview_id。没有匹配的 stored preview 不执行任何写入或提交。不能用 preview_id 绕过安全检查。",
                    },
                    "preview_digest": {
                        "type": "string",
                        "pattern": "^[0-9a-f]{64}$",
                        "description": "github_delivery pr_apply 必须原样回传 pr_preview 返回的 canonical SHA-256 digest。",
                    },
                    "work_item_id": {
                        "type": "string",
                        "maxLength": GATE_REVIEW_MAX_BINDING_ID_CHARS,
                        "description": "gate_review_request inspect/status/preview/apply 的 Work Item ID。",
                    },
                    "task_version": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "gate_review_request preview/apply 的任务版本，必须与签名预览一致。",
                    },
                    "target_state": {
                        "type": "string",
                        "enum": ["proposed", "ready", "in_delivery", "submitted", "accepted", "cancelled"],
                        "description": "gate_review_request preview/apply 的目标 Work Item 状态。",
                    },
                    "expected_state_version": {
                        "type": "integer",
                        "minimum": 0,
                        "description": "gate_review_request preview/apply 的乐观锁状态版本。",
                    },
                    "decision_ids": {
                        "type": "array",
                        "maxItems": GATE_REVIEW_MAX_BINDING_IDS_PER_FIELD,
                        "items": {
                            "type": "string",
                            "maxLength": GATE_REVIEW_MAX_BINDING_ID_CHARS,
                        },
                        "description": "gate_review_request 绑定的 ReviewDecision ID 列表。",
                    },
                    "evidence_artifact_ids": {
                        "type": "array",
                        "maxItems": GATE_REVIEW_MAX_BINDING_IDS_PER_FIELD,
                        "items": {
                            "type": "string",
                            "maxLength": GATE_REVIEW_MAX_BINDING_ID_CHARS,
                        },
                        "description": "gate_review_request 绑定的证据 artifact ID 列表。",
                    },
                    "idempotency_key": {
                        "type": "string",
                        "maxLength": GATE_REVIEW_MAX_BINDING_ID_CHARS,
                        "description": "gate_review_request 可选幂等键。",
                    },
                    "ttl_seconds": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 900,
                        "description": "gate_review_request preview 可选签名预览有效期。",
                    },
                    "gate_preview": {
                        "type": "object",
                        "additionalProperties": True,
                        "description": "仅供兼容的本地 apply 输入；公开 preview 不返回完整签名对象。",
                    },
                    "gate_preview_id": {
                        "type": "string",
                        "maxLength": GATE_REVIEW_MAX_BINDING_ID_CHARS,
                        "description": "gate_review_request preview 返回的进程内 opaque continuation handle。",
                    },
                    "confirm_gate_review": {
                        "type": "boolean",
                        "description": "gate_review_request apply 必须显式为 true。",
                    },
                    "batch_preview_id": {
                        "type": "string",
                        "description": "operator_batch execute/status 使用的一次性 batch ticket id。",
                    },
                    "manifest_digest": {
                        "type": "string",
                        "description": "operator_batch execute 必须原样回传的 canonical manifest SHA-256。",
                    },
                    "operations": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 16,
                        "items": {
                            "type": "object",
                            "properties": {
                                "step_id": {"type": "string"},
                                "tool": {
                                    "type": "string",
                                    "enum": ["run_mcp_workflow", "manage_validation_run", "manage_git"],
                                },
                                "params": {"type": "object", "additionalProperties": True},
                            },
                            "required": ["step_id", "tool", "params"],
                            "additionalProperties": False,
                        },
                        "description": "operator_batch preview 的有序、精确操作清单；execute 不得重传。",
                    },
                    "patch_id": {
                        "type": "string",
                        "description": "agent_dispatch apply 可选，prompt_to_plan plan_apply 使用 patch_id。apply_all 内部生成并使用 patch_id，但用户不传 patch_id。",
                    },
                    "commit": {
                        "type": "string",
                        "description": "撤销目标 commit ref。git_undo_version preview 阶段必填，其他 workflow 可选。",
                    },
                    "file": {
                        "type": "string",
                        "description": "要恢复的文件路径。git_undo_version 可选，恢复单文件时使用。",
                    },
                    "reason": {
                        "type": "string",
                        "description": "操作理由，进入 workflow record。",
                    },
                    "max_chars": {
                        "type": "integer",
                        "description": "输出字符限制。",
                    },
                    "max_files": {
                        "type": "integer",
                        "description": "最大文件数。",
                    },
                    "include_diff_summary": {
                        "type": "boolean",
                        "description": "是否包含 diff 摘要。",
                    },
                    "max_diff_chars": {
                        "type": "integer",
                        "description": "最大 diff 字符数。",
                    },
                    "project_name": {
                        "type": "string",
                        "description": "可选。service mode 下项目级 workflow 必须传入已登记 project_name。project_status inspect、plan_update、prompt_to_plan、small_project_patch、thin_governed_loop_preview、stage_7_9_preview、gate_review_request 支持按 project_name 路由；stage_7_9_preview 是只读 route，不要求 managed mode。source-onboarding 仍将该字段用作 onboarding 项目名称。",
                    },
                    "context_binding": _operation_context_binding_input_schema(),
                    "goal": {
                        "type": "string",
                        "description": "source_onboarding 项目目标。",
                    },
                    "provider": {
                        "type": "string",
                        "enum": ["pi", "codex", "opencode"],
                        "description": "auto_preview 可选。执行器 provider，用于 executor preflight 和 continuation 决策。",
                    },
                    "first_version": {
                        "type": "string",
                        "description": "source_onboarding 首版本号。",
                    },
                    "first_version_name": {
                        "type": "string",
                        "description": "source_onboarding 首版本显示名称。",
                    },
                    "dry_run": {
                        "type": "boolean",
                        "description": "source_onboarding 是否 dry_run。",
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["repair", "extend"],
                        "description": "plan_update 模式。",
                    },
                    "version": {
                        "type": "string",
                        "description": "plan_update 版本号。",
                    },
                    "target_version": {
                        "type": "string",
                        "description": "plan_update 目标版本号（repair）。",
                    },
                    "insert_after": {
                        "type": "string",
                        "description": "plan_update extend 插入位置。",
                    },
                    "name": {
                        "type": "string",
                        "description": "plan_update extend 版本名称。",
                    },
                    "description": {
                        "type": "string",
                        "description": "plan_update extend 版本描述。",
                    },
                    "prompt": {
                        "type": "string",
                        "description": "plan_update extend 版本 prompt。",
                    },
                    "user_request": {
                        "type": "string",
                        "description": "agent_dispatch preview 或 plan_update extend preview 的用户需求文本。",
                    },
                    "allowed_files": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "agent_dispatch preview 或 plan_update extend preview 的显式 allowed_files。",
                    },
                    "forbidden_files": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "agent_dispatch preview 或 plan_update extend preview 的显式 forbidden_files。",
                    },
                    "acceptance_commands": {
                        "type": "array",
                        "items": {
                            "oneOf": [
                                {"type": "string"},
                                {
                                    "type": "object",
                                    "properties": {
                                        "command": {"type": "string"},
                                        "timeout_seconds": {"type": "integer"},
                                        "continue_on_failure": {"type": "boolean"},
                                    },
                                    "required": ["command"],
                                    "additionalProperties": True,
                                },
                            ],
                        },
                        "description": "agent_dispatch preview 或 plan_update extend preview 的显式 acceptance_commands。",
                    },
                    "manual_acceptance": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "agent_dispatch preview 或 plan_update extend preview 的显式 manual_acceptance。",
                    },
                    "out_of_scope": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "agent_dispatch preview 或 plan_update extend preview 的显式 out_of_scope。",
                    },
                    "context_files": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "agent_dispatch preview 或 plan_update extend preview 的显式 context_files。",
                    },
                    "repair_kinds": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "plan_update repair 指定修复类型。",
                    },
                    "file": {
                        "type": "string",
                        "description": "small_project_patch / git_restore_file 文件路径。",
                    },
                    "old_text": {
                        "type": "string",
                        "description": "small_project_patch 旧文本。",
                    },
                    "new_text": {
                        "type": "string",
                        "description": "small_project_patch 新文本。",
                    },
                    "patch_text": {
                        "type": "string",
                        "description": "small_project_patch unified diff 文本。",
                    },
                    "docs_action": {
                        "type": "string",
                        "enum": ["index", "search", "read_section", "update_section_preview", "append_section_preview", "sync_docs_preview", "apply"],
                        "description": "docs_update 动作。",
                    },
                    "heading": {
                        "type": "string",
                        "description": "docs_update 文档 heading。",
                    },
                    "query": {
                        "type": "string",
                        "description": "docs_update 搜索关键词。",
                    },
                    "section_heading": {
                        "type": "string",
                        "description": "docs_update 新 section heading。",
                    },
                    "new_content": {
                        "type": "string",
                        "description": "docs_update 更新后的 section 内容。",
                    },
                    "section_content": {
                        "type": "string",
                        "description": "docs_update 新 section 内容。",
                    },
                    "after_heading": {
                        "type": "string",
                        "description": "docs_update 指定追加位置。",
                    },
                    "stale_terms": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "docs_update 过时术语列表。",
                    },
                    "message": {
                        "type": "string",
                        "description": "git_commit commit message。",
                    },
                    "style": {
                        "type": "string",
                        "enum": ["conventional", "runner_version", "concise"],
                        "description": "git_commit commit message 风格。",
                    },
                    "scope_hint": {
                        "type": "string",
                        "description": "git_commit 版本号或 scope 提示。",
                    },
                    "commit": {
                        "type": "string",
                        "description": "git_restore_file / git_revert commit ref。",
                    },
                    "content": {
                        "type": "string",
                        "description": "prompt_to_plan preview 必填。prompt 文本内容。",
                    },
                    "overwrite": {
                        "type": "boolean",
                        "description": "prompt_to_plan preview 可选。是否覆盖已存在的 prompt 文件。默认 false。",
                    },
                    "prompt_file": {
                        "type": "string",
                        "description": "prompt_to_plan plan_preview 必填。prompt 文件名，例如 v1.84.58.md。只接受文件名，不接受路径。",
                    },
                    "input_mode": {
                        "type": "string",
                        "enum": ["example", "template", "draft", "provided"],
                        "description": "thin_governed_loop_preview 可选。example 使用内置样例；template 只返回真实输入契约和最小请求形状；draft 生成可编辑的四对象输入包但不执行闭环；provided 要求同时提供 external_taskbook_claim、execution_envelope、local_execution_receipt、review_feedback。",
                    },
                    "thin_loop_inputs": {
                        "type": "object",
                        "description": "thin_governed_loop_preview 可选。真实输入对象包；可包含 external_taskbook_claim、execution_envelope、local_execution_receipt、review_feedback、current_head；draft 模式也可在此携带 draft_seed。",
                        "additionalProperties": True,
                    },
                    "draft_seed": {
                        "type": "object",
                        "description": "thin_governed_loop_preview draft 模式可选。用少量上游字段生成四对象输入包和 Codex 可执行包，例如 goal/objective、task_tier、allowed_files、forbidden_files、context_files、validation_commands、allowed_commands、review_decision_value、reviewer_notes。",
                        "additionalProperties": True,
                    },
                    "external_taskbook_claim": {
                        "type": "object",
                        "description": "thin_governed_loop_preview provided 模式必填。外部任务书声明对象，作为 bounded claim 验证。",
                        "additionalProperties": True,
                    },
                    "execution_envelope": {
                        "type": "object",
                        "description": "thin_governed_loop_preview provided 模式必填。受控执行 envelope 对象。",
                        "additionalProperties": True,
                    },
                    "local_execution_receipt": {
                        "type": "object",
                        "description": "thin_governed_loop_preview provided 模式必填。本地执行 receipt 对象。",
                        "additionalProperties": True,
                    },
                    "review_feedback": {
                        "type": "object",
                        "description": "thin_governed_loop_preview provided 模式必填。审查反馈对象。",
                        "additionalProperties": True,
                    },
                    "current_head": {
                        "type": "string",
                        "description": "thin_governed_loop_preview 可选。用于 evidence preview 的 HEAD 绑定；不传时读取当前 checkout HEAD。",
                    },
                    "stage_7_9_context": _stage_7_9_context_input_schema(),
                    "stage_7_9_inputs": {
                        "type": "object",
                        "description": "stage_7_9_preview preview 必填。必须精确包含 Stage 7 drift evidence、Stage 8 PLAN_ADJUST preview、Stage 9 continue-readiness 的三个 input object。服务只返回白名单 projection，不回显原始 evidence/runtime payload。",
                        "properties": {
                            "stage_7_drift_evidence_inputs": {
                                "type": "object",
                                "description": "传给 Stage 7 drift evidence builder 的有界 evidence input。",
                                "additionalProperties": True,
                            },
                            "stage_8_plan_adjustment_inputs": {
                                "type": "object",
                                "description": "传给 Stage 8 plan adjustment preview 的显式 PLAN_ADJUST request input。",
                                "additionalProperties": True,
                            },
                            "stage_9_continue_readiness_inputs": {
                                "type": "object",
                                "description": "传给 Stage 9 controlled continue readiness report 的 plan/state/gate/hash input。",
                                "additionalProperties": True,
                            },
                        },
                        "required": [
                            "stage_7_drift_evidence_inputs",
                            "stage_8_plan_adjustment_inputs",
                            "stage_9_continue_readiness_inputs",
                        ],
                        "additionalProperties": False,
                    },
                    "review_manifest": {
                        "type": "object",
                        "description": "review_manifest inspect 可选：省略时只返回当前绑定模板；提供时建立独立审查会话。精确只读合同必须使用 schema_version=colameta.review_manifest.v1，绑定 project_name、branch、head、runner_plan、current_version、review_unit、workflow_intent=independent_review、subjects[{path,sha256}]；可选 acceptance_commands 仅预览，不执行。",
                        "properties": {
                            "schema_version": {"type": "string", "const": REVIEW_MANIFEST_SCHEMA_VERSION},
                            "review_unit": {"type": "string", "maxLength": 160},
                            "workflow_intent": {"type": "string", "const": REVIEW_MANIFEST_WORKFLOW_INTENT},
                            "project_name": {"type": "string", "maxLength": 128},
                            "branch": {"type": "string", "maxLength": 255},
                            "head": {"type": "string", "pattern": "^[0-9a-fA-F]{40,128}$"},
                            "runner_plan": {
                                "type": "object",
                                "properties": {
                                    "mode": {"type": "string", "enum": ["managed", "source-only"]},
                                    "plan_sha256": {"type": ["string", "null"], "pattern": "^[0-9a-fA-F]{64}$"},
                                },
                                "required": ["mode", "plan_sha256"],
                                "additionalProperties": False,
                            },
                            "current_version": {"type": ["string", "null"], "maxLength": 128},
                            "subjects": {
                                "type": "array",
                                "minItems": 1,
                                "maxItems": 64,
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "path": {"type": "string"},
                                        "sha256": {"type": "string", "pattern": "^[0-9a-fA-F]{64}$"},
                                    },
                                    "required": ["path", "sha256"],
                                    "additionalProperties": False,
                                },
                            },
                            "acceptance_commands": {
                                "type": "array",
                                "maxItems": 32,
                                "items": {
                                    "oneOf": [
                                        {"type": "string", "maxLength": 2000},
                                        {
                                            "type": "object",
                                            "properties": {
                                                "command": {"type": "string", "maxLength": 2000},
                                                "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 3600},
                                                "continue_on_failure": {"type": "boolean"},
                                            },
                                            "required": ["command"],
                                            "additionalProperties": False,
                                        },
                                    ],
                                },
                            },
                        },
                        "required": [
                            "schema_version", "review_unit", "workflow_intent", "project_name",
                            "branch", "head", "runner_plan", "current_version", "subjects",
                        ],
                        "additionalProperties": False,
                    },
                    "review_manifest_id": {
                        "type": "string",
                        "description": "review_manifest read/verify/status 必填。来自 inspect 的短期只读审查会话 ID；也可交给 manage_validation_run action=preview，令同一会话声明的 acceptance_commands 生成独立的受控 validation preview；不能用于读未声明文件或直接授权写入。",
                    },
                    "review_manifest_subject_index": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "review_manifest read 必填。只能使用 inspect 返回的 subjects[].subject_index，不能改写为任意路径。",
                    },
                    "review_manifest_page": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "review_manifest read 可选。默认 1；不能超过 inspect 返回的 subject page_count。",
                    },
                    "artifact_id": {
                        "type": "string",
                        "pattern": "^[A-Za-z0-9_-]{16,128}$",
                        "description": "result_artifact read 必填。只能使用 packaged=true 响应返回的 opaque artifact_id；不是项目文件、Git object 或 Delivery evidence ID。",
                    },
                    "artifact_page": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "result_artifact read 可选。默认 1；只能读取该 artifact 的有效页码。",
                    },
                },
                "required": ["workflow"],
                "additionalProperties": False,
            },
            output_schema=common_output_schema,
        ),
        MCPToolDef(
            name="review_manifest",
            title="Review Manifest",
            description=(
                f"[{owner.project_hint}] Use this when ChatGPT needs to perform a hash-bound, "
                "independent review of explicitly declared project files. "
                "inspect returns the exact manifest template or opens a short-lived review session; "
                "read returns one declared subject page only; verify rechecks the project context and every subject hash. "
                "It never reads an arbitrary file, executes acceptance commands, starts an executor, or writes a review decision. "
                "scope=mcp:read。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "phase": {
                        "type": "string",
                        "enum": ["inspect", "read", "verify", "status"],
                        "description": "可选。默认 inspect；inspect 建立只读会话，read 读取一页已声明 subject，verify 复核全部绑定。",
                    },
                    "project_name": {
                        "type": "string",
                        "description": "可选。服务模式下指定已登记 managed project；manifest 内的 project_name 必须与其匹配。",
                    },
                    "review_manifest": {
                        "type": "object",
                        "description": "仅 phase=inspect 且要建立会话时提供。先调用不带它的 inspect 获取模板；随后原样填充 schema_version、review_unit、workflow_intent、project_name、branch、head、runner_plan、current_version、subjects[{path,sha256}]，以及可选 acceptance_commands。服务端严格校验，不能扩展为任意文件读取。",
                        "additionalProperties": True,
                    },
                    "review_manifest_id": {
                        "type": "string",
                        "description": "read、verify、status 必填；来自 inspect 返回的短期 opaque 会话 ID。",
                    },
                    "review_manifest_subject_index": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "read 必填；必须使用 inspect 返回的 subject_index。",
                    },
                    "review_manifest_page": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "read 可选，默认 1；仅限 inspect 返回的 page_count 范围。",
                    },
                },
                "required": [],
                "additionalProperties": False,
            },
            output_schema=common_output_schema,
            annotations={
                "readOnlyHint": True,
                "destructiveHint": False,
                "openWorldHint": False,
                "idempotentHint": True,
            },
        ),
        MCPToolDef(
            name="read_result_artifact",
            title="Read Result Artifact Page",
            description=(
                f"[{owner.project_hint}] Use this when a previous tool response was packaged because it was too large, "
                "including in ChatGPT. "
                "Reads exactly one page from the same short-lived opaque artifact and returns its stable SHA-256 and expiry; "
                "it cannot enumerate artifacts, read project files, or perform a side effect. scope=mcp:read。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "artifact_id": {
                        "type": "string",
                        "pattern": "^[A-Za-z0-9_-]{16,128}$",
                        "description": "必填。只能使用 packaged response 返回的 opaque artifact_id。",
                    },
                    "artifact_page": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "可选，默认 1；使用同一 artifact 的有效页码。",
                    },
                },
                "required": ["artifact_id"],
                "additionalProperties": False,
            },
            output_schema=common_output_schema,
            annotations={
                "readOnlyHint": True,
                "destructiveHint": False,
                "openWorldHint": False,
                "idempotentHint": True,
            },
        ),
        MCPToolDef(
            name="manage_executor_config",
            description=(
                f"[{owner.project_hint}] 受控执行器配置管理工具。支持 action："
                "inspect_inventory（只读，返回安全的 inventory 摘要，不暴露 token/api_key/Bearer/secret）；"
                "probe_models_preview（生成 preview_id，不探测执行器）；"
                "probe_models_apply（基于 preview_id 执行受控探测，执行 probe_executor_inventory，"
                "验证 project_root/expiry/provider 一致性）；"
                "set_default_profile_preview / set_default_profile_apply（受控设置项目本地 executor profile）。"
                "provider 可选，必须是 codex、opencode 或 pi；model/reasoning_effort 仅用于 profile 设置。"
                "不执行任意 shell 命令，不写 token，不安装模型，不修改登录态。"
                "scope：inspect_inventory=mcp:read，probe_models_preview/set_default_profile_preview=mcp:preview，"
                "probe_models_apply/set_default_profile_apply=mcp:commit。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "inspect_inventory",
                            "probe_models_preview",
                            "probe_models_apply",
                            "set_default_profile_preview",
                            "set_default_profile_apply",
                        ],
                        "description": "执行器配置管理 action。",
                    },
                    "provider": {
                        "type": "string",
                        "enum": ["codex", "opencode", "pi"],
                        "description": "可选。执行器 provider 过滤或 profile provider。不传时返回所有 provider。",
                    },
                    "model": {
                        "type": "string",
                        "description": "set_default_profile_preview 可选。项目本地 executor profile 的模型名，例如 opencode/deepseek-v4-flash-free。",
                    },
                    "reasoning_effort": {
                        "type": "string",
                        "description": "set_default_profile_preview 可选。项目本地 executor profile 的 reasoning effort。",
                    },
                    "preview_id": {
                        "type": "string",
                        "description": "probe_models_apply 或 set_default_profile_apply 必填。来自对应 preview 的 preview_id。",
                    },
                    "project_name": {
                        "type": "string",
                        "description": "可选。按已登记 managed project_name 路由项目本地 executor profile 和受控 preview/apply。",
                    },
                },
                "required": ["action"],
                "additionalProperties": False,
            },
            output_schema=common_output_schema,
        ),
        MCPToolDef(
            name="manage_executor_workflow",
            description=(
                f"[{owner.project_hint}] 受控执行器工作流工具。支持以下 action："
                "preflight（只读预检，检查项目与执行器就绪状态）；"
                "run_once_preview（生成 preview_id，不执行执行器）；"
                "run_once（异步执行，需要来自 run_once_preview 的 preview_id。快速返回 started/running 状态，后台执行。完成后通过 status run_id 或 preview_id 轮询获取结果。不循环，不自动修复，不自动提交）；"
                "run_bounded_preview（只做预检并生成 bounded loop preview，不执行执行器）；"
                "run_bounded（基于 run_bounded_preview 的 preview_id 执行 bounded loop，受 max_iterations 限制）；"
                "get_audit_package（读取执行审计包的轻量摘要与lineage）；"
                "refresh_audit_package（按 version 生成新的版本审计包 refresh 快照）；"
                "recheck_report_preview（只读重审旧 report 的 scope 结论，生成状态刷新 preview）；"
                "recheck_report_apply（基于 recheck_report_preview 的 preview_id 刷新目标 version 的 state 状态）；"
                "manual_fix_prompt_preview（为当前 blocked/failure 版本生成手动修复提示词准备 preview）；"
                "manual_fix_prompt_apply（基于 manual_fix_prompt_preview 的 preview_id 写入 current-fix-prompt.md 并把当前版本置为 FIX_PROMPT_READY）；"
                "manual_validation_preview（基于已通过的 manage_validation_run 记录生成手动验收通过 state 刷新 preview）；"
                "manual_validation_apply（基于 manual_validation_preview 的 preview_id 登记手动/等价验收通过，不改 executor report）；"
                "scope_mismatch_preview（只读输出授权范围与实际 changed_files 的通用差异诊断，生成 resolution preview，不改 state/report/audit/Git）；"
                "scope_mismatch_apply（基于 scope_mismatch_preview 的 preview_id 执行受控 resolution 状态落盘，不改 report/Git）；"
                "state_lineage_reconciliation_preview（基于人工受控完成证据生成 Runner state lineage 对账 preview）；"
                "state_lineage_reconciliation_apply（基于 state_lineage_reconciliation_preview 的 preview_id 受控写入 state lineage 对账结果）；"
                "final_version_closeout_preview（基于最后一个版本的人工 closeout 证据生成 Runner state 完成 preview）；"
                "final_version_closeout_apply（基于 final_version_closeout_preview 的 preview_id 受控写入最后一个版本完成状态）；"
                "reconcile_orphaned_claims_preview（只读扫描 RUNNING claim 并生成失联 claim reconcile preview，不改 runtime）；"
                "reconcile_orphaned_claims_apply（基于 reconcile_orphaned_claims_preview 的 preview_id 受控终结仍失联的 RUNNING claim，不删除 claim，不杀进程）；"
                "status（查看当前执行器会话状态）。"
                "此工具遵循单项预览/应用审批模式。"
                "project_root 可选，缺省使用 MCP 绑定项目，仅用于显式覆盖。"
                "run_bounded 默认 max_iterations=1，最大 3；max_iterations>1 需要 trusted_mode=true。"
                "不支持无限循环。allow_fix=false 时不执行 fix；allow_fix=true 只允许已有 FIX_PROMPT_READY。"
                "allow_commit 不会执行 commit，只能停在 commit preview/next_action 边界。"
                "run_once/run_bounded 不执行任意 git reset/clean/stash/merge/rebase/push，不创建或切换分支。"
                "status 使用按 profile 分级的有界轮询契约：web_gpt_commander 默认短轮询，local_codex_commander 可更长时间跟进。支持 preview_id/run_id/profile_id 查询。"
                "project_name 支持已登记 managed 项目的所有 action。"
                "scope：preflight/status/get_audit_package=mcp:read，run_once_preview/run_bounded_preview/recheck_report_preview/manual_fix_prompt_preview/manual_validation_preview/scope_mismatch_preview/state_lineage_reconciliation_preview/final_version_closeout_preview/reconcile_orphaned_claims_preview=mcp:preview，run_once/run_bounded/refresh_audit_package/recheck_report_apply/manual_fix_prompt_apply/manual_validation_apply/scope_mismatch_apply/state_lineage_reconciliation_apply/final_version_closeout_apply/reconcile_orphaned_claims_apply=mcp:commit。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["preflight", "run_once_preview", "run_once", "run_bounded_preview", "run_bounded", "get_audit_package", "refresh_audit_package", "recheck_report_preview", "recheck_report_apply", "manual_fix_prompt_preview", "manual_fix_prompt_apply", "manual_validation_preview", "manual_validation_apply", "scope_mismatch_preview", "scope_mismatch_apply", "state_lineage_reconciliation_preview", "state_lineage_reconciliation_apply", "final_version_closeout_preview", "final_version_closeout_apply", "reconcile_orphaned_claims_preview", "reconcile_orphaned_claims_apply", "status"], "description": "执行器工作流操作。"},
                    "project_name": {"type": "string", "description": "可选。按已登记 managed project_name 路由 preflight、run_once_preview、run_once、status。"},
                    "project_root": {"type": "string", "description": "可选。项目根目录路径；不传时使用 MCP 绑定项目。"},
                    "provider": {"type": "string", "enum": ["pi", "codex", "opencode"], "description": "执行器 provider。默认 codex。"},
                    "model": {"type": "string", "description": "run_once_preview/run_once 可选。显式指定本次执行器模型；run_once 必须与对应 preview 中记录的 model 一致。"},
                    "execution_mode": {"type": "string", "enum": ["run", "fix"], "description": "执行模式。run 为正常执行，fix 仅当当前状态为 FIX_PROMPT_READY 时可用。默认 run。"},
                    "preview_id": {"type": "string", "description": "run_once/run_bounded/recheck_report_apply/manual_fix_prompt_apply/manual_validation_apply/scope_mismatch_apply/state_lineage_reconciliation_apply/final_version_closeout_apply/reconcile_orphaned_claims_apply 必填；status 可选。来自对应 preview 的 preview_id。"},
                    "manual_fix_prompt": {"type": "string", "description": "manual_fix_prompt_preview 必填。用户提供的手动修复提示词内容。"},
                    "validation_run_id": {"type": "string", "description": "manual_validation_preview 必填。来自 manage_validation_run run/status 的 validation run ID。"},
                    "resolution": {"type": "string", "enum": ["refresh_in_scope_state", "record_direct_manual_review", "abort_version"], "description": "scope_mismatch_apply 必填。resolution 选项。"},
                    "expected_head": {"type": "string", "description": "state_lineage_reconciliation_preview 必填。期望当前 Git HEAD。"},
                    "expected_branch": {"type": "string", "description": "state_lineage_reconciliation_preview 可选。期望当前分支。"},
                    "target_next_version": {"type": "string", "description": "state_lineage_reconciliation_preview 必填。对账后应成为当前可运行版本的 version。"},
                    "target_version": {"type": "string", "description": "final_version_closeout_preview 必填。要完成 closeout 的最后一个 plan version。"},
                    "accepted_commit": {"type": "string", "description": "final_version_closeout_preview 必填。最后一个版本对应的完整 commit hash。"},
                    "accepted_commit_subject": {"type": "string", "description": "final_version_closeout_preview 必填。accepted_commit 在本地 Git history 中的 subject。"},
                    "commit_files": {"type": "array", "items": {"type": "string"}, "description": "final_version_closeout_preview 可选。记录到版本 runtime 的 commit file 摘要。"},
                    "evidence_refs": {"type": "array", "items": {"type": "string"}, "description": "final_version_closeout_preview 可选。closeout evidence 引用；path:/file:/.colameta/ 开头的本地路径会校验存在。"},
                    "evidence_summary": {"type": "string", "description": "final_version_closeout_preview 可选。当 evidence_refs 不足时提供 closeout evidence 摘要。"},
                    "bindings": {
                        "type": "array",
                        "description": "state_lineage_reconciliation_preview 必填。版本对账绑定列表。",
                        "items": {
                            "type": "object",
                            "additionalProperties": True,
                            "properties": {
                                "version": {"type": "string"},
                                "target_status": {"type": "string"},
                                "accepted_commit": {"type": "string"},
                                "accepted_commit_subject": {"type": "string"},
                                "commit_files": {"type": "array", "items": {"type": "string"}},
                                "evidence_refs": {"type": "array", "items": {"type": "string"}},
                                "evidence_summary": {"type": "string"},
                                "reason": {"type": "string"},
                            },
                        },
                    },
                    "run_id": {"type": "string", "description": "status 可选。执行器运行 ID。"},
                    "profile_id": {"type": "string", "enum": ["web_gpt_commander", "local_codex_commander", "planner_agent", "reviewer_agent", "source_observer"], "description": "status/run_once 可选。用于选择 polling guidance。默认 web_gpt_commander；local_codex_commander 使用更长的本地有界轮询窗口。"},
                    "poll_attempt": {"type": "integer", "description": "status 可选。轮询次数。默认 1；最大建议由 polling_guidance.max_poll_attempts 按 profile 返回。"},
                    "max_diff_chars": {"type": "integer", "default": 40000, "minimum": 1, "maximum": 80000, "description": "run_once 可选。diff 输出字符限制。默认 40000，最大 80000。"},
                    "include_diff_summary": {"type": "boolean", "default": True, "description": "run_once 可选。是否返回 diff_summary。默认 true。"},
                    "include_report_markdown": {"type": "boolean", "default": False, "description": "run_once 可选。是否返回报告 markdown。默认 false。"},
                    "max_report_chars": {"type": "integer", "default": 30000, "minimum": 1, "maximum": 60000, "description": "run_once 可选。报告 markdown 最大字符数。默认 30000，最大 60000。"},
                    "executor_session_mode": {"type": "string", "enum": ["auto", "resume_existing", "start_new"], "default": "auto", "description": "run_once 可选。执行器会话模式：auto（默认）使用自动续接决策；resume_existing 要求续接现有会话；start_new 启动新会话。默认 auto。"},
                    "reason": {"type": "string", "description": "可选。执行理由说明。"},
                    "max_iterations": {"type": "integer", "default": 1, "minimum": 1, "maximum": 3, "description": "run_bounded 可选。循环轮数，默认 1，最小 1，最大 3。"},
                    "trusted_mode": {"type": "boolean", "default": False, "description": "run_bounded 可选。仅 trusted_mode=true 时允许 max_iterations>1。默认 false。"},
                    "stop_on_acceptance_failure": {"type": "boolean", "default": True, "description": "run_bounded 可选。是否在验收失败时停止。默认 true。"},
                    "stop_on_scope_violation": {"type": "boolean", "default": True, "description": "run_bounded 可选。是否在 scope violation 时停止。默认 true。"},
                    "stop_on_diff_too_large": {"type": "boolean", "default": True, "description": "run_bounded 可选。是否在 diff 超阈值时停止。默认 true。"},
                    "max_total_diff_chars": {"type": "integer", "default": 80000, "minimum": 1, "maximum": 200000, "description": "run_bounded 可选。总 diff 字符阈值，默认 80000，最大 200000。"},
                    "allow_fix": {"type": "boolean", "default": False, "description": "run_bounded 可选。默认 false；仅已有 FIX_PROMPT_READY 时允许 fix 轮。"},
                    "allow_commit": {"type": "boolean", "default": False, "description": "run_bounded 可选。默认 false；即使 true 也不会自动 commit。"},
                    "latest": {"type": "boolean", "default": True, "description": "get_audit_package 可选。默认 true。"},
                    "report_id": {"type": "string", "description": "get_audit_package/recheck_report_preview/scope_mismatch_preview 可选。指定 report_id。"},
                    "version": {"type": "string", "description": "get_audit_package/recheck_report_preview/manual_fix_prompt_preview/manual_validation_preview/scope_mismatch_preview/refresh_audit_package 可选。指定 version。"},
                    "section": {"type": "string", "enum": ["summary", "lineage", "validation", "scope", "report_excerpt"], "description": "get_audit_package 可选。默认 summary。"},
                    "include_markdown": {"type": "boolean", "default": False, "description": "get_audit_package 可选。section=report_excerpt 时是否返回 markdown 片段。"},
                    "max_chars": {"type": "integer", "default": 20000, "minimum": 1, "maximum": 60000, "description": "get_audit_package 可选。返回字符上限。"},
                },
                "required": ["action"],
                "additionalProperties": False,
            },
            output_schema=common_output_schema,
        ),
        MCPToolDef(
            name="manage_validation_run",
            description=(
                f"[{owner.project_hint}] 通用受控验证运行工具。"
                "GPTs 只提供 scope/target_files；Runner 本地选择验证策略。"
                "也可在 preview 中提供已 inspect 的 review_manifest_id：先复核其上下文和所有 subject hash，再将其声明的 acceptance_commands 固化为固定 argv。"
                "inspect/status 只读；preview 生成固定 argv，不运行命令；run 只执行 preview 固化命令，shell=False，执行前会再次复核 manifest-bound 输入，输出脱敏截断。"
                "scope：inspect/status=mcp:read，preview=mcp:preview，run=mcp:commit。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["inspect", "preview", "run", "status"],
                        "description": "验证动作。inspect/status 只读；preview 生成固定验证命令；run 使用 preview_id 执行一次。",
                    },
                    "scope": {
                        "type": "string",
                        "enum": ["changed_files", "target_files", "current_version", "full"],
                        "description": "验证范围。默认 changed_files；target_files 使用 target_files；current_version/full 优先运行当前版本 acceptance_commands。",
                    },
                    "target_files": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "可选目标文件列表。只接受项目内相对路径。",
                    },
                    "preview_id": {
                        "type": "string",
                        "description": "run 必填。来自 preview 的 preview_id。",
                    },
                    "review_manifest_id": {
                        "type": "string",
                        "description": "仅 action=preview 可选。来自 run_mcp_workflow review_manifest inspect；会把该短期、哈希绑定会话声明的 acceptance_commands 转为受控 validation preview。不能与 scope/target_files 混用，也不直接授权执行。",
                    },
                    "run_id": {
                        "type": "string",
                        "description": "status 必填。验证运行 ID。",
                    },
                    "project_name": {
                        "type": "string",
                        "description": "可选。按已登记 managed project_name 路由所有操作。",
                    },
                    "context_binding": _operation_context_binding_input_schema(),
                },
                "required": ["action"],
                "additionalProperties": False,
            },
            output_schema=common_output_schema,
        ),
        MCPToolDef(
            name="list_workflow_runs",
            description=f"[{owner.project_hint}] 列出 workflow run records。每次受控 MCP 操作（analyze_project_state、manage_plan_version insert/update/repair preview、manage_project_patch preview/apply、manage_git_history restore/preview/revert、manage_git_commit preview/commit、run_mcp_workflow、manage_executor_workflow）会自动生成 workflow record。返回摘要列表，不包含完整 steps。scope=mcp:read。",
            input_schema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "最大返回条数。默认 20，最大 100。",
                    },
                    "workflow_name": {
                        "type": "string",
                        "description": "按 workflow_name 筛选。",
                    },
                    "status": {
                        "type": "string",
                        "description": "按 status 筛选（running/succeeded/failed/partial/unsupported）。",
                    },
                    "project_name": {
                        "type": "string",
                        "description": "可选。按已登记 managed project_name 路由读取目标项目 workflow records。",
                    },
                },
                "required": [],
                "additionalProperties": False,
            },
            output_schema=common_output_schema,
        ),
        MCPToolDef(
            name="get_workflow_run",
            description=f"[{owner.project_hint}] 查看单个 workflow run record 详情。返回完整 workflow record，包含 steps 数组。scope=mcp:read。",
            input_schema={
                "type": "object",
                "properties": {
                    "workflow_id": {
                        "type": "string",
                        "description": "workflow_id。",
                    },
                    "project_name": {
                        "type": "string",
                        "description": "可选。按已登记 managed project_name 路由读取目标项目 workflow record。",
                    },
                },
                "required": ["workflow_id"],
                "additionalProperties": False,
            },
            output_schema=common_output_schema,
        ),
    ]
