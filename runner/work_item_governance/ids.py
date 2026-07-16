from __future__ import annotations

import os
import time
import uuid

from runner.work_item_governance.contracts import ID_PREFIXES, UUID7_TEXT_PATTERN
from runner.work_item_governance.errors import WorkItemGovernanceError


def new_uuid7(*, timestamp_ms: int | None = None, random_bytes: bytes | None = None) -> uuid.UUID:
    """Create an RFC 9562 UUIDv7 without requiring Python 3.14's uuid.uuid7."""

    millis = int(time.time_ns() // 1_000_000 if timestamp_ms is None else timestamp_ms)
    if millis < 0 or millis >= 1 << 48:
        raise WorkItemGovernanceError("UUID7_TIMESTAMP_INVALID", "UUIDv7 timestamp must fit in 48 bits.")
    entropy = os.urandom(10) if random_bytes is None else random_bytes
    if len(entropy) != 10:
        raise WorkItemGovernanceError(
            "UUID7_ENTROPY_INVALID",
            "UUIDv7 requires exactly 10 bytes of entropy.",
            details={"actual_bytes": len(entropy)},
        )
    raw = bytearray(millis.to_bytes(6, "big") + entropy)
    raw[6] = (raw[6] & 0x0F) | 0x70
    raw[8] = (raw[8] & 0x3F) | 0x80
    return uuid.UUID(bytes=bytes(raw))


def new_stable_id(kind: str) -> str:
    try:
        prefix = ID_PREFIXES[kind]
    except KeyError as exc:
        raise WorkItemGovernanceError(
            "ID_KIND_UNSUPPORTED",
            "Stable identifier kind is unsupported.",
            details={"kind": kind, "supported": sorted(ID_PREFIXES)},
        ) from exc
    return f"{prefix}_{new_uuid7()}"


def is_stable_id(value: object, kind: str) -> bool:
    if not isinstance(value, str) or kind not in ID_PREFIXES:
        return False
    import re

    return re.fullmatch(rf"{re.escape(ID_PREFIXES[kind])}_{UUID7_TEXT_PATTERN}", value) is not None
