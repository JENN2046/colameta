import json
from pathlib import Path

from jsonschema import Draft202012Validator

from runner.mcp_server import COMMANDER_APP_WIDGET_URI, MCPPlanningBridgeServer, MCPToolDef
from runner.mcp_tool_catalog import (
    MCPToolDef as CatalogMCPToolDef,
    apply_chatgpt_submission_tool_annotations,
    build_mcp_tool_definitions,
    _manage_stage_parallel_executor_group_input_schema,
)
from runner.workflow_records import WorkflowRecordStore


ROOT = Path(__file__).resolve().parents[1]


def test_stage_executor_group_authorization_schema_exposes_only_opaque_handles() -> None:
    schema = _manage_stage_parallel_executor_group_input_schema()
    item = schema["properties"]["task_authorizations"]["items"]
    assert set(item["properties"]) == {"task_id", "grant_id"}
    assert item["required"] == ["task_id", "grant_id"]
    assert item["additionalProperties"] is False
    validator = Draft202012Validator(schema)
    valid = {
        "action": "preview",
        "task_authorizations": [{"task_id": "one", "grant_id": "preview_opaque"}],
    }
    assert list(validator.iter_errors(valid)) == []
    for forbidden in (
        "work_item_id", "task_version", "attempt_id", "artifact_refs",
        "authority_id", "admission_sha256", "branch", "HEAD",
    ):
        malformed = json.loads(json.dumps(valid))
        malformed["task_authorizations"][0][forbidden] = "forbidden"
        assert list(validator.iter_errors(malformed))


def test_server_composes_the_tool_definitions_from_the_standalone_catalog() -> None:
    server = MCPPlanningBridgeServer(str(ROOT))

    catalog = build_mcp_tool_definitions(
        server,
        server._build_common_output_schema(),
        commander_widget_uri=COMMANDER_APP_WIDGET_URI,
    )
    apply_chatgpt_submission_tool_annotations(catalog)

    assert MCPToolDef is CatalogMCPToolDef
    assert catalog == server.tool_defs[: len(catalog)]
    assert {"review_manifest", "read_result_artifact", "run_mcp_workflow"} <= {
        tool.name for tool in catalog
    }


def test_executor_workflow_catalog_schema_requires_exact_fresh_authority_contract() -> None:
    server = MCPPlanningBridgeServer(str(ROOT))
    tool_def = next(
        tool for tool in server.tool_defs if tool.name == "manage_executor_workflow"
    )
    validator = Draft202012Validator(tool_def.input_schema)
    authority_id = "a" * 32
    admission_sha256 = "b" * 64

    assert not list(validator.iter_errors({
        "action": "run_once_preview",
        "executor_session_mode": "start_new",
        "executor_authority_id": authority_id,
        "admission_sha256": admission_sha256,
    }))

    malformed = [
        {"action": "status", "unexpected": True},
        {"action": "run_once_preview", "executor_authority_id": authority_id},
        {
            "action": "run_once_preview",
            "executor_session_mode": "start_new",
            "executor_authority_id": "A" * 32,
            "admission_sha256": admission_sha256,
        },
        {
            "action": "status",
            "executor_session_mode": "start_new",
            "executor_authority_id": authority_id,
            "admission_sha256": admission_sha256,
        },
        {
            "action": "run_once_preview",
            "executor_session_mode": "auto",
            "executor_authority_id": authority_id,
            "admission_sha256": admission_sha256,
        },
        {"action": "run_once_preview", "executor_session_mode": "start_new"},
    ]

    assert all(list(validator.iter_errors(arguments)) for arguments in malformed)


