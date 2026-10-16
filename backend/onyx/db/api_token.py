"""Shared third-party API tokens.

Features point to an ``ApiToken`` row instead of storing their own copy of a
key. ``assign_api_token`` is the one write path: it turns the request's
new-or-existing input into a token, points the feature row at it, and deletes
the previous token once nothing uses it.
"""

from datetime import datetime
from typing import Any, Protocol
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.models import (
    ApiToken,
    CloudEmbeddingProvider,
    ImageGenerationConfig,
    InternetContentProvider,
    InternetSearchProvider,
    LLMProvider,
    ModelConfiguration,
    VoiceProvider,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.manage.api_token.models import ApiTokenInput, NewApiToken
from shared_configs.configs import MULTI_TENANT


class HasApiToken(Protocol):
    api_token_id: int | None
    api_token: ApiToken | None


def _origin(url: str | None) -> tuple[str, str]:
    parts = urlsplit(url or "")
    return parts.scheme.lower(), parts.netloc.lower()


def _same_base_url(a: str | None, b: str | None) -> bool:
    """Same scheme, host and port. The path may differ: one service can use
    several endpoints with the same key (Firecrawl search and scrape)."""
    return _origin(a) == _origin(b)


def get_api_token(db_session: Session, token_id: int) -> ApiToken | None:
    return db_session.get(ApiToken, token_id)


def create_api_token(
    db_session: Session,
    *,
    platform: str,
    value: str,
    base_url: str | None = None,
    is_system: bool = False,
) -> ApiToken:
    token = ApiToken(
        platform=platform, value=value, base_url=base_url, is_system=is_system
    )
    db_session.add(token)
    db_session.flush()
    return token


def resolve_api_token(
    db_session: Session,
    token_input: ApiTokenInput | None,
    *,
    platform: str,
    base_url: str | None,
    current_token_id: int | None,
) -> ApiToken | None:
    """Turn a request's key input into the token a feature should use.

    ``None`` clears the key. A new key creates a token. An existing key must
    be for the same platform, and an Onyx-owned key can only be kept, not
    picked. In multi-tenant, a stored key is only sent to the base URL it was
    saved for, so an admin cannot point it at another host.
    """
    if token_input is None:
        return None
    if isinstance(token_input, NewApiToken):
        if not token_input.value.strip():
            return None
        return create_api_token(
            db_session,
            platform=platform,
            value=token_input.value.strip(),
            base_url=base_url,
        )

    token = get_api_token(db_session, token_input.id)
    if token is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "API key not found")
    is_current = token.id == current_token_id
    if not is_current and (token.platform != platform or token.is_system):
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, "This API key cannot be used here")
    if MULTI_TENANT and not _same_base_url(token.base_url, base_url):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "A saved API key can only be used with the base URL it was saved for",
        )
    return token


def peek_api_token_value(
    db_session: Session,
    token_input: ApiTokenInput | None,
    *,
    platform: str,
    base_url: str | None,
    current_token_id: int | None = None,
) -> str | None:
    """The key a request names, without saving anything: for endpoints that
    test a key before it is saved. The same rules as ``resolve_api_token``
    apply to a saved key."""
    if token_input is None:
        return None
    if isinstance(token_input, NewApiToken):
        return token_input.value.strip() or None
    token = resolve_api_token(
        db_session,
        token_input,
        platform=platform,
        base_url=base_url,
        current_token_id=current_token_id,
    )
    return token.value.get_value(apply_mask=False) if token else None


def assign_api_token(
    db_session: Session,
    row: HasApiToken,
    token_input: ApiTokenInput | None,
    *,
    platform: str,
    base_url: str | None,
) -> None:
    """Point ``row`` at the token the input names, then drop the old token if
    nothing else uses it."""
    previous_id = row.api_token_id
    token = resolve_api_token(
        db_session,
        token_input,
        platform=platform,
        base_url=base_url,
        current_token_id=previous_id,
    )
    row.api_token = token
    db_session.flush()
    if previous_id is not None and (token is None or token.id != previous_id):
        release_api_token(db_session, previous_id)


def assign_system_api_token(
    db_session: Session,
    row: HasApiToken,
    value: str,
    *,
    platform: str,
    base_url: str | None,
) -> None:
    """Point ``row`` at a new Onyx-owned key (a Cloud default), which never
    shows in the token list and cannot be picked for another feature."""
    previous_id = row.api_token_id
    row.api_token = create_api_token(
        db_session,
        platform=platform,
        value=value,
        base_url=base_url,
        is_system=True,
    )
    db_session.flush()
    if previous_id is not None:
        release_api_token(db_session, previous_id)


