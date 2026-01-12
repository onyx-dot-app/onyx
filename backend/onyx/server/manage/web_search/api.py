from __future__ import annotations

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Response
from sqlalchemy.orm import Session

from onyx.auth.users import current_admin_user
from onyx.db.engine.sql_engine import get_session
from onyx.db.models import User
from onyx.db.web_search import deactivate_web_content_provider
from onyx.db.web_search import deactivate_web_search_provider
from onyx.db.web_search import delete_web_content_provider
from onyx.db.web_search import delete_web_search_provider
from onyx.db.web_search import fetch_web_content_provider_by_name
from onyx.db.web_search import fetch_web_content_provider_by_type
from onyx.db.web_search import fetch_web_content_providers
from onyx.db.web_search import fetch_web_search_provider_by_name
from onyx.db.web_search import fetch_web_search_provider_by_type
from onyx.db.web_search import fetch_web_search_providers
from onyx.db.web_search import set_active_web_content_provider
from onyx.db.web_search import set_active_web_search_provider
from onyx.db.web_search import upsert_web_content_provider
from onyx.db.web_search import upsert_web_search_provider
from onyx.server.manage.web_search.models import WebContentProviderTestRequest
from onyx.server.manage.web_search.models import WebContentProviderUpsertRequest
from onyx.server.manage.web_search.models import WebContentProviderView
from onyx.server.manage.web_search.models import WebSearchProviderTestRequest
from onyx.server.manage.web_search.models import WebSearchProviderUpsertRequest
from onyx.server.manage.web_search.models import WebSearchProviderView
from onyx.tools.tool_implementations.open_url.utils import (
    filter_web_contents_with_no_title_or_content,
)
from onyx.tools.tool_implementations.web_search.providers import (
    build_content_provider_from_config,
)
from onyx.tools.tool_implementations.web_search.providers import (
    build_search_provider_from_config,
)
from onyx.utils.logger import setup_logger
from shared_configs.enums import WebContentProviderType
from shared_configs.enums import WebSearchProviderType

logger = setup_logger()

admin_router = APIRouter(prefix="/admin/web-search")


