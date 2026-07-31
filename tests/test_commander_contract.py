from __future__ import annotations

import copy
import json
import time

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


def test_primary_blocker_controls_public_error_and_matching_recovery() -> None:
    response = build_commander_response(
        tool_name="run_mcp_workflow",
        raw_result={
            "ok": False,
            "tool": "run_mcp_workflow",
            "error_code": "SCOPE_VIOLATION",
            "message": "当前请求超出允许范围。",
            "result": {
                "diagnostics": {
                    "error_code": "PROJECT_UNAVAILABLE",
                }
            },
        },
        params={
            "workflow": "small_project_patch",
            "project_name": "colameta",
        },
    )

    expected_action = {
        "tool": "analyze_project_state",
        "arguments": {"project_name": "colameta"},
        "reason": "重新读取项目事实后再决定如何解除阻断。",
    }
    assert response["outcome"] == "blocked"
    assert response["error"]["code"] == "SCOPE_VIOLATION"
    assert response["next_action"] == expected_action
    assert response["error"]["recovery"] == expected_action
    validate_commander_response(response)


def test_review_manifest_hash_mismatch_maps_to_public_stale_context() -> None:
    response = build_commander_response(
        tool_name="review_manifest",
        raw_result={
            "ok": False,
            "tool": "review_manifest",
            "error_code": "REVIEW_MANIFEST_SUBJECT_HASH_MISMATCH",
            "message": "审查 subject 已变化。",
        },
        params={
            "phase": "read",
            "project_name": "colameta",
            "review_manifest_id": MANIFEST_ID,
            "review_manifest_subject_index": 1,
        },
    )

    assert response["outcome"] == "blocked"
    assert response["error"]["code"] == "STALE_CONTEXT"
    assert response["error"]["recoverable"] is True
    assert response["next_action"]["tool"] == "analyze_project_state"
    assert response["error"]["recovery"] == response["next_action"]
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


@pytest.mark.parametrize(
    "private_path",
    [
        "/home/reviewer/private.txt",
        "file:///home/reviewer/private.txt",
        r"C:\Users\Reviewer\private.txt",
        r"\\server\share\private.txt",
    ],
)
@pytest.mark.parametrize(
    "escaped_boundary",
    [
        "\\n",
        "\\r",
        "\\t",
        "\\b",
        "\\f",
        "\\n\\t",
        "\\u0000",
        "\\u000a",
        "\\u000A",
        "\\u001f",
        "\\u007f",
        "\\u0085",
        "\\u2028",
        "\\u002e",
        "\\u3002",
    ],
)
def test_public_text_redacts_private_paths_after_json_escaped_boundaries(
    escaped_boundary: str,
    private_path: str,
) -> None:
    serialized = f'{{"content":"safe{escaped_boundary}{private_path}"}}'

    public = commander_public_text(serialized)

    assert private_path not in public
    assert "<local-path>" in public


@pytest.mark.parametrize(
    "encoded_path",
    [
        "\\u002fhome/reviewer/private.txt",
        "\\u002Fhome/reviewer/private.txt",
        "\\/home/reviewer/private.txt",
        "\\\\u002fhome/reviewer/private.txt",
        "C:\\u005cUsers\\u005cReviewer\\u005cprivate.txt",
        "C:\\u005CUsers\\u005CReviewer\\u005Cprivate.txt",
        "\\u005c\\u005cserver\\u005cshare\\u005cprivate.txt",
        "C:\\\\Users\\\\Reviewer\\\\private.txt",
        "\\u005cu002fhome/reviewer/private.txt",
        "\\\\u005cu002fhome/reviewer/private.txt",
        (
            "C:\\u005cu005cUsers\\u005cu005cReviewer"
            "\\u005cu005cprivate.txt"
        ),
    ],
)
def test_public_text_redacts_json_escaped_path_separators(
    encoded_path: str,
) -> None:
    serialized = f'{{"content":"{encoded_path}"}}'

    public = commander_public_text(serialized)

    assert encoded_path not in public
    assert "<local-path>" in public


