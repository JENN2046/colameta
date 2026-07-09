from __future__ import annotations

import json
from datetime import datetime, timezone

from runner.product_console import (
    build_product_console_map,
    build_submission_evidence_fill_preview,
    load_product_console_action_results,
    record_product_console_action_result,
)
from runner.release_submission_readiness import DEFAULT_SUBMISSION_MATERIALS_REL_PATH


def _readiness(status: str = "ready", safe_next_action: dict[str, object] | None = None) -> dict[str, object]:
    return {
        "status": status,
        "ready": status == "ready",
        "primary_blocker": None if status == "ready" else {"check": "remote_https_mcp_preflight"},
        "safe_next_action": safe_next_action or {"action": "continue_with_public_beta_workflow", "tool": "render_commander_app"},
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
    ready = evidence_status == "ready"
    filled_not_marked_ready = evidence_status == "filled_not_marked_ready"
    evidence_progress = {
        "source": "submission_evidence_progress",
        "schema_version": "submission_evidence_progress.v1",
        "status": evidence_status,
        "complete_count": 1 if ready else 0,
        "total_count": 1,
        "counts": {
            "ready": 1 if ready else 0,
            "needs_attention": 1 if evidence_status == "needs_attention" else 0,
            "filled_not_marked_ready": 1 if filled_not_marked_ready else 0,
            "placeholder": 0,
            "not_started": 0,
        },
        "rows": [
            {
                "key": "logo",
                "ready_field": "logo_ready",
                "ready": ready,
                "status": evidence_status,
                "refs": ["docs/submission/logo.todo.md"] if evidence_status == "needs_attention" else ["docs/submission/logo.md"],
                "file_states": [{"ref": "docs/submission/logo.todo.md", "status": "placeholder"}]
                if evidence_status == "needs_attention"
                else [{"ref": "docs/submission/logo.md", "status": "present"}],
            }
        ],
    }
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
        "submission_evidence_progress": evidence_progress,
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


def _action_by_tool(packet: dict[str, object], tool: str) -> dict[str, object]:
    for action in packet["recommended_first_actions"]:
        if isinstance(action, dict) and action.get("tool") == tool:
            return action
    raise AssertionError(f"missing recommended action for tool {tool}")


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
    init_action = packet["recommended_first_actions"][0]
    assert init_action["tool"] == "init_submission_evidence"
    assert init_action["action_id"] == "init_submission_evidence"
    assert init_action["mode"] == "commit"
    assert init_action["required_scope"] == "mcp:commit"
    assert init_action["requires_explicit_confirmation"] is True
    assert init_action["authority_boundary"]["does_not_execute_now"] is True
    assert init_action["result_contract"]["expected_result_kind"] == "commit_scoped_result"
    assert (
        init_action["result_contract"]["last_action_result_shape"]["status"]
        == "not_recorded|pending|updated|requested|blocked|failed|stale"
    )
    assert init_action["result_contract"]["refresh_after"][0]["tool"] == "get_release_submission_readiness"
    assert init_action["last_action_result"]["status"] == "not_recorded"
    assert init_action["action_fingerprint"]
    commander_action = _action_by_tool(packet, "render_commander_app")
    assert commander_action["arguments"] == {"project_name": "demo-project"}
    assert commander_action["source"] == "readiness_safe_next_action"
    assert commander_action["mode"] == "read"
    assert commander_action["required_scope"] == "mcp:read"
    assert commander_action["side_effects"] is False
    assert commander_action["action"] == "continue_with_public_beta_workflow"
    assert commander_action["result_contract"]["expected_result_kind"] == "read_packet"
    assert commander_action["result_contract"]["refresh_after"][0]["tool"] == "get_product_console_map"
    assert commander_action["action_key"] == "continue_with_public_beta_workflow|render_commander_app|read"
    entries = {entry["entry_id"]: entry for entry in packet["entries"]}
    assert entries["product_readiness"]["arguments"] == {"project_name": "demo-project"}
    assert entries["executor_workflow"]["status"] == "blocked"
    assert entries["git_remote_push"]["required_scope"] == "mcp:commit"
    assert entries["release_submission_readiness"]["tool"] == "get_release_submission_readiness"
    assert entries["release_submission_readiness"]["status"] == "needs_attention"
    evidence_bundle = packet["release_submission_evidence_bundle"]
    assert evidence_bundle["source"] == "release_submission_evidence_bundle"
    assert evidence_bundle["read_only"] is True
    assert evidence_bundle["fill_plan"]["status"] == "manifest_missing"
    assert evidence_bundle["fill_plan"]["next_tool"] == "init_submission_evidence"
    completion = packet["completion_surface"]
    assert completion["source"] == "product_console_completion_surface"
    assert completion["read_only"] is True
    assert completion["side_effects"] is False
    assert completion["status"] == "needs_attention"
    assert completion["ready"] is False
    assert completion["components"]["product_readiness"]["ready"] is True
    assert completion["components"]["release_submission"]["ready"] is False
    assert completion["components"]["submission_evidence"]["status"] == "manifest_missing"
    assert completion["components"]["submission_evidence_activity"]["status"] == "not_recorded"
    assert completion["needs_attention_codes"] == [
        "RELEASE_SUBMISSION_NOT_READY",
        "SUBMISSION_EVIDENCE_NOT_READY",
        "SUBMISSION_EVIDENCE_ACTIVITY_NOT_RECORDED",
    ]
    assert completion["safe_next_action"]["tool"] == "init_submission_evidence"
    groups = {item["group_id"]: item for item in completion["action_groups"]}
    assert list(groups) == ["release_submission", "submission_evidence", "submission_evidence_activity"]
    assert groups["release_submission"]["status"] == "needs_attention"
    assert groups["release_submission"]["primary_action"]["tool"] == "init_submission_evidence"
    assert groups["release_submission"]["action_refs"][0]["tool"] == "init_submission_evidence"
    assert groups["submission_evidence"]["primary_action"]["tool"] == "init_submission_evidence"
    assert groups["submission_evidence_activity"]["primary_action"]["tool"] == "get_product_console_map"
    assert "Record the latest submission evidence activity" in groups["submission_evidence_activity"]["empty_state"]
    assert completion["authority_boundary"]["does_not_execute_actions"] is True
    assert packet["authority_boundary"]["does_not_push"] is True


def test_console_map_attaches_recorded_action_result(tmp_path) -> None:
    initial_packet = build_product_console_map(
        str(tmp_path),
        project_name="demo-project",
        readiness_packet=_readiness(),
        full_loop_authority=_full_loop(),
        release_submission_readiness=_release_with_materials(status="ready", evidence_status="ready"),
    )
    initial_action = _action_by_tool(initial_packet, "render_commander_app")

    result = record_product_console_action_result(
        str(tmp_path),
        action_id="continue_with_public_beta_workflow",
        tool="render_commander_app",
        mode="read",
        status="updated",
        message="rendered with token=secret-value",
        project_name="demo-project",
        result_ok=True,
        action_fingerprint=initial_action["action_fingerprint"],
        now=datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc),
    )

    assert result["status"] == "recorded"
    assert result["recorded_result"]["result_ok"] is True
    assert result["recorded_result"]["action_fingerprint"] == initial_action["action_fingerprint"]
    assert "secret-value" not in result["recorded_result"]["message"]

    loaded = load_product_console_action_results(str(tmp_path))
    assert loaded["results"][0]["status"] == "updated"
    assert loaded["results"][0]["action_fingerprint"] == initial_action["action_fingerprint"]
    assert "secret-value" not in loaded["results"][0]["message"]

    packet = build_product_console_map(
        str(tmp_path),
        project_name="demo-project",
        readiness_packet=_readiness(),
        full_loop_authority=_full_loop(),
        release_submission_readiness=_release_with_materials(status="ready", evidence_status="ready"),
    )

    commander_action = _action_by_tool(packet, "render_commander_app")
    assert packet["action_result_state"]["available"] is True
    assert packet["action_result_state"]["stored_result_count"] == 1
    assert packet["action_result_state"]["stale_result_count"] == 0
    assert packet["action_result_state"]["pending_refresh_count"] == 1
    assert packet["action_result_state"]["pending_refreshes"][0]["tool"] == "get_product_console_map"
    assert packet["action_result_state"]["pending_refreshes"][0]["arguments"] == {"project_name": "demo-project"}
    assert commander_action["last_action_result"]["status"] == "updated"
    assert commander_action["last_action_result"]["result_ok"] is True
    assert commander_action["last_action_result"]["fingerprint_verified"] is True
    assert commander_action["last_action_result"]["refresh_recommended"] is True
    assert commander_action["next_refresh_actions"][0]["tool"] == "get_product_console_map"
    assert commander_action["next_refresh_actions"][0]["source_action_key"] == commander_action["action_key"]


