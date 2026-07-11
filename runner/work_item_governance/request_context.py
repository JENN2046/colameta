from __future__ import annotations

from dataclasses import dataclass
from typing import Any


_TOKEN_REQUEST_SEAL = object()
_AUTHORITATIVE_REQUEST_SEAL = object()


@dataclass(frozen=True)
class AuthenticatedTokenRequestProof:
    mode: str
    _trust_seal: object | None = None

    @property
    def trusted(self) -> bool:
        return self.mode == "token" and self._trust_seal is _TOKEN_REQUEST_SEAL


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


def _issue_authenticated_token_request_proof() -> AuthenticatedTokenRequestProof:
    """Minted only after the HTTP transport verifies its private Bearer Token."""

    return AuthenticatedTokenRequestProof(mode="token", _trust_seal=_TOKEN_REQUEST_SEAL)


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
    if not isinstance(proof, AuthenticatedTokenRequestProof) or not proof.trusted:
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