@pytest.mark.parametrize(
    "value",
    [
        json.dumps({"reason": r"\\server\share\private.txt"}),
        json.dumps(
            {
                "nested": json.dumps(
                    {"reason": r"\\server\share\private.txt"}
                )
            }
        ),
    ],
)
def test_public_text_redacts_json_serialized_unc_paths(value: str) -> None:
    public = commander_public_text(value)

    assert "server" not in public
    assert "<local-path>" in public


@pytest.mark.parametrize(
    "value",
    [
        "safe\\/relative.txt",
        "1\\/2",
        "https:\\/\\/example.com",
        "safe\\u002fhome/reviewer/private.txt",
    ],
)
def test_public_text_preserves_context_for_escaped_relative_separators(
    value: str,
) -> None:
    assert commander_public_text(value) == value


def test_public_text_scans_a_full_page_of_escaped_separators_in_linear_time(
) -> None:
    value = '{"content":"' + ("\\" * 12_000) + 'relative.txt"}'

    started = time.perf_counter()
    public = commander_public_text(value, max_chars=len(value) + 1)
    elapsed = time.perf_counter() - started

    assert public == value
    assert elapsed < 2.0


def test_public_text_scans_repeated_literal_uri_suffixes_in_linear_time(
) -> None:
    uri = "colameta://result-artifact/opaque_handle_123_/pages/{page}"
    value = '{"content":"' + (f"{uri}\\u0020Next " * 150) + '"}'

    started = time.perf_counter()
    public = commander_public_text(value, max_chars=len(value) + 1)
    elapsed = time.perf_counter() - started

    assert public == value
    assert elapsed < 2.0


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
    uri = "colameta://result-artifact/opaque_handle_123_/pages/{page}"
    nested = json.dumps({"nested": json.dumps({"uri": uri})})
    escaped_unicode = json.dumps({"note": f"取{uri}"})
    content = (
        "line one\n"
        "The bearer of this note may continue.\n"
        f"读取 {uri}。继续\n"
        f"Read {uri}。Next\n"
        f"📎{uri}✅Next\n"
        f"请读取{uri}继续\n"
        f"❤️{uri}👩‍💻Next\n"
        f"1️⃣{uri}#️⃣Next\n"
        f"↔️{uri}〰️Next\n"
        f"Read {uri}✅,Next\n"
        f"Read {uri}」.Next\n"
        "safe\\/relative.txt\n"
        "1\\/2\n"
        "https:\\/\\/example.com\n"
        f"{nested}\n"
        f"{escaped_unicode}\n"
    )
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
        "colameta://result-artifact/manage_files-opaque_123/pages/{page}",
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
    embedded = f"Read {uri}\n/home/reviewer/private.txt"
    assert commander_public_text(embedded) == f"Read {uri}\n<local-path>"
    assert commander_public_text(f'{{"uri":"{uri}"}}') == f'{{"uri":"{uri}"}}'
    escaped_space = f"{uri}\\u0020Next"
    assert commander_public_text(escaped_space) == escaped_space
    serialized_escaped_space = json.dumps({"note": escaped_space})
    assert commander_public_text(serialized_escaped_space) == (
        serialized_escaped_space
    )
    for punctuation in ".,;:!?":
        assert commander_public_text(f"Read {uri}{punctuation} Next") == (
            f"Read {uri}{punctuation} Next"
        )
    for punctuation in ("?!", ").", "}:"):
        assert commander_public_text(f"Read {uri}{punctuation} Next") == (
            f"Read {uri}{punctuation} Next"
        )
    for punctuation in "。，、；：！？…．｡":
        assert commander_public_text(f"读取 {uri}{punctuation}继续") == (
            f"读取 {uri}{punctuation}继续"
        )
        assert commander_public_text(f"Read {uri}{punctuation}Next") == (
            f"Read {uri}{punctuation}Next"
        )
    for closing in "）》】”’」』":
        assert commander_public_text(f"读取（{uri}{closing}") == (
            f"读取（{uri}{closing}"
        )
        assert commander_public_text(f"Read ({uri}{closing}Next") == (
            f"Read ({uri}{closing}Next"
        )
    assert commander_public_text(f"读取 {uri}。）继续") == (
        f"读取 {uri}。）继续"
    )
    assert commander_public_text(f"Read {uri}。）Next") == (
        f"Read {uri}。）Next"
    )
    assert commander_public_text(f"📎{uri}✅Next") == (
        f"📎{uri}✅Next"
    )
    assert commander_public_text(f"❤️{uri}👩‍💻Next") == (
        f"❤️{uri}👩‍💻Next"
    )
    for keycap in ("1️⃣", "#️⃣", "*️⃣", "1\u20e3"):
        assert commander_public_text(f"{keycap}{uri}") == f"{keycap}{uri}"
        assert commander_public_text(f"Read {uri}{keycap}Next") == (
            f"Read {uri}{keycap}Next"
        )
    for emoji in ("↔️", "〰️"):
        assert commander_public_text(f"{emoji}{uri}") == f"{emoji}{uri}"
        assert commander_public_text(f"Read {uri}{emoji}Next") == (
            f"Read {uri}{emoji}Next"
        )
    assert commander_public_text(f"Read {uri}✅,Next") == (
        f"Read {uri}✅,Next"
    )
    assert commander_public_text(f"Read {uri}」.Next") == (
        f"Read {uri}」.Next"
    )
    serialized = f'{{"content":"读取 {uri}。\\n继续"}}'
    assert commander_public_text(serialized) == serialized
    long_form_serialized = f'{{"content":"读取 {uri}。\\u000a继续"}}'
    assert commander_public_text(long_form_serialized) == long_form_serialized
    serialized_private_path = (
        f'{{"content":"读取 {uri}.\\n/home/reviewer/private.txt"}}'
    )
    public = commander_public_text(serialized_private_path)
    assert "/home/reviewer" not in public
    assert "<resource-uri>" in public or "<local-path>" in public


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
@pytest.mark.parametrize("separator", ["\u200b", "\\u200b"])
def test_public_text_preserves_zero_width_space_resource_boundaries(
    uri: str,
    separator: str,
) -> None:
    following = f"{uri}{separator}Next"
    preceding = f"Before{separator}{uri}"

    assert commander_public_text(following) == following
    assert commander_public_text(preceding) == preceding
    serialized = json.dumps({"following": following, "preceding": preceding})
    assert commander_public_text(serialized) == serialized
    private_suffix = f"{uri}{separator}/home/reviewer/private.txt"
    public_private_suffix = commander_public_text(private_suffix)
    assert uri in public_private_suffix
    assert "/home/reviewer" not in public_private_suffix
    assert "<local-path>" in public_private_suffix
    disallowed_suffix = (
        f"{uri}{separator}Colameta://review-manifest/opaque_handle_123_"
    )
    public_disallowed_suffix = commander_public_text(disallowed_suffix)
    assert uri in public_disallowed_suffix
    assert "Colameta://" not in public_disallowed_suffix
    assert "<resource-uri>" in public_disallowed_suffix


