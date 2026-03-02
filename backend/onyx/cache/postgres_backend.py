"""PostgreSQL-backed ``CacheBackend`` for NO_VECTOR_DB deployments.

Uses the ``cache_store`` table for key-value storage, PostgreSQL advisory locks
for distributed locking, and a polling loop for the BLPOP pattern.
"""

import hashlib
import struct
import time
import uuid
from contextlib import AbstractContextManager
from datetime import datetime
from datetime import timedelta
from datetime import timezone

from sqlalchemy import delete
from sqlalchemy import func
from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from onyx.cache.interface import CacheBackend
from onyx.cache.interface import CacheLock
from onyx.db.models import CacheStore

_LIST_KEY_PREFIX = "_q:"
# ASCII: ':' (0x3A) < ';' (0x3B). Upper bound for range queries so [prefix+, prefix;)
# captures all list-item keys (e.g. _q:mylist:123:uuid) without including other
# lists whose names share a prefix (e.g. _q:mylist2:...).
_LIST_KEY_RANGE_TERMINATOR = ";"
_LIST_ITEM_TTL_SECONDS = 3600
_LOCK_POLL_INTERVAL = 0.1
_BLPOP_POLL_INTERVAL = 0.25


def _list_item_key(key: str) -> str:
    """Unique key for a list item. Timestamp for FIFO ordering; UUID prevents
    collision when concurrent rpush calls occur within the same nanosecond.
    """
    return f"{_LIST_KEY_PREFIX}{key}:{time.time_ns()}:{uuid.uuid4().hex}"


def _to_bytes(value: str | bytes | int | float) -> bytes:
    if isinstance(value, bytes):
        return value
    return str(value).encode()


# ------------------------------------------------------------------
# Lock
# ------------------------------------------------------------------


class PostgresCacheLock(CacheLock):
    """Advisory-lock-based distributed lock.

    Uses ``get_session_with_tenant`` for connection lifecycle.  The lock is tied
    to the session's connection; releasing or closing the session frees it.

    NOTE: Unlike Redis locks, advisory locks do not auto-expire after
    ``timeout`` seconds.  They are released when ``release()`` is
    called or when the session is closed.
    """

    def __init__(self, lock_id: int, timeout: float | None, tenant_id: str) -> None:
        self._lock_id = lock_id
        self._timeout = timeout
        self._tenant_id = tenant_id
        self._session_cm: AbstractContextManager[Session] | None = None
        self._session: Session | None = None
        self._acquired = False

    def acquire(
        self,
        blocking: bool = True,
        blocking_timeout: float | None = None,
    ) -> bool:
        from onyx.db.engine.sql_engine import get_session_with_tenant

        self._session_cm = get_session_with_tenant(tenant_id=self._tenant_id)
        self._session = self._session_cm.__enter__()
        try:
            if not blocking:
                return self._try_lock()

            effective_timeout = blocking_timeout or self._timeout
            deadline = (
                (time.monotonic() + effective_timeout) if effective_timeout else None
            )
            while True:
                if self._try_lock():
                    return True
                if deadline is not None and time.monotonic() >= deadline:
                    return False
                time.sleep(_LOCK_POLL_INTERVAL)
        finally:
            if not self._acquired:
                self._close_session()

    def release(self) -> None:
        if not self._acquired or self._session is None:
            return
        try:
            self._session.execute(select(func.pg_advisory_unlock(self._lock_id)))
        finally:
            self._acquired = False
            self._close_session()

    def owned(self) -> bool:
        return self._acquired

    def _close_session(self) -> None:
        if self._session_cm is not None:
            try:
                self._session_cm.__exit__(None, None, None)
            finally:
                self._session_cm = None
                self._session = None

    def _try_lock(self) -> bool:
        assert self._session is not None
        result = self._session.execute(
            select(func.pg_try_advisory_lock(self._lock_id))
        ).scalar()
        if result:
            self._acquired = True
            return True
        return False


# ------------------------------------------------------------------
# Backend
# ------------------------------------------------------------------


