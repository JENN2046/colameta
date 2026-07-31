from __future__ import annotations

import copy

import pytest
from jsonschema import Draft202012Validator

from runner.commander_contract import (
    COMMANDER_OUTCOMES,
    COMMANDER_PUBLIC_ERROR_CODES,
    COMMANDER_RESPONSE_FIELDS,
    COMMANDER_RESPONSE_SCHEMA_VERSION,
    COMMANDER_TEXT_MAX_CHARS,
    CommanderContractError,
    build_commander_response,
    commander_public_text,
    commander_response_schema,
    derive_commander_outcome,
    validate_commander_response,
)
from runner.mcp_commander_public import COMMANDER_EXPOSED_TOOLS


ARTIFACT_ID = "artifact_handle_1234567890"
MANIFEST_ID = "manifest_handle_1234567890"
PREVIEW_ID = "preview_handle_1234567890"
RUN_ID = "validation_run_1234567890"
CONTENT_SHA256 = "a" * 64
PLAN_SHA256 = "b" * 64
GIT_HEAD = "c" * 40
EXPIRES_AT = "2026-07-30T18:00:00+08:00"


def _base_context_binding() -> dict:
    return {
        "project_name": "colameta",
        "branch": "codex/nuobao-commander-contract-v1",
        "head": GIT_HEAD,
        "runner_plan": {
            "mode": "managed",
            "plan_sha256": PLAN_SHA256,
        },
        "current_version": "N1",
    }


def _operation_context_binding() -> dict:
    return {
        **_base_context_binding(),
        "review_unit": "git-commit-preview",
        "workflow_intent": "create-local-commit",
    }


def _minimal_completed_response() -> dict:
    return {
        "schema_version": COMMANDER_RESPONSE_SCHEMA_VERSION,
        "outcome": "completed",
        "summary": "当前调用已完成。",
        "journey_stage": "observe",
        "context_binding": None,
        "facts": {},
        "evidence": None,
        "next_action": None,
        "confirmation": None,
        "error": None,
    }


@pytest.mark.parametrize(
    ("tool_name", "result", "expected"),
    [
        (
            "list_registered_projects",
            {"ok": True, "data": {"ok": True, "projects": []}},
            "completed",
        ),
        (
            "manage_validation_run",
            {"ok": True, "data": {"ok": True, "status": "running"}},
            "in_progress",
        ),
        (
            "manage_git",
            {
                "ok": True,
                "data": {
                    "ok": True,
                    "requires_confirmation": True,
                    "preview_id": PREVIEW_ID,
                },
            },
            "confirmation_required",
        ),
        (
            "analyze_project_state",
            {
                "ok": False,
                "error_code": "PROJECT_NAME_REQUIRED",
                "message": "必须选择项目。",
            },
            "blocked",
        ),
        (
            "analyze_project_state",
            {
                "ok": False,
                "error_code": "TOOL_EXEC_ERROR",
                "message": "unexpected failure",
            },
            "failed",
        ),
        (
            "analyze_project_state",
            {"ok": True, "data": []},
            "failed",
        ),
        (
            "manage_files",
            {"ok": True, "data": {"ok": True}},
            "failed",
        ),
        (
            "analyze_project_state",
            {
                "ok": True,
                "tool": "manage_git",
                "data": {"ok": True},
            },
            "failed",
        ),
    ],
)
def test_derive_commander_outcome_covers_all_public_states(
    tool_name: str,
    result: dict,
    expected: str,
) -> None:
    assert derive_commander_outcome(tool_name, result) == expected


def test_blocker_wins_over_confirmation_and_running_state() -> None:
    result = {
        "ok": True,
        "data": {
            "ok": True,
            "status": "running",
            "requires_confirmation": True,
            "preview_id": PREVIEW_ID,
            "blockers": ["WORKTREE_DIRTY"],
        },
    }

    assert derive_commander_outcome("manage_git", result) == "blocked"


def test_false_ok_cannot_be_upgraded_by_an_untrusted_confirmation_flag() -> None:
    result = {
        "ok": False,
        "data": {
            "requires_confirmation": True,
            "preview_id": PREVIEW_ID,
        },
    }

    assert derive_commander_outcome("manage_git", result) == "failed"


def test_consumed_bound_apply_is_completed_even_if_legacy_flag_remains_true() -> None:
    result = {
        "ok": True,
        "data": {
            "ok": True,
            "status": "succeeded",
            "requires_confirmation": True,
            "result": {
                "ok": True,
                "action": "apply",
            },
            "context_binding_verification": {
                "status": "matched",
            },
        },
    }

    assert derive_commander_outcome("run_mcp_workflow", result) == "completed"


def test_normal_business_code_is_not_misread_as_an_error_code() -> None:
    result = {
        "ok": True,
        "data": {
            "ok": True,
            "code": "READY",
            "projects": [],
        },
    }

    assert derive_commander_outcome("list_registered_projects", result) == "completed"


