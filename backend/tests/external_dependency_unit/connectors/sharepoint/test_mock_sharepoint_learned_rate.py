"""The Microsoft limiter's rate against the mock server, at 20 times speed.

With no admin value, the learned rate settles under the server's RU limit,
with few 429 answers after the first minutes. With a value, the connector
stays under its value.

Time is 20 times faster: the test shortens the limiter's times and the
budgets' periods, and the server counts its RU limit for a 3-second minute.
Each thread makes Graph calls through the connector's own client, so each
call takes its cost from the limiter and a 429 goes through the client's
retry and the pacer.
"""

import threading
from collections.abc import Callable, Iterator
from typing import Any
from uuid import uuid4

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors import source_api_limiter
from onyx.connectors.models import ConnectorStopSignal
from onyx.connectors.sharepoint.connector import SharepointConnector
from onyx.connectors.source_api_limiter import (
    SourceApiBudget,
    build_source_api_limiter,
)
from onyx.redis import redis_rate_window
from onyx.redis.redis_pool import get_redis_client
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from tests.external_dependency_unit.connectors.sharepoint.conftest import (
    MockSharepoint,
)

_SPEED = 20.0
_SCALE = 1 / _SPEED
# One minute of the limiter and of the server, in real seconds.
_MINUTE = 60 * _SCALE
_THREADS = 16
_RUN_SECONDS = 30.0
# The last part of the run, when the rate must have settled.
_SETTLED_SECONDS = 15.0


def _scaled(budget: SourceApiBudget) -> SourceApiBudget:
    return budget.model_copy(
        update={
            "period_seconds": budget.period_seconds * _SCALE,
            "window_seconds": (
                budget.window_seconds * _SCALE
                if budget.window_seconds is not None
                else None
            ),
        }
    )


