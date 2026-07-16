from __future__ import annotations

from pathlib import Path
from typing import Any

from runner.work_item_commands import WorkItemCommandGateway


class AppSubmissionWorkItemCommands:
    """App Productization adapter using only formal application commands."""

    def __init__(self, project_root: str | Path) -> None:
        self.gateway = WorkItemCommandGateway(project_root)

    def preview_create(
        self,
        *,
        submission_ref: str,
        snapshot_digest: str,
        attributes: dict[str, Any] | None = None,
        task: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        ttl_seconds: int = 300,
    ) -> dict[str, Any]:
        command = {
            "origin": {
                "kind": "project",
                "ref": submission_ref,
                "snapshot_digest": snapshot_digest,
            },
            "attributes": {
                "domain": "app_submission",
                **dict(attributes or {}),
            },
            "task": dict(task or {}),
            "idempotency_key": idempotency_key or f"app_submission:{submission_ref}:{snapshot_digest}",
        }
        return self.gateway.execute(
            "preview_work_item_create",
            {"command": command, "ttl_seconds": ttl_seconds},
        )

    def apply_create(self, preview: dict[str, Any]) -> dict[str, Any]:
        return self.gateway.execute("apply_work_item_create", {"preview": preview})

    def reference_existing(self, work_item_id: str) -> dict[str, Any]:
        item = self.gateway.execute("get_work_item", {"work_item_id": work_item_id})
        return {
            "schema_version": "app_submission_work_item_reference.v1",
            "work_item_id": item["work_item_id"],
            "task_version": item["current_task_version"],
            "state": item["state"],
            "can_write_ledger_directly": False,
        }
