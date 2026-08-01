from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import json
import threading

import runner.mcp_server as mcp_server_module
from runner.commander_contract import validate_commander_response
from runner.mcp_result_artifacts import MCPResultArtifactStore
from runner.mcp_server import (
    COMMANDER_APP_WIDGET_URI,
    MCP_RESULT_ARTIFACT_PAGE_CHARS,
    MCP_RESULT_ARTIFACT_RESOURCE_TEMPLATES,
    MCP_RESULT_ARTIFACT_WORKFLOW,
    MCPPlanningBridgeServer,
)


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


SYNTHETIC_JWT = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJzdWIiOiJzeW50aGV0aWMtdXNlciIsInNjb3BlIjoicmVhZCJ9."
    "c3ludGhldGljLXNpZ25hdHVyZS1ieXRlcw"
)
ESCAPED_SYNTHETIC_JWT = SYNTHETIC_JWT.replace(".", "\\u002e")
SYNTHETIC_GITHUB_PAT = "ghp_" + ("A1" * 18)
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
        "api_key=synthetic-budget-artifact-secret",
        16,
    )
)


def test_result_artifact_store_pages_exact_json_and_expires() -> None:
    now = datetime(2026, 7, 22, tzinfo=timezone.utc)

    def now_fn() -> datetime:
        return now

    store = MCPResultArtifactStore(
        ttl_seconds=60,
        page_chars=10,
        now_fn=now_fn,
    )
    handle = store.put(tool="example", payload={"message": "你好", "values": list(range(8))})

    assert handle is not None
    pages = [store.read_page(handle.artifact_id, index) for index in range(1, handle.page_count + 1)]
    assert all(page is not None for page in pages)
    content = "".join(page.content for page in pages if page is not None)
    assert json.loads(content) == {"message": "你好", "values": list(range(8))}
    assert hashlib.sha256(content.encode("utf-8")).hexdigest() == handle.content_sha256

    now = now + timedelta(seconds=61)
    assert store.read_page(handle.artifact_id) is None


def test_packaged_mcp_result_exposes_a_paged_resource_continuation(tmp_path) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path))
    raw_result = {
        "ok": True,
        "tool": "manage_files",
        "data": {"content": "x" * 30000},
    }
    params = {"action": "read", "file": "CURRENT_STATE.md"}

    shaped = server._shape_mcp_call_result(raw_result, params)
    manifest = shaped["structuredContent"]

    assert manifest["packaged"] is True
    assert manifest["artifact_id"]
    assert manifest["resource_uri"].startswith("colameta://result-artifact/")
    assert manifest["page_count"] > 1
    assert manifest["page_uri_template"].endswith("/pages/{page}")
    assert manifest["recommended_next_reads"][:3] == [
        {
            "kind": "mcp_tool",
            "tool": "read_result_artifact",
            "arguments": {
                "artifact_id": manifest["artifact_id"],
                "artifact_page": 1,
            },
            "reason": "通过 ChatGPT 可调用的 read_result_artifact 读取同一短期 artifact 页；保留 artifact_id、页码、SHA-256 与 expiry 合同。",
        },
        {
            "kind": "mcp_resource",
            "tool": "resources/read",
            "arguments": {"uri": manifest["resource_uri"]},
            "reason": "可选的标准 MCP 资源续读：支持动态 resources/read 的客户端可读取第 1 页，再按 page_uri_template 续读。",
        },
        {
            "kind": "mcp_tool_compatibility",
            "tool": "run_mcp_workflow",
            "arguments": {
                "workflow": MCP_RESULT_ARTIFACT_WORKFLOW,
                "phase": "read",
                "artifact_id": manifest["artifact_id"],
                "artifact_page": 1,
            },
            "reason": "旧客户端兼容：通过 run_mcp_workflow 的 result_artifact read 读取同一短期 artifact 页。",
        },
    ]

    pages: list[str] = []
    for page_number in range(1, manifest["page_count"] + 1):
        uri = manifest["resource_uri"] if page_number == 1 else manifest["page_uri_template"].format(page=page_number)
        response = server._handle_jsonrpc_request(
            {
                "jsonrpc": "2.0",
                "id": page_number,
                "method": "resources/read",
                "params": {"uri": uri},
            }
        )
        assert response is not None
        page_payload = json.loads(response["result"]["contents"][0]["text"])
        assert page_payload["page"] == page_number
        assert page_payload["content_sha256"] == manifest["content_sha256"]
        pages.append(page_payload["content"])

    restored = "".join(pages)
    assert json.loads(restored) == raw_result
    assert hashlib.sha256(restored.encode("utf-8")).hexdigest() == manifest["content_sha256"]


def test_actions_packaging_uses_the_same_recoverable_artifact_contract(tmp_path) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path))
    raw_result = {
        "ok": True,
        "tool": "manage_files",
        "data": {"content": "x" * 70000},
    }
    params = {"action": "read", "file": "CURRENT_STATE.md"}

    manifest = server._package_actions_rest_response("manage_files", params, raw_result)

    assert manifest["packaged"] is True
    assert manifest["resource_uri"].startswith("colameta://result-artifact/")
    assert manifest["recommended_next_reads"][0]["tool"] == "read_result_artifact"
    assert manifest["recommended_next_reads"][1]["tool"] == "resources/read"
    assert manifest["recommended_next_reads"][2]["tool"] == "run_mcp_workflow"


def test_result_artifact_templates_are_static_and_artifact_ids_remain_opaque(tmp_path) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path))
    shaped = server._shape_mcp_call_result(
        {"ok": True, "tool": "manage_files", "data": {"content": "x" * 30000}},
        {"action": "read", "file": "CURRENT_STATE.md"},
    )
    artifact_id = shaped["structuredContent"]["artifact_id"]

    response = server._handle_jsonrpc_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "resources/templates/list",
            "params": {},
        }
    )

    assert response is not None
    templates = response["result"]["resourceTemplates"]
    artifact_templates = templates[: len(MCP_RESULT_ARTIFACT_RESOURCE_TEMPLATES)]
    assert artifact_templates == [dict(item) for item in MCP_RESULT_ARTIFACT_RESOURCE_TEMPLATES]
    assert [item["uriTemplate"] for item in artifact_templates] == [
        "colameta://result-artifact/{artifact_id}",
        "colameta://result-artifact/{artifact_id}/pages/{page}",
    ]
    assert artifact_id not in json.dumps(templates)


