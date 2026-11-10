"""Cache-backed Firecracker state for signed egress identity (`SANDBOX_RUNTIME=firecracker`).

No schema change: host-node signing keys live in the shared cache and VM
placement in the tenant cache, both with TTLs their writers refresh.
- Signing keys: the host agent re-registers well inside
  `NODE_SIGNING_KEY_TTL_SECONDS`, so a dead node's keys expire on their own.
- Placement: the Firecracker lifecycle writes it at VM start, refreshes it on
  heartbeat and clears it at stop.
- Agent addresses: the registration carries the agent's mTLS listener, so the
  api_server knows how to reach every node that registered a live key.
- Placement index: per node, the (tenant, sandbox) pairs placed on it, so the
  cluster-wide reconcile loop can find placement records in tenant caches.
- Guest daemon key: per sandbox, the key of one attempt, encrypted with the
  app encryption key. Placement writes it before Create and it lives as long
  as the placement record. A lost key makes the VM unusable: placement then
  replaces the VM with a new attempt.
"""

import base64
import json
from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

from pydantic import BaseModel, ConfigDict, SecretStr

from onyx.cache.interface import (
    TTL_NO_EXPIRY,
    CacheBackend,
    CacheLock,
    CacheLockAcquisitionError,
)
from onyx.microvm.models import IndexedPlacement, RegisteredNode
from onyx.utils.encryption import decrypt_bytes_to_string, encrypt_string_to_bytes

NODE_SIGNING_KEY_TTL_SECONDS = 3600
_KEY_PREFIX = "sandbox_fc:signing_key:"
_NODE_KIDS_PREFIX = "sandbox_fc:node_kids:"
_NODE_LOCK_PREFIX = "sandbox_fc:node_lock:"
_PLACEMENT_PREFIX = "sandbox_fc:placement:"
_NODE_ADDRESS_PREFIX = "sandbox_fc:node_address:"
_NODES_KEY = "sandbox_fc:nodes"
_NODE_PLACEMENTS_PREFIX = "sandbox_fc:node_placements:"
_DAEMON_KEY_PREFIX = "sandbox_fc:daemon_key:"
_MAX_NODES = 10_000
_MAX_NODE_PLACEMENTS = 100_000
_LOCK_WAIT_SECONDS = 10.0


@contextmanager
def _node_lock(shared_cache: CacheBackend, node_id: str) -> Iterator[None]:
    """Serialize writes to one node's keys, address and set membership."""
    lock = shared_cache.lock(_NODE_LOCK_PREFIX + node_id, timeout=_LOCK_WAIT_SECONDS)
    if not lock.acquire(blocking_timeout=_LOCK_WAIT_SECONDS):
        raise CacheLockAcquisitionError(node_id)
    try:
        yield
    finally:
        lock.release()


class NodeSigningKeyConflictError(Exception):
    """The key id is already registered with different key material or node."""


class RegisteredSigningKey(BaseModel):
    model_config = ConfigDict(frozen=True)

    node_id: str
    public_key: bytes


class SandboxPlacement(BaseModel):
    model_config = ConfigDict(frozen=True)

    node_id: str
    generation: int


def get_node_signing_key(
    shared_cache: CacheBackend, key_id: str
) -> RegisteredSigningKey | None:
    raw = shared_cache.get(_KEY_PREFIX + key_id)
    if raw is None:
        return None
    record = json.loads(raw)
    return RegisteredSigningKey(
        node_id=record["node"], public_key=base64.b64decode(record["public_key"])
    )


