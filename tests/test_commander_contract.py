from __future__ import annotations

import copy
import json
import time

import pytest
from jsonschema import Draft202012Validator

from runner.commander_contract import (
    COMMANDER_OUTCOMES,
    COMMANDER_PUBLIC_ERROR_CODES,
    COMMANDER_PUBLIC_MAX_DEPTH,
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


def _percent_encode_layers(value: str, layers: int) -> str:
    encoded = value
    for _ in range(layers):
        encoded = "".join(
            character
            if character.isalnum()
            else f"%{ord(character):02X}"
            for character in encoded
        )
    return encoded


def _nest_json_containers(value: object) -> object:
    nested = value
    for _ in range(COMMANDER_PUBLIC_MAX_DEPTH + 1):
        nested = {"layer": nested}
    return nested


ARTIFACT_ID = "artifact_handle_1234567890"
MANIFEST_ID = "manifest_handle_1234567890"
PREVIEW_ID = "preview_handle_1234567890"
RUN_ID = "validation_run_1234567890"
TOKEN_LIKE_OPAQUE_ID = "sk-" + ("R" * 29)
CONTENT_SHA256 = "a" * 64
PLAN_SHA256 = "b" * 64
GIT_HEAD = "c" * 40
EXPIRES_AT = "2026-07-30T18:00:00+08:00"
SYNTHETIC_JWT = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJzdWIiOiJzeW50aGV0aWMtdXNlciIsInNjb3BlIjoicmVhZCJ9."
    "c3ludGhldGljLXNpZ25hdHVyZS1ieXRlcw"
)
ESCAPED_SYNTHETIC_JWT = SYNTHETIC_JWT.replace(".", "\\u002e")
SYNTHETIC_AGE_X25519_IDENTITY = (
    "AGE-SECRET-KEY-1" + ("Q" * 58)
)
ESCAPED_SYNTHETIC_AGE_X25519_IDENTITY = (
    SYNTHETIC_AGE_X25519_IDENTITY.replace(
        "AGE-SECRET-KEY-",
        "\\u0041GE-SECRET-KEY-",
    )
)
SYNTHETIC_GITHUB_PAT = "ghp_" + ("A1" * 18)
SYNTHETIC_GITHUB_OAUTH_TOKEN = "gho_" + ("B2" * 18)
SYNTHETIC_GITHUB_FINE_GRAINED_PAT = (
    "github_pat_" + ("Ab_" * 27) + "Z"
)
SYNTHETIC_HUGGING_FACE_TOKEN = "hf_" + ("A1" * 17)
ESCAPED_SYNTHETIC_HUGGING_FACE_TOKEN = (
    SYNTHETIC_HUGGING_FACE_TOKEN.replace("hf_", "\\u0068f_")
)
SYNTHETIC_DIGITALOCEAN_TOKEN = "dop_v1_" + ("a1" * 32)
ESCAPED_SYNTHETIC_DIGITALOCEAN_TOKEN = (
    SYNTHETIC_DIGITALOCEAN_TOKEN.replace(
        "dop_v1_",
        "\\u0064op_v1_",
    )
)
SYNTHETIC_DATABRICKS_PAT = "dapi" + ("a1" * 16)
ESCAPED_SYNTHETIC_DATABRICKS_PAT = SYNTHETIC_DATABRICKS_PAT.replace(
    "dapi",
    "\\u0064api",
)
SYNTHETIC_SHOPIFY_ACCESS_TOKEN = "shpat_" + ("a1" * 16)
ESCAPED_SYNTHETIC_SHOPIFY_ACCESS_TOKEN = (
    SYNTHETIC_SHOPIFY_ACCESS_TOKEN.replace(
        "shpat_",
        "\\u0073hpat_",
    )
)
ESCAPED_SYNTHETIC_GITHUB_PAT = SYNTHETIC_GITHUB_PAT.replace(
    "ghp_",
    "\\u0067hp_",
)
SYNTHETIC_NPM_ACCESS_TOKEN = "npm_" + ("A1" * 18)
ESCAPED_SYNTHETIC_NPM_ACCESS_TOKEN = (
    SYNTHETIC_NPM_ACCESS_TOKEN.replace(
        "npm_",
        "\\u006epm_",
    )
)
SYNTHETIC_DOCKER_PAT = "dckr_pat_" + (("Ab1_-" * 5) + "Z9")
ESCAPED_SYNTHETIC_DOCKER_PAT = SYNTHETIC_DOCKER_PAT.replace(
    "dckr_pat_",
    "\\u0064ckr_pat_",
)
SYNTHETIC_PYPI_API_TOKEN = "pypi-" + ("Ab1_-" * 17)
SYNTHETIC_LONG_PYPI_API_TOKEN = "pypi-" + ("B2" * 160)
ESCAPED_SYNTHETIC_PYPI_API_TOKEN = (
    SYNTHETIC_PYPI_API_TOKEN.replace(
        "pypi-",
        "\\u0070ypi-",
    )
)
SYNTHETIC_SENDGRID_API_KEY = (
    f"SG.{'A' * 22}.{'B' * 43}"
)
ESCAPED_SYNTHETIC_SENDGRID_API_KEY = (
    SYNTHETIC_SENDGRID_API_KEY.replace(".", "\\u002e")
)
SYNTHETIC_GITLAB_PAT = "glpat-" + ("A1" * 10)
ESCAPED_SYNTHETIC_GITLAB_PAT = SYNTHETIC_GITLAB_PAT.replace(
    "glpat-",
    "\\u0067lpat-",
)
SYNTHETIC_GOOGLE_API_KEY = "AIza" + ("Ab1_-" * 7)
ESCAPED_SYNTHETIC_GOOGLE_API_KEY = SYNTHETIC_GOOGLE_API_KEY.replace(
    "AIza",
    "\\u0041Iza",
)
SYNTHETIC_GOOGLE_OAUTH_CLIENT_SECRET = (
    "GOCSPX-" + ("Ab1_-" * 5) + "Z9Q"
)
ESCAPED_SYNTHETIC_GOOGLE_OAUTH_CLIENT_SECRET = (
    SYNTHETIC_GOOGLE_OAUTH_CLIENT_SECRET.replace(
        "GOCSPX-",
        "\\u0047OCSPX-",
    )
)
SYNTHETIC_AWS_ACCESS_KEY_ID = "AKIA" + ("A1" * 8)
SYNTHETIC_AWS_TEMPORARY_ACCESS_KEY_ID = "ASIA" + ("B2" * 8)
ESCAPED_SYNTHETIC_AWS_ACCESS_KEY_ID = (
    SYNTHETIC_AWS_ACCESS_KEY_ID.replace(
        "AKIA",
        "\\u0041KIA",
    )
)
SYNTHETIC_STRIPE_SECRET_KEY = "sk_live_" + ("A1" * 12)
SYNTHETIC_STRIPE_RESTRICTED_KEY = "rk_test_" + ("B2" * 12)
ESCAPED_SYNTHETIC_STRIPE_SECRET_KEY = (
    SYNTHETIC_STRIPE_SECRET_KEY.replace(
        "sk_live_",
        "\\u0073k_live_",
    )
)
SYNTHETIC_SLACK_TOKEN = (
    "xoxb-123456789012-123456789012-" + ("Ab" * 24)
)
SYNTHETIC_SLACK_APP_TOKEN = "xapp-1-" + ("Cd" * 24)
ESCAPED_SYNTHETIC_SLACK_TOKEN = SYNTHETIC_SLACK_TOKEN.replace(
    "xoxb-",
    "\\u0078oxb-",
)
SYNTHETIC_OPENAI_PROJECT_KEY = "sk-proj-" + ("Ab1_" * 24)
ESCAPED_SYNTHETIC_OPENAI_PROJECT_KEY = (
    SYNTHETIC_OPENAI_PROJECT_KEY.replace(
        "sk-proj-",
        "\\u0073k-proj-",
    )
)
SYNTHETIC_TELEGRAM_BOT_TOKEN = "123456789:" + ("A" * 35)
ESCAPED_SYNTHETIC_TELEGRAM_BOT_TOKEN = (
    SYNTHETIC_TELEGRAM_BOT_TOKEN.replace(":", "\\u003a")
)
MAX_BUDGET_PERCENT_ENCODED_SAFE_PROSE = _percent_encode_layers(
    "public_key=visible",
    15,
)
EXHAUSTING_PERCENT_ENCODED_SAFE_PROSE = _percent_encode_layers(
    "public_key=visible",
    16,
)
EXHAUSTING_PERCENT_ENCODED_SENSITIVE_ASSIGNMENT = (
    _percent_encode_layers(
        "api_key=synthetic-budget-secret",
        16,
    )
)


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
            "next_actions": [
                {
                    "tool": "run_mcp_workflow",
                    "arguments": {"workflow": "git_restore_file"},
                    "reason": "不能绕过项目发现的嵌入恢复动作。",
                },
                {
                    "tool": "analyze_project_state",
                    "arguments": {},
                    "reason": "不能绕过项目发现的嵌入轮询动作。",
                },
            ],
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


def test_summary_redacts_complete_basic_authorization_material() -> None:
    response = build_commander_response(
        tool_name="render_commander_app",
        raw_result={
            "ok": True,
            "data": {
                "ok": True,
                "message": (
                    "Connector responded with Authorization: "
                    "Basic dXNlcjpwYXNzd29yZA==."
                ),
            },
        },
    )

    assert "Authorization" not in response["summary"]
    assert "dXNlcjpwYXNzd29yZA" not in response["summary"]
    assert response["summary"] == "<sensitive>"
    validate_commander_response(response)


@pytest.mark.parametrize(
    "message",
    [
        "Basic dXNlcjpwYXNzd29yZA==",
        '{"reason":"\\u0042asic dXNlcjpwYXNzd29yZA=="}',
    ],
)
def test_summary_redacts_standalone_basic_authorization_material(
    message: str,
) -> None:
    response = build_commander_response(
        tool_name="render_commander_app",
        raw_result={
            "ok": True,
            "data": {
                "ok": True,
                "message": message,
            },
        },
    )

    assert response["summary"] == "<sensitive>"
    assert "dXNlcjpwYXNzd29yZA" not in response["summary"]
    validate_commander_response(response)


@pytest.mark.parametrize(
    "message, secret_fragments",
    [
        (
            "Cookie: session=abc; csrf=def",
            ("session=abc", "csrf=def"),
        ),
        (
            (
                'Authorization: Digest username="Mufasa", '
                'response="deadbeef"'
            ),
            ("Mufasa", "deadbeef"),
        ),
    ],
)
def test_summary_redacts_complete_compound_credential_headers(
    message: str,
    secret_fragments: tuple[str, ...],
) -> None:
    response = build_commander_response(
        tool_name="render_commander_app",
        raw_result={
            "ok": True,
            "data": {
                "ok": True,
                "message": message,
            },
        },
    )

    assert response["summary"] == "<sensitive>"
    for fragment in secret_fragments:
        assert fragment not in response["summary"]
    validate_commander_response(response)


def test_summary_redacts_complete_quoted_credential_values() -> None:
    response = build_commander_response(
        tool_name="render_commander_app",
        raw_result={
            "ok": True,
            "data": {
                "ok": True,
                "message": (
                    'Connector rejected password="alpha beta gamma". Retry.'
                ),
            },
        },
    )

    assert response["summary"] == "<sensitive>"
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
                "C:/Users/Jenn/private.txt",
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
            "apiKey": "synthetic-secret-value",
            "client-key-data": "synthetic-kube-client-key-data",
            "private-key": "synthetic-private-key-value",
            "AWS_SECRET_ACCESS_KEY": "synthetic-aws-secret-value",
            "passPhrase": "synthetic-passphrase-value",
            "_auth": "synthetic-npm-auth-value",
        },
    }

    response = build_commander_response(
        tool_name="analyze_project_state",
        raw_result=raw_result,
    )
    rendered = repr(response)

    assert response["outcome"] == "completed"
    assert response["facts"]["paths"] == ["<local-path>"] * 6
    for forbidden in (
        "/home/",
        "/tmp/",
        "C:\\",
        "C:/",
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
        "apiKey",
        "client-key-data",
        "synthetic-kube-client-key-data",
        "private-key",
        "AWS_SECRET_ACCESS_KEY",
        "passPhrase",
        "synthetic-passphrase-value",
        "_auth",
        "synthetic-npm-auth-value",
        "Bearer private",
    ):
        assert forbidden not in rendered
    validate_commander_response(response)


