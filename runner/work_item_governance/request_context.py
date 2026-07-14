from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import hashlib
import hmac
import json
import re
import secrets
import threading
from typing import Any


_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
AUTHENTICATED_REQUEST_PROOF_SCHEMA_VERSION = "authenticated_token_request_proof.v2"


@dataclass(frozen=True)
class AuthenticatedTokenRequestProof:
    mode: str
    lease_id: str
    listener_instance_nonce: str
    request_nonce: str
    token_file_sha256: str
    token_evidence_digest: str
    signature: str
    @property
    def trusted(self) -> bool:
        """Legacy compatibility is deliberately fail-closed.

        Trust now requires the Activation Guard to verify the HMAC with the private
        auth.json Token and reconcile both token digests with the active Ledger.
        """

        return False

    @property
    def active(self) -> bool:
        return _authenticated_token_request_proof_is_active(self)

    def unsigned_record(self) -> dict[str, str]:
        return {
            "schema_version": AUTHENTICATED_REQUEST_PROOF_SCHEMA_VERSION,
            "mode": self.mode,
            "lease_id": self.lease_id,
            "listener_instance_nonce": self.listener_instance_nonce,
            "request_nonce": self.request_nonce,
            "token_file_sha256": self.token_file_sha256,
            "token_evidence_digest": self.token_evidence_digest,
        }

    def structurally_valid(self) -> bool:
        return (
            self.mode == "token"
            and bool(self.lease_id)
            and bool(_SHA256_PATTERN.fullmatch(self.listener_instance_nonce))
            and bool(_SHA256_PATTERN.fullmatch(self.request_nonce))
            and bool(_SHA256_PATTERN.fullmatch(self.token_file_sha256))
            and bool(_SHA256_PATTERN.fullmatch(self.token_evidence_digest))
            and bool(_SHA256_PATTERN.fullmatch(self.signature))
        )

    def verify_signature(self, auth_token: str) -> bool:
        if not self.structurally_valid() or not isinstance(auth_token, str) or not auth_token:
            return False
        expected = token_request_proof_signature(
            auth_token=auth_token,
            unsigned_record=self.unsigned_record(),
        )
        return hmac.compare_digest(self.signature, expected)


_LISTENER_BOUNDARY_FACTORY_SEAL = object()
_LISTENER_PROOF_LOCK = threading.RLock()
_LISTENER_BOUNDARIES: dict[int, "_AuthenticatedTokenListenerBoundary"] = {}
_ISSUED_LISTENER_PROOFS: dict[
    int,
    tuple[AuthenticatedTokenRequestProof, "_AuthenticatedTokenListenerBoundary"],
] = {}
_ACTIVE_LISTENER_PROOFS: dict[
    int,
    tuple[AuthenticatedTokenRequestProof, "_AuthenticatedTokenListenerBoundary"],
] = {}


