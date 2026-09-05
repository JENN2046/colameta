from __future__ import annotations

import tempfile
import unittest

from runner.executor_result_builder import already_claimed_error, run_once_started_result
from runner.executor_status import polling_guidance_for_profile, status_base_result
from runner.mcp_executor_workflow import MCPExecutorWorkflowManager


class ExecutorPollingGuidanceTests(unittest.TestCase):
    def test_default_profile_keeps_short_web_gpt_polling(self) -> None:
        result = status_base_result(1)

        assert result["polling_profile_id"] == "web_gpt_commander"
        assert result["next_poll_after_seconds"] == 3
        assert result["max_poll_attempts"] == 3
        assert result["max_total_poll_seconds"] == 9
        assert result["polling_guidance"]["policy"] == "non_blocking_polling"

    def test_local_codex_profile_gets_longer_bounded_polling(self) -> None:
        result = status_base_result(4, profile_id="local_codex_commander")

        assert result["polling_profile_id"] == "local_codex_commander"
        assert result["next_poll_after_seconds"] == 5
        assert result["max_poll_attempts"] == 24
        assert result["max_total_poll_seconds"] == 120
        assert result["remaining_poll_attempts"] == 20
        assert result["polling_exhausted"] is False
        assert result["polling_guidance"]["policy"] == "bounded_local_polling"

    def test_profile_specific_exhaustion_uses_profile_attempt_limit(self) -> None:
        web = status_base_result(4, profile_id="web_gpt_commander")
        local = status_base_result(24, profile_id="local_codex_commander")
        local_exhausted = status_base_result(25, profile_id="local_codex_commander")

        assert web["polling_exhausted"] is True
        assert local["polling_exhausted"] is False
        assert local_exhausted["polling_exhausted"] is True

    def test_unknown_profile_falls_back_to_web_gpt_default(self) -> None:
        guidance = polling_guidance_for_profile("unknown_profile")

        assert guidance["profile_id"] == "web_gpt_commander"
        assert guidance["requested_profile_id"] == "unknown_profile"
        assert guidance["fallback_profile_id"] == "web_gpt_commander"
        assert guidance["warning"] == "UNKNOWN_POLLING_PROFILE_USED_DEFAULT"

    def test_manager_status_accepts_profile_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = MCPExecutorWorkflowManager(tmpdir)

            result = manager.handle(
                "status",
                {"profile_id": "local_codex_commander", "poll_attempt": 24},
            )

        assert result["ok"] is True
        assert result["polling_profile_id"] == "local_codex_commander"
        assert result["max_poll_attempts"] == 24
        assert result["polling_exhausted"] is False

    def test_profile_less_status_uses_claimed_profile_for_preview_and_run_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = MCPExecutorWorkflowManager(tmpdir)
            preview_id = "preview_local_profile"
            claim_result = manager._claims.acquire_claim(
                preview_id=preview_id,
                artifact={
                    "artifact_kind": "run_once",
                    "profile_id": "local_codex_commander",
                },
                provider="codex",
                execution_mode="run",
            )
            run_id = claim_result["run_id"]

            by_preview = manager.handle(
                "status",
                {"preview_id": preview_id, "poll_attempt": 4},
            )
            by_run = manager.handle(
                "status",
                {"run_id": run_id, "poll_attempt": 4},
            )

        for result in (by_preview, by_run):
            assert result["polling_profile_id"] == "local_codex_commander"
            assert result["next_poll_after_seconds"] == 5
            assert result["max_poll_attempts"] == 24
            assert result["polling_exhausted"] is False

    def test_explicit_status_profile_overrides_claimed_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = MCPExecutorWorkflowManager(tmpdir)
            preview_id = "preview_explicit_profile"
            manager._claims.acquire_claim(
                preview_id=preview_id,
                artifact={
                    "artifact_kind": "run_once",
                    "profile_id": "local_codex_commander",
                },
                provider="codex",
                execution_mode="run",
            )

            result = manager.handle(
                "status",
                {
                    "preview_id": preview_id,
                    "profile_id": "web_gpt_commander",
                    "poll_attempt": 4,
                },
            )

        assert result["polling_profile_id"] == "web_gpt_commander"
        assert result["next_poll_after_seconds"] == 3
        assert result["max_poll_attempts"] == 3
        assert result["polling_exhausted"] is True

    def test_explicit_run_profile_is_persisted_in_claim_for_later_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = MCPExecutorWorkflowManager(tmpdir)
            for action, artifact_kind in (
                ("run_once", "run_once"),
                ("run_bounded", "run_bounded"),
            ):
                with self.subTest(action=action):
                    claim_result = manager._claim_preview_artifact(
                        action=action,
                        preview_id=f"profileless_preview_{action}",
                        artifact={"artifact_kind": artifact_kind},
                        provider="codex",
                        execution_mode="run",
                        profile_id="local_codex_commander",
                    )

                    status = manager.handle(
                        "status",
                        {"run_id": claim_result["run_id"], "poll_attempt": 4},
                    )

                    assert claim_result["ok"] is True
                    assert status["polling_profile_id"] == "local_codex_commander"
                    assert status["next_poll_after_seconds"] == 5
                    assert status["max_poll_attempts"] == 24
                    assert status["polling_exhausted"] is False

    def test_run_bounded_already_claimed_preserves_polling_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = MCPExecutorWorkflowManager(tmpdir)
            preview_id = "preview_claimed"
            manager._claims.acquire_claim(
                preview_id=preview_id,
                artifact={"artifact_kind": "run_bounded"},
                provider="codex",
                execution_mode="run",
            )

            result = manager.handle(
                "run_bounded",
                {"preview_id": preview_id, "profile_id": "local_codex_commander"},
            )

        assert result["ok"] is False
        assert result["error_code"] == "PREVIEW_ALREADY_CLAIMED"
        assert result["polling_profile_id"] == "local_codex_commander"
        assert result["next_actions"][0]["params"]["profile_id"] == "local_codex_commander"

    def test_run_once_next_action_preserves_polling_profile(self) -> None:
        result = run_once_started_result(
            run_id="exec_run_example",
            preview_id="preview_example",
            preview_claimed_at="2026-07-02T00:00:00+08:00",
            profile_id="local_codex_commander",
        )

        assert result["polling_guidance"]["profile_id"] == "local_codex_commander"
        assert result["next_actions"][0]["params"]["profile_id"] == "local_codex_commander"

    def test_already_claimed_error_preserves_polling_profile(self) -> None:
        result = already_claimed_error(
            action="run_once",
            preview_id="preview_example",
            claim={
                "run_id": "exec_run_example",
                "status": "RUNNING",
                "claimed_at": "2026-07-02T00:00:00+08:00",
            },
            orphan_info={"orphaned": False},
            profile_id="local_codex_commander",
        )

        assert result["polling_profile_id"] == "local_codex_commander"
        assert result["max_poll_attempts"] == 24
        assert result["next_actions"][0]["params"]["profile_id"] == "local_codex_commander"


if __name__ == "__main__":
    unittest.main()