def test_public_facts_do_not_trust_opaque_id_keys_as_handle_provenance() -> None:
    response = build_commander_response(
        tool_name="analyze_project_state",
        raw_result={
            "ok": True,
            "data": {
                "ok": True,
                "context_binding": _base_context_binding(),
                "metadata": {
                    "preview_id": SYNTHETIC_GITHUB_PAT,
                },
            },
        },
    )

    rendered = json.dumps(response, ensure_ascii=False)
    assert response["outcome"] == "completed"
    assert response["facts"]["metadata"]["preview_id"] == "<sensitive>"
    assert SYNTHETIC_GITHUB_PAT not in rendered
    validate_commander_response(response)


@pytest.mark.parametrize(
    "private_path",
    [
        "/home/reviewer/private.txt",
        "file:///home/reviewer/private.txt",
        r"C:\Users\Reviewer\private.txt",
        "C:/Users/Reviewer/private.txt",
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
        "C:\\u002fUsers\\u002fReviewer\\u002fprivate.txt",
        "C:\\/Users\\/Reviewer\\/private.txt",
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
        (
            "https://example.test/download"
            "?file=%2Fhome%2Fjenn%2Fsecret.txt"
        ),
        (
            "https://example.test/download"
            "?file=%252Fhome%252Fjenn%252Fsecret.txt"
        ),
        (
            '{"url":"https:\\/\\/example.test\\/download'
            '?file=\\u00252Fhome\\u00252Fjenn'
            '\\u00252Fsecret.txt"}'
        ),
        (
            "https://example.test/download"
            "?file=C%3A%5CUsers%5CJenn%5Csecret.txt"
        ),
        (
            "https://example.test/download"
            "?file=%5C%5Cserver%5Cshare%5Csecret.txt"
        ),
        (
            "https://example.test/download"
            "?file=%2F%2Fserver%2Fshare%2Fsecret.txt"
        ),
        json.dumps(
            {
                "wrapped": (
                    "https://example.test/download"
                    "?file=%25252Fhome%25252Fjenn"
                    "%25252Fsecret.txt"
                )
            }
        ),
    ],
)
def test_public_text_redacts_percent_encoded_private_paths(
    value: str,
) -> None:
    public = commander_public_text(value)

    assert public == "<local-path>"
    for fragment in ("home", "Users", "server", "secret.txt"):
        assert fragment not in public


@pytest.mark.parametrize(
    "value",
    [
        "https://example.test/download?file=docs%2FREADME.md",
        "https://example.test/ratio?value=1%2F2",
        (
            "https://example.test/next"
            "?url=https%3A%2F%2Fpublic.example%2Fdocs"
        ),
        "https://example.test/download?file=C%3Arelative.txt",
    ],
)
def test_public_text_preserves_percent_encoded_public_locations(
    value: str,
) -> None:
    assert commander_public_text(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "root:/home/jenn/secret.txt",
        "checkout:/tmp/private.txt",
        r"root:\Users\Jenn\secret.txt",
        r"checkout:\temp\private.txt",
        '{"note":"root:\\u002fhome\\u002fjenn\\u002fsecret.txt"}',
        (
            '{"note":"root:\\u005cUsers\\u005cJenn'
            '\\u005csecret.txt"}'
        ),
        "root:%2Fhome%2Fjenn%2Fsecret.txt",
        json.dumps(
            {
                "wrapped": (
                    "checkout%253A%252Ftmp%252Fprivate.txt"
                )
            }
        ),
    ],
)
def test_public_text_redacts_labeled_absolute_paths(
    value: str,
) -> None:
    public = commander_public_text(value)

    assert "<local-path>" in public
    for fragment in ("home", "Users", "tmp", "secret.txt", "private.txt"):
        assert fragment not in public


@pytest.mark.parametrize(
    "value",
    [
        "https://example.test/public/readme.txt",
        "custom://public.example/docs/readme.txt",
        "root://public.example/docs/readme.txt",
        "root:docs/README.md",
        "checkout:relative/project",
        "root:C:relative.txt",
        "urn:isbn:9780141036144",
    ],
)
def test_public_text_preserves_url_schemes_and_labeled_relative_paths(
    value: str,
) -> None:
    assert commander_public_text(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "//example.test/docs/page",
        "//cdn.example.test:8443/assets/app.js",
        "//localhost:8080/docs/page",
        "//[2001:db8::1]/docs/page",
        '{"url":"\\/\\/example.test\\/docs\\/page"}',
        (
            '{"url":"\\u002f\\u002fexample.test'
            '\\u002fdocs\\u002fpage"}'
        ),
        json.dumps(
            {
                "nested": json.dumps(
                    {"url": "//example.test/docs/page"}
                )
            }
        ),
    ],
)
def test_public_text_preserves_scheme_relative_public_urls(
    value: str,
) -> None:
    assert commander_public_text(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "//example.test/download?file=/home/jenn/private.txt",
        "//[2001:db8::1]/download?file=/home/jenn/private.txt",
        "//example.test/download?file=%2Fhome%2Fjenn%2Fprivate.txt",
    ],
)
def test_public_text_redacts_private_paths_in_scheme_relative_url_queries(
    value: str,
) -> None:
    public = commander_public_text(value)

    assert "<local-path>" in public
    assert "home" not in public
    assert "private.txt" not in public


@pytest.mark.parametrize(
    "value",
    [
        "C:/Users/Jenn/secret.txt",
        r"C:/Users\Jenn/secret.txt",
        r"C:\Users/Jenn\secret.txt",
        "c:/users/jenn/secret.txt",
        "C:/",
        '{"path":"C:/Users/Jenn/secret.txt"}',
        json.dumps(
            {
                "nested": json.dumps(
                    {"path": "C:/Users/Jenn/secret.txt"}
                )
            }
        ),
    ],
)
def test_public_text_redacts_forward_slash_windows_drive_paths(
    value: str,
) -> None:
    public = commander_public_text(value)

    assert "C:/" not in public.upper()
    assert "<local-path>" in public


@pytest.mark.parametrize(
    "value",
    [
        r"\Users\Jenn\secret.txt",
        r"\Windows\System32\config\SAM",
        r"\temp\secret.txt",
        json.dumps({"path": r"\Users\Jenn\secret.txt"}),
        (
            '{"path":"\\u005cUsers\\u005cJenn'
            '\\u005csecret.txt"}'
        ),
        json.dumps(
            {
                "nested": json.dumps(
                    {"path": r"\Windows\System32\config\SAM"}
                )
            }
        ),
    ],
)
def test_public_text_redacts_windows_current_drive_rooted_paths(
    value: str,
) -> None:
    public = commander_public_text(value)

    assert "<local-path>" in public
    for fragment in ("Users", "Windows", "secret.txt", "SAM"):
        assert fragment not in public


@pytest.mark.parametrize(
    "value",
    [
        "C:relative.txt",
        "drive C:relative/path.txt",
    ],
)
def test_public_text_preserves_windows_drive_relative_paths(
    value: str,
) -> None:
    assert commander_public_text(value) == value


@pytest.mark.parametrize(
    "value",
    [
        r"\\server/share\private.txt",
        "//server/share/private.txt",
        "///server/share/private.txt",
        "///example.test/share/private.txt",
        json.dumps({"reason": r"\\server/share\private.txt"}),
        json.dumps({"reason": r"\\server\share\private.txt"}),
        json.dumps({"reason": "//server/share/private.txt"}),
        '{"reason":"\\/\\/server\\/share\\/private.txt"}',
        (
            '{"reason":"\\u002f\\u002fserver\\u002fshare'
            '\\u002fprivate.txt"}'
        ),
        json.dumps(
            {
                "nested": json.dumps(
                    {"reason": r"\\server\share\private.txt"}
                )
            }
        ),
        json.dumps(
            {
                "nested": json.dumps(
                    {"reason": "//server/share/private.txt"}
                )
            }
        ),
    ],
)
def test_public_text_redacts_unc_paths_across_serialization(
    value: str,
) -> None:
    public = commander_public_text(value)

    assert "server" not in public
    assert "<local-path>" in public


@pytest.mark.parametrize(
    "value",
    [
        "safe\\/relative.txt",
        "1\\/2",
        "https://example.com/public/readme.txt",
        "https:\\/\\/example.com",
        "safe\\u002fhome/reviewer/private.txt",
        r"docs\README.md",
        r"safe\relative.txt",
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


def test_prevalidated_result_artifact_page_rejects_requested_page_mismatch(
) -> None:
    content = "page two must not satisfy a page-one request"
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
                    "page": 2,
                    "page_count": 2,
                    "page_char_start": len(content),
                    "page_char_end": len(content) * 2,
                    "content_sha256": CONTENT_SHA256,
                    "expires_at": EXPIRES_AT,
                    "content": content,
                },
                "content_sha256": CONTENT_SHA256,
                "expires_at": EXPIRES_AT,
            },
        },
        params={"artifact_id": ARTIFACT_ID, "artifact_page": 1},
        exact_evidence_prevalidated=True,
    )

    assert response["outcome"] == "failed"
    assert response["error"]["code"] == "INTERNAL_RESULT_INVALID"
    assert content not in repr(response)
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
            f"colameta://result-artifact/{TOKEN_LIKE_OPAQUE_ID}"
            "/pages/{page}"
        ),
        (
            f"colameta://result-artifact/{SYNTHETIC_DOCKER_PAT}"
            "/pages/{page}"
        ),
        (
            f"colameta://result-artifact/{SYNTHETIC_DIGITALOCEAN_TOKEN}"
            "/pages/{page}"
        ),
        (
            f"colameta://result-artifact/{SYNTHETIC_SHOPIFY_ACCESS_TOKEN}"
            "/pages/{page}"
        ),
        (
            "colameta://review-manifest/opaque_handle_123_"
            "/subjects/1/pages/{page}"
        ),
        (
            f"colameta://review-manifest/{TOKEN_LIKE_OPAQUE_ID}"
            "/subjects/1/pages/{page}"
        ),
        (
            f"colameta://review-manifest/{SYNTHETIC_DOCKER_PAT}"
            "/subjects/1/pages/{page}"
        ),
        (
            f"colameta://review-manifest/{SYNTHETIC_DIGITALOCEAN_TOKEN}"
            "/subjects/1/pages/{page}"
        ),
        (
            f"colameta://review-manifest/{SYNTHETIC_SHOPIFY_ACCESS_TOKEN}"
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
@pytest.mark.parametrize(
    "separator",
    ["\u200b", "\\u200b", "\ufeff", "\\ufeff"],
)
def test_public_text_preserves_format_separator_resource_boundaries(
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
        "−private",
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
        "−",
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
    "marker",
    ["*", "**", "***", "_", "__", "___", "\\u002a\\u002a"],
)
def test_public_text_preserves_opaque_uris_inside_markdown_emphasis(
    uri: str,
    marker: str,
) -> None:
    value = f"{marker}{uri}{marker}"
    serialized = json.dumps({"note": value})

    assert commander_public_text(value) == value
    assert commander_public_text(serialized) == serialized


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
def test_public_text_preserves_opaque_uri_markdown_link_labels(
    uri: str,
) -> None:
    value = f"[{uri}](https://example.test/evidence)"
    escaped = (
        f"\\u005b{uri}\\u005d\\u0028"
        "https://example.test/evidence\\u0029"
    )
    serialized = json.dumps({"note": value})
    nested = json.dumps({"note": json.dumps({"link": value})})

    assert commander_public_text(value) == value
    assert commander_public_text(escaped) == escaped
    assert commander_public_text(serialized) == serialized
    assert commander_public_text(nested) == nested


@pytest.mark.parametrize(
    "value",
    [
        (
            "colameta://result-artifact/"
            "opaque_handle_123_/pages/{page}]"
            "(https://example.test/evidence)"
        ),
        (
            "[colameta://result-artifact/"
            "opaque_handle_123_/pages/{page}]"
            "(ftp://example.test/evidence)"
        ),
        (
            "[colameta://result-artifact/"
            "opaque_handle_123_/pages/{page}]"
            "(https://example.test/evidence"
        ),
        (
            "prefix[colameta://result-artifact/"
            "opaque_handle_123_/pages/{page}]"
            "(https://example.test/evidence)"
        ),
        (
            "[colameta://result-artifact/"
            "opaque_handle_123_/pages/{page}]"
            "(https://example.test/evidence)tail"
        ),
    ],
)
def test_public_text_rejects_unpaired_or_unsafe_markdown_link_labels(
    value: str,
) -> None:
    public = commander_public_text(value)

    assert "colameta://" not in public
    assert "<resource-uri>" in public


def test_public_text_rejects_credentials_in_markdown_link_destination(
) -> None:
    uri = "colameta://result-artifact/opaque_handle_123_/pages/{page}"
    value = (
        f"[{uri}]"
        "(https://alice:synthetic-password@example.test/evidence)"
    )

    public = commander_public_text(value)

    assert public == "<sensitive>"
    assert "synthetic-password" not in public


@pytest.mark.parametrize(
    "value",
    [
        (
            "*colameta://result-artifact/"
            "opaque_handle_123_/pages/{page}_"
        ),
        (
            "**colameta://result-artifact/"
            "opaque_handle_123_/pages/{page}"
        ),
        (
            "colameta://result-artifact/"
            "opaque_handle_123_/pages/{page}**"
        ),
        (
            "prefix**colameta://result-artifact/"
            "opaque_handle_123_/pages/{page}**suffix"
        ),
        (
            "****colameta://result-artifact/"
            "opaque_handle_123_/pages/{page}****"
        ),
    ],
)
def test_public_text_does_not_treat_unpaired_markdown_as_uri_boundaries(
    value: str,
) -> None:
    public = commander_public_text(value)

    assert "colameta://" not in public
    assert "<resource-uri>" in public


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
@pytest.mark.parametrize("dash", ["–", "—"])
def test_public_text_preserves_opaque_uris_at_unicode_dash_boundaries(
    uri: str,
    dash: str,
) -> None:
    value = f"before{dash}{uri}{dash}continue"
    serialized = json.dumps({"content": value})

    assert commander_public_text(value) == value
    assert commander_public_text(serialized) == serialized


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
    ("closing", "opening"),
    [("」", "「"), ("”", "“"), ("）", "（")],
)
def test_public_text_preserves_opaque_uris_at_paired_punctuation_boundaries(
    uri: str,
    closing: str,
    opening: str,
) -> None:
    value = f"before{closing}{uri}{opening}continue"
    serialized = json.dumps({"content": value})

    assert commander_public_text(value) == value
    assert commander_public_text(serialized) == serialized


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
    "closing",
    [")", "]", "}", "\\u0029", "\\u005d", "\\u007d"],
)
def test_public_text_preserves_opaque_uris_after_ascii_closing_punctuation(
    uri: str,
    closing: str,
) -> None:
    value = f"before{closing}{uri}"
    serialized = json.dumps({"nested": value})

    assert commander_public_text(value) == value
    assert commander_public_text(serialized) == serialized


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
    "separator",
    [",", ";", "!", "?", "\\u002c", "\\u003b", "\\u0021", "\\u003f"],
)
def test_public_text_preserves_opaque_uris_after_ascii_separators(
    uri: str,
    separator: str,
) -> None:
    value = f"before{separator}{uri}"
    serialized = json.dumps({"nested": value})

    assert commander_public_text(value) == value
    assert commander_public_text(serialized) == serialized
    disallowed = (
        f"before{separator}"
        "Colameta://result-artifact/opaque_handle_123_"
    )
    public_disallowed = commander_public_text(disallowed)
    assert "Colameta://" not in public_disallowed
    assert "<resource-uri>" in public_disallowed


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
    "suffix",
    [
        "(see page 2)",
        "[details]",
        "{details}",
        "<details>",
        "\\u0028see page 2\\u0029",
        "\\u005bdetails\\u005d",
        "\\u007bdetails\\u007d",
        "\\u003cdetails\\u003e",
    ],
)
def test_public_text_preserves_opaque_uris_before_ascii_opening_punctuation(
    uri: str,
    suffix: str,
) -> None:
    value = f"Read {uri}{suffix}"
    nested = json.dumps({"nested": value})

    assert commander_public_text(value) == value
    assert commander_public_text(nested) == nested


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
    "uri",
    [
        "colameta://result-artifact/opaque_handle_123_/pages/{page}",
        (
            "colameta://review-manifest/opaque_handle_123_"
            "/subjects/1/pages/{page}"
        ),
    ],
)
@pytest.mark.parametrize("delimiter", ["\b", "\f", "\n", "\r", "\t"])
def test_public_text_preserves_opaque_uris_after_json_short_escapes(
    uri: str,
    delimiter: str,
) -> None:
    serialized = json.dumps({"content": f"{delimiter}{uri}"})
    nested = json.dumps({"nested": serialized})

    assert commander_public_text(serialized) == serialized
    assert commander_public_text(nested) == nested


