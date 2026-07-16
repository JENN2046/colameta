from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from runner.work_item_commands import WorkItemCommandGateway


_COMMIT_PATTERN = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


class StablePromotionWorkItemReader:
    """Build a promotion input packet without any reverse Work Item write."""

    def __init__(self, project_root: str | Path) -> None:
        self.gateway = WorkItemCommandGateway(project_root)

    def build_candidate(
        self,
        *,
        work_item_id: str,
        exact_commit: str,
        artifact_manifest: list[dict[str, str]],
        deployment_authorization: dict[str, Any],
    ) -> dict[str, Any]:
        work_item = self.gateway.execute("get_work_item", {"work_item_id": work_item_id})
        blockers: list[dict[str, Any]] = []
        if work_item.get("state") != "accepted":
            blockers.append(
                {
                    "code": "WORK_ITEM_NOT_ACCEPTED",
                    "actual_state": work_item.get("state"),
                }
            )
        if work_item.get("delivery_state_authority") != "work_item_application_service":
            blockers.append({"code": "WORK_ITEM_GATE_NOT_AUTHORITATIVE"})
        acceptance = work_item.get("accepted_evidence_manifest")
        if not isinstance(acceptance, dict):
            acceptance = {}
            blockers.append({"code": "ACCEPTANCE_EVIDENCE_MANIFEST_REQUIRED"})
        elif acceptance.get("task_version") != work_item.get("current_task_version"):
            blockers.append({"code": "ACCEPTANCE_MANIFEST_TASK_VERSION_MISMATCH"})
        elif acceptance.get("accepted_state_version") != work_item.get("state_version"):
            blockers.append({"code": "ACCEPTANCE_MANIFEST_STATE_VERSION_MISMATCH"})
        accepted_gate_id = acceptance.get("gate_event_id")
        accepted_gate = next(
            (
                gate
                for gate in work_item.get("gate_events", [])
                if isinstance(gate, dict) and gate.get("gate_event_id") == accepted_gate_id
            ),
            None,
        )
        if (
            not isinstance(accepted_gate, dict)
            or accepted_gate.get("outcome") != "transition_applied"
            or accepted_gate.get("target_state") != "accepted"
        ):
            blockers.append({"code": "FINAL_ACCEPTANCE_GATE_REQUIRED"})
        if not isinstance(exact_commit, str) or _COMMIT_PATTERN.fullmatch(exact_commit) is None:
            blockers.append({"code": "EXACT_COMMIT_INVALID"})
        if not isinstance(deployment_authorization, dict) or not deployment_authorization:
            blockers.append({"code": "DEPLOYMENT_AUTHORIZATION_REQUIRED"})
        elif deployment_authorization.get("exact_commit") != exact_commit:
            blockers.append({"code": "DEPLOYMENT_AUTHORIZATION_COMMIT_MISMATCH"})

        known_artifacts = {
            str(item.get("artifact_id")): item
            for item in acceptance.get("artifact_manifest", [])
            if isinstance(item, dict)
        }
        normalized_manifest: list[dict[str, str]] = []
        exact_commit_artifact_present = False
        if not isinstance(artifact_manifest, list) or not artifact_manifest:
            blockers.append({"code": "ARTIFACT_MANIFEST_REQUIRED"})
        else:
            seen: set[str] = set()
            for index, entry in enumerate(artifact_manifest):
                if not isinstance(entry, dict):
                    blockers.append({"code": "ARTIFACT_MANIFEST_ENTRY_INVALID", "index": index})
                    continue
                artifact_id = entry.get("artifact_id")
                digest = entry.get("digest")
                stored = known_artifacts.get(str(artifact_id))
                if stored is None:
                    blockers.append({
                        "code": "ARTIFACT_NOT_IN_ACCEPTANCE_MANIFEST",
                        "index": index,
                        "artifact_id": artifact_id,
                    })
                    continue
                if digest != stored.get("digest"):
                    blockers.append(
                        {"code": "ARTIFACT_MANIFEST_DIGEST_MISMATCH", "index": index, "artifact_id": artifact_id}
                    )
                    continue
                if str(artifact_id) in seen:
                    blockers.append({"code": "ARTIFACT_MANIFEST_DUPLICATE", "artifact_id": artifact_id})
                    continue
                seen.add(str(artifact_id))
                if stored.get("kind") == "git_commit" and stored.get("immutable_ref") == exact_commit:
                    exact_commit_artifact_present = True
                normalized_manifest.append(
                    {
                        "artifact_id": str(artifact_id),
                        "digest": str(digest),
                        "immutable_ref": str(stored.get("immutable_ref") or ""),
                    }
                )
        if not exact_commit_artifact_present:
            blockers.append({"code": "EXACT_COMMIT_ARTIFACT_REQUIRED"})
        return {
            "schema_version": "stable_promotion_work_item_input.v1",
            "eligible": not blockers,
            "work_item_id": work_item_id,
            "accepted_state_version": work_item.get("state_version"),
            "acceptance_manifest_id": acceptance.get("acceptance_manifest_id"),
            "acceptance_gate_event_id": acceptance.get("gate_event_id"),
            "acceptance_manifest_digest": acceptance.get("artifact_manifest_digest"),
            "exact_commit": exact_commit,
            "artifact_manifest": normalized_manifest,
            "deployment_authorization": dict(deployment_authorization or {}),
            "blockers": blockers,
            "authority_boundary": {
                "consumes_accepted_read_model": True,
                "can_write_work_item_state": False,
                "can_infer_accepted_from_runner": False,
                "can_bypass_gate": False,
                "promotion_triggered": False,
            },
        }

    def inspect_accepted_candidate(
        self,
        *,
        work_item_id: str,
        exact_commit: str,
    ) -> dict[str, Any]:
        """Bind read-only promotion evidence to the frozen acceptance manifest."""
        work_item = self.gateway.execute("get_work_item", {"work_item_id": work_item_id})
        acceptance = work_item.get("accepted_evidence_manifest")
        artifact_manifest = []
        if isinstance(acceptance, dict):
            artifact_manifest = [
                {
                    "artifact_id": str(entry.get("artifact_id") or ""),
                    "digest": str(entry.get("digest") or ""),
                }
                for entry in acceptance.get("artifact_manifest", [])
                if isinstance(entry, dict)
            ]
        candidate = self.build_candidate(
            work_item_id=work_item_id,
            exact_commit=exact_commit,
            artifact_manifest=artifact_manifest,
            deployment_authorization={},
        )
        non_authorization_blockers = [
            blocker
            for blocker in candidate["blockers"]
            if blocker.get("code") != "DEPLOYMENT_AUTHORIZATION_REQUIRED"
        ]
        return {
            **candidate,
            "schema_version": "stable_promotion_work_item_inspection.v1",
            "acceptance_binding_valid": not non_authorization_blockers,
            "acceptance_binding_blockers": non_authorization_blockers,
            "deployment_authorization_present": False,
            "eligible": False,
        }
