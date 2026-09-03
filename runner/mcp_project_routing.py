from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


@dataclass(frozen=True)
class ProjectRouteContext:
    project_root: str
    public_project_name: str | None
    require_managed: bool


class _ProjectRouteBindingPolicy(Enum):
    TOOL_ROUTE_CONTINUATIONS = "tool_route_continuations"
    OPERATOR_TARGET_ISOLATED = "operator_target_isolated"


TOOL_ROUTE_CONTINUATIONS = _ProjectRouteBindingPolicy.TOOL_ROUTE_CONTINUATIONS
OPERATOR_TARGET_ISOLATED = _ProjectRouteBindingPolicy.OPERATOR_TARGET_ISOLATED


class ProjectRouteServerFactory:
    def __init__(self, serving_server: Any):
        self._serving_server = serving_server

    def create(
        self,
        context: ProjectRouteContext,
        binding_policy: _ProjectRouteBindingPolicy,
    ) -> Any:
        if binding_policy not in {
            TOOL_ROUTE_CONTINUATIONS,
            OPERATOR_TARGET_ISOLATED,
        }:
            raise ValueError(f"Unsupported project route binding policy: {binding_policy!r}")

        constructor_kwargs: dict[str, Any] = {}
        if binding_policy is TOOL_ROUTE_CONTINUATIONS:
            # A project-routed public tool is still served through the same
            # exposure surface. Preserve that profile so nested routing and
            # Agent UX projection cannot advertise tools hidden from the
            # caller. Operator targets intentionally remain isolated below.
            constructor_kwargs["exposure_profile"] = (
                self._serving_server.mcp_exposure_profile
            )
        routed_server = self._serving_server.__class__(
            context.project_root,
            **constructor_kwargs,
        )
        if binding_policy is TOOL_ROUTE_CONTINUATIONS:
            # Read these stores for every routed server creation. The serving
            # process can replace either store at runtime.
            routed_server._mcp_result_artifact_store = (
                self._serving_server._mcp_result_artifact_store
            )
            routed_server._gate_review_preview_store = (
                self._serving_server._gate_review_preview_store
            )
        return routed_server