def test_nested_historical_error_fact_does_not_override_current_ok() -> None:
    result = {
        "ok": True,
        "data": {
            "ok": True,
            "error": {
                "ok": False,
                "message": "historical diagnostic",
            },
        },
    }

    assert derive_commander_outcome("render_commander_app", result) == "completed"


def test_validation_failure_is_a_recoverable_blocker_not_a_tool_crash() -> None:
    result = {
        "ok": True,
        "data": {
            "ok": True,
            "status": "failed",
            "message": "测试未通过。",
        },
    }

    response = build_commander_response(
        tool_name="manage_validation_run",
        raw_result=result,
        params={"action": "status"},
    )

    assert response["outcome"] == "blocked"
    assert response["error"]["code"] == "VALIDATION_FAILED"
    assert response["error"]["recoverable"] is True
    validate_commander_response(response)


def test_connector_smoke_not_ready_is_blocked_even_when_read_succeeds() -> None:
    response = build_commander_response(
        tool_name="get_apps_connector_smoke_packet",
        raw_result={
            "ok": True,
            "data": {
                "ok": True,
                "apps_connector_closeout": {"status": "needs_attention"},
                "connector_runtime_health": {"overall_status": "degraded"},
            },
        },
    )

    assert response["outcome"] == "blocked"
    assert response["error"]["code"] == "MANUAL_REVIEW_REQUIRED"
    assert response["next_action"]["tool"] == "analyze_project_state"
    validate_commander_response(response)


@pytest.mark.parametrize(
    ("error_code", "public_error_code", "params"),
    [
        (
            "PROJECT_NAME_REQUIRED",
            "PROJECT_REQUIRED",
            {"workflow": "project_status"},
        ),
        (
            "PROJECT_REQUIRED",
            "PROJECT_REQUIRED",
            {"workflow": "project_status"},
        ),
        (
            "INVALID_PROJECT_NAME",
            "PROJECT_REQUIRED",
            {"workflow": "project_status"},
        ),
        (
            "PROJECT_NOT_REGISTERED",
            "PROJECT_NOT_REGISTERED",
            {
                "workflow": "project_status",
                "project_name": "stale-project",
            },
        ),
        (
            "PROJECT_UNAVAILABLE",
            "PROJECT_NOT_REGISTERED",
            {
                "workflow": "project_status",
                "project_name": "unavailable-project",
            },
        ),
        (
            "PROJECT_ROOT_UNAVAILABLE",
            "PROJECT_NOT_REGISTERED",
            {
                "workflow": "project_status",
                "project_name": "missing-root-project",
            },
        ),
    ],
)
def test_project_selection_blockers_expose_project_list_as_single_recovery(
    error_code: str,
    public_error_code: str,
    params: dict,
) -> None:
    response = build_commander_response(
        tool_name="run_mcp_workflow",
        raw_result={
            "ok": False,
            "tool": "run_mcp_workflow",
            "error_code": error_code,
            "message": "必须重新选择一个已登记项目。",
        },
        params=params,
    )

    expected_action = {
        "tool": "list_registered_projects",
        "arguments": {},
        "reason": "列出可用项目后，使用有效 project_name 重试原调用。",
    }
    assert response["outcome"] == "blocked"
    assert response["error"]["code"] == public_error_code
    assert response["next_action"] == expected_action
    assert response["error"]["recovery"] == expected_action
    validate_commander_response(response)


def test_completed_response_has_exact_fields_and_bounded_public_facts() -> None:
    raw_result = {
        "ok": True,
        "data": {
            "ok": True,
            "project_name": "colameta",
            "context_binding": _base_context_binding(),
            "project_root": "/home/jenn/src/colameta-dev",
            "stdout": "private diagnostic",
            "note": "See /tmp/private.log for details",
            "warning": "Do not call manage_files from Commander.",
            "long_text": "x" * (COMMANDER_TEXT_MAX_CHARS + 50),
            "items": list(range(150)),
            "next_actions": [
                {
                    "tool": "manage_files",
                    "arguments": {"action": "write"},
                    "reason": "internal-only",
                }
            ],
        },
    }

    response = build_commander_response(
        tool_name="analyze_project_state",
        raw_result=raw_result,
        params={"project_name": "colameta"},
    )

    assert set(response) == set(COMMANDER_RESPONSE_FIELDS)
    assert response["schema_version"] == COMMANDER_RESPONSE_SCHEMA_VERSION
    assert response["outcome"] == "completed"
    assert response["journey_stage"] == "observe"
    assert response["facts"]["project_name"] == "colameta"
    assert "project_root" not in response["facts"]
    assert "stdout" not in response["facts"]
    assert "next_actions" not in response["facts"]
    assert response["facts"]["note"] == "See <local-path> for details"
    assert response["facts"]["warning"] == (
        "Do not call <internal-tool> from Commander."
    )
    assert len(response["facts"]["long_text"]) == COMMANDER_TEXT_MAX_CHARS
    assert len(response["facts"]["items"]) == 100
    assert response["next_action"] is None
    assert response["confirmation"] is None
    assert response["error"] is None
    validate_commander_response(response)