@pytest.mark.parametrize("encoded_prefix", [r"\/", r"\\"])
def test_public_text_rejects_opaque_uris_after_non_delimiter_short_escapes(
    encoded_prefix: str,
) -> None:
    uri = "colameta://result-artifact/opaque_handle_123_/pages/{page}"
    serialized = f'{{"content":"{encoded_prefix}{uri}"}}'

    public = commander_public_text(serialized)

    assert uri not in public
    assert "<resource-uri>" in public


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


@pytest.mark.parametrize(
    "value",
    [
        "The bearer of this note may continue.",
        "Basic evidence remains available.",
        "Basic authentication is documented.",
    ],
)
def test_public_text_preserves_ordinary_authorization_scheme_prose(
    value: str,
) -> None:

    assert commander_public_text(value) == value


def test_public_text_redacts_complete_basic_authorization_value() -> None:
    value = "Authorization: Basic dXNlcjpwYXNzd29yZA=="

    assert commander_public_text(value) == "<sensitive>"


@pytest.mark.parametrize(
    "value",
    [
        "Basic dXNlcjpwYXNzd29yZA==",
        "basic YTpi",
        '{"reason":"\\u0042asic dXNlcjpwYXNzd29yZA=="}',
        json.dumps(
            {
                "wrapped": (
                    '{"reason":"\\\\u0042asic '
                    'dXNlcjpwYXNzd29yZA=="}'
                )
            }
        ),
    ],
)
def test_public_text_redacts_standalone_basic_authorization_values(
    value: str,
) -> None:
    public = commander_public_text(value)

    assert public == "<sensitive>"
    assert "dXNlcjpwYXNzd29yZA" not in public
    assert "YTpi" not in public


@pytest.mark.parametrize(
    "value",
    [
        SYNTHETIC_JWT,
        f"Provider returned {SYNTHETIC_JWT}",
        json.dumps({"access": SYNTHETIC_JWT}),
        f'{{"access":"{ESCAPED_SYNTHETIC_JWT}"}}',
        json.dumps(
            {
                "wrapped": json.dumps(
                    {"access": ESCAPED_SYNTHETIC_JWT}
                )
            }
        ),
    ],
)
def test_public_text_redacts_structurally_valid_standalone_jwts(
    value: str,
) -> None:
    public = commander_public_text(value)

    assert public == "<sensitive>"
    assert SYNTHETIC_JWT.split(".", maxsplit=1)[0] not in public


@pytest.mark.parametrize(
    "value",
    [
        SYNTHETIC_GITHUB_PAT,
        f"Provider returned {SYNTHETIC_GITHUB_OAUTH_TOKEN}",
        json.dumps({"access": SYNTHETIC_GITHUB_FINE_GRAINED_PAT}),
        f'{{"access":"{ESCAPED_SYNTHETIC_GITHUB_PAT}"}}',
        json.dumps(
            {
                "wrapped": json.dumps(
                    {"access": ESCAPED_SYNTHETIC_GITHUB_PAT}
                )
            }
        ),
        SYNTHETIC_HUGGING_FACE_TOKEN,
        (
            "https://huggingface.example.invalid/callback?token="
            f"{SYNTHETIC_HUGGING_FACE_TOKEN}"
        ),
        f'{{"access":"{ESCAPED_SYNTHETIC_HUGGING_FACE_TOKEN}"}}',
        json.dumps(
            {
                "wrapped": json.dumps(
                    {"access": ESCAPED_SYNTHETIC_HUGGING_FACE_TOKEN}
                )
            }
        ),
        SYNTHETIC_DIGITALOCEAN_TOKEN,
        (
            "https://cloud.digitalocean.com/account/api/tokens"
            f"?token={SYNTHETIC_DIGITALOCEAN_TOKEN}"
        ),
        SYNTHETIC_DIGITALOCEAN_TOKEN.replace(
            "dop_v1_",
            "dop%5Fv1%5F",
        ),
        f'{{"access":"{ESCAPED_SYNTHETIC_DIGITALOCEAN_TOKEN}"}}',
        json.dumps(
            {
                "wrapped": json.dumps(
                    {"access": ESCAPED_SYNTHETIC_DIGITALOCEAN_TOKEN}
                )
            }
        ),
        SYNTHETIC_DATABRICKS_PAT,
        (
            "https://workspace.example.invalid/login?token="
            f"{SYNTHETIC_DATABRICKS_PAT}"
        ),
        SYNTHETIC_DATABRICKS_PAT.replace("dapi", "d%61pi"),
        f'{{"access":"{ESCAPED_SYNTHETIC_DATABRICKS_PAT}"}}',
        json.dumps(
            {
                "wrapped": json.dumps(
                    {"access": ESCAPED_SYNTHETIC_DATABRICKS_PAT}
                )
            }
        ),
        SYNTHETIC_SHOPIFY_ACCESS_TOKEN,
        (
            "https://shop.example.invalid/admin?token="
            f"{SYNTHETIC_SHOPIFY_ACCESS_TOKEN}"
        ),
        SYNTHETIC_SHOPIFY_ACCESS_TOKEN.replace("shpat_", "shpat%5F"),
        f'{{"access":"{ESCAPED_SYNTHETIC_SHOPIFY_ACCESS_TOKEN}"}}',
        json.dumps(
            {
                "wrapped": json.dumps(
                    {"access": ESCAPED_SYNTHETIC_SHOPIFY_ACCESS_TOKEN}
                )
            }
        ),
        SYNTHETIC_NPM_ACCESS_TOKEN,
        (
            "https://registry.npmjs.org/callback?token="
            f"{SYNTHETIC_NPM_ACCESS_TOKEN}"
        ),
        f'{{"access":"{ESCAPED_SYNTHETIC_NPM_ACCESS_TOKEN}"}}',
        json.dumps(
            {
                "wrapped": json.dumps(
                    {"access": ESCAPED_SYNTHETIC_NPM_ACCESS_TOKEN}
                )
            }
        ),
        SYNTHETIC_DOCKER_PAT,
        (
            "https://hub.docker.com/settings/security?token="
            f"{SYNTHETIC_DOCKER_PAT}"
        ),
        SYNTHETIC_DOCKER_PAT.replace("dckr_pat_", "dckr%5Fpat%5F"),
        f'{{"access":"{ESCAPED_SYNTHETIC_DOCKER_PAT}"}}',
        json.dumps(
            {
                "wrapped": json.dumps(
                    {"access": ESCAPED_SYNTHETIC_DOCKER_PAT}
                )
            }
        ),
        SYNTHETIC_PYPI_API_TOKEN,
        SYNTHETIC_LONG_PYPI_API_TOKEN,
        (
            "https://upload.pypi.org/legacy/?token="
            f"{SYNTHETIC_PYPI_API_TOKEN}"
        ),
        SYNTHETIC_PYPI_API_TOKEN.replace("pypi-", "pypi%2D"),
        f'{{"access":"{ESCAPED_SYNTHETIC_PYPI_API_TOKEN}"}}',
        json.dumps(
            {
                "wrapped": json.dumps(
                    {"access": ESCAPED_SYNTHETIC_PYPI_API_TOKEN}
                )
            }
        ),
        SYNTHETIC_SENDGRID_API_KEY,
        (
            "https://api.sendgrid.com/v3/?access="
            f"{SYNTHETIC_SENDGRID_API_KEY}"
        ),
        SYNTHETIC_SENDGRID_API_KEY.replace(".", "%2E"),
        f'{{"access":"{ESCAPED_SYNTHETIC_SENDGRID_API_KEY}"}}',
        json.dumps(
            {
                "wrapped": json.dumps(
                    {"access": ESCAPED_SYNTHETIC_SENDGRID_API_KEY}
                )
            }
        ),
        SYNTHETIC_GITLAB_PAT,
        (
            "https://gitlab.example.invalid/callback?token="
            f"{SYNTHETIC_GITLAB_PAT}"
        ),
        f'{{"access":"{ESCAPED_SYNTHETIC_GITLAB_PAT}"}}',
        json.dumps(
            {
                "wrapped": json.dumps(
                    {"access": ESCAPED_SYNTHETIC_GITLAB_PAT}
                )
            }
        ),
        SYNTHETIC_GOOGLE_API_KEY,
        (
            "https://googleapis.example.invalid/callback?key="
            f"{SYNTHETIC_GOOGLE_API_KEY}"
        ),
        f'{{"access":"{ESCAPED_SYNTHETIC_GOOGLE_API_KEY}"}}',
        json.dumps(
            {
                "wrapped": json.dumps(
                    {"access": ESCAPED_SYNTHETIC_GOOGLE_API_KEY}
                )
            }
        ),
        SYNTHETIC_GOOGLE_OAUTH_CLIENT_SECRET,
        (
            "https://oauth2.example.invalid/callback?client_secret="
            f"{SYNTHETIC_GOOGLE_OAUTH_CLIENT_SECRET}"
        ),
        SYNTHETIC_GOOGLE_OAUTH_CLIENT_SECRET.replace("-", "%2D"),
        (
            '{"access":"'
            f"{ESCAPED_SYNTHETIC_GOOGLE_OAUTH_CLIENT_SECRET}"
            '"}'
        ),
        json.dumps(
            {
                "wrapped": json.dumps(
                    {
                        "access": (
                            ESCAPED_SYNTHETIC_GOOGLE_OAUTH_CLIENT_SECRET
                        )
                    }
                )
            }
        ),
        SYNTHETIC_AWS_ACCESS_KEY_ID,
        SYNTHETIC_AWS_TEMPORARY_ACCESS_KEY_ID,
        (
            "https://aws.example.invalid/callback?access_key_id="
            f"{SYNTHETIC_AWS_ACCESS_KEY_ID}"
        ),
        f'{{"access":"{ESCAPED_SYNTHETIC_AWS_ACCESS_KEY_ID}"}}',
        json.dumps(
            {
                "wrapped": json.dumps(
                    {"access": ESCAPED_SYNTHETIC_AWS_ACCESS_KEY_ID}
                )
            }
        ),
        SYNTHETIC_STRIPE_SECRET_KEY,
        SYNTHETIC_STRIPE_RESTRICTED_KEY,
        (
            "https://stripe.example.invalid/callback?key="
            f"{SYNTHETIC_STRIPE_SECRET_KEY}"
        ),
        f'{{"access":"{ESCAPED_SYNTHETIC_STRIPE_SECRET_KEY}"}}',
        json.dumps(
            {
                "wrapped": json.dumps(
                    {"access": ESCAPED_SYNTHETIC_STRIPE_SECRET_KEY}
                )
            }
        ),
        SYNTHETIC_SLACK_TOKEN,
        SYNTHETIC_SLACK_APP_TOKEN,
        f'{{"access":"{ESCAPED_SYNTHETIC_SLACK_TOKEN}"}}',
        json.dumps(
            {
                "wrapped": json.dumps(
                    {"access": ESCAPED_SYNTHETIC_SLACK_TOKEN}
                )
            }
        ),
        SYNTHETIC_OPENAI_PROJECT_KEY,
        (
            "https://provider.example.invalid/callback?key="
            f"{SYNTHETIC_OPENAI_PROJECT_KEY}"
        ),
        f'{{"key":"{ESCAPED_SYNTHETIC_OPENAI_PROJECT_KEY}"}}',
        json.dumps(
            {
                "wrapped": json.dumps(
                    {"key": ESCAPED_SYNTHETIC_OPENAI_PROJECT_KEY}
                )
            }
        ),
    ],
)
def test_public_text_redacts_standalone_provider_access_tokens(
    value: str,
) -> None:
    public = commander_public_text(value)

    assert public == "<sensitive>"
    assert "ghp_" not in public
    assert "gho_" not in public
    assert "github_pat_" not in public
    assert "hf_" not in public
    assert "dapi" not in public
    assert "dckr_pat_" not in public
    assert "shpat_" not in public
    assert "SG." not in public
    assert "GOCSPX-" not in public