def release_api_token(db_session: Session, token_id: int) -> None:
    """Delete a token that no feature uses anymore."""
    if get_api_token_usages(db_session, [token_id]).get(token_id):
        return
    token = get_api_token(db_session, token_id)
    if token is not None:
        db_session.delete(token)
        db_session.flush()


def delete_orphaned_api_tokens(db_session: Session, *, unused_since: datetime) -> int:
    """Delete tokens that no feature uses and that were last changed before
    ``unused_since``. Every write path already releases the tokens it drops;
    this catches any that slip past it. Returns the number deleted."""
    candidates = list(
        db_session.scalars(select(ApiToken).where(ApiToken.time_updated < unused_since))
    )
    usages = get_api_token_usages(db_session, [token.id for token in candidates])
    orphans = [token for token in candidates if not usages[token.id]]
    for token in orphans:
        db_session.delete(token)
    db_session.commit()
    return len(orphans)


def rotate_api_token(db_session: Session, token_id: int, value: str) -> ApiToken:
    token = get_api_token(db_session, token_id)
    if token is None or token.is_system:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "API key not found")
    if not value.strip():
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, "API key cannot be empty")
    token.value = value.strip()  # ty: ignore[invalid-assignment]
    db_session.flush()
    return token


def list_api_tokens(db_session: Session, platform: str) -> list[ApiToken]:
    """Tokens an admin can pick for ``platform``. Onyx-owned keys are left out."""
    return list(
        db_session.scalars(
            select(ApiToken)
            .where(ApiToken.platform == platform, ApiToken.is_system.is_(False))
            .order_by(ApiToken.id)
        )
    )


def _add_named_usages(
    db_session: Session,
    usages: dict[int, list[tuple[str, str]]],
    kind: str,
    fk_column: Any,
    name_column: Any,
) -> None:
    for token_id, name in db_session.execute(
        select(fk_column, name_column).where(fk_column.in_(list(usages)))
    ):
        usages[token_id].append((kind, str(name)))


def get_api_token_usages(
    db_session: Session, token_ids: list[int]
) -> dict[int, list[tuple[str, str]]]:
    """Where each token is used, as ``(kind, name)`` pairs. Each feature that
    references tokens adds its own lookup here."""
    usages: dict[int, list[tuple[str, str]]] = {token_id: [] for token_id in token_ids}
    if not token_ids:
        return usages

    # An image generation config owns a hidden LLM provider row, so those rows
    # read as image generation, not as an LLM provider.
    llm_rows = db_session.execute(
        select(
            LLMProvider.id,
            LLMProvider.api_token_id,
            LLMProvider.name,
            LLMProvider.provider,
            ImageGenerationConfig.image_provider_id,
        )
        .outerjoin(
            ModelConfiguration, ModelConfiguration.llm_provider_id == LLMProvider.id
        )
        .outerjoin(
            ImageGenerationConfig,
            ImageGenerationConfig.model_configuration_id == ModelConfiguration.id,
        )
        .where(LLMProvider.api_token_id.in_(token_ids))
    ).all()
    image_gen_provider_ids = {row[0] for row in llm_rows if row[4] is not None}
    for provider_id, token_id, name, provider, image_provider_id in llm_rows:
        if image_provider_id is not None:
            usage = ("image_generation", image_provider_id)
        elif provider_id in image_gen_provider_ids:
            continue
        else:
            usage = ("llm_provider", name or provider)
        if token_id is not None and usage not in usages[token_id]:
            usages[token_id].append(usage)

    _add_named_usages(
        db_session,
        usages,
        "voice_provider",
        VoiceProvider.api_token_id,
        VoiceProvider.name,
    )

    for token_id, provider_type in db_session.execute(
        select(
            CloudEmbeddingProvider.api_token_id, CloudEmbeddingProvider.provider_type
        ).where(CloudEmbeddingProvider.api_token_id.in_(token_ids))
    ):
        usages[token_id].append(("embedding_provider", provider_type.value))

    _add_named_usages(
        db_session,
        usages,
        "web_search_provider",
        InternetSearchProvider.api_token_id,
        InternetSearchProvider.name,
    )
    _add_named_usages(
        db_session,
        usages,
        "web_content_provider",
        InternetContentProvider.api_token_id,
        InternetContentProvider.name,
    )

    return usages
