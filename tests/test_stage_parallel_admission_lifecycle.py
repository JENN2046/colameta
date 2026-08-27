from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from runner.mcp_executor_workflow import MCPExecutorWorkflowManager
from runner.mcp_stage_parallel_executor_group import MCPStageParallelExecutorGroupManager
from runner.mcp_stage_parallel_shard_inputs import MCPStageParallelShardInputManager
from runner.mcp_stage_parallel_worktrees import MCPStageParallelWorktreeManager
from tests.test_stage_parallel_executor_group import (
    _FakeAttemptBridge,
    _init_managed_repo,
    _secure_test_directories,
    _task_authorizations,
)
from runner.work_item_governance.ids import new_stable_id


def _intents() -> list[dict[str, object]]:
    return [
        {"task_id": "one", "title": "One", "allowed_files": ["README.md"]},
        {"task_id": "two", "title": "Two", "allowed_files": ["SECOND.md"]},
    ]


def _prepare_shards(project: Path, intents: list[dict[str, object]]) -> None:
    if any("SECOND.md" in item["allowed_files"] for item in intents):
        (project / "SECOND.md").write_text("second\n", encoding="utf-8")
        subprocess.run(["git", "add", "SECOND.md"], cwd=project, check=True)
        subprocess.run(
            [
                "git", "-c", "user.name=Test", "-c", "user.email=test@example.com",
                "commit", "-m", "second fixture", "-q",
            ],
            cwd=project,
            check=True,
        )
    worktrees = MCPStageParallelWorktreeManager(str(project))
    preview = worktrees.handle(
        "preview", {"stage_id": "stage_parallel_dev", "task_intents": intents}
    )
    applied = worktrees.handle("apply", {"preview_id": preview["preview_id"]})
    assert applied["ok"] is True
    inputs = MCPStageParallelShardInputManager(str(project))
    preview = inputs.handle(
        "preview",
        {
            "stage_id": "stage_parallel_dev",
            "task_intents": intents,
            "provider": "codex",
        },
    )
    applied_inputs = inputs.handle("apply", {"preview_id": preview["preview_id"]})
    assert applied_inputs["ok"] is True
    roots = [project / ".colameta"]
    roots.extend(Path(item["worktree_path"]) for item in applied["created_worktrees"])
    _secure_test_directories(*roots)


def _group_preview(project: Path, bridge, intents):
    task_ids = [str(item["task_id"]) for item in intents]
    authorizations = _task_authorizations(task_ids)
    manager = MCPStageParallelExecutorGroupManager(
        str(project), attempt_bridge=bridge
    )
    preview = manager.handle(
        "preview",
        {
            "stage_id": "stage_parallel_dev",
            "task_intents": intents,
            "provider": "codex",
            "task_authorizations": authorizations,
        },
    )
    assert preview["ok"] is True, preview
    return manager, preview, authorizations


def _advance_until(manager, preview_id, authorizations, target_state):
    results = []
    for _ in range(32):
        result = manager.handle(
            "apply",
            {"preview_id": preview_id, "task_authorizations": authorizations},
        )
        results.append(result)
        assert result["ok"] is True, result
        if result["lifecycle"]["lifecycle_state"] == target_state:
            return results
    raise AssertionError(f"lifecycle did not reach {target_state}")


def test_two_task_lifecycle_prepares_exactly_once_without_provider_start(tmp_path) -> None:
    project = _init_managed_repo(tmp_path)
    intents = _intents()
    _prepare_shards(project, intents)
    bridge = _FakeAttemptBridge(["one", "two"])
    manager, preview, authorizations = _group_preview(project, bridge, intents)

    prior_apply_calls = 0
    prior_resolve_calls = 0
    results = []
    for _ in range(32):
        result = manager.handle(
            "apply",
            {
                "preview_id": preview["preview_id"],
                "task_authorizations": authorizations,
            },
        )
        assert result["ok"] is True, result
        assert bridge.apply_calls - prior_apply_calls <= 1
        assert bridge.resolve_calls - prior_resolve_calls <= 1
        prior_apply_calls = bridge.apply_calls
        prior_resolve_calls = bridge.resolve_calls
        results.append(result)
        if result["lifecycle"]["status"] == "PREPARED_FOR_EXECUTION":
            break
    else:
        raise AssertionError("lifecycle did not prepare")

    assert bridge.apply_calls == 0
    assert all(item["provider_started_count"] == 0 for item in results)
    shard_root = project / ".colameta" / "runtime" / "parallel-worktrees"
    reservations = sorted(shard_root.glob("*/*/.colameta/runtime/executor-sessions/*/stage-shard-admission-reservation.json"))
    admissions = sorted(shard_root.glob("*/*/.colameta/runtime/executor-sessions/*/admission.json"))
    bindings = sorted(shard_root.glob("*/*/.colameta/runtime/executor-sessions/*/execution-binding.json"))
    executor_previews = sorted(shard_root.glob("*/*/.colameta/runtime/executor-workflow-previews/*.json"))
    assert len(reservations) == len(admissions) == len(executor_previews) == 2
    assert bindings == []
    authority_ids = {path.parent.name for path in reservations}
    assert len(authority_ids) == 2
    public = json.dumps(results[-1]["lifecycle"], sort_keys=True)
    assert all(authority_id not in public for authority_id in authority_ids)
    assert '"private_authority_material_exposed": false' in public


