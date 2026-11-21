"""The Microsoft Graph limiter against a real Redis: one budget and one pause
for each app registration in a tenant, shared by every connector on the app.

Each test uses a unique tenant, so runs cannot collide. Separate limiter
objects stand in for separate worker pods: they share only Redis."""

import threading
import time
from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import pytest
from prometheus_client import REGISTRY

from onyx.configs.constants import DocumentSource
from onyx.connectors import source_api_limiter
from onyx.connectors.microsoft_utils.request_pacer import DOWNLOAD_LIMITER_API
from onyx.connectors.models import ConnectorStopSignal
from onyx.connectors.source_api_limiter import (
    RedisSourceApiLimiter,
    build_source_api_limiter,
    microsoft_app_key,
)
from onyx.redis.redis_pool import get_redis_client
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

_API = "graph"
_DIRECTORY = "11111111-AAAA-4111-8111-111111111111"
_CLIENT = "22222222-BBBB-4222-8222-222222222222"
_SECRET = "s3cret-value-that-must-not-leak"


@pytest.fixture
def tenant_id() -> Iterator[str]:
    tenant = f"tenant_test_{uuid4().hex[:12]}"
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(tenant)
    yield tenant
    CURRENT_TENANT_ID_CONTEXTVAR.reset(token)
    client = get_redis_client(tenant_id=tenant)
    for key in client.scan_iter("*"):
        client.delete(key)


@pytest.fixture(autouse=True)
def limiter_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(source_api_limiter, "ENABLE_SOURCE_API_LIMITER", True)


def _credential(prefix: str, client_id: str = _CLIENT) -> dict[str, str]:
    return {
        f"{prefix}_client_id": client_id,
        f"{prefix}_directory_id": _DIRECTORY,
        f"{prefix}_client_secret": _SECRET,
    }


def _build(
    source: DocumentSource,
    prefix: str,
    client_id: str = _CLIENT,
    should_stop: threading.Event | None = None,
) -> RedisSourceApiLimiter:
    limiter = build_source_api_limiter(
        source,
        credential_id=int(uuid4().int % 1_000_000_000),
        should_stop=should_stop.is_set if should_stop else None,
        load_credential_json=lambda: _credential(prefix, client_id),
    )
    assert isinstance(limiter, RedisSourceApiLimiter)
    return limiter


def test_the_key_is_the_directory_and_the_client_and_holds_no_secret() -> None:
    key = microsoft_app_key(DocumentSource.SHAREPOINT, _credential("sp"))

    assert key == f"microsoft:{_DIRECTORY.lower()}:{_CLIENT.lower()}"
    # Every Microsoft Graph source on the app has the same key.
    assert microsoft_app_key(DocumentSource.TEAMS, _credential("teams")) == key
    assert microsoft_app_key(DocumentSource.ONEDRIVE, _credential("onedrive")) == key
    assert microsoft_app_key(DocumentSource.OUTLOOK, _credential("outlook")) == key
    # Other sources, and a credential with no app, have none.
    assert microsoft_app_key(DocumentSource.GOOGLE_DRIVE, _credential("sp")) is None
    assert microsoft_app_key(DocumentSource.AZURE_DATALAKE, _credential("adls")) is None
    assert microsoft_app_key(DocumentSource.SHAREPOINT, {}) is None