def test_mcp_overflow_reduced_manifest_keeps_resource_and_typed_recoverable_continuations(tmp_path, monkeypatch) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path))
    raw_result = {
        "ok": True,
        "tool": "manage_files",
        "data": {"content": "x" * 30000},
    }

    monkeypatch.setattr(
        server,
        "_mcp_recommended_next_reads",
        lambda *_args: [{"reason": "x" * 100000}],
    )
    shaped = server._shape_mcp_call_result(
        raw_result,
        {"action": "read", "file": "CURRENT_STATE.md"},
    )

    manifest = shaped["structuredContent"]
    assert manifest["packaged"] is True
    assert manifest["package_mode"] == "manifest"
    assert manifest["artifact_id"]
    assert [item["tool"] for item in manifest["recommended_next_reads"]] == [
        "read_result_artifact",
        "resources/read",
    ]

    page_response = server._handle_jsonrpc_request(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "resources/read",
            "params": {"uri": manifest["resource_uri"]},
        }
    )
    assert page_response is not None
    page = json.loads(page_response["result"]["contents"][0]["text"])
    assert page["artifact_id"] == manifest["artifact_id"]
    assert page["content_sha256"] == manifest["content_sha256"]


def test_actions_overflow_reduced_manifest_keeps_resource_and_typed_recoverable_continuations(tmp_path, monkeypatch) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path))
    raw_result = {
        "ok": True,
        "tool": "manage_files",
        "data": {"content": "x" * 70000},
    }

    monkeypatch.setattr(
        server,
        "_actions_recommended_next_reads",
        lambda *_args: [{"reason": "x" * 100000}],
    )
    manifest = server._package_actions_rest_response(
        "manage_files",
        {"action": "read", "file": "CURRENT_STATE.md"},
        raw_result,
    )

    assert manifest["packaged"] is True
    assert manifest["package_mode"] == "manifest"
    assert manifest["artifact_id"]
    assert manifest["resource_uri"].startswith("colameta://result-artifact/")
    assert [item["tool"] for item in manifest["recommended_next_reads"]] == [
        "read_result_artifact",
        "resources/read",
    ]


def test_result_artifact_recovery_manifest_keeps_all_recoverable_continuations(tmp_path) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path))
    artifact_fields = server._store_packaged_result_artifact(
        "manage_files",
        {"ok": True, "tool": "manage_files", "data": {"content": "x" * 30000}},
    )

    assert artifact_fields is not None
    manifest = server._result_artifact_recovery_manifest(
        tool_name="manage_files",
        ok=True,
        artifact_fields=artifact_fields,
    )

    assert manifest["packaged"] is True
    assert manifest["package_mode"] == "artifact_continuation"
    assert [item["tool"] for item in manifest["recommended_next_reads"]] == [
        "read_result_artifact",
        "resources/read",
        "run_mcp_workflow",
    ]