def register_node_signing_key(
    shared_cache: CacheBackend,
    *,
    node_id: str,
    key_id: str,
    public_key: bytes,
    rotation_overlap_seconds: int,
) -> None:
    """Make `key_id` the node's active key; its other keys expire after the overlap.

    Re-registering the same key refreshes its TTL.
    """
    lock = shared_cache.lock(_NODE_LOCK_PREFIX + node_id, timeout=_LOCK_WAIT_SECONDS)
    if not lock.acquire(blocking_timeout=_LOCK_WAIT_SECONDS):
        raise CacheLockAcquisitionError(node_id)
    try:
        # `key_id` is global and the lock is per node, so claim it atomically.
        record = json.dumps(
            {"node": node_id, "public_key": base64.b64encode(public_key).decode()}
        )
        if not shared_cache.renew_if_value(
            _KEY_PREFIX + key_id, record.encode(), NODE_SIGNING_KEY_TTL_SECONDS
        ) and not shared_cache.set_if_absent(
            _KEY_PREFIX + key_id, record, ex=NODE_SIGNING_KEY_TTL_SECONDS
        ):
            raise NodeSigningKeyConflictError(key_id)

        kids_raw = shared_cache.get(_NODE_KIDS_PREFIX + node_id)
        kids: list[str] = json.loads(kids_raw) if kids_raw else []
        for other in kids:
            if other == key_id:
                continue
            # Only shorten keys this node still owns; the id may be reclaimed.
            other_raw = shared_cache.get(_KEY_PREFIX + other)
            if other_raw is None or json.loads(other_raw)["node"] != node_id:
                continue
            ttl = shared_cache.ttl(_KEY_PREFIX + other)
            if ttl == TTL_NO_EXPIRY or ttl > rotation_overlap_seconds:
                shared_cache.renew_if_value(
                    _KEY_PREFIX + other, other_raw, rotation_overlap_seconds
                )

        live = [k for k in kids if k != key_id and shared_cache.exists(_KEY_PREFIX + k)]
        shared_cache.set(
            _NODE_KIDS_PREFIX + node_id,
            json.dumps([*live, key_id]),
            ex=NODE_SIGNING_KEY_TTL_SECONDS,
        )
    finally:
        lock.release()


def _placement_record(placement: SandboxPlacement) -> str:
    return json.dumps({"node": placement.node_id, "gen": placement.generation})


def set_sandbox_placement(
    tenant_cache: CacheBackend,
    sandbox_id: UUID,
    placement: SandboxPlacement,
    ttl_seconds: int,
) -> None:
    tenant_cache.set(
        _PLACEMENT_PREFIX + str(sandbox_id),
        _placement_record(placement),
        ex=ttl_seconds,
    )


def renew_sandbox_placement(
    tenant_cache: CacheBackend,
    sandbox_id: UUID,
    placement: SandboxPlacement,
    ttl_seconds: int,
) -> bool:
    """Reset the record TTL only while it still names `placement` (atomic)."""
    return tenant_cache.renew_if_value(
        _PLACEMENT_PREFIX + str(sandbox_id),
        _placement_record(placement).encode(),
        ttl_seconds,
    )


def clear_sandbox_placement(tenant_cache: CacheBackend, sandbox_id: UUID) -> None:
    tenant_cache.delete(_PLACEMENT_PREFIX + str(sandbox_id))


def get_sandbox_placement(
    tenant_cache: CacheBackend, sandbox_id: UUID
) -> SandboxPlacement | None:
    raw = tenant_cache.get(_PLACEMENT_PREFIX + str(sandbox_id))
    if raw is None:
        return None
    record = json.loads(raw)
    return SandboxPlacement(node_id=record["node"], generation=record["gen"])


def set_node_agent_address(
    shared_cache: CacheBackend, *, node_id: str, address: str
) -> None:
    """Record the agent listener of a node. Expires with the node's keys."""
    with _node_lock(shared_cache, node_id):
        shared_cache.set(
            _NODE_ADDRESS_PREFIX + node_id, address, ex=NODE_SIGNING_KEY_TTL_SECONDS
        )
        shared_cache.set_add(_NODES_KEY, node_id)


def clear_node_agent_address(shared_cache: CacheBackend, *, node_id: str) -> None:
    """Forget the agent listener of a node that registered without one."""
    with _node_lock(shared_cache, node_id):
        shared_cache.delete(_NODE_ADDRESS_PREFIX + node_id)
        shared_cache.set_remove(_NODES_KEY, node_id)


def get_registered_node(
    shared_cache: CacheBackend, node_id: str
) -> RegisteredNode | None:
    raw = shared_cache.get(_NODE_ADDRESS_PREFIX + node_id)
    if raw is None:
        return None
    return RegisteredNode(node_id=node_id, address=raw.decode())


def list_registered_nodes(shared_cache: CacheBackend) -> list[RegisteredNode]:
    """Nodes whose agent registered within the key TTL, sorted by id."""
    nodes: list[RegisteredNode] = []
    for member in shared_cache.set_members(_NODES_KEY, limit=_MAX_NODES):
        node_id = member.decode()
        node = get_registered_node(shared_cache, node_id)
        if node is None:
            _prune_node(shared_cache, node_id)
            continue
        nodes.append(node)
    return sorted(nodes, key=lambda n: n.node_id)