def test_duplicate_governed_target_fails_before_any_attempt_write(tmp_path) -> None:
    project = _init_managed_repo(tmp_path)
    intents = _intents()
    _prepare_shards(project, intents)
    bridge = _FakeAttemptBridge(["one", "two"])
    bridge.targets["two"] = dict(bridge.targets["one"])
    manager, preview, authorizations = _group_preview(project, bridge, intents)

    first = manager.handle(
        "apply", {"preview_id": preview["preview_id"], "task_authorizations": authorizations}
    )
    second = manager.handle(
        "apply", {"preview_id": preview["preview_id"], "task_authorizations": authorizations}
    )

    assert first["ok"] is True
    assert second["ok"] is False
    assert second["error_code"] == "DUPLICATE_GOVERNED_TARGET"
    assert bridge.apply_calls == 0


@pytest.mark.parametrize(
    ("mutate", "error_code"),
    [
        (lambda values: values[:-1], "TASK_AUTHORIZATION_COVERAGE_MISMATCH"),
        (
            lambda values: values + [{"task_id": "extra", "grant_id": new_stable_id("preview")}],
            "TASK_AUTHORIZATION_COVERAGE_MISMATCH",
        ),
        (
            lambda values: values + [dict(values[0])],
            "TASK_AUTHORIZATION_DUPLICATE_TASK",
        ),
        (
            lambda values: [values[0], {"task_id": values[1]["task_id"], "grant_id": values[0]["grant_id"]}],
            "TASK_AUTHORIZATION_DUPLICATE_GRANT",
        ),
    ],
)
def test_b0_rejects_inexact_grant_sets_before_attempt_write(
    tmp_path, mutate, error_code
) -> None:
    project = _init_managed_repo(tmp_path)
    intents = _intents()
    _prepare_shards(project, intents)
    bridge = _FakeAttemptBridge(["one", "two"])
    authorizations = _task_authorizations(["one", "two"])
    manager = MCPStageParallelExecutorGroupManager(str(project), attempt_bridge=bridge)

    result = manager.handle(
        "preview",
        {
            "stage_id": "stage_parallel_dev",
            "task_intents": intents,
            "provider": "codex",
            "task_authorizations": mutate(authorizations),
        },
    )

    assert result["ok"] is False
    assert result["error_code"] == error_code
    assert bridge.apply_calls == 0


def test_lost_executor_preview_return_reconciles_one_durable_preview(
    tmp_path, monkeypatch
) -> None:
    project = _init_managed_repo(tmp_path)
    intents = [_intents()[0]]
    _prepare_shards(project, intents)
    bridge = _FakeAttemptBridge(["one"])
    manager, preview, authorizations = _group_preview(project, bridge, intents)
    _advance_until(
        manager, preview["preview_id"], authorizations,
        "B4_ALL_FRESH_AUTHORITIES_READY",
    )

    original = MCPExecutorWorkflowManager.handle
    lost_once = {"value": False}

    def lose_return(self, action, params):
        result = original(self, action, params)
        if action == "run_once_preview" and result.get("ok") and not lost_once["value"]:
            lost_once["value"] = True
            return {"ok": False, "error_code": "SIMULATED_LOST_RETURN"}
        return result

    monkeypatch.setattr(MCPExecutorWorkflowManager, "handle", lose_return)
    failed = manager.handle(
        "apply", {"preview_id": preview["preview_id"], "task_authorizations": authorizations}
    )
    assert failed["ok"] is False
    assert failed["error_code"] == "SIMULATED_LOST_RETURN"
    shard_root = project / ".colameta" / "runtime" / "parallel-worktrees"
    preview_files = sorted(shard_root.glob("*/*/.colameta/runtime/executor-workflow-previews/*.json"))
    assert len(preview_files) == 1

    monkeypatch.setattr(MCPExecutorWorkflowManager, "handle", original)
    retried = manager.handle(
        "apply", {"preview_id": preview["preview_id"], "task_authorizations": authorizations}
    )
    assert retried["ok"] is True, retried
    assert retried["lifecycle"]["status"] == "admission_in_progress"
    completed = _advance_until(
        manager,
        preview["preview_id"],
        authorizations,
        "PREPARED_FOR_EXECUTION",
    )[-1]
    assert completed["lifecycle"]["status"] == "PREPARED_FOR_EXECUTION"
    assert len(list(shard_root.glob("*/*/.colameta/runtime/executor-workflow-previews/*.json"))) == 1


