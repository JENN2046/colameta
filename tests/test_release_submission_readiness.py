from __future__ import annotations

import json

from runner.release_submission_readiness import (
    DEFAULT_SUBMISSION_MATERIALS_REL_PATH,
    build_release_submission_readiness,
)


def _readiness(*, ready: bool = True, ops_ready: bool = True, connector_ready: bool = True) -> dict[str, object]:
    return {
        "status": "ready" if ready else "blocked",
        "ready": ready,
        "public_base_url": "https://example.test",
        "connector_url": "https://example.test/mcp",
        "primary_blocker": None if ready else {"check": "stable_runtime"},
        "ops_check": {
            "ops_check_ready": ops_ready,
            "connector_smoke_ready": connector_ready,
            "beta_gate_ready": ops_ready and connector_ready,
        },
    }


def _ready_kwargs() -> dict[str, object]:
    return {
        "app_name": "ColaMeta",
        "app_description": "Project console for local AI engineering workflows.",
        "company_url": "https://example.test",
        "privacy_policy_url": "https://example.test/privacy",
        "logo_ready": True,
        "screenshots_ready": True,
        "test_prompts_ready": True,
        "test_responses_ready": True,
        "localization_ready": True,
        "mcp_tool_info_ready": True,
        "app_management_permissions_confirmed": True,
        "security_review_ready": True,
        "metadata_snapshot_reviewed": True,
        "submission_confirmations_ready": True,
    }


def _evidence_refs() -> dict[str, object]:
    return {
        "logo": "docs/submission/logo.png",
        "screenshots": ["docs/submission/screenshot-1.png"],
        "test_prompts": "docs/submission/test-prompts.md",
        "test_responses": "docs/submission/test-responses.md",
        "localization": "docs/submission/localization.md",
        "mcp_tool_info": "docs/submission/mcp-tool-info.md",
        "app_management_permissions": "docs/submission/app-management-permissions.md",
        "security_review": "docs/submission/security-review.md",
        "metadata_snapshot": "docs/submission/metadata-snapshot.md",
        "submission_confirmations": "docs/submission/submission-confirmations.md",
    }


def _write_evidence_files(project_root) -> None:
    for value in _evidence_refs().values():
        refs = value if isinstance(value, list) else [value]
        for ref in refs:
            path = project_root / ref
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("evidence\n", encoding="utf-8")


def test_release_submission_readiness_ready_when_all_local_evidence_present() -> None:
    packet = build_release_submission_readiness(
        "/tmp/project",
        project_name="demo-project",
        readiness_packet=_readiness(),
        **_ready_kwargs(),
    )

    assert packet["source"] == "release_submission_readiness"
    assert packet["status"] == "ready"
    assert packet["ready"] is True
    assert packet["checks"]["submission_form_assets"]["status"] == "ready"
    assert packet["authority_boundary"]["does_not_submit_app_for_review"] is True
    assert packet["safe_next_action"]["action"] == "open_openai_dashboard_submission_form"
    assert packet["checks"]["submission_materials_manifest"]["status"] == "ready"


def test_release_submission_blocks_when_product_readiness_is_not_ready() -> None:
    packet = build_release_submission_readiness(
        "/tmp/project",
        readiness_packet=_readiness(ready=False, ops_ready=False),
        **_ready_kwargs(),
    )

    assert packet["status"] == "blocked"
    assert "PRODUCT_READINESS_NOT_READY" in packet["blocker_codes"]
    assert "PUBLIC_MCP_ENDPOINT_NOT_READY" in packet["blocker_codes"]
    assert packet["safe_next_action"]["tool"] == "get_product_readiness_status"


def test_release_submission_needs_materials_before_ready() -> None:
    packet = build_release_submission_readiness(
        "/tmp/project",
        readiness_packet=_readiness(),
        app_name="ColaMeta",
        company_url="https://example.test",
    )

    assert packet["status"] == "needs_attention"
    assert "SUBMISSION_MATERIALS_MISSING" in packet["needs_attention_codes"]
    assert "app_description" in packet["checks"]["submission_form_assets"]["missing"]
    assert packet["checks"]["security_privacy"]["status"] == "needs_attention"
    assert packet["safe_next_action"]["action"] == "complete_submission_materials"