def test_result_artifact_compatibility_reads_exact_pages_and_sha_through_commander(tmp_path) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path), exposure_profile="commander")
    uri = "colameta://result-artifact/opaque_handle_123_/pages/{page}"
    payload = {
        "content": (
            f"请读取{uri}。\n"
            f"Read {uri}。Next\n"
            f"📎{uri}✅Next\n"
            f"请读取{uri}继续\n"
            f"❤️{uri}👩‍💻Next\n"
            f"1️⃣{uri}#️⃣Next\n"
            f"↔️{uri}〰️Next\n"
            f"Read {uri}✅,Next\n"
            f"Read {uri}」.Next\n"
            f"नमस्ते{uri}\n"
            f"مُرَاجَعَةَ{uri}\n"
            f"cafe\u0301{uri}\n"
            + ("x" * 30000)
        ),
        "label": "paged compatibility fixture",
        "relative_value": "safe\\/relative.txt",
        "fraction": "1\\/2",
        "url": "https:\\/\\/example.com",
        "escaped_space_suffix": f"{uri}\\u0020Next",
        "serialized_escaped_space_suffix": json.dumps(
            {"note": f"{uri}\\u0020Next"}
        ),
        "zero_width_space_suffix": f"{uri}\u200bNext",
        "escaped_zero_width_space_suffix": f"{uri}\\u200bNext",
        "serialized_zero_width_space_suffix": json.dumps(
            {"note": f"{uri}\u200bNext"}
        ),
        "bom_prefix": f"\ufeff{uri}",
        "escaped_bom_prefix": f"\\ufeff{uri}",
        "serialized_bom_prefix": json.dumps(
            {"note": f"\ufeff{uri}"}
        ),
        "short_escape_left_boundary": json.dumps(
            {"content": f"\n{uri}"}
        ),
        "nested_short_escape_left_boundary": json.dumps(
            {"nested": json.dumps({"content": f"\t{uri}"})}
        ),
        "dash_boundaries": f"before—{uri}–continue",
        "serialized_dash_boundaries": json.dumps(
            {"note": f"before—{uri}–continue"}
        ),
        "paired_punctuation_boundaries": (
            f"before」{uri}「continue; before”{uri}“continue"
        ),
        "serialized_paired_punctuation_boundaries": json.dumps(
            {"note": f"before）{uri}（continue"}
        ),
        "ascii_opening_boundaries": (
            f"{uri}(see page 2); {uri}[details]; "
            f"{uri}{{details}}; {uri}<details>"
        ),
        "escaped_ascii_opening_boundaries": (
            f"{uri}\\u0028see page 2\\u0029; "
            f"{uri}\\u005bdetails\\u005d; "
            f"{uri}\\u007bdetails\\u007d; "
            f"{uri}\\u003cdetails\\u003e"
        ),
        "ascii_closing_boundaries": (
            f"before){uri}; before]{uri}; before}}{uri}"
        ),
        "escaped_ascii_closing_boundaries": (
            f"before\\u0029{uri}; before\\u005d{uri}; "
            f"before\\u007d{uri}"
        ),
        "ascii_left_separator_boundaries": " ".join(
            f"{separator}{uri}" for separator in ",;!?"
        ),
        "escaped_ascii_left_separator_boundaries": " ".join(
            f"{separator}{uri}"
            for separator in ("\\u002c", "\\u003b", "\\u0021", "\\u003f")
        ),
        "public_key_assignment": "publicKey=synthetic-public-value",
        "public_key_marker": "-----BEGIN PUBLIC KEY-----",
        "pgp_public_key_marker": "-----BEGIN PGP PUBLIC KEY BLOCK-----",
        "ordinary_url": "https://example.com/repo",
        "username_only_url": "https://alice@example.com/repo",
        "prompt_prose": "Use a passphrase prompt.",
        "putty_header_without_colon": (
            "PuTTY-User-Key-File-3 ssh-ed25519"
        ),
        "compact_placeholder": "header.payload.signature",
        "compact_non_json_prose": (
            "c3ludGhldGlj.aGVhZGVy.c2lnbmF0dXJl"
        ),
        "separator_prefixed_safe_assignment": (
            "_author=Jenn; _authorship=public"
        ),
        "percent_encoded_safe_query": (
            "https://provider.example.invalid/callback"
            "?topic=api%5Fkey&api%5Fkeyboard=public"
        ),
        "percent_encoded_missing_value": (
            "https://provider.example.invalid/callback?api%5Fkey"
        ),
        "package_marker_short": "npm_short",
        "package_marker_placeholder": "npm_<redacted>",
        "package_marker_overlength": "npm_" + ("A" * 37),
        "index_marker_short": "pypi-short",
        "index_marker_placeholder": "pypi-<redacted>",
        "index_marker_underlength": "pypi-" + ("A" * 84),
        "mail_marker_first_underlength": (
            f"SG.{'A' * 21}.{'B' * 43}"
        ),
        "mail_marker_second_underlength": (
            f"SG.{'A' * 22}.{'B' * 42}"
        ),
        "mail_marker_overlength": f"SG.{'A' * 22}.{'B' * 44}",
        "mail_marker_placeholder": "SG.<redacted>.<redacted>",
        "max_budget_percent_encoded_safe_prose": (
            MAX_BUDGET_PERCENT_ENCODED_SAFE_PROSE
        ),
        "non_sensitive_cli_options": (
            "tool --username alice --region us-east-1"
        ),
        "non_curl_user_option": "tool --user alice:note",
        "curl_user_only": (
            "curl --user alice https://example.invalid"
        ),
        "curl_user_placeholder": (
            "curl --user <user:password> https://example.invalid"
        ),
        "sensitive_flag_without_value": "tool --password --verbose",
        "escaped_sensitive_flag_without_value": (
            "tool --password\\u0020\\u002d\\u002dverbose"
        ),
        "nested_json": json.dumps({"nested": json.dumps({"uri": uri})}),
        "ascii_json": json.dumps({"note": f"取{uri}继续"}),
        "symbol_json": json.dumps({"note": f"📎{uri}✅Next"}),
        "emoji_sequence_json": json.dumps(
            {"note": f"❤️{uri}👩‍💻Next"}
        ),
        "keycap_sequence_json": json.dumps(
            {"note": f"1️⃣{uri}#️⃣Next"}
        ),
        "non_so_emoji_sequence_json": json.dumps(
            {"note": f"↔️{uri}〰️Next"}
        ),
        "mixed_delimiter_json": json.dumps(
            {"note": f"{uri}✅,Next; {uri}」.Next"}
        ),
        "combining_mark_prose_json": json.dumps(
            {
                "note": (
                    f"नमस्ते{uri}; مُرَاجَعَةَ{uri}; "
                    f"cafe\u0301{uri}"
                )
            }
        ),
    }
    handle = server._mcp_result_artifact_store.put(tool="fixture", payload=payload)

    assert handle is not None
    assert handle.page_count > 1
    expected_content = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    pages: list[str] = []
    for page_number in range(1, handle.page_count + 1):
        response = server._handle_jsonrpc_request(
            {
                "jsonrpc": "2.0",
                "id": page_number,
                "method": "tools/call",
                "params": {
                    "name": "run_mcp_workflow",
                    "arguments": {
                        "workflow": MCP_RESULT_ARTIFACT_WORKFLOW,
                        "phase": "read",
                        "artifact_id": handle.artifact_id,
                        "artifact_page": page_number,
                    },
                },
            }
        )

        assert response is not None
        structured = response["result"]["structuredContent"]
        assert structured["ok"] is True
        contract = structured["data"]
        assert contract["schema_version"] == "commander_response.v1"
        assert contract["outcome"] == "completed"
        facts = contract["facts"]
        evidence = contract["evidence"]
        assert facts["workflow"] == MCP_RESULT_ARTIFACT_WORKFLOW
        assert facts["read_only"] is True
        assert facts["side_effects"] is False
        assert evidence["artifact_id"] == handle.artifact_id
        assert evidence["page_count"] == handle.page_count
        assert evidence["content_sha256"] == handle.content_sha256
        assert evidence["expires_at"] == handle.expires_at
        page = facts["artifact_page"]
        assert page["artifact_id"] == handle.artifact_id
        assert page["page"] == page_number
        assert page["content_sha256"] == handle.content_sha256
        assert page["expires_at"] == handle.expires_at
        pages.append(page["content"])
        if page_number < handle.page_count:
            assert contract["next_action"] == {
                "tool": "run_mcp_workflow",
                "arguments": {
                    "workflow": MCP_RESULT_ARTIFACT_WORKFLOW,
                    "phase": "read",
                    "artifact_id": handle.artifact_id,
                    "artifact_page": page_number + 1,
                },
                "reason": "继续读取同一短期 artifact 的下一页；artifact_id、expires_at 与 content_sha256 保持不变。",
            }
        else:
            assert contract["next_action"] is None

    restored = "".join(pages)
    assert restored == expected_content
    assert hashlib.sha256(restored.encode("utf-8")).hexdigest() == handle.content_sha256
    assert json.loads(restored) == payload

    resource_pages: list[str] = []
    for page_number in range(1, handle.page_count + 1):
        resource_uri = (
            f"colameta://result-artifact/{handle.artifact_id}"
            if page_number == 1
            else (
                f"colameta://result-artifact/{handle.artifact_id}"
                f"/pages/{page_number}"
            )
        )
        resource = server._handle_jsonrpc_request(
            {
                "jsonrpc": "2.0",
                "id": page_number,
                "method": "resources/read",
                "params": {"uri": resource_uri},
            }
        )
        assert resource is not None
        resource_page = json.loads(
            resource["result"]["contents"][0]["text"]
        )
        resource_pages.append(resource_page["content"])
    assert "".join(resource_pages) == expected_content