def _prune_node(shared_cache: CacheBackend, node_id: str) -> None:
    """Drop an expired node from the set, unless it registered again meanwhile."""
    try:
        with _node_lock(shared_cache, node_id):
            if not shared_cache.exists(_NODE_ADDRESS_PREFIX + node_id):
                shared_cache.set_remove(_NODES_KEY, node_id)
    except CacheLockAcquisitionError:
        # A registration holds the lock; the next list prunes if still expired.
        pass


def _placement_member(tenant_id: str, sandbox_id: UUID) -> str:
    # Tenant ids match ^[A-Za-z0-9_-]+$ (the agent checks it), so "/" separates.
    return f"{tenant_id}/{sandbox_id}"


def index_sandbox_placement(
    shared_cache: CacheBackend, *, node_id: str, tenant_id: str, sandbox_id: UUID
) -> None:
    shared_cache.set_add(
        _NODE_PLACEMENTS_PREFIX + node_id, _placement_member(tenant_id, sandbox_id)
    )


def unindex_sandbox_placement(
    shared_cache: CacheBackend, *, node_id: str, tenant_id: str, sandbox_id: UUID
) -> None:
    shared_cache.set_remove(
        _NODE_PLACEMENTS_PREFIX + node_id, _placement_member(tenant_id, sandbox_id)
    )


def list_indexed_placements(
    shared_cache: CacheBackend, node_id: str
) -> list[IndexedPlacement]:
    placements: list[IndexedPlacement] = []
    for member in shared_cache.set_members(
        _NODE_PLACEMENTS_PREFIX + node_id, limit=_MAX_NODE_PLACEMENTS
    ):
        tenant_id, _, sandbox_id = member.decode().partition("/")
        placements.append(
            IndexedPlacement(tenant_id=tenant_id, sandbox_id=UUID(sandbox_id))
        )
    return placements


def set_sandbox_daemon_key(
    tenant_cache: CacheBackend,
    sandbox_id: UUID,
    *,
    attempt: int,
    key: SecretStr,
    ttl_seconds: int,
) -> None:
    """Store the guest daemon key of one attempt; it replaces any other."""
    sealed = encrypt_string_to_bytes(key.get_secret_value())
    tenant_cache.set(
        _DAEMON_KEY_PREFIX + str(sandbox_id),
        json.dumps({"attempt": attempt, "key": base64.b64encode(sealed).decode()}),
        ex=ttl_seconds,
    )


def get_sandbox_daemon_key(
    tenant_cache: CacheBackend, sandbox_id: UUID, *, attempt: int
) -> SecretStr | None:
    """The guest daemon key of this attempt, or None."""
    raw = tenant_cache.get(_DAEMON_KEY_PREFIX + str(sandbox_id))
    if raw is None:
        return None
    record = json.loads(raw)
    if record["attempt"] != attempt:
        return None
    return SecretStr(decrypt_bytes_to_string(base64.b64decode(record["key"])))


def refresh_sandbox_daemon_key(
    tenant_cache: CacheBackend, sandbox_id: UUID, ttl_seconds: int
) -> None:
    tenant_cache.expire(_DAEMON_KEY_PREFIX + str(sandbox_id), ttl_seconds)


def clear_sandbox_daemon_key(tenant_cache: CacheBackend, sandbox_id: UUID) -> None:
    tenant_cache.delete(_DAEMON_KEY_PREFIX + str(sandbox_id))


_NODE_REPORT_LEASE_PREFIX = "sandbox_fc:node_report_lease:"
_NODE_REPORT_JTI_PREFIX = "sandbox_fc:node_report_jti:"


def node_report_lease(
    shared_cache: CacheBackend, node_id: str, timeout_seconds: float
) -> CacheLock:
    """Serializes the state reports of one node across api_server replicas.

    Not `_node_lock`: a long reconcile must not delay a key registration.
    """
    return shared_cache.lock(
        _NODE_REPORT_LEASE_PREFIX + node_id, timeout=timeout_seconds
    )


def claim_node_report_token(
    shared_cache: CacheBackend, *, node_id: str, jti: str, ttl_seconds: int
) -> bool:
    """Record a report token's `jti`. False if it was already used."""
    return shared_cache.set_if_absent(
        f"{_NODE_REPORT_JTI_PREFIX}{node_id}:{jti}", "1", ex=ttl_seconds
    )
