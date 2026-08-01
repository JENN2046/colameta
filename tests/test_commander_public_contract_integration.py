from __future__ import annotations

import hashlib
import json
import subprocess
import time

import pytest
from jsonschema import Draft202012Validator

from runner.commander_contract import (
    COMMANDER_RESPONSE_SCHEMA_VERSION,
    validate_commander_response,
)
from runner.mcp_commander_public import (
    COMMANDER_EXPOSED_TOOLS,
    CommanderPublicProjector,
)
from runner.mcp_server import MCPPlanningBridgeServer
from runner.project_registry import ProjectRegistry


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


PROJECT_NAME = "colameta-self-dev"
GIT_HEAD = "a" * 40
PLAN_SHA256 = "b" * 64
CONTENT_SHA256 = "c" * 64
MANIFEST_SHA256 = "d" * 64
ARTIFACT_ID = "artifact_contract_1234567890"
MANIFEST_ID = "manifest_contract_1234567890"
PREVIEW_ID = "preview_contract_1234567890"
RUN_ID = "validation_contract_1234567890"
TOKEN_LIKE_OPAQUE_ID = "sk-" + ("R" * 29)
EXPIRES_AT = "2026-08-01T18:00:00+08:00"
SYNTHETIC_GITHUB_PAT = "ghp_" + ("A1" * 18)
SYNTHETIC_HUGGING_FACE_TOKEN = "hf_" + ("A1" * 17)
ESCAPED_SYNTHETIC_HUGGING_FACE_TOKEN = (
    SYNTHETIC_HUGGING_FACE_TOKEN.replace("hf_", "\\u0068f_")
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
        "api_key=synthetic-budget-summary-secret",
        16,
    )
)


def _base_context_binding() -> dict[str, object]:
    return {
        "project_name": PROJECT_NAME,
        "branch": "codex/nuobao-commander-contract-v1",
        "head": GIT_HEAD,
        "runner_plan": {
            "mode": "managed",
            "plan_sha256": PLAN_SHA256,
        },
        "current_version": "N1",
    }


def _operation_context_binding() -> dict[str, object]:
    return {
        **_base_context_binding(),
        "review_unit": "commander-contract-preview",
        "workflow_intent": "continue-bound-operation",
    }