def test_console_map_marks_recorded_action_result_stale_when_action_arguments_change(tmp_path) -> None:
    initial_packet = build_product_console_map(
        str(tmp_path),
        project_name="demo-project",
        readiness_packet=_readiness(),
        full_loop_authority=_full_loop(),
        release_submission_readiness=_release_with_materials(status="ready", evidence_status="ready"),
    )
    initial_action = _action_by_tool(initial_packet, "render_commander_app")
    record_product_console_action_result(
        str(tmp_path),
        action_id=initial_action["action_id"],
        tool=initial_action["tool"],
        mode=initial_action["mode"],
        status="updated",
        message="rendered commander",
        project_name="demo-project",
        result_ok=True,
        action_fingerprint=initial_action["action_fingerprint"],
    )

    packet = build_product_console_map(
        str(tmp_path),
        project_name="demo-project",
        readiness_packet=_readiness(
            safe_next_action={
                "action": "continue_with_public_beta_workflow",
                "tool": "render_commander_app",
                "arguments": {"profile_id": "reviewer_agent"},
            }
        ),
        full_loop_authority=_full_loop(),
        release_submission_readiness=_release_with_materials(status="ready", evidence_status="ready"),
    )

    commander_action = _action_by_tool(packet, "render_commander_app")
    assert commander_action["action_key"] == initial_action["action_key"]
    assert commander_action["action_fingerprint"] != initial_action["action_fingerprint"]
    assert packet["action_result_state"]["stale_result_count"] == 1
    assert packet["action_result_state"]["pending_refresh_count"] == 0
    assert packet["action_result_state"]["pending_refreshes"] == []
    assert commander_action["last_action_result"]["status"] == "stale"
    assert commander_action["last_action_result"]["previous_status"] == "updated"
    assert commander_action["last_action_result"]["stale_reason"] == "action_fingerprint_changed"
    assert commander_action["last_action_result"]["refresh_recommended"] is False
    assert commander_action["next_refresh_actions"] == []