def test_summary_is_bounded_to_three_sentences() -> None:
    response = build_commander_response(
        tool_name="analyze_project_state",
        raw_result={
            "ok": True,
            "data": {
                "ok": True,
                "message": "First. Second. Third. Fourth. Fifth.",
                "context_binding": _base_context_binding(),
            },
        },
    )

    assert response["summary"] == "First. Second. Third."
    validate_commander_response(response)


def test_summary_redacts_inline_authorization_material() -> None:
    response = build_commander_response(
        tool_name="render_commander_app",
        raw_result={
            "ok": True,
            "data": {
                "ok": True,
                "message": (
                    "Connector responded with Authorization: "
                    "Bearer abcdefghijklmnop."
                ),
            },
        },
    )

    assert "Authorization" not in response["summary"]
    assert "abcdefghijklmnop" not in response["summary"]
    assert "<sensitive>" in response["summary"]
    validate_commander_response(response)


def test_public_facts_remove_private_paths_ids_logs_and_secret_fields() -> None:
    raw_result = {
        "ok": True,
        "data": {
            "ok": True,
            "context_binding": _base_context_binding(),
            "paths": [
                "/home/jenn/private.txt",
                "/tmp/private.log",
                r"C:\Users\Jenn\private.txt",
                r"\\server\share\private.txt",
                "file:///home/jenn/private.txt",
            ],
            "project_root": "/home/jenn/src/colameta-dev",
            "workspace_root": "/home/jenn/src",
            "runtime_dir": "/tmp/colameta",
            "stdout": "raw output",
            "stderr": "raw error",
            "pid": 123,
            "session_id": "private-session",
            "workflow_id": "private-workflow",
            "report_id": "private-report",
            "Authorization": "Bearer private",
            "access_token": "private-access-token",
            "cookie": "private-cookie",
        },
    }

    response = build_commander_response(
        tool_name="analyze_project_state",
        raw_result=raw_result,
    )
    rendered = repr(response)

    assert response["outcome"] == "completed"
    assert response["facts"]["paths"] == ["<local-path>"] * 5
    for forbidden in (
        "/home/",
        "/tmp/",
        "C:\\",
        "\\\\server\\share",
        "file:///",
        "project_root",
        "workspace_root",
        "runtime_dir",
        "stdout",
        "stderr",
        "session_id",
        "workflow_id",
        "report_id",
        "Authorization",
        "access_token",
        "cookie",
        "Bearer private",
    ):
        assert forbidden not in rendered
    validate_commander_response(response)


def test_nested_internal_tool_reference_removes_the_public_action() -> None:
    response = build_commander_response(
        tool_name="render_commander_app",
        raw_result={
            "ok": True,
            "data": {
                "ok": True,
                "next_actions": [
                    {
                        "tool": "run_mcp_workflow",
                        "arguments": {
                            "workflow": "docs_update",
                            "delegate": {
                                "tool": "manage_files",
                                "arguments": {"action": "write"},
                            },
                        },
                        "reason": "continue",
                    }
                ],
            },
        },
    )

    assert response["outcome"] == "completed"
    assert response["next_action"] is None
    assert "manage_files" not in repr(response)
    validate_commander_response(response)


def test_context_binding_is_preserved_verbatim() -> None:
    binding = _operation_context_binding()
    raw_result = {
        "ok": True,
        "data": {
            "ok": True,
            "context_binding": binding,
            "state": "observed",
        },
    }

    response = build_commander_response(
        tool_name="analyze_project_state",
        raw_result=raw_result,
        params={"project_name": "colameta"},
    )

    assert response["context_binding"] == binding
    assert response["context_binding"] is not binding
    assert "context_binding" not in response["facts"]
    validate_commander_response(response)


def test_context_binding_can_be_read_from_canonical_project_state() -> None:
    binding = _base_context_binding()
    raw_result = {
        "ok": True,
        "data": {
            "ok": True,
            "canonical_project_state": {
                "schema_version": "canonical_project_state.v1",
                "context_binding": binding,
            },
        },
    }

    response = build_commander_response(
        tool_name="analyze_project_state",
        raw_result=raw_result,
    )

    assert response["context_binding"] == binding
    validate_commander_response(response)


def test_source_only_context_binding_preserves_meaningful_nulls() -> None:
    binding = {
        "project_name": "source-only-project",
        "branch": None,
        "head": None,
        "runner_plan": {
            "mode": "source-only",
            "plan_sha256": None,
        },
        "current_version": None,
    }
    response = build_commander_response(
        tool_name="analyze_project_state",
        raw_result={
            "ok": True,
            "data": {"ok": True, "context_binding": binding},
        },
    )

    assert response["context_binding"] == binding
    validate_commander_response(response)


