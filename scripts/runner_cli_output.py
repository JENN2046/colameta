from __future__ import annotations

import sys
import unicodedata
from typing import Callable, TextIO


COLAMATE_BANNER_WIDTH = 60
COLAMATE_BANNER_ART = (
    "   ______      __                      __",
    "  / ____/___  / /___ _____ ___  ____ _/ /____",
    " / /   / __ \\/ / __ `/ __ `__ \\/ __ `/ __/ _ \\",
    "/ /___/ /_/ / / /_/ / / / / / / /_/ / /_/  __/",
    "\\____/\\____/_/\\__,_/_/ /_/ /_/\\__,_/\\__/\\___/",
)
COLAMATE_BANNER_SLOGAN = "🥤 enjoy your vibe coding with GPTs! ✨"
COLAMATE_BANNER_ART_COLOR = "\033[32m"
COLAMATE_BANNER_COLOR_RESET = "\033[0m"


def _terminal_cell_width(text: str) -> int:
    width = 0
    index = 0
    while index < len(text):
        char = text[index]
        if char == "\033" and index + 1 < len(text) and text[index + 1] == "[":
            index += 2
            while index < len(text) and not text[index].isalpha():
                index += 1
            index += 1
            continue
        if unicodedata.combining(char):
            index += 1
            continue
        if unicodedata.category(char) in {"Mn", "Me", "Cf"}:
            index += 1
            continue
        width += 2 if unicodedata.east_asian_width(char) in {"F", "W"} else 1
        index += 1
    return width


def _pad_text_to_width(text: str, width: int) -> str:
    padding = max(width - _terminal_cell_width(text), 0)
    return text + " " * padding


def _center_text(text: str, width: int) -> str:
    padding = max(width - _terminal_cell_width(text), 0)
    left_padding = padding // 2
    return " " * left_padding + text + " " * (padding - left_padding)


def _colorize_colamate_art(line: str) -> str:
    return f"{COLAMATE_BANNER_ART_COLOR}{line}{COLAMATE_BANNER_COLOR_RESET}"


