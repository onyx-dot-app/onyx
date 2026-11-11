"""Cache-backed Firecracker state (`SANDBOX_RUNTIME=firecracker`).

No schema change. State model: microvm/README.md, "Sandbox state model".
- Signing keys (shared cache, TTL): the host agent re-registers well inside
  `NODE_SIGNING_KEY_TTL_SECONDS`, so a dead node's keys expire on their own.
- Agent addresses (shared cache, same TTL): the registration carries the
  agent's mTLS listener. A node without a live address counts as dead. An
  agent that stops on a draining node deletes its address at once.
- Last report time (shared cache, NO TTL): set on each accepted node state
  report, and deleted when the node's registration ends or starts again. Placement counts a node as dead when its last report is older than
  `SANDBOX_FC_NODE_REPORT_TIMEOUT_SECONDS`.
- Placement record (tenant cache, NO TTL): the VM instance of a sandbox
  (node, attempt, generation) and its last activity. Only Stop, a discard,
  or a reconcile that confirms the VM is gone removes it. Writes from a
  Create result or a node report are fenced on (attempt, generation).
- Reservation (tenant cache, NO TTL): taken atomically before Create, holds
  (attempt, node). One VM per sandbox: at most one reservation exists, and a
  Create of the same (sandbox, attempt) on the same node returns the same VM.
- Placement index (shared cache): per node, the (tenant, sandbox) pairs placed
  on it, so a node report can find the records in tenant caches.
- Guest daemon key (tenant cache, NO TTL): per sandbox, the key of one
  attempt, encrypted with the app encryption key. It lives as long as the
  sandbox's VM. A lost key makes the VM unusable: placement then replaces the
  VM with a new attempt.

Keys without a TTL need a Redis eviction policy that never evicts them
(`volatile-*` or `noeviction`), or the Postgres cache backend.
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
from onyx.microvm.configs import SANDBOX_FC_NODE_REPORT_TIMEOUT_SECONDS
from onyx.microvm.models import IndexedPlacement, RegisteredNode
from onyx.utils.encryption import decrypt_bytes_to_string, encrypt_string_to_bytes
from onyx.utils.logger import setup_logger

logger = setup_logger()

NODE_SIGNING_KEY_TTL_SECONDS = 3600
_KEY_PREFIX = "sandbox_fc:signing_key:"
_NODE_KIDS_PREFIX = "sandbox_fc:node_kids:"
_NODE_LOCK_PREFIX = "sandbox_fc:node_lock:"
_PLACEMENT_PREFIX = "sandbox_fc:placement:"
_NODE_ADDRESS_PREFIX = "sandbox_fc:node_address:"
_NODES_KEY = "sandbox_fc:nodes"
_NODE_PLACEMENTS_PREFIX = "sandbox_fc:node_placements:"
_DAEMON_KEY_PREFIX = "sandbox_fc:daemon_key:"
_RESERVATION_PREFIX = "sandbox_fc:reservation:"
_NODE_LAST_REPORT_PREFIX = "sandbox_fc:node_last_report:"
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
    """The durable placement record: one VM instance of a sandbox."""

    model_config = ConfigDict(frozen=True)

    node_id: str
    attempt: int
    generation: int
    # Unix seconds of the last activity (wake or touch); the idle evictor
    # reads it.
    last_active: int

    def fence(self) -> tuple[int, int]:
        return (self.attempt, self.generation)

    def names(self, node_id: str, attempt: int, generation: int) -> bool:
        return (self.node_id, self.attempt, self.generation) == (
            node_id,
            attempt,
            generation,
        )


class SandboxReservation(BaseModel):
    """The intent to create one VM: taken before Create, ended after it."""

    model_config = ConfigDict(frozen=True)

    attempt: int
    # Empty until placement picks a node.
    node_id: str
    # Random per reservation, so a compare-and-set never mistakes another
    # caller's reservation of the same (attempt, node) for its own.
    owner: str


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


_CAS_TRIES = 8


def _placement_record(placement: SandboxPlacement) -> str:
    return json.dumps(
        {
            "node": placement.node_id,
            "attempt": placement.attempt,
            "gen": placement.generation,
            "active": placement.last_active,
        }
    )


def _parse_placement(raw: bytes) -> SandboxPlacement:
    record = json.loads(raw)
    return SandboxPlacement(
        node_id=record["node"],
        attempt=record["attempt"],
        generation=record["gen"],
        last_active=record["active"],
    )


def get_sandbox_placement(
    tenant_cache: CacheBackend, sandbox_id: UUID
) -> SandboxPlacement | None:
    raw = tenant_cache.get(_PLACEMENT_PREFIX + str(sandbox_id))
    return _parse_placement(raw) if raw is not None else None


def write_sandbox_placement(
    tenant_cache: CacheBackend, sandbox_id: UUID, placement: SandboxPlacement
) -> bool:
    """Write the record unless the stored one is newer (the fence).

    Compare-and-set on the stored value: a write for an older
    (attempt, generation) never replaces a newer record. A rewrite of the
    same instance keeps the later `last_active`. No TTL. False when fenced
    out (or after `_CAS_TRIES` lost races).
    """
    key = _PLACEMENT_PREFIX + str(sandbox_id)
    for _ in range(_CAS_TRIES):
        raw = tenant_cache.get(key)
        if raw is None:
            if tenant_cache.set_if_absent(key, _placement_record(placement)):
                return True
            continue
        current = _parse_placement(raw)
        if current.fence() > placement.fence():
            return False
        new = placement
        if current.fence() == placement.fence():
            new = placement.model_copy(
                update={"last_active": max(current.last_active, placement.last_active)}
            )
        if tenant_cache.replace_if_value(key, raw, _placement_record(new)):
            return True
    return False


def touch_sandbox_placement(
    tenant_cache: CacheBackend,
    sandbox_id: UUID,
    *,
    node_id: str,
    attempt: int,
    generation: int,
    now: int,
) -> bool:
    """Set `last_active` while the record still names this VM instance."""
    key = _PLACEMENT_PREFIX + str(sandbox_id)
    for _ in range(_CAS_TRIES):
        raw = tenant_cache.get(key)
        if raw is None:
            return False
        current = _parse_placement(raw)
        if not current.names(node_id, attempt, generation):
            return False
        if current.last_active >= now:
            return True
        updated = current.model_copy(update={"last_active": now})
        if tenant_cache.replace_if_value(key, raw, _placement_record(updated)):
            return True
    return False


def clear_sandbox_placement_if(
    tenant_cache: CacheBackend,
    sandbox_id: UUID,
    *,
    node_id: str,
    attempt: int,
    generation: int,
) -> bool:
    """Delete the record only while it names this VM instance."""
    key = _PLACEMENT_PREFIX + str(sandbox_id)
    for _ in range(_CAS_TRIES):
        raw = tenant_cache.get(key)
        if raw is None or not _parse_placement(raw).names(node_id, attempt, generation):
            return False
        if tenant_cache.delete_if_value(key, raw):
            return True
    return False


def clear_sandbox_placement(tenant_cache: CacheBackend, sandbox_id: UUID) -> None:
    tenant_cache.delete(_PLACEMENT_PREFIX + str(sandbox_id))


def _reservation_record(reservation: SandboxReservation) -> str:
    return json.dumps(
        {
            "attempt": reservation.attempt,
            "node": reservation.node_id,
            "owner": reservation.owner,
        }
    )


def get_sandbox_reservation(
    tenant_cache: CacheBackend, sandbox_id: UUID
) -> tuple[SandboxReservation, bytes] | None:
    """The reservation and its stored value (for compare-and-set), or None."""
    raw = tenant_cache.get(_RESERVATION_PREFIX + str(sandbox_id))
    if raw is None:
        return None
    record = json.loads(raw)
    return (
        SandboxReservation(
            attempt=record["attempt"], node_id=record["node"], owner=record["owner"]
        ),
        raw,
    )


def reserve_sandbox(
    tenant_cache: CacheBackend,
    sandbox_id: UUID,
    reservation: SandboxReservation,
    *,
    replaces: bytes | None,
) -> bytes | None:
    """Take the reservation atomically: SET NX when `replaces` is None, else
    compare-and-set over that stored value. Returns the stored value, or None
    when another caller holds or changed it. No TTL."""
    key = _RESERVATION_PREFIX + str(sandbox_id)
    record = _reservation_record(reservation)
    taken = (
        tenant_cache.set_if_absent(key, record)
        if replaces is None
        else tenant_cache.replace_if_value(key, replaces, record)
    )
    return record.encode() if taken else None


def release_sandbox_reservation(
    tenant_cache: CacheBackend, sandbox_id: UUID, held: bytes
) -> bool:
    """Delete the reservation only while it is still `held`."""
    return tenant_cache.delete_if_value(_RESERVATION_PREFIX + str(sandbox_id), held)


def clear_sandbox_reservation(tenant_cache: CacheBackend, sandbox_id: UUID) -> None:
    tenant_cache.delete(_RESERVATION_PREFIX + str(sandbox_id))


def set_node_agent_address(
    shared_cache: CacheBackend, *, node_id: str, address: str
) -> None:
    """Record the agent listener of a node. Expires with the node's keys."""
    with _node_lock(shared_cache, node_id):
        if not shared_cache.exists(_NODE_ADDRESS_PREFIX + node_id):
            # A node that comes back starts without the report time of its
            # earlier life.
            shared_cache.delete(_NODE_LAST_REPORT_PREFIX + node_id)
        shared_cache.set(
            _NODE_ADDRESS_PREFIX + node_id, address, ex=NODE_SIGNING_KEY_TTL_SECONDS
        )
        shared_cache.set_add(_NODES_KEY, node_id)