@pytest.mark.parametrize(
    "value",
    [
        SYNTHETIC_TELEGRAM_BOT_TOKEN,
        (
            "https://telegram.example.invalid/bot?token="
            f"{SYNTHETIC_TELEGRAM_BOT_TOKEN}"
        ),
        SYNTHETIC_TELEGRAM_BOT_TOKEN.replace(":", "%3A"),
        f'{{"access":"{ESCAPED_SYNTHETIC_TELEGRAM_BOT_TOKEN}"}}',
        json.dumps(
            {
                "wrapped": (
                    SYNTHETIC_TELEGRAM_BOT_TOKEN.replace(":", "%253A")
                )
            }
        ),
    ],
)
def test_public_text_redacts_standalone_telegram_bot_tokens(
    value: str,
) -> None:
    public = commander_public_text(value)

    assert public == "<sensitive>"
    assert "123456789" not in public


@pytest.mark.parametrize(
    "value",
    [
        (
            "https://provider.example.invalid/callback"
            "?api%5Fkey=synthetic-percent-secret"
        ),
        (
            "https://provider.example.invalid/callback"
            "?%61pi%5fkey%3dsynthetic-fully-encoded-secret"
        ),
        (
            "https://provider.example.invalid/callback"
            "?api%255Fkey=synthetic-double-encoded-secret"
        ),
        (
            '{"url":"https:\\/\\/provider.example.invalid\\/callback'
            '?api\\u00255Fkey=synthetic-json-encoded-secret"}'
        ),
        json.dumps(
            {
                "wrapped": json.dumps(
                    {
                        "url": (
                            "https://provider.example.invalid/callback"
                            "?api%255Fkey="
                            "synthetic-nested-percent-secret"
                        )
                    }
                )
            }
        ),
    ],
)
def test_public_text_redacts_percent_encoded_sensitive_key_assignments(
    value: str,
) -> None:
    public = commander_public_text(value)

    assert public == "<sensitive>"
    assert "synthetic-" not in public


@pytest.mark.parametrize(
    "value",
    [
        "api+key=synthetic-standalone-form-secret",
        (
            "https://provider.example.invalid/callback"
            "?api+key=synthetic-form-secret"
        ),
        (
            "https://provider.example.invalid/callback"
            "?api%2Bkey=synthetic-percent-plus-form-secret"
        ),
        (
            '{"url":"https:\\/\\/provider.example.invalid\\/callback'
            '?api\\u002bkey=synthetic-json-plus-form-secret"}'
        ),
        json.dumps(
            {
                "wrapped": (
                    "https://provider.example.invalid/callback"
                    "?api%252Bkey=synthetic-nested-plus-form-secret"
                )
            }
        ),
    ],
)
def test_public_text_redacts_form_encoded_sensitive_key_assignments(
    value: str,
) -> None:
    public = commander_public_text(value)

    assert public == "<sensitive>"
    assert "synthetic-" not in public


@pytest.mark.parametrize(
    "value",
    [
        (
            "https://client.example.invalid/callback"
            "?code=synthetic-oauth-code&state=synthetic-oauth-state"
        ),
        (
            "https://client.example.invalid/callback"
            "?state=synthetic-reordered-state"
            "&code=synthetic-reordered-code"
        ),
        (
            "https://client.example.invalid/callback"
            "?%63ode=synthetic-percent-code"
            "&st%61te=synthetic-percent-state"
        ),
        (
            '{"url":"https:\\/\\/client.example.invalid\\/callback'
            '?code\\u003dsynthetic-json-code'
            '\\u0026state\\u003dsynthetic-json-state"}'
        ),
        json.dumps(
            {
                "wrapped": (
                    "https:\\u002f\\u002fclient.example.invalid/callback"
                    "?code%253Dsynthetic-nested-code"
                    "%2526state%253Dsynthetic-nested-state"
                )
            }
        ),
    ],
)
def test_public_text_redacts_oauth_authorization_code_callbacks(
    value: str,
) -> None:
    public = commander_public_text(value)

    assert public == "<sensitive>"
    assert "synthetic-" not in public


@pytest.mark.parametrize(
    "value",
    [
        json.dumps(
            {
                "device_code": "synthetic-device-secret",
                "user_code": "ABCD-EFGH",
            }
        ),
        json.dumps(
            {
                "device_code": "synthetic-device-uri-secret",
                "verification_uri": (
                    "https://provider.example.invalid/device"
                ),
            }
        ),
        json.dumps(
            {
                "device_code": "synthetic-device-expiry-secret",
                "expires_in": 600,
                "interval": 5,
            }
        ),
        (
            'OAuth response: {"device_code":'
            '"synthetic-embedded-device-secret",'
            '"user_code":"IJKL-MNOP"}'
        ),
        (
            '{"device\\u005fcode":"synthetic-escaped-device-secret",'
            '"user\\u005fcode":"QRST-UVWX"}'
        ),
        json.dumps(
            {
                "wrapped": json.dumps(
                    {
                        "device_code": (
                            "synthetic-nested-device-secret"
                        ),
                        "verification_uri_complete": (
                            "https://provider.example.invalid/device"
                            "?user_code=YZ12-3456"
                        ),
                    }
                )
            }
        ),
        _percent_encode_layers(
            json.dumps(
                {
                    "device_code": (
                        "synthetic-percent-device-secret"
                    ),
                    "user_code": "7890-ABCD",
                }
            ),
            1,
        ),
    ],
)
def test_public_text_redacts_oauth_device_authorization_codes(
    value: str,
) -> None:
    public = commander_public_text(value)

    assert public == "<sensitive>"
    assert "synthetic-" not in public


@pytest.mark.parametrize(
    "value",
    [
        json.dumps(
            {
                "device_code": "public-sensor-identifier",
                "model": "weather-station",
            }
        ),
        json.dumps(
            {
                "device_code_hint": "public-prefix",
                "user_code": "display-only",
            }
        ),
        json.dumps(
            {
                "device_code": "",
                "user_code": "display-only",
            }
        ),
        "The device_code field identifies a hardware device.",
    ],
)
def test_public_text_preserves_unrelated_device_identifiers(
    value: str,
) -> None:
    assert commander_public_text(value) == value


@pytest.mark.parametrize(
    "credential",
    [
        {
            "kty": "RSA",
            "d": "synthetic-depth-private-coordinate",
        },
        {
            "device_code": "synthetic-depth-device-secret",
            "user_code": "ABCD-EFGH",
        },
    ],
    ids=("private-jwk", "oauth-device"),
)
def test_public_text_fails_closed_for_depth_exhausted_credentials(
    credential: dict[str, str],
) -> None:
    value = json.dumps(_nest_json_containers(credential))

    public = commander_public_text(value)

    assert public == "<sensitive>"
    assert "synthetic-depth" not in public


@pytest.mark.parametrize(
    "public_mapping",
    [
        {
            "kty": "RSA",
            "n": "synthetic-public-modulus",
            "e": "AQAB",
        },
        {
            "device_code": "public-sensor-identifier",
            "model": "weather-station",
        },
    ],
    ids=("public-jwk", "device-identifier"),
)
def test_public_text_preserves_depth_exhausted_public_mappings(
    public_mapping: dict[str, str],
) -> None:
    value = json.dumps(_nest_json_containers(public_mapping))

    assert commander_public_text(value) == value


def test_commander_response_omits_structured_oauth_device_response() -> None:
    device_secret = "synthetic-structured-device-secret"
    response = build_commander_response(
        tool_name="list_registered_projects",
        raw_result={
            "ok": True,
            "status": "clean",
            "device_authorization": {
                "device_code": device_secret,
                "user_code": "EFGH-IJKL",
                "expires_in": 600,
            },
        },
        params={},
    )

    rendered = json.dumps(response, ensure_ascii=False)
    assert device_secret not in rendered
    assert response["facts"]["status"] == "clean"
    assert "device_authorization" not in response["facts"]
    validate_commander_response(response)


def test_public_text_fails_closed_only_when_decode_budget_is_exhausted(
) -> None:
    assert (
        commander_public_text(MAX_BUDGET_PERCENT_ENCODED_SAFE_PROSE)
        == MAX_BUDGET_PERCENT_ENCODED_SAFE_PROSE
    )
    assert (
        commander_public_text(EXHAUSTING_PERCENT_ENCODED_SAFE_PROSE)
        == "<sensitive>"
    )
    assert (
        commander_public_text(
            EXHAUSTING_PERCENT_ENCODED_SENSITIVE_ASSIGNMENT
        )
        == "<sensitive>"
    )


