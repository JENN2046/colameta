from __future__ import annotations

import os
from typing import Any

from runner.planning_bridge import PlanningBridge


class PlanPatchAutoApplyService:
    def __init__(self, project_root: str):
        self.project_root = os.path.abspath(os.path.expanduser(project_root))
        self._bridge = PlanningBridge()

    def auto_apply(self) -> dict[str, Any]:
        try:
            data = self._bridge.auto_apply_pending_plan_patches(self.project_root, limit=5)
        except Exception as e:
            return {
                "ok": False,
                "message": str(e),
                "results": [],
                "applied_count": 0,
                "failed_count": 0,
                "skipped_count": 0,
            }
        data["ok"] = True
        return data