def _artifact_descriptor() -> dict[str, object]:
    return {
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


def _manifest_descriptor() -> dict[str, object]:
    return {
        "kind": "review_manifest",
        "review_manifest_id": MANIFEST_ID,
        "manifest_resource_uri": f"colameta://review-manifest/{MANIFEST_ID}",
        "manifest_sha256": MANIFEST_SHA256,
        "expires_at": EXPIRES_AT,
    }


def _project(
    tool_name: str,
    data: dict[str, object],
    params: dict[str, object] | None = None,
    *,
    ok: bool = True,
    error_code: str | None = None,
    message: str | None = None,
) -> dict[str, object]:
    raw: dict[str, object] = {
        "ok": ok,
        "tool": tool_name,
        "data": data,
    }
    if error_code is not None:
        raw["error_code"] = error_code
    if message is not None:
        raw["message"] = message
    return CommanderPublicProjector("/home/example/src/private-project").project_tool_result(
        raw,
        params,
    )


def _assert_contract(
    result: dict[str, object],
    *,
    tool_name: str,
    outcome: str,
    journey_stage: str,
) -> dict[str, object]:
    assert result["tool"] == tool_name
    contract = result["data"]
    assert isinstance(contract, dict)
    validate_commander_response(contract)
    assert contract["schema_version"] == COMMANDER_RESPONSE_SCHEMA_VERSION
    assert contract["outcome"] == outcome
    assert contract["journey_stage"] == journey_stage
    return contract


@pytest.mark.parametrize(
    ("tool_name", "data", "params", "journey_stage"),
    [
        (
            "list_registered_projects",
            {
                "ok": True,
                "project_count": 1,
                "registry_path": "/home/example/.config/colameta/projects.json",
                "projects": [
                    {
                        "project_id": "private-project-id",
                        "project_name": PROJECT_NAME,
                        "display_name": "ColaMeta",
                        "project_root": "/home/example/src/private-project",
                        "project_mode": "managed",
                        "available": True,
                        "runner_managed": True,
                    }
                ],
            },
            {},
            "connect",
        ),
        (
            "get_apps_connector_smoke_packet",
            {
                "ok": True,
                "protocol_version": "mcp.v1",
                "connector_runtime_health": {"overall_status": "healthy"},
                "pid": 42,
                "log_path": "/tmp/private.log",
            },
            {},
            "connect",
        ),
        (
            "render_commander_app",
            {
                "ok": True,
                "app_manifest_version": "colameta_commander_app.v1",
                "project_name": PROJECT_NAME,
                "project_root": "/home/example/src/private-project",
            },
            {"project_name": PROJECT_NAME},
            "connect",
        ),
        (
            "analyze_project_state",
            {
                "ok": True,
                "project_name": PROJECT_NAME,
                "canonical_project_state": {
                    "status": "ready",
                    "context_binding": _base_context_binding(),
                },
                "context_binding": _base_context_binding(),
            },
            {"project_name": PROJECT_NAME},
            "observe",
        ),
        (
            "review_manifest",
            {
                "ok": True,
                "phase": "inspect",
                "context_binding": _operation_context_binding(),
                **_manifest_descriptor(),
            },
            {"phase": "inspect", "project_name": PROJECT_NAME},
            "review",
        ),
        (
            "read_result_artifact",
            {
                "ok": True,
                "result_artifact": _artifact_descriptor(),
            },
            {"artifact_id": ARTIFACT_ID},
            "review",
        ),
        (
            "run_mcp_workflow",
            {
                "ok": True,
                "workflow": "docs_update",
                "phase": "completed",
                "context_binding": _base_context_binding(),
            },
            {"workflow": "docs_update", "project_name": PROJECT_NAME},
            "execute",
        ),
        (
            "manage_validation_run",
            {
                "ok": True,
                "status": "passed",
                "context_binding": _base_context_binding(),
            },
            {"action": "status", "project_name": PROJECT_NAME},
            "validate",
        ),
        (
            "manage_git",
            {
                "ok": True,
                "status": "clean",
                "context_binding": _base_context_binding(),
            },
            {"action": "status", "project_name": PROJECT_NAME},
            "close",
        ),
    ],
)
def test_all_nine_public_tools_project_through_commander_response_v1(
    tool_name: str,
    data: dict[str, object],
    params: dict[str, object],
    journey_stage: str,
) -> None:
    result = _project(tool_name, data, params)

    contract = _assert_contract(
        result,
        tool_name=tool_name,
        outcome="completed",
        journey_stage=journey_stage,
    )
    serialized = json.dumps(result, ensure_ascii=False)
    assert "/home/" not in serialized
    assert "/tmp/" not in serialized
    assert "private-project-id" not in serialized
    assert "manage_files" not in serialized
    assert contract["confirmation"] is None
    assert contract["error"] is None


@pytest.mark.parametrize(
    ("data", "params", "expected_outcome"),
    [
        (
            {
                "ok": True,
                "workflow": "docs_update",
                "status": "completed",
                "context_binding": _base_context_binding(),
            },
            {"workflow": "docs_update", "project_name": PROJECT_NAME},
            "completed",
        ),
        (
            {
                "ok": True,
                "workflow": "docs_update",
                "requires_confirmation": True,
                "preview_id": PREVIEW_ID,
                "context_binding": _operation_context_binding(),
            },
            {
                "workflow": "docs_update",
                "phase": "preview",
                "project_name": PROJECT_NAME,
            },
            "confirmation_required",
        ),
        (
            {
                "ok": True,
                "workflow": "agent_dispatch",
                "status": "running",
                "batch_preview_id": PREVIEW_ID,
                "context_binding": _base_context_binding(),
            },
            {"workflow": "agent_dispatch", "project_name": PROJECT_NAME},
            "in_progress",
        ),
    ],
)
def test_workflow_projection_covers_normal_lifecycle_states(
    data: dict[str, object],
    params: dict[str, object],
    expected_outcome: str,
) -> None:
    contract = _assert_contract(
        _project("run_mcp_workflow", data, params),
        tool_name="run_mcp_workflow",
        outcome=expected_outcome,
        journey_stage="execute",
    )

    if expected_outcome == "confirmation_required":
        assert contract["confirmation"]["preview_id"] == PREVIEW_ID
        assert contract["next_action"]["tool"] == "run_mcp_workflow"
    elif expected_outcome == "in_progress":
        assert contract["next_action"]["arguments"]["phase"] == "status"


def test_workflow_projection_blocks_scope_violations_without_hidden_recommendations() -> None:
    contract = _assert_contract(
        _project(
            "run_mcp_workflow",
            {
                "ok": False,
                "error_code": "SCOPE_VIOLATION",
                "message": "请求超出工作项范围。",
                "next_action": {
                    "tool": "manage_files",
                    "arguments": {"action": "edit"},
                },
            },
            {"workflow": "small_project_patch", "project_name": PROJECT_NAME},
            ok=False,
            error_code="SCOPE_VIOLATION",
            message="请求超出工作项范围。",
        ),
        tool_name="run_mcp_workflow",
        outcome="blocked",
        journey_stage="execute",
    )

    assert contract["error"]["code"] == "SCOPE_VIOLATION"
    assert contract["next_action"]["tool"] == "analyze_project_state"
    assert "manage_files" not in json.dumps(contract, ensure_ascii=False)


def test_workflow_projection_drops_non_commander_next_action() -> None:
    contract = _assert_contract(
        _project(
            "run_mcp_workflow",
            {
                "ok": True,
                "status": "completed",
                "context_binding": _base_context_binding(),
                "next_action": {
                    "tool": "manage_executor_workflow",
                    "arguments": {"action": "run"},
                },
            },
            {"workflow": "docs_update", "project_name": PROJECT_NAME},
        ),
        tool_name="run_mcp_workflow",
        outcome="completed",
        journey_stage="execute",
    )

    assert contract["next_action"] is None
    assert "manage_executor_workflow" not in json.dumps(contract, ensure_ascii=False)


def test_projection_removes_sensitive_keys_path_keys_hidden_tools_and_nested_ids() -> None:
    result = _project(
        "analyze_project_state",
        {
            "ok": True,
            "context_binding": _base_context_binding(),
            "safe_fact": "kept",
            "safe_project_label": "get_started",
            "oauth_token": "oauth-value-must-not-leak",
            "id_token": "id-value-must-not-leak",
            "client_secret": "client-value-must-not-leak",
            "oauth_authorization_code": "code-value-must-not-leak",
            "passPhrase": "passphrase-value-must-not-leak",
            "_auth": "npm-auth-value-must-not-leak",
            "AccountKey": "azure-account-value-must-not-leak",
            "SharedAccessSignature": "azure-sas-value-must-not-leak",
            "/home/jenn/private/secret.txt": "posix-key-value",
            r"C:\Users\Jenn\secret.txt": "windows-key-value",
            r"\\server/share\secret.txt": "unc-key-value",
            r"\Users\Jenn\secret.txt": "rooted-windows-key-value",
            "nested": {
                "safe_nested": True,
                "run_id": "run-private-123",
                "validation_run_id": "validation-private-123",
                "executor_run_id": "executor-private-123",
            },
            "guidance": (
                "Call manage_git_remote, get_git_status, or "
                "manage_plan_version next."
            ),
        },
        {"project_name": PROJECT_NAME},
    )

    contract = _assert_contract(
        result,
        tool_name="analyze_project_state",
        outcome="completed",
        journey_stage="observe",
    )
    assert contract["facts"]["safe_fact"] == "kept"
    assert contract["facts"]["safe_project_label"] == "get_started"
    assert contract["facts"]["nested"] == {"safe_nested": True}
    rendered = json.dumps(result, ensure_ascii=False)
    for forbidden in (
        "oauth_token",
        "id_token",
        "client_secret",
        "oauth_authorization_code",
        "passPhrase",
        "_auth",
        "AccountKey",
        "SharedAccessSignature",
        "oauth-value-must-not-leak",
        "id-value-must-not-leak",
        "client-value-must-not-leak",
        "code-value-must-not-leak",
        "passphrase-value-must-not-leak",
        "npm-auth-value-must-not-leak",
        "azure-account-value-must-not-leak",
        "azure-sas-value-must-not-leak",
        "/home/jenn",
        r"C:\Users\Jenn",
        r"\\server/share",
        "unc-key-value",
        r"\Users\Jenn",
        "rooted-windows-key-value",
        "manage_git_remote",
        "get_git_status",
        "manage_plan_version",
        "run-private-123",
        "validation-private-123",
        "executor-private-123",
    ):
        assert forbidden not in rendered


@pytest.mark.parametrize(
    "summary",
    [
        (
            "machine example.com login alice "
            "password synthetic-netrc-summary-secret"
        ),
        (
            '{"netrc":"machine example.com login alice '
            'password\\u0020synthetic-encoded-netrc-summary-secret"}'
        ),
        json.dumps(
            {
                "wrapped": (
                    "machine example.com\\u0020login alice"
                    "\\u0020password synthetic-nested-netrc-summary-secret"
                )
            }
        ),
    ],
)
def test_projection_redacts_whitespace_delimited_netrc_passwords(
    summary: str,
) -> None:
    contract = _assert_contract(
        _project(
            "analyze_project_state",
            {
                "ok": True,
                "context_binding": _base_context_binding(),
                "summary": summary,
            },
            {"project_name": PROJECT_NAME},
        ),
        tool_name="analyze_project_state",
        outcome="completed",
        journey_stage="observe",
    )

    assert contract["summary"] == "<sensitive>"
    assert "synthetic-" not in json.dumps(contract, ensure_ascii=False)


@pytest.mark.parametrize(
    "summary",
    [
        SYNTHETIC_GITHUB_PAT,
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
        SYNTHETIC_NPM_ACCESS_TOKEN,
        f'{{"access":"{ESCAPED_SYNTHETIC_NPM_ACCESS_TOKEN}"}}',
        json.dumps(
            {
                "wrapped": json.dumps(
                    {"access": ESCAPED_SYNTHETIC_NPM_ACCESS_TOKEN}
                )
            }
        ),
        SYNTHETIC_PYPI_API_TOKEN,
        SYNTHETIC_LONG_PYPI_API_TOKEN,
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
        f'{{"access":"{ESCAPED_SYNTHETIC_GITLAB_PAT}"}}',
        json.dumps(
            {
                "wrapped": json.dumps(
                    {"access": ESCAPED_SYNTHETIC_GITLAB_PAT}
                )
            }
        ),
        SYNTHETIC_GOOGLE_API_KEY,
        f'{{"access":"{ESCAPED_SYNTHETIC_GOOGLE_API_KEY}"}}',
        json.dumps(
            {
                "wrapped": json.dumps(
                    {"access": ESCAPED_SYNTHETIC_GOOGLE_API_KEY}
                )
            }
        ),
        SYNTHETIC_AWS_ACCESS_KEY_ID,
        SYNTHETIC_AWS_TEMPORARY_ACCESS_KEY_ID,
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
        f'{{"access":"{ESCAPED_SYNTHETIC_STRIPE_SECRET_KEY}"}}',
        json.dumps(
            {
                "wrapped": json.dumps(
                    {"access": ESCAPED_SYNTHETIC_STRIPE_SECRET_KEY}
                )
            }
        ),
        SYNTHETIC_SLACK_TOKEN,
        f'{{"access":"{ESCAPED_SYNTHETIC_SLACK_TOKEN}"}}',
        json.dumps(
            {
                "wrapped": json.dumps(
                    {"access": ESCAPED_SYNTHETIC_SLACK_TOKEN}
                )
            }
        ),
        SYNTHETIC_OPENAI_PROJECT_KEY,
        f'{{"access":"{ESCAPED_SYNTHETIC_OPENAI_PROJECT_KEY}"}}',
        json.dumps(
            {
                "wrapped": json.dumps(
                    {"access": ESCAPED_SYNTHETIC_OPENAI_PROJECT_KEY}
                )
            }
        ),
    ],
)
def test_projection_redacts_standalone_provider_access_tokens(
    summary: str,
) -> None:
    contract = _assert_contract(
        _project(
            "analyze_project_state",
            {
                "ok": True,
                "context_binding": _base_context_binding(),
                "summary": summary,
            },
            {"project_name": PROJECT_NAME},
        ),
        tool_name="analyze_project_state",
        outcome="completed",
        journey_stage="observe",
    )

    assert contract["summary"] == "<sensitive>"
    assert "ghp_" not in json.dumps(contract, ensure_ascii=False)
    assert "hf_" not in json.dumps(contract, ensure_ascii=False)
    assert "npm_" not in json.dumps(contract, ensure_ascii=False)
    assert "pypi-" not in json.dumps(contract, ensure_ascii=False)
    assert "SG." not in json.dumps(contract, ensure_ascii=False)
    assert "glpat-" not in json.dumps(contract, ensure_ascii=False)
    assert "AIza" not in json.dumps(contract, ensure_ascii=False)
    assert "AKIA" not in json.dumps(contract, ensure_ascii=False)
    assert "ASIA" not in json.dumps(contract, ensure_ascii=False)
    assert "sk_live_" not in json.dumps(contract, ensure_ascii=False)
    assert "rk_test_" not in json.dumps(contract, ensure_ascii=False)
    assert "xoxb-" not in json.dumps(contract, ensure_ascii=False)
    assert "sk-proj-" not in json.dumps(contract, ensure_ascii=False)


@pytest.mark.parametrize(
    "summary",
    [
        (
            "https://provider.example.invalid/callback"
            "?api%5Fkey=synthetic-percent-summary-secret"
        ),
        (
            '{"url":"https:\\/\\/provider.example.invalid\\/callback'
            '?api\\u00255Fkey=synthetic-json-percent-summary-secret"}'
        ),
        json.dumps(
            {
                "wrapped": json.dumps(
                    {
                        "url": (
                            "https://provider.example.invalid/callback"
                            "?api%255Fkey="
                            "synthetic-nested-percent-summary-secret"
                        )
                    }
                )
            }
        ),
    ],
)
def test_projection_redacts_percent_encoded_sensitive_key_assignments(
    summary: str,
) -> None:
    contract = _assert_contract(
        _project(
            "analyze_project_state",
            {
                "ok": True,
                "context_binding": _base_context_binding(),
                "summary": summary,
            },
            {"project_name": PROJECT_NAME},
        ),
        tool_name="analyze_project_state",
        outcome="completed",
        journey_stage="observe",
    )

    assert contract["summary"] == "<sensitive>"
    assert "synthetic-" not in json.dumps(contract, ensure_ascii=False)


@pytest.mark.parametrize(
    "summary",
    [
        (
            "https://provider.example.invalid/callback"
            "?api+key=synthetic-form-summary-secret"
        ),
        (
            "localhost:5432:mydb:alice:"
            "synthetic-pgpass-summary-password"
        ),
        (
            "https://client.example.invalid/callback"
            "?code=synthetic-oauth-summary-code"
            "&state=synthetic-oauth-summary-state"
        ),
        "PGPASSWORD=synthetic-postgres-summary-password",
        (
            '{"env":"PGPASSWORD\\u003d'
            'synthetic-encoded-postgres-summary-password"}'
        ),
        SYNTHETIC_TELEGRAM_BOT_TOKEN,
        (
            '{"access":"'
            + SYNTHETIC_TELEGRAM_BOT_TOKEN.replace(":", "\\u003a")
            + '"}'
        ),
    ],
)
def test_projection_redacts_form_pgpass_oauth_postgres_and_telegram_credentials(
    summary: str,
) -> None:
    contract = _assert_contract(
        _project(
            "analyze_project_state",
            {
                "ok": True,
                "context_binding": _base_context_binding(),
                "summary": summary,
            },
            {"project_name": PROJECT_NAME},
        ),
        tool_name="analyze_project_state",
        outcome="completed",
        journey_stage="observe",
    )

    assert contract["summary"] == "<sensitive>"
    assert "synthetic-" not in json.dumps(contract, ensure_ascii=False)


@pytest.mark.parametrize(
    ("summary", "expected"),
    [
        (
            MAX_BUDGET_PERCENT_ENCODED_SAFE_PROSE,
            MAX_BUDGET_PERCENT_ENCODED_SAFE_PROSE,
        ),
        (EXHAUSTING_PERCENT_ENCODED_SAFE_PROSE, "<sensitive>"),
        (
            EXHAUSTING_PERCENT_ENCODED_SENSITIVE_ASSIGNMENT,
            "<sensitive>",
        ),
    ],
)
def test_projection_fails_closed_only_when_decode_budget_is_exhausted(
    summary: str,
    expected: str,
) -> None:
    contract = _assert_contract(
        _project(
            "analyze_project_state",
            {
                "ok": True,
                "context_binding": _base_context_binding(),
                "summary": summary,
            },
            {"project_name": PROJECT_NAME},
        ),
        tool_name="analyze_project_state",
        outcome="completed",
        journey_stage="observe",
    )

    assert contract["summary"] == expected


@pytest.mark.parametrize(
    "summary",
    [
        (
            "curl -u alice:synthetic-curl-summary-password "
            "https://example.invalid"
        ),
        (
            "curl --user=alice:synthetic-equals-curl-summary-password "
            "https://example.invalid"
        ),
        (
            "curl -U alice:synthetic-curl-proxy-summary-password "
            "https://example.invalid"
        ),
        (
            "curl --proxy-user=alice:"
            "synthetic-equals-proxy-summary-password "
            "https://example.invalid"
        ),
        (
            '{"command":"curl\\u0020--user\\u0020alice\\u003a'
            'synthetic-encoded-curl-summary-password '
            'https:\\/\\/example.invalid"}'
        ),
        (
            '{"command":"curl\\u0020--proxy-user\\u0020alice\\u003a'
            'synthetic-encoded-proxy-summary-password '
            'https:\\/\\/example.invalid"}'
        ),
        json.dumps(
            {
                "wrapped": (
                    "curl%20-u%20alice%3A"
                    "synthetic-nested-curl-summary-password%20"
                    "https%3A%2F%2Fexample.invalid"
                )
            }
        ),
        json.dumps(
            {
                "wrapped": (
                    "curl%20--proxy-user%3Dalice%3A"
                    "synthetic-nested-proxy-summary-password%20"
                    "https%3A%2F%2Fexample.invalid"
                )
            }
        ),
    ],
)
def test_projection_redacts_curl_user_password_options(
    summary: str,
) -> None:
    contract = _assert_contract(
        _project(
            "analyze_project_state",
            {
                "ok": True,
                "context_binding": _base_context_binding(),
                "summary": summary,
            },
            {"project_name": PROJECT_NAME},
        ),
        tool_name="analyze_project_state",
        outcome="completed",
        journey_stage="observe",
    )

    assert contract["summary"] == "<sensitive>"
    assert "synthetic-" not in json.dumps(contract, ensure_ascii=False)


@pytest.mark.parametrize(
    ("summary", "expected"),
    [
        (
            "curl --cert=client.pem:synthetic-summary-cert-password "
            "https://example.invalid",
            "<sensitive>",
        ),
        (
            '{"command":"curl\\u0020--proxy-pass\\u003d'
            'synthetic-encoded-summary-passphrase '
            'https:\\/\\/example.invalid"}',
            "<sensitive>",
        ),
        (
            "https://example.test/download"
            "?file=%2Fhome%2Fjenn%2Fsecret.txt",
            "<local-path>",
        ),
        (
            '{"url":"https:\\/\\/example.test\\/download'
            '?file=\\u00252Fhome\\u00252Fjenn'
            '\\u00252Fsecret.txt"}',
            "<local-path>",
        ),
        (
            "root:/home/jenn/summary-secret.txt",
            "<local-path>",
        ),
        (
            '{"note":"root:\\u005cUsers\\u005cJenn'
            '\\u005csummary-secret.txt"}',
            "<local-path>",
        ),
    ],
)
def test_projection_redacts_curl_certificate_and_encoded_path_evidence(
    summary: str,
    expected: str,
) -> None:
    contract = _assert_contract(
        _project(
            "analyze_project_state",
            {
                "ok": True,
                "context_binding": _base_context_binding(),
                "summary": summary,
            },
            {"project_name": PROJECT_NAME},
        ),
        tool_name="analyze_project_state",
        outcome="completed",
        journey_stage="observe",
    )

    assert contract["summary"] == expected
    assert "synthetic-" not in json.dumps(contract, ensure_ascii=False)
    assert "secret.txt" not in json.dumps(contract, ensure_ascii=False)


def test_projection_preserves_token_like_opaque_resource_uri() -> None:
    uri = (
        f"colameta://result-artifact/{TOKEN_LIKE_OPAQUE_ID}"
        "/pages/{page}"
    )
    summary = f"Read {uri} to continue."

    contract = _assert_contract(
        _project(
            "analyze_project_state",
            {
                "ok": True,
                "context_binding": _base_context_binding(),
                "summary": summary,
            },
            {"project_name": PROJECT_NAME},
        ),
        tool_name="analyze_project_state",
        outcome="completed",
        journey_stage="observe",
    )

    assert contract["summary"] == summary


@pytest.mark.parametrize(
    "summary",
    [
        (
            "https://account.blob.core.windows.net/container/blob"
            "?sv=2024-11-04&sp=r&sig=synthetic-sas-url-signature"
        ),
        (
            '{"url":"https:\\/\\/account.blob.core.windows.net'
            '\\/container\\/blob?sv\\u003d2024-11-04'
            '\\u0026sig\\u003dsynthetic-encoded-sas-signature"}'
        ),
        json.dumps(
            {
                "wrapped": (
                    "https:\\u002f\\u002faccount.blob.core.windows.net"
                    "/container/blob?sig=synthetic-nested-sas-signature"
                    "\\u0026sv=2024-11-04"
                )
            }
        ),
    ],
)
def test_projection_redacts_azure_sas_signature_queries(
    summary: str,
) -> None:
    contract = _assert_contract(
        _project(
            "analyze_project_state",
            {
                "ok": True,
                "context_binding": _base_context_binding(),
                "summary": summary,
            },
            {"project_name": PROJECT_NAME},
        ),
        tool_name="analyze_project_state",
        outcome="completed",
        journey_stage="observe",
    )

    assert contract["summary"] == "<sensitive>"
    assert "synthetic-" not in json.dumps(contract, ensure_ascii=False)


@pytest.mark.parametrize(
    ("data", "params", "expected_outcome", "expected_error"),
    [
        (
            {
                "ok": True,
                "status": "ready",
                "context_binding": _base_context_binding(),
            },
            {"action": "inspect", "project_name": PROJECT_NAME},
            "completed",
            None,
        ),
        (
            {
                "ok": True,
                "status": "previewed",
                "requires_confirmation": True,
                "preview_id": PREVIEW_ID,
                "context_binding": _operation_context_binding(),
            },
            {"action": "preview", "project_name": PROJECT_NAME},
            "confirmation_required",
            None,
        ),
        (
            {
                "ok": True,
                "status": "running",
                "run_id": RUN_ID,
                "context_binding": _base_context_binding(),
            },
            {"action": "run", "project_name": PROJECT_NAME},
            "in_progress",
            None,
        ),
        (
            {
                "ok": True,
                "status": "passed",
                "context_binding": _base_context_binding(),
            },
            {"action": "status", "project_name": PROJECT_NAME},
            "completed",
            None,
        ),
        (
            {
                "ok": True,
                "status": "failed",
                "message": "验证未通过。",
            },
            {"action": "status", "project_name": PROJECT_NAME},
            "blocked",
            "VALIDATION_FAILED",
        ),
    ],
)
def test_validation_projection_distinguishes_inspect_preview_run_status_and_failure(
    data: dict[str, object],
    params: dict[str, object],
    expected_outcome: str,
    expected_error: str | None,
) -> None:
    contract = _assert_contract(
        _project("manage_validation_run", data, params),
        tool_name="manage_validation_run",
        outcome=expected_outcome,
        journey_stage="validate",
    )

    if expected_outcome == "confirmation_required":
        assert contract["next_action"]["arguments"]["action"] == "run"
    if expected_outcome == "in_progress":
        assert contract["next_action"]["arguments"] == {
            "action": "status",
            "run_id": RUN_ID,
            "project_name": PROJECT_NAME,
        }
    if expected_error is not None:
        assert contract["error"]["code"] == expected_error
        assert contract["next_action"]["tool"] == "analyze_project_state"


@pytest.mark.parametrize(
    ("data", "params", "expected_outcome", "expected_error", "expected_apply"),
    [
        (
            {
                "ok": True,
                "status": "clean",
                "context_binding": _base_context_binding(),
            },
            {"action": "status", "project_name": PROJECT_NAME},
            "completed",
            None,
            None,
        ),
        (
            {
                "ok": True,
                "changed_files": ["runner/commander_contract.py"],
                "context_binding": _base_context_binding(),
            },
            {"action": "diff", "project_name": PROJECT_NAME},
            "completed",
            None,
            None,
        ),
        (
            {
                "ok": True,
                "requires_confirmation": True,
                "preview_id": PREVIEW_ID,
                "context_binding": _operation_context_binding(),
            },
            {"action": "commit_preview", "project_name": PROJECT_NAME},
            "confirmation_required",
            None,
            "commit_apply",
        ),
        (
            {
                "ok": False,
                "error_code": "PREVIEW_STALE",
                "message": "Git HEAD 已变化。",
            },
            {"action": "commit_apply", "project_name": PROJECT_NAME},
            "blocked",
            "STALE_PREVIEW",
            None,
        ),
        (
            {
                "ok": False,
                "error_code": "GIT_WORKTREE_DIRTY",
                "message": "工作区存在额外修改。",
            },
            {"action": "commit_preview", "project_name": PROJECT_NAME},
            "blocked",
            "WORKTREE_DIRTY",
            None,
        ),
        (
            {
                "ok": True,
                "requires_confirmation": True,
                "preview_id": PREVIEW_ID,
                "context_binding": _operation_context_binding(),
            },
            {"action": "push_preview", "project_name": PROJECT_NAME},
            "confirmation_required",
            None,
            "push_apply",
        ),
    ],
)
def test_git_projection_distinguishes_read_preview_stale_dirty_and_push(
    data: dict[str, object],
    params: dict[str, object],
    expected_outcome: str,
    expected_error: str | None,
    expected_apply: str | None,
) -> None:
    ok = data.get("ok") is True
    contract = _assert_contract(
        _project(
            "manage_git",
            data,
            params,
            ok=ok,
            error_code=(
                data.get("error_code")
                if isinstance(data.get("error_code"), str)
                else None
            ),
            message=(
                data.get("message") if isinstance(data.get("message"), str) else None
            ),
        ),
        tool_name="manage_git",
        outcome=expected_outcome,
        journey_stage="close",
    )

    if expected_error is not None:
        assert contract["error"]["code"] == expected_error
        assert contract["confirmation"] is None
    if expected_apply is not None:
        assert contract["confirmation"]["preview_id"] == PREVIEW_ID
        assert contract["next_action"]["tool"] == "manage_git"
        assert contract["next_action"]["arguments"]["action"] == expected_apply


def test_commander_projection_is_idempotent_across_transport_packaging() -> None:
    projector = CommanderPublicProjector("/home/example/src/private-project")
    raw = {
        "ok": True,
        "tool": "manage_git",
        "data": {
            "ok": True,
            "status": "clean",
            "context_binding": _base_context_binding(),
        },
    }

    once = projector.project_tool_result(
        raw,
        {"action": "status", "project_name": PROJECT_NAME},
    )
    twice = projector.project_tool_result(
        once,
        {"action": "status", "project_name": PROJECT_NAME},
    )

    assert twice == once


def test_commander_tool_catalog_uses_the_versioned_output_schema(tmp_path) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path), exposure_profile="commander")
    visible = server._filter_tools_by_exposure_profile(server.tool_defs)

    assert tuple(tool.name for tool in visible) == COMMANDER_EXPOSED_TOOLS
    for tool in visible:
        schema = tool.output_schema
        assert schema["required"] == ["ok", "tool", "data"]
        data_schema = schema["properties"]["data"]
        assert (
            data_schema["properties"]["schema_version"]["const"]
            == COMMANDER_RESPONSE_SCHEMA_VERSION
        )
        Draft202012Validator.check_schema(schema)


