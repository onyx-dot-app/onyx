import logging
from unittest.mock import MagicMock

import pytest
from office365.runtime.client_request import (  # type: ignore[import-untyped]
    ClientRequestException,
)

from onyx.connectors.sharepoint.connector import sleep_and_retry


def _make_query_raising(status_code: int) -> MagicMock:
    query = MagicMock()
    response = MagicMock()
    response.status_code = status_code
    response.headers = {"Content-Type": "text/plain"}
    response.content = b""
    err = ClientRequestException(response=response)
    query.execute_query.side_effect = err
    return query


def test_sleep_and_retry_logs_404_at_warning(caplog: pytest.LogCaptureFixture) -> None:
    """404 on a non-retryable call should log at WARNING level (not ERROR) so
    Sentry doesn't flag deleted-resource cases that callers routinely handle."""
    query = _make_query_raising(404)

    with caplog.at_level(logging.WARNING):
        with pytest.raises(ClientRequestException):
            sleep_and_retry(query, "get_azuread_groups", max_retries=0)

    records = [
        r for r in caplog.records if "SharePoint request failed" in r.getMessage()
    ]
    assert records, "expected a 'SharePoint request failed' log record"
    assert all(r.levelno == logging.WARNING for r in records)


def test_sleep_and_retry_logs_non_404_at_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Non-404 non-retryable failures should still log at ERROR level."""
    query = _make_query_raising(500)

    with caplog.at_level(logging.WARNING):
        with pytest.raises(ClientRequestException):
            sleep_and_retry(query, "get_azuread_groups", max_retries=0)

    records = [
        r for r in caplog.records if "SharePoint request failed" in r.getMessage()
    ]
    assert records
    assert all(r.levelno == logging.ERROR for r in records)