@pytest.fixture
def fast_limiter(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """The limiter on, in a tenant of its own, with times 20 times shorter.
    The budgets keep their values; only their periods are shorter."""
    monkeypatch.setattr(source_api_limiter, "ENABLE_SOURCE_API_LIMITER", True)
    module = redis_rate_window
    for name, seconds in (
        ("REFUSAL_WINDOW_SECONDS", module.REFUSAL_WINDOW_SECONDS),
        ("CUT_HOLD_SECONDS", module.CUT_HOLD_SECONDS),
        ("STORM_RECUT_SECONDS", module.STORM_RECUT_SECONDS),
        ("GROW_INTERVAL_SECONDS", module.GROW_INTERVAL_SECONDS),
    ):
        monkeypatch.setattr(module, name, seconds * _SCALE)
    monkeypatch.setattr(
        source_api_limiter,
        "MICROSOFT_GRAPH_BUDGETS",
        {
            api: _scaled(budget)
            for api, budget in source_api_limiter.MICROSOFT_GRAPH_BUDGETS.items()
        },
    )
    connector_budgets = source_api_limiter.microsoft_connector_budgets

    def scaled_connector_budgets(ru_per_minute: int) -> dict[str, SourceApiBudget]:
        return {
            api: _scaled(budget)
            for api, budget in connector_budgets(ru_per_minute).items()
        }

    monkeypatch.setattr(
        source_api_limiter, "microsoft_connector_budgets", scaled_connector_budgets
    )
    tenant = f"tenant_test_{uuid4().hex[:12]}"
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(tenant)
    yield tenant
    CURRENT_TENANT_ID_CONTEXTVAR.reset(token)
    client = get_redis_client(tenant_id=tenant)
    for key in client.scan_iter("*"):
        client.delete(key)


def _limited_connector(
    mock: MockSharepoint,
    stop: threading.Event,
    connector_specific_config: dict[str, Any] | None = None,
) -> SharepointConnector:
    connector = mock.build_connector()
    limiter = build_source_api_limiter(
        DocumentSource.SHAREPOINT,
        credential_id=int(uuid4().int % 1_000_000_000),
        should_stop=stop.is_set,
        load_credential_json=mock.credentials,
        cc_pair_id=int(uuid4().int % 1_000_000_000),
        connector_specific_config=connector_specific_config,
    )
    assert limiter is not None
    connector.set_source_api_limiter(limiter)
    return connector


def _run(
    mock: MockSharepoint, connector: SharepointConnector, stop: threading.Event
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Runs the threads, and returns the server stats at the start and at
    the end of the settled part of the run."""
    ops = connector.ops
    url = f"{ops._base()}/sites/root"
    get_json: Callable[[str], dict[str, Any]] = ops._graph_api().get_json
    errors: list[BaseException] = []

    def caller() -> None:
        while not stop.is_set():
            try:
                get_json(url)
            except ConnectorStopSignal:
                return
            except Exception as error:  # noqa: BLE001 - the test reports it
                errors.append(error)
                return

    threads = [threading.Thread(target=caller, daemon=True) for _ in range(_THREADS)]
    try:
        for thread in threads:
            thread.start()
        stop.wait(_RUN_SECONDS - _SETTLED_SECONDS)
        settled_start = mock.stats()
        stop.wait(_SETTLED_SECONDS)
        settled_end = mock.stats()
    finally:
        stop.set()
        for thread in threads:
            thread.join(timeout=30)
    assert not any(thread.is_alive() for thread in threads)
    assert not errors, errors[0]
    return settled_start, settled_end


def _accepted_ru(stats: dict[str, Any]) -> int:
    """RU of the calls that the server accepted (a throttled call costs 1
    RU here, as a site read does)."""
    return int(sum(stats["ru_by_app"].values())) - int(stats["throttled"])


def test_the_learned_rate_settles_under_the_server_limit(
    own_mock_sharepoint: MockSharepoint,
    fast_limiter: str,  # noqa: ARG001
) -> None:
    mock = own_mock_sharepoint
    # 3,000 RU per minute: 150 RU in each 3-second minute. The limiter's
    # budget starts at 0.2 of 6,250 RU, which is over that limit.
    limit_per_minute = 150
    mock.patch_config(
        {
            "quota": {
                "window_seconds": _MINUTE,
                "ru_per_minute": int(limit_per_minute * 60 / _MINUTE),
                "retry_after_seconds": 1,
                "other_ru": 1,
            },
            "latency": {"enabled": False},
        }
    )
    mock.reset_stats()
    stop = threading.Event()
    connector = _limited_connector(mock, stop)

    start, end = _run(mock, connector, stop)

    requests = end["requests"] - start["requests"]
    throttled = end["throttled"] - start["throttled"]
    accepted_ru = _accepted_ru(end) - _accepted_ru(start)
    summary = (requests, throttled, accepted_ru)
    # Few 429 answers once the rate has settled. The learned rate probes
    # above the limit now and then; a run measured about 4.5 %.
    assert requests > 0, summary
    assert throttled / requests < 0.1, summary
    # The rate stays under the limit, and does not starve.
    settled_minutes = _SETTLED_SECONDS / _MINUTE
    assert accepted_ru <= limit_per_minute * settled_minutes * 1.05, summary
    assert accepted_ru >= limit_per_minute * settled_minutes * 0.4, summary


def test_a_connector_with_a_value_stays_under_it(
    own_mock_sharepoint: MockSharepoint,
    fast_limiter: str,  # noqa: ARG001
) -> None:
    mock = own_mock_sharepoint
    # The server allows far more than the admin's value.
    value = 200
    mock.patch_config(
        {
            "quota": {
                "window_seconds": _MINUTE,
                "ru_per_minute": 100_000,
                "other_ru": 1,
            },
            "latency": {"enabled": False},
        }
    )
    mock.reset_stats()
    stop = threading.Event()
    connector = _limited_connector(
        mock, stop, connector_specific_config={"ru_per_minute": value}
    )

    start, end = _run(mock, connector, stop)

    throttled = end["throttled"] - start["throttled"]
    accepted_ru = _accepted_ru(end) - _accepted_ru(start)
    settled_minutes = _SETTLED_SECONDS / _MINUTE
    summary = (throttled, accepted_ru, value * settled_minutes)
    assert throttled == 0, summary
    assert accepted_ru <= value * settled_minutes * 1.05, summary
    # The value applies from the start: the connector uses most of it.
    assert accepted_ru >= value * settled_minutes * 0.7, summary
