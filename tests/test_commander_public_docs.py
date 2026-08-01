from __future__ import annotations

import json
import re
from pathlib import Path

from runner.commander_contract import validate_commander_response
from runner.mcp_commander_public import COMMANDER_EXPOSED_TOOLS


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_DOC = ROOT / "docs" / "commander-public-response-minimization.md"
AGENT_CONSUMER_CONTRACT_ZH = (
    ROOT / "docs" / "agent-consumer-contract.zh-CN.md"
)
USAGE_DOCS = (
    ROOT / "docs" / "USAGE.md",
    ROOT / "docs" / "USAGE.zh-CN.md",
)
CURRENT_COMMANDER_GUIDES = (
    ROOT / "README.md",
    ROOT / "README.zh-CN.md",
    ROOT / "docs" / "ONBOARDING.md",
    ROOT / "docs" / "ONBOARDING.zh-CN.md",
    ROOT / "docs" / "agent-consumer-contract.zh-CN.md",
    ROOT / "docs" / "connector-runtime-health-observability.md",
    ROOT / "docs" / "jenn-private-operator-protocol.md",
    ROOT / "docs" / "private-beta-systemd.md",
    ROOT / "docs" / "remote-https-mcp-service.md",
    ROOT / "docs" / "runtime-loaded-code-verification.md",
    ROOT / "docs" / "web-gpt-service-entrypoint.zh-CN.md",
)
COMMANDER_INVENTORY_GUIDES = (
    ROOT / "README.md",
    ROOT / "README.zh-CN.md",
    ROOT / "docs" / "ONBOARDING.md",
    ROOT / "docs" / "ONBOARDING.zh-CN.md",
    ROOT / "docs" / "agent-consumer-contract.zh-CN.md",
    ROOT / "docs" / "web-gpt-service-entrypoint.zh-CN.md",
)
RESPONSE_FIELDS = (
    "schema_version",
    "outcome",
    "summary",
    "journey_stage",
    "context_binding",
    "facts",
    "evidence",
    "next_action",
    "confirmation",
    "error",
)


def test_current_commander_guides_do_not_restore_the_seven_tool_contract() -> None:
    stale_inventory = re.compile(
        r"(?i)(?:"
        r"exactly seven(?: public| commander)? tools"
        r"|seven[- ]tool(?: commander| private app| contract| profile| surface)?"
        r"|七工具"
        r"|7\s*个工具"
        r")"
    )

    for path in CURRENT_COMMANDER_GUIDES:
        text = path.read_text(encoding="utf-8")
        assert stale_inventory.search(text) is None, path


def test_current_commander_inventory_guides_list_all_nine_public_tools() -> None:
    assert len(COMMANDER_EXPOSED_TOOLS) == 9
    for path in COMMANDER_INVENTORY_GUIDES:
        text = path.read_text(encoding="utf-8")
        for tool_name in COMMANDER_EXPOSED_TOOLS:
            assert tool_name in text, (path, tool_name)
        assert "review_manifest" in text
        assert "read_result_artifact" in text


def test_commander_contract_doc_tracks_current_schema_and_tool_inventory() -> None:
    text = CONTRACT_DOC.read_text(encoding="utf-8")

    assert "commander_response.v1" in text
    assert "nine-tool" in text
    assert "commander_public_minimal.v1" not in text
    assert "seven-tool" not in text
    for tool_name in COMMANDER_EXPOSED_TOOLS:
        assert f"`{tool_name}`" in text
    for field in RESPONSE_FIELDS:
        assert f'"{field}"' in text or f"`data.{field}`" in text


def test_commander_contract_doc_response_example_validates() -> None:
    text = CONTRACT_DOC.read_text(encoding="utf-8")
    match = re.search(r"```json\n(?P<payload>\{.*?\})\n```", text, re.DOTALL)

    assert match is not None
    envelope = json.loads(match.group("payload"))
    assert envelope["tool"] in COMMANDER_EXPOSED_TOOLS
    validate_commander_response(envelope["data"])


