import json
import socket
from collections.abc import Iterator
from unittest.mock import AsyncMock, Mock

import pytest
from fastmcp.server.auth import cimd, ssrf
from fastmcp.server.auth.ssrf import SSRFFetchError, SSRFFetchResponse

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.oauth_provider.config import OAuthProviderSettings
from onyx.server.oauth_provider.provider import (
    OAuthClientMetadataUnavailable,
    OnyxOAuthProvider,
    _cimd_fetcher,
)

CLIENT_ID = "https://client.example/oauth.json"
SETTINGS = OAuthProviderSettings(
    issuer_url="https://onyx.example/api/oauth-provider",
    mcp_resource_url="https://onyx.example/mcp/",
    web_url="https://onyx.example",
    web_origin="https://onyx.example",
)


@pytest.fixture(autouse=True)
def clear_client_cache() -> Iterator[None]:
    _cimd_fetcher.cache_clear()
    yield
    _cimd_fetcher.cache_clear()


def metadata_response(
    client_id: str = CLIENT_ID,
    *,
    cache_control: str = "max-age=300",
    redirect_uri: str = "https://client.example/callback",
) -> SSRFFetchResponse:
    return SSRFFetchResponse(
        content=json.dumps(
            {
                "client_id": client_id,
                "client_name": "Search client",
                "redirect_uris": [redirect_uri],
                "token_endpoint_auth_method": "none",
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
            }
        ).encode(),
        status_code=200,
        headers={"Cache-Control": cache_control},
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "cache_control, expected_fetches", [("max-age=300", 1), ("no-store", 2)]
)
async def test_cache_policy_applies_across_provider_instances(
    monkeypatch: pytest.MonkeyPatch, cache_control: str, expected_fetches: int
) -> None:
    fetch = AsyncMock(return_value=metadata_response(cache_control=cache_control))
    monkeypatch.setattr(cimd, "ssrf_safe_fetch_response", fetch)
    for _ in range(2):
        client = await OnyxOAuthProvider(SETTINGS).get_client(CLIENT_ID)
        assert client is not None
        assert client.client_id == CLIENT_ID
        assert client.token_endpoint_auth_method == "none"
    assert fetch.await_count == expected_fetches


@pytest.mark.asyncio
async def test_cache_evicts_oldest_client(monkeypatch: pytest.MonkeyPatch) -> None:
    identifiers = [f"https://client.example/{index}.json" for index in range(129)]
    fetch = AsyncMock(
        side_effect=[metadata_response(identifier) for identifier in identifiers]
        + [metadata_response(identifiers[0])]
    )
    monkeypatch.setattr(cimd, "ssrf_safe_fetch_response", fetch)
    provider = OnyxOAuthProvider(SETTINGS)
    for identifier in identifiers:
        assert await provider.get_client(identifier) is not None
    assert _cimd_fetcher.cache_info().currsize == 128
    assert await provider.get_client(identifiers[-1]) is not None
    assert fetch.await_count == 129
    assert await provider.get_client(identifiers[0]) is not None
    assert fetch.await_count == 130


@pytest.mark.asyncio
async def test_expired_metadata_revalidates_with_etag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 1000.0
    monkeypatch.setattr(cimd.time, "time", lambda: now)
    response = metadata_response(cache_control="max-age=60")
    response.headers["ETag"] = '"version-one"'
    fetch = AsyncMock(
        side_effect=[
            response,
            SSRFFetchResponse(content=b"", status_code=304, headers={}),
        ]
    )
    monkeypatch.setattr(cimd, "ssrf_safe_fetch_response", fetch)
    provider = OnyxOAuthProvider(SETTINGS)
    original = await provider.get_client(CLIENT_ID)
    assert original is not None
    now = 1061.0
    assert await provider.get_client(CLIENT_ID) == original
    assert fetch.call_args.kwargs["request_headers"] == {
        "If-None-Match": '"version-one"'
    }
    now = 1100.0
    assert await provider.get_client(CLIENT_ID) == original
    assert fetch.await_count == 2


@pytest.mark.asyncio
async def test_metadata_fetch_outage_is_not_invalid_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetch = AsyncMock(side_effect=SSRFFetchError("upstream unavailable"))
    monkeypatch.setattr(cimd, "ssrf_safe_fetch_response", fetch)
    with pytest.raises(OAuthClientMetadataUnavailable) as caught:
        await OnyxOAuthProvider(SETTINGS).get_client(CLIENT_ID)
    assert caught.value.error_code == OnyxErrorCode.SERVICE_UNAVAILABLE


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "client_id, redirect_uri",
    [
        (CLIENT_ID + "/", "https://client.example/callback"),
        ("https://other.example/oauth.json", "https://client.example/callback"),
        (CLIENT_ID, "https://client.example/*"),
        (CLIENT_ID, "http://client.example/callback"),
    ],
)
async def test_invalid_metadata_is_not_a_client(
    monkeypatch: pytest.MonkeyPatch, client_id: str, redirect_uri: str
) -> None:
    fetch = AsyncMock(
        return_value=metadata_response(client_id, redirect_uri=redirect_uri)
    )
    monkeypatch.setattr(cimd, "ssrf_safe_fetch_response", fetch)
    assert await OnyxOAuthProvider(SETTINGS).get_client(CLIENT_ID) is None


@pytest.mark.asyncio
async def test_private_metadata_url_is_blocked() -> None:
    assert (
        await OnyxOAuthProvider(SETTINGS).get_client("https://127.0.0.1/oauth.json")
        is None
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error_number", [socket.EAI_AGAIN, socket.EAI_FAIL, socket.EAI_NONAME]
)
async def test_dns_failure_classification(
    monkeypatch: pytest.MonkeyPatch, error_number: int
) -> None:
    resolver = Mock(side_effect=socket.gaierror(error_number, "DNS lookup failed"))
    monkeypatch.setattr(ssrf.socket, "getaddrinfo", resolver)
    provider = OnyxOAuthProvider(SETTINGS)
    if error_number == socket.EAI_NONAME:
        assert await provider.get_client(CLIENT_ID) is None
    else:
        with pytest.raises(OAuthClientMetadataUnavailable):
            await provider.get_client(CLIENT_ID)
    resolver.assert_called_once()
