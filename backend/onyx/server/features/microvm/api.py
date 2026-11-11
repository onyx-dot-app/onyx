"""Cluster-scoped registration of Firecracker host-node signing keys.

Mounted only with `SANDBOX_RUNTIME=firecracker`.

The host agent calls this at startup. Its key signs the egress identity the
relay stamps on VM traffic; the sandbox proxy verifies with the public half.
The optional `agent_address` (the agent's mTLS listener, `host:port`) is how
the api_server finds the node for placement and lifecycle calls.
"""

import base64
import binascii
import secrets

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, field_validator

from onyx.auth.constants import BEARER_PREFIX
from onyx.cache.factory import get_shared_cache_backend
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.microvm.registry import (
    NodeSigningKeyConflictError,
    clear_node_agent_address,
    register_node_signing_key,
    set_node_agent_address,
)
from onyx.server.features.build.configs import (
    SANDBOX_NODE_REGISTRATION_SECRET,
    SANDBOX_NODE_SIGNING_KEY_ROTATION_OVERLAP_SECONDS,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

SANDBOX_NODE_SIGNING_KEY_PATH = "/microvm/node/signing-key"

_IDENTIFIER_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"
# host:port, with a DNS name, an IPv4 address or a bracketed IPv6 address.
# The agent's advertiseAddress() applies the same host rule.
_AGENT_ADDRESS_PATTERN = r"^([A-Za-z0-9][A-Za-z0-9.-]*|\[[0-9A-Fa-f:.]+\]):[0-9]{1,5}$"


def verify_sandbox_node_registration(request: Request) -> None:
    """Constant-time check of the shared cluster credential (fails closed if unset)."""
    expected = SANDBOX_NODE_REGISTRATION_SECRET
    auth_header = request.headers.get("Authorization", "")
    # Compare bytes: compare_digest raises on non-ASCII str, and Starlette
    # decodes header values as latin-1.
    if (
        not expected
        or not auth_header.startswith(BEARER_PREFIX)
        or not secrets.compare_digest(
            auth_header[len(BEARER_PREFIX) :].encode("latin-1").strip(),
            expected.encode("utf-8"),
        )
    ):
        raise OnyxError(OnyxErrorCode.UNAUTHENTICATED)


class SandboxNodeSigningKeyRegistration(BaseModel):
    node_id: str = Field(min_length=1, max_length=253, pattern=_IDENTIFIER_PATTERN)
    key_id: str = Field(min_length=1, max_length=128, pattern=_IDENTIFIER_PATTERN)
    # Base64 of the raw 32-byte Ed25519 public key.
    public_key: str = Field(min_length=1, max_length=64)
    agent_address: str | None = Field(
        default=None, max_length=261, pattern=_AGENT_ADDRESS_PATTERN
    )

    @field_validator("agent_address")
    @classmethod
    def _agent_port_in_range(cls, value: str | None) -> str | None:
        if value is not None and not 1 <= int(value.rsplit(":", 1)[1]) <= 65535:
            raise ValueError("agent_address port must be 1-65535")
        return value


router = APIRouter()


@router.put(SANDBOX_NODE_SIGNING_KEY_PATH)
def register_sandbox_node_signing_key(
    registration: SandboxNodeSigningKeyRegistration,
    _: None = Depends(verify_sandbox_node_registration),
) -> None:
    try:
        raw = base64.b64decode(registration.public_key, validate=True)
        Ed25519PublicKey.from_public_bytes(raw)
    except (binascii.Error, ValueError):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT, "public_key must be a base64 Ed25519 key"
        )

    try:
        register_node_signing_key(
            get_shared_cache_backend(),
            node_id=registration.node_id,
            key_id=registration.key_id,
            public_key=raw,
            rotation_overlap_seconds=SANDBOX_NODE_SIGNING_KEY_ROTATION_OVERLAP_SECONDS,
        )
    except NodeSigningKeyConflictError:
        raise OnyxError(
            OnyxErrorCode.CONFLICT,
            "key_id is already registered with a different key or node",
        )
    # Only after the key registered, so a rejected request changes nothing.
    if registration.agent_address is not None:
        set_node_agent_address(
            get_shared_cache_backend(),
            node_id=registration.node_id,
            address=registration.agent_address,
        )
    else:
        # A stale address may point at a previous agent pod.
        clear_node_agent_address(
            get_shared_cache_backend(), node_id=registration.node_id
        )
    logger.info(
        "sandbox_node_signing_key_registered node=%s key_id=%s agent_address=%s",
        registration.node_id,
        registration.key_id,
        registration.agent_address,
    )
