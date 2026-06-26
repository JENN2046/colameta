from __future__ import annotations

import unittest

from runner.dangerous_action_guard import DangerousActionGuard


class DangerousActionGuardTests(unittest.TestCase):
    def make_guard(self, *, ttl_seconds: int = 300) -> DangerousActionGuard:
        counter = {"value": 0}

        def next_id() -> str:
            counter["value"] += 1
            return f"confirmation-{counter['value']}"

        return DangerousActionGuard(ttl_seconds=ttl_seconds, now=lambda: 1000.0, id_factory=next_id)

    def preview(self, guard: DangerousActionGuard):
        return guard.create_preview(
            action_type="switch_project",
            surface="web",
            route="/api/switch-project",
            risk_class="identity_or_registry_action",
            project_root="/tmp/project-a",
            project_id="project-a",
            project_name="project-a",
            current_head="abc123",
            state_signature="state-a",
            plan_signature="plan-a",
            patch_signature="patch-a",
            registry_signature="registry-a",
            payload={"project_root": "/tmp/project-b"},
            target_summary={"project_root": "/tmp/project-b"},
            display_summary={"title": "Switch project", "target": "project-b"},
        )

    def test_preview_required_before_confirm(self) -> None:
        guard = self.make_guard()

        result = guard.confirm(
            confirmation_id=None,
            action_type="switch_project",
            surface="web",
            route="/api/switch-project",
            project_root="/tmp/project-a",
            payload={"project_root": "/tmp/project-b"},
        )

        assert result["ok"] is False
        assert result["error_code"] == "DANGEROUS_CONFIRMATION_REQUIRED"

    def test_expired_confirmation_rejected(self) -> None:
        guard = self.make_guard(ttl_seconds=-1)
        preview = self.preview(guard)

        result = guard.confirm(
            confirmation_id=preview.confirmation_id,
            action_type="switch_project",
            surface="web",
            route="/api/switch-project",
            project_root="/tmp/project-a",
            current_head="abc123",
            state_signature="state-a",
            plan_signature="plan-a",
            patch_signature="patch-a",
            registry_signature="registry-a",
            payload={"project_root": "/tmp/project-b"},
        )

        assert result["ok"] is False
        assert result["error_code"] == "DANGEROUS_CONFIRMATION_EXPIRED"

    def test_wrong_action_rejected(self) -> None:
        guard = self.make_guard()
        preview = self.preview(guard)

        result = guard.confirm(
            confirmation_id=preview.confirmation_id,
            action_type="switch_executor",
            surface="web",
            route="/api/switch-project",
            project_root="/tmp/project-a",
            current_head="abc123",
            state_signature="state-a",
            plan_signature="plan-a",
            patch_signature="patch-a",
            registry_signature="registry-a",
            payload={"project_root": "/tmp/project-b"},
        )

        assert result["ok"] is False
        assert result["error_code"] == "DANGEROUS_CONFIRMATION_ACTION_MISMATCH"

    def test_wrong_route_rejected(self) -> None:
        guard = self.make_guard()
        preview = self.preview(guard)

        result = guard.confirm(
            confirmation_id=preview.confirmation_id,
            action_type="switch_project",
            surface="web",
            route="/api/switch-executor",
            project_root="/tmp/project-a",
            current_head="abc123",
            state_signature="state-a",
            plan_signature="plan-a",
            patch_signature="patch-a",
            registry_signature="registry-a",
            payload={"project_root": "/tmp/project-b"},
        )

        assert result["ok"] is False
        assert result["error_code"] == "DANGEROUS_CONFIRMATION_ROUTE_MISMATCH"

    def test_wrong_project_rejected(self) -> None:
        guard = self.make_guard()
        preview = self.preview(guard)

        result = guard.confirm(
            confirmation_id=preview.confirmation_id,
            action_type="switch_project",
            surface="web",
            route="/api/switch-project",
            project_root="/tmp/project-other",
            current_head="abc123",
            state_signature="state-a",
            plan_signature="plan-a",
            patch_signature="patch-a",
            registry_signature="registry-a",
            payload={"project_root": "/tmp/project-b"},
        )

        assert result["ok"] is False
        assert result["error_code"] == "DANGEROUS_CONFIRMATION_PROJECT_MISMATCH"

    def test_payload_mismatch_rejected(self) -> None:
        guard = self.make_guard()
        preview = self.preview(guard)

        result = guard.confirm(
            confirmation_id=preview.confirmation_id,
            action_type="switch_project",
            surface="web",
            route="/api/switch-project",
            project_root="/tmp/project-a",
            current_head="abc123",
            state_signature="state-a",
            plan_signature="plan-a",
            patch_signature="patch-a",
            registry_signature="registry-a",
            payload={"project_root": "/tmp/project-c"},
        )

        assert result["ok"] is False
        assert result["error_code"] == "DANGEROUS_CONFIRMATION_PAYLOAD_MISMATCH"

    def test_state_or_registry_mismatch_rejected(self) -> None:
        guard = self.make_guard()
        preview = self.preview(guard)

        result = guard.confirm(
            confirmation_id=preview.confirmation_id,
            action_type="switch_project",
            surface="web",
            route="/api/switch-project",
            project_root="/tmp/project-a",
            current_head="abc123",
            state_signature="state-b",
            plan_signature="plan-a",
            patch_signature="patch-a",
            registry_signature="registry-a",
            payload={"project_root": "/tmp/project-b"},
        )

        assert result["ok"] is False
        assert result["error_code"] == "DANGEROUS_CONFIRMATION_STATE_MISMATCH"

        guard = self.make_guard()
        preview = self.preview(guard)
        result = guard.confirm(
            confirmation_id=preview.confirmation_id,
            action_type="switch_project",
            surface="web",
            route="/api/switch-project",
            project_root="/tmp/project-a",
            current_head="abc123",
            state_signature="state-a",
            plan_signature="plan-a",
            patch_signature="patch-a",
            registry_signature="registry-b",
            payload={"project_root": "/tmp/project-b"},
        )

        assert result["ok"] is False
        assert result["error_code"] == "DANGEROUS_CONFIRMATION_REGISTRY_MISMATCH"

    def test_plan_or_patch_mismatch_rejected(self) -> None:
        guard = self.make_guard()
        preview = self.preview(guard)

        result = guard.confirm(
            confirmation_id=preview.confirmation_id,
            action_type="switch_project",
            surface="web",
            route="/api/switch-project",
            project_root="/tmp/project-a",
            current_head="abc123",
            state_signature="state-a",
            plan_signature="plan-b",
            patch_signature="patch-a",
            registry_signature="registry-a",
            payload={"project_root": "/tmp/project-b"},
        )

        assert result["ok"] is False
        assert result["error_code"] == "DANGEROUS_CONFIRMATION_PLAN_MISMATCH"

        guard = self.make_guard()
        preview = self.preview(guard)
        result = guard.confirm(
            confirmation_id=preview.confirmation_id,
            action_type="switch_project",
            surface="web",
            route="/api/switch-project",
            project_root="/tmp/project-a",
            current_head="abc123",
            state_signature="state-a",
            plan_signature="plan-a",
            patch_signature="patch-b",
            registry_signature="registry-a",
            payload={"project_root": "/tmp/project-b"},
        )

        assert result["ok"] is False
        assert result["error_code"] == "DANGEROUS_CONFIRMATION_PATCH_MISMATCH"

    def test_reused_confirmation_rejected(self) -> None:
        guard = self.make_guard()
        preview = self.preview(guard)

        first = guard.confirm(
            confirmation_id=preview.confirmation_id,
            action_type="switch_project",
            surface="web",
            route="/api/switch-project",
            project_root="/tmp/project-a",
            current_head="abc123",
            state_signature="state-a",
            plan_signature="plan-a",
            patch_signature="patch-a",
            registry_signature="registry-a",
            payload={"project_root": "/tmp/project-b"},
        )
        second = guard.confirm(
            confirmation_id=preview.confirmation_id,
            action_type="switch_project",
            surface="web",
            route="/api/switch-project",
            project_root="/tmp/project-a",
            current_head="abc123",
            state_signature="state-a",
            plan_signature="plan-a",
            patch_signature="patch-a",
            registry_signature="registry-a",
            payload={"project_root": "/tmp/project-b"},
        )

        assert first["ok"] is True
        assert second["ok"] is False
        assert second["error_code"] == "DANGEROUS_CONFIRMATION_REUSED"


if __name__ == "__main__":
    unittest.main()
