from __future__ import annotations

import sys
from typing import Callable, TextIO


def run_registry_add(
    args: list[str],
    *,
    usage_message: str,
    resolve_path_func: Callable[[str], str],
    registry_factory: Callable[[], object],
    project_mode_managed: str,
    simple_start_modes: set[str],
    global_config_store_factory: Callable[[], object],
    prompt_initial_global_config_func: Callable[..., dict[str, object]],
    ensure_minimal_runner_managed_project_func: Callable[[str], dict[str, object]],
    stderr: TextIO | None = None,
    stdout: TextIO | None = None,
    stdin=None,
    getpass_module=None,
    json_dumps_func: Callable[[object], str] | None = None,
) -> int:
    target_stderr = stderr or sys.stderr
    target_stdout = stdout or sys.stdout
    input_stdin = stdin or sys.stdin
    if len(args) < 2:
        print("add 参数不足。", file=target_stderr)
        print(usage_message, file=target_stderr)
        return 1
    if len(args) == 2:
        project_path = resolve_path_func(args[1])
        project_name = project_path.rstrip("/").split("/")[-1]
        project_mode = project_mode_managed
    elif len(args) == 3:
        second_arg = args[1]
        third_arg = args[2]
        if third_arg in simple_start_modes:
            project_path = resolve_path_func(second_arg)
            project_name = project_path.rstrip("/").split("/")[-1]
            project_mode = third_arg
        else:
            project_name = second_arg
            project_path = resolve_path_func(third_arg)
            project_mode = project_mode_managed
    elif len(args) >= 4:
        project_name = args[1]
        project_path = resolve_path_func(args[2])
        project_mode = args[3]
    else:
        print("add 参数格式不正确。", file=target_stderr)
        print(usage_message, file=target_stderr)
        return 1

    registry = registry_factory()
    store = global_config_store_factory()
    setup_status = store.needs_interactive_setup()
    if setup_status.get("ok") and setup_status.get("needs_setup"):
        missing = ", ".join(str(item) for item in setup_status.get("missing_fields", []))
        if input_stdin.isatty():
            getpass_func = getpass_module.getpass if getpass_module is not None else None
            result = prompt_initial_global_config_func(
                store,
                input_func=input,
                getpass_func=getpass_func,
                stderr=target_stderr,
            )
            if not result.get("ok"):
                print(str(result.get("message") or "Runner 全局配置初始化失败。"), file=target_stderr)
                return 1
        else:
            print(f"警告：Runner 全局配置缺失（{missing}）。", file=target_stderr)
            print("启动项目时需要 --public-base-url / --auth-mode / --auth-token，或预先写入 ~/.config/colameta/ 全局配置。", file=target_stderr)

    json_dumps = json_dumps_func or (lambda payload: str(payload))
    try:
        clean_mode = registry.validate_project_mode(project_mode)
        if clean_mode == project_mode_managed:
            ensure_result = ensure_minimal_runner_managed_project_func(project_path)
            if not ensure_result.get("ok"):
                message = str(ensure_result.get("message") or "自动创建最小 Runner 结构失败。")
                print(json_dumps({"ok": False, "error_code": "REGISTRY_ADD_FAILED", "message": message}), file=target_stdout)
                return 1
        result = registry.register_project(
            project_path,
            project_name=project_name,
            project_mode=clean_mode,
            last_selected=True,
        )
    except ValueError as exc:
        print(json_dumps({"ok": False, "error_code": "REGISTRY_ADD_FAILED", "message": str(exc)}), file=target_stdout)
        return 1
    project = result.get("project", {})
    if isinstance(project, dict):
        name = project.get("project_name", project_name)
        path = project.get("project_root", project_path)
        mode = project.get("project_mode", clean_mode)
        print("\u2705  Project registered", file=target_stderr)
        print(f"\U0001f9e9  Name: {name}", file=target_stderr)
        print(f"\U0001f4c1  Path: {path}", file=target_stderr)
        print(f"\U0001f30d  Mode: {mode}", file=target_stderr)
    return 0


def run_registry_list(
    args: list[str],
    *,
    usage_message: str,
    registry_factory: Callable[[], object],
    json_dumps_func: Callable[[object], str],
    stderr: TextIO | None = None,
    stdout: TextIO | None = None,
) -> int:
    target_stderr = stderr or sys.stderr
    target_stdout = stdout or sys.stdout
    if len(args) != 1:
        print("list 不接受额外参数。", file=target_stderr)
        print(usage_message, file=target_stderr)
        return 1
    result = registry_factory().list_projects()
    print(json_dumps_func(result), file=target_stdout)
    return 0


def run_registry_remove(
    args: list[str],
    *,
    usage_message: str,
    registry_factory: Callable[[], object],
    json_dumps_func: Callable[[object], str],
    stderr: TextIO | None = None,
    stdout: TextIO | None = None,
) -> int:
    target_stderr = stderr or sys.stderr
    target_stdout = stdout or sys.stdout
    if len(args) < 2:
        print("remove 缺少项目名称或项目路径。", file=target_stderr)
        print(usage_message, file=target_stderr)
        return 1
    if len(args) > 2:
        print("remove 仅支持一个项目名称或项目路径。", file=target_stderr)
        print(usage_message, file=target_stderr)
        return 1
    identifier = args[1]
    registry = registry_factory()
    result = registry.unregister_project(project_name=identifier)
    if not result.get("ok"):
        result = registry.unregister_project(project_root=identifier)
    print(json_dumps_func(result), file=target_stdout)
    return 0 if result.get("ok") else 1