def test_console_map_does_not_offer_refresh_after_failed_action_result(tmp_path) -> None:
    record_product_console_action_result(
        str(tmp_path),
        action_id="continue_with_public_beta_workflow",
        tool="render_commander_app",
        mode="read",
        status="failed",
        message="direct call failed",
        project_name="demo-project",
        result_ok=False,
    )

    packet = build_product_console_map(
        str(tmp_path),
        project_name="demo-project",
        readiness_packet=_readiness(),
        full_loop_authority=_full_loop(),
        release_submission_readiness=_release_with_materials(status="ready", evidence_status="ready"),
    )

    commander_action = _action_by_tool(packet, "render_commander_app")
    assert packet["action_result_state"]["pending_refresh_count"] == 0
    assert packet["action_result_state"]["pending_refreshes"] == []
    assert commander_action["last_action_result"]["status"] == "failed"
    assert commander_action["next_refresh_actions"] == []


def test_console_map_surfaces_recorded_submission_evidence_activity(tmp_path) -> None:
    result = record_product_console_action_result(
        str(tmp_path),
        action_id="submission_evidence_activity",
        tool="submission_evidence_activity_summary",
        mode="read",
        status="updated",
        message="Submission evidence activity | token=secret-value | recovery refreshed",
        project_name="demo-project",
        result_ok=True,
        now=datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc),
    )

    assert result["status"] == "recorded"

    packet = build_product_console_map(
        str(tmp_path),
        project_name="demo-project",
        readiness_packet=_readiness(),
        full_loop_authority=_full_loop(),
        release_submission_readiness=_release_with_materials(status="ready", evidence_status="ready"),
    )

    activity = packet["action_result_state"]["submission_evidence_activity"]
    assert activity["available"] is True
    assert activity["action_id"] == "submission_evidence_activity"
    assert activity["tool"] == "submission_evidence_activity_summary"
    assert activity["mode"] == "read"
    assert activity["status"] == "updated"
    assert activity["result_ok"] is True
    assert activity["project_name"] == "demo-project"
    assert activity["observed_at"] == "2026-01-02T03:04:05Z"
    assert "secret-value" not in activity["message"]
    assert activity["read_only_summary"] is True
    assert activity["authority_boundary"]["does_not_write_runtime_state"] is True