def test_state_lineage_catalog_schema_requires_exact_normalized_bindings() -> None:
    server = MCPPlanningBridgeServer(str(ROOT))
    tool_def = next(
        tool for tool in server.tool_defs if tool.name == "manage_executor_workflow"
    )
    validator = Draft202012Validator(tool_def.input_schema)
    base = {
        "action": "state_lineage_reconciliation_preview",
        "expected_head": "d" * 40,
        "target_next_version": "v1.7",
        "bindings": [
            {
                "version": "v1.6",
                "target_status": "PASSED",
                "accepted_commit": "6" * 40,
                "accepted_commit_subject": "docs(runtime): close v1.6",
                "commit_files": ["docs/runtime.md"],
                "evidence_refs": ["receipt:v1.6"],
                "reason": "manual controlled closeout",
            },
            {
                "version": "v1.7",
                "target_status": "NOT_STARTED",
                "evidence_summary": "v1.7 remains the next runnable version",
                "reason": "preserve the next runnable version",
            },
        ],
    }

    assert not list(validator.iter_errors(base))

    malformed_bindings = [
        {**base["bindings"][1], "unexpected": True},
        {key: value for key, value in base["bindings"][1].items() if key != "version"},
        {**base["bindings"][1], "target_status": "completed"},
        {**base["bindings"][1], "reason": "   "},
        {
            key: value
            for key, value in base["bindings"][1].items()
            if key != "evidence_summary"
        },
        {**base["bindings"][1], "evidence_refs": "receipt:v1.7"},
        {
            key: value
            for key, value in base["bindings"][0].items()
            if key != "accepted_commit"
        },
        {
            key: value
            for key, value in base["bindings"][0].items()
            if key != "accepted_commit_subject"
        },
        {**base["bindings"][0], "accepted_commit": "not-a-full-commit"},
        {**base["bindings"][0], "commit_files": [""]},
    ]

    for binding in malformed_bindings:
        arguments = {**base, "bindings": [binding]}
        assert list(validator.iter_errors(arguments)), binding
    assert list(validator.iter_errors({**base, "bindings": []}))
    assert list(validator.iter_errors({
        "action": "state_lineage_reconciliation_preview",
        "expected_head": "d" * 40,
        "target_next_version": "v1.7",
    }))


def test_real_public_dispatcher_rejects_executor_schema_before_handler(tmp_path: Path) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path))
    authority_id = "a" * 32
    admission_sha256 = "b" * 64
    malformed = [
        {"action": "status", "unexpected": True},
        {"action": "run_once_preview", "executor_authority_id": authority_id},
        {
            "action": "run_once_preview",
            "executor_session_mode": "start_new",
            "executor_authority_id": "not-an-authority-id",
            "admission_sha256": admission_sha256,
        },
        {
            "action": "status",
            "executor_session_mode": "start_new",
            "executor_authority_id": authority_id,
            "admission_sha256": admission_sha256,
        },
        {
            "action": "run_once",
            "executor_session_mode": "resume_existing",
            "executor_authority_id": authority_id,
            "admission_sha256": admission_sha256,
        },
        {"action": "run_once", "executor_session_mode": "start_new"},
    ]

    for request_id, arguments in enumerate(malformed, start=1):
        response = server._handle_jsonrpc_request({
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {
                "name": "manage_executor_workflow",
                "arguments": arguments,
            },
        })

        assert response is not None
        structured = response["result"]["structuredContent"]
        assert structured["ok"] is False
        assert structured["error_code"] == "INVALID_TOOL_INPUT_SCHEMA"

    assert WorkflowRecordStore(str(tmp_path)).list_runs()["runs"] == []


def test_real_public_dispatcher_rejects_malformed_state_lineage_bindings_before_handler(
    tmp_path: Path,
) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path))
    handled: list[dict] = []
    server.tools["manage_executor_workflow"] = (
        lambda arguments: handled.append(arguments) or {"ok": True}
    )
    valid_binding = {
        "version": "v1.6",
        "target_status": "PASSED",
        "accepted_commit": "6" * 40,
        "accepted_commit_subject": "docs(runtime): close v1.6",
        "evidence_refs": ["receipt:v1.6"],
        "reason": "manual controlled closeout",
    }
    malformed_bindings = [
        {**valid_binding, "unexpected": True},
        {
            key: value
            for key, value in valid_binding.items()
            if key != "accepted_commit"
        },
        {**valid_binding, "target_status": "complete"},
        {**valid_binding, "evidence_refs": []},
        {**valid_binding, "reason": 7},
    ]

    for request_id, binding in enumerate(malformed_bindings, start=1):
        response = server._handle_jsonrpc_request({
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {
                "name": "manage_executor_workflow",
                "arguments": {
                    "action": "state_lineage_reconciliation_preview",
                    "expected_head": "d" * 40,
                    "target_next_version": "v1.7",
                    "bindings": [binding],
                },
            },
        })

        assert response is not None
        structured = response["result"]["structuredContent"]
        assert structured["ok"] is False
        assert structured["error_code"] == "INVALID_TOOL_INPUT_SCHEMA"

    assert handled == []
    assert WorkflowRecordStore(str(tmp_path)).list_runs()["runs"] == []
