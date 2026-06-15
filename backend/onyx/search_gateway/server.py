from __future__ import annotations

from typing import Protocol

from fastapi import FastAPI
from fastapi import Header

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.error_handling.exceptions import register_onyx_exception_handlers
from onyx.search_gateway.config import load_search_gateway_config_from_env
from onyx.search_gateway.config import SearchGatewayConfig
from onyx.search_gateway.models import GatewaySearchRequest
from onyx.search_gateway.models import GatewaySearchResponse
from onyx.search_gateway.service import SearchGatewayService
from onyx.search_gateway.tavily import TavilySearchAdapter


class SearchService(Protocol):
    def search(self, request: GatewaySearchRequest) -> GatewaySearchResponse:
        pass


def create_app(
    *,
    config: SearchGatewayConfig | None = None,
    search_service: SearchService | None = None,
) -> FastAPI:
    resolved_config = config or load_search_gateway_config_from_env()
    app = FastAPI(title="Glomi Search Gateway")
    register_onyx_exception_handlers(app)
    service = search_service

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "channel": resolved_config.default_channel}

    @app.post("/search")
    def search(
        request: GatewaySearchRequest,
        authorization: str | None = Header(default=None),
    ) -> GatewaySearchResponse:
        _validate_gateway_auth(authorization, resolved_config)
        resolved_service = service or _build_search_service(resolved_config)
        return resolved_service.search(request)

    return app


def _build_search_service(config: SearchGatewayConfig) -> SearchService:
    if not config.tavily_api_key:
        raise OnyxError(
            OnyxErrorCode.SERVICE_UNAVAILABLE,
            "TAVILY_API_KEY is required to start the local search gateway.",
        )
    return SearchGatewayService(
        adapters=[
            TavilySearchAdapter(
                api_key=config.tavily_api_key,
                api_url=config.tavily_api_url,
                timeout_seconds=config.timeout_seconds,
            )
        ],
        default_channel=config.default_channel,
    )


def _validate_gateway_auth(
    authorization: str | None,
    config: SearchGatewayConfig,
) -> None:
    if not config.gateway_api_key:
        raise OnyxError(
            OnyxErrorCode.SERVICE_UNAVAILABLE,
            "GLOMI_SEARCH_GATEWAY_API_KEY is required.",
        )

    expected = f"Bearer {config.gateway_api_key}"
    if authorization != expected:
        raise OnyxError(
            OnyxErrorCode.UNAUTHENTICATED,
            "Invalid search gateway bearer token.",
        )


app = create_app()
