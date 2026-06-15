from __future__ import annotations

from fastapi.testclient import TestClient

from onyx.search_gateway.config import SearchGatewayConfig
from onyx.search_gateway.models import GatewaySearchRequest
from onyx.search_gateway.models import GatewaySearchResponse
from onyx.search_gateway.models import GatewaySearchResult
from onyx.search_gateway.models import SearchMode
from onyx.search_gateway.server import create_app


class FakeSearchService:
    def __init__(self) -> None:
        self.last_request: GatewaySearchRequest | None = None

    def search(self, request: GatewaySearchRequest) -> GatewaySearchResponse:
        self.last_request = request
        return GatewaySearchResponse(
            results=[
                GatewaySearchResult(
                    title="Result",
                    url="https://example.com/result",
                    snippet="Snippet",
                )
            ]
        )


def _client(
    fake_service: FakeSearchService | None = None,
    *,
    use_real_service: bool = False,
) -> TestClient:
    app = create_app(
        config=SearchGatewayConfig(
            gateway_api_key="gateway-key",
            tavily_api_key="tavily-key",
            tavily_api_url="https://api.tavily.test/search",
            timeout_seconds=15,
            default_channel="tavily",
        ),
        search_service=(
            None if use_real_service else fake_service or FakeSearchService()
        ),
    )
    return TestClient(app, raise_server_exceptions=False)


def test_health_reports_configured_gateway() -> None:
    response = _client().get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "channel": "tavily"}


def test_search_requires_gateway_bearer_token() -> None:
    response = _client().post(
        "/search",
        json={
            "queries": ["gold"],
            "mode": "lite",
            "channel": "tavily",
            "max_results": 5,
            "locale": "zh-CN",
        },
    )

    assert response.status_code == 401
    assert response.json()["error_code"] == "UNAUTHENTICATED"


def test_search_rejects_unsupported_channel() -> None:
    response = _client(use_real_service=True).post(
        "/search",
        headers={"Authorization": "Bearer gateway-key"},
        json={
            "queries": ["gold"],
            "mode": "lite",
            "channel": "serper",
            "max_results": 5,
            "locale": "zh-CN",
        },
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "INVALID_INPUT"


def test_search_delegates_valid_request_to_service() -> None:
    fake_service = FakeSearchService()
    response = _client(fake_service).post(
        "/search",
        headers={"Authorization": "Bearer gateway-key"},
        json={
            "queries": ["gold price"],
            "mode": "deep",
            "channel": "tavily",
            "max_results": 3,
            "locale": "zh-CN",
        },
    )

    assert response.status_code == 200
    assert response.json()["results"] == [
        {
            "title": "Result",
            "url": "https://example.com/result",
            "snippet": "Snippet",
            "author": None,
            "published_date": None,
        }
    ]
    assert fake_service.last_request is not None
    assert fake_service.last_request.queries == ["gold price"]
    assert fake_service.last_request.mode is SearchMode.DEEP
    assert fake_service.last_request.max_results == 3
