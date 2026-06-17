from typing import Any


MANUAL_ACCEPTANCE_KEYWORDS = (
    "manual acceptance",
    "人工验收",
    "人工验证",
    "已人工确认",
    "人工确认",
    "用户确认",
    "用户已确认",
    "用户确认验收",
    "用户已验收",
)


def detect_manual_acceptance(reason: str | None) -> dict[str, Any]:
    if not isinstance(reason, str) or not reason.strip():
        return {"present": False, "source": None, "note": None}
    normalized = reason.lower()
    for keyword in MANUAL_ACCEPTANCE_KEYWORDS:
        if keyword.lower() in normalized:
            return {"present": True, "source": "reason", "note": reason[:200]}
    return {"present": False, "source": None, "note": None}