def test_existing_executor_preview_mismatch_fails_closed(tmp_path) -> None:
    project = _init_managed_repo(tmp_path)
    intents = [_intents()[0]]
    _prepare_shards(project, intents)
    bridge = _FakeAttemptBridge(["one"])
    manager, preview, authorizations = _group_preview(project, bridge, intents)
    _advance_until(
        manager,
        preview["preview_id"],
        authorizations,
        "B4_ALL_FRESH_AUTHORITIES_READY",
    )
    created = manager.handle(
        "apply", {"preview_id": preview["preview_id"], "task_authorizations": authorizations}
    )
    assert created["ok"] is True
    shard_root = project / ".colameta" / "runtime" / "parallel-worktrees"
    artifact_path = next(
        shard_root.glob("*/*/.colameta/runtime/executor-workflow-previews/*.json")
    )
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    artifact["expected_execution_branch"] = "substituted"
    artifact_path.write_text(json.dumps(artifact), encoding="utf-8")

    rejected = manager.handle(
        "apply", {"preview_id": preview["preview_id"], "task_authorizations": authorizations}
    )

    assert rejected["ok"] is False
    assert rejected["error_code"] == "STAGE_EXECUTOR_PREVIEW_RECONCILIATION_MISMATCH"


def test_progress_barrier_tamper_fails_closed(tmp_path) -> None:
    project = _init_managed_repo(tmp_path)
    intents = [_intents()[0]]
    _prepare_shards(project, intents)
    bridge = _FakeAttemptBridge(["one"])
    manager, preview, authorizations = _group_preview(project, bridge, intents)
    group_id = preview["parallel_group_id"]
    key = hashlib.sha256(group_id.encode("utf-8")).hexdigest()
    progress_file = (
        project / ".colameta" / "runtime" / "stage-parallel-admissions"
        / key / "progress.json"
    )
    progress = json.loads(progress_file.read_text(encoding="utf-8"))
    progress["state"] = "B4_ALL_FRESH_AUTHORITIES_READY"
    progress_file.write_text(json.dumps(progress), encoding="utf-8")
    progress_file.chmod(0o600)

    result = manager.handle(
        "apply", {"preview_id": preview["preview_id"], "task_authorizations": authorizations}
    )
    assert result["ok"] is False
    assert result["error_code"] == "STAGE_ADMISSION_PROGRESS_INTEGRITY_MISMATCH"


def test_nonlexicographic_task_order_survives_canonical_json_sorting(tmp_path) -> None:
    project = _init_managed_repo(tmp_path)
    intents = [
        {"task_id": "z-task", "title": "Z", "allowed_files": ["README.md"]},
        {"task_id": "a-task", "title": "A", "allowed_files": ["SECOND.md"]},
    ]
    _prepare_shards(project, intents)
    bridge = _FakeAttemptBridge(["z-task", "a-task"])
    manager, preview, _authorizations = _group_preview(project, bridge, intents)

    status = manager.handle("status", {"preview_id": preview["preview_id"]})

    assert status["ok"] is True, status
    assert [item["task_id"] for item in status["lifecycle"]["tasks"]] == [
        "z-task", "a-task",
    ]


