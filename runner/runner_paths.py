from __future__ import annotations

import os
from collections.abc import Iterable


PRIMARY_PROJECT_RUNNER_DIRNAME = ".colameta"
PRIMARY_USER_CONFIG_DIRNAME = "colameta"


def _abs_expand(path: str) -> str:
    return os.path.abspath(os.path.expanduser(path))


def resolve_project_runner_dir(project_root: str) -> str:
    return os.path.join(_abs_expand(project_root), PRIMARY_PROJECT_RUNNER_DIRNAME)


def resolve_project_runner_rel_dir(project_root: str) -> str:
    return os.path.basename(resolve_project_runner_dir(project_root))


def resolve_project_runner_plan_path(project_root: str) -> str:
    return os.path.join(resolve_project_runner_dir(project_root), "plan.json")


def resolve_project_runner_path(project_root: str, *parts: str) -> str:
    return os.path.join(resolve_project_runner_dir(project_root), *parts)


def primary_project_runner_dir(project_root: str) -> str:
    return resolve_project_runner_dir(project_root)


def primary_project_runner_path(project_root: str, *parts: str) -> str:
    return os.path.join(primary_project_runner_dir(project_root), *parts)


def primary_project_runner_relpath(*parts: str) -> str:
    return os.path.join(PRIMARY_PROJECT_RUNNER_DIRNAME, *parts)


def project_runner_dirnames() -> tuple[str]:
    return (PRIMARY_PROJECT_RUNNER_DIRNAME,)


def is_project_runner_path(path: str) -> bool:
    normalized = path.strip().replace("\\", "/").strip("/")
    return (
        normalized == PRIMARY_PROJECT_RUNNER_DIRNAME
        or normalized.startswith(PRIMARY_PROJECT_RUNNER_DIRNAME + "/")
    )


def is_project_runner_subpath(path: str, subpaths: Iterable[str]) -> bool:
    normalized = path.strip().replace("\\", "/").strip("/")
    for subpath in subpaths:
        candidate = f"{PRIMARY_PROJECT_RUNNER_DIRNAME}/{subpath.strip('/')}"
        if normalized == candidate or normalized.startswith(candidate + "/"):
            return True
    return False


def user_config_dir() -> str:
    xdg_config_home = os.environ.get("XDG_CONFIG_HOME", "").strip()
    if xdg_config_home:
        base = _abs_expand(xdg_config_home)
    else:
        base = _abs_expand(os.path.join("~", ".config"))
    return os.path.join(base, PRIMARY_USER_CONFIG_DIRNAME)


def resolve_user_config_dir() -> str:
    return user_config_dir()