def test_commander_resource_reads_cache_full_artifact_safety_by_digest(
    tmp_path,
    monkeypatch,
) -> None:
    server = MCPPlanningBridgeServer(
        str(tmp_path),
        exposure_profile="commander",
    )
    payload = {
        "content": "\\" * 24_000 + "relative.txt",
        "label": "backslash-dense artifact",
    }
    handle = server._mcp_result_artifact_store.put(
        tool="fixture",
        payload=payload,
    )
    assert handle is not None
    assert handle.page_count >= 3

    scans = 0
    original_safety = (
        server._commander_public_result_artifact_payload_safety
    )

    def counting_safety(value: dict) -> bool:
        nonlocal scans
        scans += 1
        return original_safety(value)

    monkeypatch.setattr(
        server,
        "_commander_public_result_artifact_payload_safety",
        counting_safety,
    )

    pages: list[str] = []
    for page_number in range(1, handle.page_count + 1):
        resource_uri = (
            f"colameta://result-artifact/{handle.artifact_id}"
            if page_number == 1
            else (
                f"colameta://result-artifact/{handle.artifact_id}"
                f"/pages/{page_number}"
            )
        )
        response = server._handle_jsonrpc_request(
            {
                "jsonrpc": "2.0",
                "id": page_number,
                "method": "resources/read",
                "params": {"uri": resource_uri},
            }
        )
        assert response is not None
        assert "error" not in response
        page = json.loads(response["result"]["contents"][0]["text"])
        pages.append(page["content"])
    repeated = server._handle_jsonrpc_request(
        {
            "jsonrpc": "2.0",
            "id": 100,
            "method": "resources/read",
            "params": {
                "uri": (
                    f"colameta://result-artifact/{handle.artifact_id}"
                    "/pages/1"
                )
            },
        }
    )

    assert repeated is not None and "error" not in repeated
    restored = "".join(pages)
    assert json.loads(restored) == payload
    assert scans == 1
    assert list(
        server._commander_public_result_artifact_safety_cache
    ) == [(handle.artifact_id, handle.content_sha256)]


def test_commander_concurrent_resource_reads_share_one_artifact_safety_scan(
    tmp_path,
    monkeypatch,
) -> None:
    server = MCPPlanningBridgeServer(
        str(tmp_path),
        exposure_profile="commander",
    )
    handle = server._mcp_result_artifact_store.put(
        tool="fixture",
        payload={
            "content": "\\" * 24_000 + "relative.txt",
            "label": "concurrent artifact",
        },
    )
    assert handle is not None
    assert handle.page_count >= 3

    waiter_entered = threading.Event()

    class ObservedFuture(Future):
        def result(self, timeout=None):
            waiter_entered.set()
            return super().result(timeout=timeout)

    monkeypatch.setattr(mcp_server_module, "Future", ObservedFuture)

    scan_entered = threading.Event()
    release_scan = threading.Event()
    scan_lock = threading.Lock()
    scans = 0
    original_safety = (
        server._commander_public_result_artifact_payload_safety
    )

    def blocking_safety(value: dict) -> bool:
        nonlocal scans
        with scan_lock:
            scans += 1
        scan_entered.set()
        assert release_scan.wait(timeout=5)
        return original_safety(value)

    monkeypatch.setattr(
        server,
        "_commander_public_result_artifact_payload_safety",
        blocking_safety,
    )

    def read_page(page: int) -> dict:
        uri = (
            f"colameta://result-artifact/{handle.artifact_id}"
            if page == 1
            else (
                f"colameta://result-artifact/{handle.artifact_id}"
                f"/pages/{page}"
            )
        )
        response = server._handle_jsonrpc_request(
            {
                "jsonrpc": "2.0",
                "id": page,
                "method": "resources/read",
                "params": {"uri": uri},
            }
        )
        assert response is not None
        return response

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(read_page, 1)
        assert scan_entered.wait(timeout=5)
        second = pool.submit(read_page, 2)
        try:
            assert waiter_entered.wait(timeout=5)
            assert scans == 1
        finally:
            release_scan.set()
        responses = [first.result(timeout=5), second.result(timeout=5)]

    assert all("error" not in response for response in responses)
    assert scans == 1
    assert not server._commander_public_result_artifact_safety_inflight
    assert list(
        server._commander_public_result_artifact_safety_cache
    ) == [(handle.artifact_id, handle.content_sha256)]


