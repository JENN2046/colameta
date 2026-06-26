from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from runner.mcp_server import MCPPlanningBridgeServer


HEAD_A = "a" * 40


class MCPRuntimeObservabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="colameta-mcp-runtime-observability-")
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

    def test_runtime_version_status_tool_is_registered_read_only_and_scoped(self) -> None:
        project = self.make_git_checkout()
        server = MCPPlanningBridgeServer(str(project))

        assert "get_runtime_version_status" in [tool.name for tool in server.tool_defs]
        assert server.get_required_scope_for_tool("get_runtime_version_status", {}) == "mcp:read"

        result = server.call_tool_for_agent("get_runtime_version_status", {})

        assert result["ok"] is True
        assert result["tool"] == "get_runtime_version_status"
        data = result["data"]
        assert data["read_only"] is True
        assert data["side_effects"] is False
        assert data["project_checkout"]["project_root"] == os.path.abspath(str(project))
        for forbidden_field in ("restart", "reload", "kill", "apply"):
            assert forbidden_field not in result
            assert forbidden_field not in data


if __name__ == "__main__":
    unittest.main()