def test_console_map_reports_missing_submission_evidence_activity_result(tmp_path) -> None:
    packet = build_product_console_map(
        str(tmp_path),
        project_name="demo-project",
        readiness_packet=_readiness(),
        full_loop_authority=_full_loop(),
        release_submission_readiness=_release_with_materials(status="ready", evidence_status="ready"),
    )

    activity = packet["action_result_state"]["submission_evidence_activity"]
    assert activity == {
        "available": False,
        "status": "not_recorded",
        "message": "No submission evidence activity result recorded yet.",
        "read_only_summary": True,
    }


def test_console_map_completion_surface_ready_when_closeout_evidence_is_current(tmp_path) -> None:
    record_product_console_action_result(
        str(tmp_path),
        action_id="submission_evidence_activity",
        tool="submission_evidence_activity_summary",
        mode="read",
        status="updated",
        message="Submission evidence activity | closeout refreshed",
        project_name="demo-project",
        result_ok=True,
        now=datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc),
    )

    packet = build_product_console_map(
        str(tmp_path),
        project_name="demo-project",
        readiness_packet=_readiness(),
        full_loop_authority=_full_loop(),
        release_submission_readiness=_release_with_materials(status="ready", evidence_status="ready"),
    )

    completion = packet["completion_surface"]
    assert completion["status"] == "ready"
    assert completion["ready"] is True
    assert completion["gap_count"] == 0
    assert completion["gaps"] == []
    assert completion["blocker_codes"] == []
    assert completion["needs_attention_codes"] == []
    assert completion["components"]["product_readiness"]["ready"] is True
    assert completion["components"]["release_submission"]["ready"] is True
    assert completion["components"]["submission_evidence"]["ready"] is True
    assert completion["components"]["submission_evidence_activity"]["ready"] is True
    assert completion["components"]["action_refresh"]["ready"] is True
    assert completion["safe_next_action"]["tool"] == "render_commander_app"
    assert completion["safe_next_action"]["authority"] == "read_only"
    ready_group = completion["action_groups"][0]
    assert ready_group["group_id"] == "closeout_ready"
    assert ready_group["status"] == "ready"
    assert ready_group["gap_codes"] == []
    assert ready_group["primary_action"]["tool"] == "render_commander_app"
    assert [item["tool"] for item in ready_group["action_refs"]] == [
        "render_commander_app",
        "get_agent_operator_flow_packet",
    ]
    assert ready_group["empty_state"] == "Closeout is ready; continue through the read-only Commander flow."


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
    assert first["action_id"] == "fill_submission_evidence_files"
    assert first["label"] == "Fill Submission Evidence"
    assert first["mode"] == "commit"
    assert first["required_scope"] == "mcp:commit"
    assert first["requires_preview_confirm"] is True
    assert first["requires_explicit_confirmation"] is True
    assert first["side_effects"] is True
    assert first["arguments"] == {"project_name": "demo-project", "entries": []}
    assert first["authority_boundary"]["side_effects_if_invoked"] is True
    assert first["authority_boundary"]["does_not_submit_app_for_review"] is True
    assert first["result_contract"]["expected_result_kind"] == "commit_scoped_result"
    assert [item["tool"] for item in first["result_contract"]["refresh_after"]] == [
        "get_release_submission_readiness",
        "get_product_console_map",
    ]
    assert first["evidence_context"]["placeholder_files"] == ["docs/submission/logo.todo.md"]
    assert first["evidence_context"]["incomplete_keys"] == ["logo"]
    assert first["evidence_context"]["entry_templates"][0]["default_filename"] == "logo.md"
    assert packet["release_submission_snapshot"]["submission_materials"]["evidence_entry_templates"][0]["key"] == "logo"
    progress = packet["release_submission_snapshot"]["submission_materials"]["evidence_progress"]
    assert progress["rows"][0]["key"] == "logo"
    assert progress["counts"]["needs_attention"] == 1
    evidence_bundle = packet["release_submission_evidence_bundle"]
    assert evidence_bundle["progress_summary"]["counts"]["needs_attention"] == 1
    assert evidence_bundle["gap_summary"]["placeholder_files"] == ["docs/submission/logo.todo.md"]
    assert evidence_bundle["fill_plan"]["status"] == "evidence_needs_fill"
    assert evidence_bundle["fill_plan"]["next_tool"] == "fill_submission_evidence_files"
    assert evidence_bundle["fill_plan"]["human_review_required"] is True
    draft_entry = evidence_bundle["fill_plan"]["draft_entries"][0]
    assert draft_entry["key"] == "logo"
    assert draft_entry["copyable_entry_shape"] == {
        "key": "logo",
        "filename": "logo.md",
        "content": "<operator-confirmed evidence text>",
    }
    assert evidence_bundle["authority_boundary"]["does_not_write_files"] is True
    assert evidence_bundle["authority_boundary"]["does_not_submit_app_for_review"] is True