@pytest.mark.parametrize(
    "value",
    [
        '{"apiKey":"synthetic-secret-value"}',
        '{"API Key":"synthetic-spaced-secret"}',
        "api key: synthetic-unquoted-spaced-secret",
        "apikey=synthetic-joined-secret",
        "stripe.api-key=synthetic-dotted-secret",
        "private-key=synthetic-private-key-value",
        (
            "client-key-data: "
            "c3ludGhldGljLWt1YmUtY2xpZW50LXByaXZhdGUta2V5"
        ),
        (
            '{"client\\u002dkey\\u002ddata":'
            '"synthetic-encoded-kube-client-key-data"}'
        ),
        json.dumps(
            {
                "wrapped": (
                    "client\\u002dkey\\u002ddata: "
                    "synthetic-nested-kube-client-key-data"
                )
            }
        ),
        "AWS_SECRET_ACCESS_KEY=synthetic-aws-secret-value",
        "AWS_ACCESS_KEY_ID=synthetic-aws-access-id",
        "AWSSecretAccessKey=synthetic-camel-aws-secret",
        'vendorApiKey="alpha beta gamma"',
        "apiKey=delta epsilon zeta",
        r'{\"apiKey\":\"synthetic-escaped-secret\"}',
        (
            r"api\u0020key\u003a "
            "synthetic-encoded-unquoted-spaced-secret"
        ),
        json.dumps(
            {
                "wrapped": (
                    r'{\"private-key\":\"synthetic-nested-secret\"}'
                )
            }
        ),
        json.dumps(
            {
                "wrapped": (
                    r"api\u0020key\u003a "
                    "synthetic-nested-unquoted-spaced-secret"
                )
            }
        ),
    ],
)
def test_public_text_redacts_normalized_sensitive_key_assignments(
    value: str,
) -> None:
    public = commander_public_text(value)

    assert "<sensitive>" in public
    for fragment in (
        "synthetic-secret-value",
        "synthetic-spaced-secret",
        "synthetic-unquoted-spaced-secret",
        "synthetic-joined-secret",
        "synthetic-dotted-secret",
        "synthetic-private-key-value",
        "c3ludGhldGljLWt1YmUtY2xpZW50LXByaXZhdGUta2V5",
        "synthetic-encoded-kube-client-key-data",
        "synthetic-nested-kube-client-key-data",
        "synthetic-aws-secret-value",
        "synthetic-aws-access-id",
        "synthetic-camel-aws-secret",
        "alpha",
        "beta",
        "gamma",
        "delta",
        "epsilon",
        "zeta",
        "synthetic-escaped-secret",
        "synthetic-encoded-unquoted-spaced-secret",
        "synthetic-nested-secret",
        "synthetic-nested-unquoted-spaced-secret",
    ):
        assert fragment not in public


@pytest.mark.parametrize(
    "value",
    [
        "password[]=synthetic-bracket-secret",
        "database[password]=synthetic-nested-bracket-secret",
        (
            "credentials[0][client_secret]="
            "synthetic-indexed-bracket-secret"
        ),
        (
            "root"
            + ("[item]" * 12)
            + "[password]=synthetic-deep-bracket-secret"
        ),
        '{"password[]":"synthetic-json-bracket-secret"}',
        (
            '{"database\\u005bpassword\\u005d":'
            '"synthetic-escaped-bracket-secret"}'
        ),
        (
            "database%5Bpassword%5D="
            "synthetic-percent-bracket-secret"
        ),
        json.dumps(
            {
                "wrapped": (
                    "credentials\\u005b0\\u005d"
                    "\\u005bclient_secret\\u005d="
                    "synthetic-nested-encoded-bracket-secret"
                )
            }
        ),
    ],
)
def test_public_text_redacts_bracket_notation_assignments(
    value: str,
) -> None:
    public = commander_public_text(value)

    assert public == "<sensitive>"
    assert "synthetic-" not in public


@pytest.mark.parametrize(
    "value",
    [
        "filters[region]=public",
        "database[public_key]=public",
        "items[0][label]=public",
        "filters" + ("[region]" * 12) + "=public",
        "password[=malformed-public-example",
        "Document database[password] fields without assigning one.",
    ],
)
def test_public_text_preserves_safe_bracket_notation(
    value: str,
) -> None:
    assert commander_public_text(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "<password>synthetic-xml-secret</password>",
        "<clientSecret>synthetic-camel-xml-secret</clientSecret>",
        (
            "<config:api-key>"
            "synthetic-namespaced-xml-secret"
            "</config:api-key>"
        ),
        (
            '{"xml":"\\u003cpassword\\u003e'
            'synthetic-encoded-xml-secret'
            '\\u003c/password\\u003e"}'
        ),
        json.dumps(
            {
                "wrapped": (
                    "\\u003cclient-secret\\u003e"
                    "synthetic-nested-xml-secret"
                    "\\u003c/client-secret\\u003e"
                )
            }
        ),
        (
            "<password>"
            "colameta://result-artifact/opaque_handle_123_"
            "</password>"
        ),
        '<password value="synthetic-xml-attribute-secret"/>',
        (
            '<property name="password" '
            'value="synthetic-xml-name-value-secret"/>'
        ),
        (
            "<field value='synthetic-xml-type-value-secret' "
            "type='clientSecret'/>"
        ),
        (
            '<entry key="password" '
            'value="synthetic-xml-key-value-secret"/>'
        ),
        (
            '<add key="ClientSecret" '
            'value="synthetic-xml-client-key-value-secret"/>'
        ),
        (
            "<setting config:key='api-key'>"
            "synthetic-xml-namespaced-key-body-secret"
            "</setting>"
        ),
        (
            '{"xml":"\\u003centry\\u0020'
            'key=\\u0022password\\u0022\\u0020'
            'value=\\u0022synthetic-encoded-xml-key-secret'
            '\\u0022/\\u003e"}'
        ),
        (
            '<property name="password" '
            'value="synthetic-xml-greater-than>secret"/>'
        ),
        (
            '{"xml":"\\u003cproperty\\u0020'
            'name=\\u0022password\\u0022\\u0020'
            'value=\\u0022synthetic-encoded-xml-attribute-secret'
            '\\u0022/\\u003e"}'
        ),
        (
            "&lt;property name=&quot;password&quot; "
            "value=&quot;synthetic-entity-xml-attribute-secret&quot;/&gt;"
        ),
        (
            '<property name="password">'
            "synthetic-xml-element-body-secret"
            "</property>"
        ),
        (
            "<field type='clientSecret'>"
            "synthetic-xml-type-body-secret"
            "</field>"
        ),
        (
            '{"xml":"\\u003cproperty\\u0020'
            'name=\\u0022password\\u0022\\u003e'
            'synthetic-encoded-xml-body-secret'
            '\\u003c/property\\u003e"}'
        ),
        (
            "&lt;property name=&quot;password&quot;&gt;"
            "synthetic-entity-xml-body-secret"
            "&lt;/property&gt;"
        ),
        '<property name="password">synthetic-unclosed-xml-body-secret',
        (
            '<property name="password"/ >'
            "synthetic-malformed-self-close-body-secret"
            "</property>"
        ),
        "<password " + ("x" * 4_097),
        (
            "&lt;password&gt;"
            "synthetic-named-entity-xml-secret"
            "&lt;/password&gt;"
        ),
        (
            "&#60;clientSecret&#62;"
            "synthetic-decimal-entity-xml-secret"
            "&#60;&#47;clientSecret&#62;"
        ),
        (
            "&#x3c;config:api-key&#x3E;"
            "synthetic-hex-entity-xml-secret"
            "&#x3c;&#x2f;config:api-key&#x3e;"
        ),
        (
            "&amp;lt;password&amp;gt;"
            "synthetic-nested-entity-xml-secret"
            "&amp;lt;/password&amp;gt;"
        ),
        (
            '{"xml":"\\u0026lt;password\\u0026gt;'
            'synthetic-json-entity-xml-secret'
            '\\u0026lt;/password\\u0026gt;"}'
        ),
        (
            "&#92;u003cpassword&#92;u003e"
            "synthetic-entity-json-xml-secret"
            "&#92;u003c/password&#92;u003e"
        ),
        (
            "&#37;26lt&#37;3Bpassword&#37;26gt&#37;3B"
            "synthetic-entity-percent-xml-secret"
            "&#37;26lt&#37;3B/password&#37;26gt&#37;3B"
        ),
        (
            "&lt;password&gt;"
            "colameta://result-artifact/opaque_handle_123_"
            "&lt;/password&gt;"
        ),
    ],
)
def test_public_text_redacts_sensitive_xml_elements(value: str) -> None:
    public = commander_public_text(value)

    assert public == "<sensitive>"
    assert "synthetic-" not in public
    assert "colameta://" not in public


@pytest.mark.parametrize(
    "value",
    [
        "<status>public-ready</status>",
        "<public-key>synthetic-public-material</public-key>",
        "Discuss the <password> element without including a body.",
        "&lt;status&gt;public-entity-status&lt;/status&gt;",
        "Discuss the &lt;password&gt; element without including a body.",
        '<property name="public-key" value="synthetic-public-material"/>',
        '<property name="password" value=""/>',
        '<property name="password"/>',
        '<property name="password"></property>',
        '<property name="password"> \n\t </property>',
        '<entry key="public-key" value="synthetic-public-material"/>',
        '<entry key="password" value=""/>',
        '<entry key="password"/>',
        '<entry key="password"></entry>',
        '<entry key="password"> \n\t </entry>',
        (
            '<property name="public-key">'
            "synthetic-public-material"
            "</property>"
        ),
        (
            "<property "
            "description='name=\"password\" value=\"synthetic-example\"'/>"
        ),
        "if count <threshold:\n    continue",
        "<property " + ("x" * 4_097),
    ],
)
def test_public_text_does_not_redact_safe_xml_prose(value: str) -> None:
    public = commander_public_text(value)

    assert public == value


@pytest.mark.parametrize(
    "value",
    [
        "<status>/home/reviewer/private.txt</status>",
        "<status></home/reviewer/private.txt></status>",
        "<status></status extra>",
        "&lt;status&gt;/home/reviewer/private.txt&lt;/status&gt;",
    ],
)
def test_public_text_keeps_xml_closing_tags_without_hiding_paths(
    value: str,
) -> None:
    public = commander_public_text(value)

    assert "<local-path>" in public
    assert "/home/reviewer" not in public


@pytest.mark.parametrize(
    "value",
    [
        "AccountKey=synthetic-azure-account-key",
        "StorageAccountKey=synthetic-storage-account-key",
        "SharedAccessKey=synthetic-shared-access-key",
        (
            "SharedAccessSignature="
            "sv=synthetic-version&sig=synthetic-sas-signature"
        ),
        '{"Account\\u004bey":"synthetic-encoded-account-key"}',
        json.dumps(
            {
                "wrapped": (
                    "SharedAccess\\u0053ignature="
                    "sv=synthetic-version&sig=synthetic-nested-sas"
                )
            }
        ),
    ],
)
def test_public_text_redacts_azure_storage_credentials(
    value: str,
) -> None:
    public = commander_public_text(value)

    assert public == "<sensitive>"
    assert "synthetic-" not in public


@pytest.mark.parametrize(
    "value",
    [
        (
            "https://account.blob.core.windows.net/container/blob"
            "?sv=2024-11-04&sp=r&sig=synthetic-sas-url-signature"
        ),
        (
            "//account.blob.core.windows.net/container/blob"
            "?sig=synthetic-relative-sas-signature&sv=2024-11-04"
        ),
        (
            "https://account.blob.core.windows.net/container/blob"
            "?sig=synthetic-duplicate-sas-signature&sig=&sv=2024-11-04"
        ),
        (
            "https://account.blob.core.windows.net/container/blob?"
            + "&".join(
                [
                    "sv=2024-11-04",
                    *(["sp=r"] * 130),
                    "sig=synthetic-late-sas-signature",
                ]
            )
        ),
        (
            '{"url":"https:\\/\\/account.blob.core.windows.net'
            '\\/container\\/blob?sv\\u003d2024-11-04'
            '\\u0026sp\\u003dr\\u0026sig\\u003d'
            'synthetic-encoded-sas-signature"}'
        ),
        json.dumps(
            {
                "wrapped": (
                    "https:\\u002f\\u002faccount.blob.core.windows.net"
                    "/container/blob?sv=2024-11-04"
                    "\\u0026sig=synthetic-nested-sas-signature"
                )
            }
        ),
    ],
)
def test_public_text_redacts_azure_sas_signature_queries(
    value: str,
) -> None:
    public = commander_public_text(value)

    assert public == "<sensitive>"
    assert "synthetic-" not in public


