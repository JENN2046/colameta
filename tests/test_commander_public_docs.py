from __future__ import annotations

import json
import re
from pathlib import Path

from runner.commander_contract import validate_commander_response
from runner.mcp_commander_public import COMMANDER_EXPOSED_TOOLS


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_DOC = ROOT / "docs" / "commander-public-response-minimization.md"
USAGE_DOCS = (
    ROOT / "docs" / "USAGE.md",
    ROOT / "docs" / "USAGE.zh-CN.md",
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