class _AuthenticatedTokenListenerBoundary:
    """Opaque proof issuer owned by one actually-bound HTTP listener.

    It is intentionally not a general-purpose Registry.  Construction requires
    the module-private factory seal and the factory verifies an exact live MCP
    HTTP composition root.  Proof activity is held in the module registry,
    never in caller-writable dataclass fields.
    """

    def __init__(
        self,
        *,
        owner: object,
        httpd: object,
        auth_token: str,
        lease_id: str,
        token_file_sha256: str,
        token_evidence_digest: str,
        _factory_seal: object,
    ) -> None:
        if _factory_seal is not _LISTENER_BOUNDARY_FACTORY_SEAL:
            raise TypeError("Authenticated listener boundaries are composition-root capabilities.")
        self.__owner = owner
        self.__httpd = httpd
        self.__auth_token = auth_token
        self.__lease_id = lease_id
        self.__token_file_sha256 = token_file_sha256
        self.__token_evidence_digest = token_evidence_digest
        self.__listener_instance_nonce = secrets.token_hex(32)
        self.__closed = False
        self.__issued_count = 0
        self.__activated_count = 0
        self.__retired_count = 0

    def issue(self) -> AuthenticatedTokenRequestProof:
        if self.__closed:
            raise RuntimeError("Authenticated listener boundary is closed.")
        request_nonce = secrets.token_hex(32)
        unsigned = {
            "schema_version": AUTHENTICATED_REQUEST_PROOF_SCHEMA_VERSION,
            "mode": "token",
            "lease_id": self.__lease_id,
            "listener_instance_nonce": self.__listener_instance_nonce,
            "request_nonce": request_nonce,
            "token_file_sha256": self.__token_file_sha256,
            "token_evidence_digest": self.__token_evidence_digest,
        }
        proof = AuthenticatedTokenRequestProof(
            mode="token",
            lease_id=self.__lease_id,
            listener_instance_nonce=self.__listener_instance_nonce,
            request_nonce=request_nonce,
            token_file_sha256=self.__token_file_sha256,
            token_evidence_digest=self.__token_evidence_digest,
            signature=token_request_proof_signature(
                auth_token=self.__auth_token,
                unsigned_record=unsigned,
            ),
        )
        with _LISTENER_PROOF_LOCK:
            if self.__closed:
                raise RuntimeError("Authenticated listener boundary is closed.")
            _ISSUED_LISTENER_PROOFS[id(proof)] = (proof, self)
            self.__issued_count += 1
        return proof

    def activate(self, proof: object) -> bool:
        if type(proof) is not AuthenticatedTokenRequestProof:
            return False
        with _LISTENER_PROOF_LOCK:
            issued = _ISSUED_LISTENER_PROOFS.get(id(proof))
            if (
                self.__closed
                or issued != (proof, self)
                or id(proof) in _ACTIVE_LISTENER_PROOFS
                or not proof.verify_signature(self.__auth_token)
            ):
                return False
            _ACTIVE_LISTENER_PROOFS[id(proof)] = (proof, self)
            self.__activated_count += 1
            return True

    def is_active(self, proof: object) -> bool:
        if type(proof) is not AuthenticatedTokenRequestProof:
            return False
        with _LISTENER_PROOF_LOCK:
            return bool(
                not self.__closed
                and _ISSUED_LISTENER_PROOFS.get(id(proof)) == (proof, self)
                and _ACTIVE_LISTENER_PROOFS.get(id(proof)) == (proof, self)
            )

    def retire(self, proof: object) -> bool:
        if type(proof) is not AuthenticatedTokenRequestProof:
            return False
        with _LISTENER_PROOF_LOCK:
            was_issued = _ISSUED_LISTENER_PROOFS.get(id(proof)) == (proof, self)
            if _ACTIVE_LISTENER_PROOFS.get(id(proof)) == (proof, self):
                _ACTIVE_LISTENER_PROOFS.pop(id(proof), None)
            if was_issued:
                _ISSUED_LISTENER_PROOFS.pop(id(proof), None)
                self.__retired_count += 1
            return was_issued

    def conformance_snapshot(self) -> dict[str, Any]:
        with _LISTENER_PROOF_LOCK:
            address = getattr(self.__httpd, "server_address", None)
            if self.__closed or not isinstance(address, tuple) or len(address) < 2:
                raise RuntimeError("Authenticated listener boundary is not active.")
            return {
                "bind_address": str(address[0]),
                "port": int(address[1]),
                "lease_id_digest": hashlib.sha256(self.__lease_id.encode("utf-8")).hexdigest(),
                "listener_instance_nonce": self.__listener_instance_nonce,
                "token_file_sha256": self.__token_file_sha256,
                "token_evidence_digest": self.__token_evidence_digest,
                "proof_type": "AuthenticatedTokenRequestProof",
                "issued_count": self.__issued_count,
                "activated_count": self.__activated_count,
                "retired_count": self.__retired_count,
                "active_proof_count": sum(
                    1 for _proof, boundary in _ACTIVE_LISTENER_PROOFS.values() if boundary is self
                ),
            }

    def close(self) -> None:
        with _LISTENER_PROOF_LOCK:
            self.__closed = True
            for proof_id, (_proof, boundary) in list(_ACTIVE_LISTENER_PROOFS.items()):
                if boundary is self:
                    _ACTIVE_LISTENER_PROOFS.pop(proof_id, None)
            for proof_id, (_proof, boundary) in list(_ISSUED_LISTENER_PROOFS.items()):
                if boundary is self:
                    _ISSUED_LISTENER_PROOFS.pop(proof_id, None)
            if _LISTENER_BOUNDARIES.get(id(self.__owner)) is self:
                _LISTENER_BOUNDARIES.pop(id(self.__owner), None)