@pytest.mark.parametrize(
    "value",
    [
        "client_secret: alpha beta gamma",
        "password: correct horse battery staple",
        "token: alpha beta gamma # synthetic YAML comment",
        "client_secret: >-\n  alpha beta gamma",
        (
            '{"yaml":"client\\u005fsecret\\u003a '
            'alpha beta gamma"}'
        ),
        json.dumps(
            {
                "wrapped": (
                    "password\\u003a correct horse "
                    "battery staple"
                )
            }
        ),
    ],
)
def test_public_text_fails_closed_for_multiword_sensitive_scalars(
    value: str,
) -> None:
    public = commander_public_text(value)

    assert public == "<sensitive>"
    for fragment in (
        "alpha",
        "beta",
        "gamma",
        "correct",
        "horse",
        "battery",
        "staple",
    ):
        assert fragment not in public


@pytest.mark.parametrize(
    "value",
    [
        "_auth=dXNlcjpwYXNz",
        "_authToken=synthetic-npm-token",
        "//registry.npmjs.org/:_authToken=synthetic-registry-token",
        '{"_auth":"dXNlcjpwYXNz"}',
        '{"\\u005fauth":"dXNlcjpwYXNz"}',
        json.dumps(
            {
                "wrapped": (
                    "//registry.npmjs.org/:"
                    "\\u005fauthToken=synthetic-nested-npm-token"
                )
            }
        ),
    ],
)
def test_public_text_redacts_separator_prefixed_sensitive_assignments(
    value: str,
) -> None:
    public = commander_public_text(value)

    assert public == "<sensitive>"
    assert "dXNlcjpwYXNz" not in public
    assert "synthetic-" not in public


@pytest.mark.parametrize(
    "value",
    [
        (
            "machine example.com login alice "
            "password synthetic-netrc-secret"
        ),
        (
            "machine example.com\n"
            "  login alice\n"
            "  password synthetic-multiline-netrc-secret"
        ),
        "default login alice passwd synthetic-default-netrc-secret",
        (
            '{"netrc":"machine example.com login alice '
            'password\\u0020synthetic-encoded-netrc-secret"}'
        ),
        json.dumps(
            {
                "wrapped": (
                    "machine example.com\\u0020login alice"
                    "\\u0020password synthetic-nested-netrc-secret"
                )
            }
        ),
    ],
)
def test_public_text_redacts_whitespace_delimited_netrc_passwords(
    value: str,
) -> None:
    public = commander_public_text(value)

    assert public == "<sensitive>"
    assert "synthetic-" not in public


@pytest.mark.parametrize(
    "value",
    [
        "localhost:5432:mydb:alice:synthetic-pgpass-password",
        "*:5432:*:alice:synthetic-wildcard-pgpass-password",
        (
            r"db\:primary:5432:mydb:alice:"
            "synthetic-escaped-host-pgpass-password"
        ),
        (
            '{"pgpass":"localhost:5432:mydb:alice:'
            'synthetic-json-pgpass-password"}'
        ),
        (
            '{"pgpass":"localhost\\u003a5432\\u003amydb'
            '\\u003aalice\\u003asynthetic-encoded-pgpass-password"}'
        ),
        json.dumps(
            {
                "wrapped": (
                    "localhost\\u003a5432\\u003amydb"
                    "\\u003aalice"
                    "\\u003asynthetic-nested-pgpass-password"
                )
            }
        ),
    ],
)
def test_public_text_redacts_pgpass_password_records(value: str) -> None:
    public = commander_public_text(value)

    assert public == "<sensitive>"
    assert "synthetic-" not in public


@pytest.mark.parametrize(
    "value",
    [
        "PGPASSWORD=synthetic-postgres-password",
        "pgpassword=synthetic-lowercase-postgres-password",
        '{"PGPASSWORD":"synthetic-json-postgres-password"}',
        (
            '{"env":"PGPASSWORD\\u003d'
            'synthetic-encoded-postgres-password"}'
        ),
        "PGPASSWORD%3Dsynthetic-percent-postgres-password",
        json.dumps(
            {
                "wrapped": (
                    "PGPASSWORD%253Dsynthetic-nested-postgres-password"
                )
            }
        ),
        "MYSQL_PWD=synthetic-mysql-password",
        "mysql_pwd=synthetic-lowercase-mysql-password",
        '{"MYSQL_PWD":"synthetic-json-mysql-password"}',
        (
            '{"env":"MYSQL\\u005fPWD\\u003d'
            'synthetic-encoded-mysql-password"}'
        ),
        "MYSQL%5FPWD%3Dsynthetic-percent-mysql-password",
        json.dumps(
            {
                "wrapped": (
                    "MYSQL%255FPWD%253Dsynthetic-nested-mysql-password"
                )
            }
        ),
    ],
)
def test_public_text_redacts_database_password_assignments(
    value: str,
) -> None:
    public = commander_public_text(value)

    assert public == "<sensitive>"
    assert "synthetic-" not in public


@pytest.mark.parametrize(
    "value",
    [
        "--password synthetic-cli-password",
        "tool --api-key synthetic-cli-secret --verbose",
        "tool --password\tsynthetic-tab-cli-secret",
        "tool --client_secret 'synthetic quoted cli secret'",
        "tool --AWS_SECRET_ACCESS_KEY synthetic-aws-cli-secret",
        (
            'curl --oauth2-bearer "syntheticBearerToken123" '
            "https://example.test"
        ),
        (
            "curl --oauth2-bearer 'synthetic-single-quoted-bearer' "
            "https://example.test"
        ),
        (
            '{"command":"curl --oauth2-bearer\\u0020'
            '\\"synthetic-encoded-oauth2-bearer\\" '
            'https:\\/\\/example.test"}'
        ),
        (
            '{"command":"tool --api-key\\u0020'
            'synthetic-encoded-space-cli-secret"}'
        ),
        (
            '{"command":"tool --api\\u002dkey '
            'synthetic-encoded-cli-secret"}'
        ),
        json.dumps(
            {
                "wrapped": (
                    '{"command":"tool --refresh\\u002dtoken '
                    'synthetic-nested-cli-secret"}'
                )
            }
        ),
    ],
)
def test_public_text_redacts_whitespace_separated_sensitive_cli_options(
    value: str,
) -> None:
    public = commander_public_text(value)

    assert public == "<sensitive>"
    assert "synthetic-" not in public


@pytest.mark.parametrize(
    "value",
    [
        (
            "curl -u alice:synthetic-curl-password "
            "https://example.invalid"
        ),
        (
            "curl --user alice:synthetic-long-curl-password "
            "https://example.invalid"
        ),
        (
            "curl --user=alice:synthetic-equals-curl-password "
            "https://example.invalid"
        ),
        (
            "curl -U alice:synthetic-curl-proxy-password "
            "https://example.invalid"
        ),
        (
            "curl --proxy-user=alice:synthetic-equals-proxy-password "
            "https://example.invalid"
        ),
        (
            "curl -Ualice:synthetic-attached-proxy-password "
            "https://example.invalid"
        ),
        (
            "curl -ualice:synthetic-attached-curl-password "
            "https://example.invalid"
        ),
        (
            "curl -u 'alice:synthetic-quoted-curl-password' "
            "https://example.invalid"
        ),
        (
            '{"command":"curl\\u0020-u\\u0020alice\\u003a'
            'synthetic-encoded-curl-password https:\\/\\/example.invalid"}'
        ),
        (
            '{"command":"curl\\u0020--proxy-user\\u0020alice\\u003a'
            'synthetic-encoded-proxy-password https:\\/\\/example.invalid"}'
        ),
        (
            "curl%20--user%20alice%3A"
            "synthetic-percent-curl-password%20"
            "https%3A%2F%2Fexample.invalid"
        ),
        json.dumps(
            {
                "wrapped": json.dumps(
                    {
                        "command": (
                            "curl\\u0020--user\\u003dalice\\u003a"
                            "synthetic-nested-curl-password "
                            "https:\\/\\/example.invalid"
                        )
                    }
                )
            }
        ),
        json.dumps(
            {
                "wrapped": (
                    "curl%20--proxy-user%3Dalice%3A"
                    "synthetic-nested-proxy-password%20"
                    "https%3A%2F%2Fexample.invalid"
                )
            }
        ),
    ],
)
def test_public_text_redacts_curl_user_password_options(
    value: str,
) -> None:
    public = commander_public_text(value)

    assert public == "<sensitive>"
    assert "synthetic-" not in public


@pytest.mark.parametrize(
    "value",
    [
        (
            "curl -Eclient.pem:synthetic-cert-password "
            "https://example.invalid"
        ),
        (
            "curl -E client.pem:synthetic-spaced-cert-password "
            "https://example.invalid"
        ),
        (
            "curl --cert=client.pem:synthetic-long-cert-password "
            "https://example.invalid"
        ),
        (
            "curl --cert 'client.pem:synthetic-quoted-cert-password' "
            "https://example.invalid"
        ),
        (
            "curl --proxy-cert=proxy.pem:"
            "synthetic-proxy-cert-password https://example.invalid"
        ),
        (
            "curl --pass synthetic-cert-passphrase "
            "https://example.invalid"
        ),
        (
            "curl --proxy-pass=synthetic-proxy-cert-passphrase "
            "https://example.invalid"
        ),
        (
            '{"command":"curl\\u0020--cert\\u003dclient.pem'
            '\\u003asynthetic-encoded-cert-password '
            'https:\\/\\/example.invalid"}'
        ),
        json.dumps(
            {
                "wrapped": (
                    "curl%2520--proxy-pass%253D"
                    "synthetic-nested-proxy-passphrase%2520"
                    "https%253A%252F%252Fexample.invalid"
                )
            }
        ),
    ],
)
def test_public_text_redacts_curl_certificate_credentials(
    value: str,
) -> None:
    public = commander_public_text(value)

    assert public == "<sensitive>"
    assert "synthetic-" not in public


@pytest.mark.parametrize(
    ("value", "secret_fragment"),
    [
        (
            "passphrase=synthetic-passphrase-value",
            "synthetic-passphrase-value",
        ),
        (
            '{"passPhrase":"synthetic-camel-passphrase"}',
            "synthetic-camel-passphrase",
        ),
        (
            '"pass phrase" = "synthetic spaced passphrase"',
            "synthetic spaced passphrase",
        ),
        (
            "--passphrase synthetic-cli-passphrase",
            "synthetic-cli-passphrase",
        ),
        (
            '{"pass\\u0070hrase":"synthetic-encoded-passphrase"}',
            "synthetic-encoded-passphrase",
        ),
        (
            json.dumps(
                {
                    "wrapped": (
                        '{"command":"tool --pass\\u0070hrase\\u0020'
                        'synthetic-nested-passphrase"}'
                    )
                }
            ),
            "synthetic-nested-passphrase",
        ),
    ],
)
def test_public_text_redacts_normalized_passphrase_credentials(
    value: str,
    secret_fragment: str,
) -> None:
    public = commander_public_text(value)

    assert "<sensitive>" in public
    assert secret_fragment not in public


@pytest.mark.parametrize(
    "value",
    [
        "-----BEGIN PRIVATE KEY-----\n"
        "synthetic-private-key-material\n"
        "-----END PRIVATE KEY-----",
        "-----BEGIN RSA PRIVATE KEY-----\n"
        "synthetic-rsa-key-material\n"
        "-----END RSA PRIVATE KEY-----",
        "-----BEGIN OPENSSH PRIVATE KEY-----\n"
        "synthetic-openssh-key-material\n"
        "-----END OPENSSH PRIVATE KEY-----",
        "---- BEGIN SSH2 ENCRYPTED PRIVATE KEY ----\n"
        "synthetic-ssh2-key-material\n"
        "---- END SSH2 ENCRYPTED PRIVATE KEY ----",
        "-----BEGIN PGP PRIVATE KEY BLOCK-----\n"
        "synthetic-pgp-key-material\n"
        "-----END PGP PRIVATE KEY BLOCK-----",
        (
            '{"pem":"-----BEGIN \\u0050RIVATE KEY-----'
            '\\nsynthetic-encoded-key-material"}'
        ),
        (
            '{"armor":"-----BEGIN PGP \\u0050RIVATE KEY '
            '\\u0042LOCK-----\\nsynthetic-encoded-pgp-material"}'
        ),
        (
            '{"ssh2":"---- BEGIN SSH2 \\u0045NCRYPTED PRIVATE '
            'KEY ----\\nsynthetic-encoded-ssh2-key-material"}'
        ),
        (
            "PuTTY-User-Key-File-3: ssh-ed25519\n"
            "Encryption: aes256-cbc\n"
            "Comment: synthetic fixture\n"
            "Public-Lines: 1\n"
            "synthetic-public-material\n"
            "Private-Lines: 1\n"
            "synthetic-putty-private-material\n"
            "Private-MAC: synthetic-mac"
        ),
        (
            '{"ppk":"PuTTY-User-Key-File-\\u0033\\u003a ssh-rsa'
            '\\nPrivate-Lines: 1'
            '\\nsynthetic-encoded-putty-private-material"}'
        ),
    ],
)
def test_public_text_redacts_private_key_file_markers(value: str) -> None:
    assert commander_public_text(value) == "<sensitive>"


