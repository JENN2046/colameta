from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import hashlib
import hmac
import json
import re
from typing import Any


_AUTHORITATIVE_REQUEST_SEAL = object()
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
    _active_validator: Callable[[AuthenticatedTokenRequestProof], bool] | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    @property
    def trusted(self) -> bool:
        """Legacy compatibility is deliberately fail-closed.

        Trust now requires the Activation Guard to verify the HMAC with the private
        auth.json Token and reconcile both token digests with the active Ledger.
        """

        return False

    @property
    def active(self) -> bool:
        if self._active_validator is None:
            return False
        try:
            return bool(self._active_validator(self))
        except Exception:
            return False

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
    _trust_seal: object | None = None

    @property
    def trusted(self) -> bool:
        return self._trust_seal is _AUTHORITATIVE_REQUEST_SEAL

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
) -> AuthoritativeCanaryRequestContext:
    if (
        type(proof) is not AuthenticatedTokenRequestProof
        or not proof.structurally_valid()
        or not proof.active
    ):
        raise TypeError("A trusted token-authenticated transport proof is required.")
    return AuthoritativeCanaryRequestContext(
        lease_id=lease_id,
        authorization_digest=authorization_digest,
        claimed_process_identity=claimed_process_identity,
        runtime_instance_nonce=runtime_instance_nonce,
        listener_attestation_digest=listener_attestation_digest,
        principal_id=principal_id,
        session_ref=session_ref,
        binding_digest=binding_digest,
        _trust_seal=_AUTHORITATIVE_REQUEST_SEAL,
    )