def test_result_artifact_evidence_is_normalized_to_opaque_contract() -> None:
    descriptor = {
        "artifact_id": ARTIFACT_ID,
        "resource_uri": f"colameta://result-artifact/{ARTIFACT_ID}",
        "page_uri_template": (
            f"colameta://result-artifact/{ARTIFACT_ID}/pages/{{page}}"
        ),
        "page_count": 3,
        "content_sha256": CONTENT_SHA256.upper(),
        "expires_at": EXPIRES_AT,
    }
    raw_result = {
        "ok": True,
        "data": {
            "ok": True,
            "context_binding": _base_context_binding(),
            "packaged": True,
            "result_artifact": descriptor,
            **descriptor,
        },
    }

    response = build_commander_response(
        tool_name="run_mcp_workflow",
        raw_result=raw_result,
        params={"workflow": "docs_update"},
    )

    assert response["outcome"] == "completed"
    assert response["evidence"] == {
        "kind": "result_artifact",
        **descriptor,
        "content_sha256": CONTENT_SHA256,
    }
    assert "artifact_id" not in response["facts"]
    validate_commander_response(response)


def test_result_artifact_page_can_rebuild_its_existing_resource_contract() -> None:
    content = "line one\nbounded public evidence\n"
    raw_result = {
        "ok": True,
        "data": {
            "ok": True,
            "artifact_id": ARTIFACT_ID,
            "artifact_page": {
                "artifact_id": ARTIFACT_ID,
                "tool": "read_result_artifact",
                "page": 1,
                "page_count": 2,
                "page_char_start": 0,
                "page_char_end": len(content),
                "content_sha256": CONTENT_SHA256,
                "expires_at": EXPIRES_AT,
                "content": content,
            },
            "content_sha256": CONTENT_SHA256,
            "expires_at": EXPIRES_AT,
        },
    }

    response = build_commander_response(
        tool_name="read_result_artifact",
        raw_result=raw_result,
        params={"artifact_id": ARTIFACT_ID, "artifact_page": 1},
    )

    assert response["evidence"] == {
        "kind": "result_artifact",
        "artifact_id": ARTIFACT_ID,
        "resource_uri": f"colameta://result-artifact/{ARTIFACT_ID}",
        "page_uri_template": (
            f"colameta://result-artifact/{ARTIFACT_ID}/pages/{{page}}"
        ),
        "page_count": 2,
        "content_sha256": CONTENT_SHA256,
        "expires_at": EXPIRES_AT,
    }
    assert response["facts"]["artifact_page"]["content"] == content
    validate_commander_response(response)


def test_result_artifact_page_with_private_content_fails_closed() -> None:
    content = "line one\n/home/reviewer/example.md\n"
    raw_result = {
        "ok": True,
        "data": {
            "ok": True,
            "artifact_id": ARTIFACT_ID,
            "artifact_page": {
                "artifact_id": ARTIFACT_ID,
                "tool": "read_result_artifact",
                "page": 1,
                "page_count": 1,
                "page_char_start": 0,
                "page_char_end": len(content),
                "content_sha256": CONTENT_SHA256,
                "expires_at": EXPIRES_AT,
                "content": content,
            },
            "content_sha256": CONTENT_SHA256,
            "expires_at": EXPIRES_AT,
        },
    }

    response = build_commander_response(
        tool_name="read_result_artifact",
        raw_result=raw_result,
        params={"artifact_id": ARTIFACT_ID, "artifact_page": 1},
    )

    assert response["outcome"] == "failed"
    assert response["error"]["code"] == "INTERNAL_RESULT_INVALID"
    assert "/home/" not in repr(response)
    validate_commander_response(response)


def test_review_manifest_evidence_uses_opaque_manifest_uri() -> None:
    raw_result = {
        "ok": True,
        "data": {
            "ok": True,
            "context_binding": _base_context_binding(),
            "review_manifest_id": MANIFEST_ID,
            "manifest_resource_uri": (
                f"colameta://review-manifest/{MANIFEST_ID}"
            ),
            "manifest_sha256": CONTENT_SHA256,
            "expires_at": EXPIRES_AT,
        },
    }

    response = build_commander_response(
        tool_name="review_manifest",
        raw_result=raw_result,
        params={"phase": "inspect"},
    )

    assert response["evidence"] == {
        "kind": "review_manifest",
        "review_manifest_id": MANIFEST_ID,
        "resource_uri": f"colameta://review-manifest/{MANIFEST_ID}",
        "manifest_sha256": CONTENT_SHA256,
        "expires_at": EXPIRES_AT,
    }
    validate_commander_response(response)


@pytest.mark.parametrize(
    "uri",
    [
        "colameta://result-artifact/opaque_handle_123_/pages/{page}",
        (
            "colameta://review-manifest/opaque_handle_123_"
            "/subjects/1/pages/{page}"
        ),
    ],
)
def test_public_text_preserves_valid_opaque_uri_templates_ending_in_underscore(
    uri: str,
) -> None:
    assert commander_public_text(uri) == uri


