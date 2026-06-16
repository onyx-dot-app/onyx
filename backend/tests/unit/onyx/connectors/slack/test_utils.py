from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from slack_sdk.errors import SlackApiError

from onyx.connectors.slack.utils import make_paginated_slack_api_call


def _slack_error(
    error: str,
    status_code: int = 200,
    retry_after: str | list[str] | None = "0",
) -> SlackApiError:
    response = MagicMock()
    response.status_code = status_code
    response.headers = {} if retry_after is None else {"Retry-After": retry_after}
    response.get.side_effect = lambda key, default=None: {"error": error}.get(
        key, default
    )
    return SlackApiError(error, response)


def _rate_limited_error(
    retry_after: str | list[str] | None = "0",
) -> SlackApiError:
    return _slack_error("ratelimited", retry_after=retry_after)


class _SlackResponse(dict[str, Any]):
    def __init__(
        self,
        payload: dict[str, Any] | None = None,
        error: SlackApiError | None = None,
    ) -> None:
        super().__init__(payload or {})
        self.error = error

    def validate(self) -> "_SlackResponse":
        if self.error:
            raise self.error
        return self


def test_make_paginated_slack_api_call_retries_validation_rate_limits() -> None:
    response_payload = {"ok": True, "response_metadata": {"next_cursor": ""}}
    call = MagicMock(
        side_effect=[
            _SlackResponse(error=_rate_limited_error()),
            _SlackResponse(payload=response_payload),
        ]
    )

    with patch("onyx.connectors.slack.utils.time.sleep") as mock_sleep:
        responses = list(make_paginated_slack_api_call(call, channel="C1"))

    assert responses == [response_payload]
    assert call.call_count == 2
    assert call.call_args_list[0].kwargs == {
        "channel": "C1",
        "cursor": None,
        "limit": 900,
    }
    mock_sleep.assert_called_once_with(0.0)


def test_make_paginated_slack_api_call_retries_api_call_rate_limits() -> None:
    response_payload = {"ok": True, "response_metadata": {"next_cursor": ""}}
    call = MagicMock(
        side_effect=[
            _rate_limited_error(),
            _SlackResponse(payload=response_payload),
        ]
    )

    with patch("onyx.connectors.slack.utils.time.sleep") as mock_sleep:
        responses = list(make_paginated_slack_api_call(call, channel="C1"))

    assert responses == [response_payload]
    assert call.call_count == 2
    mock_sleep.assert_called_once_with(0.0)


def test_make_paginated_slack_api_call_does_not_retry_http_429() -> None:
    error = _slack_error("ratelimited", status_code=429)
    call = MagicMock(return_value=_SlackResponse(error=error))

    with patch("onyx.connectors.slack.utils.time.sleep") as mock_sleep:
        with pytest.raises(SlackApiError) as exc_info:
            list(make_paginated_slack_api_call(call, channel="C1"))

    assert exc_info.value is error
    call.assert_called_once_with(channel="C1", cursor=None, limit=900)
    mock_sleep.assert_not_called()


def test_make_paginated_slack_api_call_does_not_retry_non_rate_limit_errors() -> None:
    error = _slack_error("invalid_auth")
    call = MagicMock(return_value=_SlackResponse(error=error))

    with patch("onyx.connectors.slack.utils.time.sleep") as mock_sleep:
        with pytest.raises(SlackApiError) as exc_info:
            list(make_paginated_slack_api_call(call, channel="C1"))

    assert exc_info.value is error
    call.assert_called_once_with(channel="C1", cursor=None, limit=900)
    mock_sleep.assert_not_called()


def test_make_paginated_slack_api_call_exhausts_rate_limit_retries() -> None:
    error = _rate_limited_error()
    call = MagicMock(return_value=_SlackResponse(error=error))

    with patch("onyx.connectors.slack.utils.time.sleep") as mock_sleep:
        with pytest.raises(SlackApiError) as exc_info:
            list(make_paginated_slack_api_call(call, channel="C1"))

    assert exc_info.value is error
    assert call.call_count == 8
    assert mock_sleep.call_count == 7


def test_make_paginated_slack_api_call_parses_retry_after_headers() -> None:
    response_payload = {"ok": True, "response_metadata": {"next_cursor": ""}}
    call = MagicMock(
        side_effect=[
            _SlackResponse(error=_rate_limited_error(retry_after=["1.5"])),
            _SlackResponse(error=_rate_limited_error(retry_after="bad-value")),
            _SlackResponse(payload=response_payload),
        ]
    )

    with patch("onyx.connectors.slack.utils.time.sleep") as mock_sleep:
        responses = list(make_paginated_slack_api_call(call, channel="C1"))

    assert responses == [response_payload]
    assert [call_args.args[0] for call_args in mock_sleep.call_args_list] == [1.5, 5.0]


def test_make_paginated_slack_api_call_retries_current_cursor_page() -> None:
    page_one = {"ok": True, "response_metadata": {"next_cursor": "cursor-2"}}
    page_two = {"ok": True, "response_metadata": {"next_cursor": ""}}
    call = MagicMock(
        side_effect=[
            _SlackResponse(payload=page_one),
            _SlackResponse(error=_rate_limited_error()),
            _SlackResponse(payload=page_two),
        ]
    )

    with patch("onyx.connectors.slack.utils.time.sleep"):
        responses = list(make_paginated_slack_api_call(call, channel="C1"))

    assert responses == [page_one, page_two]
    assert call.call_args_list[0].kwargs["cursor"] is None
    assert call.call_args_list[1].kwargs["cursor"] == "cursor-2"
    assert call.call_args_list[2].kwargs["cursor"] == "cursor-2"
