"""Server-requested connector waits: cloud-only cap, logs and counter."""

import io
import json
import logging
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from googleapiclient.errors import HttpError
from httplib2 import Response as HttplibResponse
from prometheus_client import REGISTRY
from slack_sdk.http_retry.request import HttpRequest
from slack_sdk.http_retry.response import HttpResponse
from slack_sdk.http_retry.state import RetryState
from urllib3 import HTTPResponse

from onyx.connectors.cross_connector_utils import server_wait
from onyx.connectors.cross_connector_utils.server_wait import (
    MAX_SERVER_WAIT_SECONDS,
    SERVER_WAIT_CAPPED_LOG_PREFIX,
    SERVER_WAIT_LONG_LOG_PREFIX,
    bound_server_wait,
)
from onyx.connectors.github import connector as github_connector
from onyx.connectors.github import rate_limit_utils as github_rl
from onyx.connectors.github.connector import GithubConnector
from onyx.connectors.github.rate_limit_utils import BoundedGithubRetry
from onyx.connectors.google_utils import google_utils
from onyx.connectors.hubspot.rate_limit import get_rate_limit_retry_delay_seconds
from onyx.connectors.microsoft_utils.graph_client import backoff_seconds
from onyx.connectors.slack import source_operations as slack_ops
from onyx.connectors.slack.source_operations import (
    OnyxRedisSlackRetryHandler,
    OnyxSlackWebClient,
)
from onyx.connectors.zulip import utils as zulip_utils
from onyx.connectors.zulip.utils import ZulipAPIError, call_api

_HUGE_S = 999999999.0
_HUGE = str(int(_HUGE_S))
_FAR_FUTURE = datetime.now(timezone.utc) + timedelta(days=365)


def _count(source: str, wait_class: str) -> float:
    value = REGISTRY.get_sample_value(
        "onyx_connector_long_retry_after_total",
        {"source": source, "wait_class": wait_class},
    )
    return value or 0.0


def _set_cloud(monkeypatch: pytest.MonkeyPatch, cloud: bool) -> None:
    monkeypatch.setattr(server_wait, "MULTI_TENANT", cloud)
    monkeypatch.setattr(zulip_utils, "MULTI_TENANT", cloud)


