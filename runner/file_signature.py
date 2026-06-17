import hashlib
from typing import Any


def sha256_text(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def text_signature(content: str) -> dict[str, Any]:
    return {
        "sha256": sha256_text(content),
        "size": len(content.encode("utf-8")),
    }


def signatures_equal(a: Any, b: Any) -> bool:
    return isinstance(a, dict) and isinstance(b, dict) and a == b