class PostgresCacheBackend(CacheBackend):
    """``CacheBackend`` backed by the ``cache_store`` table in PostgreSQL.

    Each operation opens and closes its own database session so the backend
    is safe to share across threads.  Tenant isolation is handled by
    SQLAlchemy's ``schema_translate_map`` (set by ``get_session_with_tenant``).
    """

    def __init__(self, tenant_id: str) -> None:
        self._tenant_id = tenant_id

    # -- basic key/value ---------------------------------------------------

    def get(self, key: str) -> bytes | None:
        from onyx.db.engine.sql_engine import get_session_with_tenant

        stmt = select(CacheStore.value).where(
            CacheStore.key == key,
            or_(CacheStore.expires_at.is_(None), CacheStore.expires_at > func.now()),
        )
        with get_session_with_tenant(tenant_id=self._tenant_id) as session:
            value = session.execute(stmt).scalar_one_or_none()
        if value is None:
            return None
        return bytes(value)

    def set(
        self,
        key: str,
        value: str | bytes | int | float,
        ex: int | None = None,
    ) -> None:
        from onyx.db.engine.sql_engine import get_session_with_tenant

        value_bytes = _to_bytes(value)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=ex) if ex else None
        stmt = (
            pg_insert(CacheStore)
            .values(key=key, value=value_bytes, expires_at=expires_at)
            .on_conflict_do_update(
                index_elements=[CacheStore.key],
                set_={"value": value_bytes, "expires_at": expires_at},
            )
        )
        with get_session_with_tenant(tenant_id=self._tenant_id) as session:
            session.execute(stmt)
            session.commit()

    def delete(self, key: str) -> None:
        from onyx.db.engine.sql_engine import get_session_with_tenant

        with get_session_with_tenant(tenant_id=self._tenant_id) as session:
            session.execute(delete(CacheStore).where(CacheStore.key == key))
            session.commit()

    def exists(self, key: str) -> bool:
        from onyx.db.engine.sql_engine import get_session_with_tenant

        stmt = (
            select(CacheStore.key)
            .where(
                CacheStore.key == key,
                or_(
                    CacheStore.expires_at.is_(None),
                    CacheStore.expires_at > func.now(),
                ),
            )
            .limit(1)
        )
        with get_session_with_tenant(tenant_id=self._tenant_id) as session:
            return session.execute(stmt).first() is not None

    # -- TTL ---------------------------------------------------------------

    def expire(self, key: str, seconds: int) -> None:
        from onyx.db.engine.sql_engine import get_session_with_tenant

        new_exp = datetime.now(timezone.utc) + timedelta(seconds=seconds)
        stmt = (
            update(CacheStore).where(CacheStore.key == key).values(expires_at=new_exp)
        )
        with get_session_with_tenant(tenant_id=self._tenant_id) as session:
            session.execute(stmt)
            session.commit()

    def ttl(self, key: str) -> int:
        from onyx.db.engine.sql_engine import get_session_with_tenant

        stmt = select(CacheStore.expires_at).where(CacheStore.key == key)
        with get_session_with_tenant(tenant_id=self._tenant_id) as session:
            result = session.execute(stmt).first()
        if result is None:
            return -2
        expires_at: datetime | None = result[0]
        if expires_at is None:
            return -1
        remaining = (expires_at - datetime.now(timezone.utc)).total_seconds()
        if remaining <= 0:
            return -2
        return int(remaining)

    # -- distributed lock --------------------------------------------------

    def lock(self, name: str, timeout: float | None = None) -> CacheLock:
        return PostgresCacheLock(
            self._lock_id_for(name), timeout, tenant_id=self._tenant_id
        )

    # -- blocking list (MCP OAuth BLPOP pattern) ---------------------------

    def rpush(self, key: str, value: str | bytes) -> None:
        self.set(_list_item_key(key), value, ex=_LIST_ITEM_TTL_SECONDS)

    def blpop(self, keys: list[str], timeout: int = 0) -> tuple[bytes, bytes] | None:
        from onyx.db.engine.sql_engine import get_session_with_tenant

        deadline = (time.monotonic() + timeout) if timeout > 0 else None
        while True:
            for key in keys:
                lower = f"{_LIST_KEY_PREFIX}{key}:"
                upper = f"{_LIST_KEY_PREFIX}{key}{_LIST_KEY_RANGE_TERMINATOR}"
                stmt = (
                    select(CacheStore)
                    .where(
                        CacheStore.key >= lower,
                        CacheStore.key < upper,
                        or_(
                            CacheStore.expires_at.is_(None),
                            CacheStore.expires_at > func.now(),
                        ),
                    )
                    .order_by(CacheStore.key)
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
                with get_session_with_tenant(tenant_id=self._tenant_id) as session:
                    row = session.execute(stmt).scalars().first()
                    if row is not None:
                        value = bytes(row.value) if row.value else b""
                        session.delete(row)
                        session.commit()
                        return (key.encode(), value)
            if deadline is not None and time.monotonic() >= deadline:
                return None
            time.sleep(_BLPOP_POLL_INTERVAL)

    # -- helpers -----------------------------------------------------------

    def _lock_id_for(self, name: str) -> int:
        """Map *name* to a 64-bit signed int for ``pg_advisory_lock``."""
        h = hashlib.md5(f"{self._tenant_id}:{name}".encode()).digest()
        return struct.unpack("q", h[:8])[0]


# ------------------------------------------------------------------
# Periodic cleanup
# ------------------------------------------------------------------


def cleanup_expired_cache_entries() -> None:
    """Delete rows whose ``expires_at`` is in the past.

    Called by the periodic poller every 5 minutes.
    """
    from onyx.db.engine.sql_engine import get_session_with_current_tenant

    with get_session_with_current_tenant() as session:
        session.execute(
            delete(CacheStore).where(
                CacheStore.expires_at.is_not(None),
                CacheStore.expires_at < func.now(),
            )
        )
        session.commit()