def test_commander_rejects_unsafe_uri_boundaries_across_artifact_reads(
    tmp_path,
) -> None:
    server = MCPPlanningBridgeServer(
        str(tmp_path),
        exposure_profile="commander",
    )
    unsafe_values = (
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
            "/pages/{page}∕private"
        ),
        (
            "colameta://result-artifact/opaque_handle_123_"
            "/pages/{page}\\u2215private"
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
        r"\Users\Jenn\secret.txt",
        json.dumps({"reason": r"\Windows\System32\config\SAM"}),
        (
            '{"reason":"\\u005cUsers\\u005cJenn'
            '\\u005csecret.txt"}'
        ),
        json.dumps(
            {
                "nested": json.dumps(
                    {"reason": r"\Users\Jenn\secret.txt"}
                )
            }
        ),
        r"\\server/share\private.txt",
        "//server/share/private.txt",
        "///server/share/private.txt",
        json.dumps({"reason": r"\\server/share\private.txt"}),
        json.dumps({"reason": r"\\server\share\private.txt"}),
        json.dumps({"reason": "//server/share/private.txt"}),
        json.dumps(
            {
                "nested": json.dumps(
                    {"reason": "//server/share/private.txt"}
                )
            }
        ),
        '{"reason":"\\/\\/server\\/share\\/private.txt"}',
        (
            '{"reason":"\\u002f\\u002fserver\\u002fshare'
            '\\u002fprivate.txt"}'
        ),
        (
            '{"reason":"safe C:\\u005cUsers\\u005cReviewer'
            '\\u005cprivate.txt"}'
        ),
        "C:/Users/Reviewer/private.txt",
        r"C:/Users\Reviewer/private.txt",
        '{"reason":"C:\\u002fUsers\\u002fReviewer\\u002fprivate.txt"}',
        '{"oauth\\u005ftoken":"synthetic-secret-value"}',
        'password="alpha beta gamma"',
        r'{\"client_secret\":\"alpha beta gamma\"}',
        "Authorization: Basic dXNlcjpwYXNzd29yZA==",
        "Basic dXNlcjpwYXNzd29yZA==",
        (
            '{"reason":"Authorization: '
            '\\u0042asic dXNlcjpwYXNzd29yZA=="}'
        ),
        '{"reason":"\\u0042asic dXNlcjpwYXNzd29yZA=="}',
        '{"apiKey":"synthetic-secret-value"}',
        '{"API Key":"synthetic-spaced-secret"}',
        "AWS_ACCESS_KEY_ID=synthetic-aws-access-id",
        "apiKey=delta epsilon zeta",
        "private-key=synthetic-private-key-value",
        "AWS_SECRET_ACCESS_KEY=synthetic-aws-secret-value",
        r'{\"apiKey\":\"synthetic-escaped-secret\"}',
        (
            "-----BEGIN PRIVATE KEY-----\n"
            "synthetic-private-key-material\n"
            "-----END PRIVATE KEY-----"
        ),
        (
            '{"pem":"-----BEGIN \\u0050RIVATE KEY-----'
            '\\nsynthetic-encoded-key-material"}'
        ),
        (
            "-----BEGIN PGP PRIVATE KEY BLOCK-----\n"
            "synthetic-pgp-key-material\n"
            "-----END PGP PRIVATE KEY BLOCK-----"
        ),
        (
            '{"armor":"-----BEGIN PGP \\u0050RIVATE KEY '
            '\\u0042LOCK-----\\nsynthetic-encoded-pgp-material"}'
        ),
        "passphrase=synthetic-passphrase-value",
        '{"passPhrase":"synthetic-camel-passphrase"}',
        "--passphrase synthetic-cli-passphrase",
        (
            "PuTTY-User-Key-File-3: ssh-ed25519\n"
            "Encryption: aes256-cbc\n"
            "Private-Lines: 1\n"
            "synthetic-putty-private-material"
        ),
        (
            '{"ppk":"PuTTY-User-Key-File-\\u0032\\u003a ssh-rsa'
            '\\nPrivate-Lines: 1'
            '\\nsynthetic-encoded-putty-private-material"}'
        ),
        SYNTHETIC_JWT,
        f'{{"access":"{ESCAPED_SYNTHETIC_JWT}"}}',
        json.dumps(
            {
                "wrapped": json.dumps(
                    {"access": ESCAPED_SYNTHETIC_JWT}
                )
            }
        ),
        SYNTHETIC_GITHUB_PAT,
        f'{{"access":"{ESCAPED_SYNTHETIC_GITHUB_PAT}"}}',
        json.dumps(
            {
                "wrapped": json.dumps(
                    {"access": ESCAPED_SYNTHETIC_GITHUB_PAT}
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
        "AccountKey=synthetic-azure-account-key",
        '{"Account\\u004bey":"synthetic-encoded-account-key"}',
        json.dumps(
            {
                "wrapped": (
                    "SharedAccess\\u0053ignature="
                    "sv=synthetic-version&sig=synthetic-nested-sas"
                )
            }
        ),
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
        "client_secret: alpha beta gamma",
        "password: correct horse battery staple",
        "_auth=dXNlcjpwYXNz",
        '{"\\u005fauth":"dXNlcjpwYXNz"}',
        json.dumps(
            {
                "wrapped": (
                    "//registry.npmjs.org/:"
                    "\\u005fauthToken=synthetic-nested-npm-token"
                )
            }
        ),
        (
            "https://provider.example.invalid/callback"
            "?api%5Fkey=synthetic-percent-artifact-secret"
        ),
        (
            '{"url":"https:\\/\\/provider.example.invalid\\/callback'
            '?api\\u00255Fkey=synthetic-json-percent-artifact-secret"}'
        ),
        json.dumps(
            {
                "wrapped": json.dumps(
                    {
                        "url": (
                            "https://provider.example.invalid/callback"
                            "?api%255Fkey="
                            "synthetic-nested-percent-artifact-secret"
                        )
                    }
                )
            }
        ),
        (
            "machine example.com login alice "
            "password synthetic-netrc-artifact-secret"
        ),
        (
            "machine example.com\n"
            "  login alice\n"
            "  password synthetic-multiline-netrc-artifact-secret"
        ),
        (
            '{"netrc":"machine example.com login alice '
            'password\\u0020synthetic-encoded-netrc-artifact-secret"}'
        ),
        json.dumps(
            {
                "wrapped": (
                    "machine example.com\\u0020login alice"
                    "\\u0020password synthetic-nested-netrc-artifact-secret"
                )
            }
        ),
        "https://alice:synthetic-password@example.com/repo",
        "postgresql://dbuser:synthetic-db-password@db.example/app",
        "//alice:synthetic-relative-password@example.com/repo",
        (
            '{"url":"https:\\/\\/alice:'
            'synthetic-escaped-password@example.com/repo"}'
        ),
        (
            '{"url":"https:\\u002f\\u002falice\\u003a'
            'synthetic-encoded-authority\\u0040example.com/repo"}'
        ),
        "--password synthetic-cli-password",
        "tool --api-key synthetic-cli-secret --verbose",
        (
            "curl -u alice:synthetic-curl-artifact-password "
            "https://example.invalid"
        ),
        (
            "curl --user=alice:synthetic-equals-curl-artifact-password "
            "https://example.invalid"
        ),
        (
            '{"command":"curl\\u0020--user\\u0020alice\\u003a'
            'synthetic-encoded-curl-artifact-password '
            'https:\\/\\/example.invalid"}'
        ),
        json.dumps(
            {
                "wrapped": (
                    "curl%20-ualice%3A"
                    "synthetic-nested-curl-artifact-password%20"
                    "https%3A%2F%2Fexample.invalid"
                )
            }
        ),
        EXHAUSTING_PERCENT_ENCODED_SAFE_PROSE,
        EXHAUSTING_PERCENT_ENCODED_SENSITIVE_ASSIGNMENT,
        (
            '{"command":"tool --api-key\\u0020'
            'synthetic-encoded-space-cli-secret"}'
        ),
        (
            '{"command":"tool --client\\u002dsecret '
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
        "Cookie: session=abc; csrf=def",
        (
            'Authorization: Digest username="Mufasa", '
            'response="deadbeef"'
        ),
        r'{\"Cookie\":\"session=abc; csrf=def\"}',
        (
            '{"reason":"Authorization: \\u0044igest '
            'username=\\"Mufasa\\", response=\\"deadbeef\\""}'
        ),
        '{"reason":"\\u0042earer abcdefghijklmnop"}',
        '{"reason":"manage\\u005ffiles"}',
        json.dumps(
            {"reason": '{"tool":"manage\\u005fexecutor\\u005fworkflow"}'}
        ),
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
    )
    for unsafe_uri in unsafe_values:
        handle = server._mcp_result_artifact_store.put(
            tool="fixture",
            payload={"content": unsafe_uri},
        )

        assert handle is not None
        typed = server.call_tool_for_agent(
            "read_result_artifact",
            {"artifact_id": handle.artifact_id, "artifact_page": 1},
        )
        assert typed["ok"] is False
        assert typed["data"]["outcome"] == "blocked"
        assert typed["data"]["error"]["code"] == "EVIDENCE_UNAVAILABLE"
        assert unsafe_uri not in json.dumps(typed, ensure_ascii=False)

        resource = server._handle_jsonrpc_request(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "resources/read",
                "params": {
                    "uri": f"colameta://result-artifact/{handle.artifact_id}",
                },
            }
        )
        assert resource is not None
        assert resource["error"]["data"]["error_code"] == "evidence_unavailable"
        assert unsafe_uri not in json.dumps(resource, ensure_ascii=False)


def test_commander_rejects_unsafe_artifact_across_tool_and_resource_reads(
    tmp_path,
) -> None:
    server = MCPPlanningBridgeServer(
        str(tmp_path),
        exposure_profile="commander",
    )
    serialized_probe = json.dumps(
        {"content": ""},
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    content_start = serialized_probe.index('""') + 1
    private_path = "/home/reviewer/example.md"
    prefix = "x" * (12_000 - content_start - 2)
    payload = {
        "content": f"{prefix}{private_path}\n",
        "oauth_token": "must-not-cross-the-public-boundary",
    }
    serialized_payload = json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    private_path_start = serialized_payload.index(private_path)
    assert private_path_start < 12_000 < private_path_start + len(private_path)
    handle = server._mcp_result_artifact_store.put(
        tool="fixture",
        payload=payload,
    )

    assert handle is not None
    typed = server.call_tool_for_agent(
        "read_result_artifact",
        {"artifact_id": handle.artifact_id, "artifact_page": 1},
    )
    assert typed["ok"] is False
    assert typed["data"]["outcome"] == "blocked"
    assert typed["data"]["error"]["code"] == "EVIDENCE_UNAVAILABLE"
    assert "/home/" not in json.dumps(typed, ensure_ascii=False)
    assert "must-not-cross" not in json.dumps(typed, ensure_ascii=False)

    resource = server._handle_jsonrpc_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "resources/read",
            "params": {
                "uri": f"colameta://result-artifact/{handle.artifact_id}",
            },
        }
    )
    assert resource is not None
    assert resource["error"]["data"]["error_code"] == "evidence_unavailable"
    assert "/home/" not in json.dumps(resource, ensure_ascii=False)
    assert "must-not-cross" not in json.dumps(resource, ensure_ascii=False)


def test_commander_artifact_scan_rejects_unsafe_resource_reference_siblings(
    tmp_path,
) -> None:
    server = MCPPlanningBridgeServer(
        str(tmp_path),
        exposure_profile="commander",
    )
    payload = {
        "recommended_next_reads": [
            {
                "kind": "mcp_resource",
                "tool": "resources/read",
                "arguments": {
                    "uri": "colameta://result-artifact/abcdefghijklmnop",
                },
                "reason": "Read the opaque public evidence.",
                "project_root": "/home/reviewer/private-project",
                "oauth_token": "synthetic-token-must-not-cross",
                "diagnostics": {
                    "stderr": "synthetic diagnostic must not cross",
                },
            }
        ]
    }
    handle = server._mcp_result_artifact_store.put(
        tool="fixture",
        payload=payload,
    )

    assert handle is not None
    typed = server.call_tool_for_agent(
        "read_result_artifact",
        {"artifact_id": handle.artifact_id, "artifact_page": 1},
    )
    assert typed["ok"] is False
    assert typed["data"]["outcome"] == "blocked"
    assert typed["data"]["error"]["code"] == "EVIDENCE_UNAVAILABLE"
    rendered = json.dumps(typed, ensure_ascii=False)
    assert "/home/reviewer" not in rendered
    assert "synthetic-token-must-not-cross" not in rendered
    assert "synthetic diagnostic must not cross" not in rendered

    resource = server._handle_jsonrpc_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "resources/read",
            "params": {
                "uri": f"colameta://result-artifact/{handle.artifact_id}",
            },
        }
    )
    assert resource is not None
    assert resource["error"]["data"]["error_code"] == "evidence_unavailable"
    rendered_resource = json.dumps(resource, ensure_ascii=False)
    assert "/home/reviewer" not in rendered_resource
    assert "synthetic-token-must-not-cross" not in rendered_resource
    assert "synthetic diagnostic must not cross" not in rendered_resource


