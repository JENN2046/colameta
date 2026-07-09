from __future__ import annotations

from runner.full_loop_authority import build_full_loop_authority_status


def test_full_loop_authority_defaults_to_disabled_read_preview_only() -> None:
    packet = build_full_loop_authority_status("/tmp/project")

    assert packet["status"] == "disabled"
    assert packet["full_loop_ready"] is False
    assert packet["effective_authority"] == "read_preview_only"
    assert "enable_full_loop" in packet["missing_controls"]
    assert packet["authority_boundary"]["does_not_start_executor"] is True
    assert "executor_run" in packet["not_authorized_actions"]


def test_full_loop_authority_blocks_without_preview_confirm_mode() -> None:
    packet = build_full_loop_authority_status(
        "/tmp/project",
        enable_full_loop=True,
        confirmation_mode="manual",
        operator_confirmation_ref="receipt-1",
        allow_executor_run=True,
        allow_validation_run=True,
        allow_local_commit=True,
        allow_remote_push=True,
    )

    assert packet["status"] == "blocked"
    assert packet["full_loop_ready"] is False
    assert "confirmation_mode_preview_confirm" in packet["missing_controls"]


def test_full_loop_authority_ready_requires_all_controls() -> None:
    packet = build_full_loop_authority_status(
        "/tmp/project",
        enable_full_loop=True,
        confirmation_mode="preview-confirm",
        operator_confirmation_ref="receipt-1",
        allow_executor_run=True,
        allow_validation_run=True,
        allow_local_commit=True,
        allow_remote_push=True,
    )

    assert packet["status"] == "ready"
    assert packet["full_loop_ready"] is True
    assert packet["effective_authority"] == "controlled_full_loop"
    assert packet["capability_gates"]["executor_run"]["status"] == "ready"
    assert packet["capability_gates"]["remote_push"]["tool"] == "manage_git_remote"
    assert "stable_replacement" in packet["not_authorized_actions"]


def test_stable_replacement_is_not_enabled_by_full_loop_status() -> None:
    packet = build_full_loop_authority_status(
        "/tmp/project",
        enable_full_loop=True,
        confirmation_mode="preview_confirm",
        operator_confirmation_ref="receipt-1",
        allow_executor_run=True,
        allow_validation_run=True,
        allow_local_commit=True,
        allow_remote_push=True,
        allow_stable_replacement=True,
    )

    assert packet["full_loop_ready"] is True
    assert packet["stable_replacement"]["requested"] is True
    assert packet["stable_replacement"]["status"] == "blocked"