@pytest.mark.parametrize(
    "suffix",
    [
        "/private",
        "%2Fprivate",
        "@private",
        ":private",
        "=private",
        "&private",
        "?query=private",
        "??query",
        "??）query",
        "✅\u200dprivate",
        "✅\\u200dprivate",
        "✅\u20e3private",
        "✅\\u20e3private",
        "1\ufe0f",
        "1\\ufe0f",
        "1️⃣/private",
        "1\\ufe0f\\u20e3/private",
        "🙼private",
        "\\ud83d\\ude7cprivate",
        "⌿private",
        "\\u233fprivate",
        "::）private",
        "..）suffix",
        "::private",
        "..suffix",
        "／private",
        "∕private",
        "⁄private",
        "⧸private",
        "＿private",
        "‿private",
        "—private",
    ],
)
def test_public_text_does_not_preserve_an_extended_opaque_uri_lookalike(
    suffix: str,
) -> None:
    lookalike = (
        "Read colameta://result-artifact/opaque_handle_123_"
        f"/pages/{{page}}{suffix}"
    )

    assert commander_public_text(lookalike) == "Read <resource-uri>"


@pytest.mark.parametrize(
    "prefix",
    [
        "/",
        "\\",
        "@",
        "%",
        ":",
        "=",
        "&",
        "?",
        "#",
        "+",
        "_",
        "-",
        ".",
        "／",
        "∕",
        "⁄",
        "⧸",
        "＿",
        "‿",
        "—",
        "🙼",
        "\\ud83d\\ude7c",
        "⌿",
        "\\u233f",
    ],
)
def test_public_text_does_not_preserve_a_prefixed_opaque_uri_lookalike(
    prefix: str,
) -> None:
    uri = "colameta://result-artifact/opaque_handle_123_/pages/{page}"

    public = commander_public_text(f"Read {prefix}{uri}")

    assert uri not in public
    assert "<resource-uri>" in public


