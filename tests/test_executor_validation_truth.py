from __future__ import annotations

import unittest

from runner.executor_validation_truth import (
    MAX_VALIDATION_EXCERPT_CHARS,
    build_validation_truth,
    validation_truth_from_summary,
)


COMMAND = "python3 -m unittest discover -s tests"


class ValidationReportTruthTests(unittest.TestCase):
    def test_passed_status_nonzero_exit_is_inconsistent_not_passed(self) -> None:
        truth = build_validation_truth(
            [f"PASSED: {COMMAND}"],
            [{"command": COMMAND, "status": "PASSED", "exit_code": 1}],
        )

        assert truth["validation_inconsistent"] is True
        assert truth["validation_status_summary"] != "passed"
        assert truth["validation_status_summary"] == "inconsistent"
        assert "status_exit_code_mismatch" in truth["validation_command_records"][0]["inconsistency_reason"]

    def test_failed_status_nonzero_exit_is_failed_and_preserves_evidence(self) -> None:
        truth = build_validation_truth(
            [f"FAILED: {COMMAND}"],
            [
                {
                    "command": COMMAND,
                    "original_command": COMMAND,
                    "executed_command": COMMAND,
                    "status": "FAILED",
                    "exit_code": 1,
                    "stdout": "ran tests\n",
                    "stderr": "PermissionError: socket denied\n",
                }
            ],
        )

        record = truth["validation_command_records"][0]
        assert truth["validation_status_summary"] == "failed"
        assert truth["validation_inconsistent"] is False
        assert record["command"] == COMMAND
        assert record["exit_code"] == 1
        assert record["stdout_excerpt"] == "ran tests"
        assert "PermissionError" in record["stderr_excerpt"]

    def test_string_only_validation_results_fallback_still_passes_old_reports(self) -> None:
        truth = validation_truth_from_summary({
            "validation_results": [f"PASSED: {COMMAND}", "Scope check: PASSED"],
        })

        assert truth["validation_status_summary"] == "passed"
        assert truth["validation_inconsistent"] is False
        assert truth["validation_command_records"][0]["source"] == "legacy_validation_results"
        assert truth["validation_command_records"][0]["exit_code"] is None

    def test_summary_passed_but_report_text_failed_same_command_is_inconsistent(self) -> None:
        truth = build_validation_truth(
            [f"PASSED: {COMMAND}"],
            None,
            executor_report_text=f"{COMMAND} failed with 38 socket PermissionError errors.",
        )

        assert truth["validation_inconsistent"] is True
        assert truth["validation_status_summary"] == "inconsistent"
        assert "report_text_failed_same_command" in truth["validation_command_records"][0]["inconsistency_reason"]

    def test_stdout_stderr_excerpts_are_redacted_and_bounded(self) -> None:
        secret_stdout = "api_key=supersecret " + ("x" * (MAX_VALIDATION_EXCERPT_CHARS + 50))
        secret_stderr = "token=verysecret " + ("y" * (MAX_VALIDATION_EXCERPT_CHARS + 50))

        truth = build_validation_truth(
            [f"FAILED: {COMMAND}"],
            [
                {
                    "command": COMMAND,
                    "status": "FAILED",
                    "exit_code": 1,
                    "stdout": secret_stdout,
                    "stderr": secret_stderr,
                }
            ],
        )

        record = truth["validation_command_records"][0]
        assert "supersecret" not in record["stdout_excerpt"]
        assert "verysecret" not in record["stderr_excerpt"]
        assert "api_key=<redacted>" in record["stdout_excerpt"]
        assert "token=<redacted>" in record["stderr_excerpt"]
        assert len(record["stdout_excerpt"]) == MAX_VALIDATION_EXCERPT_CHARS
        assert len(record["stderr_excerpt"]) == MAX_VALIDATION_EXCERPT_CHARS
        assert record["stdout_truncated"] is True
        assert record["stderr_truncated"] is True


if __name__ == "__main__":
    unittest.main()