def test_typed_result_artifact_tool_reads_exact_pages_and_returns_typed_continuation(tmp_path) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path), exposure_profile="commander")
    payload = {"content": "typed result artifact\n" + ("x" * 30000)}
    handle = server._mcp_result_artifact_store.put(tool="fixture", payload=payload)

    assert handle is not None
    assert "read_result_artifact" in server._visible_tool_names()
    assert server.get_required_scope_for_tool(
        "read_result_artifact",
        {"artifact_id": handle.artifact_id},
    ) == "mcp:read"

    pages: list[str] = []
    for page_number in range(1, handle.page_count + 1):
        result = server.call_tool_for_agent(
            "read_result_artifact",
            {"artifact_id": handle.artifact_id, "artifact_page": page_number},
        )
        assert result["ok"] is True
        contract = result["data"]
        facts = contract["facts"]
        evidence = contract["evidence"]
        assert facts["read_only"] is True
        assert facts["side_effects"] is False
        assert evidence["artifact_id"] == handle.artifact_id
        assert evidence["content_sha256"] == handle.content_sha256
        pages.append(facts["artifact_page"]["content"])
        if page_number < handle.page_count:
            assert contract["next_action"] == {
                "tool": "read_result_artifact",
                "arguments": {
                    "artifact_id": handle.artifact_id,
                    "artifact_page": page_number + 1,
                },
                "reason": "继续读取同一短期 artifact 的下一页；artifact_id、expires_at 与 content_sha256 保持不变。",
            }

    restored = "".join(pages)
    assert hashlib.sha256(restored.encode("utf-8")).hexdigest() == handle.content_sha256
    assert json.loads(restored) == payload