def clear_node_agent_address(shared_cache: CacheBackend, *, node_id: str) -> None:
    """Forget the agent listener of a node that registered without one."""
    with _node_lock(shared_cache, node_id):
        shared_cache.delete(_NODE_ADDRESS_PREFIX + node_id)
        shared_cache.delete(_NODE_LAST_REPORT_PREFIX + node_id)
        shared_cache.set_remove(_NODES_KEY, node_id)


def deregister_node(shared_cache: CacheBackend, *, node_id: str, key_id: str) -> bool:
    """End the node's registration now, for an agent that leaves a draining node.

    Only while `key_id` is the node's newest key: a later agent on the same
    node keeps its registration. The keys expire on their own. Returns False
    when nothing changed.
    """
    with _node_lock(shared_cache, node_id):
        kids_raw = shared_cache.get(_NODE_KIDS_PREFIX + node_id)
        kids: list[str] = json.loads(kids_raw) if kids_raw else []
        if not kids or kids[-1] != key_id:
            return False
        if not shared_cache.exists(_NODE_ADDRESS_PREFIX + node_id):
            return False
        shared_cache.delete(_NODE_ADDRESS_PREFIX + node_id)
        shared_cache.delete(_NODE_LAST_REPORT_PREFIX + node_id)
        shared_cache.set_remove(_NODES_KEY, node_id)
        return True


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


