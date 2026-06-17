import os
from dataclasses import dataclass

from runner.runner_paths import resolve_project_runner_dir


@dataclass
class ProjectWorkspace:
    workspace_root: str
    runner_dir: str
    prompts_dir: str
    runtime_dir: str
    logs_dir: str
    backup_dir: str
    plan_file: str
    state_file: str
    rules_file: str

    @classmethod
    def from_project_path(cls, project_path: str) -> "ProjectWorkspace":
        workspace_root = os.path.abspath(os.path.expanduser(project_path))
        runner_dir = resolve_project_runner_dir(workspace_root)
        return cls(
            workspace_root=workspace_root,
            runner_dir=runner_dir,
            prompts_dir=os.path.join(runner_dir, "prompts"),
            runtime_dir=os.path.join(runner_dir, "runtime"),
            logs_dir=os.path.join(runner_dir, "logs"),
            backup_dir=os.path.join(runner_dir, "backup"),
            plan_file=os.path.join(runner_dir, "plan.json"),
            state_file=os.path.join(runner_dir, "state.json"),
            rules_file=os.path.join(runner_dir, "rules.md"),
        )

    def ensure_directories(self) -> None:
        for path in (
            self.runner_dir,
            self.prompts_dir,
            self.runtime_dir,
            self.logs_dir,
            self.backup_dir,
        ):
            os.makedirs(path, exist_ok=True)
