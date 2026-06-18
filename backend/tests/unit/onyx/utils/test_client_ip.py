"""Unit tests for get_client_ip, current_client_ip, and ClientIPMiddleware."""

from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi import Request
from fastapi.testclient import TestClient

from onyx.utils.client_ip import ClientIPMiddleware
from onyx.utils.client_ip import current_client_ip
from onyx.utils.client_ip import get_client_ip


def _fake_request(
    *, xff: str | None = None, client_host: str | None = None
) -> MagicMock:
    req = MagicMock()
    req.headers = {"x-forwarded-for": xff} if xff is not None else {}
    if client_host:
        req.client = MagicMock()
        req.client.host = client_host
    else:
        req.client = None
    return req


def test_walks_xff_right_to_left_skipping_private_hops() -> None:
    """Proxies append their immediate peer on the right. The real client
    sits one-past the rightmost private hop — not the leftmost entry.
    """
    req = _fake_request(xff="8.8.8.8, 10.0.0.1, 192.168.0.1", client_host="10.0.0.2")
    assert get_client_ip(req) == "8.8.8.8"


def test_ignores_client_supplied_public_spoof_at_the_left() -> None:
    """If a client prepends a fake public IP at the leftmost position, it
    must not be returned. The rightmost public IP (added by our outermost
    trusted proxy) is the real client.
    """
    # Client tried to spoof `1.2.3.4`; ALB appended the true client `8.8.8.8`;
    # ingress-nginx appended its own peer `10.0.0.1`.
    req = _fake_request(xff="1.2.3.4, 8.8.8.8, 10.0.0.1", client_host=None)
    assert get_client_ip(req) == "8.8.8.8"


def test_falls_back_to_client_host_when_no_xff() -> None:
    req = _fake_request(xff=None, client_host="9.9.9.9")
    assert get_client_ip(req) == "9.9.9.9"


def test_all_private_xff_falls_back_to_client() -> None:
    req = _fake_request(xff="10.0.0.5", client_host="9.9.9.9")
    assert get_client_ip(req) == "9.9.9.9"


def test_returns_none_when_nothing_is_globally_routable() -> None:
    req = _fake_request(xff="10.0.0.5", client_host="172.31.0.42")
    assert get_client_ip(req) is None


def test_returns_none_when_xff_malformed_and_no_client() -> None:
    req = _fake_request(xff="not-an-ip", client_host=None)
    assert get_client_ip(req) is None


def test_empty_xff_falls_back_to_client_host() -> None:
    req = _fake_request(xff="", client_host="1.1.1.1")
    assert get_client_ip(req) == "1.1.1.1"


def test_loopback_is_not_treated_as_global() -> None:
    req = _fake_request(xff="127.0.0.1", client_host=None)
    assert get_client_ip(req) is None


def test_ipv6_global_is_accepted() -> None:
    req = _fake_request(xff="2001:db8::1", client_host=None)
    # 2001:db8::/32 is documentation-reserved (not global). Real global IPv6 works:
    req2 = _fake_request(xff="2606:4700:4700::1111", client_host=None)
    assert get_client_ip(req) is None
    assert get_client_ip(req2) == "2606:4700:4700::1111"


def test_current_client_ip_is_none_outside_request() -> None:
    """No request context = no IP. Used by telemetry called from Celery."""
    assert current_client_ip() is None


def _app_reading_contextvar() -> FastAPI:
    app = FastAPI()
    app.add_middleware(ClientIPMiddleware)

    @app.get("/echo-ip")
    def _echo(_request: Request) -> dict[str, str | None]:
        return {"ip": current_client_ip()}

    return app


def test_middleware_sets_contextvar_for_request() -> None:
    client = TestClient(_app_reading_contextvar())
    res = client.get("/echo-ip", headers={"X-Forwarded-For": "8.8.8.8, 10.0.0.1"})
    assert res.status_code == 200
    assert res.json() == {"ip": "8.8.8.8"}


def test_middleware_resets_contextvar_after_request() -> None:
    """A second request with no usable IP must see a clean contextvar —
    not the value set by the previous request."""
    client = TestClient(_app_reading_contextvar())

    first = client.get("/echo-ip", headers={"X-Forwarded-For": "8.8.8.8"})
    second = client.get("/echo-ip", headers={"X-Forwarded-For": "10.0.0.1"})

    assert first.json() == {"ip": "8.8.8.8"}
    # Private XFF + TestClient-internal client — nothing globally routable:
    assert second.json() == {"ip": None}
    assert current_client_ip() is None


def test_middleware_with_no_routable_ip_sets_none() -> None:
    client = TestClient(_app_reading_contextvar())
    res = client.get("/echo-ip", headers={"X-Forwarded-For": "10.0.0.5"})
    assert res.status_code == 200
    assert res.json() == {"ip": None}
