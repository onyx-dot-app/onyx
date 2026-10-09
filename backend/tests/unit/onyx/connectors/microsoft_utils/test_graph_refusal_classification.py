"""The classifier SharePoint, Teams and Outlook share to decide whether Graph
refused one entity for good (record it, move on). Anything else is the
caller's call."""

from __future__ import annotations

import pytest
import requests
from office365.runtime.client_request_exception import ClientRequestException
from requests import Response
from requests.exceptions import HTTPError

from onyx.connectors.microsoft_utils.graph_client import (
    is_permanent_refusal,
    is_permanent_refusal_status,
)

# 410 is here on purpose: Graph answers it for an expired delta or page token.
NON_PERMANENT_STATUSES = [400, 401, 410, 429, 500, 502, 503, 504]


def _response(status_code: int) -> Response:
    response = Response()
    response.status_code = status_code
    return response


def _http_error(status_code: int) -> HTTPError:
    return HTTPError(response=_response(status_code))


def _sdk_error(status_code: int) -> ClientRequestException:
    return ClientRequestException(
        f"{status_code} Client Error", response=_response(status_code)
    )


def _verdicts(status_code: int) -> set[bool]:
    """The status form, the raw GET's error and the SDK's error must agree."""
    return {
        is_permanent_refusal_status(status_code),
        is_permanent_refusal(_http_error(status_code)),
        is_permanent_refusal(_sdk_error(status_code)),
    }


@pytest.mark.parametrize("status_code", [403, 404, 423])
def test_no_grant_gone_and_locked_are_permanent(status_code: int) -> None:
    assert _verdicts(status_code) == {True}


@pytest.mark.parametrize("status_code", NON_PERMANENT_STATUSES)
def test_other_statuses_are_not_a_permanent_refusal(status_code: int) -> None:
    assert _verdicts(status_code) == {False}


def test_response_less_error_is_not_a_permanent_refusal() -> None:
    # response=None is transport, whichever layer produced it, never a refusal.
    error = _sdk_error(404)
    error.response = None
    assert is_permanent_refusal(error) is False
    assert is_permanent_refusal(requests.ConnectionError()) is False
    assert is_permanent_refusal_status(None) is False