def test_reminted_wrong_target_grant_is_rejected_before_attempt_mutation(tmp_path) -> None:
    project = _init_managed_repo(tmp_path)
    intents = [_intents()[0]]
    _prepare_shards(project, intents)
    bridge = _FakeAttemptBridge(["one"])
    manager, preview, authorizations = _group_preview(project, bridge, intents)
    b0 = manager.handle(
        "apply", {"preview_id": preview["preview_id"], "task_authorizations": authorizations}
    )
    assert b0["lifecycle"]["lifecycle_state"] == "B0_ALL_TASK_GRANTS_VALID"
    reminted = _task_authorizations(["one"])
    original_inspect = bridge.inspect_task_grant

    def wrong_target(grant_id, *, expected_execution_context):
        result = original_inspect(
            grant_id, expected_execution_context=expected_execution_context
        )
        return {**result, "work_item_id": "wi_00000000-0000-7000-8000-000000000000"}

    bridge.inspect_task_grant = wrong_target
    rejected = manager.handle(
        "apply", {"preview_id": preview["preview_id"], "task_authorizations": reminted}
    )

    assert rejected["ok"] is False
    assert rejected["error_code"] == "STAGE_ATTEMPT_GRANT_TARGET_MISMATCH"
    assert bridge.apply_calls == 0


def test_same_target_grant_remint_requires_read_call_before_one_mutation(tmp_path) -> None:
    project = _init_managed_repo(tmp_path)
    intents = [_intents()[0]]
    _prepare_shards(project, intents)
    bridge = _FakeAttemptBridge(["one"])
    manager, preview, authorizations = _group_preview(project, bridge, intents)
    manager.handle(
        "apply", {"preview_id": preview["preview_id"], "task_authorizations": authorizations}
    )
    reminted = _task_authorizations(["one"])

    inspected = manager.handle(
        "apply", {"preview_id": preview["preview_id"], "task_authorizations": reminted}
    )
    admitted = manager.handle(
        "apply", {"preview_id": preview["preview_id"], "task_authorizations": reminted}
    )

    assert inspected["ok"] is True
    assert inspected["lifecycle"]["lifecycle_state"] == "B0_ALL_TASK_GRANTS_VALID"
    assert admitted["ok"] is True
    assert admitted["lifecycle"]["lifecycle_state"] == "B1_ALL_ATTEMPTS_ADMITTED"
    assert bridge.apply_calls == 0


def test_missing_attempt_returns_authoritative_next_action_without_stage_write(
    tmp_path,
) -> None:
    project = _init_managed_repo(tmp_path)
    intents = [_intents()[0]]
    _prepare_shards(project, intents)
    bridge = _FakeAttemptBridge(["one"], admitted=False)
    manager, preview, authorizations = _group_preview(project, bridge, intents)
    b0 = manager.handle(
        "apply", {"preview_id": preview["preview_id"], "task_authorizations": authorizations}
    )
    assert b0["ok"] is True

    required = manager.handle(
        "apply", {"preview_id": preview["preview_id"], "task_authorizations": authorizations}
    )

    assert required["ok"] is True
    assert required["lifecycle"]["lifecycle_state"] == "B0_ALL_TASK_GRANTS_VALID"
    assert required["lifecycle"]["next_authoritative_action"] == {
        "task_id": "one",
        "governance_admission_required": True,
        "grant_id": authorizations[0]["grant_id"],
        "operation": "apply_execution_attempt_create",
    }
    assert bridge.apply_calls == 0
    bridge.authoritatively_admit("one")
    resumed = manager.handle(
        "apply", {"preview_id": preview["preview_id"], "task_authorizations": authorizations}
    )
    assert resumed["ok"] is True
    assert resumed["lifecycle"]["lifecycle_state"] == "B1_ALL_ATTEMPTS_ADMITTED"
    assert bridge.apply_calls == 1


def test_b2_rejects_synthetic_artifact_projection(tmp_path) -> None:
    project = _init_managed_repo(tmp_path)
    intents = [_intents()[0]]
    _prepare_shards(project, intents)
    bridge = _FakeAttemptBridge(["one"])
    original = bridge.resolve_task_attempt_artifacts

    def synthetic(*args, **kwargs):
        return {**original(*args, **kwargs), "synthetic_empty": True}

    bridge.resolve_task_attempt_artifacts = synthetic
    manager, preview, authorizations = _group_preview(project, bridge, intents)
    manager.handle(
        "apply", {"preview_id": preview["preview_id"], "task_authorizations": authorizations}
    )
    manager.handle(
        "apply", {"preview_id": preview["preview_id"], "task_authorizations": authorizations}
    )
    rejected = manager.handle(
        "apply", {"preview_id": preview["preview_id"], "task_authorizations": authorizations}
    )
    assert rejected["ok"] is False
    assert rejected["error_code"] == "STAGE_ATTEMPT_ARTIFACT_PROJECTION_INVALID"


