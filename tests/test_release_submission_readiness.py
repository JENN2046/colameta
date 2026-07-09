from __future__ import annotations

import json

from runner.release_submission_readiness import (
    DEFAULT_SUBMISSION_MATERIALS_REL_PATH,
    build_release_submission_readiness,
    fill_submission_evidence_files,
    init_submission_evidence_scaffold,
    mark_submission_evidence_ready_fields,
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
    progress = packet["submission_evidence_progress"]
    assert progress["status"] == "ready"
    assert progress["complete_count"] == 10
    assert progress["total_count"] == 10
    assert progress["counts"]["ready"] == 10
    assert {row["key"] for row in progress["rows"]} == set(_evidence_refs())


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


def test_submission_evidence_scaffold_creates_manifest_and_placeholders(tmp_path) -> None:
    packet = init_submission_evidence_scaffold(str(tmp_path), app_name="Demo App")

    assert packet["source"] == "submission_evidence_scaffold"
    assert packet["manifest_created"] is True
    assert DEFAULT_SUBMISSION_MATERIALS_REL_PATH in packet["created_files"]
    manifest_path = tmp_path / DEFAULT_SUBMISSION_MATERIALS_REL_PATH
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["app_name"] == "Demo App"
    assert manifest["logo_ready"] is False
    assert manifest["evidence"]["logo"] == "docs/submission/logo.todo.md"
    assert (tmp_path / "docs/submission/logo.todo.md").is_file()


def test_submission_evidence_scaffold_preserves_existing_files(tmp_path) -> None:
    first = init_submission_evidence_scaffold(str(tmp_path))
    logo_path = tmp_path / "docs/submission/logo.todo.md"
    logo_path.write_text("custom\n", encoding="utf-8")

    second = init_submission_evidence_scaffold(str(tmp_path))

    assert first["manifest_created"] is True
    assert second["manifest_created"] is False
    assert "docs/submission/logo.todo.md" in second["existing_files"]
    assert logo_path.read_text(encoding="utf-8") == "custom\n"


def test_release_submission_rejects_placeholder_evidence_when_marked_ready(tmp_path) -> None:
    init_submission_evidence_scaffold(str(tmp_path))
    manifest_path = tmp_path / DEFAULT_SUBMISSION_MATERIALS_REL_PATH
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["logo_ready"] = True
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    packet = build_release_submission_readiness(str(tmp_path), readiness_packet=_readiness())

    assert packet["status"] == "needs_attention"
    evidence_check = packet["checks"]["submission_evidence_references"]
    assert evidence_check["incomplete_keys"] == ["logo"]
    assert "docs/submission/logo.todo.md" in evidence_check["placeholder_files"]
    assert evidence_check["placeholder_files_by_key"] == [{"key": "logo", "ref": "docs/submission/logo.todo.md"}]
    template = evidence_check["fill_entry_templates"][0]
    assert template["key"] == "logo"
    assert template["default_filename"] == "logo.md"
    assert "asset_path" in template["required_sections"]
    assert packet["submission_evidence_entry_templates"][0]["key"] == "logo"
    progress = packet["submission_evidence_progress"]
    logo_row = next(row for row in progress["rows"] if row["key"] == "logo")
    assert logo_row["status"] == "needs_attention"
    assert logo_row["file_states"] == [{"ref": "docs/submission/logo.todo.md", "status": "placeholder"}]
    assert progress["counts"]["needs_attention"] == 1
    assert progress["counts"]["placeholder"] == 9


def test_fill_submission_evidence_files_updates_manifest_refs_without_marking_ready(tmp_path) -> None:
    init_submission_evidence_scaffold(str(tmp_path))

    packet = fill_submission_evidence_files(
        str(tmp_path),
        entries=[
            {
                "key": "logo",
                "filename": "logo-review.md",
                "content": "# Logo\n\nReviewed logo asset: docs/submission/logo.png\n",
            }
        ],
    )

    assert packet["ok"] is True
    assert packet["source"] == "submission_evidence_fill"
    assert packet["created_files"] == ["docs/submission/logo-review.md"]
    assert packet["ready_fields_marked"] == []
    manifest = json.loads((tmp_path / DEFAULT_SUBMISSION_MATERIALS_REL_PATH).read_text(encoding="utf-8"))
    assert manifest["logo_ready"] is False
    assert manifest["evidence"]["logo"] == "docs/submission/logo-review.md"
    assert (tmp_path / "docs/submission/logo-review.md").read_text(encoding="utf-8").startswith("# Logo")


def test_fill_submission_evidence_files_can_mark_reviewed_key_ready(tmp_path) -> None:
    init_submission_evidence_scaffold(str(tmp_path))

    packet = fill_submission_evidence_files(
        str(tmp_path),
        entries=[
            {
                "key": "mcp_tool_info",
                "content": "# MCP Tool Info\n\nTool scopes reviewed.\n",
            }
        ],
        mark_ready=True,
    )

    assert packet["ok"] is True
    assert packet["ready_fields_marked"] == ["mcp_tool_info_ready"]
    manifest = json.loads((tmp_path / DEFAULT_SUBMISSION_MATERIALS_REL_PATH).read_text(encoding="utf-8"))
    assert manifest["mcp_tool_info_ready"] is True
    assert manifest["evidence"]["mcp_tool_info"] == "docs/submission/mcp-tool-info.md"


def test_fill_submission_evidence_files_rejects_unsafe_target_without_partial_write(tmp_path) -> None:
    init_submission_evidence_scaffold(str(tmp_path))
    manifest_path = tmp_path / DEFAULT_SUBMISSION_MATERIALS_REL_PATH
    before = manifest_path.read_text(encoding="utf-8")

    packet = fill_submission_evidence_files(
        str(tmp_path),
        entries=[
            {
                "key": "security_review",
                "filename": "../security-review.md",
                "content": "reviewed\n",
            }
        ],
        mark_ready=True,
    )

    assert packet["ok"] is False
    assert packet["error_code"] == "SUBMISSION_EVIDENCE_INPUT_INVALID"
    assert packet["validation_errors"][0]["error_code"] == "EVIDENCE_PATH_OUTSIDE_PROJECT"
    assert [item["tool"] for item in packet["safe_recovery_actions"]] == [
        "get_release_submission_readiness",
        "get_submission_evidence_fill_preview",
    ]
    assert packet["safe_recovery_actions"][1]["arguments"] == {"selected_keys": ["security_review"]}
    assert packet["safe_recovery_actions"][1]["authority_boundary"]["does_not_write_files"] is True
    assert manifest_path.read_text(encoding="utf-8") == before
    assert not (tmp_path / "security-review.md").exists()


def test_fill_submission_evidence_files_rejects_existing_file_conflict(tmp_path) -> None:
    init_submission_evidence_scaffold(str(tmp_path))
    existing_path = tmp_path / "docs/submission/logo.md"
    existing_path.write_text("existing\n", encoding="utf-8")

    packet = fill_submission_evidence_files(
        str(tmp_path),
        entries=[{"key": "logo", "content": "different\n"}],
    )

    assert packet["ok"] is False
    assert packet["validation_errors"][0]["error_code"] == "SUBMISSION_EVIDENCE_FILE_EXISTS"
    assert packet["safe_recovery_actions"][1]["arguments"] == {"selected_keys": ["logo"]}
    assert existing_path.read_text(encoding="utf-8") == "existing\n"


def test_mark_submission_evidence_ready_fields_marks_existing_reviewed_refs(tmp_path) -> None:
    init_submission_evidence_scaffold(str(tmp_path))
    logo_path = tmp_path / "docs/submission/logo.md"
    logo_path.write_text("# Logo\n\nReviewed.\n", encoding="utf-8")
    manifest_path = tmp_path / DEFAULT_SUBMISSION_MATERIALS_REL_PATH
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["evidence"]["logo"] = "docs/submission/logo.md"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    packet = mark_submission_evidence_ready_fields(
        str(tmp_path),
        keys=["logo"],
        review_confirmation="human_reviewed",
    )

    assert packet["ok"] is True
    assert packet["source"] == "submission_evidence_mark_ready"
    assert packet["changed_files"] == [DEFAULT_SUBMISSION_MATERIALS_REL_PATH]
    assert packet["ready_fields_marked"] == ["logo_ready"]
    assert packet["reviewed_refs_by_key"] == [{"key": "logo", "refs": ["docs/submission/logo.md"]}]
    updated = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert updated["logo_ready"] is True
    assert logo_path.read_text(encoding="utf-8") == "# Logo\n\nReviewed.\n"


def test_mark_submission_evidence_ready_fields_requires_confirmation_without_write(tmp_path) -> None:
    init_submission_evidence_scaffold(str(tmp_path))
    manifest_path = tmp_path / DEFAULT_SUBMISSION_MATERIALS_REL_PATH
    before = manifest_path.read_text(encoding="utf-8")

    packet = mark_submission_evidence_ready_fields(
        str(tmp_path),
        keys=["logo"],
        review_confirmation="",
    )

    assert packet["ok"] is False
    assert packet["error_code"] == "SUBMISSION_EVIDENCE_REVIEW_CONFIRMATION_REQUIRED"
    assert [item["tool"] for item in packet["safe_recovery_actions"]] == [
        "get_release_submission_readiness",
        "get_submission_evidence_fill_preview",
    ]
    assert packet["safe_recovery_actions"][1]["arguments"] == {"selected_keys": ["logo"]}
    assert packet["safe_recovery_actions"][1]["required_scope"] == "mcp:read"
    assert manifest_path.read_text(encoding="utf-8") == before


def test_mark_submission_evidence_ready_fields_rejects_placeholder_refs_without_write(tmp_path) -> None:
    init_submission_evidence_scaffold(str(tmp_path))
    manifest_path = tmp_path / DEFAULT_SUBMISSION_MATERIALS_REL_PATH
    before = manifest_path.read_text(encoding="utf-8")

    packet = mark_submission_evidence_ready_fields(
        str(tmp_path),
        keys=["logo"],
        review_confirmation="human_reviewed",
    )

    assert packet["ok"] is False
    assert packet["error_code"] == "SUBMISSION_EVIDENCE_READY_PROOF_INVALID"
    assert packet["validation_errors"] == [
        {
            "key": "logo",
            "ref": "docs/submission/logo.todo.md",
            "error_code": "SUBMISSION_EVIDENCE_PLACEHOLDER_REF",
        }
    ]
    assert packet["safe_recovery_actions"][0]["authority_boundary"]["does_not_mark_ready_fields"] is True
    assert packet["safe_recovery_actions"][1]["arguments"] == {"selected_keys": ["logo"]}
    assert manifest_path.read_text(encoding="utf-8") == before