def test_review_manifest_subject_page_preserves_exact_hash_bound_text() -> None:
    content = "# Review input\n\nA bounded subject.\n"
    raw_result = {
        "ok": True,
        "data": {
            "ok": True,
            "context_binding": _operation_context_binding(),
            "review_manifest_id": MANIFEST_ID,
            "manifest_resource_uri": (
                f"colameta://review-manifest/{MANIFEST_ID}"
            ),
            "manifest_sha256": CONTENT_SHA256,
            "expires_at": EXPIRES_AT,
            "subject_page": {
                "review_manifest_id": MANIFEST_ID,
                "review_unit": "git-commit-preview",
                "subject_index": 1,
                "path": "docs/review-input.md",
                "sha256": "d" * 64,
                "page": 1,
                "page_count": 1,
                "page_char_start": 0,
                "page_char_end": len(content),
                "expires_at": EXPIRES_AT,
                "content": content,
            },
        },
    }

    response = build_commander_response(
        tool_name="review_manifest",
        raw_result=raw_result,
        params={"phase": "read", "review_manifest_id": MANIFEST_ID},
    )

    assert response["facts"]["subject_page"]["content"] == content
    assert response["facts"]["subject_page"]["path"] == "docs/review-input.md"
    validate_commander_response(response)


def test_confirmation_is_explicit_and_bound_to_one_apply_action() -> None:
    binding = _operation_context_binding()
    raw_result = {
        "ok": True,
        "data": {
            "ok": True,
            "requires_confirmation": True,
            "preview_id": PREVIEW_ID,
            "expires_at": EXPIRES_AT,
            "confirmation": {
                "decision": "是否提交当前修改",
                "impact": ["将创建一个本地 Git commit", "不会执行 push"],
                "risks": ["尚未执行浏览器端集成测试"],
                "preview_id": PREVIEW_ID,
                "expires_at": EXPIRES_AT,
                "context_binding": binding,
            },
        },
    }

    response = build_commander_response(
        tool_name="manage_git",
        raw_result=raw_result,
        params={
            "action": "commit_preview",
            "project_name": "colameta",
            "message": "feat(commander): add public response contract v1",
        },
    )

    assert response["outcome"] == "confirmation_required"
    assert response["context_binding"] == binding
    assert response["confirmation"] == {
        "decision": "是否提交当前修改",
        "impact": ["将创建一个本地 Git commit", "不会执行 push"],
        "risks": ["尚未执行浏览器端集成测试"],
        "preview_id": PREVIEW_ID,
        "expires_at": EXPIRES_AT,
        "context_binding": binding,
    }
    assert response["next_action"]["tool"] == "manage_git"
    assert response["next_action"]["arguments"]["action"] == "commit_apply"
    assert response["next_action"]["arguments"]["preview_id"] == PREVIEW_ID
    assert response["error"] is None
    validate_commander_response(response)


def test_builder_fails_closed_when_confirmation_action_uses_another_preview() -> None:
    binding = _operation_context_binding()
    response = build_commander_response(
        tool_name="manage_git",
        raw_result={
            "ok": True,
            "data": {
                "ok": True,
                "requires_confirmation": True,
                "preview_id": PREVIEW_ID,
                "context_binding": binding,
                "next_action": {
                    "tool": "manage_git",
                    "arguments": {
                        "action": "commit_apply",
                        "preview_id": "another_preview_1234567890",
                        "context_binding": binding,
                    },
                    "reason": "确认后创建本地提交。",
                },
            },
        },
        params={"action": "commit_preview", "project_name": "colameta"},
    )

    assert response["outcome"] == "failed"
    assert response["error"]["code"] == "INTERNAL_RESULT_INVALID"
    validate_commander_response(response)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value["next_action"]["arguments"].update(
            preview_id="another_preview_1234567890"
        ),
        lambda value: value["next_action"]["arguments"].update(
            context_binding={
                **_operation_context_binding(),
                "head": "d" * 40,
            }
        ),
        lambda value: value["confirmation"].update(
            context_binding={
                **_operation_context_binding(),
                "head": "d" * 40,
            }
        ),
    ],
)
def test_validator_enforces_confirmation_preview_and_context_relations(
    mutate,
) -> None:
    binding = _operation_context_binding()
    response = build_commander_response(
        tool_name="manage_git",
        raw_result={
            "ok": True,
            "data": {
                "ok": True,
                "requires_confirmation": True,
                "preview_id": PREVIEW_ID,
                "context_binding": binding,
            },
        },
        params={"action": "commit_preview", "project_name": "colameta"},
    )
    assert response["outcome"] == "confirmation_required"
    mutate(response)

    with pytest.raises(CommanderContractError):
        validate_commander_response(response)


def test_in_progress_response_has_one_query_action() -> None:
    raw_result = {
        "ok": True,
        "data": {
            "ok": True,
            "status": "running",
            "run_id": RUN_ID,
            "context_binding": _operation_context_binding(),
        },
    }

    response = build_commander_response(
        tool_name="manage_validation_run",
        raw_result=raw_result,
        params={"action": "status", "project_name": "colameta"},
    )

    assert response["outcome"] == "in_progress"
    assert "run_id" not in response["facts"]
    assert response["next_action"] == {
        "tool": "manage_validation_run",
        "arguments": {
            "action": "status",
            "run_id": RUN_ID,
            "project_name": "colameta",
        },
        "reason": "查询当前验证运行状态。",
    }
    assert response["confirmation"] is None
    assert response["error"] is None
    validate_commander_response(response)


