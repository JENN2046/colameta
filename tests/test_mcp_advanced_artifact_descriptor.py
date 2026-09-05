from __future__ import annotations

import copy
import json

import pytest

from runner.mcp_commander_public import COMMANDER_EXPOSED_TOOLS, CommanderPublicProjector


def _descriptor():
    artifact_id = "synthetic_artifact_123"
    return {
        "kind": "result_artifact",
        "artifact_id": artifact_id,
        "resource_uri": f"colameta://result-artifact/{artifact_id}",
        "page_uri_template": f"colameta://result-artifact/{artifact_id}/pages/{{page}}",
        "page_count": 2,
        "content_sha256": "a" * 64,
        "expires_at": "2026-09-04T12:34:56.123456+00:00",
    }


def _owner_projector():
    return CommanderPublicProjector(
        "/synthetic/project",
        exposed_tool_names=(*COMMANDER_EXPOSED_TOOLS, "get_agent_operator_flow_packet"),
    )


@pytest.mark.parametrize("expiry", [
    "2026-09-04T12:34:56.123456+00:00",
    "2026-09-04T12:34:56Z",
    "2026-09-04T12:34:56-03:00",
])
def test_typed_descriptor_expiry_survives_repeated_projection(expiry):
    descriptor = _descriptor()
    descriptor["expires_at"] = expiry
    payload = {
        "ok": True,
        "tool": "get_agent_operator_flow_packet",
        "data": {
            "advanced_context_artifact": descriptor,
            "diagnostic": {"expires_at": expiry, "created_at": expiry},
        },
    }
    projector = _owner_projector()
    first = projector.project_tool_result(payload)
    assert first["data"]["advanced_context_artifact"] == descriptor
    assert first["data"]["diagnostic"] == {}
    assert projector.project_tool_result(first) == first
    stored = projector.sanitize_for_artifact(payload)
    assert stored["data"]["advanced_context_artifact"] == descriptor
    assert projector.sanitize_for_artifact(stored) == stored


@pytest.mark.parametrize("changes", [
    {"kind": "unknown"},
    {"artifact_id": "/home/synthetic/private"},
    {"resource_uri": "colameta://result-artifact/different_artifact_id"},
    {"resource_uri": "https://synthetic.invalid/private"},
    {"page_uri_template": "colameta://result-artifact/different_artifact_id/pages/{page}"},
    {"page_count": True},
    {"page_count": 0},
    {"page_count": "2"},
    {"content_sha256": "invalid"},
    {"expires_at": "2026-09-04T12:34:56"},
    {"expires_at": "2026-02-30T12:34:56Z"},
    {"expires_at": "/home/synthetic/private"},
    {"expires_at": {"private": "synthetic-value"}},
    {"extra": "synthetic-value"},
    {"created_at": "2026-09-04T12:34:56Z"},
])
def test_malformed_descriptor_does_not_bypass_generic_redaction(changes):
    descriptor = _descriptor()
    descriptor.update(changes)
    source = {"advanced_context_artifact": descriptor}
    untouched = copy.deepcopy(source)
    projector = _owner_projector()
    assert projector.sanitize(source, compact=False) == {}
    assert projector.sanitize_for_artifact(source) == {}
    assert source == untouched


@pytest.mark.parametrize("missing", list(_descriptor()))
def test_incomplete_descriptor_is_not_preserved(missing):
    descriptor = _descriptor()
    del descriptor[missing]
    assert _owner_projector().sanitize(
        {"advanced_context_artifact": descriptor}, compact=False,
    ) == {}


def test_commander_does_not_expose_owner_continuation_descriptor():
    descriptor = _descriptor()
    projected = CommanderPublicProjector("/synthetic/project").sanitize(
        {"advanced_context_artifact": descriptor}, compact=False,
    )
    assert projected == {}
    assert descriptor["artifact_id"] not in json.dumps(projected)
