from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from adapters.codex_cli_adapter import CodexCliError
from adapters.opencode_types import OpenCodeCliError
from runner.codex_executor import CodexExecutor
from runner.commander_projections import CommanderProjectionService
from runner.executor_session import (
    CANONICAL_CONTINUATION_ACTIONS,
    CANONICAL_CONTINUATION_CLASSIFICATIONS,
    ExecutorSessionStore,
    build_canonical_continuation_decision,
    classify_executor_session_head_mismatch,
)
from runner.core_orchestrator import WorkflowOrchestrator
from runner.continuation_snapshot import snapshot_from_fact_bundle
from runner.mcp_executor_workflow import MCPExecutorWorkflowManager
from runner.opencode_executor import OpenCodeExecutor
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
            "conversation_id": "conversation-1",
            "resume_supported": True,
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


class _StatusBridge:
    def __init__(self, data: dict[str, Any]):
        self.data = dict(data)

    def get_runner_status(self, project_root: str) -> dict[str, Any]:
        return dict(self.data)


class _SessionStore:
    def __init__(self, status: dict[str, Any]):
        self.status = status
        self.last_fact_bundle: dict[str, Any] | None = None

    def get_status(self) -> dict[str, Any]:
        return self.status

    def get_continuation_preview(self) -> dict[str, Any]:
        return {}

    def get_continuation_decision(
        self,
        *,
        requested_provider: str | None,
        fact_bundle: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.last_fact_bundle = fact_bundle
        return build_canonical_continuation_decision(dict(fact_bundle or {}))

    def get_resume_invocation_preview(
        self,
        *,
        requested_provider: str | None,
        fact_bundle: dict[str, Any] | None = None,
        continuation_decision: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "ok": True,
            "canonical_continuation_decision": continuation_decision,
            "head_mismatch_classification": (continuation_decision or {}).get(
                "head_mismatch_classification",
                {},
            ),
        }


class _RecordingAdapter:
    def __init__(self, error: Exception | None = None):
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def execute_prompt(self, **kwargs: Any) -> Any:
        self.calls.append(dict(kwargs))
        if self.error is not None:
            raise self.error
        return SimpleNamespace()


def canonical_fact_bundle(
    *,
    status: dict[str, Any] | None = None,
    requested_provider: str = "codex",
    selected_provider: str = "codex",
    identity_present: bool = True,
    provider_resume_supported: bool = True,
    resume_invocation_verified: bool = True,
    operation_running: bool | None = False,
    job_status: str | None = "idle",
    latest_run_status: str | None = "completed",
    runner_status: str | None = "VERSION_PASSED",
    current_version_status: str | None = "PASSED",
    worktree_clean: bool | None = True,
) -> dict[str, Any]:
    return {
        "executor_session_status": status if status is not None else session_status(session_head=HEAD_A, current_head=HEAD_A),
        "requested_provider": requested_provider,
        "selected_provider": selected_provider,
        "identity_present": identity_present,
        "provider_resume_supported": provider_resume_supported,
        "resume_invocation_verified": resume_invocation_verified,
        "operation_running": operation_running,
        "job_status": job_status,
        "latest_run_status": latest_run_status,
        "runner_status": runner_status,
        "current_version_status": current_version_status,
        "worktree_clean": worktree_clean,
        "hard_blockers": [],
        "risk_warnings": [],
    }


class ExecutorSessionHeadMismatchTests(unittest.TestCase):
    def make_minimal_web_console_server(self, project_root: str) -> WebConsoleServer:
        server = WebConsoleServer.__new__(WebConsoleServer)
        server.project_root = project_root
        server.plan_file = str(Path(project_root) / ".colameta" / "plan.json")
        server.runner_rel_dir = ".colameta"
        server.operation_lock = threading.Lock()
        server.operation_running = False
        server.operation_name = None
        server.operation_started_at = None
        server.last_operation_result = None
        server.pending_commit_preview = None
        server.job = {"status": "idle"}
        server.bridge = _StatusBridge({
            "runner_status": "VERSION_PASSED",
            "current_version_status": "PASSED",
        })
        server.executor_session_store = _SessionStore(session_status())
        server._latest_run_evidence_for_classification = lambda live_run=None: ("completed", None, {"available": False})
        server._read_worktree_clean_for_status = lambda: True
        server._is_plan_reload_needed = lambda: False
        server._api_remote_git_status = lambda: {}
        server._api_execution_display = lambda: {
            "provider": "codex",
            "provider_display": "codex",
            "model_display": "default",
        }
        server._api_project_registry = lambda: {"projects": [], "project_count": 0}
        server._resolve_current_execution_provider = lambda fallback_provider=None: "codex"
        captured = snapshot_from_fact_bundle(
            project_root,
            canonical_fact_bundle(status=session_status()),
        )
        server._continuation_snapshot_supplier = lambda provider: captured
        return server

    def assert_canonical_shape(self, decision: dict[str, Any]) -> None:
        assert decision["classification"] in CANONICAL_CONTINUATION_CLASSIFICATIONS
        assert decision["recommended_action"] in CANONICAL_CONTINUATION_ACTIONS
        assert decision["decision_source"] == "runner.executor_session.build_canonical_continuation_decision"
        assert isinstance(decision["resume_allowed"], bool)
        assert isinstance(decision["start_new_allowed"], bool)

    def test_cont_01_verified_same_head_can_resume(self) -> None:
        decision = build_canonical_continuation_decision(canonical_fact_bundle())

        self.assert_canonical_shape(decision)
        assert decision["classification"] == "resume_eligible"
        assert decision["recommended_action"] == "resume"
        assert decision["resume_allowed"] is True
        assert decision["start_new_allowed"] is False

    def test_cont_02_completed_idle_stale_session_starts_new(self) -> None:
        decision = build_canonical_continuation_decision(
            canonical_fact_bundle(status=session_status())
        )

        self.assert_canonical_shape(decision)
        assert decision["classification"] == "completed_idle_stale_session"
        assert decision["recommended_action"] == "start_new"
        assert decision["resume_allowed"] is False
        assert decision["start_new_allowed"] is True

    def test_cont_03_active_head_mismatch_requires_human_review(self) -> None:
        decision = build_canonical_continuation_decision(
            canonical_fact_bundle(
                status=session_status(),
                requested_provider="opencode",
                identity_present=False,
                provider_resume_supported=False,
                operation_running=True,
            )
        )

        self.assert_canonical_shape(decision)
        assert decision["classification"] == "active_operation_head_mismatch"
        assert decision["recommended_action"] == "human_review"
        assert decision["resume_allowed"] is False
        assert decision["start_new_allowed"] is False

    def test_active_operation_same_head_still_requires_human_review(self) -> None:
        decision = build_canonical_continuation_decision(
            canonical_fact_bundle(operation_running=True)
        )

        self.assert_canonical_shape(decision)
        assert decision["classification"] == "active_operation_head_mismatch"
        assert decision["recommended_action"] == "human_review"
        assert decision["resume_allowed"] is False
        assert decision["start_new_allowed"] is False

    def test_active_operation_without_session_still_requires_human_review(self) -> None:
        decision = build_canonical_continuation_decision(
            canonical_fact_bundle(
                status={"ok": True, "active": False, "current_head": HEAD_A},
                operation_running=True,
            )
        )

        self.assert_canonical_shape(decision)
        assert decision["classification"] == "active_operation_head_mismatch"
        assert decision["recommended_action"] == "human_review"
        assert decision["resume_allowed"] is False
        assert decision["start_new_allowed"] is False

    def test_cont_04_incomplete_mismatch_requires_evidence_inspection(self) -> None:
        decision = build_canonical_continuation_decision(
            canonical_fact_bundle(
                status=session_status(),
                requested_provider="opencode",
                identity_present=False,
                latest_run_status=None,
                worktree_clean=None,
            )
        )

        self.assert_canonical_shape(decision)
        assert decision["classification"] == "head_evidence_incomplete"
        assert decision["recommended_action"] == "inspect_evidence"
        assert decision["resume_allowed"] is False
        assert decision["start_new_allowed"] is False

    def test_cont_05_start_new_reasons_are_exact(self) -> None:
        cases = {
            "no_session": (
                canonical_fact_bundle(status={"ok": True, "active": False, "current_head": HEAD_A}),
                "no_session",
                "no_session_manifest",
            ),
            "provider_mismatch": (
                canonical_fact_bundle(requested_provider="opencode"),
                "provider_or_identity_mismatch",
                "provider_mismatch",
            ),
            "identity_missing": (
                canonical_fact_bundle(identity_present=False),
                "provider_or_identity_mismatch",
                "resume_identity_missing",
            ),
            "resume_unsupported": (
                canonical_fact_bundle(provider_resume_supported=False),
                "resume_unsupported",
                "provider_resume_not_supported",
            ),
        }
        for name, (facts, expected_classification, expected_reason) in cases.items():
            with self.subTest(name=name):
                decision = build_canonical_continuation_decision(facts)
                self.assert_canonical_shape(decision)
                assert decision["classification"] == expected_classification
                assert decision["recommended_action"] == "start_new"
                assert decision["reason"] == expected_reason
                assert decision["resume_allowed"] is False
                assert decision["start_new_allowed"] is True

    def test_cont_01_through_05_are_consistent_across_all_continuation_surfaces(self) -> None:
        cases = {
            "CONT-01": canonical_fact_bundle(),
            "CONT-02": canonical_fact_bundle(status=session_status()),
            "CONT-03": canonical_fact_bundle(
                status=session_status(),
                operation_running=True,
            ),
            "CONT-04": canonical_fact_bundle(
                status=session_status(),
                latest_run_status=None,
                worktree_clean=None,
            ),
            "CONT-05-no-session": canonical_fact_bundle(
                status={"ok": True, "active": False, "current_head": HEAD_A},
            ),
            "CONT-05-provider-mismatch": canonical_fact_bundle(
                requested_provider="opencode",
            ),
            "CONT-05-identity-missing": canonical_fact_bundle(
                identity_present=False,
            ),
            "CONT-05-resume-unsupported": canonical_fact_bundle(
                provider_resume_supported=False,
            ),
        }
        compared_fields = (
            "classification",
            "recommended_action",
            "reason",
            "resume_allowed",
            "start_new_allowed",
        )

        with tempfile.TemporaryDirectory(prefix="colameta-continuation-surfaces-") as tmp:
            for name, facts in cases.items():
                with self.subTest(case=name):
                    provider = str(facts.get("requested_provider") or "codex")
                    captured = snapshot_from_fact_bundle(tmp, facts)
                    session_projection = captured.project(provider)
                    expected = session_projection["canonical_continuation_decision"]

                    orchestrator = WorkflowOrchestrator(
                        tmp,
                        continuation_snapshot=captured,
                    )
                    analyze = orchestrator.build_fact_snapshot(
                        provider=provider,
                        include_reports=False,
                    )
                    thin = orchestrator._thin_loop_executor_session_guidance(
                        provider=provider,
                        continuation_snapshot=captured,
                    )

                    web_server = WebConsoleServer.__new__(WebConsoleServer)
                    web_server.project_root = tmp
                    web_data: dict[str, Any] = {}
                    web_server._apply_executor_session_head_mismatch_classification(
                        web_data,
                        requested_provider=provider,
                        continuation_snapshot=captured,
                    )

                    invocation = session_projection["resume_invocation_preview"]
                    handled, commander = (
                        CommanderProjectionService.project_cc_s01_contract_value(
                            "canonical_continuation_decision",
                            expected,
                        )
                    )
                    assert handled is True

                    surfaces = {
                        "session": expected,
                        "analyze": analyze._executor_raw[
                            "canonical_continuation_decision"
                        ],
                        "thin_loop": thin["canonical_continuation_decision"],
                        "web": web_data["executor_continuation_decision"],
                        "invocation": invocation[
                            "canonical_continuation_decision"
                        ],
                        "commander": commander,
                    }
                    for surface_name, decision in surfaces.items():
                        with self.subTest(case=name, surface=surface_name):
                            assert {
                                field: decision.get(field)
                                for field in compared_fields
                            } == {
                                field: expected.get(field)
                                for field in compared_fields
                            }
                            assert decision.get("decision_source") == expected.get(
                                "decision_source"
                            )

    def test_store_accepts_injected_fact_bundle(self) -> None:
        with tempfile.TemporaryDirectory(prefix="colameta-canonical-store-") as tmp:
            store = ExecutorSessionStore(tmp)
            facts = canonical_fact_bundle(status=session_status())

            decision = store.get_continuation_decision(
                requested_provider="codex",
                fact_bundle=facts,
            )

        assert decision["classification"] == "completed_idle_stale_session"
        assert decision["recommended_action"] == "start_new"
        assert decision["head_mismatch_classification"]["status"] == "completed_idle_stale_session"

    def test_invocation_preview_cannot_downgrade_human_review_to_start_new(self) -> None:
        with tempfile.TemporaryDirectory(prefix="colameta-canonical-invocation-") as tmp:
            store = ExecutorSessionStore(tmp)
            facts = canonical_fact_bundle(
                status=session_status(),
                operation_running=True,
            )
            decision = store.get_continuation_decision(
                requested_provider="codex",
                fact_bundle=facts,
            )
            invocation = store.get_resume_invocation_preview(
                requested_provider="codex",
                fact_bundle=facts,
                continuation_decision=decision,
            )

        assert decision["recommended_action"] == "human_review"
        assert invocation["canonical_continuation_decision"] is decision
        assert invocation["should_resume"] is False
        assert invocation["requires_manual_confirmation"] is True
        assert "人工判断" in invocation["next_action_hint"]
        assert "使用新会话" not in invocation["next_action_hint"]

    def test_analyze_projection_exposes_complete_canonical_decision(self) -> None:
        with tempfile.TemporaryDirectory(prefix="colameta-canonical-analyze-") as tmp:
            orchestrator = WorkflowOrchestrator(tmp)
            snapshot = orchestrator.build_fact_snapshot(
                provider="codex",
                include_reports=False,
                continuation_fact_bundle=canonical_fact_bundle(
                    status={"ok": True, "active": False, "current_head": HEAD_A}
                ),
            )
            output = orchestrator._build_analyze_core_output(snapshot)

        decision = snapshot._executor_raw["canonical_continuation_decision"]
        assert decision["classification"] == "no_session"
        assert decision["recommended_action"] == "start_new"
        assert decision["resume_allowed"] is False
        assert decision["start_new_allowed"] is True
        assert output.result["executor"]["canonical_continuation_decision"] is decision

    def test_project_snapshot_uses_injected_fact_bundle_for_its_single_decision(self) -> None:
        with tempfile.TemporaryDirectory(prefix="colameta-canonical-snapshot-") as tmp:
            orchestrator = WorkflowOrchestrator(tmp)
            facts = canonical_fact_bundle(operation_running=True)
            snapshot = orchestrator.build_fact_snapshot(
                provider="codex",
                include_reports=False,
                continuation_fact_bundle=facts,
            )

        decision = snapshot._executor_raw["canonical_continuation_decision"]
        assert decision["classification"] == "active_operation_head_mismatch"
        assert decision["recommended_action"] == "human_review"
        assert decision["resume_allowed"] is False
        assert decision["start_new_allowed"] is False

    def test_direct_executors_block_all_adapter_calls_when_canonical_action_is_human_review(self) -> None:
        blocked = build_canonical_continuation_decision(
            canonical_fact_bundle(operation_running=True)
        )
        plan = SimpleNamespace(project_root="/tmp/project", logs_dir="/tmp/logs")

        codex_adapter = _RecordingAdapter()
        codex = CodexExecutor.__new__(CodexExecutor)
        codex.adapter = codex_adapter
        codex._get_codex_auto_resume_candidate = lambda project_root: {
            "enabled": False,
            "conversation_id": None,
            "decision": blocked,
        }
        with self.assertRaisesRegex(CodexCliError, "forbids starting"):
            codex._execute_codex_with_auto_resume(
                plan=plan,
                version="v1",
                attempt=1,
                prompt="bounded",
                prompt_file="prompt.md",
                summary_file="summary.md",
                execution_mode="normal",
            )
        assert codex_adapter.calls == []

        opencode_adapter = _RecordingAdapter()
        opencode = OpenCodeExecutor.__new__(OpenCodeExecutor)
        opencode._get_opencode_auto_resume_candidate = lambda project_root: {
            "enabled": False,
            "resume_session_id": None,
            "decision": blocked,
        }
        with self.assertRaisesRegex(OpenCodeCliError, "forbids starting"):
            opencode._execute_opencode_with_auto_resume(
                adapter=opencode_adapter,
                plan=plan,
                version="v1",
                attempt=1,
                prompt="bounded",
                prompt_file="prompt.md",
                summary_file="summary.md",
                execution_mode="normal",
            )
        assert opencode_adapter.calls == []

    def test_explicit_session_modes_cannot_downgrade_to_the_other_action(self) -> None:
        start_new = build_canonical_continuation_decision(
            canonical_fact_bundle(status={"ok": True, "active": False, "current_head": HEAD_A})
        )
        plan = SimpleNamespace(project_root="/tmp/project", logs_dir="/tmp/logs")

        codex_adapter = _RecordingAdapter()
        codex = CodexExecutor.__new__(CodexExecutor)
        codex.adapter = codex_adapter
        codex._get_codex_auto_resume_candidate = lambda project_root: {
            "enabled": False,
            "conversation_id": None,
            "decision": start_new,
        }
        with self.assertRaisesRegex(CodexCliError, "forbids resuming"):
            codex._execute_codex_with_auto_resume(
                plan=plan,
                version="v1",
                attempt=1,
                prompt="bounded",
                prompt_file="prompt.md",
                summary_file="summary.md",
                execution_mode="normal",
                executor_session_mode="resume_existing",
            )
        assert codex_adapter.calls == []

        resume = build_canonical_continuation_decision(canonical_fact_bundle())
        opencode_adapter = _RecordingAdapter()
        opencode = OpenCodeExecutor.__new__(OpenCodeExecutor)
        opencode._get_opencode_auto_resume_candidate = lambda project_root: {
            "enabled": True,
            "resume_session_id": "session-1",
            "decision": resume,
        }
        with self.assertRaisesRegex(OpenCodeCliError, "forbids starting"):
            opencode._execute_opencode_with_auto_resume(
                adapter=opencode_adapter,
                plan=plan,
                version="v1",
                attempt=1,
                prompt="bounded",
                prompt_file="prompt.md",
                summary_file="summary.md",
                execution_mode="normal",
                executor_session_mode="start_new",
            )
        assert opencode_adapter.calls == []

    def test_mcp_affinity_and_action_gate_fail_closed_for_human_review(self) -> None:
        manager = MCPExecutorWorkflowManager.__new__(MCPExecutorWorkflowManager)
        blocked = build_canonical_continuation_decision(
            canonical_fact_bundle(operation_running=True)
        )
        compact = manager._compact_continuation_decision(blocked)

        for mode in ("auto", "resume_existing", "start_new"):
            with self.subTest(mode=mode):
                gate = manager._continuation_action_gate(
                    compact,
                    requested_session_mode=mode,
                )
                affinity = manager._build_executor_session_affinity(
                    provider="codex",
                    session_record={"provider": "codex", "version": "v1"},
                    continuation_decision=compact,
                    requested_session_mode=mode,
                )
                assert gate["allowed"] is False
                assert affinity["action_blocked"] is True
                assert affinity["will_resume_session"] is False
                assert affinity["will_start_new_session"] is False

        assert manager._allowed_session_modes(compact) == []

    def test_direct_executor_block_matrix_never_reaches_adapter(self) -> None:
        blocked_decisions = {
            "human_review": build_canonical_continuation_decision(
                canonical_fact_bundle(operation_running=True)
            ),
            "inspect_evidence": build_canonical_continuation_decision(
                canonical_fact_bundle(
                    latest_run_status=None,
                    worktree_clean=None,
                )
            ),
        }
        plan = SimpleNamespace(project_root="/tmp/project", logs_dir="/tmp/logs")

        for provider in ("codex", "opencode"):
            for classification, decision in blocked_decisions.items():
                for mode in ("auto", "resume_existing", "start_new"):
                    with self.subTest(provider=provider, classification=classification, mode=mode):
                        adapter = _RecordingAdapter()
                        candidate = {
                            "enabled": False,
                            "decision": decision,
                            "conversation_id": None,
                            "resume_session_id": None,
                        }
                        if provider == "codex":
                            executor = CodexExecutor.__new__(CodexExecutor)
                            executor.adapter = adapter
                            executor._get_codex_auto_resume_candidate = lambda project_root, value=candidate: value
                            call = lambda: executor._execute_codex_with_auto_resume(
                                plan=plan,
                                version="v1",
                                attempt=1,
                                prompt="bounded",
                                prompt_file="prompt.md",
                                summary_file="summary.md",
                                execution_mode="normal",
                                executor_session_mode=mode,
                            )
                            expected_error = CodexCliError
                        else:
                            executor = OpenCodeExecutor.__new__(OpenCodeExecutor)
                            executor._get_opencode_auto_resume_candidate = lambda project_root, value=candidate: value
                            call = lambda: executor._execute_opencode_with_auto_resume(
                                adapter=adapter,
                                plan=plan,
                                version="v1",
                                attempt=1,
                                prompt="bounded",
                                prompt_file="prompt.md",
                                summary_file="summary.md",
                                execution_mode="normal",
                                executor_session_mode=mode,
                            )
                            expected_error = OpenCodeCliError
                        with self.assertRaises(expected_error):
                            call()
                        assert adapter.calls == []

    def test_codex_resume_failure_cannot_fallback_when_start_new_is_forbidden(self) -> None:
        decision = build_canonical_continuation_decision(canonical_fact_bundle())
        adapter = _RecordingAdapter(CodexCliError("resume failed"))
        executor = CodexExecutor.__new__(CodexExecutor)
        executor.adapter = adapter
        executor._get_codex_auto_resume_candidate = lambda project_root: {
            "enabled": True,
            "conversation_id": "conversation-1",
            "decision": decision,
        }

        with self.assertRaisesRegex(CodexCliError, "forbids fallback"):
            executor._execute_codex_with_auto_resume(
                plan=SimpleNamespace(project_root="/tmp/project", logs_dir="/tmp/logs"),
                version="v1",
                attempt=1,
                prompt="bounded",
                prompt_file="prompt.md",
                summary_file="summary.md",
                execution_mode="normal",
            )

        assert len(adapter.calls) == 1
        assert adapter.calls[0]["resume_conversation_id"] == "conversation-1"

    def test_mcp_run_once_and_bounded_block_before_claim(self) -> None:
        manager = MCPExecutorWorkflowManager.__new__(MCPExecutorWorkflowManager)
        manager._service = SimpleNamespace(
            preflight=lambda **kwargs: {
                "preflight_blocked": False,
                "blocking_git_status_short": [],
                "executor_inventory": None,
            }
        )
        manager._read_preview_claim_record = lambda preview_id: None
        manager._validate_preview_artifact = lambda *args, **kwargs: {"ok": True}
        manager._compare_artifact_with_preflight = lambda *args, **kwargs: {"ok": True}
        manager._compare_bounded_artifact_with_preflight = lambda *args, **kwargs: {"ok": True}
        manager._preview_guard_error = lambda *args, **kwargs: None

        calls = {"claim": 0, "worker": 0}

        def forbidden_claim(**kwargs: Any) -> dict[str, Any]:
            calls["claim"] += 1
            raise AssertionError("claim must not be reached")

        manager._claim_preview_artifact = forbidden_claim
        manager._start_run_once_background_worker = lambda **kwargs: calls.__setitem__("worker", calls["worker"] + 1)

        with tempfile.TemporaryDirectory(prefix="colameta-mcp-continuation-block-") as tmp:
            manager.project_root = tmp
            captured = snapshot_from_fact_bundle(tmp, canonical_fact_bundle(operation_running=True))
            with patch(
                "runner.mcp_executor_workflow.collect_continuation_snapshot",
                return_value=captured,
            ):
                manager._read_preview_artifact = lambda preview_id: {
                    "artifact_kind": "run_once",
                    "executor_session_continuation_facts": {
                        "allowed_session_modes": ["auto", "resume_existing", "start_new"],
                    },
                }
                run_once = manager._run_once({
                    "preview_id": "preview-1",
                    "provider": "codex",
                    "executor_session_mode": "auto",
                })

                manager._read_preview_artifact = lambda preview_id: {
                    "artifact_kind": "run_bounded",
                    "max_iterations": 1,
                    "trusted_mode": False,
                    "allow_fix": False,
                    "allow_commit": False,
                }
                run_bounded = manager._run_bounded({
                    "preview_id": "preview-2",
                    "provider": "codex",
                })

        assert run_once["error_code"] == "CONTINUATION_ACTION_NOT_ALLOWED"
        assert run_once["status"] == "blocked"
        assert "CONTINUATION_ACTION_NOT_ALLOWED" in run_bounded["blockers"]
        assert run_bounded["status"] == "blocked"
        assert calls == {"claim": 0, "worker": 0}

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

            captured = snapshot_from_fact_bundle(
                str(Path(tmp)),
                canonical_fact_bundle(status=session_status()),
            )
            classification = server._apply_executor_session_head_mismatch_classification(
                data,
                continuation_snapshot=captured,
            )

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
        assert "历史会话残留" in display["text"]
        assert "运行中" not in display["text"]

    def test_v1_status_payload_includes_executor_session_display(self) -> None:
        with tempfile.TemporaryDirectory(prefix="colameta-head-mismatch-v1-payload-") as tmp:
            server = self.make_minimal_web_console_server(str(Path(tmp)))

            payload = server._api_status()

        display = payload["executor_session_display"]
        assert display["state"] == "stale_session"
        assert display["head_mismatch_classification_status"] == "completed_idle_stale_session"
        assert "历史会话残留" in display["text"]
        decision = payload["executor_continuation_decision"]
        assert decision["classification"] == "completed_idle_stale_session"
        assert decision["recommended_action"] == "start_new"
        assert payload["executor_session_status"]["canonical_continuation_decision"] is decision
        assert payload["executor_continuation_preview"]["canonical_continuation_decision"] is decision
        assert payload["executor_resume_invocation_preview"]["canonical_continuation_decision"] is decision

    def test_v2_status_payload_includes_executor_session_display(self) -> None:
        from runner import web_console

        original = web_console.WorkflowOrchestrator

        class StubWorkflowOrchestrator:
            def __init__(self, project_root: str, **kwargs: Any):
                self.project_root = project_root
                self.continuation_snapshot = kwargs.get("continuation_snapshot")

            def handle(self, workflow: str, params: dict[str, Any]) -> dict[str, Any]:
                if workflow == "thin_governed_loop_preview":
                    return {
                        "ok": True,
                        "workflow": "thin_governed_loop_preview",
                        "status": "succeeded",
                        "risk_level": "info",
                        "requires_confirmation": False,
                        "changed_files": [],
                        "preview_ids": [],
                        "result": {
                            "read_only": True,
                            "side_effects": False,
                            "input_mode": "example",
                            "codex_execution_packet": {
                                "executor_session_recovery": {
                                    "continuation_snapshot": self.continuation_snapshot.public_view("codex"),
                                }
                            },
                            "thin_loop": {
                                "thin_loop_status": "thin_governed_loop_passed",
                                "blockers": [],
                            },
                            "forbidden_authority_outputs": {
                                "delivery_state_accepted": False,
                                "review_decision_created": False,
                                "gate_event_emitted": False,
                                "executor_dispatch_authorized": False,
                            },
                        },
                    }
                return {
                    "ok": True,
                    "runner_status": "VERSION_PASSED",
                    "current_version_status": "PASSED",
                    "fact_snapshot": {
                        "project_identity": {
                            "project_name": "demo-project",
                            "project_root": self.project_root,
                        },
                        "executor": {
                            "continuation_snapshot": self.continuation_snapshot.public_view("codex"),
                        },
                    },
                }

        web_console.WorkflowOrchestrator = StubWorkflowOrchestrator
        self.addCleanup(lambda: setattr(web_console, "WorkflowOrchestrator", original))

        with tempfile.TemporaryDirectory(prefix="colameta-head-mismatch-v2-payload-") as tmp:
            server = self.make_minimal_web_console_server(str(Path(tmp)))
            original_supplier = server._continuation_snapshot_supplier
            snapshot_calls: list[str | None] = []

            def one_snapshot(provider: str | None):
                snapshot_calls.append(provider)
                return original_supplier(provider)

            server._continuation_snapshot_supplier = one_snapshot
            server._api_v2_live_run = lambda continuation_snapshot=None: {"available": False}
            server._enrich_latest_report_identity = lambda result, **kwargs: None
            server._build_plan_version_list_for_v2 = lambda: []

            payload = server._api_v2_status()

        display = payload["executor_session_display"]
        assert display["state"] == "stale_session"
        assert display["head_mismatch_classification_status"] == "completed_idle_stale_session"
        assert "历史会话残留" in display["text"]
        assert snapshot_calls == ["codex"]
        snapshot_id = payload["continuation_snapshot"]["snapshot_id"]
        assert payload["fact_snapshot"]["executor"]["continuation_snapshot"]["snapshot_id"] == snapshot_id
        thin_snapshot = payload["thin_governed_loop_preview"]["result"]["codex_execution_packet"]["executor_session_recovery"]["continuation_snapshot"]
        assert thin_snapshot["snapshot_id"] == snapshot_id
        assert payload["thin_governed_loop_preview"]["result"]["read_only"] is True
        assert payload["thin_governed_loop_preview"]["result"]["forbidden_authority_outputs"]["delivery_state_accepted"] is False


if __name__ == "__main__":
    unittest.main()