def test_console_map_does_not_recommend_release_work_when_submission_ready() -> None:
    packet = build_product_console_map(
        "/tmp/project",
        readiness_packet=_readiness(),
        full_loop_authority=_full_loop(),
        release_submission_readiness=_release_with_materials(status="ready", evidence_status="ready"),
    )

    assert packet["recommended_first_actions"][0]["tool"] == "render_commander_app"
    assert packet["release_submission_evidence_bundle"]["fill_plan"]["status"] == "ready"
    assert packet["release_submission_evidence_bundle"]["fill_plan"]["human_review_required"] is False


def test_console_map_recommends_mark_ready_when_evidence_is_filled() -> None:
    packet = build_product_console_map(
        "/tmp/project",
        project_name="demo-project",
        readiness_packet=_readiness(),
        full_loop_authority=_full_loop(),
        release_submission_readiness=_release_with_materials(evidence_status="filled_not_marked_ready"),
    )

    first = packet["recommended_first_actions"][0]
    assert first["tool"] == "mark_submission_evidence_ready_fields"
    assert first["action_id"] == "mark_submission_evidence_ready_fields"
    assert first["mode"] == "commit"
    assert first["required_scope"] == "mcp:commit"
    assert first["requires_explicit_confirmation"] is True
    assert first["result_contract"]["refresh_after"][1]["tool"] == "get_product_console_map"
    assert first["arguments"] == {
        "project_name": "demo-project",
        "keys": ["logo"],
        "review_confirmation": "human_reviewed",
    }
    assert first["evidence_context"]["ready_fields"] == ["logo_ready"]
    evidence_bundle = packet["release_submission_evidence_bundle"]
    assert evidence_bundle["fill_plan"]["status"] == "evidence_ready_for_review"
    assert evidence_bundle["fill_plan"]["next_tool"] == "mark_submission_evidence_ready_fields"
    assert evidence_bundle["fill_plan"]["review_entries"][0]["refs"] == ["docs/submission/logo.md"]


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
        readiness_packet=_readiness(
            "blocked",
            safe_next_action={
                "action": "follow_runbook",
                "runbook": "docs/dns-proxy-tunnel-runbook.zh-CN.md",
                "why": "The primary blocker includes a bounded operator runbook.",
            },
        ),
        full_loop_authority=_full_loop("ready"),
        release_submission_readiness=_release("blocked"),
    )

    assert packet["status"] == "blocked"
    first = packet["recommended_first_actions"][0]
    assert first["action"] == "follow_runbook"
    assert first["runbook"] == "docs/dns-proxy-tunnel-runbook.zh-CN.md"
    assert first["source"] == "readiness_safe_next_action"
    assert first["action_id"] == "follow_runbook"
    assert first["label"] == "Follow Runbook"
    assert first["mode"] == "read"
    assert first["required_scope"] == "mcp:read"
    assert first["requires_explicit_confirmation"] is False
    assert packet["recommended_first_actions"][1]["tool"] == "init_submission_evidence"
    full_loop_action = _action_by_tool(packet, "get_full_loop_authority_status")
    assert full_loop_action["arguments"] == {}
    assert full_loop_action["action_id"] == "full_loop_authority"
    assert packet["readiness_snapshot"]["primary_blocker"]["check"] == "remote_https_mcp_preflight"
    assert packet["release_submission_snapshot"]["status"] == "blocked"