@admin_router.get("/search-providers", response_model=list[WebSearchProviderView])
def list_search_providers(
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> list[WebSearchProviderView]:
    providers = fetch_web_search_providers(db_session)
    return [
        WebSearchProviderView(
            id=provider.id,
            name=provider.name,
            provider_type=WebSearchProviderType(provider.provider_type),
            is_active=provider.is_active,
            config=provider.config or {},
            has_api_key=bool(provider.api_key),
        )
        for provider in providers
    ]


@admin_router.post("/search-providers", response_model=WebSearchProviderView)
def upsert_search_provider_endpoint(
    request: WebSearchProviderUpsertRequest,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> WebSearchProviderView:
    existing_by_name = fetch_web_search_provider_by_name(request.name, db_session)
    if (
        existing_by_name
        and request.id is not None
        and existing_by_name.id != request.id
    ):
        raise HTTPException(
            status_code=400,
            detail=f"A search provider named '{request.name}' already exists.",
        )

    provider = upsert_web_search_provider(
        provider_id=request.id,
        name=request.name,
        provider_type=request.provider_type,
        api_key=request.api_key,
        api_key_changed=request.api_key_changed,
        config=request.config,
        activate=request.activate,
        db_session=db_session,
    )

    db_session.commit()
    return WebSearchProviderView(
        id=provider.id,
        name=provider.name,
        provider_type=WebSearchProviderType(provider.provider_type),
        is_active=provider.is_active,
        config=provider.config or {},
        has_api_key=bool(provider.api_key),
    )


@admin_router.delete(
    "/search-providers/{provider_id}", status_code=204, response_class=Response
)
def delete_search_provider(
    provider_id: int,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> Response:
    delete_web_search_provider(provider_id, db_session)
    return Response(status_code=204)


@admin_router.post("/search-providers/{provider_id}/activate")
def activate_search_provider(
    provider_id: int,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> WebSearchProviderView:
    provider = set_active_web_search_provider(
        provider_id=provider_id, db_session=db_session
    )
    db_session.commit()
    return WebSearchProviderView(
        id=provider.id,
        name=provider.name,
        provider_type=WebSearchProviderType(provider.provider_type),
        is_active=provider.is_active,
        config=provider.config or {},
        has_api_key=bool(provider.api_key),
    )


@admin_router.post("/search-providers/{provider_id}/deactivate")
def deactivate_search_provider(
    provider_id: int,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> dict[str, str]:
    deactivate_web_search_provider(provider_id=provider_id, db_session=db_session)
    db_session.commit()
    return {"status": "ok"}


@admin_router.post("/search-providers/test")
def test_search_provider(
    request: WebSearchProviderTestRequest,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> dict[str, str]:
    provider_requires_api_key = request.provider_type != WebSearchProviderType.SEARXNG

    # Determine which API key to use
    api_key = request.api_key
    if request.use_stored_key and provider_requires_api_key:
        existing_provider = fetch_web_search_provider_by_type(
            request.provider_type, db_session
        )
        if existing_provider is None or not existing_provider.api_key:
            raise HTTPException(
                status_code=400,
                detail="No stored API key found for this provider type.",
            )
        api_key = existing_provider.api_key

    if provider_requires_api_key and not api_key:
        raise HTTPException(
            status_code=400,
            detail="API key is required. Either provide api_key or set use_stored_key to true.",
        )

    try:
        provider = build_search_provider_from_config(
            provider_type=request.provider_type,
            api_key=api_key or "",
            config=request.config or {},
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if provider is None:
        raise HTTPException(
            status_code=400, detail="Unable to build provider configuration."
        )

    # Run the API client's test_connection method to ensure the connection is valid.
    try:
        return provider.test_connection()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@admin_router.get("/content-providers", response_model=list[WebContentProviderView])
def list_content_providers(
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> list[WebContentProviderView]:
    providers = fetch_web_content_providers(db_session)
    return [
        WebContentProviderView(
            id=provider.id,
            name=provider.name,
            provider_type=WebContentProviderType(provider.provider_type),
            is_active=provider.is_active,
            config=provider.config or {},
            has_api_key=bool(provider.api_key),
        )
        for provider in providers
    ]


@admin_router.post("/content-providers", response_model=WebContentProviderView)
def upsert_content_provider_endpoint(
    request: WebContentProviderUpsertRequest,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> WebContentProviderView:
    existing_by_name = fetch_web_content_provider_by_name(request.name, db_session)
    if (
        existing_by_name
        and request.id is not None
        and existing_by_name.id != request.id
    ):
        raise HTTPException(
            status_code=400,
            detail=f"A content provider named '{request.name}' already exists.",
        )

    provider = upsert_web_content_provider(
        provider_id=request.id,
        name=request.name,
        provider_type=request.provider_type,
        api_key=request.api_key,
        api_key_changed=request.api_key_changed,
        config=request.config,
        activate=request.activate,
        db_session=db_session,
    )

    db_session.commit()
    return WebContentProviderView(
        id=provider.id,
        name=provider.name,
        provider_type=WebContentProviderType(provider.provider_type),
        is_active=provider.is_active,
        config=provider.config or {},
        has_api_key=bool(provider.api_key),
    )


@admin_router.delete(
    "/content-providers/{provider_id}", status_code=204, response_class=Response
)
def delete_content_provider(
    provider_id: int,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> Response:
    delete_web_content_provider(provider_id, db_session)
    return Response(status_code=204)


@admin_router.post("/content-providers/{provider_id}/activate")
def activate_content_provider(
    provider_id: int,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> WebContentProviderView:
    provider = set_active_web_content_provider(
        provider_id=provider_id, db_session=db_session
    )
    db_session.commit()
    return WebContentProviderView(
        id=provider.id,
        name=provider.name,
        provider_type=WebContentProviderType(provider.provider_type),
        is_active=provider.is_active,
        config=provider.config or {},
        has_api_key=bool(provider.api_key),
    )


@admin_router.post("/content-providers/reset-default")
def reset_content_provider_default(
    _: User | None = Depends(current_admin_user),
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
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> dict[str, str]:
    deactivate_web_content_provider(provider_id=provider_id, db_session=db_session)
    db_session.commit()
    return {"status": "ok"}


@admin_router.post("/content-providers/test")
def test_content_provider(
    request: WebContentProviderTestRequest,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> dict[str, str]:
    # Determine which API key to use
    api_key = request.api_key
    if request.use_stored_key:
        existing_provider = fetch_web_content_provider_by_type(
            request.provider_type, db_session
        )
        if existing_provider is None or not existing_provider.api_key:
            raise HTTPException(
                status_code=400,
                detail="No stored API key found for this provider type.",
            )
        api_key = existing_provider.api_key

    if not api_key:
        raise HTTPException(
            status_code=400,
            detail="API key is required. Either provide api_key or set use_stored_key to true.",
        )

    try:
        provider = build_content_provider_from_config(
            provider_type=request.provider_type,
            api_key=api_key,
            config=request.config,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if provider is None:
        raise HTTPException(
            status_code=400, detail="Unable to build provider configuration."
        )

    # Actually test the API key by making a real content fetch call
    try:
        test_url = "https://example.com"
        test_results = filter_web_contents_with_no_title_or_content(
            list(provider.contents([test_url]))
        )
        if not test_results or not any(
            result.scrape_successful for result in test_results
        ):
            raise HTTPException(
                status_code=400,
                detail="API key validation failed: content fetch returned no results.",
            )
    except HTTPException:
        raise
    except Exception as e:
        error_msg = str(e)
        if (
            "api" in error_msg.lower()
            or "key" in error_msg.lower()
            or "auth" in error_msg.lower()
        ):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid API key: {error_msg}",
            ) from e
        raise HTTPException(
            status_code=400,
            detail=f"API key validation failed: {error_msg}",
        ) from e

    logger.info(
        f"Web content provider test succeeded for {request.provider_type.value}."
    )
    return {"status": "ok"}
