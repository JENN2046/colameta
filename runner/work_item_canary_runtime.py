from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from runner.runner_global_config import RunnerGlobalConfigStore
from runner.work_item_governance.activation import (
    AUTHORITATIVE_TOKEN_EVIDENCE_DIGEST_META_KEY,
    AUTHORITATIVE_TOKEN_FILE_SHA256_META_KEY,
    AUTHORITATIVE_CANARY_PROFILE,
    ActivationLeaseControlPlane,
    canonical_path_digest,
    require_authoritative_token_file_binding,
)
from runner.work_item_governance.bootstrap import revoke_private_bearer_token
from runner.work_item_governance.errors import WorkItemGovernanceError
from runner.work_item_governance.repository import SQLiteWorkItemLedger
from runner.work_item_governance.source_binding import reverify_runtime_source_binding
from runner.work_item_principal_adapter import local_principal_from_environment


PRIVATE_CREDENTIAL_SOURCE = "isolated_xdg_auth_json"


def serve_prepared_authoritative_canary(
    *,
    canary_root: str | os.PathLike[str],
    project_root: str | os.PathLike[str],
    lease_id: str,
    activation_envelope_path: str | os.PathLike[str],
    claimed_activation_envelope_path: str | os.PathLike[str],
    host: str = "127.0.0.1",
    port: int,
) -> int:
    """Claim, attest, and serve one separately authorized prepared Lease.

    Merely importing or constructing this composition performs no activation.
    The caller must have already produced a reviewed prepared Lease and must run
    this function inside the isolated HOME/XDG environment bound by Preflight.
    """

    root = Path(canary_root).expanduser().resolve()
    project = Path(project_root).expanduser().resolve()
    _require_below(project, root, "project_root")
    if host != "127.0.0.1":
        raise WorkItemGovernanceError(
            "ACTIVATION_BIND_ADDRESS_INVALID",
            "Authoritative Canary runtime must bind exactly 127.0.0.1.",
        )
    expected_environment = {
        "HOME": root / "home",
        "XDG_CONFIG_HOME": root / "xdg-config",
        "XDG_STATE_HOME": root / "xdg-state",
        "XDG_CACHE_HOME": root / "xdg-cache",
    }
    for name, expected in expected_environment.items():
        actual = Path(os.environ.get(name, "")).expanduser().resolve()
        if actual != expected.resolve():
            raise WorkItemGovernanceError(
                "ACTIVATION_RUNTIME_ISOLATION_INVALID",
                "Authoritative Canary HOME/XDG isolation differs from the prepared Preflight.",
                details={"variable": name},
            )
    store = RunnerGlobalConfigStore(config_dir=str(expected_environment["XDG_CONFIG_HOME"] / "colameta"))
    auth_file = Path(store.auth_path()).resolve()
    _require_below(auth_file, root, "auth_file")
    try:
        principal = local_principal_from_environment()
        if principal is None or not principal.trusted or not principal.session_ref:
            raise WorkItemGovernanceError(
                "ACTIVATION_PRINCIPAL_CONFIGURATION_INVALID",
                "A trusted session-bound local Principal must be configured before claim.",
            )
        ledger = SQLiteWorkItemLedger(project)
        token = require_authoritative_token_file_binding(ledger, auth_file)
        control_plane = ActivationLeaseControlPlane(ledger, canary_root=root)
        with ledger.read_connection() as connection:
            lease = connection.execute(
                """
                SELECT principal_binding_json,runtime_binding_json,source_binding_json,status
                FROM activation_leases WHERE lease_id=?
                """,
                (lease_id,),
            ).fetchone()
            token_binding_rows = connection.execute(
                "SELECT key,value FROM ledger_meta WHERE key IN (?,?)",
                (
                    AUTHORITATIVE_TOKEN_FILE_SHA256_META_KEY,
                    AUTHORITATIVE_TOKEN_EVIDENCE_DIGEST_META_KEY,
                ),
            ).fetchall()
        token_bindings = {
            str(item["key"]): str(item["value"])
            for item in token_binding_rows
        }
        if lease is None or lease["status"] != "prepared":
            raise WorkItemGovernanceError(
                "PREPARED_ACTIVATION_LEASE_REQUIRED",
                "Runtime startup requires one exact prepared Activation Lease.",
            )
        import json

        principal_binding: dict[str, Any] = json.loads(str(lease["principal_binding_json"]))
        runtime_binding: dict[str, Any] = json.loads(str(lease["runtime_binding_json"]))
        source_binding: dict[str, str] = json.loads(str(lease["source_binding_json"]))
        # Import the complete request/dispatch composition before remeasurement
        # so its actually loaded bytes are part of the attested module set.
        from runner.mcp_server import MCPPlanningBridgeServer

        reverify_runtime_source_binding(ledger, expected_source_binding=source_binding)
        if (
            principal.principal_id != principal_binding.get("principal_id")
            or principal.principal_kind != principal_binding.get("principal_kind")
            or principal.session_ref != principal_binding.get("session_ref")
            or sorted(principal.granted_permissions) != principal_binding.get("permissions")
            or runtime_binding.get("bind_address") != host
            or int(runtime_binding.get("port", -1)) != port
            or runtime_binding.get("cwd_path_digest") != canonical_path_digest(Path.cwd())
            or runtime_binding.get("token_file_path_digest") != canonical_path_digest(auth_file)
            or runtime_binding.get("project_root_digest") != canonical_path_digest(project)
        ):
            raise WorkItemGovernanceError(
                "ACTIVATION_RUNTIME_BINDING_MISMATCH",
                "Runtime Principal or listener differs from the prepared Lease.",
            )
        server = MCPPlanningBridgeServer(
            str(project),
            service_mode=False,
            exposure_profile=AUTHORITATIVE_CANARY_PROFILE,
        )
        server.validate_project("source-only")
        return server.serve_http(
            host=host,
            port=port,
            auth_token=token,
            auth_token_source=PRIVATE_CREDENTIAL_SOURCE,
            auth_token_file_sha256=token_bindings.get(
                AUTHORITATIVE_TOKEN_FILE_SHA256_META_KEY
            ),
            auth_token_evidence_digest=token_bindings.get(
                AUTHORITATIVE_TOKEN_EVIDENCE_DIGEST_META_KEY
            ),
            auth_mode="token",
            activation_control_plane=control_plane,
            activation_lease_id=lease_id,
            activation_envelope_path=str(Path(activation_envelope_path).resolve()),
            claimed_activation_envelope_path=str(Path(claimed_activation_envelope_path).resolve()),
        )
    finally:
        revoke_private_bearer_token(auth_file=auth_file, canary_root=root)


def _require_below(path: Path, root: Path, field: str) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise WorkItemGovernanceError(
            "ACTIVATION_RUNTIME_PATH_ESCAPE",
            "Runtime path escapes the isolated Canary root.",
            details={"field": field},
        ) from exc


__all__ = ["serve_prepared_authoritative_canary"]