@pytest.mark.parametrize("opening", ["(", "[", "{", "<", "（", "【", "“"])
def test_public_text_preserves_opaque_uris_after_genuine_left_delimiters(
    opening: str,
) -> None:
    uri = "colameta://result-artifact/opaque_handle_123_/pages/{page}"

    assert commander_public_text(f"{opening}{uri}") == f"{opening}{uri}"


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
@pytest.mark.parametrize(
    "prefix",
    ["请读取", "版本１", "नमस्ते", "مُرَاجَعَةَ", "cafe\u0301"],
)
def test_public_text_preserves_opaque_uris_adjacent_to_unicode_prose(
    prefix: str,
    uri: str,
) -> None:
    value = f"{prefix}{uri}。"

    assert commander_public_text(value) == value
    assert commander_public_text(f"{prefix}{uri}继续") == (
        f"{prefix}{uri}继续"
    )
    assert commander_public_text(f"{prefix}{uri}１") == (
        f"{prefix}{uri}１"
    )


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
def test_public_text_preserves_opaque_uris_at_json_escaped_boundaries(
    uri: str,
) -> None:
    nested = json.dumps({"nested": json.dumps({"uri": uri})})
    escaped_unicode_prose = json.dumps({"note": f"取{uri}继续"})
    escaped_ascii_punctuation = f'{{"uri":"{uri}\\u002e"}}'
    escaped_unicode_punctuation = (
        f'{{"uri":"{uri}\\u3002\\u7ee7\\u7eed"}}'
    )
    escaped_unicode_ascii_prose = f'{{"uri":"{uri}\\u3002Next"}}'
    escaped_symbol_boundaries = json.dumps(
        {"note": f"📎{uri}✅Next"}
    )
    escaped_emoji_sequences = json.dumps(
        {"note": f"❤️{uri}👩‍💻Next"}
    )
    escaped_keycap_sequences = json.dumps(
        {"note": f"1️⃣{uri}#️⃣Next"}
    )
    escaped_non_so_emoji_sequences = json.dumps(
        {"note": f"↔️{uri}〰️Next"}
    )
    escaped_unicode_then_ascii_delimiters = json.dumps(
        {"note": f"{uri}✅,Next; {uri}」.Next"}
    )
    escaped_combining_mark_prose = json.dumps(
        {
            "note": (
                f"नमस्ते{uri}; مُرَاجَعَةَ{uri}; cafe\u0301{uri}"
            )
        }
    )
    fully_escaped_keycap_sequences = (
        f'{{"note":"\\u0031\\ufe0f\\u20e3{uri}'
        '\\u0023\\ufe0f\\u20e3Next"}'
    )

    assert commander_public_text(nested) == nested
    assert commander_public_text(escaped_unicode_prose) == (
        escaped_unicode_prose
    )
    assert commander_public_text(escaped_ascii_punctuation) == (
        escaped_ascii_punctuation
    )
    assert commander_public_text(escaped_unicode_punctuation) == (
        escaped_unicode_punctuation
    )
    assert commander_public_text(escaped_unicode_ascii_prose) == (
        escaped_unicode_ascii_prose
    )
    assert commander_public_text(escaped_symbol_boundaries) == (
        escaped_symbol_boundaries
    )
    assert commander_public_text(escaped_emoji_sequences) == (
        escaped_emoji_sequences
    )
    assert commander_public_text(escaped_keycap_sequences) == (
        escaped_keycap_sequences
    )
    assert commander_public_text(escaped_non_so_emoji_sequences) == (
        escaped_non_so_emoji_sequences
    )
    assert commander_public_text(escaped_unicode_then_ascii_delimiters) == (
        escaped_unicode_then_ascii_delimiters
    )
    assert "\\u0947" in escaped_combining_mark_prose
    assert "\\u064e" in escaped_combining_mark_prose
    assert "\\u0301" in escaped_combining_mark_prose
    assert commander_public_text(escaped_combining_mark_prose) == (
        escaped_combining_mark_prose
    )
    assert commander_public_text(fully_escaped_keycap_sequences) == (
        fully_escaped_keycap_sequences
    )


