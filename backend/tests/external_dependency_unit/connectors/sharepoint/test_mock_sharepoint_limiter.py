"""The shared Graph limiter against the mock server: Microsoft's Retry-After
pauses every connector on the app registration, and a stop signal during a
wait for the limiter ends the walk."""

import threading
import time
from collections.abc import Iterator
from uuid import uuid4

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors import source_api_limiter
from onyx.connectors.interfaces import SourceApiLimiter
from onyx.connectors.load_all import load_all_from_connector
from onyx.connectors.microsoft_utils.request_pacer import MICROSOFT_USER_AGENT
from onyx.connectors.models import ConnectorStopSignal
from onyx.connectors.sharepoint.connector import SharepointConnector
from onyx.connectors.source_api_limiter import build_source_api_limiter
from onyx.redis.redis_pool import get_redis_client
from onyx.redis.redis_rate_window import RedisRateWindows
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from tests.external_dependency_unit.connectors.sharepoint.conftest import (
    MockSharepoint,
)

_RETRY_AFTER_SECONDS = 2


class StopAfterLimiter(SourceApiLimiter):
    """Lets ``calls`` calls through, then raises the stop signal, as the
    shared limiter does when the attempt stops during a wait."""

    def __init__(self, calls: int) -> None:
        self._left = calls

    def acquire(
        self,
        api: str,  # noqa: ARG002
        cost: int,  # noqa: ARG002
        user: str | None = None,  # noqa: ARG002
        request_count: int = 1,  # noqa: ARG002
        *,
        bulk: bool = False,  # noqa: ARG002
    ) -> None:
        self._left -= 1
        if self._left < 0:
            raise ConnectorStopSignal("Stop signal while waiting for the API budget")

    def report_rate_limit(
        self,
        api: str,  # noqa: ARG002
        user: str | None,  # noqa: ARG002
        user_scope: bool,  # noqa: ARG002
        count: int = 1,  # noqa: ARG002
    ) -> None:
        return None


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


def _shared_pause_left(tenant: str) -> float:
    """The seconds left of the longest shared pause in the tenant."""
    client = get_redis_client(tenant_id=tenant)
    windows = RedisRateWindows(client)
    return max(
        (
            windows.pause_left(key.decode())
            for key in client.scan_iter("*:blocked_until")
        ),
        default=0.0,
    )


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
    limiter_tenant: str,
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
    first_stop = threading.Event()
    second_stop = threading.Event()
    first = _limited_connector(own_mock_sharepoint, first_stop)
    second = _limited_connector(own_mock_sharepoint, second_stop)

    def run_first() -> None:
        try:
            load_all_from_connector(first, 0, time.time())
        except Exception:  # noqa: BLE001 - the stop signal ends the run
            return

    runner = threading.Thread(target=run_first, daemon=True)
    runner.start()
    try:
        deadline = time.monotonic() + 30
        # The first connector got a 429 and set the shared pause.
        while (
            own_mock_sharepoint.stats()["throttled"] == 0
            or _shared_pause_left(limiter_tenant) <= 0
        ):
            assert time.monotonic() < deadline, "no shared pause was set"
            time.sleep(0.05)  # test-flakes: allow the test polls the mock and Redis
        throttled_at = time.monotonic()
        # Read after throttled_at, so it is never more than the pause that
        # is left at that time.
        pause_left = _shared_pause_left(limiter_tenant)
        # The first connector stops. The second one calls while the pause
        # is still on.
        first_stop.set()
        started = time.monotonic()
        site_urls = second.ops.list_site_urls().site_urls
        ended = time.monotonic()
    finally:
        first_stop.set()
        second_stop.set()
        runner.join(timeout=30)
    assert not runner.is_alive()

    assert site_urls
    # The second connector's first call started in the pause and waited for
    # its end. 0.1 s covers the clock of Redis against the local clock.
    assert started - throttled_at < _RETRY_AFTER_SECONDS / 2
    assert ended - throttled_at >= pause_left - 0.1
    stats = own_mock_sharepoint.stats()
    assert stats["throttled"] >= 1
    assert stats["calls_during_pause_total"] == 0
    # The Graph calls name the client. The sign-in calls of MSAL do not.
    assert stats["user_agents"][MICROSOFT_USER_AGENT] > 0


@pytest.mark.parametrize("calls", [3, 12, 40])
def test_a_stop_during_a_limiter_wait_ends_the_fetching_walk(
    mock_sharepoint: MockSharepoint, calls: int
) -> None:
    """The stop is not a failure of one document, drive or site: the walk
    raises it, and yields no failure for it."""
    connector = mock_sharepoint.build_connector()
    connector.set_source_api_limiter(StopAfterLimiter(calls))

    with pytest.raises(ConnectorStopSignal):
        load_all_from_connector(connector, 0, time.time())


@pytest.mark.usefixtures("ee_permission_sync")
@pytest.mark.parametrize("calls", [3, 40, 150])
def test_a_stop_during_a_limiter_wait_ends_the_slim_walk(
    mock_sharepoint: MockSharepoint, calls: int
) -> None:
    """Permission sync marks a document that the slim walk does not list as
    private, so a stop must end the walk and not skip the rest of it."""
    connector = mock_sharepoint.build_connector(certificate=True)
    connector.set_source_api_limiter(StopAfterLimiter(calls))

    with pytest.raises(ConnectorStopSignal):
        for _ in connector.retrieve_all_slim_docs_perm_sync(0, time.time()):
            pass