def _center_block(lines: tuple[str, ...], width: int) -> list[str]:
    block_width = max(_terminal_cell_width(line) for line in lines)
    left_padding = max((width - block_width) // 2, 0)
    return [" " * left_padding + line for line in lines]


def _format_colamate_banner(*, color_art: bool = False) -> str:
    border = "+" + "-" * COLAMATE_BANNER_WIDTH + "+"
    content_width = COLAMATE_BANNER_WIDTH - 2
    art_lines = _center_block(COLAMATE_BANNER_ART, content_width)
    if color_art:
        art_lines = [_colorize_colamate_art(line) for line in art_lines]
    body_lines = [
        "",
        *art_lines,
        "",
        _center_text(COLAMATE_BANNER_SLOGAN, content_width),
        "",
    ]
    boxed_lines = [f"| {_pad_text_to_width(line, content_width)} |" for line in body_lines]
    return "\n".join([border, *boxed_lines, border])


COLAMATE_BANNER = _format_colamate_banner()
COLAMATE_BANNER_COLORED = _format_colamate_banner(color_art=True)


def print_colamate_banner(*, stderr: TextIO | None = None) -> None:
    target = stderr or sys.stderr
    banner = COLAMATE_BANNER_COLORED if getattr(target, "isatty", lambda: False)() else COLAMATE_BANNER
    print(banner, file=target)


def print_line(label: str, text: str, *, stderr: TextIO | None = None) -> None:
    target = stderr or sys.stderr
    print(f"  {label}: {text}", file=target)


def print_mcp_auth_status(auth_mode: str, public_base_url: str | None = None, *, stderr: TextIO | None = None) -> None:
    del public_base_url
    target = stderr or sys.stderr
    if auth_mode == "none":
        print("  Auth: disabled", file=target)
    elif auth_mode == "token":
        print("  Auth: Bearer token enabled", file=target)
    elif auth_mode == "oauth":
        print("  Auth: OAuth enabled", file=target)


def print_registry_project_list(
    *,
    registry_factory: Callable[[], object],
    stderr: TextIO | None = None,
) -> None:
    target = stderr or sys.stderr
    registry = registry_factory()
    result = registry.list_projects()
    projects = result.get("projects", []) if result.get("ok") else []
    if projects:
        print("📎  当前关联项目：", file=target)
        for project in projects:
            if not isinstance(project, dict):
                continue
            project_name = project.get("project_name", "")
            project_root = project.get("project_root", "")
            if project_name and project_root:
                print(f"    • {project_name}  {project_root}", file=target)
        return
    print("📎  当前关联项目：无", file=target)


def print_default_start_summary(
    *,
    project_path: str,
    web_host: str,
    web_port: int,
    mcp_host: str,
    mcp_port: int,
    public_base_url: str | None,
    public_base_url_source: str,
    enable_web: bool,
    enable_mcp: bool,
    open_web: bool,
    web_disabled_reason: str | None = None,
    stderr: TextIO | None = None,
) -> None:
    del public_base_url_source, open_web, web_disabled_reason
    target = stderr or sys.stderr
    print_colamate_banner(stderr=target)
    print(f"\U0001f9e9  Project: {project_path}", file=target)
    if enable_web:
        display_url = public_base_url or f"http://{web_host}:{web_port}"
        print(f"\U0001f310  Web Console: {display_url}", file=target)
    if enable_mcp:
        if public_base_url:
            print(f"\u2699\ufe0f  Actions API: {public_base_url.rstrip('/')}/openapi.json", file=target)
        mcp_url = f"http://{mcp_host}:{mcp_port}/mcp"
        print(f"\U0001f50c  MCP Endpoint: {mcp_url}", file=target)
    print("\U0001f510  Auth: OAuth enabled", file=target)
    print("\u2705  Ready. Press Ctrl-C to stop.", file=target)


def print_service_start_summary(
    *,
    project_path: str,
    pid: int,
    web_url: str | None,
    mcp_url: str | None,
    log_path: str,
    start_command: str,
    status_command: str,
    stop_command: str,
    stderr: TextIO | None = None,
) -> None:
    target = stderr or sys.stderr
    print_colamate_banner(stderr=target)
    print(f"\U0001f9e9  Project: {project_path}", file=target)
    print(f"\U0001f9f5  PID: {pid}", file=target)
    if web_url:
        print(f"\U0001f310  Web Console: {web_url}", file=target)
    if mcp_url:
        print(f"\U0001f50c  MCP Endpoint: {mcp_url}", file=target)
    print(f"\U0001f4dd  Log: {log_path}", file=target)
    print("\u2705  ColaMeta service 已在后台启动。", file=target)
    print(f"  查看状态: {status_command}", file=target)
    print(f"  停止服务: {stop_command}", file=target)
    print(f"  前台调试: {start_command}", file=target)


def print_service_status_summary(
    *,
    project_path: str,
    pid: int | None,
    state: str,
    web_url: str | None,
    web_state: str | None,
    mcp_url: str | None,
    mcp_state: str | None,
    log_path: str | None,
    stderr: TextIO | None = None,
) -> None:
    target = stderr or sys.stderr
    print(f"\U0001f9e9  Project: {project_path}", file=target)
    print(f"\U0001f4ca  Status: {state}", file=target)
    if pid is not None:
        print(f"\U0001f9f5  PID: {pid}", file=target)
    if web_url:
        print(f"\U0001f310  Web Console: {web_url} ({web_state or 'unknown'})", file=target)
    if mcp_url:
        print(f"\U0001f50c  MCP Endpoint: {mcp_url} ({mcp_state or 'unknown'})", file=target)
    if log_path:
        print(f"\U0001f4dd  Log: {log_path}", file=target)
