from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Callable

from runner.work_item_commands import WorkItemCommandGateway


class CommanderProjectionService:
    """One Commander shell with three separately owned read projections."""

    def __init__(
        self,
        project_root: str | Path,
        *,
        service_operations_reader: Callable[[], dict[str, Any]] | None = None,
        app_submission_reader: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        self.gateway = WorkItemCommandGateway(project_root)
        self.service_operations_reader = service_operations_reader or (lambda: {})
        self.app_submission_reader = app_submission_reader or (lambda: {})

    def project(self, *, work_item_limit: int = 25) -> dict[str, Any]:
        status_result = self.gateway.execute_safe("get_work_item_governance_status", {})
        if status_result["ok"]:
            status = status_result["data"]
            if status["enabled"]:
                work_items_result = self.gateway.execute_safe(
                    "list_work_items",
                    {"limit": work_item_limit},
                )
                work_items = (
                    work_items_result["data"]
                    if work_items_result["ok"]
                    else self._unavailable_core_list(work_items_result["error"])
                )
            else:
                work_items = {"schema_version": "work_item_list.v1", "items": [], "count": 0}
        else:
            status = {
                "enabled": None,
                "status": "unavailable",
                "error": status_result["error"],
            }
            work_items = self._unavailable_core_list(status_result["error"])
        return {
            "schema_version": "commander_domain_projections.v1",
            "sections": {
                "core": {
                    "owner": "work_item_governance",
                    "governance_status": status,
                    "work_items": work_items,
                    "write_path": "application_commands_only",
                    "read_only_surface": True,
                },
                "service_operations": {
                    "owner": "service_operations",
                    "read_model": self._read_side_projection(self.service_operations_reader),
                    "read_model_ref": "connector",
                    "can_write_work_item_state": False,
                },
                "app_submission": {
                    "owner": "app_productization",
                    "read_model": self._read_side_projection(self.app_submission_reader),
                    "read_model_ref": "apps_connector_closeout.release_submission_evidence",
                    "can_write_work_item_state": False,
                },
            },
        }

    @staticmethod
    def project_cc_s01_contract_value(key: str, value: Any) -> tuple[bool, Any]:
        """Preserve CC-S01 contract facts without exposing local path metadata."""

        if key == "canonical_continuation_decision" and isinstance(value, dict):
            allowed = {
                "ok",
                "schema_version",
                "classification",
                "resume_allowed",
                "start_new_allowed",
                "recommended_action",
                "reason",
                "severity",
                "decision_source",
                "requested_provider",
                "selected_provider",
                "provider_matches",
                "identity_present",
                "provider_resume_supported",
                "resume_invocation_verified",
                "continuation_available",
                "session_resume_available",
                "should_resume",
                "should_start_new",
                "manual_confirmation_required",
                "hard_blockers",
                "resume_blockers",
                "risk_level",
                "risk_warnings",
                "resume_warnings",
                "next_action_hint",
                "decision_owner",
                "decision",
                "decision_reason",
                "recommended_default",
                "policy",
                "actual_executor_resume_attempted",
            }
            projected = {
                field: copy.deepcopy(value[field])
                for field in allowed
                if field in value
            }
            classification = value.get("head_mismatch_classification")
            if isinstance(classification, dict):
                projected["head_mismatch_classification"] = (
                    CommanderProjectionService._project_head_mismatch_classification(
                        classification
                    )
                )
            return True, projected
        if key == "evidence_provenance" and isinstance(value, dict):
            return True, CommanderProjectionService._project_evidence_provenance(
                value
            )
        return False, None

    @staticmethod
    def _project_head_mismatch_classification(value: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "status",
            "severity",
            "blocks_auto_resume",
            "blocks_auto_start",
            "operation_running",
            "job_idle",
            "reason",
            "operator_message",
            "allowed_next_actions",
        }
        projected = {
            field: copy.deepcopy(value[field])
            for field in allowed
            if field in value
        }
        evidence = value.get("evidence")
        if isinstance(evidence, dict):
            evidence_allowed = {
                "session_exists",
                "heads_comparable",
                "head_mismatch",
                "live_run_running",
                "latest_run_status",
                "latest_claim_status",
                "runner_status",
                "current_version_status",
                "worktree_clean",
            }
            projected["evidence"] = {
                field: copy.deepcopy(evidence[field])
                for field in evidence_allowed
                if field in evidence
            }
        return projected

    @staticmethod
    def _project_evidence_provenance(value: dict[str, Any]) -> dict[str, Any]:
        projected = {
            field: copy.deepcopy(value[field])
            for field in {
                "schema_version",
                "provenance_status",
                "legacy_read_parse_only",
                "eligible_for_acceptance",
            }
            if field in value
        }
        entry_allowed = {
            "subject_path",
            "evidence_kind",
            "claimed_evidence_subject",
            "claimed_subject_requires_execution",
            "claimed_subject_operation_completed",
            "claimed_execution_performed",
            "claimed_eligible_for_acceptance",
            "evidence_subject",
            "subject_requires_execution",
            "subject_operation_completed",
            "execution_performed",
            "eligible_for_acceptance",
            "binding_status",
        }
        binding_allowed = {
            "record_schema_version",
            "subject_path",
            "content_sha256",
        }
        entries: list[dict[str, Any]] = []
        raw_entries = value.get("entries")
        if isinstance(raw_entries, list):
            for raw_entry in raw_entries:
                if not isinstance(raw_entry, dict):
                    continue
                entry = {
                    field: copy.deepcopy(raw_entry[field])
                    for field in entry_allowed
                    if field in raw_entry
                }
                binding = raw_entry.get("binding")
                if isinstance(binding, dict):
                    entry["binding"] = {
                        field: copy.deepcopy(binding[field])
                        for field in binding_allowed
                        if field in binding
                    }
                entries.append(entry)
        projected["entries"] = entries
        authority = value.get("authority_boundary")
        if isinstance(authority, dict):
            authority_allowed = {
                "eligible_means_accepted",
                "creates_review_decision",
                "emits_gate_event",
                "writes_delivery_state",
            }
            projected["authority_boundary"] = {
                field: copy.deepcopy(authority[field])
                for field in authority_allowed
                if field in authority
            }
        return projected

    @staticmethod
    def _unavailable_core_list(error: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": "work_item_list.v1",
            "items": [],
            "count": 0,
            "status": "unavailable",
            "error": error,
        }

    @staticmethod
    def _read_side_projection(reader: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        try:
            value = reader()
        except Exception as exc:
            return {
                "status": "unavailable",
                "error_code": "SIDE_PROJECTION_UNAVAILABLE",
                "error_type": type(exc).__name__,
            }
        if not isinstance(value, dict):
            return {
                "status": "unavailable",
                "error_code": "SIDE_PROJECTION_INVALID",
            }
        return value
