import json
import os
from pathlib import Path
from typing import Any

from runner.planning_bridge import PlanningBridge, PlanningBridgeError

MAX_FILE_BYTES = 512 * 1024

_NORMAL_OPERATIONS = {
    "insert": "insert_version",
    "insert_version": "insert_version",
    "update": "update_version",
    "update_version": "update_version",
}


class PlanFileImportError(ValueError):
    pass


def _normalize_operation(value: str) -> str:
    norm = value.strip().lower()
    result = _NORMAL_OPERATIONS.get(norm)
    if result is None:
        raise PlanFileImportError(
            f"不支持的 operation：{value}。仅支持 insert、update、insert_version 和 update_version。",
        )
    return result


def load_plan_patch_file(file_path: str) -> dict[str, Any]:
    abs_path = os.path.abspath(os.path.expanduser(file_path))
    if not os.path.exists(abs_path):
        raise PlanFileImportError(f"文件不存在：{file_path}")
    if os.path.isdir(abs_path):
        raise PlanFileImportError(f"路径是目录，不是文件：{file_path}")

    try:
        stat = os.stat(abs_path)
    except OSError as e:
        raise PlanFileImportError(f"无法读取文件：{e}") from e

    if stat.st_size > MAX_FILE_BYTES:
        raise PlanFileImportError(f"文件过大（{stat.st_size} 字节），最大支持 {MAX_FILE_BYTES} 字节。")

    raw_bytes = Path(abs_path).read_bytes()
    if b"\0" in raw_bytes:
        raise PlanFileImportError("文件包含 NUL 字节，疑似二进制文件。")
    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        raise PlanFileImportError("文件不是 UTF-8 编码文本文件。")

    if not text.strip():
        raise PlanFileImportError("文件内容为空。")

    try:
        spec = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PlanFileImportError(f"JSON 格式错误：第 {exc.lineno} 行第 {exc.colno} 列，{exc.msg}") from exc

    if not isinstance(spec, dict):
        raise PlanFileImportError("JSON 根对象必须是 JSON 对象。")

    return spec


def _check_field_conflict(
    spec: dict[str, Any], cli_value: str | None, field: str, cli_label: str,
) -> None:
    if cli_value is not None:
        file_value = spec.get(field)
        if file_value is not None and str(file_value).strip() != cli_value:
            raise PlanFileImportError(
                f"CLI 参数 {cli_label}={cli_value} 与文件内容 {field}={file_value} 冲突，请保持一致。",
            )


def preview_plan_file_import(
    project_path: str,
    file_path: str,
    mode: str | None = None,
    insert_after: str | None = None,
    version: str | None = None,
) -> dict[str, Any]:
    spec = load_plan_patch_file(file_path)
    file_op = str(spec.get("operation") or "").strip()
    if not file_op and not mode:
        raise PlanFileImportError("缺少 operation 字段。operation 必须是 insert、update、insert_version 或 update_version。")
    raw_operation = (mode or file_op)
    operation = _normalize_operation(raw_operation)

    file_normalized = _normalize_operation(file_op) if file_op else None
    mode_normalized = _normalize_operation(mode) if mode else None
    if file_normalized and mode_normalized and file_normalized != mode_normalized:
        raise PlanFileImportError(
            f"CLI 参数 --mode={mode} 与文件内容 operation={file_op} 冲突，请保持一致。",
        )

    _check_field_conflict(spec, insert_after, "insert_after", "--insert-after")
    _check_field_conflict(spec, version, "version", "--version")

    spec_for_bridge: dict[str, Any] = {}
    for key, value in spec.items():
        if key == "operation":
            continue
        spec_for_bridge[key] = value

    if insert_after is not None:
        spec_for_bridge["insert_after"] = insert_after
    if version is not None:
        spec_for_bridge["version"] = version

    if not os.path.isdir(os.path.abspath(os.path.expanduser(project_path))):
        raise PlanFileImportError(f"项目目录不存在：{project_path}")

    bridge = PlanningBridge()
    try:
        if operation == "insert_version":
            result = bridge.preview_insert_version(project_path, spec_for_bridge)
        else:
            result = bridge.preview_update_version(project_path, spec_for_bridge)
    except PlanningBridgeError as e:
        raise PlanFileImportError(str(e)) from e

    if not isinstance(result, dict):
        raise PlanFileImportError("导入失败：未返回有效预览结果。")

    patch_id = result.get("patch_id", "未知")
    patch_path = result.get("patch_path", "")

    operation_display = "insert_version" if operation == "insert_version" else "update_version"
    return {
        "ok": True,
        "operation": operation_display,
        "patch_id": patch_id,
        "patch_file": patch_path,
        "version": spec_for_bridge.get("version"),
        "message": "计划变更已生成，Web Console 会自动接收。",
    }
