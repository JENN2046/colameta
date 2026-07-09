from __future__ import annotations

import json

from runner.product_console import build_product_console_map
from runner.release_submission_readiness import DEFAULT_SUBMISSION_MATERIALS_REL_PATH


def _readiness(status: str = "ready") -> dict[str, object]:
    return {
        "status": status,
        "ready": status == "ready",
        "primary_blocker": None if status == "ready" else {"check": "remote_https_mcp_preflight"},
        "safe_next_action": {"action": "continue_with_public_beta_workflow"},
        "remote_connector": {
            "connector_smoke": {
                "status": "ready",
                "reason_codes": ["CONNECTOR_SMOKE_READY"],
            }
        },
        "ops_check": {
            "ops_check_ready": status == "ready",
            "connector_smoke_ready": status == "ready",
        },
    }


def _full_loop(status: str = "disabled") -> dict[str, object]:
    return {
        "status": status,
        "full_loop_ready": status == "ready",
        "effective_authority": "controlled_full_loop" if status == "ready" else "read_preview_only",
        "missing_controls": [] if status == "ready" else ["enable_full_loop"],
    }


def _release(status: str = "needs_attention") -> dict[str, object]:
    return {
        "status": status,
        "ready": status == "ready",
        "blocker_codes": [] if status != "blocked" else ["PRODUCT_READINESS_NOT_READY"],
        "needs_attention_codes": [] if status == "ready" else ["SUBMISSION_MATERIALS_MISSING"],
        "safe_next_action": {"action": "complete_submission_materials"},
    }


