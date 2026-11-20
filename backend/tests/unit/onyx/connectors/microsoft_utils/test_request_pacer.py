"""The Microsoft request pacer: the cost of each call type, the User-Agent,
and what it tells the shared limiter."""

import io
from typing import Any
from unittest.mock import MagicMock

import pytest
import requests
from office365.graph_client import GraphClient
from office365.runtime.auth.token_response import TokenResponse
from office365.sharepoint.client_context import ClientContext
from typing_extensions import override

from onyx.connectors.interfaces import SourceApiLimiter
from onyx.connectors.microsoft_utils import graph_client as graph_client_module
from onyx.connectors.microsoft_utils.drive_items import download_via_graph_api
from onyx.connectors.microsoft_utils.graph_client import (
    GraphApiClient,
    sleep_and_retry,
)
from onyx.connectors.microsoft_utils.request_pacer import (
    GRAPH_LIMITER_API,
    MICROSOFT_USER_AGENT,
    RU_COSTS,
    MicrosoftCall,
    MicrosoftRequestPacer,
    graph_call_type,
    prepare_sdk_client,
)

GRAPH = "https://graph.microsoft.com/v1.0"


class _RecordingLimiter(SourceApiLimiter):
    def __init__(self) -> None:
        self.costs: list[int] = []
        self.refusals = 0
        self.pauses: list[float] = []

    @override
    def acquire(
        self,
        api: str,
        cost: int,
        user: str | None = None,
        request_count: int = 1,
        *,
        bulk: bool = False,
    ) -> None:
        assert api == GRAPH_LIMITER_API and user is None and request_count == 1
        self.costs.append(cost)

    @override
    def report_rate_limit(
        self, api: str, user: str | None, user_scope: bool, count: int = 1
    ) -> None:
        assert api == GRAPH_LIMITER_API and user is None and not user_scope
        self.refusals += count

    @override
    def report_retry_after(self, api: str, seconds: float) -> None:
        assert api == GRAPH_LIMITER_API
        self.pauses.append(seconds)


def _response(status: int, headers: dict[str, str] | None = None) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response._content = b'{"value": []}'
    response.headers.update(headers or {})
    return response


def _stream_response(
    status: int, headers: dict[str, str] | None = None
) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response.raw = io.BytesIO(b"content")
    response.headers.update(headers or {})
    return response


@pytest.mark.parametrize(
    ("url", "call"),
    [
        (f"{GRAPH}/drives/d/root/delta?token=latest", MicrosoftCall.DELTA_PAGE),
        (f"{GRAPH}/drives/d/items/i/children?$top=200", MicrosoftCall.CHILDREN_PAGE),
        (f"{GRAPH}/drives/d/root/children", MicrosoftCall.CHILDREN_PAGE),
        (f"{GRAPH}/drives/d/items/i", MicrosoftCall.ITEM_GET),
        (f"{GRAPH}/drives/d/root:/Folder/Sub?$select=id", MicrosoftCall.ITEM_GET),
        (f"{GRAPH}/drives/d/items/i/content", MicrosoftCall.DOWNLOAD),
        (f"{GRAPH}/drives/d/items/i/permissions", MicrosoftCall.PERMISSION),
        (
            f"{GRAPH}/sites/s/pages/p/microsoft.graph.sitePage?$expand=canvasLayout",
            MicrosoftCall.ITEM_GET,
        ),
        (f"{GRAPH}/sites/s/pages/microsoft.graph.sitePage", MicrosoftCall.OTHER),
        (f"{GRAPH}/sites/s/drives", MicrosoftCall.OTHER),
        (f"{GRAPH}/groups/g/members", MicrosoftCall.OTHER),
    ],
)
def test_the_url_gives_the_call_type(url: str, call: MicrosoftCall) -> None:
    assert graph_call_type(url) == call


def test_the_costs_follow_microsofts_table() -> None:
    assert RU_COSTS == {
        MicrosoftCall.ITEM_GET: 1,
        MicrosoftCall.DELTA_PAGE: 1,
        MicrosoftCall.CHILDREN_PAGE: 2,
        MicrosoftCall.DOWNLOAD: 1,
        MicrosoftCall.PERMISSION: 5,
        MicrosoftCall.REST: 5,
        MicrosoftCall.OTHER: 1,
    }