def test_executor_running_error_becomes_in_progress_with_polling() -> None:
    response = build_commander_response(
        tool_name="run_mcp_workflow",
        raw_result={
            "ok": False,
            "error_code": "EXECUTOR_RUNNING",
            "message": "执行器已经在运行。",
            "data": {
                "context_binding": _operation_context_binding(),
                "batch_preview_id": PREVIEW_ID,
            },
        },
        params={
            "workflow": "agent_dispatch",
            "phase": "run",
            "project_name": "colameta",
        },
    )

    assert response["outcome"] == "in_progress"
    assert response["next_action"]["tool"] == "run_mcp_workflow"
    assert response["next_action"]["arguments"]["phase"] == "status"
    assert response["error"] is None
    validate_commander_response(response)


def test_blocked_response_maps_nested_error_and_exposes_read_only_recovery() -> None:
    raw_result = {
        "ok": False,
        "error": {
            "code": "GIT_WORKTREE_DIRTY",
            "message": "当前工作区存在不属于本次任务的修改。",
            "recoverable": True,
            "recovery": {
                "tool": "analyze_project_state",
                "arguments": {"project_name": "colameta"},
                "reason": "重新读取工作区事实。",
            },
        },
    }

    response = build_commander_response(
        tool_name="manage_git",
        raw_result=raw_result,
        params={"action": "commit_preview", "project_name": "colameta"},
    )

    assert response["outcome"] == "blocked"
    assert response["error"] == {
        "code": "WORKTREE_DIRTY",
        "message": "当前工作区存在不属于本次任务的修改。",
        "recoverable": True,
        "recovery": {
            "tool": "analyze_project_state",
            "arguments": {"project_name": "colameta"},
            "reason": "重新读取工作区事实。",
        },
    }
    assert response["next_action"]["tool"] == "analyze_project_state"
    assert response["confirmation"] is None
    validate_commander_response(response)


def test_validator_requires_error_recovery_to_equal_the_single_next_action() -> None:
    response = build_commander_response(
        tool_name="manage_git",
        raw_result={
            "ok": False,
            "error_code": "GIT_WORKTREE_DIRTY",
            "message": "当前工作区不满足提交前置条件。",
        },
        params={"action": "commit_preview", "project_name": "colameta"},
    )
    assert response["outcome"] == "blocked"
    response["error"]["recovery"]["reason"] = "另一个恢复建议。"

    with pytest.raises(CommanderContractError):
        validate_commander_response(response)


@pytest.mark.parametrize(
    ("internal_code", "public_code"),
    [
        ("WORKING_TREE_DIRTY", "WORKTREE_DIRTY"),
        ("HEAD_CHANGED", "STALE_PREVIEW"),
        ("RESULT_ARTIFACT_NOT_FOUND_OR_EXPIRED", "ARTIFACT_EXPIRED"),
        ("INVALID_RESULT_ARTIFACT_ID", "RESOURCE_URI_INVALID"),
        ("INVALID_WORKFLOW", "WORKFLOW_NOT_SUPPORTED"),
        ("RUN_NOT_FOUND", "VALIDATION_UNAVAILABLE"),
        ("PATH_NOT_ALLOWED", "SCOPE_VIOLATION"),
    ],
)
def test_known_internal_errors_have_explicit_stable_public_mappings(
    internal_code: str,
    public_code: str,
) -> None:
    response = build_commander_response(
        tool_name="run_mcp_workflow",
        raw_result={
            "ok": False,
            "error_code": internal_code,
            "message": "当前前置条件不满足。",
        },
        params={"workflow": "project_status"},
    )

    assert response["outcome"] == "blocked"
    assert response["error"]["code"] == public_code
    validate_commander_response(response)


def test_nested_core_result_error_uses_the_same_public_mapping() -> None:
    response = build_commander_response(
        tool_name="run_mcp_workflow",
        raw_result={
            "ok": False,
            "workflow": "small_project_patch",
            "status": "failed",
            "result": {
                "ok": False,
                "error_code": "PATH_NOT_ALLOWED",
                "message": "路径必须是项目内相对路径。",
            },
        },
        params={"workflow": "small_project_patch", "phase": "preview"},
    )

    assert response["outcome"] == "blocked"
    assert response["error"]["code"] == "SCOPE_VIOLATION"
    validate_commander_response(response)


def test_unknown_internal_error_and_exception_text_are_not_exposed() -> None:
    raw_result = {
        "ok": False,
        "error": {
            "code": "SomePythonException",
            "message": (
                "SomePythonException at /home/jenn/private.py: "
                "authorization=secret"
            ),
        },
    }

    response = build_commander_response(
        tool_name="analyze_project_state",
        raw_result=raw_result,
    )
    rendered = repr(response)

    assert response["outcome"] == "failed"
    assert response["error"] == {
        "code": "INTERNAL_ERROR",
        "message": "工具执行失败，内部诊断未公开。",
        "recoverable": False,
    }
    assert "SomePythonException" not in rendered
    assert "/home/jenn" not in rendered
    assert "authorization=secret" not in rendered
    validate_commander_response(response)