def _bind_authenticated_token_listener(
    *,
    owner: object,
    httpd: object,
    auth_token: str,
    lease_id: str,
    token_file_sha256: str,
    token_evidence_digest: str,
) -> _AuthenticatedTokenListenerBoundary:
    """Bind the opaque issuer to one exact, already-bound MCP HTTP server."""

    server_address = getattr(httpd, "server_address", None)
    socket_object = getattr(httpd, "socket", None)
    owner_type = type(owner)
    if (
        owner_type.__module__ != "runner.mcp_server"
        or owner_type.__qualname__ != "MCPPlanningBridgeServer"
        or not callable(getattr(owner, "serve_http", None))
        or getattr(owner, "_httpd", None) is not httpd
        or not isinstance(auth_token, str)
        or not auth_token
        or not isinstance(server_address, tuple)
        or len(server_address) < 2
        or socket_object is None
        or socket_object.getsockname()[:2] != server_address[:2]
    ):
        raise TypeError("Authenticated proof issuance requires the exact bound MCP HTTP listener.")
    with _LISTENER_PROOF_LOCK:
        if id(owner) in _LISTENER_BOUNDARIES:
            raise RuntimeError("This MCP HTTP listener already owns a proof boundary.")
        boundary = _AuthenticatedTokenListenerBoundary(
            owner=owner,
            httpd=httpd,
            auth_token=auth_token,
            lease_id=lease_id,
            token_file_sha256=token_file_sha256,
            token_evidence_digest=token_evidence_digest,
            _factory_seal=_LISTENER_BOUNDARY_FACTORY_SEAL,
        )
        _LISTENER_BOUNDARIES[id(owner)] = boundary
        return boundary


def _authenticated_token_request_proof_is_active(proof: object) -> bool:
    if type(proof) is not AuthenticatedTokenRequestProof:
        return False
    with _LISTENER_PROOF_LOCK:
        issued = _ISSUED_LISTENER_PROOFS.get(id(proof))
        active = _ACTIVE_LISTENER_PROOFS.get(id(proof))
        return bool(issued is not None and issued == active and issued[0] is proof)


def _authenticated_token_listener_conformance_snapshot(owner: object) -> dict[str, Any]:
    with _LISTENER_PROOF_LOCK:
        boundary = _LISTENER_BOUNDARIES.get(id(owner))
        if boundary is None:
            raise RuntimeError("No active authenticated listener is bound to this server.")
        return boundary.conformance_snapshot()


@dataclass(frozen=True)
class AuthoritativeCanaryRequestContext:
    lease_id: str
    authorization_digest: str
    claimed_process_identity: str
    runtime_instance_nonce: str
    listener_attestation_digest: str
    principal_id: str
    session_ref: str
    binding_digest: str
    _trust_seal: object | None = field(default=None, init=False, repr=False, compare=False)
    _active_validator: Callable[[AuthoritativeCanaryRequestContext], bool] | None = field(
        default=None,
        init=False,
        repr=False,
        compare=False,
    )

    @property
    def trusted(self) -> bool:
        return self.active

    @property
    def active(self) -> bool:
        if self._trust_seal is None or self._active_validator is None:
            return False
        try:
            return bool(self._active_validator(self))
        except Exception:
            return False

    def to_record(self) -> dict[str, Any]:
        return {
            "lease_id": self.lease_id,
            "authorization_digest": self.authorization_digest,
            "claimed_process_identity": self.claimed_process_identity,
            "runtime_instance_nonce": self.runtime_instance_nonce,
            "listener_attestation_digest": self.listener_attestation_digest,
            "principal_id": self.principal_id,
            "session_ref": self.session_ref,
            "binding_digest": self.binding_digest,
        }


def token_request_proof_signature(
    *,
    auth_token: str,
    unsigned_record: dict[str, str],
) -> str:
    """Return the canonical HMAC-SHA256 tag for one listener request proof."""

    if not isinstance(auth_token, str) or not auth_token:
        raise ValueError("auth_token is required")
    canonical = json.dumps(
        unsigned_record,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hmac.new(auth_token.encode("utf-8"), canonical, hashlib.sha256).hexdigest()


def _mint_authoritative_request_context(
    *,
    proof: AuthenticatedTokenRequestProof,
    lease_id: str,
    authorization_digest: str,
    claimed_process_identity: str,
    runtime_instance_nonce: str,
    listener_attestation_digest: str,
    principal_id: str,
    session_ref: str,
    binding_digest: str,
    trust_seal: object,
    active_validator: Callable[[AuthoritativeCanaryRequestContext], bool],
) -> AuthoritativeCanaryRequestContext:
    if (
        type(proof) is not AuthenticatedTokenRequestProof
        or not proof.structurally_valid()
        or not proof.active
    ):
        raise TypeError("A trusted token-authenticated transport proof is required.")
    request_context = AuthoritativeCanaryRequestContext(
        lease_id=lease_id,
        authorization_digest=authorization_digest,
        claimed_process_identity=claimed_process_identity,
        runtime_instance_nonce=runtime_instance_nonce,
        listener_attestation_digest=listener_attestation_digest,
        principal_id=principal_id,
        session_ref=session_ref,
        binding_digest=binding_digest,
    )
    object.__setattr__(request_context, "_trust_seal", trust_seal)
    object.__setattr__(request_context, "_active_validator", active_validator)
    return request_context
