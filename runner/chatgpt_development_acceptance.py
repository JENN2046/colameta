"""Repeatable local rehearsal for the ChatGPT Commander contract.

This module deliberately tests the same compact MCP contract a ChatGPT
development connector uses, but it runs entirely against an in-process,
temporary Git checkout.  It is therefore a *contract rehearsal*, not evidence
that a live ChatGPT session, OAuth connection, tunnel, runtime, or stable
service has been accepted.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
from typing import Any

from runner.mcp_commander_public import (
    COMMANDER_EXPOSED_TOOLS,
    COMMANDER_LOCAL_CODEX_ADVANCED_TOOL_EXAMPLES,
)
from runner.mcp_result_artifacts import MCPResultArtifactStore
from runner.mcp_server import MCPPlanningBridgeServer
from runner.p1_release_gate import build_p1_client_release_gate
from runner.review_manifest import (
    REVIEW_MANIFEST_SCHEMA_VERSION,
    REVIEW_MANIFEST_WORKFLOW_INTENT,
    collect_review_context_binding,
)


CHATGPT_DEVELOPMENT_CONTRACT_REHEARSAL_SCHEMA_VERSION = (
    "colameta.chatgpt_development_contract_rehearsal.v1"
)


class ChatGPTDevelopmentContractRehearsalError(RuntimeError):
    """Raised when the local ChatGPT contract rehearsal fails."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ChatGPTDevelopmentContractRehearsalError(message)