def test_b1_partial_admission_restart_resumes_without_duplicate(tmp_path) -> None:
    project = _init_managed_repo(tmp_path)
    intents = _intents()
    _prepare_shards(project, intents)
    bridge = _FakeAttemptBridge(["one", "two"])
    bridge.admitted["two"] = False
    manager, preview, authorizations = _group_preview(project, bridge, intents)
    _advance_until(
        manager, preview["preview_id"], authorizations, "B0_ALL_TASK_GRANTS_VALID"
    )
    first = manager.handle(
        "apply", {"preview_id": preview["preview_id"], "task_authorizations": authorizations}
    )
    assert first["lifecycle"]["tasks"][0]["attempt_admitted"] is True
    required = manager.handle(
        "apply", {"preview_id": preview["preview_id"], "task_authorizations": authorizations}
    )
    assert required["lifecycle"]["next_authoritative_action"]["task_id"] == "two"

    restarted = MCPStageParallelExecutorGroupManager(
        str(project), attempt_bridge=bridge
    )
    bridge.authoritatively_admit("two")
    resumed = restarted.handle(
        "apply", {"preview_id": preview["preview_id"], "task_authorizations": authorizations}
    )
    assert resumed["ok"] is True
    assert resumed["lifecycle"]["lifecycle_state"] == "B1_ALL_ATTEMPTS_ADMITTED"
    assert all(item["attempt_admitted"] for item in resumed["lifecycle"]["tasks"])
    assert bridge.apply_calls == 1