def test_required_artifact_creation_failure_is_a_projection_failure() -> None:
    response = build_commander_response(
        tool_name="run_mcp_workflow",
        raw_result={
            "ok": False,
            "error_code": "MCP_RESULT_ARTIFACT_UNAVAILABLE",
            "message": "store path /tmp/private is unavailable",
        },
        params={"workflow": "docs_update"},
    )

    assert response["outcome"] == "failed"
    assert response["error"] == {
        "code": "PUBLIC_PROJECTION_FAILED",
        "message": "Commander 公共响应构建失败，内部诊断未公开。",
        "recoverable": False,
    }
    assert "/tmp/" not in repr(response)
    validate_commander_response(response)


def test_malformed_or_incomplete_contract_input_fails_closed() -> None:
    malformed = build_commander_response(
        tool_name="manage_git",
        raw_result={
            "ok": True,
            "data": {
                "ok": True,
                "requires_confirmation": True,
                "preview_id": "bad!",
            },
        },
        params={"action": "commit_preview"},
    )

    assert malformed["outcome"] == "failed"
    assert malformed["error"]["code"] == "INTERNAL_RESULT_INVALID"
    assert malformed["facts"] == {}
    assert malformed["next_action"] is None
    assert malformed["confirmation"] is None
    validate_commander_response(malformed)


def test_confirmation_accepts_existing_twelve_character_preview_handles() -> None:
    context_binding = {
        **_operation_context_binding(),
        "review_unit": "operation:validation_run",
        "workflow_intent": "validation_run",
    }
    response = build_commander_response(
        tool_name="manage_validation_run",
        raw_result={
            "ok": True,
            "action": "preview",
            "status": "preview_ready",
            "requires_confirmation": True,
            "preview_id": "d6a119fa6a01",
            "context_binding": context_binding,
            "next_actions": [
                {
                    "tool": "manage_validation_run",
                    "params": {
                        "action": "run",
                        "preview_id": "d6a119fa6a01",
                        "context_binding": context_binding,
                    },
                    "requires_confirmation": True,
                }
            ],
        },
        params={"action": "preview", "scope": "changed_files"},
    )

    assert response["outcome"] == "confirmation_required"
    assert response["confirmation"]["preview_id"] == "d6a119fa6a01"
    assert response["next_action"]["arguments"]["action"] == "run"
    validate_commander_response(response)


def test_confirmation_without_project_context_fails_closed() -> None:
    response = build_commander_response(
        tool_name="manage_git",
        raw_result={
            "ok": True,
            "data": {
                "ok": True,
                "requires_confirmation": True,
                "preview_id": PREVIEW_ID,
            },
        },
        params={"action": "commit_preview"},
    )

    assert response["outcome"] == "failed"
    assert response["error"]["code"] == "INTERNAL_RESULT_INVALID"
    assert response["confirmation"] is None
    validate_commander_response(response)


def test_project_state_without_context_binding_fails_closed() -> None:
    response = build_commander_response(
        tool_name="analyze_project_state",
        raw_result={"ok": True, "data": {"ok": True, "state": "observed"}},
        params={"project_name": "colameta"},
    )

    assert response["outcome"] == "failed"
    assert response["error"]["code"] == "INTERNAL_RESULT_INVALID"
    validate_commander_response(response)


def test_response_schema_freezes_required_fields_and_allowed_values() -> None:
    schema = commander_response_schema()

    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(_minimal_completed_response())
    assert schema["additionalProperties"] is False
    assert schema["required"] == list(COMMANDER_RESPONSE_FIELDS)
    assert schema["properties"]["schema_version"]["const"] == (
        COMMANDER_RESPONSE_SCHEMA_VERSION
    )
    assert set(schema["properties"]["outcome"]["enum"]) == COMMANDER_OUTCOMES
    assert set(schema["properties"]["journey_stage"]["enum"]) == {
        "connect",
        "observe",
        "plan",
        "execute",
        "review",
        "validate",
        "close",
        "recover",
    }
    next_action_schema = schema["properties"]["next_action"]["anyOf"][1]
    assert set(next_action_schema["properties"]["tool"]["enum"]) == set(
        COMMANDER_EXPOSED_TOOLS
    )
    assert next_action_schema["additionalProperties"] is False
    evidence_kinds = {
        branch["properties"]["kind"]["const"]
        for branch in schema["properties"]["evidence"]["anyOf"]
        if branch.get("type") == "object"
    }
    assert evidence_kinds == {"result_artifact", "review_manifest"}
    assert len(schema["allOf"]) == 4