def test_typed_result_artifact_rejects_a_mismatched_prevalidated_page(
    tmp_path,
    monkeypatch,
) -> None:
    server = MCPPlanningBridgeServer(
        str(tmp_path),
        exposure_profile="commander",
    )
    payload = {
        "content": (
            ("a" * 13000)
            + "synthetic-page-two-only-marker"
        )
    }
    handle = server._mcp_result_artifact_store.put(
        tool="fixture",
        payload=payload,
    )

    assert handle is not None
    assert handle.page_count == 2
    original_read_page = server._mcp_result_artifact_store.read_page
    wrong_page = original_read_page(handle.artifact_id, 2)
    assert wrong_page is not None
    assert "synthetic-page-two-only-marker" in wrong_page.content

    monkeypatch.setattr(
        server,
        "_commander_public_result_artifact_safety",
        lambda _artifact_id: True,
    )

    def read_mismatched_page(
        artifact_id: str,
        page: int = 1,
    ):
        if artifact_id == handle.artifact_id and page == 1:
            return wrong_page
        return original_read_page(artifact_id, page)

    monkeypatch.setattr(
        server._mcp_result_artifact_store,
        "read_page",
        read_mismatched_page,
    )

    result = server.call_tool_for_agent(
        "read_result_artifact",
        {
            "artifact_id": handle.artifact_id,
            "artifact_page": 1,
        },
    )

    assert result["ok"] is False
    assert result["data"]["outcome"] == "failed"
    assert result["data"]["error"]["code"] == "INTERNAL_RESULT_INVALID"
    assert "synthetic-page-two-only-marker" not in json.dumps(
        result,
        ensure_ascii=False,
    )


def test_typed_result_artifact_validates_whole_payload_before_slicing_resource_uri(
    tmp_path,
) -> None:
    server = MCPPlanningBridgeServer(
        str(tmp_path),
        exposure_profile="commander",
    )
    resource_uri = (
        "colameta://result-artifact/opaque_handle_123_"
        "/pages/{page}"
    )
    target_start = (
        MCP_RESULT_ARTIFACT_PAGE_CHARS - (len(resource_uri) // 2)
    )
    probe = json.dumps(
        {"content": f" {resource_uri}\n"},
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    filler_chars = target_start - probe.index(resource_uri)
    payload = {
        "content": f"{'x' * filler_chars} {resource_uri}\n",
    }
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    uri_start = serialized.index(resource_uri)
    assert (
        uri_start
        < MCP_RESULT_ARTIFACT_PAGE_CHARS
        < uri_start + len(resource_uri)
    )
    handle = server._mcp_result_artifact_store.put(
        tool="fixture",
        payload=payload,
    )

    assert handle is not None
    assert handle.page_count == 2
    pages: list[str] = []
    for page_number in (1, 2):
        result = server.call_tool_for_agent(
            "read_result_artifact",
            {
                "artifact_id": handle.artifact_id,
                "artifact_page": page_number,
            },
        )

        assert result["ok"] is True
        contract = result["data"]
        validate_commander_response(
            contract,
            exact_evidence_prevalidated=True,
        )
        page = contract["facts"]["artifact_page"]
        assert page["page"] == page_number
        pages.append(page["content"])

    assert pages[0] == serialized[:MCP_RESULT_ARTIFACT_PAGE_CHARS]
    assert pages[1] == serialized[MCP_RESULT_ARTIFACT_PAGE_CHARS:]
    assert "".join(pages) == serialized


def test_typed_result_artifact_tool_requires_only_a_known_opaque_handle(tmp_path) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path), exposure_profile="commander")
    tool = next(tool for tool in server.tool_defs if tool.name == "read_result_artifact")

    assert "phase" not in tool.input_schema["properties"]
    assert tool.input_schema["required"] == ["artifact_id"]

    missing = server.call_tool_for_agent("read_result_artifact", {})
    assert missing["ok"] is False
    assert missing["error_code"] == "RESOURCE_URI_INVALID"

    unknown = server.call_tool_for_agent(
        "read_result_artifact",
        {"artifact_id": "abcdefghijklmnopqrstuvwx", "artifact_page": 1},
    )
    assert unknown["ok"] is False
    assert unknown["error_code"] == "ARTIFACT_EXPIRED"

    invalid_phase = server.call_tool_for_agent(
        "read_result_artifact",
        {"artifact_id": "abcdefghijklmnopqrstuvwx", "phase": "verify"},
    )
    assert invalid_phase["ok"] is False
    assert invalid_phase["error_code"] == "WORKFLOW_NOT_SUPPORTED"


