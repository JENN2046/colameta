from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from runner.final_version_closeout import (
    apply_final_version_closeout_artifact,
    build_final_version_closeout_preview,
)
from runner.mcp_executor_workflow import MCPExecutorWorkflowManager


COMMIT_V11 = "a" * 40
HEAD = "b" * 40
SUBJECT_V11 = "feat(runtime): add connector health observability"


class FinalVersionCloseoutTests(unittest.TestCase):
    def plan(self) -> dict:
        return {
            "project_name": "colameta-self-dev",
            "versions": [
                {"version": "v1.10", "name": "Runtime Provenance"},
                {"version": "v1.11", "name": "Connector Runtime Health"},
            ],
        }

    def state(self) -> dict:
        return {
            "project_name": "colameta-self-dev",
            "status": "VERSION_PASSED",
            "current_version": "v1.10",
            "current_version_index": 0,
            "attempt": 1,
            "max_fix_attempts_per_version": 3,
            "started_at": "2026-06-30T00:00:00+00:00",
            "updated_at": "2026-06-30T00:00:00+00:00",
            "versions": [
                {
                    "version": "v1.10",
                    "name": "Runtime Provenance",
                    "status": "PASSED",
                    "commit_hash": "1" * 40,
                    "commit_message": "feat(runtime): verify installed package provenance",
                },
                {
                    "version": "v1.11",
                    "name": "Connector Runtime Health",
                    "status": "NOT_STARTED",
                },
            ],
        }

    def preview(self, **overrides) -> dict:
        kwargs = {
            "plan": self.plan(),
            "state": self.state(),
            "target_version": "v1.11",
            "accepted_commit": COMMIT_V11,
            "accepted_commit_subject": SUBJECT_V11,
            "expected_head": HEAD,
            "current_head": HEAD,
            "git_status_short": "",
            "now": "2026-07-01T00:00:00+08:00",
            "state_file": ".colameta/state.json",
            "project_root": "/tmp/project",
            "expected_branch": "main",
            "current_branch": "main",
            "commit_exists": True,
            "commit_subject": SUBJECT_V11,
            "commit_files": ["runner/runtime_observability.py"],
            "evidence_refs": ["receipt:v1.11"],
            "evidence_summary": "",
            "reason": "manual controlled v1.11 closeout",
        }
        kwargs.update(overrides)
        return build_final_version_closeout_preview(**kwargs)

    @staticmethod
    def blocker_codes(result: dict) -> set[str]:
        return {item.get("code") for item in result.get("blockers", []) if isinstance(item, dict)}

    def test_preview_happy_path_marks_final_version_completed(self) -> None:
        result = self.preview()

        assert result["status"] == "preview_ready"
        assert result["can_apply"] is True
        assert result["before_state_summary"]["current_version"] == "v1.10"
        assert result["proposed_after_state_summary"]["runner_status"] == "COMPLETED"
        assert result["proposed_after_state_summary"]["current_version"] == "v1.11"
        assert result["versions_to_update"] == [{
            "version": "v1.11",
            "before": {"version": "v1.11", "status": "NOT_STARTED", "commit_hash": None, "commit_message": None},
            "after": {
                "version": "v1.11",
                "status": "PASSED",
                "commit_hash": COMMIT_V11,
                "commit_message": SUBJECT_V11,
            },
        }]
        assert "delivery_state_accepted_write" in result["forbidden_side_effects"]
        assert ".colameta/state.json" in result["files_apply_would_touch"]

    def test_apply_happy_path_updates_only_runner_state(self) -> None:
        artifact = self.preview()
        artifact["preview_id"] = "final_closeout_preview_1"

        result = apply_final_version_closeout_artifact(
            artifact=artifact,
            current_state=self.state(),
            preview_id="final_closeout_preview_1",
            current_head=HEAD,
            git_status_short="",
            current_branch="main",
            commit_exists=True,
            commit_subject=SUBJECT_V11,
        )

        assert result["ok"] is True
        updated = result["updated_state"]
        assert updated["status"] == "COMPLETED"
        assert updated["current_version"] == "v1.11"
        assert updated["current_version_index"] == 1
        assert updated["versions"][0]["status"] == "PASSED"
        assert updated["versions"][1]["status"] == "PASSED"
        assert updated["versions"][1]["commit_hash"] == COMMIT_V11
        metadata = updated["versions"][1]["metadata"]["final_version_closeout"]
        assert metadata["accepted_commit"] == COMMIT_V11
        assert "gate_event_write" in metadata["forbidden_side_effects"]

    def test_non_final_target_fails_closed(self) -> None:
        result = self.preview(target_version="v1.10")

        assert result["can_apply"] is False
        assert "TARGET_VERSION_NOT_FINAL" in self.blocker_codes(result)
        assert "TARGET_VERSION_STATUS_UNSUPPORTED" in self.blocker_codes(result)

    def test_dirty_worktree_fails_closed(self) -> None:
        result = self.preview(git_status_short=" M runner/file.py")

        assert result["can_apply"] is False
        assert "WORKTREE_DIRTY" in self.blocker_codes(result)

    def test_subject_mismatch_fails_closed(self) -> None:
        result = self.preview(commit_subject="different subject")

        assert result["can_apply"] is False
        assert "ACCEPTED_COMMIT_SUBJECT_MISMATCH" in self.blocker_codes(result)

    def test_missing_local_evidence_path_fails_closed(self) -> None:
        result = self.preview(evidence_refs=["path:.colameta/reports/missing.md"])

        assert result["can_apply"] is False
        assert "EVIDENCE_PATH_NOT_FOUND" in self.blocker_codes(result)

    def test_apply_blocks_when_state_changed_since_preview(self) -> None:
        artifact = self.preview()
        artifact["preview_id"] = "expected"
        changed_state = self.state()
        changed_state["updated_at"] = "2026-07-01T01:00:00+08:00"

        result = apply_final_version_closeout_artifact(
            artifact=artifact,
            current_state=changed_state,
            preview_id="expected",
            current_head=HEAD,
            git_status_short="",
            current_branch="main",
            commit_exists=True,
            commit_subject=SUBJECT_V11,
        )

        assert result["ok"] is False
        assert result["error_code"] == "STATE_CHANGED_SINCE_PREVIEW"

    def test_manager_preview_and_apply_use_temporary_state_file(self) -> None:
        with tempfile.TemporaryDirectory(prefix="colameta-final-closeout-") as tmp:
            project = Path(tmp)
            (project / ".colameta" / "reports" / "executor-runs" / "v1.11").mkdir(parents=True)
            (project / ".gitignore").write_text(
                ".colameta/state.json\n.colameta/runtime/**\n.colameta/reports/**\n",
                encoding="utf-8",
            )
            (project / ".colameta" / "plan.json").write_text(json.dumps(self.plan()), encoding="utf-8")
            (project / ".colameta" / "state.json").write_text(json.dumps(self.state()), encoding="utf-8")
            receipt = project / ".colameta" / "reports" / "executor-runs" / "v1.11" / "receipt.md"
            receipt.write_text("v1.11 closeout evidence\n", encoding="utf-8")

            self._git(project, "init")
            self._git(project, "checkout", "-b", "main")
            self._git(project, "config", "user.name", "Test")
            self._git(project, "config", "user.email", "test@example.com")
            self._git(project, "add", ".gitignore", ".colameta/plan.json")
            self._git(project, "commit", "-m", "initial plan")
            commit_v11 = self._commit_file(project, "health.txt", "v1.11\n", SUBJECT_V11)

            manager = MCPExecutorWorkflowManager(str(project))
            result = manager.handle("final_version_closeout_preview", {
                "expected_head": commit_v11,
                "expected_branch": "main",
                "target_version": "v1.11",
                "accepted_commit": commit_v11,
                "accepted_commit_subject": SUBJECT_V11,
                "evidence_refs": ["path:.colameta/reports/executor-runs/v1.11/receipt.md"],
                "reason": "manual controlled v1.11 closeout",
            })

            assert result["status"] == "preview_ready"
            apply_result = manager.handle("final_version_closeout_apply", {
                "preview_id": result["preview_id"],
            })

            assert apply_result["ok"] is True
            updated = json.loads((project / ".colameta" / "state.json").read_text(encoding="utf-8"))
            assert updated["current_version"] == "v1.11"
            assert updated["status"] == "COMPLETED"
            assert updated["versions"][1]["commit_hash"] == commit_v11
            assert self._git_out(project, "status", "--short") == ""

    def _commit_file(self, project: Path, name: str, content: str, subject: str) -> str:
        (project / name).write_text(content, encoding="utf-8")
        self._git(project, "add", name)
        self._git(project, "commit", "-m", subject)
        return self._git_out(project, "rev-parse", "HEAD")

    def _git(self, project: Path, *args: str) -> None:
        proc = subprocess.run(["git", *args], cwd=project, capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            raise AssertionError(proc.stderr or proc.stdout)

    def _git_out(self, project: Path, *args: str) -> str:
        proc = subprocess.run(["git", *args], cwd=project, capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            raise AssertionError(proc.stderr or proc.stdout)
        return proc.stdout.strip()


if __name__ == "__main__":
    unittest.main()