def test_usage_docs_require_nested_commander_response_paths() -> None:
    for path in USAGE_DOCS:
        text = path.read_text(encoding="utf-8")

        assert "data.schema_version=commander_response.v1" in text
        for field in (
            "data.outcome",
            "data.facts",
            "data.evidence",
            "data.next_action",
            "data.confirmation",
            "data.error",
            "data.context_binding",
            "data.facts.canonical_state",
            "data.evidence.review_manifest_id",
            "data.facts.subject_page",
        ):
            assert field in text
        assert "data.evidence.kind=result_artifact" in text
        assert "packaged=true" not in text
        assert "Read data, then check read_only" not in text
        assert "读取 data；继续看 read_only" not in text


def test_public_docs_keep_artifact_reads_separate_from_confirmation_actions() -> None:
    english = USAGE_DOCS[0].read_text(encoding="utf-8")
    chinese = USAGE_DOCS[1].read_text(encoding="utf-8")
    contract = CONTRACT_DOC.read_text(encoding="utf-8")

    assert "When data.outcome=completed" in english
    assert "For confirmation_required" in english
    assert "Do not invoke the confirmation action" in english
    assert "仅当 data.outcome=completed" in chinese
    assert "对于 confirmation_required" in chinese
    assert "不得为了读取 Artifact 而执行确认动作" in chinese
    assert "When `data.outcome=completed`" in contract
    assert "For `confirmation_required`" in contract
    assert "never invoke the confirmation action" in contract


def test_usage_docs_keep_commander_error_recovery_on_the_public_surface() -> None:
    section_bounds = (
        (USAGE_DOCS[0], "Common errors:", "### Manifest-bound independent review"),
        (USAGE_DOCS[1], "最常见的错误处理：", "### Manifest 绑定的独立审查"),
    )

    for path, start, end in section_bounds:
        text = path.read_text(encoding="utf-8")
        section = text.split(start, maxsplit=1)[1].split(end, maxsplit=1)[0]

        assert "PROJECT_CONTEXT_MISMATCH" in section
        assert "INTERNAL_ERROR" in section
        assert "analyze_project_state" in section
        assert "get_apps_connector_smoke_packet" in section
        assert "PROJECT_ROOT_OVERRIDE_NOT_ALLOWED" not in section
        assert "UNKNOWN_SERVICE_ENTRY_PROFILE" not in section
        assert "get_agent_consumer_contract" not in section
        for tool_name in (
            "list_registered_projects",
            "analyze_project_state",
            "get_apps_connector_smoke_packet",
        ):
            assert tool_name in COMMANDER_EXPOSED_TOOLS


def test_usage_docs_expose_only_the_public_manifest_hash_error() -> None:
    section_bounds = (
        (
            USAGE_DOCS[0],
            "### Manifest-bound independent review",
            "### Confirmation-bound actions and canonical project state",
        ),
        (
            USAGE_DOCS[1],
            "### Manifest 绑定的独立审查",
            "### 确认性操作上下文绑定与统一项目状态",
        ),
    )

    for path, start, end in section_bounds:
        text = path.read_text(encoding="utf-8")
        section = text.split(start, maxsplit=1)[1].split(end, maxsplit=1)[0]

        assert "STALE_CONTEXT" in section
        assert "REVIEW_MANIFEST_SUBJECT_HASH_MISMATCH" not in section


def test_agent_consumer_contract_distinguishes_manifest_context_errors() -> None:
    text = AGENT_CONSUMER_CONTRACT_ZH.read_text(encoding="utf-8")
    section = text.split(
        "## Manifest 绑定的独立审查",
        maxsplit=1,
    )[1].split("## Thin Governed Loop 使用规则", maxsplit=1)[0]

    assert "data.error.code=PROJECT_CONTEXT_MISMATCH" in section
    assert "data.error.code=STALE_CONTEXT" in section
    assert "绑定值不一致" in section
    assert "subject SHA-256 已漂移" in section
    assert "REVIEW_MANIFEST_SUBJECT_HASH_MISMATCH" not in section