def _tool_data(
    server: MCPPlanningBridgeServer,
    trace: list[dict[str, Any]],
    tool_name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    trace.append(
        {
            "method": "tools/call",
            "tool": tool_name,
            "arguments": sorted(arguments),
        }
    )
    result = server.call_tool_for_agent(tool_name, arguments)
    _require(result.get("ok") is True, f"{tool_name} failed: {result}")
    _require(result.get("tool") == tool_name, f"{tool_name} returned an unexpected tool name")
    data = result.get("data")
    _require(isinstance(data, dict), f"{tool_name} returned non-object data")
    _require(
        data.get("schema_version") == "commander_response.v1",
        f"{tool_name} returned an unexpected public schema",
    )
    return data


def _contract_object(
    contract: dict[str, Any],
    field: str,
) -> dict[str, Any]:
    value = contract.get(field)
    _require(isinstance(value, dict), f"Commander contract omitted object field {field}")
    return value


def _tool_error(
    server: MCPPlanningBridgeServer,
    trace: list[dict[str, Any]],
    tool_name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    trace.append(
        {
            "method": "tools/call",
            "tool": tool_name,
            "arguments": sorted(arguments),
        }
    )
    result = server.call_tool_for_agent(tool_name, arguments)
    _require(result.get("ok") is False, f"{tool_name} unexpectedly succeeded: {result}")
    return result


def _make_git_fixture(root: Path) -> tuple[Path, str]:
    project = root / "chatgpt-contract-fixture"
    project.mkdir()
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    subprocess.run(
        ["git", "-C", str(project), "config", "user.email", "chatgpt-contract@example.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(project), "config", "user.name", "ChatGPT Contract Fixture"],
        check=True,
    )
    (project / ".gitignore").write_text(".colameta/reports/**\n", encoding="utf-8")
    docs = project / "docs"
    docs.mkdir()
    subject_text = "# Hash-bound review subject\n\n" + "".join(
        f"- bounded review line {index:04d}: ChatGPT must recover this exact declared text.\n"
        for index in range(900)
    )
    subject_path = docs / "review-input.md"
    subject_path.write_text(subject_text, encoding="utf-8")
    (project / "README.md").write_text("ChatGPT development contract rehearsal fixture.\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(project), "add", "."], check=True)
    subprocess.run(["git", "-C", str(project), "commit", "-qm", "fixture"], check=True)
    return project, subject_text


def _git_status(project: Path) -> str:
    status = subprocess.run(
        ["git", "-C", str(project), "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    )
    return status.stdout


def _review_manifest(project: Path) -> dict[str, Any]:
    binding = collect_review_context_binding(str(project))
    subject_path = project / "docs" / "review-input.md"
    return {
        "schema_version": REVIEW_MANIFEST_SCHEMA_VERSION,
        "review_unit": "chatgpt-development-contract-rehearsal",
        "workflow_intent": REVIEW_MANIFEST_WORKFLOW_INTENT,
        **binding,
        "subjects": [
            {
                "path": "docs/review-input.md",
                "sha256": hashlib.sha256(subject_path.read_bytes()).hexdigest(),
            }
        ],
    }


def _tool_inventory(server: MCPPlanningBridgeServer, trace: list[dict[str, Any]]) -> tuple[str, ...]:
    trace.append({"method": "tools/list"})
    response = server._handle_jsonrpc_request(
        {
            "jsonrpc": "2.0",
            "id": "chatgpt-contract-tool-list",
            "method": "tools/list",
            "params": {},
        }
    )
    _require(response is not None, "tools/list returned no response")
    tools = response.get("result", {}).get("tools") if isinstance(response, dict) else None
    _require(isinstance(tools, list), "tools/list returned no tools list")
    names = tuple(item.get("name") for item in tools if isinstance(item, dict))
    _require(all(isinstance(name, str) for name in names), "tools/list returned an invalid tool name")
    return names


def run_chatgpt_development_contract_rehearsal() -> dict[str, Any]:
    """Exercise the ChatGPT-facing contract without a host or external state.

    The return payload is intentionally explicit about its limit: a passing
    local rehearsal is developer preflight evidence only.  ``p1_release_gate``
    remains blocked until independently verified live evidence exists.
    """

    trace: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="colameta-chatgpt-contract-") as temp_name:
        project, expected_subject_text = _make_git_fixture(Path(temp_name))
        commander = MCPPlanningBridgeServer(str(project), exposure_profile="commander")
        commander._mcp_result_artifact_store = MCPResultArtifactStore(page_chars=300)

        _require(_git_status(project) == "", "fixture checkout is dirty before rehearsal")

        visible_tools = _tool_inventory(commander, trace)
        _require(visible_tools == COMMANDER_EXPOSED_TOOLS, f"Commander tool inventory diverged: {visible_tools}")

        local_codex = MCPPlanningBridgeServer(str(project), exposure_profile="normal")
        local_visible_tools = set(local_codex._visible_tool_names())
        local_only_examples = set(COMMANDER_LOCAL_CODEX_ADVANCED_TOOL_EXAMPLES)
        _require(
            local_only_examples <= local_visible_tools,
            f"Local Codex advanced surface is missing: {sorted(local_only_examples - local_visible_tools)}",
        )
        _require(
            not (local_only_examples & set(visible_tools)),
            "Local Codex advanced tools leaked into the Commander inventory",
        )

        current_facts_preview = _tool_data(
            commander,
            trace,
            "run_mcp_workflow",
            {"workflow": "current_facts", "phase": "preview"},
        )
        missing_binding = _tool_error(
            commander,
            trace,
            "run_mcp_workflow",
            {
                "workflow": "current_facts",
                "phase": "apply",
                "preview_id": _contract_object(
                    current_facts_preview,
                    "confirmation",
                )["preview_id"],
            },
        )
        _require(
            missing_binding.get("error_code") == "PROJECT_CONTEXT_MISMATCH",
            f"unexpected context mismatch result: {missing_binding}",
        )
        _require(
            not (project / ".colameta" / "reports" / "current-facts").exists(),
            "context mismatch created a current-facts archive",
        )

        inspected = _tool_data(
            commander,
            trace,
            "review_manifest",
            {"phase": "inspect", "review_manifest": _review_manifest(project)},
        )
        inspected_facts = _contract_object(inspected, "facts")
        inspected_evidence = _contract_object(inspected, "evidence")
        subjects = inspected_facts.get("subjects")
        _require(isinstance(subjects, list) and len(subjects) == 1, "review inspect returned wrong subject set")
        subject = subjects[0]
        _require(isinstance(subject, dict), "review inspect returned malformed subject")
        page_count = subject.get("page_count")
        subject_index = subject.get("subject_index")
        _require(isinstance(page_count, int) and page_count > 1, "review fixture did not page")
        _require(isinstance(subject_index, int), "review inspect omitted subject_index")

        review_pages: list[str] = []
        review_ranges: list[tuple[int, int]] = []
        review_expiry = inspected_evidence.get("expires_at")
        _require(
            isinstance(review_expiry, str) and review_expiry,
            "review inspect omitted expiry",
        )
        for page in range(1, page_count + 1):
            read = _tool_data(
                commander,
                trace,
                "review_manifest",
                {
                    "phase": "read",
                    "review_manifest_id": inspected_evidence["review_manifest_id"],
                    "review_manifest_subject_index": subject_index,
                    "review_manifest_page": page,
                },
            )
            read_facts = _contract_object(read, "facts")
            read_evidence = _contract_object(read, "evidence")
            read_page = read_facts.get("subject_page")
            _require(isinstance(read_page, dict), "review read omitted subject_page")
            _require(
                read_page.get("review_manifest_id")
                == inspected_evidence["review_manifest_id"],
                "review handle changed",
            )
            _require(read_page.get("sha256") == subject["sha256"], "review subject hash changed")
            _require(
                read_evidence.get("expires_at") == review_expiry,
                "review read expiry changed",
            )
            _require(read_page.get("expires_at") == review_expiry, "review expiry changed")
            _require(read_page.get("page") == page, "review page number changed")
            content = read_page.get("content")
            _require(isinstance(content, str), "review page content is not text")
            review_pages.append(content)
            review_ranges.append((int(read_page["page_char_start"]), int(read_page["page_char_end"])))
        restored_subject = "".join(review_pages)
        _require(restored_subject == expected_subject_text, "review pages did not reconstruct the declared subject")
        _require(
            hashlib.sha256(restored_subject.encode("utf-8")).hexdigest() == subject["sha256"],
            "review pages did not preserve the declared subject SHA-256",
        )
        _require(
            all(end == next_start for (_, end), (next_start, _) in zip(review_ranges, review_ranges[1:])),
            "review page ranges are not contiguous",
        )
        verified = _tool_data(
            commander,
            trace,
            "review_manifest",
            {
                "phase": "verify",
                "review_manifest_id": inspected_evidence["review_manifest_id"],
            },
        )
        verification = _contract_object(verified, "facts").get("verification")
        _require(isinstance(verification, dict), "review verify omitted verification")
        _require(
            _contract_object(verified, "evidence").get("expires_at")
            == review_expiry,
            "review verify expiry changed",
        )
        _require(verification.get("context_binding") == "matched", "review verify did not match context")
        _require(verification.get("subject_hashes") == "matched", "review verify did not match hashes")

        current_facts = _tool_data(
            commander,
            trace,
            "run_mcp_workflow",
            {"workflow": "current_facts", "phase": "inspect"},
        )
        current_facts_evidence = _contract_object(current_facts, "evidence")
        artifact_id = current_facts_evidence.get("artifact_id")
        artifact_page_count = current_facts_evidence.get("page_count")
        artifact_sha256 = current_facts_evidence.get("content_sha256")
        artifact_expiry = current_facts_evidence.get("expires_at")
        _require(isinstance(artifact_id, str) and artifact_id, "current facts omitted artifact_id")
        _require(isinstance(artifact_page_count, int) and artifact_page_count > 1, "current facts did not package")
        _require(isinstance(artifact_sha256, str) and len(artifact_sha256) == 64, "current facts omitted artifact SHA")
        _require(isinstance(artifact_expiry, str) and artifact_expiry, "current facts omitted artifact expiry")

        artifact_pages: list[str] = []
        artifact_ranges: list[tuple[int, int]] = []
        for page in range(1, artifact_page_count + 1):
            read = _tool_data(
                commander,
                trace,
                "read_result_artifact",
                {"artifact_id": artifact_id, "artifact_page": page},
            )
            read_facts = _contract_object(read, "facts")
            read_evidence = _contract_object(read, "evidence")
            artifact_page = read_facts.get("artifact_page")
            _require(isinstance(artifact_page, dict), "artifact read omitted artifact_page")
            _require(read_evidence.get("artifact_id") == artifact_id, "artifact handle changed")
            _require(
                read_evidence.get("content_sha256") == artifact_sha256,
                "artifact SHA changed",
            )
            _require(
                read_evidence.get("expires_at") == artifact_expiry,
                "artifact expiry changed",
            )
            _require(artifact_page.get("page") == page, "artifact page number changed")
            content = artifact_page.get("content")
            _require(isinstance(content, str), "artifact page content is not text")
            artifact_pages.append(content)
            artifact_ranges.append((int(artifact_page["page_char_start"]), int(artifact_page["page_char_end"])))
        restored_artifact = "".join(artifact_pages)
        _require(
            hashlib.sha256(restored_artifact.encode("utf-8")).hexdigest() == artifact_sha256,
            "artifact pages did not preserve content SHA-256",
        )
        _require(
            all(end == next_start for (_, end), (next_start, _) in zip(artifact_ranges, artifact_ranges[1:])),
            "artifact page ranges are not contiguous",
        )
        restored_payload = json.loads(restored_artifact)
        _require(
            restored_payload.get("data", {}).get("workflow") == "current_facts",
            "artifact pages did not reconstruct current-facts payload",
        )

        _require(_git_status(project) == "", "read-only rehearsal dirtied the fixture checkout")
        resource_methods = [item["method"] for item in trace if item.get("method") == "resources/read"]
        _require(not resource_methods, "rehearsal unexpectedly invoked resources/read")

    release_gate = build_p1_client_release_gate()
    _require(release_gate.get("status") == "blocked", "local rehearsal made the release gate ready")

    return {
        "ok": True,
        "schema_version": CHATGPT_DEVELOPMENT_CONTRACT_REHEARSAL_SCHEMA_VERSION,
        "acceptance_kind": "local_contract_rehearsal",
        "rehearsal_status": "passed",
        "read_only": True,
        "side_effects": False,
        "live_chatgpt_session_observed": False,
        "release_eligible": False,
        "commander_tool_inventory": {
            "expected": list(COMMANDER_EXPOSED_TOOLS),
            "observed": list(visible_tools),
            "exact_match": True,
        },
        "client_experience_partition": {
            "chatgpt_visible_tool_count": len(visible_tools),
            "local_codex_advanced_examples": list(COMMANDER_LOCAL_CODEX_ADVANCED_TOOL_EXAMPLES),
            "advanced_examples_absent_from_chatgpt": True,
        },
        "context_binding_negative": {
            "error_code": "PROJECT_CONTEXT_MISMATCH",
            "archive_written": False,
        },
        "review_manifest": {
            "subject_count": 1,
            "page_count": page_count,
            "subject_sha256": subject["sha256"],
            "expires_at": review_expiry,
            "expiry_continuity": True,
            "page_ranges_contiguous": True,
            "verify_context_binding": verification["context_binding"],
            "verify_subject_hashes": verification["subject_hashes"],
        },
        "result_artifact": {
            "artifact_id": artifact_id,
            "page_count": artifact_page_count,
            "content_sha256": artifact_sha256,
            "expires_at": artifact_expiry,
            "expiry_continuity": True,
            "page_ranges_contiguous": True,
        },
        "resources_read": {
            "used": False,
            "typed_primary_paths": ["review_manifest", "read_result_artifact"],
            "proof": "all paged reads in this rehearsal used typed MCP tools only",
        },
        "fixture_checkout_clean_after_rehearsal": True,
        "p1_client_release_gate": {
            "status": release_gate["status"],
            "blocker_codes": release_gate["blocker_codes"],
            "local_rehearsal_not_accepted_as_live_evidence": True,
        },
        "next_step": {
            "action": "run_fresh_live_chatgpt_development_connector_acceptance",
            "required_before_release": True,
            "does_not_authorize_stable_replacement": True,
        },
    }
