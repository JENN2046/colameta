from __future__ import annotations

from runner.release_submission_readiness import build_release_submission_readiness


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