@pytest.mark.parametrize(
    ("substitution", "expected_error"),
    [
        ("root", "STAGE_SHARD_ROOT_MISMATCH"),
        ("branch", "APPLY_STATE_MISMATCH"),
        ("head", "APPLY_STATE_MISMATCH"),
    ],
)
def test_b3_rejects_shard_root_branch_and_head_substitution(
    tmp_path, substitution, expected_error
) -> None:
    project = _init_managed_repo(tmp_path)
    intents = [_intents()[0]]
    _prepare_shards(project, intents)
    bridge = _FakeAttemptBridge(["one"])
    manager, preview, authorizations = _group_preview(project, bridge, intents)
    _advance_until(
        manager,
        preview["preview_id"],
        authorizations,
        "B2_ALL_GOVERNED_TARGETS_COMPLETE",
    )
    root = (
        project
        / ".colameta"
        / "runtime"
        / "parallel-worktrees"
        / preview["parallel_group_id"]
        / "one"
    )
    if substitution == "root":
        displaced = root.with_name("one-displaced")
        root.rename(displaced)
        root.symlink_to(displaced, target_is_directory=True)
    elif substitution == "branch":
        subprocess.run(["git", "switch", "-c", "substituted"], cwd=root, check=True)
    else:
        (root / "README.md").write_text("head drift\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=root, check=True)
        subprocess.run(
            [
                "git", "-c", "user.name=Test", "-c", "user.email=test@example.com",
                "commit", "-m", "head drift", "-q",
            ],
            cwd=root,
            check=True,
        )

    rejected = manager.handle(
        "apply", {"preview_id": preview["preview_id"], "task_authorizations": authorizations}
    )

    assert rejected["ok"] is False
    assert rejected["error_code"] == expected_error


def test_artifact_drift_after_first_authority_blocks_b4_without_replacement(tmp_path) -> None:
    project = _init_managed_repo(tmp_path)
    intents = _intents()
    _prepare_shards(project, intents)
    bridge = _FakeAttemptBridge(["one", "two"])
    manager, preview, authorizations = _group_preview(project, bridge, intents)
    shard_root = project / ".colameta" / "runtime" / "parallel-worktrees"

    for _ in range(20):
        result = manager.handle(
            "apply", {"preview_id": preview["preview_id"], "task_authorizations": authorizations}
        )
        assert result["ok"] is True, result
        reservations = list(
            shard_root.glob("*/*/.colameta/runtime/executor-sessions/*/stage-shard-admission-reservation.json")
        )
        if len(reservations) == 1:
            break
    else:
        raise AssertionError("first authority was not created")
    first_ids = {path.parent.name for path in reservations}
    bridge.artifact_refs["one"] = [new_stable_id("artifact")]
    manager.handle(
        "apply", {"preview_id": preview["preview_id"], "task_authorizations": authorizations}
    )
    blocked = manager.handle(
        "apply", {"preview_id": preview["preview_id"], "task_authorizations": authorizations}
    )

    assert blocked["ok"] is False
    assert blocked["error_code"] == "STAGE_ATTEMPT_ARTIFACT_PROJECTION_DRIFT"
    all_reservations = list(
        shard_root.glob("*/*/.colameta/runtime/executor-sessions/*/stage-shard-admission-reservation.json")
    )
    assert first_ids <= {path.parent.name for path in all_reservations}
    assert len(all_reservations) == 2
    assert list(shard_root.glob("*/*/.colameta/runtime/executor-workflow-previews/*.json")) == []


def test_latest_artifacts_for_unreserved_task_continue_after_other_authority(tmp_path) -> None:
    project = _init_managed_repo(tmp_path)
    intents = _intents()
    _prepare_shards(project, intents)
    bridge = _FakeAttemptBridge(["one", "two"])
    manager, preview, authorizations = _group_preview(project, bridge, intents)
    shard_root = project / ".colameta" / "runtime" / "parallel-worktrees"

    for _ in range(20):
        result = manager.handle(
            "apply", {"preview_id": preview["preview_id"], "task_authorizations": authorizations}
        )
        assert result["ok"] is True, result
        if len(list(shard_root.glob(
            "*/*/.colameta/runtime/executor-sessions/*/stage-shard-admission-reservation.json"
        ))) == 1:
            break
    else:
        raise AssertionError("first authority was not created")
    latest_ref = new_stable_id("artifact")
    bridge.artifact_refs["two"] = [latest_ref]

    continued = manager.handle(
        "apply", {"preview_id": preview["preview_id"], "task_authorizations": authorizations}
    )

    assert continued["ok"] is True, continued
    reservations = list(shard_root.glob(
        "*/*/.colameta/runtime/executor-sessions/*/stage-shard-admission-reservation.json"
    ))
    assert len(reservations) == 2
    records = [json.loads(path.read_text(encoding="utf-8")) for path in reservations]
    task_two = next(record for record in records if record["task_id"] == "two")
    assert task_two["artifact_refs"] == [latest_ref]


def test_artifact_drift_after_first_preview_blocks_b5_without_duplicate(tmp_path) -> None:
    project = _init_managed_repo(tmp_path)
    intents = _intents()
    _prepare_shards(project, intents)
    bridge = _FakeAttemptBridge(["one", "two"])
    manager, preview, authorizations = _group_preview(project, bridge, intents)
    _advance_until(
        manager, preview["preview_id"], authorizations,
        "B4_ALL_FRESH_AUTHORITIES_READY",
    )
    shard_root = project / ".colameta" / "runtime" / "parallel-worktrees"
    created = manager.handle(
        "apply", {"preview_id": preview["preview_id"], "task_authorizations": authorizations}
    )
    assert created["ok"] is True
    assert len(list(shard_root.glob("*/*/.colameta/runtime/executor-workflow-previews/*.json"))) == 1
    bridge.artifact_refs["one"] = [new_stable_id("artifact")]
    manager.handle(
        "apply", {"preview_id": preview["preview_id"], "task_authorizations": authorizations}
    )
    blocked = manager.handle(
        "apply", {"preview_id": preview["preview_id"], "task_authorizations": authorizations}
    )

    assert blocked["ok"] is False
    assert blocked["error_code"] == "STAGE_ATTEMPT_ARTIFACT_PROJECTION_DRIFT"
    assert len(list(shard_root.glob("*/*/.colameta/runtime/executor-workflow-previews/*.json"))) == 2


def test_prepared_status_is_checkpoint_not_current_execution_authority(tmp_path) -> None:
    project = _init_managed_repo(tmp_path)
    intents = [_intents()[0]]
    _prepare_shards(project, intents)
    bridge = _FakeAttemptBridge(["one"])
    manager, preview, authorizations = _group_preview(project, bridge, intents)
    prepared = _advance_until(
        manager, preview["preview_id"], authorizations, "PREPARED_FOR_EXECUTION"
    )[-1]
    assert prepared["lifecycle"]["current_governance_revalidated"] is True
    assert prepared["lifecycle"]["provider_start_authorized"] is False

    bridge.artifact_refs["one"] = [new_stable_id("artifact")]
    status = manager.handle("status", {"preview_id": preview["preview_id"]})

    assert status["ok"] is True
    assert status["lifecycle"]["prepared_checkpoint_present"] is True
    assert status["lifecycle"]["current_governance_revalidated"] is False
    assert status["lifecycle"]["status"] == "CURRENT_GOVERNANCE_REVALIDATION_REQUIRED"
    assert status["lifecycle"]["provider_start_authorized"] is False