@pytest.mark.parametrize(
    "prefix",
    ["\u0301", "1\u0301", "\u20e3", "✅\u20e3"],
)
def test_public_text_rejects_opaque_uris_after_orphaned_prose_marks(
    prefix: str,
) -> None:
    uri = "colameta://result-artifact/opaque_handle_123_/pages/{page}"

    public = commander_public_text(f"{prefix}{uri}")

    assert uri not in public
    assert "<resource-uri>" in public


def test_public_text_redacts_an_opaque_uri_crossing_the_character_cutoff() -> None:
    uri = "colameta://result-artifact/opaque_handle_123_/pages/{page}"
    prefix = "x" * 570

    public = commander_public_text(f"{prefix} {uri}", max_chars=600)

    assert public == f"{prefix} <resource-uri>"
    assert len(public) <= 600


def test_public_text_preserves_an_opaque_uri_ending_at_the_character_cutoff() -> None:
    uri = "colameta://result-artifact/opaque_handle_123_/pages/{page}"
    max_chars = 100
    prefix = "x" * (max_chars - 2 - len(uri))

    public = commander_public_text(f"{prefix} {uri} tail", max_chars=max_chars)

    assert public == f"{prefix} {uri}…"
    assert len(public) == max_chars


@pytest.mark.parametrize(
    "value",
    [
        (
            "oauth_token="
            "colameta://result-artifact/opaque_handle_123_/pages/{page}"
        ),
        (
            "Bearer "
            "colameta://result-artifact/opaque_handle_123_/pages/{page}"
        ),
    ],
)
def test_public_text_redacts_sensitive_values_that_are_valid_opaque_uris(
    value: str,
) -> None:
    assert commander_public_text(value) == "<sensitive>"


def test_public_text_preserves_ordinary_bearer_prose() -> None:
    value = "The bearer of this note may continue."

    assert commander_public_text(value) == value


@pytest.mark.parametrize(
    "value",
    [
        '{"oauth\\u005ftoken":"synthetic-secret-value"}',
        '{"reason":"\\u0042earer abcdefghijklmnop"}',
        json.dumps(
            {
                "wrapped": (
                    '{"oauth\\\\u005ftoken":'
                    '"nested-synthetic-secret"}'
                )
            }
        ),
    ],
)
def test_public_text_redacts_json_escaped_sensitive_material(
    value: str,
) -> None:
    assert commander_public_text(value) == "<sensitive>"


