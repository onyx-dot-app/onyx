"""Cluster-scoped registration of Firecracker host-node signing keys.

Mounted only with `SANDBOX_RUNTIME=firecracker`.

The host agent calls this at startup. Its key signs the egress identity the
relay stamps on VM traffic; the sandbox proxy verifies with the public half.
The optional `agent_address` (the agent's mTLS listener, `host:port`) is how
the api_server finds the node for placement and lifecycle calls.

The agent also pushes its VM state (VMs and recently ended VMs) to
`SANDBOX_NODE_STATE_REPORT_PATH`, signed with its registered key; the
api_server reconciles that node on each report. An agent that stops on a
draining node ends its registration at `SANDBOX_NODE_DEREGISTER_PATH`.
"""

import base64
import binascii
import secrets
import time

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field, ValidationError, field_validator

from onyx.auth.constants import BEARER_PREFIX
from onyx.cache.factory import get_shared_cache_backend
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.microvm.agent_client import MtlsHostAgentClientFactory
from onyx.microvm.models import (
    NODE_REPORT_MAX_BODY_BYTES,
    NodeStateReport,
    NodeStateReportResult,
)
from onyx.microvm.node_report import (
    NODE_DEREGISTER_AUDIENCE,
    NodeNotRegisteredError,
    NodeReportAuthError,
    reconcile_node_report,
    verify_node_report_token,
    verify_node_token,
)
from onyx.microvm.registry import (
    NodeSigningKeyConflictError,
    clear_node_agent_address,
    deregister_node,
    register_node_signing_key,
    set_node_agent_address,
)
from onyx.sandbox_proxy.sandbox_identity.signed_lookups import (
    CachedNodeSigningKeyLookup,
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
            key_id=registration.key_id,
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


SANDBOX_NODE_STATE_REPORT_PATH = "/microvm/node/state"

# Process-wide: a 30 s memo of node keys, one mTLS channel per agent.
_node_report_signing_keys = CachedNodeSigningKeyLookup(get_shared_cache_backend)
_node_report_agents = MtlsHostAgentClientFactory()


async def _read_body(request: Request, max_bytes: int) -> bytes:
    declared = request.headers.get("Content-Length", "")
    if declared.isdigit() and int(declared) > max_bytes:
        raise OnyxError(OnyxErrorCode.PAYLOAD_TOO_LARGE, "request body is too large")
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > max_bytes:
            raise OnyxError(
                OnyxErrorCode.PAYLOAD_TOO_LARGE, "request body is too large"
            )
        body.extend(chunk)
    return bytes(body)


def _verify_and_reconcile(token: str, body: bytes) -> NodeStateReportResult:
    shared_cache = get_shared_cache_backend()
    try:
        node_id = verify_node_report_token(
            token,
            body,
            signing_keys=_node_report_signing_keys,
            shared_cache=shared_cache,
        )
    except NodeReportAuthError as e:
        logger.warning("sandbox_fc_node_report_rejected reason=%s", e)
        raise OnyxError(OnyxErrorCode.UNAUTHENTICATED)
    try:
        report = NodeStateReport.model_validate_json(body)
    except ValidationError:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, "malformed node report")
    if report.node_id != node_id:
        logger.warning(
            "sandbox_fc_node_report_rejected reason=body_node token_node=%s body_node=%s",
            node_id,
            report.node_id,
        )
        raise OnyxError(OnyxErrorCode.UNAUTHENTICATED)
    try:
        return reconcile_node_report(
            shared_cache,
            _node_report_agents,
            report,
            now=int(time.time()),
        )
    except NodeNotRegisteredError:
        raise OnyxError(
            OnyxErrorCode.CONFLICT,
            "node has no registered agent_address",
        )


@router.post(SANDBOX_NODE_STATE_REPORT_PATH)
async def report_sandbox_node_state(request: Request) -> NodeStateReportResult:
    """The agent's VM state; the api_server reconciles that node's records.

    Auth: a JWT signed by the node's registered key (`onyx.microvm.node_report`).
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith(BEARER_PREFIX):
        raise OnyxError(OnyxErrorCode.UNAUTHENTICATED)
    token = auth_header[len(BEARER_PREFIX) :].strip()
    body = await _read_body(request, NODE_REPORT_MAX_BODY_BYTES)
    return await run_in_threadpool(_verify_and_reconcile, token, body)


SANDBOX_NODE_DEREGISTER_PATH = "/microvm/node/deregister"
_DEREGISTER_MAX_BODY_BYTES = 4096


class SandboxNodeDeregistration(BaseModel):
    node_id: str = Field(min_length=1, max_length=253, pattern=_IDENTIFIER_PATTERN)


class SandboxNodeDeregistrationResult(BaseModel):
    # False when the node had no registration, or a later agent registered.
    deregistered: bool


def _verify_and_deregister(token: str, body: bytes) -> SandboxNodeDeregistrationResult:
    shared_cache = get_shared_cache_backend()
    try:
        signing_key = verify_node_token(
            token,
            body,
            audience=NODE_DEREGISTER_AUDIENCE,
            signing_keys=_node_report_signing_keys,
            shared_cache=shared_cache,
        )
    except NodeReportAuthError as e:
        logger.warning("sandbox_fc_node_deregister_rejected reason=%s", e)
        raise OnyxError(OnyxErrorCode.UNAUTHENTICATED)
    try:
        request = SandboxNodeDeregistration.model_validate_json(body)
    except ValidationError:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, "malformed deregistration")
    if request.node_id != signing_key.node_id:
        logger.warning(
            "sandbox_fc_node_deregister_rejected reason=body_node token_node=%s body_node=%s",
            signing_key.node_id,
            request.node_id,
        )
        raise OnyxError(OnyxErrorCode.UNAUTHENTICATED)
    deregistered = deregister_node(
        shared_cache, node_id=request.node_id, key_id=signing_key.key_id
    )
    logger.info(
        "sandbox_fc_node_deregistered node=%s key_id=%s deregistered=%s",
        request.node_id,
        signing_key.key_id,
        deregistered,
    )
    return SandboxNodeDeregistrationResult(deregistered=deregistered)


@router.post(SANDBOX_NODE_DEREGISTER_PATH)
async def deregister_sandbox_node(request: Request) -> SandboxNodeDeregistrationResult:
    """End a node's registration when its agent stops on a draining node.

    Auth: a JWT signed by the node's registered key, like a state report,
    with its own audience. Idempotent.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith(BEARER_PREFIX):
        raise OnyxError(OnyxErrorCode.UNAUTHENTICATED)
    token = auth_header[len(BEARER_PREFIX) :].strip()
    body = await _read_body(request, _DEREGISTER_MAX_BODY_BYTES)
    return await run_in_threadpool(_verify_and_deregister, token, body)
