from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.db.api_token import assign_api_token, peek_api_token_value
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.models import InternetContentProvider, InternetSearchProvider, User
from onyx.db.web_search import (
    deactivate_web_content_provider,
    deactivate_web_search_provider,
    delete_web_content_provider,
    delete_web_search_provider,
    fetch_web_content_provider_by_id,
    fetch_web_content_provider_by_name,
    fetch_web_content_providers,
    fetch_web_search_provider_by_id,
    fetch_web_search_provider_by_name,
    fetch_web_search_providers,
    set_active_web_content_provider,
    set_active_web_search_provider,
    set_web_content_provider_base_url,
    set_web_search_provider_base_url,
    upsert_web_content_provider,
    upsert_web_search_provider,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.manage.api_token.models import (
    ExistingApiToken,
    keep_omitted_api_token,
)
from onyx.server.manage.web_search.models import (
    WebContentProviderTestRequest,
    WebContentProviderUpsertRequest,
    WebContentProviderView,
    WebSearchProviderTestRequest,
    WebSearchProviderUpsertRequest,
    WebSearchProviderView,
)
from onyx.tools.tool_implementations.open_url.firecrawl import FIRECRAWL_SCRAPE_URL
from onyx.tools.tool_implementations.open_url.utils import (
    filter_web_contents_with_no_title_or_content,
)
from onyx.tools.tool_implementations.web_search.clients.firecrawl_client import (
    FIRECRAWL_SEARCH_URL,
)
from onyx.tools.tool_implementations.web_search.models import WebContentProviderConfig
from onyx.tools.tool_implementations.web_search.providers import (
    build_content_provider_from_config,
    build_search_provider_from_config,
    provider_requires_api_key,
)
from onyx.utils.logger import setup_logger
from shared_configs.enums import WebContentProviderType, WebSearchProviderType

logger = setup_logger()

admin_router = APIRouter(prefix="/admin/web-search")

# Providers whose API key is shared between the search and content sides: a new
# key saved on one side is also used by the other (see the upsert endpoints
# below). Each entry is (provider_type_on_this_side, display_name,
# provider_type_other_side).
_SEARCH_TO_CONTENT_SYNC: list[
    tuple[WebSearchProviderType, str, WebContentProviderType]
] = [
    (WebSearchProviderType.EXA, "Exa", WebContentProviderType.EXA),
    (WebSearchProviderType.TAVILY, "Tavily", WebContentProviderType.TAVILY),
    (WebSearchProviderType.FIRECRAWL, "Firecrawl", WebContentProviderType.FIRECRAWL),
]
_CONTENT_TO_SEARCH_SYNC: list[
    tuple[WebContentProviderType, str, WebSearchProviderType]
] = [
    (WebContentProviderType.EXA, "Exa", WebSearchProviderType.EXA),
    (WebContentProviderType.TAVILY, "Tavily", WebSearchProviderType.TAVILY),
    (WebContentProviderType.FIRECRAWL, "Firecrawl", WebSearchProviderType.FIRECRAWL),
]

_FIRECRAWL_SCRAPE_PATH = "/v2/scrape"
_FIRECRAWL_SEARCH_PATH = "/v2/search"


def _sibling_firecrawl_url(
    base_url: str | None, *, from_path: str, to_path: str
) -> str | None:
    """Derive the other Firecrawl endpoint on the same origin.

    Both Firecrawl endpoints require a full URL, so a synced row needs one too.
    Returns None when the source URL does not end in the expected path; the
    synced row then stays disconnected until the admin enters a URL.
    """
    if not base_url or not base_url.endswith(from_path):
        return None
    return base_url[: -len(from_path)] + to_path


def _synced_content_config(
    content_type: WebContentProviderType, search_config: dict[str, str] | None
) -> WebContentProviderConfig | None:
    if content_type != WebContentProviderType.FIRECRAWL:
        return None
    search_url = (search_config or {}).get("base_url") or FIRECRAWL_SEARCH_URL
    scrape_url = _sibling_firecrawl_url(
        search_url, from_path=_FIRECRAWL_SEARCH_PATH, to_path=_FIRECRAWL_SCRAPE_PATH
    )
    return WebContentProviderConfig(base_url=scrape_url) if scrape_url else None


def _synced_search_config(
    search_type: WebSearchProviderType, content_config: WebContentProviderConfig | None
) -> dict[str, str] | None:
    if search_type != WebSearchProviderType.FIRECRAWL:
        return None
    scrape_url = (content_config.base_url if content_config else None) or (
        FIRECRAWL_SCRAPE_URL
    )
    search_url = _sibling_firecrawl_url(
        scrape_url, from_path=_FIRECRAWL_SCRAPE_PATH, to_path=_FIRECRAWL_SEARCH_PATH
    )
    return {"base_url": search_url} if search_url else None


def _search_view(provider: InternetSearchProvider) -> WebSearchProviderView:
    return WebSearchProviderView(
        id=provider.id,
        name=provider.name,
        provider_type=WebSearchProviderType(provider.provider_type),
        is_active=provider.is_active,
        config=provider.config or {},
        masked_api_key=(
            provider.api_key.get_value(apply_mask=True) if provider.api_key else None
        ),
        api_token_id=provider.api_token_id,
    )


def _content_view(provider: InternetContentProvider) -> WebContentProviderView:
    return WebContentProviderView(
        id=provider.id,
        name=provider.name,
        provider_type=WebContentProviderType(provider.provider_type),
        is_active=provider.is_active,
        config=provider.config or WebContentProviderConfig(),
        masked_api_key=(
            provider.api_key.get_value(apply_mask=True) if provider.api_key else None
        ),
        api_token_id=provider.api_token_id,
    )


def _share_token_with_sibling(
    db_session: Session,
    sibling: InternetSearchProvider | InternetContentProvider,
    token_id: int,
    base_url: str | None,
) -> None:
    """Point the sibling row at the token the other side just saved."""
    try:
        assign_api_token(
            db_session,
            sibling,
            ExistingApiToken(id=token_id),
            platform=sibling.provider_type,
            base_url=base_url,
        )
    except OnyxError:
        # In multi-tenant a key only goes to the base URL it was saved for, so
        # a sibling on another URL keeps its own key.
        logger.info("Did not share the API key with %s.", sibling.name)


@admin_router.get("/search-providers", response_model=list[WebSearchProviderView])
def list_search_providers(
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> list[WebSearchProviderView]:
    return [
        _search_view(provider) for provider in fetch_web_search_providers(db_session)
    ]


@admin_router.post("/search-providers", response_model=WebSearchProviderView)
def upsert_search_provider_endpoint(
    request: WebSearchProviderUpsertRequest,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> WebSearchProviderView:
    existing_by_name = fetch_web_search_provider_by_name(request.name, db_session)
    if (
        existing_by_name
        and request.id is not None
        and existing_by_name.id != request.id
    ):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"A search provider named '{request.name}' already exists.",
        )

    existing = (
        fetch_web_search_provider_by_id(request.id, db_session)
        if request.id is not None
        else None
    )
    previous_token_id = existing.api_token_id if existing else None
    provider = upsert_web_search_provider(
        provider_id=request.id,
        name=request.name,
        provider_type=request.provider_type,
        api_key=keep_omitted_api_token(
            request.api_key,
            was_sent="api_key" in request.model_fields_set,
            current_token_id=previous_token_id,
        ),
        config=request.config,
        activate=request.activate,
        db_session=db_session,
    )

    # Exa / Tavily / Firecrawl: the content provider uses the same key.
    token_id = provider.api_token_id
    if token_id is not None and token_id != previous_token_id:
        for search_type, name, content_type in _SEARCH_TO_CONTENT_SYNC:
            if request.provider_type != search_type:
                continue
            synced_config = _synced_content_config(content_type, request.config)
            if content_type == WebContentProviderType.FIRECRAWL and not synced_config:
                # No matching endpoint; keep the sibling's key and URL paired.
                break
            sibling = fetch_web_content_provider_by_name(name, db_session)
            if sibling is None:
                sibling = upsert_web_content_provider(
                    provider_id=None,
                    name=name,
                    provider_type=content_type,
                    api_key=None,
                    config=synced_config,
                    activate=False,
                    db_session=db_session,
                )
            elif synced_config is not None and synced_config.base_url:
                set_web_content_provider_base_url(
                    name=sibling.name,
                    base_url=synced_config.base_url,
                    db_session=db_session,
                )
            _share_token_with_sibling(
                db_session,
                sibling,
                token_id,
                base_url=sibling.config.base_url if sibling.config else None,
            )
            break

    db_session.commit()
    return _search_view(provider)


@admin_router.delete(
    "/search-providers/{provider_id}", status_code=204, response_class=Response
)
def delete_search_provider(
    provider_id: int,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> Response:
    delete_web_search_provider(provider_id, db_session)
    return Response(status_code=204)


@admin_router.post("/search-providers/{provider_id}/activate")
def activate_search_provider(
    provider_id: int,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> WebSearchProviderView:
    provider = set_active_web_search_provider(
        provider_id=provider_id, db_session=db_session
    )
    db_session.commit()
    return _search_view(provider)


@admin_router.post("/search-providers/{provider_id}/deactivate")
def deactivate_search_provider(
    provider_id: int,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> dict[str, str]:
    deactivate_web_search_provider(provider_id=provider_id, db_session=db_session)
    db_session.commit()
    return {"status": "ok"}


@admin_router.post("/search-providers/test")
def test_search_provider(
    request: WebSearchProviderTestRequest,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> dict[str, str]:
    api_key = peek_api_token_value(
        db_session,
        request.api_key,
        platform=request.provider_type.value,
        base_url=(request.config or {}).get("base_url"),
    )
    if provider_requires_api_key(request.provider_type) and not api_key:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, "API key is required.")

    try:
        provider = build_search_provider_from_config(
            provider_type=request.provider_type,
            api_key=api_key,
            config=request.config or {},
        )
    except ValueError as exc:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, str(exc)) from exc

    if provider is None:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT, "Unable to build provider configuration."
        )

    # Run the API client's test_connection method to ensure the connection is valid.
    try:
        return provider.test_connection()
    except (HTTPException, OnyxError):
        raise
    except Exception as e:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, str(e)) from e


@admin_router.get("/content-providers", response_model=list[WebContentProviderView])
def list_content_providers(
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> list[WebContentProviderView]:
    return [
        _content_view(provider) for provider in fetch_web_content_providers(db_session)
    ]


@admin_router.post("/content-providers", response_model=WebContentProviderView)
def upsert_content_provider_endpoint(
    request: WebContentProviderUpsertRequest,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> WebContentProviderView:
    existing_by_name = fetch_web_content_provider_by_name(request.name, db_session)
    if (
        existing_by_name
        and request.id is not None
        and existing_by_name.id != request.id
    ):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"A content provider named '{request.name}' already exists.",
        )

    existing = (
        fetch_web_content_provider_by_id(request.id, db_session)
        if request.id is not None
        else None
    )
    previous_token_id = existing.api_token_id if existing else None
    provider = upsert_web_content_provider(
        provider_id=request.id,
        name=request.name,
        provider_type=request.provider_type,
        api_key=keep_omitted_api_token(
            request.api_key,
            was_sent="api_key" in request.model_fields_set,
            current_token_id=previous_token_id,
        ),
        config=request.config,
        activate=request.activate,
        db_session=db_session,
    )

    # Exa / Tavily / Firecrawl: the search provider uses the same key.
    token_id = provider.api_token_id
    if token_id is not None and token_id != previous_token_id:
        for content_type, name, search_type in _CONTENT_TO_SEARCH_SYNC:
            if request.provider_type != content_type:
                continue
            synced_config = _synced_search_config(search_type, request.config)
            if search_type == WebSearchProviderType.FIRECRAWL and not synced_config:
                # No matching endpoint; keep the sibling's key and URL paired.
                break
            sibling = fetch_web_search_provider_by_name(name, db_session)
            if sibling is None:
                sibling = upsert_web_search_provider(
                    provider_id=None,
                    name=name,
                    provider_type=search_type,
                    api_key=None,
                    config=synced_config,
                    activate=False,
                    db_session=db_session,
                )
            elif synced_config is not None and synced_config.get("base_url"):
                set_web_search_provider_base_url(
                    name=sibling.name,
                    base_url=synced_config["base_url"],
                    db_session=db_session,
                )
            _share_token_with_sibling(
                db_session,
                sibling,
                token_id,
                base_url=(sibling.config or {}).get("base_url"),
            )
            break

    db_session.commit()
    return _content_view(provider)


@admin_router.delete(
    "/content-providers/{provider_id}", status_code=204, response_class=Response
)
def delete_content_provider(
    provider_id: int,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> Response:
    delete_web_content_provider(provider_id, db_session)
    return Response(status_code=204)


@admin_router.post("/content-providers/{provider_id}/activate")
def activate_content_provider(
    provider_id: int,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> WebContentProviderView:
    provider = set_active_web_content_provider(
        provider_id=provider_id, db_session=db_session
    )
    db_session.commit()
    return _content_view(provider)


@admin_router.post("/content-providers/reset-default")
def reset_content_provider_default(
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> dict[str, str]:
    providers = fetch_web_content_providers(db_session)
    active_ids = [provider.id for provider in providers if provider.is_active]

    for provider_id in active_ids:
        deactivate_web_content_provider(provider_id=provider_id, db_session=db_session)
        db_session.commit()

    return {"status": "ok"}


@admin_router.post("/content-providers/{provider_id}/deactivate")
def deactivate_content_provider(
    provider_id: int,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> dict[str, str]:
    deactivate_web_content_provider(provider_id=provider_id, db_session=db_session)
    db_session.commit()
    return {"status": "ok"}


@admin_router.post("/content-providers/test")
def test_content_provider(
    request: WebContentProviderTestRequest,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> dict[str, str]:
    api_key = peek_api_token_value(
        db_session,
        request.api_key,
        platform=request.provider_type.value,
        base_url=request.config.base_url,
    )
    if not api_key:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, "API key is required.")

    try:
        provider = build_content_provider_from_config(
            provider_type=request.provider_type,
            api_key=api_key,
            config=request.config,
        )
    except ValueError as exc:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, str(exc)) from exc

    if provider is None:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT, "Unable to build provider configuration."
        )

    # Actually test the API key by making a real content fetch call
    try:
        test_url = "https://example.com"
        test_results = filter_web_contents_with_no_title_or_content(
            list(provider.contents([test_url]))
        )
    except Exception as e:
        error_msg = str(e)
        if (
            "api" in error_msg.lower()
            or "key" in error_msg.lower()
            or "auth" in error_msg.lower()
        ):
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT, f"Invalid API key: {error_msg}"
            ) from e
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT, f"API key validation failed: {error_msg}"
        ) from e

    if not test_results or not any(result.scrape_successful for result in test_results):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "API key validation failed: content fetch returned no results.",
        )

    logger.info(
        "Web content provider test succeeded for %s.", request.provider_type.value
    )
    return {"status": "ok"}
