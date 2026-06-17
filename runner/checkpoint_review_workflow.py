import json
import os
from pathlib import Path
from typing import Any

from runner.workspace import ProjectWorkspace
from runner.plan_loader import PlanLoader
from runner.state_store import StateStore
from runner.stage_reviewer import StageReviewer


class CheckpointReviewService:
    def __init__(self, project_root: str):
        self.project_root = project_root

    def run_review(self) -> dict[str, Any]:
        workspace = ProjectWorkspace.from_project_path(self.project_root)
        workspace.ensure_directories()
        loader = PlanLoader()
        plan = loader.load_plan(workspace.plan_file)
        plan.project_root = workspace.workspace_root
        plan.logs_dir = workspace.logs_dir
        plan.runtime_dir = workspace.runtime_dir
        plan.state_file = workspace.state_file
        if not os.path.isabs(plan.rules_file):
            plan.rules_file = workspace.rules_file
        loader.validate_plan(plan)
        store = StateStore()
        state = store.load_state(workspace.state_file)

        reviewer = StageReviewer(workspace=workspace)
        try:
            review_result = reviewer.run_review()
        except Exception as e:
            return {
                "ok": False,
                "action": "checkpoint_review",
                "error_code": "REVIEW_FAILED",
                "message": str(e),
            }

        review_file = resolve_project_runner_path(self.project_root, "review-state.json")
        payload = {
            "last_reviewed_version": state.current_version if state.current_version else "",
            "last_review_file": review_result.report_path,
            "last_reviewed_at": review_result.reviewed_at,
        }
        Path(review_file).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        return {
            "ok": True,
            "action": "checkpoint_review",
            "message": "阶段审查完成。",
            "report_path": review_result.report_path,
            "log_path": review_result.log_path,
            "summary": review_result.short_summary,
            "reviewed_at": review_result.reviewed_at,
            "last_reviewed_version": state.current_version,
            "review_state_file": review_file,
        }
from runner.runner_paths import resolve_project_runner_path
