"""The container record of a harness sandbox, in the tenant cache (no TTL).

One record per sandbox: its running container, the daemon instance and the
last activity. The guest daemon key lives in the shared per-sandbox key
record (`onyx.microvm.registry`), by attempt, so encryption key rotation
covers it. Starts, stops and purges hold the sandbox's container lock.
"""

from collections.abc import Callable
from uuid import UUID

from onyx.cache.interface import CacheBackend, CacheLock
from onyx.server.features.build.sandbox.container.models import ContainerRecord
from onyx.server.features.build.sandbox.firecracker.harness_state import (
    StateContentionError,
)

RECORD_PREFIX = "sandbox_container:record:"
_LOCK_PREFIX = "sandbox_container:lock:"
_CAS_TRIES = 16


def get_container_record(
    tenant_cache: CacheBackend, sandbox_id: UUID
) -> ContainerRecord | None:
    raw = tenant_cache.get(RECORD_PREFIX + str(sandbox_id))
    return None if raw is None else ContainerRecord.model_validate_json(raw)


def set_container_record(
    tenant_cache: CacheBackend, sandbox_id: UUID, record: ContainerRecord
) -> None:
    tenant_cache.set(RECORD_PREFIX + str(sandbox_id), record.model_dump_json())


def update_container_record(
    tenant_cache: CacheBackend,
    sandbox_id: UUID,
    change: Callable[[ContainerRecord], ContainerRecord | None],
) -> None:
    """Compare-and-set a change of the record (None from `change`: keep
    it). Nothing when there is no record."""
    key = RECORD_PREFIX + str(sandbox_id)
    for _ in range(_CAS_TRIES):
        raw = tenant_cache.get(key)
        if raw is None:
            return
        new = change(ContainerRecord.model_validate_json(raw))
        if new is None:
            return
        payload = new.model_dump_json()
        if payload.encode() == raw or tenant_cache.replace_if_value(key, raw, payload):
            return
    raise StateContentionError(key)


def clear_container_record(
    tenant_cache: CacheBackend, sandbox_id: UUID, *, name: str | None = None
) -> None:
    """Delete the record; with `name`, only while it names that container."""
    key = RECORD_PREFIX + str(sandbox_id)
    if name is None:
        tenant_cache.delete(key)
        return
    for _ in range(_CAS_TRIES):
        raw = tenant_cache.get(key)
        if raw is None or ContainerRecord.model_validate_json(raw).name != name:
            return
        if tenant_cache.delete_if_value(key, raw):
            return
    raise StateContentionError(key)


def container_lock(
    tenant_cache: CacheBackend, sandbox_id: UUID, ttl_seconds: float
) -> CacheLock:
    return tenant_cache.lock(_LOCK_PREFIX + str(sandbox_id), timeout=ttl_seconds)
