from collections.abc import Generator
from contextlib import contextmanager
from datetime import timedelta

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.models import CacheStore

CONTROL_STATEMENT_TIMEOUT_MS = "1000"


@contextmanager
def cache_session(
    tenant_id: str, *, control: bool = False
) -> Generator[Session, None, None]:
    with get_session_with_tenant(tenant_id=tenant_id) as session:
        if control:
            session.execute(
                select(
                    func.set_config(
                        "statement_timeout", CONTROL_STATEMENT_TIMEOUT_MS, True
                    )
                )
            )
            session.execute(
                select(
                    func.set_config("lock_timeout", CONTROL_STATEMENT_TIMEOUT_MS, True)
                )
            )
        yield session


def expire_cache_if_value(
    tenant_id: str, key: str, expected: bytes, seconds: int, *, control: bool = False
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
    with cache_session(tenant_id, control=control) as session:
        renewed = session.execute(statement).scalar_one_or_none()
        session.commit()
    return renewed is not None