def test_release_submission_accepts_structured_materials_manifest(tmp_path) -> None:
    _write_evidence_files(tmp_path)
    packet = build_release_submission_readiness(
        str(tmp_path),
        readiness_packet=_readiness(),
        submission_materials={
            "schema_version": "chatgpt_app_submission_materials.v1",
            **_ready_kwargs(),
            "evidence": _evidence_refs(),
        },
    )

    assert packet["status"] == "ready"
    assert packet["submission_materials"]["source"] == "manifest"
    assert packet["submission_materials"]["schema_version"] == "chatgpt_app_submission_materials.v1"
    assert "app_name" in packet["submission_materials"]["manifest_fields"]
    assert "screenshots_ready" in packet["submission_materials"]["effective_fields"]
    assert packet["checks"]["submission_evidence_references"]["status"] == "ready"
    assert packet["checks"]["submission_materials_manifest"]["reason_codes"] == [
        "SUBMISSION_MATERIALS_MANIFEST_ACCEPTED"
    ]


def test_release_submission_auto_loads_default_materials_manifest(tmp_path) -> None:
    _write_evidence_files(tmp_path)
    manifest_path = tmp_path / DEFAULT_SUBMISSION_MATERIALS_REL_PATH
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "chatgpt_app_submission_materials.v1",
                **_ready_kwargs(),
                "evidence": _evidence_refs(),
            }
        ),
        encoding="utf-8",
    )

    packet = build_release_submission_readiness(str(tmp_path), readiness_packet=_readiness())

    assert packet["status"] == "ready"
    assert packet["submission_materials"]["source"] == "default_manifest_file"
    assert packet["submission_materials"]["source_detail"]["path"] == DEFAULT_SUBMISSION_MATERIALS_REL_PATH
    assert packet["checks"]["submission_materials_manifest"]["status"] == "ready"
    assert packet["checks"]["submission_evidence_references"]["status"] == "ready"


def test_release_submission_reports_invalid_default_materials_manifest(tmp_path) -> None:
    manifest_path = tmp_path / DEFAULT_SUBMISSION_MATERIALS_REL_PATH
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text("{", encoding="utf-8")

    packet = build_release_submission_readiness(str(tmp_path), readiness_packet=_readiness())

    assert packet["status"] == "needs_attention"
    assert "SUBMISSION_MATERIALS_MANIFEST_INVALID" in packet["needs_attention_codes"]
    assert packet["submission_materials"]["error"]["path"] == DEFAULT_SUBMISSION_MATERIALS_REL_PATH
    assert packet["submission_materials"]["error"]["error_code"] == "SUBMISSION_MATERIALS_JSON_INVALID"


def test_release_submission_flags_unknown_manifest_fields() -> None:
    packet = build_release_submission_readiness(
        "/tmp/project",
        readiness_packet=_readiness(),
        submission_materials={**_ready_kwargs(), "screenhots_ready": True},
    )

    assert packet["status"] == "needs_attention"
    assert "SUBMISSION_MATERIALS_MANIFEST_HAS_UNKNOWN_FIELDS" in packet["needs_attention_codes"]
    assert packet["submission_materials"]["ignored_manifest_fields"] == ["screenhots_ready"]
    assert packet["checks"]["submission_materials_manifest"]["ignored_fields"] == ["screenhots_ready"]


def test_release_submission_requires_evidence_files_for_manifest_ready_flags(tmp_path) -> None:
    packet = build_release_submission_readiness(
        str(tmp_path),
        readiness_packet=_readiness(),
        submission_materials={**_ready_kwargs(), "evidence": {"screenshots": ["docs/submission/missing.png"]}},
    )

    assert packet["status"] == "needs_attention"
    assert "SUBMISSION_EVIDENCE_REFERENCES_INCOMPLETE" in packet["needs_attention_codes"]
    evidence_check = packet["checks"]["submission_evidence_references"]
    assert "logo" in evidence_check["missing_keys"]
    assert "docs/submission/missing.png" in evidence_check["missing_files"]


def test_release_submission_rejects_evidence_paths_outside_project(tmp_path) -> None:
    packet = build_release_submission_readiness(
        str(tmp_path),
        readiness_packet=_readiness(),
        submission_materials={
            **_ready_kwargs(),
            "evidence": {
                **_evidence_refs(),
                "security_review": "../private/security-review.md",
            },
        },
    )

    assert packet["status"] == "needs_attention"
    evidence_check = packet["checks"]["submission_evidence_references"]
    assert evidence_check["invalid_refs"] == [
        {
            "key": "security_review",
            "ref": "../private/security-review.md",
            "error_code": "EVIDENCE_PATH_OUTSIDE_PROJECT",
        }
    ]
