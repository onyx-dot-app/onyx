"""The shared Graph limiter against the mock server: Microsoft's Retry-After
pauses every connector on the app registration."""

import threading
import time
from collections.abc import Iterator
from uuid import uuid4

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors import source_api_limiter
from onyx.connectors.load_all import load_all_from_connector
from onyx.connectors.microsoft_utils.request_pacer import MICROSOFT_USER_AGENT
from onyx.connectors.sharepoint.connector import SharepointConnector
from onyx.connectors.source_api_limiter import build_source_api_limiter
from onyx.redis.redis_pool import get_redis_client
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from tests.external_dependency_unit.connectors.sharepoint.conftest import (
    MockSharepoint,
)

_RETRY_AFTER_SECONDS = 2


@pytest.fixture
def limiter_tenant(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """The limiter on, in a tenant of its own, so runs cannot collide."""
    monkeypatch.setattr(source_api_limiter, "ENABLE_SOURCE_API_LIMITER", True)
    tenant = f"tenant_test_{uuid4().hex[:12]}"
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(tenant)
    yield tenant
    CURRENT_TENANT_ID_CONTEXTVAR.reset(token)
    client = get_redis_client(tenant_id=tenant)
    for key in client.scan_iter("*"):
        client.delete(key)


def _limited_connector(
    mock_sharepoint: MockSharepoint, stop: threading.Event
) -> SharepointConnector:
    """A connector with the limiter of its app, as the factory builds it.
    Each call is a new limiter object, like a connector in another pod."""
    connector = mock_sharepoint.build_connector()
    limiter = build_source_api_limiter(
        DocumentSource.SHAREPOINT,
        credential_id=int(uuid4().int % 1_000_000_000),
        should_stop=stop.is_set,
        load_credential_json=mock_sharepoint.credentials,
    )
    assert limiter is not None
    connector.set_source_api_limiter(limiter)
    return connector


def test_a_retry_after_pauses_a_second_connector_on_the_app(
    own_mock_sharepoint: MockSharepoint,
    limiter_tenant: str,  # noqa: ARG001
) -> None:
    # 5 RU in each 2 s, and a wait of 2 s when the app passes it. A full run
    # of the corpus needs more.
    own_mock_sharepoint.patch_config(
        {
            "quota": {
                "window_seconds": 2.0,
                "ru_per_minute": 150,
                "retry_after_seconds": _RETRY_AFTER_SECONDS,
            }
        }
    )
    own_mock_sharepoint.reset_stats()
    stop = threading.Event()
    first = _limited_connector(own_mock_sharepoint, stop)
    second = _limited_connector(own_mock_sharepoint, stop)

    def run_first() -> None:
        try:
            load_all_from_connector(first, 0, time.time())
        except Exception:  # noqa: BLE001 - the stop signal ends the run
            return

    runner = threading.Thread(target=run_first, daemon=True)
    runner.start()
    try:
        deadline = time.monotonic() + 30
        while own_mock_sharepoint.stats()["throttled"] == 0:
            assert time.monotonic() < deadline, "the mock refused no call"
            time.sleep(0.05)  # test-flakes: allow the test polls the mock's stats
        throttled_at = time.monotonic()
        # The first connector stops, so only the second one calls from here.
        stop.set()
        runner.join(timeout=30)
        assert not runner.is_alive()

        stop.clear()
        site_urls = second.ops.list_site_urls().site_urls
        waited = time.monotonic() - throttled_at
    finally:
        stop.set()

    assert site_urls
    # The second connector's first call waited for the pause to end.
    assert waited >= _RETRY_AFTER_SECONDS - 0.5
    stats = own_mock_sharepoint.stats()
    assert stats["throttled"] >= 1
    assert stats["calls_during_pause_total"] == 0
    # The Graph calls name the client. The sign-in calls of MSAL do not.
    assert stats["user_agents"][MICROSOFT_USER_AGENT] > 0
