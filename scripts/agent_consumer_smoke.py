from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runner.mcp_server import MCPPlanningBridgeServer  # noqa: E402
from runner.project_registry import ProjectRegistry  # noqa: E402


EXPECTED_PROFILE_IDS = (
    "web_gpt_commander",
    "local_codex_commander",
    "reviewer_agent",
    "planner_agent",
    "source_observer",
)


class AgentConsumerSmokeError(RuntimeError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AgentConsumerSmokeError(message)


def _require_outer_ok(result: dict[str, Any], tool_name: str) -> dict[str, Any]:
    _require(result.get("ok") is True, f"{tool_name} failed: {result}")
    _require(result.get("tool") == tool_name, f"{tool_name} returned unexpected tool name")
    data = result.get("data")
    _require(isinstance(data, dict), f"{tool_name} returned non-object data")
    return data


def run_agent_consumer_smoke(project_root: str | Path, *, project_name: str = "colameta-self-dev") -> dict[str, Any]:
    root = Path(project_root).resolve()
    _require(root.is_dir(), f"project_root does not exist: {root}")

    with tempfile.TemporaryDirectory(prefix="colameta-agent-consumer-smoke-") as temp_name:
        temp_dir = Path(temp_name)
        registry = ProjectRegistry(
            registry_path=str(temp_dir / "project-registry.json"),
            user_settings_path=str(temp_dir / "settings.json"),
        )
        registration = registry.register_project(str(root), project_name=project_name)
        _require(registration.get("ok") is True, f"project registration failed: {registration}")
        registered_project = registration.get("project") or {}
        effective_project_name = str(registered_project.get("project_name") or project_name)

        server = MCPPlanningBridgeServer(str(root), service_mode=True)
        server.project_registry = registry
        visible_tools = set(server._visible_tool_names())

        required_tools = {
            "list_registered_projects",
            "get_agent_consumer_contract",
            "get_service_entry_profile",
            "get_web_gpt_service_entrypoint",
            "get_stable_promotion_readiness",
            "analyze_project_state",
        }
        missing_tools = sorted(required_tools - visible_tools)
        _require(not missing_tools, f"missing visible tools: {missing_tools}")

        listed = _require_outer_ok(server.call_tool_for_agent("list_registered_projects", {}), "list_registered_projects")
        project_names = [
            item.get("project_name")
            for item in listed.get("projects", [])
            if isinstance(item, dict)
        ]
        _require(effective_project_name in project_names, f"registered project not listed: {effective_project_name}")

        contract = _require_outer_ok(
            server.call_tool_for_agent("get_agent_consumer_contract", {}),
            "get_agent_consumer_contract",
        )
        _require(contract.get("contract_version") == "agent_consumer_contract.v1", "unexpected contract version")
        contract_profiles = [
            item.get("profile_id")
            for item in contract.get("service_entry_profiles", [])
            if isinstance(item, dict)
        ]
        _require(tuple(contract_profiles) == EXPECTED_PROFILE_IDS, f"unexpected profile ids: {contract_profiles}")

        profile_results: dict[str, dict[str, Any]] = {}
        for profile_id in EXPECTED_PROFILE_IDS:
            data = _require_outer_ok(
                server.call_tool_for_agent("get_service_entry_profile", {"profile_id": profile_id}),
                "get_service_entry_profile",
            )
            _require(data.get("profile_id") == profile_id, f"profile selector returned wrong profile: {profile_id}")
            _require(data.get("read_only") is True, f"profile selector is not read-only: {profile_id}")
            selected = data.get("selected_profile")
            _require(isinstance(selected, dict), f"profile selector missing selected_profile: {profile_id}")
            _require(selected.get("profile_id") == profile_id, f"selected profile mismatch: {profile_id}")
            profile_results[profile_id] = {
                "consumer_kind": selected.get("consumer_kind"),
                "authority": data.get("authority"),
                "first_read_count": len(selected.get("first_reads", [])),
            }

        invalid_profile = server.call_tool_for_agent("get_service_entry_profile", {"profile_id": "invalid_profile"})
        _require(invalid_profile.get("ok") is False, "invalid profile did not fail closed")
        _require(
            invalid_profile.get("error_code") == "UNKNOWN_SERVICE_ENTRY_PROFILE",
            f"unexpected invalid profile error: {invalid_profile}",
        )

        entry = _require_outer_ok(
            server.call_tool_for_agent(
                "get_web_gpt_service_entrypoint",
                {"project_name": effective_project_name},
            ),
            "get_web_gpt_service_entrypoint",
        )
        entry_profiles = [
            item.get("profile_id")
            for item in entry.get("service_entry_profiles", [])
            if isinstance(item, dict)
        ]
        _require(tuple(entry_profiles) == EXPECTED_PROFILE_IDS, f"entry profile ids diverged: {entry_profiles}")

        readiness = _require_outer_ok(
            server.call_tool_for_agent(
                "get_stable_promotion_readiness",
                {"project_name": effective_project_name},
            ),
            "get_stable_promotion_readiness",
        )
        tool_support = readiness.get("tool_support") if isinstance(readiness.get("tool_support"), dict) else {}
        _require(tool_support.get("missing_visible_tools") == [], f"missing readiness tools: {tool_support}")
        _require(tool_support.get("agent_consumer_contract_visible") is True, "contract tool not visible")
        _require(tool_support.get("service_entry_profile_visible") is True, "profile selector not visible")

        project_state = _require_outer_ok(
            server.call_tool_for_agent("analyze_project_state", {"project_name": effective_project_name}),
            "analyze_project_state",
        )
        _require(project_state.get("read_only") is True, "project state analysis is not read-only")
        _require(project_state.get("side_effects") is False, "project state analysis declares side effects")

        return {
            "ok": True,
            "project_root": str(root),
            "project_name": effective_project_name,
            "visible_required_tools": sorted(required_tools),
            "profile_ids": list(EXPECTED_PROFILE_IDS),
            "profile_results": profile_results,
            "entry_profiles_match_contract": entry_profiles == contract_profiles,
            "invalid_profile_fail_closed": True,
            "readiness_status": readiness.get("readiness_status"),
            "readiness_missing_tools": tool_support.get("missing_visible_tools"),
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a read-only ColaMeta agent consumer smoke test.")
    parser.add_argument("--project-root", default=str(ROOT), help="Project root to register in a temporary registry.")
    parser.add_argument("--project-name", default="colameta-self-dev", help="Temporary registry project_name.")
    args = parser.parse_args(argv)

    try:
        result = run_agent_consumer_smoke(args.project_root, project_name=args.project_name)
    except AgentConsumerSmokeError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
