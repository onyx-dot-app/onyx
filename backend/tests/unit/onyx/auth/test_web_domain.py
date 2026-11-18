import pytest
from fastapi import WebSocketException
from starlette.requests import Request
from starlette.types import Message, Scope
from starlette.websockets import WebSocket

from onyx.auth import users, web_domain

_WEB_DOMAIN = "https://cloud.example.com"
_ALTERNATE = "https://agent.customer.example"
_ALTERNATE_WITH_PORT = "http://127.0.0.1:3000"


def _request(headers: dict[str, str]) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/auth/oauth/authorize",
            "headers": [
                (name.encode(), value.encode()) for name, value in headers.items()
            ],
        }
    )


async def _unused_receive() -> Message:
    raise NotImplementedError


async def _unused_send(_message: Message) -> None:
    raise NotImplementedError


def _websocket(origin: str) -> WebSocket:
    scope: Scope = {
        "type": "websocket",
        "path": "/ws",
        "headers": [(b"origin", origin.encode())],
    }
    return WebSocket(scope, receive=_unused_receive, send=_unused_send)


@pytest.fixture
def alternates(monkeypatch: pytest.MonkeyPatch) -> None:
    alternate_web_domains = [_ALTERNATE, _ALTERNATE_WITH_PORT]
    monkeypatch.setattr(web_domain, "WEB_DOMAIN", _WEB_DOMAIN)
    monkeypatch.setattr(web_domain, "ALTERNATE_WEB_DOMAINS", alternate_web_domains)
    monkeypatch.setattr(
        web_domain,
        "_ALTERNATE_ORIGINS_BY_HOST",
        web_domain._alternate_origins_by_host(alternate_web_domains),
    )


def test_no_alternates_always_returns_web_domain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(web_domain, "WEB_DOMAIN", _WEB_DOMAIN)
    monkeypatch.setattr(web_domain, "_ALTERNATE_ORIGINS_BY_HOST", {})

    request = _request({"host": "agent.customer.example"})

    assert web_domain.get_request_web_domain(request) == _WEB_DOMAIN


@pytest.mark.usefixtures("alternates")
@pytest.mark.parametrize(
    "headers,expected",
    [
        # Direct through the ingress: Host is the browser's host.
        ({"host": "agent.customer.example"}, _ALTERNATE),
        ({"host": "AGENT.customer.example"}, _ALTERNATE),
        # From the web server: Host is internal, the forwarded host is the browser's.
        (
            {
                "host": "api-server:8080",
                "x-forwarded-host": "agent.customer.example",
            },
            _ALTERNATE,
        ),
        ({"x-forwarded-host": "agent.customer.example, proxy.internal"}, _ALTERNATE),
        ({"host": "127.0.0.1:3000"}, _ALTERNATE_WITH_PORT),
        # Canonical host, unknown hosts and a port mismatch fall back.
        ({"host": "cloud.example.com"}, _WEB_DOMAIN),
        ({"host": "api-server:8080"}, _WEB_DOMAIN),
        ({"host": "evil.example"}, _WEB_DOMAIN),
        ({"x-forwarded-host": "evil.example"}, _WEB_DOMAIN),
        ({"host": "127.0.0.1:4000"}, _WEB_DOMAIN),
        ({}, _WEB_DOMAIN),
    ],
)
def test_get_request_web_domain(headers: dict[str, str], expected: str) -> None:
    assert web_domain.get_request_web_domain(_request(headers)) == expected


@pytest.mark.parametrize(
    "origin",
    [
        "agent.customer.example",
        "ftp://agent.customer.example",
        "https://agent.customer.example/path",
        "https://agent.customer.example?x=1",
        "https://",
    ],
)
def test_invalid_alternate_web_domain_is_rejected(origin: str) -> None:
    with pytest.raises(ValueError):
        web_domain._alternate_origins_by_host([origin])


@pytest.mark.usefixtures("alternates")
@pytest.mark.parametrize("origin", [_WEB_DOMAIN, _ALTERNATE])
def test_websocket_accepts_configured_origins(origin: str) -> None:
    users._check_websocket_origin(_websocket(origin))


@pytest.mark.usefixtures("alternates")
def test_websocket_rejects_other_origins() -> None:
    with pytest.raises(WebSocketException):
        users._check_websocket_origin(_websocket("https://evil.example"))