@pytest.mark.parametrize(
    "value",
    [
        '{"reason":"manage\\u005ffiles"}',
        (
            '{"reason":"manage\\u005fexecutor'
            '\\u005fworkflow"}'
        ),
        json.dumps(
            {
                "wrapped": (
                    '{"reason":"manage\\u005ffiles"}'
                )
            }
        ),
    ],
)
def test_public_text_redacts_json_escaped_noncommander_tools(
    value: str,
) -> None:
    assert commander_public_text(value) == "<internal-tool>"


def test_public_text_redacts_json_escaped_dynamic_hidden_tool() -> None:
    value = '{"reason":"private\\u005frunner\\u005ftool"}'

    assert commander_public_text(
        value,
        forbidden_tools={"private_runner_tool"},
    ) == "<internal-tool>"


@pytest.mark.parametrize(
    "value",
    [
        '{"oauth\\u005ftokenizer":"synthetic-safe-value"}',
        '{"reason":"\\u0042earer of this note may continue."}',
        '{"reason":"\\u0042earer resource_metadata=available"}',
        '{"reason":"manage\\u005ffiling remains public prose"}',
        '{"tool":"read\\u005fresult\\u005fartifact"}',
    ],
)
def test_public_text_preserves_safe_json_escaped_prose(value: str) -> None:
    assert commander_public_text(value) == value


def test_blocked_message_with_uri_at_cutoff_remains_a_blocked_response() -> None:
    uri = "colameta://result-artifact/opaque_handle_123_/pages/{page}"
    prefix = "x" * 570
    response = build_commander_response(
        tool_name="manage_git",
        raw_result={
            "ok": False,
            "error": {
                "code": "GIT_WORKTREE_DIRTY",
                "message": f"{prefix} {uri}",
                "recoverable": True,
            },
        },
        params={"action": "commit_preview", "project_name": "colameta"},
    )

    assert response["outcome"] == "blocked"
    assert response["error"]["code"] == "WORKTREE_DIRTY"
    assert response["error"]["message"] == f"{prefix} <resource-uri>"
    validate_commander_response(response)


@pytest.mark.parametrize(
    "content",
    [
        (
            "oauth_token="
            "colameta://result-artifact/opaque_handle_123_/pages/{page}"
        ),
        (
            "Bearer "
            "colameta://result-artifact/opaque_handle_123_/pages/{page}"
        ),
        '{"oauth\\u005ftoken":"synthetic-secret-value"}',
        '{"reason":"\\u0042earer abcdefghijklmnop"}',
        (
            "colameta://result-artifact/opaque_handle_123_"
            "/pages/{page}??query"
        ),
        (
            "colameta://result-artifact/opaque_handle_123_"
            "/pages/{page}??）query"
        ),
        (
            "colameta://result-artifact/opaque_handle_123_"
            "/pages/{page}.\\n/home/reviewer/private.txt"
        ),
        (
            "colameta://result-artifact/opaque_handle_123_"
            "/pages/{page}.\\u000a/home/reviewer/private.txt"
        ),
        (
            "colameta://result-artifact/opaque_handle_123_"
            "/pages/{page}.\\n\\u002fhome/reviewer/private.txt"
        ),
        (
            "colameta://result-artifact/opaque_handle_123_"
            "/pages/{page}.\\nC:\\u005cUsers\\u005cReviewer"
            "\\u005cprivate.txt"
        ),
        '{"reason":"\\u002fhome/reviewer/private.txt"}',
        '{"reason":"\\u005cu002fhome/reviewer/private.txt"}',
        json.dumps({"reason": r"\\server\share\private.txt"}),
        (
            '{"reason":"safe C:\\u005cUsers\\u005cReviewer'
            '\\u005cprivate.txt"}'
        ),
        (
            "colameta://result-artifact/opaque_handle_123_"
            "/pages/{page}／private"
        ),
        (
            "colameta://result-artifact/opaque_handle_123_"
            "/pages/{page}∕private"
        ),
        (
            "colameta://result-artifact/opaque_handle_123_"
            "/pages/{page}\\u2215private"
        ),
        (
            "colameta://result-artifact/opaque_handle_123_"
            "/pages/{page}‿private"
        ),
        (
            "/colameta://result-artifact/opaque_handle_123_"
            "/pages/{page}"
        ),
        '{"uri":"colameta:\\/\\/result-artifact\\/short"}',
        (
            '{"uri":"colameta:\\u002f\\u002fresult-artifact'
            '\\u002fshort"}'
        ),
        (
            '{"valid":"colameta://result-artifact/opaque_handle_123_'
            '/pages/{page}","invalid":"colameta:\\/\\/'
            'result-artifact\\/short"}'
        ),
        (
            "colameta://result-artifact/opaque_handle_123_"
            "/pages/{page}\\u0020Colameta:\\u002f\\u002f"
            "review-manifest\\u002fshort"
        ),
        json.dumps(
            {
                "note": (
                    "colameta://result-artifact/opaque_handle_123_"
                    "/pages/{page}\\u0020Colameta:\\u002f\\u002f"
                    "review-manifest\\u002fshort"
                )
            }
        ),
        "Colameta://result-artifact/opaque_handle_123_",
        (
            '{"uri":"Colameta:\\/\\/result-artifact\\/'
            'opaque_handle_123_"}'
        ),
        (
            '{"uri":"COLAMETA:\\u002f\\u002fresult-artifact'
            '\\u002fopaque_handle_123_"}'
        ),
    ],
)
def test_typed_result_artifact_page_rejects_unsafe_opaque_uri_text(
    content: str,
) -> None:
    response = build_commander_response(
        tool_name="read_result_artifact",
        raw_result={
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
        },
        params={"artifact_id": ARTIFACT_ID, "artifact_page": 1},
    )

    assert response["outcome"] == "failed"
    assert response["error"]["code"] == "INTERNAL_RESULT_INVALID"
    assert "opaque_handle_123_" not in repr(response)
    validate_commander_response(response)