def _release_with_materials(
    *,
    status: str = "needs_attention",
    source: str = "default_manifest_file",
    evidence_status: str = "needs_attention",
) -> dict[str, object]:
    entry_templates = [
        {
            "key": "logo",
            "ready_field": "logo_ready",
            "default_filename": "logo.md",
            "content_prompt": "Record final logo evidence.",
        }
    ] if evidence_status == "needs_attention" else []
    return {
        "status": status,
        "ready": status == "ready",
        "blocker_codes": [],
        "needs_attention_codes": [] if status == "ready" else ["SUBMISSION_EVIDENCE_REFERENCES_INCOMPLETE"],
        "submission_materials": {
            "source": source,
            "effective_fields": ["app_name"],
            "evidence_keys": ["logo"],
        },
        "checks": {
            "submission_materials_manifest": {"status": "ready"},
            "submission_evidence_references": {
                "status": evidence_status,
                "incomplete_keys": ["logo"] if evidence_status == "needs_attention" else [],
                "missing_keys": ["logo"] if evidence_status == "needs_attention" else [],
                "missing_files": [],
                "missing_files_by_key": [],
                "placeholder_files": ["docs/submission/logo.todo.md"] if evidence_status == "needs_attention" else [],
                "placeholder_files_by_key": [
                    {"key": "logo", "ref": "docs/submission/logo.todo.md"}
                ] if evidence_status == "needs_attention" else [],
                "fill_entry_templates": entry_templates,
            },
        },
        "submission_evidence_entry_templates": entry_templates,
        "safe_next_action": {"action": "complete_submission_materials"},
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


def test_console_map_defaults_to_read_preview_product_surface() -> None:
    packet = build_product_console_map(
        "/tmp/project",
        project_name="demo-project",
        readiness_packet=_readiness(),
        full_loop_authority=_full_loop(),
        release_submission_readiness=_release(),
    )

    assert packet["source"] == "product_console_map"
    assert packet["read_only"] is True
    assert packet["side_effects"] is False
    assert packet["status"] == "ready_read_preview"
    assert packet["default_mode"] == "public_beta_read_preview"
    assert packet["recommended_first_actions"][0]["tool"] == "init_submission_evidence"
    assert {"tool": "get_product_readiness_status", "arguments": {"project_name": "demo-project"}} in packet[
        "recommended_first_actions"
    ]
    entries = {entry["entry_id"]: entry for entry in packet["entries"]}
    assert entries["product_readiness"]["arguments"] == {"project_name": "demo-project"}
    assert entries["executor_workflow"]["status"] == "blocked"
    assert entries["git_remote_push"]["required_scope"] == "mcp:commit"
    assert entries["release_submission_readiness"]["tool"] == "get_release_submission_readiness"
    assert entries["release_submission_readiness"]["status"] == "needs_attention"
    assert packet["authority_boundary"]["does_not_push"] is True


def test_console_map_recommends_submission_scaffold_when_manifest_missing() -> None:
    packet = build_product_console_map(
        "/tmp/project",
        project_name="demo-project",
        readiness_packet=_readiness(),
        full_loop_authority=_full_loop(),
        release_submission_readiness=_release_with_materials(source="parameters_only"),
    )

    first = packet["recommended_first_actions"][0]
    assert first["tool"] == "init_submission_evidence"
    assert first["arguments"] == {"project_name": "demo-project"}


def test_console_map_recommends_filling_submission_evidence_for_placeholders() -> None:
    packet = build_product_console_map(
        "/tmp/project",
        project_name="demo-project",
        readiness_packet=_readiness(),
        full_loop_authority=_full_loop(),
        release_submission_readiness=_release_with_materials(),
    )

    first = packet["recommended_first_actions"][0]
    assert first["tool"] == "fill_submission_evidence_files"
    assert first["arguments"] == {"project_name": "demo-project", "entries": []}
    assert first["evidence_context"]["placeholder_files"] == ["docs/submission/logo.todo.md"]
    assert first["evidence_context"]["incomplete_keys"] == ["logo"]
    assert first["evidence_context"]["entry_templates"][0]["default_filename"] == "logo.md"
    assert packet["release_submission_snapshot"]["submission_materials"]["evidence_entry_templates"][0]["key"] == "logo"


def test_console_map_does_not_recommend_release_work_when_submission_ready() -> None:
    packet = build_product_console_map(
        "/tmp/project",
        readiness_packet=_readiness(),
        full_loop_authority=_full_loop(),
        release_submission_readiness=_release_with_materials(status="ready", evidence_status="ready"),
    )

    assert packet["recommended_first_actions"][0]["tool"] == "get_product_readiness_status"


def test_console_map_marks_full_loop_entries_preview_required_when_controls_ready() -> None:
    packet = build_product_console_map(
        "/tmp/project",
        readiness_packet=_readiness(),
        full_loop_authority=_full_loop("ready"),
        release_submission_readiness=_release(),
    )

    entries = {entry["entry_id"]: entry for entry in packet["entries"]}
    assert packet["status"] == "full_loop_ready"
    assert entries["executor_workflow"]["status"] == "preview_required"
    assert entries["validation_run"]["status"] == "preview_required"
    assert entries["git_commit"]["requires_preview_confirm"] is True


def test_console_map_blocks_on_product_readiness_blocker() -> None:
    packet = build_product_console_map(
        "/tmp/project",
        readiness_packet=_readiness("blocked"),
        full_loop_authority=_full_loop("ready"),
        release_submission_readiness=_release("blocked"),
    )

    assert packet["status"] == "blocked"
    assert packet["recommended_first_actions"][0]["tool"] == "init_submission_evidence"
    assert {"tool": "get_product_readiness_status", "arguments": {}} in packet["recommended_first_actions"]
    assert packet["readiness_snapshot"]["primary_blocker"]["check"] == "remote_https_mcp_preflight"
    assert packet["release_submission_snapshot"]["status"] == "blocked"


def test_console_map_auto_loads_default_release_submission_manifest(tmp_path) -> None:
    _write_evidence_files(tmp_path)
    manifest_path = tmp_path / DEFAULT_SUBMISSION_MATERIALS_REL_PATH
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "chatgpt_app_submission_materials.v1",
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
                "evidence": _evidence_refs(),
            }
        ),
        encoding="utf-8",
    )

    packet = build_product_console_map(
        str(tmp_path),
        readiness_packet=_readiness(),
        full_loop_authority=_full_loop(),
    )

    assert packet["release_submission_snapshot"]["status"] == "ready"
    assert packet["release_submission_snapshot"]["submission_materials"]["source"] == "default_manifest_file"
    assert "app_name" in packet["release_submission_snapshot"]["submission_materials"]["effective_fields"]
    assert packet["release_submission_snapshot"]["submission_materials"]["evidence_status"] == "ready"
    assert "screenshots" in packet["release_submission_snapshot"]["submission_materials"]["evidence_keys"]
