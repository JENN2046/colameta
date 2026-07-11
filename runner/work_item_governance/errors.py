from __future__ import annotations

from typing import Any


class WorkItemGovernanceError(ValueError):
    """A fail-closed, machine-readable Work Item Governance error."""

    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": str(self),
            "details": self.details,
        }


class CommitWorkItemRejection(Exception):
    """Commit control-plane evidence, then surface the contained domain error.

    Only the Activation Lease guard uses this path, and only before a domain
    mutation has occurred in the surrounding transaction.
    """

    def __init__(self, error: WorkItemGovernanceError) -> None:
        super().__init__(str(error))
        self.error = error
