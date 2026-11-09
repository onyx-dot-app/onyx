"""Web connector validation classifies HTTP failures by status code, even when
the URL itself contains digits that look like a status code."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    UnexpectedValidationError,
)
from onyx.connectors.web import connector as web_connector
from onyx.connectors.web.config import WEB_CONNECTOR_VALID_SETTINGS
from onyx.connectors.web.connector import WebConnector

# Port and path hold 401, 403 and 404.
TEST_URL = "https://example.com:33403/docs/401/404"


def _validate_with_status(status_code: int) -> None:
    response = requests.Response()
    response.status_code = status_code
    response.url = TEST_URL
    session = MagicMock()
    session.get.return_value = response

    connector = WebConnector(
        base_url=TEST_URL,
        web_connector_type=WEB_CONNECTOR_VALID_SETTINGS.SINGLE.value,
    )
    with (
        patch.object(web_connector, "protected_url_check"),
        patch.object(web_connector.requests, "Session", return_value=session),
    ):
        connector.validate_connector_settings()


@pytest.mark.parametrize(
    ("status_code", "expected_error"),
    [
        (500, UnexpectedValidationError),
        (401, CredentialExpiredError),
        (404, ConnectorValidationError),
    ],
)
def test_validation_error_follows_status_code(
    status_code: int, expected_error: type[Exception]
) -> None:
    with pytest.raises(expected_error) as exc_info:
        _validate_with_status(status_code)
    assert type(exc_info.value) is expected_error


def test_validation_passes_on_403() -> None:
    # 403 is usually bot detection; indexing retries it with Playwright.
    _validate_with_status(403)
