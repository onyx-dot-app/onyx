"""Read deployment-specific retrieval settings without leaking ORM instances."""

from sqlalchemy import or_, select

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import Document, LLMProvider


def get_rerank_credentials() -> tuple[str, str] | None:
    with get_session_with_current_tenant() as session:
        provider = session.scalar(
            select(LLMProvider)
            .where(LLMProvider.api_base.ilike("%siliconflow%"))
            .limit(1)
        )
        if provider and provider.api_base and provider.api_key:
            return (
                provider.api_base.rstrip("/"),
                provider.api_key.get_value(apply_mask=False),
            )
    return None


def get_indexed_case_document_ids() -> list[str]:
    with get_session_with_current_tenant() as session:
        statement = (
            select(Document.id)
            .where(
                or_(
                    Document.id.like("%/portfolios%"),
                    Document.id.like("%/projects%"),
                )
            )
            .order_by(Document.id)
            .limit(48)
        )
        return list(session.scalars(statement).all())