def test_console_map_surfaces_stable_cadence_as_first_action_for_stable_blocker() -> None:
    readiness = _readiness(
        "blocked",
        safe_next_action={
            "action": "inspect_stable_replacement_cadence",
            "tool": "get_stable_replacement_cadence",
            "arguments": {},
            "why": "Inspect the read-only cadence packet before deciding whether stable replacement should be requested.",
        },
    )
    readiness["primary_blocker"] = {"check": "stable_runtime"}

    packet = build_product_console_map(
        "/tmp/project",
        project_name="demo-project",
        readiness_packet=readiness,
        full_loop_authority=_full_loop("ready"),
        release_submission_readiness=_release("blocked"),
    )

    first = packet["recommended_first_actions"][0]
    assert first["tool"] == "get_stable_replacement_cadence"
    assert first["arguments"] == {"project_name": "demo-project"}
    assert first["required_scope"] == "mcp:read"
    assert first["mode"] == "read"
    assert first["requires_explicit_confirmation"] is False
    assert first["side_effects"] is False
    assert first["authority_boundary"]["does_not_execute_now"] is True
    assert first["result_contract"]["expected_result_kind"] == "read_packet"
    assert first["result_contract"]["failure_summary_source"] == "transport error, tool error, or result.error.message"
    assert first["source"] == "readiness_safe_next_action"
    assert packet["recommended_first_actions"][1]["tool"] == "init_submission_evidence"


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


def test_submission_evidence_fill_preview_packages_bundle_draft_entries() -> None:
    packet = build_submission_evidence_fill_preview(
        "/tmp/project",
        project_name="demo-project",
        release_submission_readiness=_release_with_materials(),
    )

    assert packet["source"] == "submission_evidence_fill_preview"
    assert packet["read_only"] is True
    assert packet["side_effects"] is False
    assert packet["status"] == "preview_ready"
    assert packet["fill_plan_status"] == "evidence_needs_fill"
    assert packet["copyable_tool_call"]["tool"] == "fill_submission_evidence_files"
    assert packet["copyable_tool_call"]["required_scope"] == "mcp:commit"
    assert [item["tool"] for item in packet["copyable_tool_call"]["result_contract"]["refresh_after"]] == [
        "get_release_submission_readiness",
        "get_product_console_map",
    ]
    assert packet["copyable_tool_call"]["arguments"] == {
        "project_name": "demo-project",
        "entries": [
            {
                "key": "logo",
                "filename": "logo.md",
                "content": "<operator-confirmed evidence text>",
            }
        ],
        "mark_ready": False,
    }
    assert packet["authority_boundary"]["does_not_write_files"] is True
    assert packet["authority_boundary"]["does_not_mark_ready_fields"] is True


def test_submission_evidence_fill_preview_filters_selected_keys() -> None:
    packet = build_submission_evidence_fill_preview(
        "/tmp/project",
        project_name="demo-project",
        selected_keys=["mcp_tool_info"],
        release_submission_readiness=_release_with_materials(),
    )

    assert packet["status"] == "selected_keys_not_available"
    assert packet["selected_keys"] == ["mcp_tool_info"]
    assert packet["ignored_selected_keys"] == ["mcp_tool_info"]
    assert packet["copyable_tool_call"]["arguments"]["entries"] == []