def test_result_artifact_compatibility_is_read_scoped_and_fails_closed(tmp_path) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path), exposure_profile="commander")
    handle = server._mcp_result_artifact_store.put(
        tool="fixture",
        payload={"content": "x" * 30000},
    )

    assert handle is not None
    assert server.get_required_scope_for_tool(
        "run_mcp_workflow",
        {"workflow": MCP_RESULT_ARTIFACT_WORKFLOW, "phase": "read"},
    ) == "mcp:read"

    missing = server.call_tool_for_agent(
        "run_mcp_workflow",
        {"workflow": MCP_RESULT_ARTIFACT_WORKFLOW, "phase": "read"},
    )
    assert missing["ok"] is False
    assert missing["error_code"] == "RESOURCE_URI_INVALID"

    invalid_page = server.call_tool_for_agent(
        "run_mcp_workflow",
        {
            "workflow": MCP_RESULT_ARTIFACT_WORKFLOW,
            "phase": "read",
            "artifact_id": handle.artifact_id,
            "artifact_page": 0,
        },
    )
    assert invalid_page["ok"] is False
    assert invalid_page["error_code"] == "RESOURCE_URI_INVALID"

    missing_or_expired = server.call_tool_for_agent(
        "run_mcp_workflow",
        {
            "workflow": MCP_RESULT_ARTIFACT_WORKFLOW,
            "phase": "read",
            "artifact_id": "abcdefghijklmnopqrstuvwx",
            "artifact_page": 1,
        },
    )
    assert missing_or_expired["ok"] is False
    assert missing_or_expired["error_code"] == "ARTIFACT_EXPIRED"

    invalid_phase = server.call_tool_for_agent(
        "run_mcp_workflow",
        {
            "workflow": MCP_RESULT_ARTIFACT_WORKFLOW,
            "phase": "verify",
            "artifact_id": handle.artifact_id,
        },
    )
    assert invalid_phase["ok"] is False
    assert invalid_phase["error_code"] == "SCOPE_VIOLATION"


def test_result_artifact_compatibility_and_typed_read_allow_external_oauth_without_project_name(tmp_path) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path), exposure_profile="commander")
    handle = server._mcp_result_artifact_store.put(
        tool="fixture",
        payload={"content": "x" * 30000},
    )

    assert handle is not None

    class _ScopeProvider:
        @staticmethod
        def validate_scope(token_payload: dict, scope: str) -> bool:
            return scope in str(token_payload.get("scope") or "").split()

    authorized = server.call_tool_for_agent(
        "run_mcp_workflow",
        {
            "workflow": MCP_RESULT_ARTIFACT_WORKFLOW,
            "phase": "read",
            "artifact_id": handle.artifact_id,
            "artifact_page": 1,
        },
        auth_context={
            "mode": "external-oauth",
            "oauth_provider": _ScopeProvider(),
            "token": {"scope": "mcp:read"},
        },
    )
    assert authorized["ok"] is True
    assert (
        authorized["data"]["facts"]["artifact_page"]["artifact_id"]
        == handle.artifact_id
    )

    typed_authorized = server.call_tool_for_agent(
        "read_result_artifact",
        {
            "artifact_id": handle.artifact_id,
            "artifact_page": 1,
        },
        auth_context={
            "mode": "external-oauth",
            "oauth_provider": _ScopeProvider(),
            "token": {"scope": "mcp:read"},
        },
    )
    assert typed_authorized["ok"] is True
    assert (
        typed_authorized["data"]["facts"]["artifact_page"]["artifact_id"]
        == handle.artifact_id
    )

    denied = server.call_tool_for_agent(
        "run_mcp_workflow",
        {
            "workflow": MCP_RESULT_ARTIFACT_WORKFLOW,
            "phase": "read",
            "artifact_id": handle.artifact_id,
            "artifact_page": 1,
        },
        auth_context={
            "mode": "external-oauth",
            "oauth_provider": _ScopeProvider(),
            "token": {"scope": "mcp:preview"},
        },
    )
    assert denied["ok"] is False
    assert denied["error_code"] == "SCOPE_VIOLATION"

    typed_denied = server.call_tool_for_agent(
        "read_result_artifact",
        {
            "artifact_id": handle.artifact_id,
            "artifact_page": 1,
        },
        auth_context={
            "mode": "external-oauth",
            "oauth_provider": _ScopeProvider(),
            "token": {"scope": "mcp:preview"},
        },
    )
    assert typed_denied["ok"] is False
    assert typed_denied["error_code"] == "SCOPE_VIOLATION"


def test_unavailable_artifact_store_never_returns_a_hollow_packaged_manifest(tmp_path, monkeypatch) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path))
    monkeypatch.setattr(server, "_store_packaged_result_artifact", lambda *_args: None)

    shaped = server._shape_mcp_call_result(
        {"ok": True, "tool": "manage_files", "data": {"content": "x" * 30000}},
        {"action": "read", "file": "CURRENT_STATE.md"},
    )

    result = shaped["structuredContent"]
    assert result["ok"] is False
    assert result["packaged"] is False
    assert result["error_code"] == "MCP_RESULT_ARTIFACT_UNAVAILABLE"
    assert "artifact_id" not in result


def test_result_artifacts_are_not_discoverable_and_require_read_scope_when_authenticated(tmp_path) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path))
    shaped = server._shape_mcp_call_result(
        {"ok": True, "tool": "manage_files", "data": {"content": "x" * 30000}},
        {"action": "read", "file": "CURRENT_STATE.md"},
    )
    artifact_uri = shaped["structuredContent"]["resource_uri"]

    listed = server._handle_jsonrpc_request(
        {"jsonrpc": "2.0", "id": 1, "method": "resources/list", "params": {}}
    )
    assert listed is not None
    assert [resource["uri"] for resource in listed["result"]["resources"]] == [COMMANDER_APP_WIDGET_URI]

    class _ScopeProvider:
        @staticmethod
        def validate_scope(token_payload: dict, scope: str) -> bool:
            return scope in str(token_payload.get("scope") or "").split()

    denied = server._handle_jsonrpc_request(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "resources/read",
            "params": {"uri": artifact_uri},
        },
        auth_context={
            "mode": "external-oauth",
            "oauth_provider": _ScopeProvider(),
            "token": {"scope": "mcp:preview"},
        },
    )
    assert denied is not None
    assert denied["error"]["data"]["error_code"] == "resource_access_denied"

    relay_denied = server._handle_jsonrpc_request(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "resources/read",
            "params": {"uri": artifact_uri},
        },
        auth_context={"mode": "cloud-relay", "scopes": ["mcp:preview"]},
    )
    assert relay_denied is not None
    assert relay_denied["error"]["data"]["error_code"] == "resource_access_denied"

    missing = server._handle_jsonrpc_request(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "resources/read",
            "params": {"uri": "colameta://result-artifact/abcdefghijklmnop"},
        },
    )
    assert missing is not None
    assert missing["error"]["data"]["error_code"] == "result_artifact_not_found_or_expired"
