from datetime import timedelta

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.models import CacheStore


def set_cache_statement_timeout(session: Session, timeout_ms: int | None) -> None:
    """Limit statements and lock waits for this transaction, not connection acquisition."""
    if timeout_ms is None:
        return
    for setting in ("statement_timeout", "lock_timeout"):
        session.execute(select(func.set_config(setting, str(timeout_ms), True)))


def expire_cache_if_value(
    tenant_id: str,
    key: str,
    expected: bytes,
    seconds: int,
    *,
    statement_timeout_ms: int | None = None,
) -> bool:
    """Renew a matching unexpired lease and commit the update."""
    statement = (
        update(CacheStore)
        .where(
            CacheStore.key == key,
            CacheStore.value == expected,
            or_(CacheStore.expires_at.is_(None), CacheStore.expires_at > func.now()),
        )
        .values(expires_at=func.now() + timedelta(seconds=seconds))
        .returning(CacheStore.key)
    )
    with get_session_with_tenant(tenant_id=tenant_id) as session:
        set_cache_statement_timeout(session, statement_timeout_ms)
        renewed = session.execute(statement).scalar_one_or_none()
        session.commit()
    return renewed is not None