@pytest.mark.parametrize(
    "value",
    [
        SYNTHETIC_AGE_X25519_IDENTITY,
        f"age identity: {SYNTHETIC_AGE_X25519_IDENTITY}",
        SYNTHETIC_AGE_X25519_IDENTITY.replace("-", "%2D"),
        (
            '{"identity":"'
            f"{ESCAPED_SYNTHETIC_AGE_X25519_IDENTITY}"
            '"}'
        ),
        json.dumps(
            {
                "wrapped": json.dumps(
                    {
                        "identity": (
                            ESCAPED_SYNTHETIC_AGE_X25519_IDENTITY
                        )
                    }
                )
            }
        ),
    ],
)
def test_public_text_redacts_standalone_age_x25519_identities(
    value: str,
) -> None:
    public = commander_public_text(value)

    assert public == "<sensitive>"
    assert "AGE-SECRET-KEY-1" not in public


@pytest.mark.parametrize(
    "value",
    [
        json.dumps(
            {
                "kty": "RSA",
                "n": "synthetic-public-modulus",
                "e": "AQAB",
                "d": "synthetic-private-rsa-coordinate",
            }
        ),
        json.dumps(
            {
                "kty": "EC",
                "crv": "P-256",
                "x": "synthetic-public-x",
                "y": "synthetic-public-y",
                "d": "synthetic-private-ec-coordinate",
            }
        ),
        json.dumps(
            {
                "keys": [
                    {
                        "kty": "OKP",
                        "crv": "Ed25519",
                        "x": "synthetic-public-x",
                        "d": "synthetic-private-okp-coordinate",
                    }
                ]
            }
        ),
        json.dumps(
            {
                "kty": "oct",
                "k": "synthetic-symmetric-key-material",
            }
        ),
        (
            'JWK fixture: {"kty":"RSA","e":"AQAB",'
            '"d":"synthetic-embedded-private-coordinate"}'
        ),
        (
            '{"\\u006bty":"RSA","\\u0064":'
            '"synthetic-escaped-private-coordinate"}'
        ),
        json.dumps(
            {
                "wrapped": json.dumps(
                    {
                        "kty": "EC",
                        "d": "synthetic-nested-private-coordinate",
                    }
                )
            }
        ),
        _percent_encode_layers(
            json.dumps(
                {
                    "kty": "RSA",
                    "d": "synthetic-percent-private-coordinate",
                }
            ),
            1,
        ),
    ],
)
def test_public_text_redacts_structured_private_jwk_material(
    value: str,
) -> None:
    public = commander_public_text(value)

    assert public == "<sensitive>"
    assert "synthetic-" not in public


@pytest.mark.parametrize(
    "value",
    [
        json.dumps(
            {
                "kty": "RSA",
                "n": "synthetic-public-modulus",
                "e": "AQAB",
            }
        ),
        json.dumps(
            {
                "kty": "EC",
                "crv": "P-256",
                "x": "synthetic-public-x",
                "y": "synthetic-public-y",
            }
        ),
        json.dumps(
            {
                "d": "ordinary-derivative-field",
                "note": "No JWK key type is present.",
            }
        ),
        json.dumps(
            {
                "kty": "document-kind",
                "d": "ordinary-document-field",
            }
        ),
        json.dumps({"kty": "RSA", "d": ""}),
    ],
)
def test_public_text_preserves_public_jwk_and_unrelated_d_fields(
    value: str,
) -> None:
    assert commander_public_text(value) == value


def test_commander_response_omits_structured_private_jwk_facts() -> None:
    private_coordinate = "synthetic-structured-private-coordinate"
    response = build_commander_response(
        tool_name="list_registered_projects",
        raw_result={
            "ok": True,
            "message": "Project state read.",
            "status": "clean",
            "crypto": {
                "kty": "RSA",
                "n": "synthetic-public-modulus",
                "e": "AQAB",
                "d": private_coordinate,
            },
        },
        params={},
    )

    rendered = json.dumps(response, ensure_ascii=False)
    assert private_coordinate not in rendered
    assert response["facts"]["status"] == "clean"
    assert "crypto" not in response["facts"]
    validate_commander_response(response)


@pytest.mark.parametrize(
    "value",
    [
        "https://alice:synthetic-password@example.com/repo",
        "postgresql://dbuser:synthetic-db-password@db.example/app",
        (
            "postgresql+psycopg://dbuser:"
            "synthetic:p%40ssword@db.example/app"
        ),
        "https:\\/\\/alice:synthetic-escaped-password@example.com/repo",
        "//alice:synthetic-relative-password@example.com/repo",
        (
            '{"url":"https:\\u002f\\u002falice:'
            'synthetic-unicode-password@example.com/repo"}'
        ),
        (
            '{"url":"https:\\u002f\\u002falice\\u003a'
            'synthetic-encoded-authority\\u0040example.com/repo"}'
        ),
        json.dumps(
            {
                "wrapped": (
                    "redis:\\/\\/cache:"
                    "synthetic-nested-password@cache.example/0"
                )
            }
        ),
    ],
)
def test_public_text_redacts_credentials_in_uri_userinfo(
    value: str,
) -> None:
    public = commander_public_text(value)

    assert public == "<sensitive>"
    assert "synthetic-" not in public


@pytest.mark.parametrize(
    "value",
    [
        "publicKey=synthetic-public-value",
        "monkey=banana",
        '{"apiVersion":"v1"}',
        "AWS_REGION=us-east-1",
        "-----BEGIN PUBLIC KEY-----",
        "-----BEGIN PGP PUBLIC KEY BLOCK-----",
        "-----BEGIN CERTIFICATE-----",
        "---- BEGIN SSH2 PUBLIC KEY ----",
        "https://example.com/repo",
        "https://alice@example.com/repo",
        "http://[::1]:8080/health",
        "https://example.com/archive/user:note@v1",
        "mailto:alice@example.com",
        "tool --username alice --region us-east-1",
        "tool --user alice:note",
        "curl --user alice https://example.invalid",
        "curl --user alice@example.invalid https://example.invalid",
        "curl --user <user:password> https://example.invalid",
        "curl --proxy-user alice https://example.invalid",
        "curl --proxy-user <user:password> https://example.invalid",
        (
            "curl -e https://example.test/page "
            "https://example.invalid"
        ),
        (
            '{"command":"curl\\u0020-e\\u0020'
            'https:\\/\\/example.test/page\\u0020'
            'https:\\/\\/example.invalid"}'
        ),
        "curl -E client.pem https://example.invalid",
        "curl --cert client.pem https://example.invalid",
        "curl --proxy-cert proxy.pem https://example.invalid",
        "curl --cert <certificate[:password]> https://example.invalid",
        "curl --proxy-cert <cert[:passwd]> https://example.invalid",
        "curl --pass --verbose https://example.invalid",
        "curl --proxy-pass --verbose https://example.invalid",
        "curl --cert-status https://example.invalid",
        "tool --cert client.pem:public-note",
        "tool --proxy-user alice:note",
        "curl --help all",
        "curl -u",
        "curl -U",
        "curl --oauth2-bearer",
        "Document the OAuth2 bearer option.",
        "tool --password --verbose",
        "tool --password\\u0020\\u002d\\u002dverbose",
        "tool --passphrase --prompt",
        "Use password protection for local data.",
        "Document a netrc password prompt.",
        (
            "# localhost:5432:mydb:alice:"
            "synthetic-commented-pgpass-placeholder"
        ),
        "localhost:5432:mydb:alice",
        (
            "localhost:postgres:mydb:alice:"
            "synthetic-nonrecord-password-prose"
        ),
        "machine-readable password policy.",
        "Use password protection for the default profile.",
        "Use a passphrase prompt.",
        "PuTTY-User-Key-File-3 ssh-ed25519",
        "AGE-SECRET-KEY-1" + ("Q" * 57),
        "AGE-SECRET-KEY-1" + ("Q" * 59),
        "x" + SYNTHETIC_AGE_X25519_IDENTITY,
        SYNTHETIC_AGE_X25519_IDENTITY + "Q",
        "AGE-SECRET-KEY-1" + ("B" * 58),
        "AGE-SECRET-KEY-1<redacted>",
        "Document the AGE-SECRET-KEY-1 prefix.",
        "age1" + ("q" * 58),
        "header.payload.signature",
        "release.v1.signature",
        "c3ludGhldGlj.aGVhZGVy.c2lnbmF0dXJl",
        "ghp_" + ("A1" * 17) + "A",
        "ghp_" + ("A1" * 18) + "A",
        "github_pat_<redacted>",
        "hf_" + ("A" * 33),
        "hf_<redacted>",
        "hf_" + ("A" * 35),
        "xhf_" + ("A" * 34),
        "dop_v1_" + ("a" * 63),
        "dop_v1_<redacted>",
        "dop_v1_" + ("a" * 65),
        "xdop_v1_" + ("a" * 64),
        "dop_v1_" + ("g" * 64),
        "dapi" + ("a" * 31),
        "dapi<redacted>",
        "dapi" + ("a" * 33),
        "x" + SYNTHETIC_DATABRICKS_PAT,
        SYNTHETIC_DATABRICKS_PAT + "a",
        "dapi" + ("g" * 32),
        "shpat_" + ("a" * 31),
        "shpat_<redacted>",
        "shpat_" + ("a" * 33),
        "xshpat_" + ("a" * 32),
        "shpat_" + ("g" * 32),
        "npm_short",
        "npm_<redacted>",
        "npm_" + ("A" * 37),
        "dckr_pat_" + ("A" * 26),
        "dckr_pat_<redacted>",
        "dckr_pat_" + ("A" * 28),
        "pypi-short",
        "pypi-<redacted>",
        "pypi-" + ("A" * 84),
        "1234567:" + ("A" * 35),
        "123456789:" + ("A" * 34),
        "123456789:" + ("A" * 36),
        "123456789:<redacted>",
        f"SG.{'A' * 21}.{'B' * 43}",
        f"SG.{'A' * 22}.{'B' * 42}",
        f"SG.{'A' * 22}.{'B' * 44}",
        "SG.<redacted>.<redacted>",
        f"xSG.{'A' * 22}.{'B' * 43}",
        "glpat-short",
        "glpat-<redacted>",
        "glpat-" + ("A" * 21),
        "AIza-short",
        "AIza<redacted>",
        "AIza" + ("A" * 36),
        "GOCSPX-" + ("A" * 27),
        "GOCSPX-<redacted>",
        "GOCSPX-" + ("A" * 29),
        "x" + SYNTHETIC_GOOGLE_OAUTH_CLIENT_SECRET,
        SYNTHETIC_GOOGLE_OAUTH_CLIENT_SECRET + "A",
        "AKIA-short",
        "AKIA<redacted>",
        "AKIA" + ("A" * 17),
        "ASIA-short",
        "AIDA" + ("A" * 16),
        "AROA" + ("A" * 16),
        "sk_live_short",
        "sk_live_<redacted>",
        "sk_live_" + ("A" * 25),
        "rk_test_short",
        "pk_live_" + ("A" * 24),
        "pk_test_" + ("A" * 24),
        "xoxb-short",
        "xoxb-<redacted>",
        "xoxb-" + ("A" * 251),
        "sk-proj-short",
        "sk-proj-<redacted>",
        "sk-proj-" + ("A" * 257),
        (
            "https://example.com/callback"
            "?sig=synthetic-ordinary-signature"
        ),
        (
            "https://account.blob.core.windows.net/container/blob"
            "?sv=2024-11-04&sp=r"
        ),
        "sig=synthetic-ordinary-signature",
        (
            "https://provider.example.invalid/callback"
            "?topic=api%5Fkey"
        ),
        (
            "https://provider.example.invalid/callback"
            "?api%5Fkeyboard=public"
        ),
        (
            "https://provider.example.invalid/callback"
            "?api%5Fkey"
        ),
        (
            "https://provider.example.invalid/callback"
            "?topic=api+key"
        ),
        (
            "https://provider.example.invalid/callback"
            "?api+keyboard=public"
        ),
        (
            "https://client.example.invalid/callback"
            "?code=public-code-without-state"
        ),
        (
            "https://client.example.invalid/callback"
            "?state=public-state-without-code"
        ),
        (
            "https://client.example.invalid/callback"
            "?error=access_denied&state=public-error-state"
        ),
        (
            "https://client.example.invalid/callback"
            "?code=&state=public-state"
        ),
        "C++ form parsing documentation.",
        "PGPASSWORD_HINT=use-the-local-prompt",
        "PGPASSWORD_FILE=relative.pgpass",
        "Document PGPASSWORD handling without assigning it.",
        "MYSQL_PWD_HINT=use-the-local-prompt",
        "MYSQL_PWD_FILE=relative.mysql.cnf",
        "Document MYSQL_PWD handling without assigning it.",
        "pwd=public-relative-name",
        "_author=Jenn",
        "_authorship=public",
        "client-certificate-data: synthetic-public-certificate",
        "client-key-data-file: relative-client-key.pem",
        "client-key-data-hint: use-local-agent",
        "Document client-key-data handling without assigning it.",
        "public key: synthetic-public-value",
        "Discuss the api key rotation policy.",
    ],
)
def test_public_text_preserves_non_sensitive_key_prose(value: str) -> None:
    assert commander_public_text(value) == value


