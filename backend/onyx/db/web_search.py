from __future__ import annotations

from sqlalchemy import select
from sqlalchemy import update
from sqlalchemy.orm import Session

from onyx.db.models import InternetContentProvider
from onyx.db.models import InternetSearchProvider
from shared_configs.enums import WebContentProviderType
from shared_configs.enums import WebSearchProviderType


def fetch_web_search_providers(db_session: Session) -> list[InternetSearchProvider]:
    stmt = select(InternetSearchProvider).order_by(InternetSearchProvider.id.asc())
    return list(db_session.scalars(stmt).all())


def fetch_web_content_providers(db_session: Session) -> list[InternetContentProvider]:
    stmt = select(InternetContentProvider).order_by(InternetContentProvider.id.asc())
    return list(db_session.scalars(stmt).all())


def fetch_active_web_search_provider(
    db_session: Session,
) -> InternetSearchProvider | None:
    stmt = select(InternetSearchProvider).where(
        InternetSearchProvider.is_active.is_(True)
    )
    return db_session.scalars(stmt).first()


def fetch_web_search_provider_by_id(
    provider_id: int, db_session: Session
) -> InternetSearchProvider | None:
    return db_session.get(InternetSearchProvider, provider_id)


def fetch_web_search_provider_by_name(
    name: str, db_session: Session
) -> InternetSearchProvider | None:
    stmt = select(InternetSearchProvider).where(InternetSearchProvider.name.ilike(name))
    return db_session.scalars(stmt).first()


def fetch_web_search_provider_by_type(
    provider_type: WebSearchProviderType, db_session: Session
) -> InternetSearchProvider | None:
    stmt = select(InternetSearchProvider).where(
        InternetSearchProvider.provider_type == provider_type.value
    )
    return db_session.scalars(stmt).first()


def _ensure_unique_search_name(
    name: str, provider_id: int | None, db_session: Session
) -> None:
    existing = fetch_web_search_provider_by_name(name=name, db_session=db_session)
    if existing and existing.id != provider_id:
        raise ValueError(f"A web search provider named '{name}' already exists.")


def _apply_search_provider_updates(
    provider: InternetSearchProvider,
    *,
    name: str,
    provider_type: WebSearchProviderType,
    api_key: str | None,
    api_key_changed: bool,
    config: dict[str, str] | None,
) -> None:
    provider.name = name
    provider.provider_type = provider_type.value
    provider.config = config
    if api_key_changed or provider.api_key is None:
        provider.api_key = api_key


def upsert_web_search_provider(
    *,
    provider_id: int | None,
    name: str,
    provider_type: WebSearchProviderType,
    api_key: str | None,
    api_key_changed: bool,
    config: dict[str, str] | None,
    activate: bool,
    db_session: Session,
) -> InternetSearchProvider:
    _ensure_unique_search_name(
        name=name, provider_id=provider_id, db_session=db_session
    )

    provider: InternetSearchProvider | None = None
    if provider_id is not None:
        provider = fetch_web_search_provider_by_id(provider_id, db_session)
        if provider is None:
            raise ValueError(f"No web search provider with id {provider_id} exists.")
    else:
        provider = InternetSearchProvider()
        db_session.add(provider)

    _apply_search_provider_updates(
        provider,
        name=name,
        provider_type=provider_type,
        api_key=api_key,
        api_key_changed=api_key_changed,
        config=config,
    )

    db_session.flush()

    if activate:
        set_active_web_search_provider(provider_id=provider.id, db_session=db_session)

    db_session.commit()
    db_session.refresh(provider)
    return provider


def set_active_web_search_provider(
    *, provider_id: int | None, db_session: Session
) -> InternetSearchProvider:
    if provider_id is None:
        raise ValueError("Cannot activate a provider without an id.")

    provider = fetch_web_search_provider_by_id(provider_id, db_session)
    if provider is None:
        raise ValueError(f"No web search provider with id {provider_id} exists.")

    db_session.execute(
        update(InternetSearchProvider)
        .where(
            InternetSearchProvider.is_active.is_(True),
            InternetSearchProvider.id != provider_id,
        )
        .values(is_active=False)
    )
    provider.is_active = True

    db_session.flush()
    db_session.refresh(provider)
    return provider


def deactivate_web_search_provider(
    *, provider_id: int | None, db_session: Session
) -> InternetSearchProvider:
    if provider_id is None:
        raise ValueError("Cannot deactivate a provider without an id.")

    provider = fetch_web_search_provider_by_id(provider_id, db_session)
    if provider is None:
        raise ValueError(f"No web search provider with id {provider_id} exists.")

    provider.is_active = False

    db_session.flush()
    db_session.refresh(provider)
    return provider


