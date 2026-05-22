import pytest
from mitmproxy import http

from onyx.sandbox_proxy.action_matcher import ACTION_TYPE_SLACK_POST_MESSAGE
from onyx.sandbox_proxy.action_matcher import ActionMatch
from onyx.sandbox_proxy.action_matcher import SlackPostMessageMatcher


def _make_request(
    *,
    method: str = "POST",
    url: str = "https://slack.com/api/chat.postMessage",
    content: bytes = b"",
    headers: dict[str | bytes, str | bytes] | None = None,
) -> http.Request:
    return http.Request.make(method, url, content=content, headers=headers or {})


def test_happy_path_json() -> None:
    request = _make_request(
        content=b'{"channel": "#test", "text": "hi"}',
        headers={"content-type": "application/json"},
    )

    match = SlackPostMessageMatcher().match(request)

    assert match == ActionMatch(
        action_type=ACTION_TYPE_SLACK_POST_MESSAGE,
        payload={"channel": "#test", "text": "hi"},
    )


def test_happy_path_urlencoded() -> None:
    request = _make_request(
        content=b"channel=%23test&text=hi",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )

    match = SlackPostMessageMatcher().match(request)

    assert match == ActionMatch(
        action_type=ACTION_TYPE_SLACK_POST_MESSAGE,
        payload={"channel": "#test", "text": "hi"},
    )


@pytest.mark.parametrize(
    "url,override_host",
    [
        ("https://foo.slack.com/api/chat.postMessage", None),
        ("https://slack.com./api/chat.postMessage", None),
        # mitmproxy lowercases hosts on URL construction, so override
        # the attribute directly to exercise the matcher's case folding.
        ("https://slack.com/api/chat.postMessage", "SLACK.COM"),
        ("https://slack.com/API/chat.postMessage", None),
    ],
    ids=["subdomain", "trailing_dot", "case_host", "case_path"],
)
def test_host_path_normalization_is_lenient(
    url: str, override_host: str | None
) -> None:
    request = _make_request(
        url=url,
        content=b'{"channel": "#x", "text": "y"}',
        headers={"content-type": "application/json"},
    )
    if override_host is not None:
        request.host = override_host

    match = SlackPostMessageMatcher().match(request)

    assert match is not None
    assert match.action_type == ACTION_TYPE_SLACK_POST_MESSAGE


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/api/chat.postMessage",
        "https://notslack.com/api/chat.postMessage",
    ],
    ids=["non_slack", "slack_lookalike"],
)
def test_non_slack_host_returns_none(url: str) -> None:
    request = _make_request(
        url=url,
        content=b'{"channel": "#x", "text": "y"}',
        headers={"content-type": "application/json"},
    )

    assert SlackPostMessageMatcher().match(request) is None


def test_wrong_method_returns_none() -> None:
    request = _make_request(method="GET")

    assert SlackPostMessageMatcher().match(request) is None


def test_wrong_path_returns_none() -> None:
    request = _make_request(
        url="https://slack.com/api/conversations.list",
        content=b'{"foo": "bar"}',
        headers={"content-type": "application/json"},
    )

    assert SlackPostMessageMatcher().match(request) is None


@pytest.mark.parametrize(
    "content,headers",
    [
        (b"not-json{", {"content-type": "application/json"}),
        (b'{"channel": "#x", "text": "y"}', None),
        (b"[1, 2, 3]", {"content-type": "application/json"}),
    ],
    ids=["unparseable_json", "missing_content_type", "json_non_dict"],
)
def test_unparseable_body_gates_with_empty_payload(
    content: bytes, headers: dict[str | bytes, str | bytes] | None
) -> None:
    request = _make_request(content=content, headers=headers)

    match = SlackPostMessageMatcher().match(request)

    assert match == ActionMatch(
        action_type=ACTION_TYPE_SLACK_POST_MESSAGE,
        payload={},
    )
