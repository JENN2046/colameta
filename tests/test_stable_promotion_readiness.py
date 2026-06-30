from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from runner.stable_promotion_readiness import (
    REQUIRED_VISIBLE_TOOLS,
    REQUIRED_WORKFLOWS,
    get_stable_promotion_readiness,
)


class StablePromotionReadinessTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="colameta-stable-readiness-")
        self.tmp_path = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def make_repo_with_origin(self) -> tuple[Path, str]:
        origin = self.tmp_path / "origin.git"
        repo = self.tmp_path / "repo"
        self.run_cmd(["git", "init", "--bare", str(origin)])
        self.run_cmd(["git", "init", str(repo)])
        self.run_cmd(["git", "-C", str(repo), "config", "user.email", "test@example.invalid"])
        self.run_cmd(["git", "-C", str(repo), "config", "user.name", "ColaMeta Test"])
        (repo / "README.md").write_text("# Demo\n", encoding="utf-8")
        self.run_cmd(["git", "-C", str(repo), "add", "README.md"])
        self.run_cmd(["git", "-C", str(repo), "commit", "-m", "initial"])
        self.run_cmd(["git", "-C", str(repo), "branch", "-M", "main"])
        self.run_cmd(["git", "-C", str(repo), "remote", "add", "origin", str(origin)])
        self.run_cmd(["git", "-C", str(repo), "push", "-u", "origin", "main"])
        head = self.run_cmd(["git", "-C", str(repo), "rev-parse", "HEAD"]).stdout.strip()
        return repo, head

    def runtime_status(self, repo: Path, head: str, *, reload_needed: bool = False) -> dict[str, object]:
        return {
            "project_checkout_head": head,
            "project_checkout": {"branch": "main"},
            "loaded_runtime": {"source_root": str(repo)},
            "loaded_runtime_head": head,
            "runtime_loaded_code_stale": reload_needed,
            "reload_needed_for_verification": reload_needed,
            "reload_awareness_reason": "loaded_code_verified_current" if not reload_needed else "loaded_head_differs_from_project_head",
        }

    def readiness(self, repo: Path, head: str, **overrides: object) -> dict[str, object]:
        stable_dir = self.tmp_path / "stable-runtime"
        stable_dir.mkdir(exist_ok=True)
        kwargs: dict[str, object] = {
            "visible_tool_names": list(REQUIRED_VISIBLE_TOOLS),
            "supported_workflows": list(REQUIRED_WORKFLOWS),
            "runtime_status": self.runtime_status(repo, head),
            "stable_runtime_dir": str(stable_dir),
        }
        kwargs.update(overrides)
        return get_stable_promotion_readiness(str(repo), **kwargs)

    def test_clean_current_runtime_is_review_candidate_not_production_ready(self) -> None:
        repo, head = self.make_repo_with_origin()

        result = self.readiness(repo, head)

        assert result["ok"] is True
        assert result["read_only"] is True
        assert result["side_effects"] is False
        assert result["readiness_status"] == "stable_promotion_review_candidate"
        assert result["stable_promotion_review_candidate"] is True
        assert result["stable_production_ready"] is False
        assert result["local_blockers"] == []
        assert result["candidate_artifact_manifest"]["available"] is True
        assert result["candidate_artifact_manifest"]["file_count"] == 1
        assert len(result["candidate_artifact_manifest"]["manifest_sha256"]) == 64
        assert {item["code"] for item in result["external_required_before_stable_replacement"]} == {
            "PROMOTION_ARTIFACT_MANIFEST_NOT_PERSISTED",
            "ROLLBACK_REHEARSAL_NOT_PROVEN",
            "COMMANDER_STABLE_REPLACEMENT_AUTHORIZATION_ABSENT",
        }
        assert result["git"]["worktree_clean"] is True
        assert result["git"]["ahead"] == 0
        assert result["tool_support"]["agent_consumer_contract_visible"] is True
        assert result["tool_support"]["stable_readiness_tool_visible"] is True
        assert result["safety_boundary"]["does_not_authorize_stable_replacement"] is True

    def test_dirty_worktree_blocks_review_candidate(self) -> None:
        repo, head = self.make_repo_with_origin()
        (repo / "scratch.txt").write_text("dirty\n", encoding="utf-8")

        result = self.readiness(repo, head)

        assert result["stable_promotion_review_candidate"] is False
        assert result["readiness_status"] == "not_ready_for_stable_promotion_review"
        assert "WORKTREE_NOT_CLEAN" in {item["code"] for item in result["local_blockers"]}

    def test_runtime_reload_needed_blocks_review_candidate(self) -> None:
        repo, head = self.make_repo_with_origin()

        result = self.readiness(repo, head, runtime_status=self.runtime_status(repo, head, reload_needed=True))

        assert result["stable_promotion_review_candidate"] is False
        assert "RUNTIME_RELOAD_NEEDED_FOR_VERIFICATION" in {item["code"] for item in result["local_blockers"]}

    def test_missing_required_entrypoint_blocks_review_candidate(self) -> None:
        repo, head = self.make_repo_with_origin()
        visible = [tool for tool in REQUIRED_VISIBLE_TOOLS if tool != "get_web_gpt_service_entrypoint"]

        result = self.readiness(repo, head, visible_tool_names=visible)

        assert result["stable_promotion_review_candidate"] is False
        assert "REQUIRED_MCP_TOOLS_MISSING" in {item["code"] for item in result["local_blockers"]}
        assert result["tool_support"]["web_gpt_entrypoint_visible"] is False

    def test_missing_agent_consumer_contract_blocks_review_candidate(self) -> None:
        repo, head = self.make_repo_with_origin()
        visible = [tool for tool in REQUIRED_VISIBLE_TOOLS if tool != "get_agent_consumer_contract"]

        result = self.readiness(repo, head, visible_tool_names=visible)

        assert result["stable_promotion_review_candidate"] is False
        assert "REQUIRED_MCP_TOOLS_MISSING" in {item["code"] for item in result["local_blockers"]}
        assert result["tool_support"]["agent_consumer_contract_visible"] is False

    def run_cmd(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        completed = subprocess.run(command, capture_output=True, text=True, check=False, timeout=10)
        assert completed.returncode == 0, completed.stderr
        return completed


if __name__ == "__main__":
    unittest.main()