def test_public_inventories_are_closed_and_reuse_the_nine_tool_source() -> None:
    assert COMMANDER_OUTCOMES == {
        "completed",
        "in_progress",
        "confirmation_required",
        "blocked",
        "failed",
    }
    assert len(COMMANDER_EXPOSED_TOOLS) == 9
    assert {
        "WORKTREE_DIRTY",
        "VALIDATION_FAILED",
        "PUBLIC_PROJECTION_FAILED",
        "INTERNAL_RESULT_INVALID",
        "INTERNAL_ERROR",
    } <= COMMANDER_PUBLIC_ERROR_CODES


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.update(outcome="success"),
        lambda value: value.update(confirmation={"decision": "wrong"}),
        lambda value: value.update(error={"code": "INTERNAL_ERROR"}),
        lambda value: value["facts"].update(project_root="/home/jenn/private"),
        lambda value: value["facts"].update(note="Call manage_files next."),
        lambda value: value.update(
            next_action={
                "tool": "manage_files",
                "arguments": {},
                "reason": "internal",
            }
        ),
    ],
)
def test_validator_rejects_unknown_states_unsafe_fields_and_hidden_tools(
    mutate,
) -> None:
    response = _minimal_completed_response()
    mutate(response)

    with pytest.raises(CommanderContractError):
        validate_commander_response(response)


@pytest.mark.parametrize(
    "unsafe_key",
    [
        "oauth_token",
        "id_token",
        "client_secret",
        "client-secret",
        "API Key",
        "oauth_authorization_code",
        "/home/jenn/private/secret.txt",
        r"C:\Users\Jenn\secret.txt",
    ],
)
def test_validator_rejects_sensitive_and_absolute_path_object_keys(
    unsafe_key: str,
) -> None:
    response = _minimal_completed_response()
    response["facts"] = {unsafe_key: "must not be public"}

    with pytest.raises(CommanderContractError):
        validate_commander_response(response)


def test_validator_enforces_confirmation_and_error_mutual_exclusion() -> None:
    response = _minimal_completed_response()
    response.update(
        {
            "outcome": "confirmation_required",
            "next_action": {
                "tool": "manage_git",
                "arguments": {
                    "action": "commit_apply",
                    "preview_id": PREVIEW_ID,
                },
                "reason": "确认后创建本地提交。",
            },
            "confirmation": {
                "decision": "是否提交当前修改",
                "impact": ["将创建一个本地 Git commit"],
                "preview_id": PREVIEW_ID,
            },
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "must not coexist",
                "recoverable": False,
            },
        }
    )

    with pytest.raises(CommanderContractError):
        validate_commander_response(response)


@pytest.mark.parametrize("outcome", ["blocked", "failed"])
def test_validator_requires_error_for_blocked_and_failed(outcome: str) -> None:
    response = _minimal_completed_response()
    response["outcome"] = outcome

    with pytest.raises(CommanderContractError):
        validate_commander_response(response)


def test_validator_requires_confirmation_object_and_apply_action() -> None:
    response = _minimal_completed_response()
    response["outcome"] = "confirmation_required"

    with pytest.raises(CommanderContractError):
        validate_commander_response(response)


def test_validator_requires_error_class_to_match_outcome() -> None:
    blocked = _minimal_completed_response()
    blocked.update(
        {
            "outcome": "blocked",
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "wrong error class",
                "recoverable": False,
            },
        }
    )
    failed = _minimal_completed_response()
    failed.update(
        {
            "outcome": "failed",
            "error": {
                "code": "WORKTREE_DIRTY",
                "message": "wrong error class",
                "recoverable": True,
            },
        }
    )

    with pytest.raises(CommanderContractError):
        validate_commander_response(blocked)
    with pytest.raises(CommanderContractError):
        validate_commander_response(failed)


def test_validator_requires_polling_action_for_in_progress() -> None:
    response = _minimal_completed_response()
    response.update(
        {
            "outcome": "in_progress",
            "next_action": {
                "tool": "manage_git",
                "arguments": {"action": "commit_preview"},
                "reason": "prepare commit",
            },
        }
    )

    with pytest.raises(CommanderContractError):
        validate_commander_response(response)


def test_validator_rejects_multiple_actions_and_non_opaque_evidence_uri() -> None:
    multiple_actions = _minimal_completed_response()
    multiple_actions["next_action"] = [
        {
            "tool": "analyze_project_state",
            "arguments": {},
            "reason": "first",
        },
        {
            "tool": "review_manifest",
            "arguments": {},
            "reason": "second",
        },
    ]
    unsafe_evidence = _minimal_completed_response()
    unsafe_evidence["evidence"] = {
        "kind": "result_artifact",
        "artifact_id": ARTIFACT_ID,
        "resource_uri": "https://example.com/private-result",
        "page_uri_template": (
            f"colameta://result-artifact/{ARTIFACT_ID}/pages/{{page}}"
        ),
        "page_count": 1,
        "content_sha256": CONTENT_SHA256,
        "expires_at": EXPIRES_AT,
    }

    with pytest.raises(CommanderContractError):
        validate_commander_response(multiple_actions)
    with pytest.raises(CommanderContractError):
        validate_commander_response(unsafe_evidence)


def test_validator_rejects_modified_context_binding_shape() -> None:
    response = _minimal_completed_response()
    response["context_binding"] = {
        **_base_context_binding(),
        "project_root": "/home/jenn/src/colameta-dev",
    }

    with pytest.raises(CommanderContractError):
        validate_commander_response(response)


def test_validator_accepts_a_minimal_completed_response() -> None:
    validate_commander_response(copy.deepcopy(_minimal_completed_response()))
