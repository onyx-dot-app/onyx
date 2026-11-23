"""The Microsoft request pacer: the cost of each call type, the User-Agent,
and what it tells the shared limiter."""

import io
from collections.abc import Iterator
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
from onyx.connectors.microsoft_utils.drive_items import (
    download_via_graph_api,
    download_with_cap,
)
from onyx.connectors.microsoft_utils.graph_client import (
    GraphApiClient,
    sleep_and_retry,
)
from onyx.connectors.microsoft_utils.request_pacer import (
    DOWNLOAD_LIMITER_API,
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
        MicrosoftCall.LINK_DOWNLOAD: 0,
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


class _LaneRecorder(SourceApiLimiter):
    """Records each limiter call with its lane."""

    def __init__(self) -> None:
        self.acquired: list[tuple[str, int]] = []
        self.refused: list[str] = []
        self.paused: list[tuple[str, float]] = []

    @override
    def acquire(
        self,
        api: str,
        cost: int,
        user: str | None = None,  # noqa: ARG002
        request_count: int = 1,  # noqa: ARG002
        *,
        bulk: bool = False,  # noqa: ARG002
    ) -> None:
        self.acquired.append((api, cost))

    @override
    def report_rate_limit(
        self,
        api: str,
        user: str | None,  # noqa: ARG002
        user_scope: bool,  # noqa: ARG002
        count: int = 1,  # noqa: ARG002
    ) -> None:
        self.refused.append(api)

    @override
    def report_retry_after(self, api: str, seconds: float) -> None:
        self.paused.append((api, seconds))


def test_a_link_download_uses_the_download_lane_and_no_graph_ru(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The download host is not Graph. A link fetch takes one turn from the
    download lane, and its 429 pauses and cuts that lane only."""
    limiter = _LaneRecorder()
    answers = iter([_stream_response(429, {"Retry-After": "3"})])
    monkeypatch.setattr(
        "onyx.connectors.microsoft_utils.drive_items.requests.get",
        lambda *_args, **_kwargs: next(answers),
    )

    with pytest.raises(requests.HTTPError):
        download_with_cap(
            "https://host/download.aspx?tempauth=x",
            10,
            1000,
            MicrosoftRequestPacer(limiter),
        )

    assert limiter.acquired == [(DOWNLOAD_LIMITER_API, 1)]
    assert limiter.paused == [(DOWNLOAD_LIMITER_API, 3.0)]
    assert limiter.refused == [DOWNLOAD_LIMITER_API]


def test_the_redirect_of_content_is_a_link_download(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """/content costs 1 Graph RU. Its redirect target is a link download:
    a 429 there pauses the download lane, and the target is tried again."""
    limiter = _LaneRecorder()
    redirect = _stream_response(302, {"Location": "https://host/download.aspx?t=1"})
    answers = iter(
        [
            redirect,
            _stream_response(429, {"Retry-After": "2"}),
            _stream_response(200),
        ]
    )
    requested: list[tuple[str, bool]] = []

    def get(url: str, **kwargs: Any) -> requests.Response:
        requested.append((url, kwargs.get("allow_redirects", True)))
        return next(answers)

    monkeypatch.setattr("onyx.connectors.microsoft_utils.drive_items.requests.get", get)
    monkeypatch.setattr(
        "onyx.connectors.microsoft_utils.drive_items.time.sleep", lambda _s: None
    )

    content = download_via_graph_api(
        lambda: "token", "d", "i", 1000, GRAPH, MicrosoftRequestPacer(limiter)
    )

    assert content == b"content"
    assert requested[0] == (f"{GRAPH}/drives/d/items/i/content", False)
    assert [url for url, _ in requested[1:]] == ["https://host/download.aspx?t=1"] * 2
    assert limiter.acquired == [
        (GRAPH_LIMITER_API, 1),
        (DOWNLOAD_LIMITER_API, 1),
        (DOWNLOAD_LIMITER_API, 1),
    ]
    assert limiter.paused == [(DOWNLOAD_LIMITER_API, 2.0)]
    assert limiter.refused == [DOWNLOAD_LIMITER_API]


def test_an_expired_redirect_target_asks_graph_for_a_new_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A target that expired during a wait answers 401. The download asks
    /content again for a new target, and each request takes its own lane."""
    limiter = _LaneRecorder()
    answers = iter(
        [
            _stream_response(302, {"Location": "https://host/download.aspx?t=1"}),
            _stream_response(401),
            _stream_response(302, {"Location": "https://host/download.aspx?t=2"}),
            _stream_response(200),
        ]
    )
    requested: list[str] = []

    def get(url: str, **_kwargs: Any) -> requests.Response:
        requested.append(url)
        return next(answers)

    monkeypatch.setattr("onyx.connectors.microsoft_utils.drive_items.requests.get", get)

    content = download_via_graph_api(
        lambda: "token", "d", "i", 1000, GRAPH, MicrosoftRequestPacer(limiter)
    )

    assert content == b"content"
    assert requested == [
        f"{GRAPH}/drives/d/items/i/content",
        "https://host/download.aspx?t=1",
        f"{GRAPH}/drives/d/items/i/content",
        "https://host/download.aspx?t=2",
    ]
    assert limiter.acquired == [
        (GRAPH_LIMITER_API, 1),
        (DOWNLOAD_LIMITER_API, 1),
        (GRAPH_LIMITER_API, 1),
        (DOWNLOAD_LIMITER_API, 1),
    ]


def test_a_target_that_keeps_expiring_fails_after_the_refreshes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def answers() -> Iterator[requests.Response]:
        while True:
            yield _stream_response(302, {"Location": "https://host/download.aspx"})
            yield _stream_response(403)

    stream = answers()
    monkeypatch.setattr(
        "onyx.connectors.microsoft_utils.drive_items.requests.get",
        lambda *_args, **_kwargs: next(stream),
    )
    limiter = _LaneRecorder()

    with pytest.raises(requests.HTTPError):
        download_via_graph_api(
            lambda: "token", "d", "i", 1000, GRAPH, MicrosoftRequestPacer(limiter)
        )

    # The first try and two refreshes.
    assert limiter.acquired.count((GRAPH_LIMITER_API, 1)) == 3


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