def test_each_try_of_a_graph_get_takes_its_cost_and_a_429_is_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    limiter = _RecordingLimiter()
    answers = iter(
        [
            _response(429, {"Retry-After": "7"}),
            _response(503, {"Retry-After": "3"}),
            _response(503),
            _response(200),
        ]
    )
    sent: list[dict[str, str]] = []

    def _get(*_args: Any, **kwargs: Any) -> requests.Response:
        sent.append(kwargs["headers"])
        return next(answers)

    monkeypatch.setattr(graph_client_module.requests, "get", _get)
    monkeypatch.setattr(graph_client_module.time, "sleep", lambda _seconds: None)
    client = GraphApiClient(
        lambda: "token", GRAPH, lambda: MicrosoftRequestPacer(limiter)
    )

    client.get_json(f"{GRAPH}/drives/d/items/i/children")

    # Four tries of a children page, 2 RU each.
    assert limiter.costs == [2, 2, 2, 2]
    # Only a 429 is a refusal for the rate. A Retry-After pauses on both.
    assert limiter.refusals == 1
    assert limiter.pauses == [7.0, 3.0]
    assert all(headers["User-Agent"] == MICROSOFT_USER_AGENT for headers in sent)


def test_a_client_with_no_pacer_sends_the_user_agent_and_is_not_limited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    get = MagicMock(return_value=_response(200))
    monkeypatch.setattr(graph_client_module.requests, "get", get)

    GraphApiClient(lambda: "token", GRAPH).get_json(f"{GRAPH}/sites/root")

    assert get.call_args.kwargs["headers"]["User-Agent"] == MICROSOFT_USER_AGENT


def test_a_download_takes_one_unit_for_each_try(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    limiter = _RecordingLimiter()
    answers = iter([_stream_response(429, {"Retry-After": "2"}), _stream_response(200)])
    monkeypatch.setattr(
        "onyx.connectors.microsoft_utils.drive_items.requests.get",
        lambda *_args, **_kwargs: next(answers),
    )
    monkeypatch.setattr(
        "onyx.connectors.microsoft_utils.drive_items.time.sleep", lambda _s: None
    )

    content = download_via_graph_api(
        lambda: "token", "d", "i", 1000, GRAPH, MicrosoftRequestPacer(limiter)
    )

    assert content == b"content"
    assert limiter.costs == [1, 1]
    assert (limiter.refusals, limiter.pauses) == (1, [2.0])


def test_an_sdk_client_takes_the_cost_of_each_request_and_reports_a_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    limiter = _RecordingLimiter()
    pacer: MicrosoftRequestPacer | None = None
    answers = iter(
        [
            _response(200),
            _response(429, {"Retry-After": "4"}),
            _response(200),
        ]
    )
    sent: list[dict[str, str]] = []

    def _get(**kwargs: Any) -> requests.Response:
        sent.append(dict(kwargs["headers"]))
        return next(answers)

    monkeypatch.setattr("office365.runtime.client_request.requests.get", _get)
    monkeypatch.setattr(graph_client_module.time, "sleep", lambda _seconds: None)
    client = prepare_sdk_client(
        GraphClient(lambda: {"token_type": "Bearer", "access_token": "token"}),
        lambda: pacer,
    )

    # The limiter comes after the credentials: the first request has none.
    sleep_and_retry(client.sites.root.get(), "get_root_site")
    assert limiter.costs == []
    assert sent[0]["User-Agent"] == MICROSOFT_USER_AGENT

    pacer = MicrosoftRequestPacer(limiter)
    sleep_and_retry(
        client.sites.root.get(),
        "get_root_site",
        rebuild=lambda: client.sites.root.get(),
    )

    assert limiter.costs == [1, 1]
    assert (limiter.refusals, limiter.pauses) == (1, [4.0])


def test_every_request_of_a_rest_context_costs_a_rest_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    limiter = _RecordingLimiter()
    monkeypatch.setattr(
        "office365.runtime.client_request.requests.get",
        lambda **_kwargs: _response(200),
    )
    context = prepare_sdk_client(
        ClientContext("https://tenant.sharepoint.com/sites/a").with_access_token(
            lambda: TokenResponse(access_token="token", token_type="Bearer")
        ),
        lambda: MicrosoftRequestPacer(limiter),
        MicrosoftCall.REST,
    )

    sleep_and_retry(context.web.role_assignments.get(), "list_role_assignments")

    assert limiter.costs == [RU_COSTS[MicrosoftCall.REST]]
