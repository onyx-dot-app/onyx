"""Node state reports (`SANDBOX_RUNTIME=firecracker`).

Each host agent pushes its full state to `POST /microvm/node/state` every
`--state-report-interval` (default 20 s): its VM list and the VM instances
that ended within its `--ended-retention`. The api_server then reconciles that
node (`reconcile_node`). Onyx has no scheduler inside the api_server, so the
agent pushes the list instead of the api_server polling it (microvm/README.md,
"Sandbox state model"). Correctness never depends on reports: placement asks
the agent directly.

The report is signed with the node's registered key: an EdDSA JWT with
`kid` = the registered key id, `aud` = `NODE_REPORT_AUDIENCE` (so a relay
identity token never passes here, and a report token never passes the
proxy), `node`, `iat`/`exp` (60 s at most), `jti` (single use) and
`body_sha256` (hex SHA-256 of the exact request body).
"""

import hashlib
import hmac
import time
from collections.abc import Callable

from onyx.cache.interface import CacheBackend, CacheLock, CacheLockLostError
from onyx.microvm.agent_client import HostAgentClientFactory, HostAgentConfigError
from onyx.microvm.lifecycle import NoCheckpointSupport, UnknownActivity
from onyx.microvm.models import NodeStateReport, NodeStateReportResult
from onyx.microvm.reconcile import reconcile_node
from onyx.microvm.registry import (
    claim_node_report_token,
    get_registered_node,
    node_report_lease,
    record_node_report,
)
from onyx.sandbox_proxy.sandbox_identity.signed import (
    CLOCK_SKEW_SECONDS,
    NodeSigningKeyLookup,
    SignedIdentityError,
    check_token_times,
    decode_node_token,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

NODE_REPORT_AUDIENCE = "onyx-api-server-node-report"
_REQUIRED_CLAIMS = ["node", "iat", "exp", "jti", "aud", "body_sha256"]
# One report pass ends after this long; the agent's next report starts again.
NODE_REPORT_DEADLINE_SECONDS = 20.0
_LEASE_SECONDS = NODE_REPORT_DEADLINE_SECONDS + 30


class NodeReportAuthError(Exception):
    """The report token is not valid for this body."""


class NodeNotRegisteredError(Exception):
    """The node has no registered agent address."""


def verify_node_report_token(
    token: str,
    body: bytes,
    *,
    signing_keys: NodeSigningKeyLookup,
    shared_cache: CacheBackend,
    clock: Callable[[], float] = time.time,
) -> str:
    """The reporting node's id. Raises `NodeReportAuthError`."""
    try:
        payload, signing_key = decode_node_token(
            token,
            signing_keys,
            audience=NODE_REPORT_AUDIENCE,
            required_claims=_REQUIRED_CLAIMS,
        )
        issued_at, expires_at = payload["iat"], payload["exp"]
        node_id, jti, body_sha256 = (
            payload["node"],
            payload["jti"],
            payload["body_sha256"],
        )
        if (
            not isinstance(issued_at, int)
            or isinstance(issued_at, bool)
            or not isinstance(expires_at, int)
            or isinstance(expires_at, bool)
            or not isinstance(node_id, str)
            or not node_id
            or not isinstance(jti, str)
            or not jti
            or len(jti) > 128
            or not isinstance(body_sha256, str)
        ):
            raise NodeReportAuthError("malformed")
        now = clock()
        check_token_times(issued_at, expires_at, now)
    except SignedIdentityError as e:
        raise NodeReportAuthError(e.reason.value) from e
    if node_id != signing_key.node_id:
        raise NodeReportAuthError("node_mismatch")
    if not hmac.compare_digest(
        body_sha256.encode(), hashlib.sha256(body).hexdigest().encode()
    ):
        raise NodeReportAuthError("body_mismatch")
    # Last, so a rejected token does not use up its jti.
    ttl = max(1, int(expires_at + CLOCK_SKEW_SECONDS - now) + 1)
    if not claim_node_report_token(
        shared_cache, node_id=node_id, jti=jti, ttl_seconds=ttl
    ):
        raise NodeReportAuthError("replayed")
    return node_id


def _check_lease(lease: CacheLock, deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise TimeoutError("node report deadline exceeded")
    if not lease.owned():
        raise CacheLockLostError("node report lease lost")
    lease.extend(_LEASE_SECONDS)


def reconcile_node_report(
    shared_cache: CacheBackend,
    client_factory: HostAgentClientFactory,
    report: NodeStateReport,
    *,
    now: int,
) -> NodeStateReportResult:
    """Reconcile one node's records against its verified report.

    One pass per node at a time across replicas; a report that finds the
    lease taken is skipped. Raises `NodeNotRegisteredError`.
    """
    node = get_registered_node(shared_cache, report.node_id)
    if node is None:
        raise NodeNotRegisteredError(report.node_id)
    # Placement counts a node whose reports stop as dead.
    record_node_report(shared_cache, node.node_id, now)
    lease = node_report_lease(shared_cache, node.node_id, _LEASE_SECONDS)
    if not lease.acquire(blocking=False):
        logger.info("sandbox_fc_node_report_busy node=%s", node.node_id)
        return NodeStateReportResult(reconciled=False)
    deadline = time.monotonic() + NODE_REPORT_DEADLINE_SECONDS
    try:
        result = reconcile_node(
            shared_cache,
            client_factory,
            # Until ENG-4580 and ENG-4575: never stop a VM automatically.
            NoCheckpointSupport(),
            UnknownActivity(),
            node=node,
            vms=[vm.to_agent_vm() for vm in report.vms],
            ended=report.ended,
            now=now,
            check_lease=lambda: _check_lease(lease, deadline),
            deadline=deadline,
        )
    except (TimeoutError, CacheLockLostError) as e:
        logger.warning(
            "sandbox_fc_node_report_pass_ended node=%s error=%s", node.node_id, e
        )
        return NodeStateReportResult(reconciled=False)
    except HostAgentConfigError as e:
        # Adopt, clear and orphan steps need the agent.
        logger.error(
            "sandbox_fc_node_report_pass_ended node=%s: agent mTLS is not configured: %s",
            node.node_id,
            e,
        )
        return NodeStateReportResult(reconciled=False)
    finally:
        if lease.owned():
            lease.release()
    if (
        result.adopted
        or result.cleared
        or result.orphans_marked
        or result.orphans_stopped
        or result.slept
        or result.failed
    ):
        logger.info(
            "sandbox_fc_node_report node=%s vms=%d ended=%d failed=%s adopted=%d "
            "cleared=%d orphans=%d stopped=%d idle=%d slept=%d",
            node.node_id,
            len(report.vms),
            len(report.ended),
            result.failed,
            len(result.adopted),
            len(result.cleared),
            len(result.orphans_marked),
            len(result.orphans_stopped),
            len(result.idle),
            len(result.slept),
        )
    return NodeStateReportResult(reconciled=True, report=result)
