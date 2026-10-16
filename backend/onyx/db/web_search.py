from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from onyx.db.api_token import assign_api_token, release_api_token
from onyx.db.models import InternetContentProvider, InternetSearchProvider
from onyx.server.manage.api_token.models import ApiTokenInput
from onyx.tools.tool_implementations.web_search.models import WebContentProviderConfig
from shared_configs.enums import WebContentProviderType, WebSearchProviderType


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
    api_key: ApiTokenInput | None,
    config: dict[str, str] | None,
    db_session: Session,
) -> None:
    provider.name = name
    provider.provider_type = provider_type.value
    provider.config = config
    db_session.flush()
    assign_api_token(
        db_session,
        provider,
        api_key,
        platform=provider_type.value,
        base_url=(config or {}).get("base_url"),
    )


def upsert_web_search_provider(
    *,
    provider_id: int | None,
    name: str,
    provider_type: WebSearchProviderType,
    api_key: ApiTokenInput | None,
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
        config=config,
        db_session=db_session,
    )

    db_session.flush()

    if activate:
        set_active_web_search_provider(provider_id=provider.id, db_session=db_session)

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

    token_id = provider.api_token_id
    db_session.delete(provider)
    db_session.flush()
    if token_id is not None:
        release_api_token(db_session, token_id)

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


def set_web_search_provider_base_url(
    *, name: str, base_url: str, db_session: Session
) -> None:
    provider = db_session.scalars(
        select(InternetSearchProvider).where(InternetSearchProvider.name == name)
    ).first()
    if provider is None:
        return
    provider.config = {**(provider.config or {}), "base_url": base_url}
    db_session.flush()


def set_web_content_provider_base_url(
    *, name: str, base_url: str, db_session: Session
) -> None:
    provider = db_session.scalars(
        select(InternetContentProvider).where(InternetContentProvider.name == name)
    ).first()
    if provider is None:
        return
    config = provider.config or WebContentProviderConfig()
    provider.config = config.model_copy(update={"base_url": base_url})
    db_session.flush()


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
    api_key: ApiTokenInput | None,
    config: WebContentProviderConfig | None,
    db_session: Session,
) -> None:
    provider.name = name
    provider.provider_type = provider_type.value
    provider.config = config
    db_session.flush()
    assign_api_token(
        db_session,
        provider,
        api_key,
        platform=provider_type.value,
        base_url=config.base_url if config else None,
    )


def upsert_web_content_provider(
    *,
    provider_id: int | None,
    name: str,
    provider_type: WebContentProviderType,
    api_key: ApiTokenInput | None,
    config: WebContentProviderConfig | None,
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
        config=config,
        db_session=db_session,
    )

    db_session.flush()

    if activate:
        set_active_web_content_provider(provider_id=provider.id, db_session=db_session)

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

    token_id = provider.api_token_id
    db_session.delete(provider)
    db_session.flush()
    if token_id is not None:
        release_api_token(db_session, token_id)

    db_session.commit()
