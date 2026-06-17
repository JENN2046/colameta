from typing import Any


def ok_result(action: str | None = None, **fields: Any) -> dict[str, Any]:
    result: dict[str, Any] = {"ok": True}
    if action is not None:
        result["action"] = action
    result.update(fields)
    return result


def error_result(error_code: str, message: str, **fields: Any) -> dict[str, Any]:
    result: dict[str, Any] = {"ok": False, "error_code": error_code, "message": message}
    result.update(fields)
    return result


def preview_result(action: str, preview_id: str, **fields: Any) -> dict[str, Any]:
    return ok_result(action, preview_id=preview_id, **fields)


def apply_result(action: str, preview_id: str, **fields: Any) -> dict[str, Any]:
    return ok_result(action, preview_id=preview_id, **fields)


def status_result(action: str, preview_id: str, **fields: Any) -> dict[str, Any]:
    return ok_result(action, preview_id=preview_id, **fields)
