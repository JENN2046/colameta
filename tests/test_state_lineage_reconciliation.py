from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from runner.mcp_executor_workflow import MCPExecutorWorkflowManager
from runner.state_lineage_reconciliation import (
    apply_state_lineage_reconciliation_artifact,
    build_state_lineage_reconciliation_preview,
)


COMMIT_V15 = "5" * 40
COMMIT_V16 = "6" * 40
HEAD = "d" * 40
SUBJECT_V15 = "feat(runtime): add read-only version observability"
SUBJECT_V16 = "docs(runtime): add version status decision contract"


class StateLineageReconciliationTests(unittest.TestCase):
    def plan(self) -> dict:
        return {
            "project_name": "colameta-self-dev",
            "versions": [
                {"version": "v1.5", "name": "Runtime Version Observability"},
                {"version": "v1.6", "name": "Runtime Decision Contract"},
                {"version": "v1.7", "name": "Runtime Decision Evaluator"},
            ],
        }

    def state(self) -> dict:
        return {
            "project_name": "colameta-self-dev",
            "status": "BLOCKED_BY_ACCEPTANCE_FAILURE",
            "current_version": "v1.5",
            "current_version_index": 0,
            "attempt": 1,
            "max_fix_attempts_per_version": 3,
            "started_at": "2026-06-26T00:00:00+00:00",
            "updated_at": "2026-06-26T00:00:00+00:00",
            "versions": [
                {
                    "version": "v1.5",
                    "name": "Runtime Version Observability",
                    "status": "FAILED_BLOCKED",
                    "commit_hash": HEAD,
                    "commit_message": "chore(plan): add v1.7 runtime decision evaluator slice",
                },
                {"version": "v1.6", "name": "Runtime Decision Contract", "status": "NOT_STARTED"},
                {"version": "v1.7", "name": "Runtime Decision Evaluator", "status": "NOT_STARTED"},
            ],
        }

    def bindings(self, commit_v15: str = COMMIT_V15, commit_v16: str = COMMIT_V16) -> list[dict]:
        return [
            {
                "version": "v1.5",
                "target_status": "PASSED",
                "accepted_commit": commit_v15,
                "accepted_commit_subject": SUBJECT_V15,
                "evidence_refs": ["receipt:v1.5"],
                "reason": "manual controlled v1.5 closeout",
            },
            {
                "version": "v1.6",
                "target_status": "PASSED",
                "accepted_commit": commit_v16,
                "accepted_commit_subject": SUBJECT_V16,
                "evidence_refs": ["receipt:v1.6"],
                "reason": "manual controlled v1.6 closeout",
            },
            {
                "version": "v1.7",
                "target_status": "NOT_STARTED",
                "evidence_refs": ["commit:plan-v1.7"],
                "reason": "v1.7 remains the next runnable version",
            },
        ]

    def preview(self, **overrides) -> dict:
        kwargs = {
            "plan": self.plan(),
            "state": self.state(),
            "bindings": self.bindings(),
            "expected_head": HEAD,
            "current_head": HEAD,
            "git_status_short": "",
            "target_next_version": "v1.7",
            "now": "2026-06-27T00:00:00+08:00",
            "state_file": ".colameta/state.json",
            "project_root": "/tmp/project",
            "expected_branch": "main",
            "current_branch": "main",
            "commit_exists": {COMMIT_V15: True, COMMIT_V16: True},
            "commit_subjects": {COMMIT_V15: SUBJECT_V15, COMMIT_V16: SUBJECT_V16},
        }
        kwargs.update(overrides)
        return build_state_lineage_reconciliation_preview(**kwargs)

    @staticmethod
    def blocker_codes(result: dict) -> set[str]:
        return {item.get("code") for item in result.get("blockers", []) if isinstance(item, dict)}

    def test_preview_happy_path(self) -> None:
        result = self.preview()

        assert result["status"] == "preview_ready"
        assert result["can_apply"] is True
        assert result["before_state_summary"]["current_version"] == "v1.5"
        assert result["proposed_after_state_summary"]["current_version"] == "v1.7"
        assert result["proposed_after_state_summary"]["runner_status"] == "READY"
        assert result["commit_bindings"] == [
            {"version": "v1.5", "accepted_commit": COMMIT_V15, "accepted_commit_subject": SUBJECT_V15},
            {"version": "v1.6", "accepted_commit": COMMIT_V16, "accepted_commit_subject": SUBJECT_V16},
        ]
        assert "executor_run" in result["forbidden_side_effects"]
        assert ".colameta/state.json" in result["files_apply_would_touch"]

    def test_apply_happy_path_only_updates_expected_state_shape(self) -> None:
        artifact = self.preview()
        artifact["preview_id"] = "state_lineage_preview_1"

        result = apply_state_lineage_reconciliation_artifact(
            artifact=artifact,
            current_state=self.state(),
            preview_id="state_lineage_preview_1",
            current_head=HEAD,
            git_status_short="",
            current_branch="main",
            commit_exists={COMMIT_V15: True, COMMIT_V16: True},
            commit_subjects={COMMIT_V15: SUBJECT_V15, COMMIT_V16: SUBJECT_V16},
        )

        assert result["ok"] is True
        updated = result["updated_state"]
        assert updated["status"] == "READY"
        assert updated["current_version"] == "v1.7"
        assert updated["current_version_index"] == 2
        assert updated["versions"][0]["status"] == "PASSED"
        assert updated["versions"][0]["commit_hash"] == COMMIT_V15
        assert updated["versions"][1]["status"] == "PASSED"
        assert updated["versions"][1]["commit_hash"] == COMMIT_V16
        assert updated["versions"][2]["status"] == "NOT_STARTED"
        assert updated["project_name"] == self.state()["project_name"]

    def test_dirty_worktree_fails_closed(self) -> None:
        result = self.preview(git_status_short=" M runner/file.py")

        assert result["can_apply"] is False
        assert "WORKTREE_DIRTY" in self.blocker_codes(result)

    def test_head_mismatch_fails_closed(self) -> None:
        result = self.preview(current_head="e" * 40)

        assert result["can_apply"] is False
        assert "HEAD_MISMATCH" in self.blocker_codes(result)

    def test_missing_evidence_fails_closed(self) -> None:
        bindings = self.bindings()
        bindings[0]["evidence_refs"] = []
        result = self.preview(bindings=bindings)

        assert result["can_apply"] is False
        assert "EVIDENCE_REQUIRED" in self.blocker_codes(result)

    def test_missing_version_fails_closed(self) -> None:
        bindings = self.bindings()
        bindings[0]["version"] = "v9.9"
        result = self.preview(bindings=bindings)

        assert result["can_apply"] is False
        assert "VERSION_MISSING_FROM_PLAN" in self.blocker_codes(result)
        assert "VERSION_MISSING_FROM_STATE" in self.blocker_codes(result)

    def test_missing_local_commit_fails_closed(self) -> None:
        result = self.preview(commit_exists={COMMIT_V15: False, COMMIT_V16: True})

        assert result["can_apply"] is False
        assert "ACCEPTED_COMMIT_MISSING" in self.blocker_codes(result)

    def test_unresolved_earlier_version_skip_fails_closed(self) -> None:
        bindings = [self.bindings()[0], self.bindings()[2]]
        result = self.preview(bindings=bindings)

        assert result["can_apply"] is False
        assert "UNRESOLVED_EARLIER_VERSION" in self.blocker_codes(result)

    def test_apply_requires_matching_preview_id(self) -> None:
        artifact = self.preview()
        artifact["preview_id"] = "expected"

        result = apply_state_lineage_reconciliation_artifact(
            artifact=artifact,
            current_state=self.state(),
            preview_id="other",
            current_head=HEAD,
            git_status_short="",
            current_branch="main",
            commit_exists={COMMIT_V15: True, COMMIT_V16: True},
            commit_subjects={COMMIT_V15: SUBJECT_V15, COMMIT_V16: SUBJECT_V16},
        )

        assert result["ok"] is False
        assert result["error_code"] == "PREVIEW_ID_MISMATCH"

    def test_manager_preview_and_apply_use_temporary_state_file(self) -> None:
        with tempfile.TemporaryDirectory(prefix="colameta-state-lineage-") as tmp:
            project = Path(tmp)
            (project / ".colameta").mkdir()
            (project / ".gitignore").write_text(
                ".colameta/state.json\n.colameta/runtime/**\n",
                encoding="utf-8",
            )
            (project / ".colameta" / "plan.json").write_text(json.dumps(self.plan()), encoding="utf-8")
            (project / ".colameta" / "state.json").write_text(json.dumps(self.state()), encoding="utf-8")

            self._git(project, "init")
            self._git(project, "checkout", "-b", "main")
            self._git(project, "config", "user.name", "Test")
            self._git(project, "config", "user.email", "test@example.com")
            self._git(project, "add", ".gitignore", ".colameta/plan.json")
            self._git(project, "commit", "-m", "initial plan")
            commit_v15 = self._commit_file(project, "runtime.txt", "v1.5\n", SUBJECT_V15)
            commit_v16 = self._commit_file(project, "contract.txt", "v1.6\n", SUBJECT_V16)
            head = self._commit_file(project, "plan.txt", "v1.7\n", "chore(plan): add v1.7 runtime decision evaluator slice")

            manager = MCPExecutorWorkflowManager(str(project))
            bindings = self.bindings(commit_v15=commit_v15, commit_v16=commit_v16)
            result = manager.handle("state_lineage_reconciliation_preview", {
                "expected_head": head,
                "expected_branch": "main",
                "target_next_version": "v1.7",
                "bindings": bindings,
            })

            assert result["status"] == "preview_ready"
            apply_result = manager.handle("state_lineage_reconciliation_apply", {
                "preview_id": result["preview_id"],
            })

            assert apply_result["ok"] is True
            updated = json.loads((project / ".colameta" / "state.json").read_text(encoding="utf-8"))
            assert updated["current_version"] == "v1.7"
            assert updated["status"] == "READY"
            assert updated["versions"][0]["commit_hash"] == commit_v15
            assert updated["versions"][1]["commit_hash"] == commit_v16
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
