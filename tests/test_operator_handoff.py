from __future__ import annotations

import unittest

from runner.operator_handoff import (
    CLOSEOUT_OUTCOMES,
    EXCLUDED_ACTIONS,
    GUARDED_ONLY_ACTIONS,
    SUPPORTED_HANDOFF_CANDIDATE_ACTIONS,
    is_excluded_action,
    is_supported_candidate_action,
    normalize_action_class,
    validate_handoff_manifest,
    validate_operator_receipt,
)


class OperatorHandoffValidatorTests(unittest.TestCase):
    def manifest(self, *, action_class: str = "run_once", surface: dict | None = None) -> dict:
        surface = surface or {
            "surface_type": "web_console",
            "surface_name": "ColaMeta run-once operator control",
            "action_class": action_class,
            "approved": True,
            "remote_git_mutation": False,
        }
        return {
            "type": "OPERATOR_HANDOFF",
            "schema_version": "1.0",
            "handoff_id": "handoff-run-once-1",
            "reason": "platform_blocked_tool_call",
            "blocked_tool_call": {
                "tool_name": "colameta.run_once",
                "action_class": action_class,
                "blocked_before_colameta": True,
            },
            "project_binding": {
                "project_root": "/tmp/project",
                "project_id": "project-1",
                "runner_state_signature": "state-sig",
                "plan_signature": "plan-sig",
            },
            "action_binding": {
                "action_class": action_class,
                "target_version": "v1.0",
                "expected_mutation_scope": "run current version once",
            },
            "operator_surface": surface,
            "required_closeout_checks": [
                "read-only executor report confirms run id",
                "read-only status confirms current version",
            ],
            "expires_at": None,
        }

    def receipt(self, manifest: dict, *, action_class: str = "run_once", surface: dict | None = None) -> dict:
        return {
            "type": "OPERATOR_RECEIPT",
            "schema_version": "1.0",
            "handoff_id": manifest["handoff_id"],
            "action_class": action_class,
            "operator_surface": surface or dict(manifest["operator_surface"]),
            "operator_claim": {
                "performed": True,
                "performed_at": "2026-06-26T00:00:00Z",
                "visible_result": "surface reported success",
                "target_confirmed": "v1.0",
                "remote_git_mutation": False,
            },
            "read_only_closeout": {
                "declared": True,
                "outcome": "verified_success",
                "verification_sources": ["read-only executor report"],
            },
            "secrets_included": False,
        }

    @staticmethod
    def error_codes(result: dict) -> set[str]:
        return {error["code"] for error in result["errors"]}

    def test_valid_handoff_manifest_for_run_once(self) -> None:
        result = validate_handoff_manifest(self.manifest())

        assert result["ok"] is True
        assert result["action_class"] == "run_once"
        assert result["read_only_closeout_declared"] is True
        assert is_supported_candidate_action("run-once") is True
        assert SUPPORTED_HANDOFF_CANDIDATE_ACTIONS == {
            "continue_next_version",
            "apply_preview",
            "run_once",
            "manual_validation_apply",
        }
        assert "verified_success" in CLOSEOUT_OUTCOMES

    def test_valid_operator_receipt_matches_manifest(self) -> None:
        manifest = self.manifest()
        result = validate_operator_receipt(self.receipt(manifest), manifest)

        assert result["ok"] is True
        assert result["action_class"] == "run_once"
        assert result["read_only_closeout_declared"] is True
        assert result["success_claim_valid"] is True

    def test_receipt_is_claim_not_proof(self) -> None:
        manifest = self.manifest()
        result = validate_operator_receipt(self.receipt(manifest), manifest)

        assert result["ok"] is True
        assert result["receipt_is_claim"] is True
        assert result["proof_verified"] is False

    def test_excluded_push_apply_rejected(self) -> None:
        manifest = self.manifest(
            action_class="push_apply",
            surface={
                "surface_type": "web_console",
                "surface_name": "ColaMeta push apply control",
                "action_class": "push_apply",
                "approved": True,
                "remote_git_mutation": False,
            },
        )
        result = validate_handoff_manifest(manifest)

        assert result["ok"] is False
        assert "EXCLUDED_ACTION" in self.error_codes(result)
        assert is_excluded_action("git-remote-push-apply") is True
        assert "push_apply" in EXCLUDED_ACTIONS

    def test_fetch_pull_rejected(self) -> None:
        for action_class in ("fetch_apply", "pull_apply", "git-remote-fetch-apply", "remote_git_pull_apply"):
            manifest = self.manifest(
                action_class=action_class,
                surface={
                    "surface_type": "web_console",
                    "surface_name": f"ColaMeta {action_class} control",
                    "action_class": action_class,
                    "approved": True,
                    "remote_git_mutation": False,
                },
            )
            result = validate_handoff_manifest(manifest)
            assert result["ok"] is False
            assert "EXCLUDED_ACTION" in self.error_codes(result)

    def test_commit_apply_existing_guarded_only(self) -> None:
        manifest = self.manifest(
            action_class="commit_apply",
            surface={
                "surface_type": "web_console",
                "surface_name": "ColaMeta commit apply control",
                "action_class": "commit_apply",
                "approved": True,
                "remote_git_mutation": False,
            },
        )
        result = validate_handoff_manifest(manifest)

        assert result["ok"] is False
        assert "GUARDED_ONLY_ACTION" in self.error_codes(result)
        assert normalize_action_class("git-commit-confirm") == "commit_apply"
        assert "commit_apply" in GUARDED_ONLY_ACTIONS

    def test_remote_git_mutation_true_rejected(self) -> None:
        manifest = self.manifest()
        manifest["operator_surface"]["remote_git_mutation"] = True
        result = validate_handoff_manifest(manifest)

        assert result["ok"] is False
        assert "REMOTE_GIT_MUTATION_REJECTED" in self.error_codes(result)

    def test_shell_surface_rejected(self) -> None:
        manifest = self.manifest(surface={
            "surface_type": "shell",
            "surface_name": "run_once shell fallback",
            "action_class": "run_once",
            "approved": True,
            "remote_git_mutation": False,
        })
        result = validate_handoff_manifest(manifest)

        assert result["ok"] is False
        assert "GENERIC_OPERATOR_SURFACE_REJECTED" in self.error_codes(result)

    def test_generic_http_client_surface_rejected(self) -> None:
        manifest = self.manifest(surface={
            "surface_type": "generic_http_client",
            "surface_name": "run_once HTTP client",
            "action_class": "run_once",
            "approved": True,
            "remote_git_mutation": False,
        })
        result = validate_handoff_manifest(manifest)

        assert result["ok"] is False
        assert "GENERIC_OPERATOR_SURFACE_REJECTED" in self.error_codes(result)

    def test_action_mismatch_rejected(self) -> None:
        manifest = self.manifest()
        receipt = self.receipt(manifest, action_class="apply_preview")
        result = validate_operator_receipt(receipt, manifest)

        assert result["ok"] is False
        assert "ACTION_MISMATCH" in self.error_codes(result)

    def test_handoff_id_mismatch_rejected(self) -> None:
        manifest = self.manifest()
        receipt = self.receipt(manifest)
        receipt["handoff_id"] = "other-handoff"
        result = validate_operator_receipt(receipt, manifest)

        assert result["ok"] is False
        assert "HANDOFF_ID_MISMATCH" in self.error_codes(result)

    def test_operator_surface_mismatch_rejected(self) -> None:
        manifest = self.manifest()
        receipt = self.receipt(manifest, surface={
            "surface_type": "web_console",
            "surface_name": "ColaMeta different run-once operator control",
            "action_class": "run_once",
            "approved": True,
            "remote_git_mutation": False,
        })
        result = validate_operator_receipt(receipt, manifest)

        assert result["ok"] is False
        assert "OPERATOR_SURFACE_MISMATCH" in self.error_codes(result)

    def test_missing_read_only_closeout_rejected(self) -> None:
        manifest = self.manifest()
        receipt = self.receipt(manifest)
        receipt.pop("read_only_closeout")
        result = validate_operator_receipt(receipt, manifest)

        assert result["ok"] is False
        assert "READ_ONLY_CLOSEOUT_REQUIRED" in self.error_codes(result)
        assert result["success_claim_valid"] is False

    def test_secret_flag_rejected(self) -> None:
        manifest = self.manifest()
        receipt = self.receipt(manifest)
        receipt["secrets_included"] = True
        result = validate_operator_receipt(receipt, manifest)

        assert result["ok"] is False
        assert "SECRETS_INCLUDED_REJECTED" in self.error_codes(result)

    def test_unbound_apply_rejected(self) -> None:
        manifest = self.manifest(
            action_class="unbound_apply",
            surface={
                "surface_type": "web_console",
                "surface_name": "ColaMeta unbound apply control",
                "action_class": "unbound_apply",
                "approved": True,
                "remote_git_mutation": False,
            },
        )
        result = validate_handoff_manifest(manifest)

        assert result["ok"] is False
        assert "EXCLUDED_ACTION" in self.error_codes(result)
        assert is_excluded_action("apply-without-preview") is True


if __name__ == "__main__":
    unittest.main()
