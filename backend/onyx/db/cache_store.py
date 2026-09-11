"""Atomic operations on PostgreSQL cache values."""

from sqlalchemy import delete, func, or_

from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.models import CacheStore


def delete_cache_value(tenant_id: str, key: str, expected: bytes) -> bool:
    with get_session_with_tenant(tenant_id=tenant_id) as session:
        removed = session.execute(
            delete(CacheStore)
            .where(
                CacheStore.key == key,
                CacheStore.value == expected,
                or_(
                    CacheStore.expires_at.is_(None), CacheStore.expires_at > func.now()
                ),
            )
            .returning(CacheStore.key)
        ).scalar_one_or_none()
        session.commit()
        return removed is not None
