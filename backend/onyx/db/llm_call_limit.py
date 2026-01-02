from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.models import ManagedLLMCallLimit


def fetch_managed_llm_call_limit(
    db_session: Session,
    enabled_only: bool = False,
) -> ManagedLLMCallLimit | None:
    query = select(ManagedLLMCallLimit)
    if enabled_only:
        query = query.where(ManagedLLMCallLimit.enabled.is_(True))
    query = query.order_by(ManagedLLMCallLimit.created_at.desc())
    return db_session.scalar(query)