def test_the_limiter_is_off_by_default_and_needs_the_credential(
    tenant_id: str,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert build_source_api_limiter(DocumentSource.SHAREPOINT, 1) is None
    monkeypatch.setattr(source_api_limiter, "ENABLE_SOURCE_API_LIMITER", False)
    assert (
        build_source_api_limiter(
            DocumentSource.SHAREPOINT, 1, load_credential_json=lambda: _credential("sp")
        )
        is None
    )


def test_connectors_on_one_app_share_the_budget(tenant_id: str) -> None:
    sharepoint = _build(DocumentSource.SHAREPOINT, "sp")
    teams = _build(DocumentSource.TEAMS, "teams")
    other_app = _build(DocumentSource.SHAREPOINT, "sp", client_id=str(uuid4()))

    # The window is 10 s of the minute budget, at the start share.
    budget = source_api_limiter.MICROSOFT_GRAPH_BUDGETS[_API]
    assert budget.per_credential is not None and budget.window_seconds is not None
    room = int(
        budget.per_credential
        * budget.window_seconds
        / budget.period_seconds
        * source_api_limiter.MICROSOFT_START_SHARE
    )
    assert sharepoint.try_acquire(_API, room) == 0
    assert teams.try_acquire(_API, 1) > 0
    assert other_app.try_acquire(_API, 1) == 0

    keys = [
        key.decode() if isinstance(key, bytes) else str(key)
        for key in get_redis_client(tenant_id=tenant_id).scan_iter("*")
    ]
    assert keys and not any(_SECRET in key for key in keys)


def test_a_retry_after_pauses_every_caller_on_the_app(tenant_id: str) -> None:  # noqa: ARG001
    sharepoint = _build(DocumentSource.SHAREPOINT, "sp")
    onedrive = _build(DocumentSource.ONEDRIVE, "onedrive")
    other_app = _build(DocumentSource.SHAREPOINT, "sp", client_id=str(uuid4()))

    sharepoint.report_retry_after(_API, 1.0)
    # A shorter wait does not end the pause sooner.
    onedrive.report_retry_after(_API, 0.1)

    started = time.monotonic()
    other_app.acquire(_API, 1)
    assert time.monotonic() - started < 0.5
    onedrive.acquire(_API, 1)
    waited = time.monotonic() - started
    assert 0.8 <= waited < 3

    paused = REGISTRY.get_sample_value(
        "onyx_source_api_limiter_paused_seconds_total",
        {"source": DocumentSource.ONEDRIVE.value, "api": _API},
    )
    assert paused is not None and paused >= 0.8
    assert (
        REGISTRY.get_sample_value(
            "onyx_source_api_limiter_units_total",
            {"source": DocumentSource.ONEDRIVE.value, "api": _API},
        )
        or 0
    ) >= 1


def test_a_download_lane_pause_does_not_stop_graph_calls(
    tenant_id: str,  # noqa: ARG001
) -> None:
    """The download host throttles on its own. Its pause stops the link
    downloads of every connector on the app, and no Graph call."""
    sharepoint = _build(DocumentSource.SHAREPOINT, "sp")
    onedrive = _build(DocumentSource.ONEDRIVE, "onedrive")

    sharepoint.report_retry_after(DOWNLOAD_LIMITER_API, 1.0)

    started = time.monotonic()
    onedrive.acquire(_API, 1)
    assert time.monotonic() - started < 0.5
    onedrive.acquire(DOWNLOAD_LIMITER_API, 1)
    assert 0.8 <= time.monotonic() - started < 3


class _RecordingLogger:
    """Keeps the text of each log line."""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def _record(self, message: str, *args: Any, **_kwargs: Any) -> None:
        self.lines.append(message % args if args else message)

    debug = info = warning = error = exception = _record


def test_log_lines_hold_no_app_ids(
    tenant_id: str,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The limiter key of a Microsoft app holds its directory id and client
    id. The log lines show a hash of the key instead."""
    recorder = _RecordingLogger()
    monkeypatch.setattr(source_api_limiter, "logger", recorder)
    limiter = _build(DocumentSource.SHAREPOINT, "sp")

    limiter.acquire(_API, 1)
    limiter.report_retry_after(_API, 0.1)
    for _ in range(20):
        limiter.report_rate_limit(_API, None, user_scope=False)

    assert any("starts at" in line for line in recorder.lines)
    assert any("Retry-After" in line for line in recorder.lines)
    for line in recorder.lines:
        assert _DIRECTORY.lower() not in line.lower(), line
        assert _CLIENT.lower() not in line.lower(), line


def test_a_stop_signal_ends_the_wait_for_a_pause(tenant_id: str) -> None:  # noqa: ARG001
    stop = threading.Event()
    limiter = _build(DocumentSource.SHAREPOINT, "sp", should_stop=stop)
    limiter.report_retry_after(_API, 120.0)
    stop.set()

    started = time.monotonic()
    with pytest.raises(ConnectorStopSignal):
        limiter.acquire(_API, 1)
    assert time.monotonic() - started < 2


def test_the_drive_limiter_has_no_pause(tenant_id: str) -> None:  # noqa: ARG001
    limiter = build_source_api_limiter(
        DocumentSource.GOOGLE_DRIVE, int(uuid4().int % 1_000_000_000)
    )
    assert isinstance(limiter, RedisSourceApiLimiter)

    limiter.report_retry_after("drive", 60.0)

    started = time.monotonic()
    limiter.acquire("drive", 1, "a@x.com")
    assert time.monotonic() - started < 1


# A connector with its own RU per minute.


def _build_with_value(
    cc_pair_id: int, ru_per_minute: int, client_id: str = _CLIENT
) -> RedisSourceApiLimiter:
    limiter = build_source_api_limiter(
        DocumentSource.SHAREPOINT,
        credential_id=int(uuid4().int % 1_000_000_000),
        load_credential_json=lambda: _credential("sp", client_id),
        cc_pair_id=cc_pair_id,
        connector_specific_config={"ru_per_minute": ru_per_minute},
    )
    assert isinstance(limiter, RedisSourceApiLimiter)
    return limiter


def test_a_connector_with_a_value_has_its_own_window_at_the_full_value(
    tenant_id: str,  # noqa: ARG001
) -> None:
    first = _build_with_value(cc_pair_id=1, ru_per_minute=600)
    same_pair_other_pod = _build_with_value(cc_pair_id=1, ru_per_minute=600)
    second = _build_with_value(cc_pair_id=2, ru_per_minute=600)
    learned = _build(DocumentSource.SHAREPOINT, "sp")

    # 600 RU a minute is 100 in each 10 s window, with no start share.
    assert first.try_acquire(_API, 100) == 0
    assert same_pair_other_pod.try_acquire(_API, 1) > 0
    # The other connectors on the app keep their budgets.
    assert second.try_acquire(_API, 100) == 0
    assert learned.try_acquire(_API, 1) == 0


def test_a_value_needs_the_pair(tenant_id: str) -> None:  # noqa: ARG001
    """With no pair to key the budget by, the connector shares the learned
    budget of the app."""
    limiter = build_source_api_limiter(
        DocumentSource.SHAREPOINT,
        credential_id=1,
        load_credential_json=lambda: _credential("sp"),
        connector_specific_config={"ru_per_minute": 600},
    )
    assert isinstance(limiter, RedisSourceApiLimiter)
    assert limiter.credential_window(_API) == _build(
        DocumentSource.SHAREPOINT, "sp"
    ).credential_window(_API)


def test_a_connector_with_a_value_obeys_the_pause_of_the_app(
    tenant_id: str,  # noqa: ARG001
) -> None:
    with_value = _build_with_value(cc_pair_id=3, ru_per_minute=600)
    learned = _build(DocumentSource.TEAMS, "teams")

    # A 429 for the connector with a value pauses every connector on the app.
    with_value.report_retry_after(_API, 1.0)

    started = time.monotonic()
    learned.acquire(_API, 1)
    assert time.monotonic() - started >= 0.8
    # The pause is over for both.
    with_value.acquire(_API, 1)
    assert time.monotonic() - started < 3


def test_a_refusal_cuts_the_window_of_a_connector_with_a_value(
    tenant_id: str,  # noqa: ARG001
) -> None:
    limiter = _build_with_value(cc_pair_id=4, ru_per_minute=6000)
    for _ in range(100):
        limiter.acquire(_API, 1)
    limiter.report_rate_limit(_API, None, user_scope=False, count=50)

    window = limiter.credential_window(_API)
    assert window is not None
    shares = limiter._windows.try_acquire_with_shares([window], cost=0).shares
    assert shares[0] <= 0.5


def test_the_day_budget_is_960_times_the_value(
    tenant_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    budgets = source_api_limiter.microsoft_connector_budgets(1250)[_API]
    assert budgets.per_credential_per_day == 1_200_000

    # A small day budget, so that the test can fill it.
    monkeypatch.setattr(source_api_limiter, "RU_PER_DAY_FACTOR", 1)
    monkeypatch.setattr(source_api_limiter, "_DAY_RETRY_SECONDS", 0.2)
    stop = threading.Event()
    limiter = build_source_api_limiter(
        DocumentSource.SHAREPOINT,
        credential_id=1,
        should_stop=stop.is_set,
        load_credential_json=lambda: _credential("sp"),
        cc_pair_id=5,
        connector_specific_config={"ru_per_minute": 60},
    )
    assert isinstance(limiter, RedisSourceApiLimiter)
    # 60 RU a minute is 10 in each 10 s window, and here 60 in the day.
    client = get_redis_client(tenant_id=tenant_id)
    for _ in range(6):
        limiter.acquire(_API, 10)
        # Empty the short windows: only the day budget stays.
        for key in client.scan_iter("*cc_pair:5*"):
            name = key.decode() if isinstance(key, bytes) else str(key)
            if not name.endswith(":day"):
                client.delete(key)

    # The day is full. The call waits until the stop signal.
    threading.Timer(0.5, stop.set).start()
    started = time.monotonic()
    with pytest.raises(ConnectorStopSignal):
        limiter.acquire(_API, 10)
    assert 0.3 <= time.monotonic() - started < 5
    # The refused call took nothing: one more unit still does not fit 60.
    day_key = "source_api_limit:microsoft:cc_pair:5:graph:all:day"
    assert limiter._windows.try_take_from_day(day_key, 1, 60) > 0
    assert limiter._windows.try_take_from_day(day_key, 1, 61) == 0