def record_node_report(shared_cache: CacheBackend, node_id: str, now: int) -> None:
    """Set the time of the node's last accepted state report. No TTL."""
    shared_cache.set(_NODE_LAST_REPORT_PREFIX + node_id, str(now))


def node_reports_stopped(shared_cache: CacheBackend, node_id: str, now: int) -> bool:
    """True when the node reported before, but not within
    `SANDBOX_FC_NODE_REPORT_TIMEOUT_SECONDS`."""
    if SANDBOX_FC_NODE_REPORT_TIMEOUT_SECONDS <= 0:
        return False
    raw = shared_cache.get(_NODE_LAST_REPORT_PREFIX + node_id)
    if raw is None:
        return False
    try:
        last = int(raw)
    except ValueError:
        logger.error("sandbox_fc_bad_node_report_time node=%s value=%r", node_id, raw)
        return False
    return now - last > SANDBOX_FC_NODE_REPORT_TIMEOUT_SECONDS


def get_live_node(
    shared_cache: CacheBackend, node_id: str, now: int
) -> RegisteredNode | None:
    """The registered node, or None when it is dead to placement (no live
    registration, or its reports stopped)."""
    node = get_registered_node(shared_cache, node_id)
    if node is None or node_reports_stopped(shared_cache, node_id, now):
        return None
    return node


def list_live_nodes(shared_cache: CacheBackend, now: int) -> list[RegisteredNode]:
    """Registered nodes whose reports did not stop, sorted by id."""
    return [
        node
        for node in list_registered_nodes(shared_cache)
        if not node_reports_stopped(shared_cache, node.node_id, now)
    ]


def _prune_node(shared_cache: CacheBackend, node_id: str) -> None:
    """Drop an expired node from the set, unless it registered again meanwhile."""
    try:
        with _node_lock(shared_cache, node_id):
            if not shared_cache.exists(_NODE_ADDRESS_PREFIX + node_id):
                shared_cache.delete(_NODE_LAST_REPORT_PREFIX + node_id)
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
) -> None:
    """Store the guest daemon key of one attempt; it replaces any other. No TTL."""
    sealed = encrypt_string_to_bytes(key.get_secret_value())
    tenant_cache.set(
        _DAEMON_KEY_PREFIX + str(sandbox_id),
        json.dumps({"attempt": attempt, "key": base64.b64encode(sealed).decode()}),
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


def clear_sandbox_daemon_key(
    tenant_cache: CacheBackend, sandbox_id: UUID, *, attempt: int | None = None
) -> None:
    """Delete the key; with `attempt`, only while it is that attempt's key."""
    key = _DAEMON_KEY_PREFIX + str(sandbox_id)
    if attempt is None:
        tenant_cache.delete(key)
        return
    raw = tenant_cache.get(key)
    if raw is not None and json.loads(raw)["attempt"] == attempt:
        tenant_cache.delete_if_value(key, raw)


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
