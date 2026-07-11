from __future__ import annotations

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