@pytest.mark.parametrize(
    "value",
    [
        '{"uri":"colameta:\\/\\/result-artifact\\/short"}',
        (
            '{"uri":"colameta:\\u002f\\u002fresult-artifact'
            '\\u002fshort"}'
        ),
        "Colameta://result-artifact/opaque_handle_123_",
        (
            '{"uri":"Colameta:\\/\\/result-artifact\\/'
            'opaque_handle_123_"}'
        ),
        (
            '{"uri":"COLAMETA:\\u002f\\u002fresult-artifact'
            '\\u002fopaque_handle_123_"}'
        ),
        (
            "colameta://result-artifact/opaque_handle_123_"
            "/pages/{page}\\u0020Colameta:\\u002f\\u002f"
            "review-manifest\\u002fshort"
        ),
        json.dumps(
            {
                "note": (
                    "colameta://result-artifact/opaque_handle_123_"
                    "/pages/{page}\\u0020Colameta:\\u002f\\u002f"
                    "review-manifest\\u002fshort"
                )
            }
        ),
    ],
)
def test_public_text_redacts_case_or_json_escaped_disallowed_resource_uri(
    value: str,
) -> None:
    assert commander_public_text(value) == "<resource-uri>"


def test_result_artifact_page_rejects_an_extended_opaque_uri_lookalike() -> None:
    content = (
        "colameta://result-artifact/opaquehandle12345"
        "/pages/{page}%2Fprivate"
    )
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
    assert "%2Fprivate" not in repr(response)
    validate_commander_response(response)


def test_review_manifest_subject_page_preserves_exact_hash_bound_text() -> None:
    uri = (
        "colameta://review-manifest/opaque_handle_123_"
        "/subjects/1/pages/{page}"
    )
    nested = json.dumps({"nested": json.dumps({"uri": uri})})
    escaped_unicode = json.dumps({"note": f"取{uri}"})
    content = (
        "# Review input\n\n"
        "The bearer of this note may continue.\n"
        f"Read {uri}\n"
        f"Read {uri}。Next\n"
        f"📎{uri}✅Next\n"
        f"请读取{uri}继续\n"
        f"❤️{uri}👩‍💻Next\n"
        f"1️⃣{uri}#️⃣Next\n"
        f"↔️{uri}〰️Next\n"
        f"Read {uri}✅,Next\n"
        f"Read {uri}」.Next\n"
        "safe\\/relative.txt\n"
        "1\\/2\n"
        "https:\\/\\/example.com\n"
        f"{nested}\n"
        f"{escaped_unicode}\n"
    )
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