def delete_web_search_provider(provider_id: int, db_session: Session) -> None:
    provider = fetch_web_search_provider_by_id(provider_id, db_session)
    if provider is None:
        raise ValueError(f"No web search provider with id {provider_id} exists.")

    db_session.delete(provider)
    db_session.flush()

    db_session.commit()


# Content provider helpers


def fetch_active_web_content_provider(
    db_session: Session,
) -> InternetContentProvider | None:
    stmt = select(InternetContentProvider).where(
        InternetContentProvider.is_active.is_(True)
    )
    return db_session.scalars(stmt).first()


def fetch_web_content_provider_by_id(
    provider_id: int, db_session: Session
) -> InternetContentProvider | None:
    return db_session.get(InternetContentProvider, provider_id)


def fetch_web_content_provider_by_name(
    name: str, db_session: Session
) -> InternetContentProvider | None:
    stmt = select(InternetContentProvider).where(
        InternetContentProvider.name.ilike(name)
    )
    return db_session.scalars(stmt).first()


def fetch_web_content_provider_by_type(
    provider_type: WebContentProviderType, db_session: Session
) -> InternetContentProvider | None:
    stmt = select(InternetContentProvider).where(
        InternetContentProvider.provider_type == provider_type.value
    )
    return db_session.scalars(stmt).first()


def _ensure_unique_content_name(
    name: str, provider_id: int | None, db_session: Session
) -> None:
    existing = fetch_web_content_provider_by_name(name=name, db_session=db_session)
    if existing and existing.id != provider_id:
        raise ValueError(f"A web content provider named '{name}' already exists.")


def _apply_content_provider_updates(
    provider: InternetContentProvider,
    *,
    name: str,
    provider_type: WebContentProviderType,
    api_key: str | None,
    api_key_changed: bool,
    config: dict[str, str] | None,
) -> None:
    provider.name = name
    provider.provider_type = provider_type.value
    provider.config = config
    if api_key_changed or provider.api_key is None:
        provider.api_key = api_key


def upsert_web_content_provider(
    *,
    provider_id: int | None,
    name: str,
    provider_type: WebContentProviderType,
    api_key: str | None,
    api_key_changed: bool,
    config: dict[str, str] | None,
    activate: bool,
    db_session: Session,
) -> InternetContentProvider:
    _ensure_unique_content_name(
        name=name, provider_id=provider_id, db_session=db_session
    )

    provider: InternetContentProvider | None = None
    if provider_id is not None:
        provider = fetch_web_content_provider_by_id(provider_id, db_session)
        if provider is None:
            raise ValueError(f"No web content provider with id {provider_id} exists.")
    else:
        provider = InternetContentProvider()
        db_session.add(provider)

    _apply_content_provider_updates(
        provider,
        name=name,
        provider_type=provider_type,
        api_key=api_key,
        api_key_changed=api_key_changed,
        config=config,
    )

    db_session.flush()

    if activate:
        set_active_web_content_provider(provider_id=provider.id, db_session=db_session)

    db_session.commit()
    db_session.refresh(provider)
    return provider


def set_active_web_content_provider(
    *, provider_id: int | None, db_session: Session
) -> InternetContentProvider:
    if provider_id is None:
        raise ValueError("Cannot activate a provider without an id.")

    provider = fetch_web_content_provider_by_id(provider_id, db_session)
    if provider is None:
        raise ValueError(f"No web content provider with id {provider_id} exists.")

    db_session.execute(
        update(InternetContentProvider)
        .where(
            InternetContentProvider.is_active.is_(True),
            InternetContentProvider.id != provider_id,
        )
        .values(is_active=False)
    )
    provider.is_active = True

    db_session.flush()
    db_session.refresh(provider)
    return provider


def deactivate_web_content_provider(
    *, provider_id: int | None, db_session: Session
) -> InternetContentProvider:
    if provider_id is None:
        raise ValueError("Cannot deactivate a provider without an id.")

    provider = fetch_web_content_provider_by_id(provider_id, db_session)
    if provider is None:
        raise ValueError(f"No web content provider with id {provider_id} exists.")

    provider.is_active = False

    db_session.flush()
    db_session.refresh(provider)
    return provider


def delete_web_content_provider(provider_id: int, db_session: Session) -> None:
    provider = fetch_web_content_provider_by_id(provider_id, db_session)
    if provider is None:
        raise ValueError(f"No web content provider with id {provider_id} exists.")

    db_session.delete(provider)
    db_session.flush()

    db_session.commit()