def test_normal_profile_keeps_the_existing_broad_output_schema(tmp_path) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path), exposure_profile="normal")
    tool = next(
        tool
        for tool in server._filter_tools_by_exposure_profile(server.tool_defs)
        if tool.name == "manage_git"
    )

    assert tool.output_schema["required"] == ["ok", "tool"]
    assert tool.output_schema["properties"]["data"]["additionalProperties"] is True


def _make_real_git_project(tmp_path, name: str):
    project = tmp_path / name
    project.mkdir()
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    subprocess.run(
        ["git", "-C", str(project), "config", "user.email", "fixture@example.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(project), "config", "user.name", "Commander Fixture"],
        check=True,
    )
    (project / "README.md").write_text("baseline\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(project), "add", "README.md"], check=True)
    subprocess.run(
        ["git", "-C", str(project), "commit", "-qm", "fixture"],
        check=True,
    )
    return project


@pytest.mark.parametrize(
    ("action", "extra_arguments"),
    [
        ("status", {}),
        ("diff", {"mode": "summary"}),
        ("history_log", {"limit": 5}),
    ],
)
def test_real_manage_git_reads_are_completed_and_context_bound(
    tmp_path,
    action: str,
    extra_arguments: dict[str, object],
) -> None:
    project = _make_real_git_project(tmp_path, f"git-read-{action}")
    (project / "README.md").write_text("bounded change\n", encoding="utf-8")
    server = MCPPlanningBridgeServer(
        str(project),
        exposure_profile="commander",
    )

    result = server.call_tool_for_agent(
        "manage_git",
        {"action": action, **extra_arguments},
    )

    assert result["ok"] is True
    contract = result["data"]
    validate_commander_response(contract)
    assert contract["outcome"] == "completed"
    assert contract["journey_stage"] == "close"
    assert contract["context_binding"] is not None
    assert contract["context_binding"]["head"]
    assert contract["confirmation"] is None
    assert contract["error"] is None


def test_real_routed_manage_git_reads_keep_the_registered_context(
    tmp_path,
) -> None:
    project = _make_real_git_project(tmp_path, "routed-git-read")
    (project / "README.md").write_text("routed bounded change\n", encoding="utf-8")
    registry = ProjectRegistry(
        registry_path=str(tmp_path / "projects.json"),
        user_settings_path=str(tmp_path / "settings.json"),
    )
    registered = registry.register_project(
        str(project),
        project_name="routed-git-project",
        project_mode="managed",
    )
    assert registered["ok"] is True
    server = MCPPlanningBridgeServer(
        str(tmp_path),
        service_mode=True,
        exposure_profile="commander",
    )
    server.project_registry = registry

    for arguments in (
        {"action": "status"},
        {"action": "diff", "mode": "summary"},
        {"action": "history_log", "limit": 5},
    ):
        result = server.call_tool_for_agent(
            "manage_git",
            {
                **arguments,
                "project_name": "routed-git-project",
            },
        )
        assert result["ok"] is True
        contract = result["data"]
        validate_commander_response(contract)
        assert contract["outcome"] == "completed"
        assert contract["context_binding"]["project_name"] == (
            "routed-git-project"
        )


def test_real_large_git_diff_is_preserved_in_a_public_safe_artifact(
    tmp_path,
) -> None:
    project = _make_real_git_project(tmp_path, "large-git-diff")
    baseline = "".join(
        f"line {index:05d} before before before\n"
        for index in range(5_000)
    )
    changed = "".join(
        f"line {index:05d} after after after\n"
        for index in range(5_000)
    )
    (project / "README.md").write_text(baseline, encoding="utf-8")
    subprocess.run(["git", "-C", str(project), "add", "README.md"], check=True)
    subprocess.run(
        ["git", "-C", str(project), "commit", "-qm", "large baseline"],
        check=True,
    )
    (project / "README.md").write_text(changed, encoding="utf-8")
    server = MCPPlanningBridgeServer(
        str(project),
        exposure_profile="commander",
    )

    result = server.call_tool_for_agent(
        "manage_git",
        {
            "action": "diff",
            "mode": "page",
            "file": "README.md",
            "max_chars": 120_000,
        },
    )

    assert result["ok"] is True
    contract = result["data"]
    validate_commander_response(contract)
    assert contract["outcome"] == "completed"
    assert contract["facts"]["result_packaged"] is True
    assert contract["facts"]["result_char_estimate"] > 60_000
    evidence = contract["evidence"]
    assert evidence["kind"] == "result_artifact"
    assert evidence["page_count"] > 1
    assert contract["next_action"]["tool"] == "read_result_artifact"
    assert "packaged" not in result
    assert "recommended_next_reads" not in result

    pages: list[str] = []
    action = contract["next_action"]
    while action is not None:
        page_result = server.call_tool_for_agent(
            action["tool"],
            action["arguments"],
        )
        assert page_result["ok"] is True
        page_contract = page_result["data"]
        validate_commander_response(page_contract)
        assert page_contract["evidence"] == evidence
        pages.append(page_contract["facts"]["artifact_page"]["content"])
        action = page_contract["next_action"]

    restored = "".join(pages)
    assert hashlib.sha256(restored.encode("utf-8")).hexdigest() == evidence[
        "content_sha256"
    ]
    artifact_payload = json.loads(restored)
    assert artifact_payload["tool"] == "manage_git"
    assert len(artifact_payload["data"]["diff"]) > 60_000
    serialized = json.dumps(artifact_payload, ensure_ascii=False)
    assert str(project) not in serialized
    assert "get_git_diff" not in serialized
    assert "delegated_tool" not in serialized


def test_real_validation_preview_and_poll_use_the_public_contract(tmp_path) -> None:
    project = tmp_path / "validation-project"
    project.mkdir()
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    subprocess.run(
        ["git", "-C", str(project), "config", "user.email", "validation@example.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(project), "config", "user.name", "Validation Fixture"],
        check=True,
    )
    (project / ".gitignore").write_text(
        ".colameta/runtime/\n",
        encoding="utf-8",
    )
    (project / "README.md").write_text("baseline\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(project), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(project), "commit", "-qm", "fixture"],
        check=True,
    )
    (project / "README.md").write_text("bounded change\n", encoding="utf-8")
    server = MCPPlanningBridgeServer(
        str(project),
        exposure_profile="commander",
    )

    preview = server.call_tool_for_agent(
        "manage_validation_run",
        {"action": "preview", "scope": "changed_files"},
    )

    assert preview["ok"] is True
    preview_contract = preview["data"]
    validate_commander_response(preview_contract)
    assert preview_contract["outcome"] == "confirmation_required"
    assert len(preview_contract["confirmation"]["preview_id"]) == 12

    started = server.call_tool_for_agent(
        "manage_validation_run",
        preview_contract["next_action"]["arguments"],
    )
    assert started["ok"] is True
    current = started["data"]
    validate_commander_response(current)
    assert current["outcome"] == "in_progress"

    for _ in range(200):
        action = current["next_action"]
        assert action["tool"] == "manage_validation_run"
        assert action["arguments"]["action"] == "status"
        time.sleep(0.01)
        status = server.call_tool_for_agent(
            "manage_validation_run",
            action["arguments"],
        )
        assert status["ok"] is True
        current = status["data"]
        validate_commander_response(current)
        if current["outcome"] != "in_progress":
            break

    assert current["outcome"] == "completed"
    assert current["facts"]["status"] == "passed"
    assert current["facts"]["passed"] is True
