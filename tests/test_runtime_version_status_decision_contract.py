from __future__ import annotations

import unittest
from pathlib import Path


DOC_PATH = Path(__file__).resolve().parents[1] / "docs" / "runtime-version-status-decision-contract.md"


class RuntimeVersionStatusDecisionContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.document = DOC_PATH.read_text(encoding="utf-8")
        cls.normalized = " ".join(cls.document.lower().split())

    def test_contract_documents_all_restart_needed_states(self) -> None:
        for state in ("not_needed", "needed", "unknown"):
            assert f"`{state}`" in self.document

    def test_restart_needed_is_signal_not_authorization(self) -> None:
        assert "restart_needed" in self.document
        assert "signals, not authorization" in self.normalized
        assert "do not grant permission" in self.normalized

    def test_needed_maps_to_operator_handoff_only(self) -> None:
        assert '`restart_needed_state == "needed"`' in self.document
        assert "operator handoff notice only" in self.normalized
        assert "no automatic restart is authorized" in self.normalized

    def test_unknown_maps_to_read_only_diagnostics_only(self) -> None:
        assert '`restart_needed_state == "unknown"`' in self.document
        assert "bounded read-only diagnostics only" in self.normalized
        assert "must not treat the result as safe or current" in self.normalized

    def test_no_automatic_restart_reload_kill_apply_authorized(self) -> None:
        assert "does not authorize any automatic restart, reload, kill, or apply action" in self.normalized
        for forbidden in ("automatic restart", "reload", "kill", "apply"):
            assert forbidden in self.normalized

    def test_no_service_lifecycle_or_git_remote_mutation_authorized(self) -> None:
        assert "does not authorize any service lifecycle mutation" in self.normalized
        assert "does not authorize any git remote mutation" in self.normalized
        for forbidden in ("git fetch", "pull", "push", "tag", "release"):
            assert forbidden in self.normalized

    def test_contract_preserves_read_only_observability(self) -> None:
        assert "v1.5 surface is read-only observability" in self.normalized
        assert "does not add web console business routes" in self.normalized
        assert "mcp mutation tools" in self.normalized


if __name__ == "__main__":
    unittest.main()