@pytest.mark.parametrize(
    "value, expected",
    [
        (
            "Cookie: session=abc; csrf=def",
            "<sensitive>",
        ),
        (
            (
                'Authorization: Digest username="Mufasa", '
                'response="deadbeef"'
            ),
            "<sensitive>",
        ),
        (
            'Cookie: "session=abc"; csrf=def',
            "<sensitive>",
        ),
        (
            (
                'Authorization: "Digest username=Mufasa", '
                "response=deadbeef"
            ),
            "<sensitive>",
        ),
        (
            (
                'Authorization: Digest username="Mufasa",\r\n'
                ' response="deadbeef"\nNext safe line.'
            ),
            "<sensitive>",
        ),
        (
            '{"Cookie":"session=abc; csrf=def","status":"safe"}',
            "<sensitive>",
        ),
        (
            "Proxy-Authorization: Basic dXNlcjpwYXNzd29yZA==",
            "<sensitive>",
        ),
        (
            "Set-Cookie: session=abc; HttpOnly; Secure",
            "<sensitive>",
        ),
    ],
)
def test_public_text_redacts_complete_compound_credential_headers(
    value: str,
    expected: str,
) -> None:
    public = commander_public_text(value)

    assert public == expected
    for fragment in (
        "session=abc",
        "csrf=def",
        "Mufasa",
        "deadbeef",
        "dXNlcjpwYXNzd29yZA",
    ):
        assert fragment not in public


@pytest.mark.parametrize(
    "value",
    [
        'password="alpha beta gamma"',
        "client_secret='alpha beta gamma'",
        'prefix authorization="Bearer alpha beta gamma" suffix',
        '{"password":"alpha beta gamma","status":"safe"}',
        r'{\"password\":\"alpha beta gamma\"}',
        json.dumps(
            {
                "wrapped": (
                    r'password=\"alpha beta gamma\"'
                )
            }
        ),
        r'password="alpha \"beta\" gamma"',
        'password="alpha beta gamma',
    ],
)
def test_public_text_redacts_complete_quoted_sensitive_values(
    value: str,
) -> None:
    public = commander_public_text(value)

    assert "<sensitive>" in public
    for fragment in ("alpha", "beta", "gamma"):
        assert fragment not in public


@pytest.mark.parametrize(
    "value",
    [
        '{"oauth\\u005ftoken":"synthetic-secret-value"}',
        r'{\"password\":\"alpha beta gamma\"}',
        '{"reason":"\\u0042earer abcdefghijklmnop"}',
        (
            '{"reason":"Authorization: '
            '\\u0042asic dXNlcjpwYXNzd29yZA=="}'
        ),
        r'{\"Cookie\":\"session=abc; csrf=def\"}',
        (
            '{"reason":"Authorization: \\u0044igest '
            'username=\\"Mufasa\\", response=\\"deadbeef\\""}'
        ),
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
        '{"reason":"%6danage_files"}',
        '{"reason":"%256danage%255ffiles"}',
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
def test_public_text_redacts_encoded_noncommander_tools(
    value: str,
) -> None:
    assert commander_public_text(value) == "<internal-tool>"


def test_public_text_redacts_json_escaped_dynamic_hidden_tool() -> None:
    value = '{"reason":"private\\u005frunner\\u005ftool"}'

    assert commander_public_text(
        value,
        forbidden_tools={"private_runner_tool"},
    ) == "<internal-tool>"
    assert commander_public_text(
        '{"reason":"private%5frunner%5ftool"}',
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
    "message",
    [
        "Cookie: session=abc; csrf=def",
        "Basic dXNlcjpwYXNzd29yZA==",
        '{"reason":"\\u0042asic dXNlcjpwYXNzd29yZA=="}',
        (
            "-----BEGIN PRIVATE KEY-----\n"
            "synthetic-private-key-material\n"
            "-----END PRIVATE KEY-----"
        ),
        (
            "-----BEGIN PGP PRIVATE KEY BLOCK-----\n"
            "synthetic-pgp-key-material\n"
            "-----END PGP PRIVATE KEY BLOCK-----"
        ),
        "https://alice:synthetic-password@example.com/repo",
        "tool --password synthetic-cli-password",
        "passphrase=synthetic-passphrase-value",
        "client_secret: alpha beta gamma",
        "_auth=dXNlcjpwYXNz",
        (
            "PuTTY-User-Key-File-3: ssh-ed25519\n"
            "Private-Lines: 1\n"
            "synthetic-putty-private-material"
        ),
        SYNTHETIC_JWT,
        (
            'Authorization: Digest username="Mufasa", '
            'response="deadbeef"'
        ),
    ],
)
def test_blocked_error_redacts_complete_compound_credential_headers(
    message: str,
) -> None:
    response = build_commander_response(
        tool_name="manage_git",
        raw_result={
            "ok": False,
            "error": {
                "code": "GIT_WORKTREE_DIRTY",
                "message": message,
                "recoverable": True,
            },
        },
        params={"action": "commit_preview", "project_name": "colameta"},
    )

    assert response["outcome"] == "blocked"
    assert response["summary"] == "<sensitive>"
    assert response["error"]["message"] == "<sensitive>"
    validate_commander_response(response)


@pytest.mark.parametrize(
    "message, secret_fragment",
    [
        (
            '{"apiKey":"synthetic-secret-value"}',
            "synthetic-secret-value",
        ),
        (
            "private-key=synthetic-private-key-value",
            "synthetic-private-key-value",
        ),
        (
            "AWS_SECRET_ACCESS_KEY=synthetic-aws-secret-value",
            "synthetic-aws-secret-value",
        ),
    ],
)
def test_blocked_error_redacts_normalized_sensitive_key_assignments(
    message: str,
    secret_fragment: str,
) -> None:
    response = build_commander_response(
        tool_name="manage_git",
        raw_result={
            "ok": False,
            "error": {
                "code": "GIT_WORKTREE_DIRTY",
                "message": message,
                "recoverable": True,
            },
        },
        params={"action": "commit_preview", "project_name": "colameta"},
    )

    assert response["outcome"] == "blocked"
    assert secret_fragment not in response["summary"]
    assert secret_fragment not in response["error"]["message"]
    assert "<sensitive>" in response["summary"]
    assert "<sensitive>" in response["error"]["message"]
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
        "Basic dXNlcjpwYXNzd29yZA==",
        '{"reason":"\\u0042asic dXNlcjpwYXNzd29yZA=="}',
        '{"apiKey":"synthetic-secret-value"}',
        "private-key=synthetic-private-key-value",
        "AWS_SECRET_ACCESS_KEY=synthetic-aws-secret-value",
        (
            "-----BEGIN PRIVATE KEY-----\n"
            "synthetic-private-key-material\n"
            "-----END PRIVATE KEY-----"
        ),
        (
            "-----BEGIN PGP PRIVATE KEY BLOCK-----\n"
            "synthetic-pgp-key-material\n"
            "-----END PGP PRIVATE KEY BLOCK-----"
        ),
        "https://alice:synthetic-password@example.com/repo",
        (
            '{"url":"postgresql:\\u002f\\u002fdbuser:'
            'synthetic-db-password@db.example/app"}'
        ),
        (
            '{"command":"tool --api\\u002dkey '
            'synthetic-encoded-cli-secret"}'
        ),
        '{"passPhrase":"synthetic-camel-passphrase"}',
        (
            '{"ppk":"PuTTY-User-Key-File-\\u0033\\u003a ssh-rsa'
            '\\nPrivate-Lines: 1'
            '\\nsynthetic-encoded-putty-private-material"}'
        ),
        f'{{"access":"{ESCAPED_SYNTHETIC_JWT}"}}',
        "client_secret: alpha beta gamma",
        '{"\\u005fauth":"dXNlcjpwYXNz"}',
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
            "/pages/{page}(/home/reviewer/private.txt)"
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
        r"\\server/share\private.txt",
        json.dumps({"reason": r"\\server/share\private.txt"}),
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
        "colameta%3A%2F%2Finternal-tool%2Fsecret",
        "colameta%253A%252F%252Finternal-tool%252Fsecret",
        (
            "colameta://result-artifact/opaque_handle_123_"
            "/pages/{page}%20colameta%3A%2F%2Finternal-tool%2Fsecret"
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
        "colameta%3A%2F%2Finternal-tool%2Fsecret",
        "colameta%253A%252F%252Finternal-tool%252Fsecret",
        (
            "colameta://result-artifact/opaque_handle_123_"
            "/pages/{page}%20colameta%3A%2F%2Finternal-tool%2Fsecret"
        ),
    ],
)
def test_public_text_redacts_encoded_disallowed_resource_uri(
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
        "Basic dXNlcjpwYXNzd29yZA==",
        '{"reason":"\\u0042asic dXNlcjpwYXNzd29yZA=="}',
        '{"apiKey":"synthetic-secret-value"}',
        "private-key=synthetic-private-key-value",
        "AWS_SECRET_ACCESS_KEY=synthetic-aws-secret-value",
        (
            "-----BEGIN OPENSSH PRIVATE KEY-----\n"
            "synthetic-private-key-material\n"
            "-----END OPENSSH PRIVATE KEY-----"
        ),
        (
            "-----BEGIN PGP PRIVATE KEY BLOCK-----\n"
            "synthetic-pgp-key-material\n"
            "-----END PGP PRIVATE KEY BLOCK-----"
        ),
        "--passphrase synthetic-cli-passphrase",
        (
            "PuTTY-User-Key-File-2: ssh-rsa\n"
            "Private-Lines: 1\n"
            "synthetic-putty-private-material"
        ),
        f'{{"access":"{ESCAPED_SYNTHETIC_JWT}"}}',
        "password: correct horse battery staple",
        (
            "//registry.npmjs.org/:"
            "\\u005fauthToken=synthetic-registry-token"
        ),
        "redis://cache:synthetic-password@cache.example/0",
        (
            '{"url":"https:\\/\\/alice:'
            'synthetic-escaped-password@example.com/repo"}'
        ),
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
            "/subjects/1/pages/{page}(/home/reviewer/private.txt)"
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
        r"\\server/share\private.txt",
        json.dumps({"reason": r"\\server/share\private.txt"}),
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
            "/subjects/1/pages/{page}−private"
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
        "oauth2_bearer",
        "oauth2-bearer",
        "id_token",
        "client_secret",
        "client-secret",
        "client-key-data",
        "clientKeyData",
        "API Key",
        "apiKey",
        "apikey",
        "private-key",
        "vendorApiKey",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_ACCESS_KEY_ID",
        "AWSSecretAccessKey",
        "passphrase",
        "passPhrase",
        "pass-phrase",
        "pass phrase",
        "MYSQL_PWD",
        "mysqlPwd",
        "mysql-pwd",
        "_auth",
        ".npm_authToken",
        "oauth_authorization_code",
        "/home/jenn/private/secret.txt",
        r"C:\Users\Jenn\secret.txt",
        "C:/Users/Jenn/secret.txt",
        r"\\server/share\secret.txt",
        "//server/share/secret.txt",
        "///server/share/secret.txt",
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
