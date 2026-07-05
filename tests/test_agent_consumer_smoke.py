from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.agent_consumer_smoke import EXPECTED_PROFILE_IDS, run_agent_consumer_smoke


class AgentConsumerSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="colameta-agent-consumer-smoke-test-")
        self.tmp_path = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def make_git_checkout(self) -> Path:
        project = self.tmp_path / "project"
        ref_dir = project / ".git" / "refs" / "heads"
        ref_dir.mkdir(parents=True)
        (project / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
        (ref_dir / "main").write_text("a" * 40 + "\n", encoding="utf-8")
        return project

    def test_agent_consumer_smoke_runs_with_temporary_registry(self) -> None:
        project = self.make_git_checkout()

        result = run_agent_consumer_smoke(project, project_name="demo-project")

        assert result["ok"] is True
        assert result["project_name"] == "demo-project"
        assert tuple(result["profile_ids"]) == EXPECTED_PROFILE_IDS
        assert result["entry_profiles_match_contract"] is True
        assert result["invalid_profile_fail_closed"] is True
        assert result["readiness_missing_tools"] == []
        assert result["operator_flow_primary_tool"] == "run_mcp_workflow"
        assert result["operator_flow_gate_level"] == "read_only_workflow_packet"
        assert result["profile_results"]["reviewer_agent"]["authority"] == "review_only"

    def test_agent_consumer_smoke_summary_is_json_serializable(self) -> None:
        project = self.make_git_checkout()

        result = run_agent_consumer_smoke(project, project_name="demo-project")

        assert json.loads(json.dumps(result))["ok"] is True