@pytest.fixture(params=[True, False], ids=["cloud", "self_hosted"])
def cloud(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> bool:
    _set_cloud(monkeypatch, request.param)
    return request.param


def _expected(cloud: bool, requested: float) -> float:
    return min(requested, MAX_SERVER_WAIT_SECONDS) if cloud else requested


@pytest.fixture
def warn_logs(caplog: pytest.LogCaptureFixture) -> Iterator[pytest.LogCaptureFixture]:
    with caplog.at_level(logging.WARNING):
        yield caplog


# --- policy ---------------------------------------------------------------


def test_cap_only_on_cloud_logs_error_and_counts(
    cloud: bool, warn_logs: pytest.LogCaptureFixture
) -> None:
    before = _count("test_src", "capped")
    assert bound_server_wait(_HUGE_S, "test_src") == _expected(cloud, _HUGE_S)
    errors = [r for r in warn_logs.records if r.levelno == logging.ERROR]
    if cloud:
        assert _count("test_src", "capped") == before + 1
        assert len(errors) == 1
        assert errors[0].getMessage().startswith(SERVER_WAIT_CAPPED_LOG_PREFIX)
        assert "source=test_src" in errors[0].getMessage()
        assert "tenant_id=" in errors[0].getMessage()
    else:
        assert _count("test_src", "capped") == before
        assert errors == []


def test_cap_is_uniform_one_day(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_cloud(monkeypatch, True)
    assert MAX_SERVER_WAIT_SECONDS == 86400.0
    assert bound_server_wait(86400.0, "test_src") == 86400.0
    assert bound_server_wait(86401.0, "test_src") == 86400.0


@pytest.mark.parametrize(
    "seconds,wait_class",
    [
        (30.0, None),
        (60.0, None),
        (61.0, "over_1m"),
        (300.0, "over_1m"),
        (301.0, "over_5m"),
    ],
)
def test_long_wait_classes_warn_on_all_deployments(
    cloud: bool,  # noqa: ARG001
    warn_logs: pytest.LogCaptureFixture,
    seconds: float,
    wait_class: str | None,
) -> None:
    before = {c: _count("cls_src", c) for c in ("over_1m", "over_5m", "capped")}
    assert bound_server_wait(seconds, "cls_src") == seconds
    after = {c: _count("cls_src", c) for c in before}
    warnings = [r for r in warn_logs.records if r.levelno == logging.WARNING]
    if wait_class is None:
        assert after == before
        assert warnings == []
    else:
        assert after[wait_class] == before[wait_class] + 1
        assert sum(after.values()) == sum(before.values()) + 1
        assert len(warnings) == 1
        message = warnings[0].getMessage()
        assert message.startswith(SERVER_WAIT_LONG_LOG_PREFIX)
        assert f"class={wait_class}" in message


def test_classify_false_skips_class_but_still_caps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_cloud(monkeypatch, True)
    before = _count("reread_src", "over_5m")
    assert bound_server_wait(_HUGE_S, "reread_src", classify=False) == 86400.0
    assert bound_server_wait(600.0, "reread_src", classify=False) == 600.0
    assert _count("reread_src", "over_5m") == before


@pytest.mark.parametrize("seconds", [-5.0, float("nan")])
def test_invalid_wait_becomes_zero(seconds: float) -> None:
    assert bound_server_wait(seconds, "test_src") == 0.0


# --- call sites -----------------------------------------------------------


def test_github_reset_sleep(cloud: bool) -> None:
    client = MagicMock()
    client.get_rate_limit.return_value.core.reset = _FAR_FUTURE
    before = _count("github", "over_5m")
    with patch.object(github_rl.time, "sleep") as sleep:
        github_rl.sleep_after_rate_limit_exception(client)
    slept = sleep.call_args.args[0]
    if cloud:
        assert slept == MAX_SERVER_WAIT_SECONDS
    else:
        assert slept > 364 * 86400
    assert _count("github", "over_5m") == before + 1


def _github_403(headers: dict[str, str]) -> HTTPResponse:
    body = json.dumps({"message": "API rate limit exceeded for user."}).encode()
    return HTTPResponse(
        body=io.BytesIO(body), status=403, headers=headers, preload_content=False
    )


def test_github_retry_primary_reset_backoff(cloud: bool) -> None:
    response = _github_403(
        {
            "X-RateLimit-Remaining": "0",
            "X-RateLimit-Reset": str(int(_FAR_FUTURE.timestamp())),
        }
    )
    retry = BoundedGithubRetry().increment(method="GET", url="/x", response=response)
    backoff = retry.get_backoff_time()
    if cloud:
        assert backoff == MAX_SERVER_WAIT_SECONDS
    else:
        assert backoff > 364 * 86400


def test_github_retry_after_header_is_classified() -> None:
    before = _count("github", "over_5m")
    assert (
        BoundedGithubRetry().get_retry_after(_github_403({"Retry-After": "600"})) == 600
    )
    assert _count("github", "over_5m") == before + 1


@pytest.mark.parametrize(
    "env_base_url", [None, "https://ghes.example.com/api/v3"], ids=["dotcom", "ghes"]
)
def test_github_client_uses_bounded_retry(
    monkeypatch: pytest.MonkeyPatch, env_base_url: str | None
) -> None:
    monkeypatch.setattr(github_connector, "GITHUB_CONNECTOR_BASE_URL", env_base_url)
    with patch.object(github_connector, "Github") as github_cls:
        connector = GithubConnector(repo_owner="o", repositories="r")
        connector.load_credentials({"github_access_token": "t"})
    assert isinstance(github_cls.call_args.kwargs["retry"], BoundedGithubRetry)


class _HubSpotRateLimitError(Exception):
    def __init__(self, headers: dict[str, str]) -> None:
        super().__init__("Too Many Requests")
        self.headers = headers


def test_hubspot_retry_after(cloud: bool) -> None:
    exc = _HubSpotRateLimitError({"Retry-After": _HUGE})
    # HubSpot adds 1 s of padding to the server value.
    assert get_rate_limit_retry_delay_seconds(exc) == _expected(cloud, _HUGE_S + 1)


def test_graph_retry_after(cloud: bool) -> None:
    assert backoff_seconds(0, _HUGE) == _expected(cloud, _HUGE_S)
    assert backoff_seconds(0, "7") == 7.0


def _zulip_rate_limited(retry_after: str) -> dict[str, str]:
    return {
        "result": "error",
        "code": "RATE_LIMIT_HIT",
        "msg": "slow down",
        "retry-after": retry_after,
    }


def test_zulip_cloud_bounds_retries_and_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_cloud(monkeypatch, True)
    fun = MagicMock(return_value=_zulip_rate_limited(_HUGE))
    with patch.object(zulip_utils.time, "sleep") as sleep:
        with pytest.raises(ZulipAPIError):
            call_api(fun, "a", anchor="newest")
    retries = zulip_utils._MAX_RATE_LIMIT_RETRIES_MULTI_TENANT
    assert sleep.call_count == retries
    assert all(c.args[0] == MAX_SERVER_WAIT_SECONDS for c in sleep.call_args_list)
    assert fun.call_count == retries + 1
    assert all(c.kwargs == {"anchor": "newest"} for c in fun.call_args_list)


def test_zulip_self_hosted_honours_server(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_cloud(monkeypatch, False)
    limited = 20
    fun = MagicMock(
        side_effect=[_zulip_rate_limited(_HUGE)] * limited + [{"result": "success"}]
    )
    with patch.object(zulip_utils.time, "sleep") as sleep:
        assert call_api(fun, x=1) == {"result": "success"}
    assert sleep.call_count == limited
    assert all(c.args[0] == _HUGE_S + 1 for c in sleep.call_args_list)
    assert all(c.kwargs == {"x": 1} for c in fun.call_args_list)


def test_slack_shared_delay_ttl(cloud: bool) -> None:
    redis = MagicMock()
    redis.pttl.return_value = int(MAX_SERVER_WAIT_SECONDS * 1000) - 1
    handler = OnyxRedisSlackRetryHandler(max_retry_count=5, delay_key="d", r=redis)
    with patch.object(slack_ops.random, "random", return_value=0.0):
        handler.prepare_for_next_attempt(
            state=RetryState(),
            request=MagicMock(spec=HttpRequest),
            response=HttpResponse(status_code=429, headers={"Retry-After": [_HUGE]}),
        )
    ttl_ms = redis.set.call_args.kwargs["px"]
    if cloud:
        assert ttl_ms == int(MAX_SERVER_WAIT_SECONDS * 1000)
    else:
        assert ttl_ms == int(MAX_SERVER_WAIT_SECONDS * 1000) - 1 + int(_HUGE_S * 1000)


def test_slack_sleep_on_shared_delay(cloud: bool) -> None:
    redis = MagicMock()
    redis.pttl.return_value = 10**12  # TTL written by another process
    client = OnyxSlackWebClient(delay_lock="l", delay_key="d", r=redis)
    with (
        patch.object(slack_ops.time, "sleep") as sleep,
        patch.object(
            slack_ops.WebClient, "_perform_urllib_http_request_internal"
        ) as parent,
    ):
        parent.return_value = {}
        client._perform_urllib_http_request_internal("https://x", MagicMock())
    sleep.assert_called_once_with(_expected(cloud, 10**9))


def _google_429(message: str) -> HttpError:
    resp = HttplibResponse({"status": "429"})
    resp.reason = "Too Many Requests"
    content = json.dumps(
        {
            "error": {
                "code": 429,
                "message": message,
                "errors": [{"reason": "rateLimitExceeded"}],
            }
        }
    ).encode()
    return HttpError(resp, content)


def test_google_retry_wait(cloud: bool) -> None:
    error = _google_429("Quota exceeded. Retry after 2999-01-01T00:00:00.000Z")
    request = MagicMock()
    request.execute.side_effect = [error, "ok"]
    with patch.object(google_utils.time, "sleep") as sleep:
        assert google_utils._execute_with_retry(request) == "ok"
    slept = sleep.call_args.args[0]
    # Google adds a 3 s buffer after the server value.
    if cloud:
        assert slept == MAX_SERVER_WAIT_SECONDS + 3
    else:
        assert slept > 900 * 365 * 86400
