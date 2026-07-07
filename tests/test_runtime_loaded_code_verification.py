from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

import runner.runtime_observability as runtime_observability
from runner.runtime_observability import (
    get_runtime_version_status,
    loaded_runner_module_fingerprints,
)


HEAD_A = "a" * 40
HEAD_B = "b" * 40
ROOT = Path(__file__).resolve().parents[1]


class RuntimeLoadedCodeVerificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="colameta-runtime-loaded-code-")
        self.tmp_path = Path(self._tmp.name)
        runtime_observability._runtime_healthz_provenance_cached.cache_clear()

    def tearDown(self) -> None:
        runtime_observability._runtime_healthz_provenance_cached.cache_clear()
        self._tmp.cleanup()

    def make_git_checkout(self, head: str = HEAD_A, branch: str = "main") -> Path:
        project = self.tmp_path / f"project-{branch}"
        git_dir = project / ".git"
        ref_dir = git_dir / "refs" / "heads"
        ref_dir.mkdir(parents=True)
        (git_dir / "HEAD").write_text(f"ref: refs/heads/{branch}\n", encoding="utf-8")
        (ref_dir / branch).write_text(f"{head}\n", encoding="utf-8")
        return project

    def make_module_file(self, content: str = "loaded = True\n") -> Path:
        source_path = self.tmp_path / "runner_runtime_observability.py"
        source_path.write_text(content, encoding="utf-8")
        return source_path

    def module_fingerprint(
        self,
        source_path: Path,
        *,
        module_name: str = "runner.runtime_observability",
        surfaces: list[str] | None = None,
    ) -> dict[str, dict[str, object]]:
        content = source_path.read_bytes()
        stat_result = source_path.stat()
        return {
            module_name: {
                "module_name": module_name,
                "source_path": str(source_path),
                "relative_path": f"runner/{source_path.name}",
                "surfaces": surfaces or ["runtime observability", "MCP tool results"],
                "fingerprint_algorithm": "sha256",
                "fingerprint_available": True,
                "sha256": hashlib.sha256(content).hexdigest(),
                "size_bytes": stat_result.st_size,
                "mtime_ns": stat_result.st_mtime_ns,
                "captured_at_process_start": True,
            }
        }

    def test_import_time_runner_module_fingerprints_are_available(self) -> None:
        evidence = loaded_runner_module_fingerprints()

        assert "runner.runtime_observability" in evidence
        runtime_evidence = evidence["runner.runtime_observability"]
        assert runtime_evidence["fingerprint_algorithm"] == "sha256"
        assert runtime_evidence["fingerprint_available"] is True
        assert runtime_evidence["captured_at_process_start"] is True

    def test_mcp_tool_registration_and_scope_remain_read_only(self) -> None:
        from runner.mcp_server import MCPPlanningBridgeServer

        project = self.make_git_checkout()
        server = MCPPlanningBridgeServer(str(project))

        assert "get_runtime_version_status" in [tool.name for tool in server.tool_defs]
        assert server.get_required_scope_for_tool("get_runtime_version_status", {}) == "mcp:read"
        result = server.call_tool_for_agent("get_runtime_version_status", {})

        assert result["ok"] is True
        assert result["tool"] == "get_runtime_version_status"
        assert result["data"]["ok"] is True
        assert result["data"]["read_only"] is True
        assert result["data"]["side_effects"] is False
        self.assert_no_forbidden_runtime_mutation_fields(result["data"])

    def test_matching_heads_and_module_fingerprints_report_not_stale(self) -> None:
        project = self.make_git_checkout(HEAD_A)
        source_path = self.make_module_file("loaded = 'same'\n")

        status = get_runtime_version_status(
            str(project),
            loaded_runtime_head=HEAD_A,
            loaded_module_fingerprints=self.module_fingerprint(source_path),
        )

        assert status["runtime_loaded_code_stale"] is False
        assert status["reload_needed_for_verification"] is False
        assert status["reload_awareness_reason"] == "loaded_code_verified_current"
        assert status["loaded_runtime_head"] == HEAD_A
        assert status["project_checkout_head"] == HEAD_A
        assert status["loaded_module_source_changed"] is False
        assert status["changed_loaded_modules"] == []
        assert status["possibly_stale_surfaces"] == []
        assert status["loaded_module_verification"]["verified_module_count"] == 1
        assert status["restart_needed_state"] == "not_needed"

    def test_mismatched_loaded_and_project_heads_report_stale(self) -> None:
        project = self.make_git_checkout(HEAD_B)
        source_path = self.make_module_file("loaded = 'same'\n")

        status = get_runtime_version_status(
            str(project),
            loaded_runtime_head=HEAD_A,
            loaded_module_fingerprints=self.module_fingerprint(source_path),
        )

        assert status["runtime_loaded_code_stale"] is True
        assert status["reload_needed_for_verification"] is True
        assert status["reload_awareness_reason"] == "loaded_head_differs_from_project_head"
        assert status["restart_needed_state"] == "needed"
        assert "MCP tool results" in status["possibly_stale_surfaces"]
        assert "Web Console handlers" in status["possibly_stale_surfaces"]
        assert "executor workflow code paths" in status["possibly_stale_surfaces"]

    def test_changed_loaded_module_fingerprint_reports_stale_and_surfaces(self) -> None:
        project = self.make_git_checkout(HEAD_A)
        source_path = self.make_module_file("loaded = 'before'\n")
        loaded_fingerprints = self.module_fingerprint(source_path)
        source_path.write_text("loaded = 'after'\n", encoding="utf-8")

        status = get_runtime_version_status(
            str(project),
            loaded_runtime_head=HEAD_A,
            loaded_module_fingerprints=loaded_fingerprints,
        )

        assert status["runtime_loaded_code_stale"] is True
        assert status["reload_needed_for_verification"] is True
        assert status["reload_awareness_reason"] == "loaded_module_source_changed"
        assert status["loaded_module_source_changed"] is True
        assert status["changed_loaded_modules"][0]["module_name"] == "runner.runtime_observability"
        assert status["changed_loaded_modules"][0]["verification_reason"] == "sha256_mismatch"
        assert "runtime observability" in status["possibly_stale_surfaces"]
        assert "MCP tool results" in status["possibly_stale_surfaces"]
        assert status["restart_needed_state"] == "not_needed"

    def test_unknown_head_fails_closed_without_authorizing_reload(self) -> None:
        project = self.tmp_path / "project-without-git"
        project.mkdir()
        source_path = self.make_module_file("loaded = 'same'\n")

        status = get_runtime_version_status(
            str(project),
            loaded_runtime_head="",
            loaded_module_fingerprints=self.module_fingerprint(source_path),
        )

        assert status["runtime_loaded_code_stale"] is None
        assert status["reload_needed_for_verification"] is True
        assert status["reload_awareness_reason"] == "unknown_runtime_or_checkout_head"
        assert status["restart_needed_state"] == "unknown"
        assert status["read_only"] is True
        assert status["side_effects"] is False
        self.assert_no_forbidden_runtime_mutation_fields(status)

    def test_installed_package_matching_project_checkout_clears_reload_verification(self) -> None:
        project = self.make_git_checkout(HEAD_A)
        installed_root = self.tmp_path / "site-packages"
        files = {
            "runner/runtime_observability.py": "loaded = 'runtime'\n",
            "scripts/runner_cli.py": "loaded = 'cli'\n",
        }
        for relative_path, content in files.items():
            project_file = project / relative_path
            project_file.parent.mkdir(parents=True, exist_ok=True)
            project_file.write_text(content, encoding="utf-8")
            installed_file = installed_root / relative_path
            installed_file.parent.mkdir(parents=True, exist_ok=True)
            installed_file.write_text(content, encoding="utf-8")

        fake_distribution = self.fake_distribution(installed_root, list(files))
        loaded_fingerprints = self.module_fingerprint(
            installed_root / "runner/runtime_observability.py",
            module_name="runner.runtime_observability",
        )

        with patch.object(runtime_observability, "LOADED_SOURCE_ROOT", str(installed_root)):
            with patch.object(runtime_observability.importlib.metadata, "distribution", return_value=fake_distribution):
                with patch.object(
                    runtime_observability,
                    "_source_checkout_cleanliness",
                    return_value=self.source_cleanliness(clean=True),
                ):
                    status = get_runtime_version_status(
                        str(project),
                        loaded_runtime_head="",
                        loaded_module_fingerprints=loaded_fingerprints,
                    )

        assert status["restart_needed_state"] == "unknown"
        assert status["runtime_loaded_code_stale"] is False
        assert status["reload_needed_for_verification"] is False
        assert status["reload_awareness_reason"] == "installed_package_matches_project_checkout"
        package = status["installed_package_verification"]
        assert package["verification_status"] == "match"
        assert package["matches_project_checkout"] is True
        assert package["project_source_clean"] is True
        assert package["checked_file_count"] == len(files)
        assert package["mismatched_file_count"] == 0

    def test_installed_package_matching_dirty_project_checkout_stays_unverified(self) -> None:
        project = self.make_git_checkout(HEAD_A)
        installed_root = self.tmp_path / "site-packages-dirty"
        relative_path = "runner/runtime_observability.py"
        for root in (project, installed_root):
            target = root / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("loaded = 'dirty-but-installed'\n", encoding="utf-8")

        fake_distribution = self.fake_distribution(installed_root, [relative_path])
        loaded_fingerprints = self.module_fingerprint(installed_root / relative_path)

        with patch.object(runtime_observability, "LOADED_SOURCE_ROOT", str(installed_root)):
            with patch.object(runtime_observability.importlib.metadata, "distribution", return_value=fake_distribution):
                with patch.object(
                    runtime_observability,
                    "_source_checkout_cleanliness",
                    return_value=self.source_cleanliness(clean=False),
                ):
                    status = get_runtime_version_status(
                        str(project),
                        loaded_runtime_head="",
                        loaded_module_fingerprints=loaded_fingerprints,
                    )

        assert status["runtime_loaded_code_stale"] is None
        assert status["reload_needed_for_verification"] is True
        assert status["reload_awareness_reason"] == "installed_package_project_checkout_dirty"
        package = status["installed_package_verification"]
        assert package["verification_status"] == "dirty_project_checkout"
        assert package["matches_project_checkout"] is False
        assert package["matches_project_worktree"] is True
        assert package["project_source_clean"] is False
        assert package["source_cleanliness_status"] == "dirty"

    def test_installed_package_mismatch_keeps_reload_verification_blocked(self) -> None:
        project = self.make_git_checkout(HEAD_A)
        installed_root = self.tmp_path / "site-packages-mismatch"
        relative_path = "runner/runtime_observability.py"
        project_file = project / relative_path
        project_file.parent.mkdir(parents=True, exist_ok=True)
        project_file.write_text("loaded = 'project'\n", encoding="utf-8")
        installed_file = installed_root / relative_path
        installed_file.parent.mkdir(parents=True, exist_ok=True)
        installed_file.write_text("loaded = 'installed'\n", encoding="utf-8")

        fake_distribution = self.fake_distribution(installed_root, [relative_path])
        loaded_fingerprints = self.module_fingerprint(installed_file)

        with patch.object(runtime_observability, "LOADED_SOURCE_ROOT", str(installed_root)):
            with patch.object(runtime_observability.importlib.metadata, "distribution", return_value=fake_distribution):
                with patch.object(
                    runtime_observability,
                    "_source_checkout_cleanliness",
                    return_value=self.source_cleanliness(clean=True),
                ):
                    status = get_runtime_version_status(
                        str(project),
                        loaded_runtime_head="",
                        loaded_module_fingerprints=loaded_fingerprints,
                    )

        assert status["runtime_loaded_code_stale"] is None
        assert status["reload_needed_for_verification"] is True
        assert status["reload_awareness_reason"] == "unknown_runtime_or_checkout_head"
        package = status["installed_package_verification"]
        assert package["verification_status"] == "mismatch"
        assert package["matches_project_checkout"] is False
        assert package["mismatched_file_count"] == 1

    def test_installed_package_match_does_not_clear_unverified_loaded_modules(self) -> None:
        project = self.make_git_checkout(HEAD_A)
        installed_root = self.tmp_path / "site-packages-unverified"
        relative_path = "runner/runtime_observability.py"
        for root in (project, installed_root):
            target = root / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("loaded = 'same'\n", encoding="utf-8")

        fake_distribution = self.fake_distribution(installed_root, [relative_path])
        loaded_fingerprints = {
            "runner.runtime_observability": {
                "module_name": "runner.runtime_observability",
                "source_path": str(installed_root / relative_path),
                "fingerprint_available": False,
                "captured_at_process_start": True,
            }
        }

        with patch.object(runtime_observability, "LOADED_SOURCE_ROOT", str(installed_root)):
            with patch.object(runtime_observability.importlib.metadata, "distribution", return_value=fake_distribution):
                with patch.object(
                    runtime_observability,
                    "_source_checkout_cleanliness",
                    return_value=self.source_cleanliness(clean=True),
                ):
                    status = get_runtime_version_status(
                        str(project),
                        loaded_runtime_head="",
                        loaded_module_fingerprints=loaded_fingerprints,
                    )

        assert status["runtime_loaded_code_stale"] is None
        assert status["reload_needed_for_verification"] is True
        assert status["reload_awareness_reason"] == "loaded_module_fingerprint_unknown"
        package = status["installed_package_verification"]
        assert package["verification_status"] == "match"
        assert package["matches_project_checkout"] is True

    def test_runtime_healthz_provenance_caches_expensive_runtime_status(self) -> None:
        project = self.make_git_checkout(HEAD_A, branch="healthz-cache")
        runtime_observability._runtime_healthz_provenance_cached.cache_clear()
        status = {
            "loaded_runtime_head": None,
            "project_checkout_head": HEAD_A,
            "runtime_loaded_code_stale": False,
            "reload_needed_for_verification": False,
            "reload_awareness_reason": "installed_package_matches_project_checkout",
            "installed_package_verification": {
                "matches_project_checkout": True,
                "verification_status": "match",
                "project_source_clean": True,
                "source_cleanliness_status": "clean",
            },
        }

        with patch.object(runtime_observability, "get_runtime_version_status", return_value=status) as mocked_status:
            first = runtime_observability.runtime_healthz_provenance(str(project))
            second = runtime_observability.runtime_healthz_provenance(str(project))

        assert mocked_status.call_count == 1
        assert first == second
        assert first is not second
        assert first["installed_package_project_source_clean"] is True
        assert first["installed_package_source_cleanliness_status"] == "clean"

    def test_no_runtime_or_external_mutation_authority_is_exposed(self) -> None:
        project = self.make_git_checkout(HEAD_A)
        source_path = self.make_module_file("loaded = 'same'\n")

        status = get_runtime_version_status(
            str(project),
            loaded_runtime_head=HEAD_A,
            loaded_module_fingerprints=self.module_fingerprint(source_path),
        )

        serialized = json.dumps(status, sort_keys=True).lower()
        for forbidden_phrase in (
            "restart_authorized",
            "reload_authorized",
            "kill_authorized",
            "apply_authorized",
            "git_remote_mutation_authorized",
            "executor_workflow_mutation_authorized",
            "service_lifecycle_mutation_authorized",
        ):
            assert forbidden_phrase not in serialized
        self.assert_no_forbidden_runtime_mutation_fields(status)

        source = (ROOT / "runner" / "runtime_observability.py").read_text(encoding="utf-8")
        for forbidden_source_token in (
            "subprocess",
            "os.system",
            ".fetch(",
            ".pull(",
            ".push(",
            "RunnerStateMutation",
            "service_lifecycle",
        ):
            assert forbidden_source_token not in source

    def test_worktree_cleanliness_is_not_claimed(self) -> None:
        project = self.make_git_checkout(HEAD_A)
        source_path = self.make_module_file("loaded = 'same'\n")

        status = get_runtime_version_status(
            str(project),
            loaded_runtime_head=HEAD_A,
            loaded_module_fingerprints=self.module_fingerprint(source_path),
        )

        verification = status["loaded_module_verification"]
        assert verification["worktree_cleanliness_claimed"] is False
        assert "does not claim full Git worktree cleanliness" in verification["worktree_cleanliness_limitation"]

    def assert_no_forbidden_runtime_mutation_fields(self, value: object) -> None:
        forbidden_exact_keys = {
            "restart",
            "reload",
            "kill",
            "apply",
            "authorized_actions",
            "restart_action",
            "reload_action",
            "kill_action",
            "apply_action",
            "restart_command",
            "reload_command",
            "kill_command",
            "apply_command",
        }
        if isinstance(value, dict):
            for key, nested in value.items():
                assert key not in forbidden_exact_keys
                self.assert_no_forbidden_runtime_mutation_fields(nested)
        elif isinstance(value, list):
            for nested in value:
                self.assert_no_forbidden_runtime_mutation_fields(nested)

    def fake_distribution(self, root: Path, files: list[str]):
        class FakeDistribution:
            version = "0.1.2"

            def __init__(self, root_path: Path, relative_files: list[str]):
                self._root = root_path
                self.files = [Path(item) for item in relative_files]

            def locate_file(self, path: object) -> Path:
                text = str(path)
                return self._root / text if text else self._root

        return FakeDistribution(root, files)

    def source_cleanliness(self, *, clean: bool) -> dict[str, object]:
        return {
            "project_source_clean": clean,
            "source_cleanliness_status": "clean" if clean else "dirty",
            "dirty_entry_count": 0 if clean else 1,
        }


if __name__ == "__main__":
    unittest.main()
