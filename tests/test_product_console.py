from __future__ import annotations

from runner.product_console import build_product_console_map


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
    assert packet["recommended_first_actions"][0]["tool"] == "get_product_readiness_status"
    entries = {entry["entry_id"]: entry for entry in packet["entries"]}
    assert entries["product_readiness"]["arguments"] == {"project_name": "demo-project"}
    assert entries["executor_workflow"]["status"] == "blocked"
    assert entries["git_remote_push"]["required_scope"] == "mcp:commit"
    assert entries["release_submission_readiness"]["tool"] == "get_release_submission_readiness"
    assert entries["release_submission_readiness"]["status"] == "needs_attention"
    assert packet["authority_boundary"]["does_not_push"] is True


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
    assert packet["recommended_first_actions"][0]["tool"] == "get_product_readiness_status"
    assert packet["readiness_snapshot"]["primary_blocker"]["check"] == "remote_https_mcp_preflight"
    assert packet["release_submission_snapshot"]["status"] == "blocked"
