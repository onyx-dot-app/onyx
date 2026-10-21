"""The SharePoint gateway's SDK reads back off on Graph throttling: 429 and
503 are retried, Retry-After is honoured, other refusals are not retried, and
exhausted retries raise MicrosoftGraphError with the throttle status."""

import json
from unittest.mock import MagicMock

import pytest
import requests
from office365.runtime.client_request_exception import ClientRequestException

from onyx.connectors.microsoft_utils import graph_client as graph_client_module
from onyx.connectors.microsoft_utils.graph_client import GRAPH_API_MAX_RETRIES
from onyx.connectors.microsoft_utils.graph_errors import MicrosoftGraphError
from tests.unit.onyx.connectors.sharepoint.sharepoint_gateway_fakes import (
    fake_gateway,
)

SITE_URL = "https://tenant.sharepoint.com/sites/eng"
SITE_ID = "tenant.sharepoint.com,abc,def"


def _sdk_error(
    status: int, code: str, retry_after: str | None = None
) -> ClientRequestException:
    response = requests.Response()
    response.status_code = status
    response.headers["Content-Type"] = "application/json"
    if retry_after is not None:
        response.headers["Retry-After"] = retry_after
    response._content = json.dumps({"error": {"code": code, "message": "m"}}).encode()
    return ClientRequestException(f"{status} Client Error", response=response)


@pytest.fixture
def sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    recorded: list[float] = []
    monkeypatch.setattr(graph_client_module.time, "sleep", recorded.append)
    return recorded


def _site_client(answers: list[object]) -> MagicMock:
    """An SDK client whose site read answers each attempt in turn: an
    exception raises, anything else is the site."""
    sdk = MagicMock()
    site = sdk.sites.get_by_url.return_value
    site.id = SITE_ID
    site.execute_query.side_effect = [
        answer if isinstance(answer, Exception) else site for answer in answers
    ]
    return sdk


def _drives_client(answers: list[object]) -> MagicMock:
    sdk = MagicMock()
    query = sdk.sites.get_by_url.return_value.drives.select.return_value.expand.return_value.get_all.return_value
    query.execute_query.side_effect = answers
    return sdk


def test_429_waits_for_retry_after_then_succeeds(sleeps: list[float]) -> None:
    sdk = _drives_client([_sdk_error(429, "activityLimitReached", "7"), []])

    assert fake_gateway(sdk_client=sdk).list_drives(site_url=SITE_URL) == []

    assert sleeps == [7.0]
    assert sdk.sites.get_by_url.call_count == 2


def test_503_backs_off_then_succeeds(sleeps: list[float]) -> None:
    sdk = _site_client([_sdk_error(503, "serviceNotAvailable"), "ok"])

    assert fake_gateway(sdk_client=sdk).get_site_id(site_url=SITE_URL) == SITE_ID

    assert len(sleeps) == 1
    # No Retry-After: the first back-off is drawn from [2.5s, 5s].
    assert 2.5 <= sleeps[0] <= 5.0


def test_exhausted_retries_raise_the_throttle(sleeps: list[float]) -> None:
    attempts = GRAPH_API_MAX_RETRIES + 1
    sdk = _site_client([_sdk_error(429, "activityLimitReached", "1")] * attempts)

    with pytest.raises(MicrosoftGraphError) as raised:
        fake_gateway(sdk_client=sdk).get_site_id(site_url=SITE_URL)

    assert raised.value.status == 429
    assert raised.value.is_throttled
    assert raised.value.fails_the_attempt
    assert sleeps == [1.0] * GRAPH_API_MAX_RETRIES
    assert sdk.sites.get_by_url.call_count == attempts


@pytest.mark.parametrize(
    ("status", "code"), [(403, "accessDenied"), (404, "itemNotFound")]
)
def test_other_refusals_are_not_retried(
    sleeps: list[float], status: int, code: str
) -> None:
    sdk = _drives_client([_sdk_error(status, code)])

    with pytest.raises(MicrosoftGraphError) as raised:
        fake_gateway(sdk_client=sdk).list_drives(site_url=SITE_URL)

    assert raised.value.status == status
    assert not raised.value.is_throttled
    assert sleeps == []
    assert sdk.sites.get_by_url.call_count == 1


def test_site_listing_retries_a_throttled_next_page(sleeps: list[float]) -> None:
    second_page = MagicMock(has_next=False)
    second_page.current_page = [MagicMock(web_url="https://tenant/sites/b")]
    first_page = MagicMock(has_next=True)
    first_page.current_page = [MagicMock(web_url="https://tenant/sites/a")]
    first_page._get_next.return_value.execute_query.side_effect = [
        _sdk_error(429, "activityLimitReached", "2"),
        second_page,
    ]
    sdk = MagicMock()
    sdk.sites.get_all_sites.return_value.execute_query.return_value = first_page

    listing = fake_gateway(sdk_client=sdk).list_site_urls()

    assert listing.site_urls == ["https://tenant/sites/a", "https://tenant/sites/b"]
    assert listing.complete
    assert sleeps == [2.0]