def test_submission_evidence_fill_preview_reports_manifest_missing() -> None:
    packet = build_submission_evidence_fill_preview(
        "/tmp/project",
        project_name="demo-project",
        release_submission_readiness=_release_with_materials(source="parameters_only"),
    )

    assert packet["status"] == "manifest_missing"
    assert packet["fill_plan_status"] == "manifest_missing"
    assert packet["copyable_tool_call"]["arguments"]["entries"] == []
    assert packet["evidence_bundle"]["fill_plan"]["next_tool"] == "init_submission_evidence"


def test_submission_evidence_fill_preview_noops_when_ready() -> None:
    packet = build_submission_evidence_fill_preview(
        "/tmp/project",
        release_submission_readiness=_release_with_materials(status="ready", evidence_status="ready"),
    )

    assert packet["status"] == "no_fill_needed"
    assert packet["copyable_tool_call"]["arguments"] == {"entries": [], "mark_ready": False}
    assert packet["operator_instructions"][0].startswith("Review every entry")


def test_submission_evidence_fill_preview_returns_mark_ready_call_when_filled() -> None:
    packet = build_submission_evidence_fill_preview(
        "/tmp/project",
        project_name="demo-project",
        release_submission_readiness=_release_with_materials(evidence_status="filled_not_marked_ready"),
    )

    assert packet["status"] == "review_ready"
    assert packet["summary"].startswith("Prepared a read-only ready-field marking payload")
    assert packet["copyable_tool_call"]["tool"] == "mark_submission_evidence_ready_fields"
    assert [item["tool"] for item in packet["copyable_tool_call"]["result_contract"]["refresh_after"]] == [
        "get_release_submission_readiness",
        "get_product_console_map",
    ]
    assert packet["copyable_tool_call"]["arguments"] == {
        "project_name": "demo-project",
        "keys": ["logo"],
        "review_confirmation": "human_reviewed",
    }
    assert packet["operator_instructions"][0].startswith("Review every referenced evidence file")


def test_submission_evidence_fill_preview_filters_mark_ready_selected_keys() -> None:
    release = _release_with_materials(evidence_status="filled_not_marked_ready")
    progress = release["submission_evidence_progress"]
    progress["total_count"] = 2
    progress["counts"]["filled_not_marked_ready"] = 2
    progress["rows"].append(
        {
            "key": "screenshots",
            "ready_field": "screenshots_ready",
            "ready": False,
            "status": "filled_not_marked_ready",
            "refs": ["docs/submission/screenshot-1.md"],
            "file_states": [{"ref": "docs/submission/screenshot-1.md", "status": "present"}],
        }
    )

    packet = build_submission_evidence_fill_preview(
        "/tmp/project",
        project_name="demo-project",
        selected_keys=["logo"],
        release_submission_readiness=release,
    )

    assert packet["status"] == "review_ready"
    assert packet["selected_keys"] == ["logo"]
    assert packet["ignored_selected_keys"] == []
    assert packet["review_entry_count"] == 1
    assert packet["copyable_tool_call"]["tool"] == "mark_submission_evidence_ready_fields"
    assert packet["copyable_tool_call"]["arguments"] == {
        "project_name": "demo-project",
        "keys": ["logo"],
        "review_confirmation": "human_reviewed",
    }


def test_submission_evidence_fill_preview_reports_unavailable_selected_review_key() -> None:
    packet = build_submission_evidence_fill_preview(
        "/tmp/project",
        project_name="demo-project",
        selected_keys=["mcp_tool_info"],
        release_submission_readiness=_release_with_materials(evidence_status="filled_not_marked_ready"),
    )

    assert packet["status"] == "selected_keys_not_available"
    assert packet["selected_keys"] == ["mcp_tool_info"]
    assert packet["ignored_selected_keys"] == ["mcp_tool_info"]
    assert packet["copyable_tool_call"]["arguments"] == {
        "project_name": "demo-project",
        "entries": [],
        "mark_ready": False,
    }
