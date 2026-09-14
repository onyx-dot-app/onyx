"""Tests for the Graph error detail the Teams connector attaches to failures.

A failed Graph call records `requests`' `HTTPError`, whose message carries only
the status line. Graph puts the actionable part -- `error.code` and
`error.message` -- in the response body, and an operator needs it to tell a 401
from a 403 from a 404. These cover extracting that detail and logging it at the
point the request fails.
"""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from requests.exceptions import HTTPError

from onyx.connectors.teams.utils import _retry, describe_graph_error


def _response(
    status_code: int,
    json_value: Any = None,
    text: str = "",
    ok: bool = False,
) -> MagicMock:
    response = MagicMock()
    response.ok = ok
    response.status_code = status_code
    response.headers = {}
    response.text = text
    if json_value is None:
        response.json = MagicMock(side_effect=ValueError("not json"))
    else:
        response.json = MagicMock(return_value=json_value)
    response.raise_for_status = MagicMock(side_effect=HTTPError(f"{status_code} error"))
    return response


def _http_error(response: MagicMock) -> HTTPError:
    error = HTTPError("boom")
    error.response = response
    return error


def test_describe_graph_error_includes_status_code_and_graph_error() -> None:
    response = _response(
        status_code=403,
        json_value={
            "error": {"code": "Forbidden", "message": "Missing ChannelMessage.Read.All"}
        },
    )

    described = describe_graph_error(_http_error(response))

    assert "403" in described
    assert "Forbidden" in described
    assert "Missing ChannelMessage.Read.All" in described


@pytest.mark.parametrize("status", [401, 404, 429])
def test_describe_graph_error_reports_status_for_each_remedy(status: int) -> None:
    # The whole point is telling these apart; each has a different remedy.
    response = _response(
        status_code=status, json_value={"error": {"code": f"Code{status}"}}
    )

    assert str(status) in describe_graph_error(_http_error(response))


def test_describe_graph_error_falls_back_to_body_when_not_a_graph_envelope() -> None:
    response = _response(status_code=500, text="upstream gateway exploded")

    described = describe_graph_error(_http_error(response))

    assert "500" in described
    assert "upstream gateway exploded" in described


def test_describe_graph_error_truncates_a_huge_body() -> None:
    response = _response(status_code=500, text="x" * 10_000)

    assert len(describe_graph_error(_http_error(response))) < 1_000


def test_describe_graph_error_without_a_response() -> None:
    # Not every failure is an HTTP error; the description must still say something.
    described = describe_graph_error(ValueError("no response here"))

    assert "ValueError" in described
    assert "no response here" in described


def test_retry_logs_status_and_graph_error_before_raising() -> None:
    # Defect: the exception is caught and recorded upstream without ever being
    # logged, so the status code appears in no log at any level.
    response = _response(
        status_code=403,
        json_value={"error": {"code": "Forbidden", "message": "Missing scope"}},
    )
    graph_client = MagicMock()
    graph_client.execute_request_direct = MagicMock(return_value=response)

    with patch("onyx.connectors.teams.utils.logger") as mock_logger:
        with pytest.raises(HTTPError):
            _retry(graph_client=graph_client, request_url="teams/t/channels/c/messages")

    assert mock_logger.error.call_count == 1
    logged = str(mock_logger.error.call_args)
    assert "403" in logged
    assert "Forbidden" in logged
    assert "teams/t/channels/c/messages" in logged
