from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any

from runner.executor_session import classify_executor_session_head_mismatch
from runner.web_console import WebConsoleServer
from runner.web_console_presenter import build_executor_session_display


HEAD_A = "a" * 40
HEAD_B = "b" * 40


def session_status(*, session_head: str = HEAD_A, current_head: str = HEAD_B) -> dict[str, Any]:
    return {
        "ok": True,
        "active": True,
        "record": {
            "active": True,
            "provider": "codex",
            "current_head": session_head,
            "base_head": session_head,
            "project_root": "/tmp/project",
        },
        "current_head": current_head,
        "matches_current_head": session_head == current_head,
        "eligibility": {
            "resume_warnings": [] if session_head == current_head else ["head_mismatch"],
            "risk_warnings": [] if session_head == current_head else ["head_mismatch"],
        },
    }


class _NoBridge:
    def get_runner_status(self, project_root: str) -> dict[str, Any]:
        raise AssertionError(f"unexpected bridge read for {project_root}")


class ExecutorSessionHeadMismatchTests(unittest.TestCase):
    def test_matching_session_head_has_no_mismatch_classification(self) -> None:
        classification = classify_executor_session_head_mismatch(
            executor_session_status=session_status(session_head=HEAD_A, current_head=HEAD_A),
            operation_running=False,
            job_status="idle",
            latest_run_status="completed",
            runner_status="VERSION_PASSED",
            current_version_status="PASSED",
            worktree_clean=True,
        )

        assert classification["status"] == "none"
        assert classification["severity"] == "info"
        assert classification["blocks_auto_resume"] is False
        assert classification["blocks_auto_start"] is False
        assert classification["evidence"]["head_mismatch"] is False

    def test_active_operation_head_mismatch_blocks_resume_and_start(self) -> None:
        classification = classify_executor_session_head_mismatch(
            executor_session_status=session_status(),
            operation_running=True,
            job_status="idle",
            latest_run_status="completed",
            runner_status="VERSION_PASSED",
            current_version_status="PASSED",
            worktree_clean=True,
        )

        assert classification["status"] == "active_operation_head_mismatch"
        assert classification["severity"] == "blocked"
        assert classification["blocks_auto_resume"] is True
        assert classification["blocks_auto_start"] is True
        assert "human_review_required" in classification["allowed_next_actions"]

    def test_completed_idle_stale_session_classification(self) -> None:
        classification = classify_executor_session_head_mismatch(
            executor_session_status=session_status(),
            operation_running=False,
            job_status="idle",
            latest_run_status="completed",
            runner_status="VERSION_PASSED",
            current_version_status="PASSED",
            worktree_clean=True,
        )

        assert classification["status"] == "completed_idle_stale_session"
        assert classification["severity"] == "warning"
        assert classification["blocks_auto_resume"] is True
        assert classification["blocks_auto_start"] is False
        assert classification["job_idle"] is True
        assert "Historical executor session resume metadata" in classification["operator_message"]
        assert "does not mean an executor is currently running" in classification["operator_message"]

    def test_completed_idle_stale_session_does_not_allow_dangerous_actions(self) -> None:
        classification = classify_executor_session_head_mismatch(
            executor_session_status=session_status(),
            operation_running=False,
            job_status="idle",
            latest_run_status="completed",
            runner_status="VERSION_PASSED",
            current_version_status="PASSED",
            worktree_clean=True,
        )

        actions_json = json.dumps(classification["allowed_next_actions"], sort_keys=True)
        for forbidden in ("restart", "reload", "kill", "apply", "commit", "push"):
            assert forbidden not in actions_json
        assert "does not authorize restart, reload, kill, apply, commit, or push" in classification["operator_message"]

    def test_incomplete_evidence_fails_closed_as_unknown_mismatch(self) -> None:
        classification = classify_executor_session_head_mismatch(
            executor_session_status=session_status(),
            operation_running=False,
            job_status="idle",
            latest_run_status=None,
            runner_status="VERSION_PASSED",
            current_version_status="PASSED",
            worktree_clean=None,
        )

        assert classification["status"] == "unknown_head_mismatch"
        assert classification["severity"] == "blocked"
        assert classification["blocks_auto_resume"] is True
        assert classification["blocks_auto_start"] is True
        assert "latest_run_or_claim_completed" in classification["reason"]
        assert "worktree_clean" in classification["reason"]
        assert "evidence is incomplete" in classification["operator_message"]

    def test_web_status_output_includes_operator_message_not_only_raw_warning(self) -> None:
        with tempfile.TemporaryDirectory(prefix="colameta-head-mismatch-status-") as tmp:
            server = WebConsoleServer.__new__(WebConsoleServer)
            server.project_root = str(Path(tmp))
            server.operation_lock = threading.Lock()
            server.operation_running = False
            server.job = {"status": "idle"}
            server.bridge = _NoBridge()
            server._latest_run_evidence_for_classification = lambda live_run=None: ("completed", None, {"available": False})
            server._read_worktree_clean_for_status = lambda: True

            data: dict[str, Any] = {
                "runner_status": "VERSION_PASSED",
                "current_version_status": "PASSED",
                "executor_session_status": session_status(),
                "executor_continuation_preview": {},
                "executor_continuation_decision": {},
                "executor_resume_invocation_preview": {},
            }

            classification = server._apply_executor_session_head_mismatch_classification(data)

        assert classification["status"] == "completed_idle_stale_session"
        assert data["executor_session_head_mismatch"]["operator_message"]
        assert data["executor_session_head_mismatch"]["reason"] == "completed_idle_runner_passed_clean_worktree"
        assert data["executor_session_head_mismatch"]["status"] != "head_mismatch"
        assert data["executor_continuation_preview"]["head_mismatch_classification"]["status"] == "completed_idle_stale_session"

    def test_completed_idle_display_is_historical_not_running(self) -> None:
        status = session_status()
        status["head_mismatch_classification"] = classify_executor_session_head_mismatch(
            executor_session_status=status,
            operation_running=False,
            job_status="idle",
            latest_run_status="completed",
            runner_status="VERSION_PASSED",
            current_version_status="PASSED",
            worktree_clean=True,
        )

        display = build_executor_session_display(
            executor_session_status=status,
            continuation_decision={},
            resume_invocation_preview={},
            continuation_preview={},
        )

        assert display["state"] == "stale_session"
        assert display["head_mismatch_classification_status"] == "completed_idle_stale_session"
        assert "历史 HEAD 不一致" in display["text"]
        assert "运行中" not in display["text"]


if __name__ == "__main__":
    unittest.main()