@pytest.mark.parametrize(
    "content",
    [
        (
            "oauth_token="
            "colameta://review-manifest/opaque_handle_123_"
            "/subjects/1/pages/{page}"
        ),
        (
            "Bearer "
            "colameta://review-manifest/opaque_handle_123_"
            "/subjects/1/pages/{page}"
        ),
        '{"oauth\\u005ftoken":"synthetic-secret-value"}',
        '{"reason":"\\u0042earer abcdefghijklmnop"}',
        (
            "colameta://review-manifest/opaque_handle_123_"
            "/subjects/1/pages/{page}::private"
        ),
        (
            "colameta://review-manifest/opaque_handle_123_"
            "/subjects/1/pages/{page}??）query"
        ),
        (
            "colameta://review-manifest/opaque_handle_123_"
            "/subjects/1/pages/{page}.\\n/home/reviewer/private.txt"
        ),
        (
            "colameta://review-manifest/opaque_handle_123_"
            "/subjects/1/pages/{page}.\\u000a/home/reviewer/private.txt"
        ),
        (
            "colameta://review-manifest/opaque_handle_123_"
            "/subjects/1/pages/{page}.\\n\\u002fhome/reviewer/private.txt"
        ),
        (
            "colameta://review-manifest/opaque_handle_123_"
            "/subjects/1/pages/{page}.\\nC:\\u005cUsers"
            "\\u005cReviewer\\u005cprivate.txt"
        ),
        '{"reason":"\\u002fhome/reviewer/private.txt"}',
        '{"reason":"\\u005cu002fhome/reviewer/private.txt"}',
        json.dumps({"reason": r"\\server\share\private.txt"}),
        (
            '{"reason":"safe C:\\u005cUsers\\u005cReviewer'
            '\\u005cprivate.txt"}'
        ),
        (
            "colameta://review-manifest/opaque_handle_123_"
            "/subjects/1/pages/{page}＿private"
        ),
        (
            "colameta://review-manifest/opaque_handle_123_"
            "/subjects/1/pages/{page}∕private"
        ),
        (
            "colameta://review-manifest/opaque_handle_123_"
            "/subjects/1/pages/{page}\\u2215private"
        ),
        (
            "colameta://review-manifest/opaque_handle_123_"
            "/subjects/1/pages/{page}—private"
        ),
        (
            "@colameta://review-manifest/opaque_handle_123_"
            "/subjects/1/pages/{page}"
        ),
        (
            "colameta://review-manifest/opaque_handle_123_"
            "/subjects/1/pages/{page}\\u0020Colameta:\\u002f\\u002f"
            "result-artifact\\u002fshort"
        ),
        json.dumps(
            {
                "note": (
                    "colameta://review-manifest/opaque_handle_123_"
                    "/subjects/1/pages/{page}\\u0020"
                    "Colameta:\\u002f\\u002fresult-artifact\\u002fshort"
                )
            }
        ),
    ],
)
def test_typed_review_manifest_page_rejects_unsafe_opaque_uri_text(
    content: str,
) -> None:
    response = build_commander_response(
        tool_name="review_manifest",
        raw_result={
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
        },
        params={"phase": "read", "review_manifest_id": MANIFEST_ID},
    )

    assert response["outcome"] == "failed"
    assert response["error"]["code"] == "INTERNAL_RESULT_INVALID"
    assert "opaque_handle_123_" not in repr(response)
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
        lambda value: value["facts"].update(
            note='{"reason":"manage\\u005ffiles"}'
        ),
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
