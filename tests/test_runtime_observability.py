from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from runner.runtime_observability import (
    PROCESS_START_TIME_ISO,
    get_runtime_version_status,
    git_checkout_metadata,
)


HEAD_A = "a" * 40
HEAD_B = "b" * 40


class RuntimeObservabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="colameta-runtime-observability-")
        self.tmp_path = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def make_git_checkout(self, head: str = HEAD_A, branch: str = "main") -> Path:
        project = self.tmp_path / f"project-{branch}"
        git_dir = project / ".git"
        ref_dir = git_dir / "refs" / "heads"
        ref_dir.mkdir(parents=True)
        (git_dir / "HEAD").write_text(f"ref: refs/heads/{branch}\n", encoding="utf-8")
        (ref_dir / branch).write_text(f"{head}\n", encoding="utf-8")
        return project

    def test_matching_head_reports_no_restart_needed(self) -> None:
        project = self.make_git_checkout(HEAD_A)

        status = get_runtime_version_status(
            str(project),
            loaded_runtime_head=HEAD_A,
            loaded_runtime_branch="main",
            process_start_time_iso="2026-06-26T00:00:00Z",
        )

        assert status["restart_needed"] is False
        assert status["restart_needed_state"] == "not_needed"
        assert status["restart_needed_reason"] == "heads_match"
        assert status["loaded_runtime"]["head"] == HEAD_A
        assert status["project_checkout"]["head"] == HEAD_A
        assert status["project_checkout"]["branch"] == "main"

    def test_mismatched_head_reports_restart_needed(self) -> None:
        project = self.make_git_checkout(HEAD_B)

        status = get_runtime_version_status(str(project), loaded_runtime_head=HEAD_A)

        assert status["restart_needed"] is True
        assert status["restart_needed_state"] == "needed"
        assert status["restart_needed_reason"] == "loaded_runtime_head_differs_from_project_checkout_head"
        assert status["project_checkout"]["head"] == HEAD_B

    def test_missing_unknown_head_reports_unknown_restart_needed(self) -> None:
        project = self.tmp_path / "project-without-git"
        project.mkdir()

        status = get_runtime_version_status(str(project), loaded_runtime_head="")

        assert status["restart_needed"] is None
        assert status["restart_needed_state"] == "unknown"
        assert status["restart_needed_reason"] == "unknown_loaded_runtime_head"
        assert status["loaded_runtime"]["head_available"] is False
        assert status["project_checkout"]["head_available"] is False

    def test_process_start_time_presence(self) -> None:
        status = get_runtime_version_status(None)

        assert status["process_start_time_iso"] == PROCESS_START_TIME_ISO
        parsed = datetime.fromisoformat(status["process_start_time_iso"].replace("Z", "+00:00"))
        assert parsed.tzinfo is not None

    def test_no_restart_side_effects(self) -> None:
        project = self.make_git_checkout(HEAD_A)
        head_path = project / ".git" / "HEAD"
        ref_path = project / ".git" / "refs" / "heads" / "main"
        before_files = sorted(str(path.relative_to(project)) for path in project.rglob("*"))
        before_head = head_path.read_text(encoding="utf-8")
        before_ref = ref_path.read_text(encoding="utf-8")

        status = get_runtime_version_status(str(project), loaded_runtime_head=HEAD_B)

        after_files = sorted(str(path.relative_to(project)) for path in project.rglob("*"))
        assert status["read_only"] is True
        assert status["side_effects"] is False
        assert before_files == after_files
        assert head_path.read_text(encoding="utf-8") == before_head
        assert ref_path.read_text(encoding="utf-8") == before_ref
        for forbidden_key in ("restart", "reload", "kill", "apply"):
            assert forbidden_key not in status

    def test_read_only_result_shape_and_packed_ref(self) -> None:
        project = self.tmp_path / "packed-project"
        git_dir = project / ".git"
        git_dir.mkdir(parents=True)
        (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
        (git_dir / "packed-refs").write_text(f"# pack-refs\n{HEAD_A} refs/heads/main\n", encoding="utf-8")

        metadata = git_checkout_metadata(str(project))
        status = get_runtime_version_status(str(project), loaded_runtime_head=HEAD_A)

        assert metadata["head"] == HEAD_A
        assert status["ok"] is True
        assert status["source"] == "runtime_version_observability"
        assert status["scope"] == "mcp:read"
        assert set(status) >= {
            "process_start_time_iso",
            "loaded_runtime",
            "project_checkout",
            "restart_needed",
            "restart_needed_state",
            "restart_needed_reason",
        }
        assert status["loaded_runtime"]["captured_at_process_start"] is True

    def test_mcp_runtime_version_status_tool_is_read_only(self) -> None:
        from runner.mcp_server import MCPPlanningBridgeServer

        project = self.make_git_checkout(HEAD_A)
        server = MCPPlanningBridgeServer(str(project))

        assert server.get_required_scope_for_tool("get_runtime_version_status", {}) == "mcp:read"
        result = server.call_tool_for_agent("get_runtime_version_status", {})

        assert result["ok"] is True
        assert result["tool"] == "get_runtime_version_status"
        assert result["data"]["read_only"] is True
        assert result["data"]["side_effects"] is False
        assert result["data"]["project_checkout"]["project_root"] == os.path.abspath(str(project))
        assert "get_runtime_version_status" in [tool.name for tool in server.tool_defs]


if __name__ == "__main__":
    unittest.main()
