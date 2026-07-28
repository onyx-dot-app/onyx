from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.models import TracingProviderConfig
from shared_configs.enums import TracingProviderType


def fetch_all_tracing_providers(db_session: Session) -> list[TracingProviderConfig]:
    stmt = select(TracingProviderConfig).order_by(
        TracingProviderConfig.provider_type.asc()
    )
    return list(db_session.scalars(stmt).all())


def fetch_tracing_provider(
    provider_type: TracingProviderType, db_session: Session
) -> TracingProviderConfig | None:
    stmt = select(TracingProviderConfig).where(
        TracingProviderConfig.provider_type == provider_type.value
    )
    return db_session.scalars(stmt).first()


def upsert_tracing_provider(
    *,
    provider_type: TracingProviderType,
    api_key: str | None,
    api_key_changed: bool,
    config: dict[str, str] | None,
    enabled: bool = True,
    updated_by_user_id: UUID | None = None,
    db_session: Session,
) -> TracingProviderConfig:
    provider = fetch_tracing_provider(provider_type, db_session)
    if provider is None:
        provider = TracingProviderConfig(provider_type=provider_type.value)
        db_session.add(provider)

    provider.enabled = enabled
    provider.config = config
    provider.updated_by_user_id = updated_by_user_id
    if api_key_changed or provider.api_key is None:
        # EncryptedString accepts str for writes, returns SensitiveValue for reads
        provider.api_key = api_key  # ty: ignore[invalid-assignment]

    db_session.flush()
    db_session.refresh(provider)
    return provider


def delete_tracing_provider(
    provider_type: TracingProviderType, db_session: Session
) -> None:
    provider = fetch_tracing_provider(provider_type, db_session)
    if provider is None:
        return

    db_session.delete(provider)
    db_session.flush()
