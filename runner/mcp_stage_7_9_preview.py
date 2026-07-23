"""One fail-closed, read-only Stage 7--9 preview journey.

The Stage 7 evidence builder, Stage 8 plan-adjustment preview, and Stage 9
continue-readiness report already own their domain contracts.  This module
does not duplicate them or create a fourth state authority.  It binds their
handoff through one narrow MCP-compatible read surface, checks the frozen
taskbook inputs declared by P1-C0, and emits only a compact public projection.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import os
from pathlib import Path
import stat
from typing import Any, Protocol

from runner.controlled_continue_readiness import (
    PLAN_ADJUST_REVIEW_DECISION_VALUE,
    build_controlled_continue_readiness_report,
)
from runner.drift_evidence_pack_builder import (
    DRIFT_EVIDENCE_PACK_GENERATED,
    build_drift_evidence_pack,
)
from runner.plan_adjustment_preview import (
    PLAN_ADJUSTMENT_PREVIEW_AVAILABLE,
    build_plan_adjustment_preview,
)
from runner.project_context_binding import (
    ProjectContextBindingError,
    collect_project_context_binding,
    context_binding_sha256,
    require_operation_context_binding,
)


STAGE_7_9_PREVIEW_WORKFLOW = "stage_7_9_preview"
STAGE_7_9_PREVIEW_SCHEMA_VERSION = "colameta.stage_7_9_preview.v1"
STAGE_7_9_REVIEW_UNIT = "stage_07_to_stage_09_preview"
STAGE_7_9_WORKFLOW_INTENT = STAGE_7_9_PREVIEW_WORKFLOW
STAGE_7_9_MAX_TASKBOOK_BYTES = 4_000_000

_INPUT_FIELDS = (
    "stage_7_drift_evidence_inputs",
    "stage_8_plan_adjustment_inputs",
    "stage_9_continue_readiness_inputs",
)

_FROZEN_TASKBOOKS: tuple[dict[str, str], ...] = (
    {
        "key": "master",
        "path": "PROJECT_MASTER_TASKBOOK.md",
        "sha256": "1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34",
    },
    {
        "key": "stage_7",
        "path": "docs/taskbooks/stages/STAGE_07_DRIFT_EVIDENCE_AND_CORRECTION.md",
        "sha256": "24cec5e48435254731cce4bb2e72c8810df3d041f57c142d5674d82a632cb142",
    },
    {
        "key": "stage_8",
        "path": "docs/taskbooks/stages/STAGE_08_PLAN_ADJUSTMENT_CONTROL.md",
        "sha256": "60421ba765b238b9671f1f9baf878cf716c6e6e5cd05524bfa746610fd9a3755",
    },
    {
        "key": "stage_9",
        "path": "docs/taskbooks/stages/STAGE_09_CONTROLLED_CONTINUE_AND_LONG_RUN_TRACE.md",
        "sha256": "5bfe6e4632748bd33f5a763963bc54b5e546bd3349ad536ec5b693522c7d696d",
    },
)
_TASKBOOK_BY_KEY = {item["key"]: item for item in _FROZEN_TASKBOOKS}


class Stage79PreviewError(ValueError):
    """A compact, public-safe Stage 7--9 journey failure."""

    def __init__(
        self,
        error_code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.details = details or {}


class Stage79PreviewHost(Protocol):
    """Only the local identity capability this read-only journey needs."""

    project_root: str


class MCPStage79PreviewWorkflow:
    """Compose Stage 7--9 evidence without creating a write route."""

    def __init__(self, host: Stage79PreviewHost) -> None:
        self._host = host

    def handle(self, params: dict[str, Any]) -> dict[str, Any]:
        phase = _phase(params.get("phase"))
        if phase == "inspect":
            return self._inspect(params)
        if phase == "preview":
            return self._preview(params)
        raise Stage79PreviewError(
            "STAGE_7_9_PHASE_NOT_SUPPORTED",
            "stage_7_9_preview 只支持 inspect 或 preview；它不支持 apply、run、commit 或 execute。",
        )

    def _inspect(self, params: dict[str, Any]) -> dict[str, Any]:
        context = self._collect_context(params)
        taskbook_bindings = self._verify_frozen_taskbooks()
        return {
            "ok": True,
            "workflow": STAGE_7_9_PREVIEW_WORKFLOW,
            "phase": "inspect",
            "schema_version": STAGE_7_9_PREVIEW_SCHEMA_VERSION,
            "read_only": True,
            "side_effects": False,
            "stage_7_9_context": context,
            "context_sha256": context_binding_sha256(context),
            "frozen_taskbook_bindings": taskbook_bindings,
            "input_contract": _input_contract(),
            "next_actions": [
                {
                    "tool": "run_mcp_workflow",
                    "params": {
                        "workflow": STAGE_7_9_PREVIEW_WORKFLOW,
                        "phase": "preview",
                        "stage_7_9_context": context,
                        "stage_7_9_inputs": _input_template(),
                    },
                    "required_scope": "mcp:read",
                    "reason": "原样回传 context，并提供 Stage 7、8、9 三个有界输入对象以生成只读 journey preview。",
                }
            ],
            "authority_boundary": _authority_boundary(),
        }

    def _preview(self, params: dict[str, Any]) -> dict[str, Any]:
        context = self._require_context(params)
        taskbook_bindings = self._verify_frozen_taskbooks()
        inputs = _require_input_bundle(params.get("stage_7_9_inputs"))
        _verify_input_taskbook_bindings(inputs)

        stage_7 = build_drift_evidence_pack(inputs["stage_7_drift_evidence_inputs"])
        if stage_7.get("pack_builder_status") != DRIFT_EVIDENCE_PACK_GENERATED:
            raise Stage79PreviewError(
                "STAGE_7_9_STAGE_7_FAILED_CLOSED",
                "Stage 7 drift evidence 未通过有界 schema/evidence 检查，已停止后续 Stage 8/9 组合。",
                {"blocker_codes": _blocker_codes(stage_7.get("failures_and_blockers"))},
            )
        drift_pack = _mapping(stage_7.get("drift_evidence_pack"))
        drift_pack_id = _required_text(
            drift_pack.get("drift_evidence_pack_id"),
            "STAGE_7_9_STAGE_7_FAILED_CLOSED",
            "Stage 7 drift evidence pack 缺少可绑定的 ID。",
        )

        stage_8_inputs = deepcopy(inputs["stage_8_plan_adjustment_inputs"])
        _verify_stage_8_drift_pack_binding(stage_8_inputs, drift_pack_id)
        stage_8 = build_plan_adjustment_preview(stage_8_inputs)
        if stage_8.get("preview_status") != PLAN_ADJUSTMENT_PREVIEW_AVAILABLE:
            raise Stage79PreviewError(
                "STAGE_7_9_STAGE_8_FAILED_CLOSED",
                "Stage 8 PLAN_ADJUST preview 未满足其独立的 request/binding 约束，已停止 Stage 9。",
                {"validation_error_codes": _blocker_codes(stage_8.get("validation_errors"))},
            )
        stage_8_preview_id = _required_text(
            stage_8.get("plan_adjustment_request_id"),
            "STAGE_7_9_STAGE_8_FAILED_CLOSED",
            "Stage 8 preview 缺少可绑定的 plan adjustment request ID。",
        )

        stage_9_inputs = deepcopy(inputs["stage_9_continue_readiness_inputs"])
        _verify_stage_9_inputs(stage_9_inputs)
        _verify_stage_9_preview_binding(stage_9_inputs, stage_8_preview_id)
        stage_9_inputs["plan_adjustment_preview_ref"] = {
            "preview_id": stage_8_preview_id,
            "preview_status": str(stage_8.get("preview_status") or ""),
            "resolution_status": "preview_available",
            "drift_evidence_pack_id": drift_pack_id,
        }
        stage_9 = build_controlled_continue_readiness_report(stage_9_inputs)
        stage_9_blocker_codes = _blocker_codes(stage_9.get("blockers"))
        if (
            stage_9.get("can_continue") is not False
            or "PLAN_ADJUST_BLOCKS_CONTINUE" not in stage_9_blocker_codes
        ):
            raise Stage79PreviewError(
                "STAGE_7_9_STAGE_9_FAILED_CLOSED",
                "Stage 9 没有保持 PLAN_ADJUST 下的 continue blocker，已停止输出 journey 结论。",
                {"blocker_codes": stage_9_blocker_codes},
            )
        _verify_authority_boundary(stage_7, stage_8, stage_9)

        return {
            "ok": True,
            "workflow": STAGE_7_9_PREVIEW_WORKFLOW,
            "phase": "preview",
            "schema_version": STAGE_7_9_PREVIEW_SCHEMA_VERSION,
            "read_only": True,
            "side_effects": False,
            "journey_status": "human_decision_required",
            "stage_7_9_context": context,
            "context_sha256": context_binding_sha256(context),
            "frozen_taskbook_bindings": taskbook_bindings,
            "stage_results": {
                "stage_7": _stage_7_projection(stage_7, drift_pack),
                "stage_8": _stage_8_projection(stage_8, drift_pack_id),
                "stage_9": _stage_9_projection(stage_9),
            },
            "next_human_decision": {
                "action": "review_stage_8_plan_adjustment_preview",
                "reason_code": "PLAN_ADJUST_BLOCKS_CONTINUE",
                "description": "先由有权的人审查并处理 Stage 8 PLAN_ADJUST preview；当前 journey 不会 apply、continue 或启动 executor。",
                "authorization_required": True,
            },
            "authority_boundary": _authority_boundary(),
        }

    def _collect_context(self, params: dict[str, Any]) -> dict[str, Any]:
        context = collect_project_context_binding(
            self._host.project_root,
            project_name=_requested_project_name(params),
            review_unit=STAGE_7_9_REVIEW_UNIT,
            workflow_intent=STAGE_7_9_WORKFLOW_INTENT,
        )
        unavailable = [
            field
            for field in ("project_name", "branch", "head")
            if not isinstance(context.get(field), str) or not str(context.get(field)).strip()
        ]
        if unavailable:
            raise Stage79PreviewError(
                "STAGE_7_9_CONTEXT_UNAVAILABLE",
                "无法建立 Stage 7--9 journey 所需的项目上下文，已停止。",
                {"unavailable_fields": unavailable},
            )
        return context

    def _require_context(self, params: dict[str, Any]) -> dict[str, Any]:
        supplied = params.get("stage_7_9_context")
        if not isinstance(supplied, dict):
            raise Stage79PreviewError(
                "STAGE_7_9_CONTEXT_REQUIRED",
                "stage_7_9_preview preview 必须原样携带 inspect 返回的 stage_7_9_context。",
            )
        try:
            return require_operation_context_binding(
                supplied,
                project_root=self._host.project_root,
                project_name=_requested_project_name(params),
                review_unit=STAGE_7_9_REVIEW_UNIT,
                workflow_intent=STAGE_7_9_WORKFLOW_INTENT,
            )
        except ProjectContextBindingError as exc:
            raise Stage79PreviewError(
                "STAGE_7_9_CONTEXT_MISMATCH",
                "Stage 7--9 journey context 已变化、格式不完整或属于另一项目；请重新 inspect。",
                {"source_error_code": exc.error_code},
            ) from exc

    def _verify_frozen_taskbooks(self) -> list[dict[str, Any]]:
        root = Path(os.path.realpath(os.path.abspath(os.path.expanduser(self._host.project_root))))
        rows: list[dict[str, Any]] = []
        for binding in _FROZEN_TASKBOOKS:
            actual = _sha256_known_regular_file(root, binding["path"])
            if actual != binding["sha256"]:
                raise Stage79PreviewError(
                    "STAGE_7_9_TASKBOOK_BINDING_MISMATCH",
                    "Stage 7--9 依赖的冻结 taskbook 路径或 SHA-256 不匹配，已停止组合 preview。",
                    {"binding_key": binding["key"], "path": binding["path"]},
                )
            rows.append(
                {
                    "binding_key": binding["key"],
                    "path": binding["path"],
                    "sha256": binding["sha256"],
                    "matches": True,
                }
            )
        return rows


def _input_contract() -> dict[str, Any]:
    return {
        "required_context_field": "stage_7_9_context",
        "required_input_fields": list(_INPUT_FIELDS),
        "allowed_phases": ["inspect", "preview"],
        "required_scope": "mcp:read",
        "stage_7_to_8_binding": "stage_8.drift_evidence_ref.drift_evidence_pack_id equals generated Stage 7 pack ID",
        "stage_8_to_9_binding": "Stage 9 receives generated Stage 8 request ID as an unresolved preview reference",
        "side_effects": False,
    }


def _input_template() -> dict[str, Any]:
    return {
        "stage_7_drift_evidence_inputs": {
            "master_taskbook_ref": _reference_template("master"),
            "stage_taskbook_ref": _reference_template("stage_7"),
            "version_taskbook_ref": {"version": "<version-taskbook-id>"},
            "execution_evidence_ref": {"evidence_id": "<bounded-execution-evidence-id>"},
            "changed_files": ["<project-relative-path>"],
            "validation_truth": {"status": "<observed-validation-status>"},
            "scope_evidence": {"scope_result": "<in_scope|out_of_scope>"},
            "forbidden_files_evidence": {"forbidden_files_touched": []},
            "out_of_scope_evidence": {"out_of_scope_files": []},
        },
        "stage_8_plan_adjustment_inputs": {
            "commander_decision_request": {
                "request_status": "commander_decision_request_available",
                "source_review_decision_value": PLAN_ADJUST_REVIEW_DECISION_VALUE,
                "normalized_classification": "plan_adjust_review_feedback",
                "requested_commander_action": "ask_whether_to_prepare_plan_adjustment_draft",
            },
            "master_taskbook_ref": _reference_template("master"),
            "master_taskbook_hash": _TASKBOOK_BY_KEY["master"]["sha256"],
            "affected_stage_refs": [_reference_template("stage_8")],
            "affected_version_refs": [{"version": "<affected-version>"}],
            "drift_evidence_ref": {"drift_evidence_pack_id": "<generated-stage-7-pack-id>"},
            "proposed_change_summary": "<candidate-only summary>",
            "proposed_diff_or_patch_preview": {"candidate_only": True, "files": []},
            "continued_master_goal_service_explanation": "<why the candidate remains within the master goal>",
        },
        "stage_9_continue_readiness_inputs": {
            "plan": {"versions": []},
            "state": {"versions": []},
            "review_decision_ref": {"normalized_review_decision_value": PLAN_ADJUST_REVIEW_DECISION_VALUE},
            "taskbook_hash_refs": {
                "master_taskbook_ref": _hash_reference_template("master"),
                "stage_taskbook_ref": _hash_reference_template("stage_9"),
                "version_taskbook_ref": {
                    "version": "<next-version>",
                    "expected_sha256": "<version-taskbook-sha256>",
                    "actual_sha256": "<version-taskbook-sha256>",
                },
            },
        },
    }


def _reference_template(key: str) -> dict[str, str]:
    binding = _TASKBOOK_BY_KEY[key]
    return {"path": binding["path"], "sha256": binding["sha256"]}


def _hash_reference_template(key: str) -> dict[str, str]:
    binding = _TASKBOOK_BY_KEY[key]
    return {
        "path": binding["path"],
        "expected_sha256": binding["sha256"],
        "actual_sha256": binding["sha256"],
    }


def _require_input_bundle(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict):
        raise Stage79PreviewError(
            "STAGE_7_9_INPUTS_REQUIRED",
            "stage_7_9_preview preview 必须提供三个 stage input object。",
            {"missing_fields": list(_INPUT_FIELDS)},
        )
    missing = [field for field in _INPUT_FIELDS if not isinstance(value.get(field), dict)]
    unexpected = sorted(set(value) - set(_INPUT_FIELDS))
    if missing or unexpected:
        details: dict[str, Any] = {}
        if missing:
            details["missing_fields"] = missing
        if unexpected:
            details["unexpected_fields"] = unexpected
        raise Stage79PreviewError(
            "STAGE_7_9_INPUTS_REQUIRED",
            "stage_7_9_inputs 必须精确包含三个非空 stage input object。",
            details,
        )
    empty = [field for field in _INPUT_FIELDS if not value.get(field)]
    if empty:
        raise Stage79PreviewError(
            "STAGE_7_9_INPUTS_REQUIRED",
            "stage_7_9_inputs 不能包含空的 stage input object。",
            {"empty_fields": empty},
        )
    return {field: deepcopy(value[field]) for field in _INPUT_FIELDS}


def _verify_input_taskbook_bindings(inputs: dict[str, dict[str, Any]]) -> None:
    stage_7 = inputs["stage_7_drift_evidence_inputs"]
    stage_8 = inputs["stage_8_plan_adjustment_inputs"]
    _require_exact_reference(stage_7.get("master_taskbook_ref"), "master")
    _require_exact_reference(stage_7.get("stage_taskbook_ref"), "stage_7")
    if not _mapping(stage_7.get("version_taskbook_ref")):
        _taskbook_binding_error("Stage 7 version_taskbook_ref 缺失。", {"field": "stage_7.version_taskbook_ref"})

    _require_exact_reference(stage_8.get("master_taskbook_ref"), "master")
    if _clean_text(stage_8.get("master_taskbook_hash")) != _TASKBOOK_BY_KEY["master"]["sha256"]:
        _taskbook_binding_error("Stage 8 master_taskbook_hash 不匹配。", {"field": "stage_8.master_taskbook_hash"})
    _require_reference_in_list(stage_8.get("affected_stage_refs"), "stage_8", "stage_8.affected_stage_refs")
    if not _structured_list(stage_8.get("affected_version_refs")):
        _taskbook_binding_error("Stage 8 affected_version_refs 缺失。", {"field": "stage_8.affected_version_refs"})


def _verify_stage_8_drift_pack_binding(stage_8_inputs: dict[str, Any], drift_pack_id: str) -> None:
    ref = _mapping(stage_8_inputs.get("drift_evidence_ref"))
    if _clean_text(ref.get("drift_evidence_pack_id")) != drift_pack_id:
        raise Stage79PreviewError(
            "STAGE_7_9_DRIFT_PACK_BINDING_MISMATCH",
            "Stage 8 必须引用本次 Stage 7 生成的 drift evidence pack ID。",
        )


def _verify_stage_9_inputs(stage_9_inputs: dict[str, Any]) -> None:
    if not _mapping(stage_9_inputs.get("plan")) or not _mapping(stage_9_inputs.get("state")):
        raise Stage79PreviewError(
            "STAGE_7_9_STAGE_9_FAILED_CLOSED",
            "Stage 9 必须提供 plan 与 state 作为受控 readiness 输入。",
            {"required_fields": ["plan", "state"]},
        )
    review_ref = _mapping(stage_9_inputs.get("review_decision_ref"))
    if _clean_text(review_ref.get("normalized_review_decision_value")) != PLAN_ADJUST_REVIEW_DECISION_VALUE:
        raise Stage79PreviewError(
            "STAGE_7_9_STAGE_9_FAILED_CLOSED",
            "PLAN_ADJUST journey 的 Stage 9 必须明确携带 PLAN_ADJUST review decision ref。",
            {"field": "review_decision_ref.normalized_review_decision_value"},
        )
    refs = _mapping(stage_9_inputs.get("taskbook_hash_refs"))
    _require_exact_hash_reference(refs.get("master_taskbook_ref"), "master", "stage_9.master_taskbook_ref")
    _require_exact_hash_reference(refs.get("stage_taskbook_ref"), "stage_9", "stage_9.stage_taskbook_ref")
    version_ref = _mapping(refs.get("version_taskbook_ref"))
    expected = _clean_text(version_ref.get("expected_sha256"))
    actual = _clean_text(version_ref.get("actual_sha256"))
    if not _clean_text(version_ref.get("version")) or not _is_sha256(expected) or expected != actual:
        raise Stage79PreviewError(
            "STAGE_7_9_STAGE_9_FAILED_CLOSED",
            "Stage 9 version_taskbook_ref 必须带有匹配的 version、expected_sha256 与 actual_sha256。",
            {"field": "stage_9.version_taskbook_ref"},
        )


def _verify_stage_9_preview_binding(stage_9_inputs: dict[str, Any], generated_preview_id: str) -> None:
    supplied = stage_9_inputs.get("plan_adjustment_preview_ref")
    if supplied is None:
        return
    ref = _mapping(supplied)
    supplied_id = _clean_text(ref.get("preview_id"))
    if supplied_id and supplied_id != generated_preview_id:
        raise Stage79PreviewError(
            "STAGE_7_9_DRIFT_PACK_BINDING_MISMATCH",
            "Stage 9 的预置 Stage 8 preview ref 不属于本次 journey。",
        )


def _verify_authority_boundary(stage_7: dict[str, Any], stage_8: dict[str, Any], stage_9: dict[str, Any]) -> None:
    stage_7_boundary = _mapping(stage_7.get("authority_boundary"))
    stage_8_effects = _mapping(stage_8.get("forbidden_side_effects"))
    stage_9_effects = _mapping(stage_9.get("forbidden_side_effects"))
    if (
        not stage_7_boundary
        or any(value is not False for value in stage_7_boundary.values())
        or not stage_8_effects
        or any(value is not False for value in stage_8_effects.values())
        or not stage_9_effects
        or any(value is not False for value in stage_9_effects.values())
        or stage_8.get("apply_allowed") is not False
        or stage_8.get("plan_mutated") is not False
        or stage_8.get("executor_continuation_authorized") is not False
        or stage_8.get("commit_or_push") is not False
    ):
        raise Stage79PreviewError(
            "STAGE_7_9_AUTHORITY_BOUNDARY_VIOLATION",
            "Stage 7--9 journey 发现不允许的 authority 或 side-effect claim，已停止输出。",
        )


def _stage_7_projection(stage_7: dict[str, Any], pack: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": stage_7.get("pack_builder_status"),
        "drift_evidence_pack_id": pack.get("drift_evidence_pack_id"),
        "schema_validation": _mapping(stage_7.get("schema_validation_result")).get("validation_result"),
        "master_goal_question_count": len(_structured_list(pack.get("master_goal_alignment_questions"))),
        "reviewer_drift_checklist_count": len(_structured_list(pack.get("reviewer_drift_checklist"))),
        "plan_adjustment_trigger_count": len(_structured_list(pack.get("plan_adjustment_trigger_conditions"))),
        "blocker_codes": _blocker_codes(stage_7.get("failures_and_blockers")),
        "semantic_alignment_pass": False,
        "no_drift_confirmed": False,
    }


def _stage_8_projection(stage_8: dict[str, Any], drift_pack_id: str) -> dict[str, Any]:
    return {
        "status": stage_8.get("preview_status"),
        "plan_adjustment_request_id": stage_8.get("plan_adjustment_request_id"),
        "drift_evidence_pack_id": drift_pack_id,
        "commander_hard_gate_required": stage_8.get("commander_hard_gate_required") is True,
        "apply_allowed": False,
        "validation_error_codes": _blocker_codes(stage_8.get("validation_errors")),
    }


def _stage_9_projection(stage_9: dict[str, Any]) -> dict[str, Any]:
    next_action = _mapping(stage_9.get("next_action"))
    return {
        "readiness_result": stage_9.get("readiness_result"),
        "can_continue": False,
        "blocker_codes": _blocker_codes(stage_9.get("blockers")),
        "plan_adjust_blocks_continue": _mapping(stage_9.get("plan_adjustment_status")).get("blocks_continue") is True,
        "next_action": {
            "action": next_action.get("action"),
            "reason_code": next_action.get("reason_code"),
        },
    }


def _authority_boundary() -> dict[str, bool]:
    return {
        "read_only": True,
        "side_effects": False,
        "does_not_read_raw_runtime_state": True,
        "does_not_emit_semantic_drift_judgment": True,
        "does_not_apply_plan_or_taskbook": True,
        "does_not_start_executor": True,
        "does_not_create_review_decision_or_gate_event": True,
        "does_not_change_delivery_state": True,
        "does_not_commit_or_push": True,
        "does_not_replace_stable_or_change_connector": True,
    }


def _requested_project_name(params: dict[str, Any]) -> str | None:
    for key in ("project_name", "__context_binding_project_name"):
        value = params.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _phase(value: Any) -> str:
    if value is None:
        return "inspect"
    return value.strip().lower() if isinstance(value, str) else ""


def _sha256_known_regular_file(root: Path, relative_path: str) -> str | None:
    candidate = root / relative_path
    try:
        root_resolved = root.resolve(strict=True)
        candidate_resolved = candidate.resolve(strict=True)
        candidate_resolved.relative_to(root_resolved)
        before = os.lstat(candidate)
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode) or before.st_size > STAGE_7_9_MAX_TASKBOOK_BYTES:
            return None
        descriptor = os.open(candidate, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except (OSError, ValueError):
        return None
    try:
        after = os.fstat(descriptor)
        if not stat.S_ISREG(after.st_mode) or after.st_dev != before.st_dev or after.st_ino != before.st_ino:
            return None
        digest = hashlib.sha256()
        while True:
            chunk = os.read(descriptor, 64 * 1024)
            if not chunk:
                break
            digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass


def _require_exact_reference(value: Any, key: str) -> None:
    expected = _TASKBOOK_BY_KEY[key]
    ref = _mapping(value)
    if _clean_text(ref.get("path")) != expected["path"] or _clean_text(ref.get("sha256")) != expected["sha256"]:
        _taskbook_binding_error("Stage 输入的 taskbook path 或 SHA-256 不匹配。", {"binding_key": key})


def _require_reference_in_list(value: Any, key: str, field: str) -> None:
    rows = _structured_list(value)
    for row in rows:
        expected = _TASKBOOK_BY_KEY[key]
        if _clean_text(row.get("path")) == expected["path"] and _clean_text(row.get("sha256")) == expected["sha256"]:
            return
    _taskbook_binding_error("Stage 输入缺少冻结 taskbook ref。", {"binding_key": key, "field": field})


def _require_exact_hash_reference(value: Any, key: str, field: str) -> None:
    expected = _TASKBOOK_BY_KEY[key]
    ref = _mapping(value)
    expected_hash = _clean_text(ref.get("expected_sha256"))
    actual_hash = _clean_text(ref.get("actual_sha256")) or _clean_text(ref.get("raw_snapshot_sha256"))
    if (
        _clean_text(ref.get("path")) != expected["path"]
        or expected_hash != expected["sha256"]
        or actual_hash != expected["sha256"]
    ):
        _taskbook_binding_error("Stage 9 taskbook hash ref 不匹配。", {"binding_key": key, "field": field})


def _taskbook_binding_error(message: str, details: dict[str, Any]) -> None:
    raise Stage79PreviewError("STAGE_7_9_TASKBOOK_BINDING_MISMATCH", message, details)


def _required_text(value: Any, code: str, message: str) -> str:
    text = _clean_text(value)
    if not text:
        raise Stage79PreviewError(code, message)
    return text


def _blocker_codes(value: Any) -> list[str]:
    rows = _structured_list(value)
    return sorted({text for row in rows if (text := _clean_text(row.get("code")))})


def _structured_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _clean_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value.lower())
